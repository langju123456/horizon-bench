"""Command line: hb run | resume | replay | show | report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from horizon_bench import otel
from horizon_bench.agents.llm import LLMConfig
from horizon_bench.report import build_report
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


def _store(args: argparse.Namespace) -> Store:
    return Store(Path(args.runs_dir) / "hb.sqlite")


def _api_key(args: argparse.Namespace) -> str | None:
    return getattr(args, "api_key", None) or os.environ.get("HB_API_KEY") or os.environ.get("OPENAI_API_KEY")


def cmd_run(args: argparse.Namespace) -> int:
    store = _store(args)
    runner = Runner(store, Path(args.runs_dir))
    salt = load_salt() if args.split == "eval" else None
    seeds = seeds_for(args.split, args.seeds, salt)
    llm = None
    if "llm" in _csv(args.policy):
        llm = LLMConfig(base_url=args.base_url, model=args.model, max_steps=args.max_steps,
                        max_tokens_per_call=args.max_tokens_per_call, max_total_tokens=args.max_total_tokens,
                        wall_time_s=args.wall_time, context_budget_tokens=args.context_budget,
                        keep_last_messages=args.keep_last_messages,
                        temperature=args.temperature, no_think=args.no_think).to_dict()
    prices = load_prices(args.prices)
    successes = total = 0
    for policy in _csv(args.policy):
        for tools in _csv(args.tools):
            for horizon in [int(h) for h in _csv(args.horizon)]:
                for i, seed in enumerate(seeds):
                    spec = RunSpec(
                        run_id=make_run_id(args.name, policy, tools, horizon, args.split, i), batch=args.name,
                        family=args.family, policy=policy, tools=_tool_mode(tools), horizon=horizon,
                        session_len=args.session_len,
                        seed=seed, split=args.split, seed_index=i, salt_sha256=salt_hash(salt) if salt else None,
                        llm=llm if policy == "llm" else None, prices=prices)
                    status = store.status(spec.run_id)
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
    out = build_report(_store(args), args.batch or [args.name], args.name, Path(args.reports_dir))
    print(f"wrote {out / 'report.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hb", description="Long-horizon agent test bench (reactor task).")
    p.add_argument("--runs-dir", default="runs", help="where hb.sqlite and per-run traces live")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one or more policies over a seed set")
    r.add_argument("--policy", default="pid", help="comma list of pid,naive,lazy,random,llm")
    r.add_argument("--tools", default="rich", help="comma list of bare,rich")
    r.add_argument("--horizon", default="120", help="comma list of horizons in steps")
    r.add_argument("--seeds", type=int, default=5, help="number of seeds")
    r.add_argument("--split", choices=["dev", "eval"], default="dev")
    r.add_argument("--name", default="default", help="batch name, used by `hb report`")
    r.add_argument("--family", default="reactor")
    r.add_argument("--session-len", type=int, default=40)
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
    r.add_argument("--keep-last-messages", type=int, default=d.keep_last_messages,
                   help="messages the rolling window keeps when it trims (fewer: rarer trims, less recent context)")
    r.add_argument("--temperature", type=float, default=d.temperature)
    r.add_argument("--no-think", action="store_true",
                   help="Qwen3 only: add the /no_think switch (recorded in the run spec)")
    r.add_argument("--prices", default=None, help='JSON {"model": [usd_per_1M_in, usd_per_1M_out]}')
    _otel_args(r)
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("resume", help="continue a killed run from its last checkpoint")
    s.add_argument("run_id")
    s.add_argument("--api-key", default=None)
    _otel_args(s)
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
    return p


def _otel_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("OpenTelemetry (pip install -e '.[otel]')")
    g.add_argument("--otel", action="store_true",
                   help="export a trace per run over OTLP/HTTP (standard OTEL_EXPORTER_OTLP_* variables apply)")
    g.add_argument("--otel-endpoint", default=None, help="e.g. http://localhost:4318/v1/traces (Jaeger, Phoenix)")
    g.add_argument("--otel-console", action="store_true", help="print spans to stdout instead of exporting")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "otel", False) or getattr(args, "otel_console", False):
        otel.configure(args.otel_endpoint, console=args.otel_console)
    try:
        code: Any = args.fn(args)
    finally:
        otel.shutdown()  # flush batched spans before exit
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
