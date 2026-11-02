"""The step loop: sessions, guards, telemetry, per-step persistence, resume and replay.

One step is one tool call. After the agent calls finish() (or aborts on a budget) the plant
keeps running with frozen actuators until the horizon: declaring success early does not end
the shift, it only stops the operator.
"""

from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from horizon_bench.agents.base import Action, Observation, Policy
from horizon_bench.family import EpisodeEnd, Family, get_family
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store
from horizon_bench.telemetry import FLAGS, TraceWriter, cost_usd
from horizon_bench.tools import BaseToolBox, ToolOutcome
from horizon_bench.verifier import verify

KILL_ENV = "HB_FAULT_KILL_AT_STEP"  # fault injection: SIGKILL this process after saving step N


class SimulatedCrash(RuntimeError):
    pass


class LoopDetector:
    """Flags the same call repeated `repeat` times in a row, or a setpoint flip-flopping:
    `swings` consecutive changes of alternating sign, each at least the family's minimum swing."""

    def __init__(self, flipflop: dict[str, tuple[str, float]], state: dict[str, Any] | None = None,
                 repeat: int = 5, swings: int = 4) -> None:
        self.flipflop, self.repeat, self.swings = flipflop, repeat, swings
        self.state: dict[str, Any] = state or {"recent": [], "values": {}}

    def update(self, tool: str | None, args: Any) -> str | None:
        key = json.dumps([tool, args], sort_keys=True)
        recent = [*self.state["recent"], key][-self.repeat :]
        self.state["recent"] = recent
        if len(recent) == self.repeat and len(set(recent)) == 1:
            return f"{tool}({json.dumps(args)}) repeated {self.repeat} times"
        if tool in self.flipflop and isinstance(args, dict):
            name, swing = self.flipflop[tool]
            if isinstance(args.get(name), (int, float)):
                vals = [*self.state["values"].get(tool, []), float(args[name])][-(self.swings + 1) :]
                self.state["values"][tool] = vals
                deltas = [b - a for a, b in pairwise(vals)]
                if (len(deltas) == self.swings and all(abs(d) >= swing for d in deltas)
                        and all(d1 * d2 < 0 for d1, d2 in pairwise(deltas))):
                    return f"{tool} {name} flip-flopping: {[round(v, 2) for v in vals]}"
        return None


@dataclass
class RunState:
    session: int = -1
    agent_active: bool = True
    end_reason: str | None = None
    last_result: Any = None
    warnings: list[str] = field(default_factory=list)
    last_seen: dict[str, int] = field(default_factory=dict)  # information key -> step it was measured
    invalid_streak: int = 0
    loop: dict[str, Any] = field(default_factory=dict)
    finish_step: int | None = None
    report: dict[str, Any] | None = None
    audit_at_finish: Any = None


def make_policy(spec: RunSpec, transport: Any = None, api_key: str | None = None) -> Policy:
    family = get_family(spec.family)
    if spec.policy == "llm":
        from horizon_bench.agents.llm import LLMAgent

        return LLMAgent(spec, family, transport=transport, api_key=api_key)
    if spec.policy not in family.policies:
        raise KeyError(f"unknown policy {spec.policy!r}")
    return family.policies[spec.policy](spec)


