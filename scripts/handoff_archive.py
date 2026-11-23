"""Save the two public handoffs per arm or replay their recorded actions offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from horizon_bench.env.annual_handoff import MODES
from horizon_bench.runner import replay
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store


def check_design(spec: RunSpec) -> None:
    if (spec.family, spec.policy, spec.tools, spec.split) != ("annual_handoff", "llm", "rich", "dev"):
        raise ValueError(f"unexpected run in {spec.run_id}")
    if spec.horizon != 12 or spec.session_len != 12 or spec.seed != spec.seed_index:
        raise ValueError(f"step budget or seed changed for {spec.run_id}")
    fixed = {"model": "qwen3:8b", "base_url": "http://127.0.0.1:11434/v1", "temperature": 0,
             "max_steps": 12, "max_tokens_per_call": 384, "max_total_tokens": 16000,
             "context_budget_tokens": 8000, "wall_time_s": 240, "no_think": True}
    differs = [key for key, value in fixed.items() if (spec.llm or {}).get(key) != value]
    if differs:
        raise ValueError(f"model or budget changed for {spec.run_id}: {differs}")


def check(archive: Path) -> None:
    seen = set()
    store = Store(":memory:")
    for path in sorted(archive.glob("*.json")):
        raw = json.loads(path.read_text())
        spec = RunSpec.model_validate(raw["spec"])
        check_design(spec)
        if not any(r["llm_call"] and r["prompt_tokens"] > 0 for r in raw["steps"]):
            raise ValueError(f"missing recorded model usage in {path}")
        mode, = spec.variants
        cell = (mode, spec.seed)
        if cell in seen:
            raise ValueError(f"repeated case {cell}")
        seen.add(cell)
        store.create_run(spec)
        for record in raw["steps"]:
            store.save_step(spec.run_id, record, {})
        store.finish_run(spec.run_id, raw["verdict"])
        result = replay(store, spec.run_id)
        if not result["ok"]:
            raise ValueError(f"{path}: {result}")
        print(f"{path.name}: replay OK, original task success={raw['verdict']['success']}")
    expected = {(mode, seed) for mode in MODES for seed in (0, 1)}
    if seen != expected:
        raise ValueError(f"expected the complete matrix, got {sorted(seen)}")


def dump(db: Path, archive: Path, batches: list[str]) -> None:
    if not db.is_file():
        raise ValueError(f"run database does not exist: {db}")
    store = Store(db)
    archive.mkdir(parents=True, exist_ok=False)
    for spec, verdict in store.runs(batches):
        if spec.policy != "llm":
            continue
        mode, = spec.variants
        if spec.family != "annual_handoff" or mode not in MODES or spec.split != "dev" or spec.seed not in (0, 1):
            raise ValueError(f"unexpected run in {spec.batch}")
        path = archive / f"{mode}-dev{spec.seed}.json"
        payload = {"spec": spec.model_dump(), "steps": store.records(spec.run_id), "verdict": verdict}
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    check(archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    save = actions.add_parser("dump")
    save.add_argument("db", type=Path)
    save.add_argument("archive", type=Path)
    save.add_argument("batches", nargs="+")
    offline = actions.add_parser("check")
    offline.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.action == "dump":
        dump(args.db, args.archive, args.batches)
    else:
        check(args.archive)
