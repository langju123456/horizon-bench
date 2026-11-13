"""Summarise the lever retest from runs/hb.sqlite into reports/retest/.

    python scripts/retest_summary.py                      # all finished retest cells
    python scripts/retest_summary.py --walk-index 7       # also write the step-by-step walkthrough for one seed

Everything here is computed from stored step records and verdicts; nothing is typed in by hand.
The decision rule is the one fixed in reports/retest/PLAN.md before any model run.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from horizon_bench.agents.base import AUTO_SUMMARY_NOTE
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store

CELLS = [  # (batch, label, variants)
    ("retest-base", "baseline (no lever)", []),
    ("retest-ctx", "context: control procedure in the prompt", ["ctx_rule"]),
    ("retest-tool", "tool feedback: deviation / trend / hint in readings", ["tool_hint"]),
    ("retest-guard", "control constraint: harness guard", ["guard"]),
    ("retest-all", "all three together (descriptive only)", ["ctx_rule", "tool_hint", "guard"]),
]
NET_FOR_VERDICT = 5  # improved - worsened seeds needed, out of 10, to call a difference (see PLAN.md)
CONTROL_TOOLS = ("set_coolant", "set_feed")
Run = tuple[RunSpec, dict[str, Any], list[dict[str, Any]]]


def load(store: Store, batch: str, horizon: int, tools: str) -> dict[int, Run]:
    out: dict[int, Run] = {}
    for spec, verdict in store.runs([batch]):
        if spec.horizon == horizon and spec.tools == tools and spec.policy == "llm":
            out[spec.seed_index] = (spec, verdict, store.records(spec.run_id))
    return out


def per_run(run: Run) -> dict[str, Any]:
    _, v, recs = run
    active = [r for r in recs if r["agent_active"]]
    return {
        "kept": bool(v["checks"]["no_lost_control"]),
        "success": bool(v["success"]),
        "onset": v["onset_step"],
        "cause": v["onset_cause"],
        "time_in_band": float(v["metrics"]["time_in_band"]),
        "control_moves": sum(1 for r in active if r["tool"] in CONTROL_TOOLS and not r["flags"].get("guard_blocked")
                             and not r["flags"]["invalid_args"]),
        "temp_reads": sum(1 for r in active if r["tool"] == "read_sensor"
                          and (r["args"] or {}).get("name") in ("temp", "temp_backup")),
        "no_tool": sum(1 for r in active if r["tool"] is None and not r["abort"]),
        "refused": sum(1 for r in active if r["flags"].get("guard_blocked")),
        "alarms_ok": bool(v["checks"]["alarms_acked_in_time"]),
        "notes": sum(1 for r in active if r["tool"] == "write_note" and r["note"] != AUTO_SUMMARY_NOTE),
    }


def mean(xs: list[float]) -> str:
    return f"{statistics.fmean(xs):.1f}" if xs else "-"


def cell_table(cells: list[tuple[str, str, dict[int, dict[str, Any]]]]) -> list[str]:
    rows = ["| cell | n | control kept | success | time in band | control actions / run | temperature reads / run "
            "| steps without a tool call / run | guard refusals / run | notes written / run | alarms on time "
            "| median onset step |",
            "|" + "---|" * 12]
    for _, label, stats in cells:
        s = list(stats.values())
        n = len(s)
        onsets = [x["onset"] for x in s if x["onset"] is not None]
        rows.append("| " + " | ".join([
            label, str(n), f"{sum(x['kept'] for x in s)}/{n}", f"{sum(x['success'] for x in s)}/{n}",
            f"{statistics.fmean(x['time_in_band'] for x in s):.3f}", mean([x["control_moves"] for x in s]),
            mean([x["temp_reads"] for x in s]), mean([x["no_tool"] for x in s]), mean([x["refused"] for x in s]),
            mean([x["notes"] for x in s]),
            f"{sum(x['alarms_ok'] for x in s)}/{n}", f"{statistics.median(onsets):.0f}" if onsets else "-",
        ]) + " |")
    return rows


def paired(base: dict[int, dict[str, Any]], other: dict[int, dict[str, Any]]) -> dict[str, Any]:
    seeds = sorted(set(base) & set(other))
    improved = [i for i in seeds if other[i]["kept"] and not base[i]["kept"]]
    worsened = [i for i in seeds if base[i]["kept"] and not other[i]["kept"]]
    net = len(improved) - len(worsened)
    verdict = "improved" if net >= NET_FOR_VERDICT else "worse" if net <= -NET_FOR_VERDICT else "cannot tell at this n"
    if len(seeds) < 10:
        verdict = f"incomplete ({len(seeds)} paired seeds)"
    return {"seeds": seeds, "improved": improved, "worsened": worsened, "net": net, "verdict": verdict}


def seed_table(cells: list[tuple[str, str, dict[int, dict[str, Any]]]]) -> list[str]:
    indexes = sorted({i for _, _, stats in cells for i in stats})
    rows = ["| eval seed | " + " | ".join(batch for batch, _, _ in cells) + " |", "|" + "---|" * (len(cells) + 1)]
    for i in indexes:
        cols = []
        for _, _, stats in cells:
            x = stats.get(i)
            cols.append("-" if x is None else
                        (f"kept, {x['control_moves']} actions" if x["kept"] else
                         f"lost @{x['onset']} ({x['cause']}), {x['control_moves']} actions"))
        rows.append(f"| {i} | " + " | ".join(cols) + " |")
    return rows


def short(result: Any) -> str:
    if isinstance(result, dict) and "value" in result:
        bits = []
        if result.get("ok") is False:
            bits.append(f"ERROR {str(result.get('error'))[:110]}")
        else:
            value = result["value"]
            bits.append(json.dumps(value)[:60] if not isinstance(value, (int, float)) else f"{value}")
            if result.get("confidence") not in (None, 1.0):
                bits.append(f"conf {result['confidence']}")
            if result.get("deviation") is not None:
                bits.append(f"dev {result['deviation']:+.2f}")
            if result.get("trend_per_step") is not None:
                bits.append(f"trend {result['trend_per_step']:+.2f}")
            if result.get("hint"):
                bits.append(f"hint: {result['hint'][:70]}")
        return "; ".join(bits)
    return "" if result is None else json.dumps(result)[:90]


def walkthrough(title: str, run: Run) -> list[str]:
    spec, v, recs = run
    lines = [f"### {title}", "",
             f"`{spec.run_id}` · variants: {', '.join(spec.variants) or 'none'} · control kept: "
             f"{'yes' if v['checks']['no_lost_control'] else 'no, onset at step ' + str(v['onset_step'])} · "
             f"time in band {v['metrics']['time_in_band']:.2f} · true events: "
             + ", ".join(f"{e['type']}@{e['step']}" for e in v["report"]["true_events"]), "",
             "| step | session | call | what the agent got back | true T | true valve % | active disturbances | note |",
             "|" + "---|" * 8]
    for r in recs:
        if not r["agent_active"]:
            continue
        args = r["args"] or {}
        arg = args.get("name") or args.get("pct") or args.get("rate") or args.get("id") or args.get("key") or ""
        call = "(text only)" if r["tool"] is None else f"{r['tool']}({arg})"
        note = []
        if r["flags"].get("guard_blocked"):
            note.append("REFUSED by guard")
        if r["flags"]["invalid_args"]:
            note.append("invalid")
        if r["flags"]["stale_read_used"]:
            note.append("stale basis")
        if r["tool"] is None and r["note"]:
            note.append("said: " + str(r["note"]).replace("|", "/").replace("\n", " ")[:120])
        t = r["truth"]
        lines.append(f"| {r['step']} | {r['session']} | {call} | {short(r['result']).replace('|', '/')} | "
                     f"{t['T']:.1f} | {t['valve']:.0f} | {', '.join(t['active']) or '-'} | {'; '.join(note)} |")
    return [*lines, ""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="reports/retest")
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--tools", default="rich")
    ap.add_argument("--walk-index", type=int, default=None, help="eval seed index for the step-by-step walkthrough")
    ap.add_argument("--original-batch", default="qwen3-8b-nothink",
                    help="the 2026-11-03 batch; its run for --walk-index is included in the walkthrough if present")
    args = ap.parse_args()

    store = Store(Path(args.runs_dir) / "hb.sqlite")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    loaded = [(batch, label, load(store, batch, args.horizon, args.tools)) for batch, label, _ in CELLS]
    loaded = [c for c in loaded if c[2]]
    if not loaded:
        raise SystemExit("no finished retest runs yet")
    cells = [(batch, label, {i: per_run(run) for i, run in runs.items()}) for batch, label, runs in loaded]
    spec0 = next(iter(loaded[0][2].values()))[0]

    lines = ["# Lever retest: summary", "",
             f"Model `{(spec0.llm or {}).get('model')}`, tools `{args.tools}`, horizon {args.horizon}, eval split "
             f"(salt sha256 `{(spec0.salt_sha256 or '')[:12]}…`). Plan and decision rule: [PLAN.md](PLAN.md). "
             "Generated by `scripts/retest_summary.py` from the stored step records.", "",
             "## Cells", "", *cell_table(cells), ""]
    base = next((stats for batch, _, stats in cells if batch == "retest-base"), None)
    if base is not None:
        lines += ["## Each lever against the baseline, paired by seed", "",
                  "| cell | paired seeds | lost -> kept | kept -> lost | net | verdict by the pre-registered rule |",
                  "|" + "---|" * 6]
        for batch, label, stats in cells:
            if batch == "retest-base":
                continue
            p = paired(base, stats)
            verdict = p["verdict"] if batch != "retest-all" else f"{p['verdict']} (descriptive only)"
            lines.append(f"| {label} | {len(p['seeds'])} | {len(p['improved'])} {p['improved'] or ''} | "
                         f"{len(p['worsened'])} {p['worsened'] or ''} | {p['net']:+d} | {verdict} |")
        lines += ["", f"Rule: a lever is called *improved* (or *worse*) only if at least {NET_FOR_VERDICT} more seeds "
                  "out of 10 move one way than the other; anything less is *cannot tell at this n*.", ""]
    lines += ["## Per seed", "", *seed_table(cells), ""]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {out / 'summary.md'}")

    if args.walk_index is not None:
        i = args.walk_index
        walk = [f"# Walkthrough: eval seed index {i}", "",
                "One step is one tool call. `what the agent got back` is the tool result exactly as the agent saw it "
                "(shortened); `true T` and `true valve` come from the hidden state and were never shown to it.", ""]
        original = load(store, args.original_batch, args.horizon, args.tools).get(i)
        if original is not None:
            walk += walkthrough("Original run (2026-11-03, before any lever)", original)
        for _, label, runs in loaded:
            if i in runs:
                walk += walkthrough(label, runs[i])
        path = out / f"walkthrough-eval{i:03d}.md"
        path.write_text("\n".join(walk) + "\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