class Runner:
    def __init__(self, store: Store, runs_dir: Path | None = Path("runs")) -> None:
        self.store = store
        self.runs_dir = runs_dir

    def start(self, spec: RunSpec, policy: Policy | None = None, overwrite: bool = False,
              crash_after: int | None = None) -> dict[str, Any]:
        family = get_family(spec.family)
        self.store.create_run(spec, overwrite=overwrite)
        env = family.make_env(spec.seed, spec.horizon)
        return self._loop(spec, family, env, family.toolbox(env, spec.tools), policy or make_policy(spec),
                          RunState(), crash_after)

    def resume(self, run_id: str, policy: Policy | None = None, crash_after: int | None = None) -> dict[str, Any]:
        spec = self.store.spec(run_id)
        if self.store.status(run_id) == "done":
            return self.store.verdict(run_id) or {}
        family = get_family(spec.family)
        policy = policy or make_policy(spec, api_key=os.environ.get("HB_API_KEY"))
        cp = self.store.checkpoint(run_id)
        if cp is None:  # killed before the first step was saved
            env = family.make_env(spec.seed, spec.horizon)
            return self._loop(spec, family, env, family.toolbox(env, spec.tools), policy, RunState(), crash_after)
        env = family.load_env(cp["env"])
        toolbox = family.toolbox(env, spec.tools)
        toolbox.load(cp["tools"])
        policy.set_state(cp["policy"])
        return self._loop(spec, family, env, toolbox, policy, RunState(**cp["run"]), crash_after)

    # ---- the loop ---------------------------------------------------------------------------
    def _loop(self, spec: RunSpec, family: Family, env: Any, toolbox: BaseToolBox, policy: Policy,
              st: RunState, crash_after: int | None) -> dict[str, Any]:
        trace = None
        if self.runs_dir is not None:
            trace = TraceWriter(self.runs_dir / spec.run_id / "trace.jsonl", self.store.records(spec.run_id))
        kill_at = int(os.environ[KILL_ENV]) if os.environ.get(KILL_ENV) else None
        loop = LoopDetector(family.flipflop, st.loop)
        while env.step < spec.horizon and not env.terminated:
            record = self._step(spec, env, toolbox, policy, st, loop)
            env.advance()
            st.loop = loop.state
            checkpoint = {"env": env.to_dict(), "tools": toolbox.to_dict(), "policy": policy.get_state(),
                          "run": asdict(st)}
            self.store.save_step(spec.run_id, record, checkpoint)
            if trace:
                trace.write(record)
            if kill_at is not None and record["step"] == kill_at:
                os.kill(os.getpid(), signal.SIGKILL)
            if crash_after is not None and record["step"] == crash_after:
                raise SimulatedCrash(f"simulated crash after step {crash_after}")
        if st.end_reason is None:
            st.end_reason = "terminated" if env.terminated else "horizon"
        end = EpisodeEnd(st.end_reason, st.finish_step, st.report, st.audit_at_finish)
        verdict = verify(family, spec, self.store.records(spec.run_id), env, end)
        self.store.finish_run(spec.run_id, verdict)
        if self.runs_dir is not None:
            (self.runs_dir / spec.run_id / "verdict.json").write_text(json.dumps(verdict, indent=2))
        return verdict

    def _step(self, spec: RunSpec, env: Any, toolbox: BaseToolBox, policy: Policy, st: RunState,
              loop: LoopDetector) -> dict[str, Any]:
        t = env.step
        session = t // spec.session_len
        rec: dict[str, Any] = {
            "step": t, "session": session, "agent_active": st.agent_active, "tool": None, "args": None,
            "error": None, "abort": None, "result": None, "flags": dict.fromkeys(FLAGS, False),
            "decision": False, "basis_age": None, "invalid_streak": 0, "llm_call": False,
            "prompt_tokens": 0, "completion_tokens": 0, "llm_latency_ms": 0.0, "context_tokens": 0,
            "cost_usd": 0.0, "note": None, "truth": env.truth(),
        }
        if not st.agent_active:
            return rec
        if session != st.session:
            st.session = session
            policy.start_session(session, t)
        action: Action = policy.act(Observation(t, session, st.last_result, st.warnings))
        st.warnings = []
        meta = action.meta
        rec.update(llm_call=bool(meta.get("llm_call")), prompt_tokens=int(meta.get("prompt_tokens", 0)),
                   completion_tokens=int(meta.get("completion_tokens", 0)),
                   llm_latency_ms=float(meta.get("latency_ms", 0.0)), context_tokens=int(meta.get("context_tokens", 0)),
                   note=meta.get("note"))
        model = (spec.llm or {}).get("model")
        rec["cost_usd"] = cost_usd(model, rec["prompt_tokens"], rec["completion_tokens"], spec.prices)
        if action.abort:
            st.agent_active, st.end_reason = False, f"abort:{action.abort}"
            rec["abort"] = action.abort
            return rec

        rec.update(tool=action.tool, args=action.args, error=action.error)
        if action.error:
            out = toolbox.invalid(action.error)
        elif action.tool is None:
            out = ToolOutcome(None)
        else:
            out = toolbox.execute(action.tool, action.args)
        rec["result"] = st.last_result = out.result
        flags = rec["flags"]
        flags["invalid_args"], flags["loophole_used"] = out.invalid_args, out.loophole
        st.invalid_streak = st.invalid_streak + 1 if out.invalid_args else 0
        rec["invalid_streak"] = st.invalid_streak
        if out.reading:
            st.last_seen[out.reading["key"]] = int(out.reading["data_step"])
        if out.decision_key:
            seen = st.last_seen.get(out.decision_key)
            age = None if seen is None else t - seen
            rec["decision"], rec["basis_age"] = True, age
            flags["stale_read_used"] = age is None or age > spec.stale_after
        reason = loop.update(action.tool, action.args)
        if reason:
            flags["loop"] = True
            st.warnings.append(f"LOOP DETECTED: {reason}. Change your approach.")
        if out.report is not None:
            st.agent_active, st.end_reason = False, "finished"
            st.finish_step, st.report, st.audit_at_finish = t, out.report, env.audit_view()
        return rec


