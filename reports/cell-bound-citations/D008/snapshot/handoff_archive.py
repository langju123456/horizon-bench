"""Save the two public handoffs per arm or replay their recorded actions offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from horizon_bench.env.annual_handoff import MODES
from horizon_bench.runner import replay
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store

SUBMISSIONS = ("auto", "fields", "reminder", "task_tools")
D006_SUBMISSIONS = ("fields", "evidence")
D007_SUBMISSIONS = ("fields", "grounded")
D008_SUBMISSIONS = ("fields", "grounded")


def check_design(spec: RunSpec, study: str) -> None:
    if (spec.family, spec.policy, spec.tools, spec.split) != ("annual_handoff", "llm", "rich", "dev"):
        raise ValueError(f"unexpected run in {spec.run_id}")
    seed_offset = 2 if study in ("D005", "D006", "D007") and spec.batch.endswith("-transfer") else 0
    if study == "D008" and spec.batch.endswith("-holdout"):
        seed_offset = 4
    if spec.horizon != 12 or spec.session_len != 12 or spec.seed != spec.seed_index + seed_offset:
        raise ValueError(f"step budget or seed changed for {spec.run_id}")
    fixed = {"model": "qwen3:8b", "base_url": "http://127.0.0.1:11434/v1", "temperature": 0,
             "max_steps": 12, "max_tokens_per_call": 384, "max_total_tokens": 16000,
             "context_budget_tokens": 8000, "wall_time_s": 240, "no_think": True}
    differs = [key for key, value in fixed.items() if (spec.llm or {}).get(key) != value]
    if differs:
        raise ValueError(f"model or budget changed for {spec.run_id}: {differs}")


def arm(spec: RunSpec, study: str) -> str:
    check_design(spec, study)
    mode, = spec.variants
    view = (spec.llm or {}).get("tool_observation", "escaped")
    submission = (spec.llm or {}).get("submission", "auto")
    if (study == "D005" and mode == "handoff_full" and view == "unicode" and submission in SUBMISSIONS
            and spec.batch in ("D005-catl", "D005-transfer") and spec.seed_index in (0, 1)):
        return str(submission)
    d006_batches = ("D006-fields-catl", "D006-fields-transfer", "D006-evidence-catl", "D006-evidence-transfer")
    if (study == "D006" and mode == "handoff_full" and view == "unicode" and submission in D006_SUBMISSIONS
            and spec.batch in d006_batches
            and spec.seed_index in (0, 1)):
        return str(submission)
    if (study == "D007" and mode == "handoff_full" and view == "unicode" and submission in D007_SUBMISSIONS
            and spec.batch in (f"D007-{submission}-catl", f"D007-{submission}-transfer")
            and spec.seed_index in (0, 1)):
        return str(submission)
    if (study == "D008" and mode == "handoff_full" and view == "unicode" and submission in D008_SUBMISSIONS
            and spec.batch in (f"D008-{submission}-holdout",) and spec.seed_index in (0, 1)):
        return str(submission)
    if submission != "auto":
        raise ValueError(f"unexpected submission strategy for {study}")
    if study == "D002" and view == "escaped" and mode in MODES:
        return mode
    if study == "D003" and mode == "handoff_full" and view in ("escaped", "unicode", "business"):
        return str(view)
    raise ValueError(f"wrong arm for {study}: {mode}, {view}")


def check(archive: Path, study: str, reports_dir: Path | None = None) -> None:
    if study == "D008":
        root = Path(__file__).resolve().parents[1]
        freeze = json.loads((root / "reports/cell-bound-citations/D008/freeze.json").read_text())
        for relative, expected in freeze.items():
            if relative == "source_pdf_sha256":
                continue  # The public PDF is not committed; its digest remains in the frozen protocol.
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"D008 freeze mismatch: {relative}")
    seen = set()
    batches = set()
    store = Store(":memory:")
    for path in sorted(archive.glob("*.json")):
        raw = json.loads(path.read_text())
        spec = RunSpec.model_validate(raw["spec"])
        batches.add(spec.batch)
        label = arm(spec, study)
        if not any(r["llm_call"] and r["prompt_tokens"] > 0 for r in raw["steps"]):
            raise ValueError(f"missing recorded model usage in {path}")
        cell = (label, spec.seed)
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
    labels = {"D002": MODES, "D003": ("escaped", "unicode", "business"), "D005": SUBMISSIONS,
              "D006": D006_SUBMISSIONS, "D007": D007_SUBMISSIONS, "D008": D008_SUBMISSIONS}[study]
    seeds = range(4) if study in ("D005", "D006", "D007") else range(2)
    if study == "D008":
        seeds = range(4, 6)
    expected = {(label, seed) for label in labels for seed in seeds}
    if seen != expected:
        raise ValueError(f"expected the complete matrix, got {sorted(seen)}")
    if reports_dir is not None:
        from horizon_bench.report import build_report

        print(build_report(store, sorted(batches), study, reports_dir) / "review.html")


def dump(db: Path, archive: Path, batches: list[str], study: str) -> None:
    if not db.is_file():
        raise ValueError(f"run database does not exist: {db}")
    store = Store(db)
    archive.mkdir(parents=True, exist_ok=False)
    for spec, verdict in store.runs(batches):
        if spec.policy != "llm":
            continue
        if study == "D003" and spec.batch == "D002" and spec.variants != ["handoff_full"]:
            continue  # D003 reuses the two full-history baseline episodes already run for D002.
        label = arm(spec, study)
        valid_seeds = range(4) if study in ("D005", "D006", "D007") else range(2)
        if study == "D008":
            valid_seeds = range(4, 6)
        if spec.seed not in valid_seeds:
            raise ValueError(f"unexpected run in {spec.batch}")
        path = archive / f"{label}-dev{spec.seed}.json"
        payload = {"spec": spec.model_dump(), "steps": store.records(spec.run_id), "verdict": verdict}
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    check(archive, study)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    save = actions.add_parser("dump")
    save.add_argument("db", type=Path)
    save.add_argument("archive", type=Path)
    save.add_argument("batches", nargs="+")
    offline = actions.add_parser("check")
    offline.add_argument("archive", type=Path)
    offline.add_argument("--reports-dir", type=Path, help="also write a read-only review of the archived runs")
    for sub in (save, offline):
        sub.add_argument("--study", choices=["D002", "D003", "D005", "D006", "D007", "D008"], default="D002")
    args = parser.parse_args()
    if args.action == "dump":
        dump(args.db, args.archive, args.batches, args.study)
    else:
        check(args.archive, args.study, args.reports_dir)
