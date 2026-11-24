"""Audit frozen D007 inputs and summarize its first recorded outcomes offline."""
import hashlib
import json
from pathlib import Path

from horizon_bench.agents.citation_support import bind_support


def main():
    root = Path(__file__).resolve().parents[1]
    base = root / "reports/cell-bound-citations"
    for path, digest in json.loads((base / "freeze.json").read_text()).items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
    rows = {}
    for path in sorted((base / "traces").glob("*.json")):
        raw = json.loads(path.read_text())
        spec, verdict = raw["spec"], raw["verdict"]
        arm, seed = spec["llm"]["submission"], spec["seed"]
        assert (arm, seed) not in rows
        attempts = [s for s in raw["steps"] if s["tool"] == "finish"]
        final, = [s for s in attempts if s["step"] == verdict["finish_step"]]
        assert final["result"]["ok"]
        proposed_pages = final["args"]["report"]["source_pages"]
        if arm == "grounded":
            note = json.loads(final["note"])
            observed = {str(s["result"]["value"]["page"]): s["result"]["value"] for s in raw["steps"]
                        if s["tool"] == "open_source" and s["step"] < final["step"]
                        and s["result"]["ok"] and s["result"]["value"].get("ok")}
            assert bind_support(observed, final["args"]["report"], "2025") == note["citation_binding"]
            assert final["args"]["report"]["source_pages"] == note["citation_binding"]["pages"]
            proposed_pages = note["model_source_pages"]
        usage = verdict["usage"]
        rows[arm, seed] = {"seed": seed, "strict_pass": verdict["success"],
            "amount_correct": verdict["checks"]["correct_amount"],
            "pages_correct": verdict["checks"]["correct_source_pages"],
            "llm_calls": usage["llm_calls"], "model_seconds": sum(usage["latency_ms"]) / 1000,
            "rejected_finish_attempts": sum(not s["result"]["ok"] for s in attempts),
            "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
            "model_pages": proposed_pages, "submitted_pages": final["args"]["report"]["source_pages"]}
    assert set(rows) == {(arm, seed) for arm in ("fields", "grounded") for seed in range(4)}
    summary = {}
    for arm in ("fields", "grounded"):
        cases = [rows[arm, seed] for seed in range(4)]
        summary[arm] = {key: round(sum(row[key] for row in cases), 3) for key in
                       ("strict_pass", "amount_correct", "pages_correct", "llm_calls", "model_seconds",
                        "prompt_tokens", "completion_tokens", "rejected_finish_attempts")}
        summary[arm].update(tasks=4, cases=cases)
    summary["fixed"] = [s for s in range(4)
                        if not rows["fields", s]["strict_pass"] and rows["grounded", s]["strict_pass"]]
    summary["regressed"] = [s for s in range(4)
                            if rows["fields", s]["strict_pass"] and not rows["grounded", s]["strict_pass"]]
    summary["decision"] = "retain development candidate" if summary["fixed"] and not summary["regressed"] else "reject"
    summary["scope"] = ("two reused development documents; deterministic citation binding, "
                        "not model training or generalization")
    (base / "D007/summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
