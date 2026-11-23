"""Command line: hb run | resume | replay | show | report."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from horizon_bench.agents.llm import LLMConfig
from horizon_bench.family import get_family
from horizon_bench.forgeflow_delivery import cmd_forgeflow_delivery
from horizon_bench.receipt import FAULTS, STRATEGIES, initial_worker, recover, verify, write_verdict
from horizon_bench.runner import Runner, make_policy, replay
from horizon_bench.spec import RunSpec, load_salt, make_run_id, salt_hash, seeds_for
from horizon_bench.store import Store
from horizon_bench.telemetry import load_prices


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def _tool_mode(text: str) -> Literal["bare", "rich"]:
    if text == "bare":
        return "bare"
    if text == "rich":
        return "rich"
    raise SystemExit(f"--tools must be bare or rich, got {text!r}")


def _variants(text: str, family: str) -> list[str]:
    known = get_family(family).variants
    chosen = _csv(text)
    unknown = [v for v in chosen if v not in known]
    if unknown:
        raise SystemExit(f"unknown --variant {', '.join(unknown)}; available: {', '.join(known) or 'none'}")
    return [v for v in known if v in chosen]  # canonical order, so the same set always labels the same


def _store(args: argparse.Namespace) -> Store:
    return Store(Path(args.runs_dir) / "hb.sqlite")


def _api_key(args: argparse.Namespace) -> str | None:
    return getattr(args, "api_key", None) or os.environ.get("HB_API_KEY") or os.environ.get("OPENAI_API_KEY")


def cmd_run(args: argparse.Namespace) -> int:
    family = get_family(args.family)
    annual = family.name == "annual_handoff"
    variants = _variants(args.variant or ("handoff_full" if annual else ""), family.name)
    count = args.seeds if args.seeds is not None else (2 if annual else 5)
    if annual and (args.split != "dev" or count not in (1, 2) or len(variants) != 1):
        raise SystemExit("annual_handoff has two public dev cases; select 1 or 2 seeds and one handoff variant")
    policies = _csv(args.policy or next(iter(family.policies)))
    if args.submission != "auto" and (not annual or policies != ["llm"]):
        raise SystemExit("--submission requires --family annual_handoff --policy llm")
    if args.handoff_doc != "catl" and not annual:
        raise SystemExit("--handoff-doc only applies to annual_handoff")
    run_prefix = f"{args.name}-{family.name}-{variants[0]}" if annual else args.name
    if args.handoff_doc != "catl":
        run_prefix += "-" + args.handoff_doc
    if args.submission != "auto":
        run_prefix += "-" + args.submission
    store = _store(args)
    runner = Runner(store, Path(args.runs_dir))
    salt = load_salt() if args.split == "eval" else None
    seeds = seeds_for(args.split, count, salt)
    if args.handoff_doc == "transfer":
        seeds = [seed + 2 for seed in seeds]
    llm = None
    if "llm" in policies:
        llm = LLMConfig(base_url=args.base_url, model=args.model, max_steps=args.max_steps,
                        max_tokens_per_call=args.max_tokens_per_call, max_total_tokens=args.max_total_tokens,
                        wall_time_s=args.wall_time, context_budget_tokens=args.context_budget,
                        temperature=args.temperature, no_think=args.no_think,
                        tool_observation=args.tool_observation, submission=args.submission).to_dict()
    prices = load_prices(args.prices)
    successes = total = 0
    for policy in policies:
        for tools in _csv(args.tools):
            for horizon in [int(h) for h in _csv(args.horizon)]:
                for i, seed in enumerate(seeds):
                    spec = RunSpec(
                        run_id=make_run_id(run_prefix, policy, tools, horizon, args.split, i), batch=args.name,
                        family=args.family, policy=policy, tools=_tool_mode(tools), horizon=horizon,
                        session_len=args.session_len,
                        seed=seed, split=args.split, seed_index=i, salt_sha256=salt_hash(salt) if salt else None,
                        llm=llm if policy == "llm" else None, prices=prices, variants=variants)
                    status = store.status(spec.run_id)
                    if annual and status and not args.overwrite and spec != store.spec(spec.run_id):
                        raise SystemExit(f"configuration changed for {spec.run_id}; choose a new --name")
                    if status == "done" and not args.overwrite:
                        print(f"skip {spec.run_id}: done (use --overwrite to run it again)")
                        continue
                    if status == "running" and not args.overwrite:
                        print(f"resume {spec.run_id}: it was interrupted", flush=True)
                        stored = store.spec(spec.run_id)
                        v = runner.resume(spec.run_id, make_policy(stored, api_key=_api_key(args)))
                    else:
                        v = runner.start(spec, make_policy(spec, api_key=_api_key(args)), overwrite=args.overwrite)
                    successes, total = successes + v["success"], total + 1
                    lost = v["onset_step"] is not None
                    onset = f"onset {v['onset_cause']}@{v['onset_step']}" if lost else "in control"
                    status = "ok  " if v["success"] else "FAIL"
                    failed = ",".join(v["failed"]) or "-"
                    print(f"{status} {spec.run_id}  end={v['end_reason']}  {onset}  failed={failed}", flush=True)
    if total:
        print(f"{successes}/{total} runs succeeded")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    store = _store(args)
    spec = store.spec(args.run_id)
    v = Runner(store, Path(args.runs_dir)).resume(args.run_id, make_policy(spec, api_key=_api_key(args)))
    print(json.dumps({k: v[k] for k in ("run_id", "success", "failed", "onset_step", "onset_cause")}))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    result = replay(_store(args), args.run_id)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.step is None:
        print(json.dumps(store.verdict(args.run_id) or {"status": store.status(args.run_id)}, indent=2))
        return 0
    rec = next((r for r in store.records(args.run_id) if r["step"] == args.step), None)
    if rec is None:
        print(f"no step {args.step} in {args.run_id}", file=sys.stderr)
        return 1
    print(json.dumps(rec, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from horizon_bench.report import build_report

    out = build_report(_store(args), args.batch or [args.name], args.name, Path(args.reports_dir))
    print(f"wrote {out / 'report.md'}")
    return 0


def cmd_receipt_worker(args: argparse.Namespace) -> int:
    client, inbox = Path(args.client_db), Path(args.inbox_db)
    if args.recover:
        recover(client, inbox, args.strategy)
    else:
        initial_worker(client, inbox, args.fault, args.crash)
    return 0


def cmd_receipt_experiment(args: argparse.Namespace) -> int:
    """Run D001's fixed 4 x 3 matrix without exposing a fault to a strategy."""
    out = Path(args.output)
    if out.exists():
        print(f"refusing to overwrite existing experiment directory: {out}", file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    base = [sys.executable, "-m", "horizon_bench.cli"]
    for fault in FAULTS:
        for strategy in STRATEGIES:
            cell = out / f"{strategy}--{fault}"
            cell.mkdir()
            client, inbox = cell / "client.sqlite", cell / "inbox.sqlite"
            initial = [*base, "receipt-worker", "--client-db", str(client), "--inbox-db", str(inbox), "--fault", fault]
            crash_requested = fault == "receipt_lost_crash"
            if crash_requested:
                initial.append("--crash")
            first = subprocess.run(initial, capture_output=True, text=True)
            measured = first.returncode == -signal.SIGKILL
            # A new process is the recovery boundary. For the first two faults, this is also deliberately
            # separate from the simulated timeout-producing process.
            second = subprocess.run(
                [
                    *base,
                    "receipt-worker",
                    "--client-db",
                    str(client),
                    "--inbox-db",
                    str(inbox),
                    "--strategy",
                    strategy,
                    "--recover",
                ],
                capture_output=True,
                text=True,
            )
            verdict = verify(client, inbox, strategy, fault, first.returncode, measured, second.returncode)
            write_verdict(cell / "verdict.json", verdict)
            (cell / "process.json").write_text(
                json.dumps(
                    {
                        "initial_returncode": first.returncode,
                        "recovery_returncode": second.returncode,
                        "process_measured": measured,
                        "infrastructure_ok": verdict.infrastructure_ok,
                        "observation": {
                            "ack": "normal acknowledgement",
                            "request_lost": "simulated timeout before the inbox write",
                            "receipt_lost_crash": "inbox write followed by intended SIGKILL",
                        }[fault],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            rows.append(
                {
                    "strategy": strategy,
                    "fault": fault,
                    "success": verdict.success,
                    "target_receipts": verdict.target_receipts,
                    "local_status": verdict.local_status,
                    "initial_returncode": first.returncode,
                    "process_measured": measured,
                    "infrastructure_ok": verdict.infrastructure_ok,
                }
            )
            # SQLite files are execution scratch space. Stable JSON is the check-in evidence, not a live database.
            for db_path in (client, inbox):
                for suffix in ("", "-wal", "-shm"):
                    (Path(str(db_path) + suffix)).unlink(missing_ok=True)
    manifest = {
        "matrix": "4 strategies x 3 faults",
        "rows": rows,
        "acceptance": (
            "expected process exits, exactly one expected payload/version/digest in inbox, and local completed"
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# D001 收件回执实验",
        "",
        "命令：`hb receipt-experiment --output <新目录>`。每格的 `verdict.json` 和 `process.json` "
        "是稳定原始证据；SQLite/WAL 只在运行时存在。",
        "",
        "| 策略 | 故障 | 目标收件数 | 本地状态 | 成功 | 初始进程 |",
        "|---|---|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy']} | {row['fault']} | {row['target_receipts']} | {row['local_status']} | "
            f"{'是' if row['success'] else '否'} | {row['initial_returncode']} |"
        )
    (out / "README.zh.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {out / 'README.zh.md'}")
    return 0 if all(row["infrastructure_ok"] for row in rows) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hb", description="Agent test bench for reactor shifts and report handoffs.")
    p.add_argument("--runs-dir", default="runs", help="where hb.sqlite and per-run traces live")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one or more policies over a seed set")
    r.add_argument("--policy", help="family policy or llm; defaults to pid for reactor and catalog for annual_handoff")
    r.add_argument("--tools", default="rich", help="comma list of bare,rich")
    r.add_argument("--horizon", default="120", help="comma list of horizons in steps")
    r.add_argument("--seeds", type=int, help="number of seeds; reactor defaults to five, annual_handoff to two")
    r.add_argument("--split", choices=["dev", "eval"], default="dev")
    r.add_argument("--name", default="default", help="batch name, used by `hb report`")
    r.add_argument("--family", choices=["reactor", "annual_handoff"], default="reactor")
    r.add_argument("--handoff-doc", choices=["catl", "transfer"], default="catl",
                   help="choose the original CATL cases or the second public document's cases")
    r.add_argument("--submission", choices=["auto", "fields", "reminder", "task_tools"], default="auto",
                   help="annual handoff only: compare how the model sees or is reminded of the final submission")
    r.add_argument("--session-len", type=int, default=40)
    r.add_argument("--variant", default="",
                   help="comma list of opt-in levers recorded in the run spec: ctx_rule (control procedure in "
                        "the prompt), tool_hint (deviation/trend/hint in temperature readings), guard "
                        "(the harness refuses out-of-order actions)")
    r.add_argument("--overwrite", action="store_true")
    d = LLMConfig()
    r.add_argument("--model", default=d.model)
    r.add_argument("--base-url", default=d.base_url)
    r.add_argument("--api-key", default=None, help="else $HB_API_KEY / $OPENAI_API_KEY; never stored")
    r.add_argument("--max-steps", type=int, default=d.max_steps)
    r.add_argument("--max-tokens-per-call", type=int, default=d.max_tokens_per_call)
    r.add_argument("--max-total-tokens", type=int, default=d.max_total_tokens)
    r.add_argument("--wall-time", type=float, default=d.wall_time_s, help="seconds of model time per run")
    r.add_argument("--context-budget", type=int, default=d.context_budget_tokens)
    r.add_argument("--temperature", type=float, default=d.temperature)
    r.add_argument("--tool-observation", choices=["escaped", "unicode", "business"], default="escaped",
                   help="how the model reads tool results; recorded tool evidence is always preserved")
    r.add_argument("--no-think", action="store_true",
                   help="Qwen3 only: add the /no_think switch (recorded in the run spec)")
    r.add_argument("--prices", default=None, help='JSON {"model": [usd_per_1M_in, usd_per_1M_out]}')
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("resume", help="continue a killed run from its last checkpoint")
    s.add_argument("run_id")
    s.add_argument("--api-key", default=None)
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("replay", help="re-execute a run from its trace and check it reproduces")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("show", help="print a run verdict, or one step with --step")
    s.add_argument("run_id")
    s.add_argument("--step", type=int, default=None)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("report", help="write reports/<name>/report.md and charts")
    s.add_argument("--name", required=True)
    s.add_argument("--batch", action="append", help="batch to include (repeatable); default: --name")
    s.add_argument("--reports-dir", default="reports")
    s.set_defaults(fn=cmd_report)

    e = sub.add_parser("receipt-experiment", help="run D001's annual-report receipt/recovery matrix")
    e.add_argument("--output", required=True, help="new directory for raw client/inbox SQLite files and verdicts")
    e.set_defaults(fn=cmd_receipt_experiment)

    d4 = sub.add_parser("forgeflow-delivery", help="check a pinned Apple approval against five local inbox scenarios")
    d4.add_argument("--source-repo", type=Path, required=True, help="local Git checkout of ForgeFlow")
    d4.add_argument("--review-sha256", required=True)
    d4.add_argument("--source-commit", required=True)
    d4.add_argument("--output", type=Path, required=True, help="new JSON output file")
    d4.set_defaults(fn=cmd_forgeflow_delivery)

    w = sub.add_parser("receipt-worker", help=argparse.SUPPRESS)
    w.add_argument("--client-db", required=True)
    w.add_argument("--inbox-db", required=True)
    w.add_argument("--fault", choices=FAULTS, default="ack")
    w.add_argument("--strategy", choices=STRATEGIES, default="assume_success")
    w.add_argument("--crash", action="store_true")
    w.add_argument("--recover", action="store_true")
    w.set_defaults(fn=cmd_receipt_worker)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: Any = args.fn(args)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