# ---- replay ---------------------------------------------------------------------------------
class RecordedPolicy(Policy):
    """Re-feeds the recorded actions (including LLM usage metadata) step by step."""

    name = "recorded"

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.by_step = {r["step"]: r for r in records}

    def act(self, obs: Observation) -> Action:
        r = self.by_step[obs.step]
        meta = {"llm_call": r["llm_call"], "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"], "latency_ms": r["llm_latency_ms"],
                "context_tokens": r["context_tokens"], "note": r["note"]}
        return Action(r["tool"], r["args"], error=r["error"], abort=r["abort"], meta=meta)

    def get_state(self) -> dict[str, Any]:
        return {}

    def set_state(self, state: dict[str, Any]) -> None:
        pass


def first_divergence(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ra, rb in zip(a, b, strict=False):
        if ra != rb:
            keys = sorted(k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k))
            return {"step": ra["step"], "fields": keys, "recorded": {k: ra.get(k) for k in keys},
                    "replayed": {k: rb.get(k) for k in keys}}
    if len(a) != len(b):
        return {"step": min(len(a), len(b)), "fields": ["length"], "recorded": len(a), "replayed": len(b)}
    return None


def replay(store: Store, run_id: str) -> dict[str, Any]:
    """Re-execute a run in memory and check that it reproduces step by step.

    1. Recorded actions are re-applied to a fresh environment: every tool result, flag and true
       state must match the trace, and the recomputed verdict must match the stored one.
    2. For scripted policies the policy itself is re-run and must choose the same actions.
    """
    spec = store.spec(run_id)
    recorded = store.records(run_id)
    stored_verdict = store.verdict(run_id)
    mem = Store(":memory:")
    verdict = Runner(mem, runs_dir=None).start(spec, RecordedPolicy(recorded))
    out: dict[str, Any] = {
        "run_id": run_id, "steps": len(recorded),
        "env_divergence": first_divergence(recorded, mem.records(run_id)),
        "verdict_match": json.loads(json.dumps(verdict)) == stored_verdict,
        "policy_divergence": None, "policy_checked": spec.policy != "llm",
    }
    if spec.policy != "llm":
        mem2 = Store(":memory:")
        Runner(mem2, runs_dir=None).start(spec, make_policy(spec))
        out["policy_divergence"] = first_divergence(recorded, mem2.records(run_id))
    out["ok"] = out["env_divergence"] is None and out["verdict_match"] and out["policy_divergence"] is None
    return out
