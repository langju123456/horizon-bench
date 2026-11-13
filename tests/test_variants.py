"""Opt-in levers (RunSpec.variants). Each one changes a single layer (prompt, tool returns, harness),
none of them changes a default run, and all of them use only what the agent itself observed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from conftest import ScriptPolicy, make_spec, run
from horizon_bench.agents.base import AUTO_SUMMARY_NOTE, Action
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.cli import _variants, main
from horizon_bench.env.reactor_guard import ARM_GRACE, DEV_LIMIT, MAX_READ_AGE, ReactorGuard
from horizon_bench.family import get_family
from horizon_bench.report import policy_label
from horizon_bench.runner import Runner, SimulatedCrash, replay
from horizon_bench.store import Store
from horizon_bench.telemetry import FLAGS
from horizon_bench.tools import ToolOutcome
from test_llm_agent import FINISH, FakeServer, call, completion

RICH_KEYS = {"value", "ok", "error", "confidence", "age_steps", "latency_ms"}
HINT_KEYS = {"setpoint", "deviation", "in_band", "trend_per_step", "hint"}
READ_T = ("read_sensor", {"name": "temp"})
READ_B = ("read_sensor", {"name": "temp_backup"})
READ_P = ("read_sensor", {"name": "pressure"})
READ_V = ("read_sensor", {"name": "valve_position"})
READ_F = ("read_sensor", {"name": "feed_rate"})
OTHERS = [READ_P, READ_V, READ_F]
COLD = ("set_coolant", {"pct": 100})  # full cooling: the reactor falls well below the setpoint within a few steps


def records(calls: list[tuple[str | None, Any]], seed: int = 3, horizon: int = 30, **kw: Any) -> list[dict[str, Any]]:
    spec = make_spec("script", horizon=horizon, seed=seed, **kw)
    _, store = run(spec, ScriptPolicy(calls))
    return store.records(spec.run_id)


def fresh(rec: dict[str, Any]) -> bool:
    return isinstance(rec["result"], dict) and rec["result"]["ok"] and rec["result"]["age_steps"] == 0


# ---- nothing changes unless a variant is asked for -------------------------------------------
def test_a_default_run_has_no_trace_of_the_variants() -> None:
    spec = make_spec("script")
    assert "Control procedure" not in get_family("reactor").system_prompt(spec)
    recs = records([COLD, READ_P, READ_T, READ_P, READ_T])
    assert all(set(r["flags"]) == set(FLAGS) for r in recs)
    assert all(set(r["result"]) == RICH_KEYS for r in recs if r["tool"] == "read_sensor")
    assert policy_label(spec) == "script"


def test_ctx_rule_changes_the_prompt_and_nothing_else() -> None:
    prompt = get_family("reactor").system_prompt(make_spec("script", variants=["ctx_rule"]))
    assert "Control procedure" in prompt and "50 + 6 x (reading - 180)" in prompt and f"{DEV_LIMIT} degC" in prompt
    calls = [COLD, READ_P, READ_T, READ_P, READ_T]
    assert records(calls, variants=["ctx_rule"]) == records(calls)  # a scripted policy never reads the prompt


# ---- tool feedback ---------------------------------------------------------------------------
def test_tool_hint_adds_computed_fields_to_fresh_temperature_readings() -> None:
    calls = [COLD, READ_P, READ_T, READ_P, READ_V, READ_T, READ_B, READ_P]
    base, hint = records(calls), records(calls, variants=["tool_hint"])
    assert [r["truth"] for r in base] == [r["truth"] for r in hint]  # the plant is untouched
    first, second, backup = hint[2]["result"], hint[5]["result"], hint[6]["result"]
    assert fresh(hint[2]) and fresh(hint[5]) and fresh(hint[6]), "pick another seed: a read timed out"
    assert set(first) == RICH_KEYS | HINT_KEYS
    assert first["deviation"] == pytest.approx(first["value"] - 180.0, abs=0.01) and first["trend_per_step"] is None
    assert second["deviation"] < -DEV_LIMIT and second["in_band"] is (abs(second["deviation"]) <= 5.0)
    assert second["trend_per_step"] == pytest.approx((second["value"] - first["value"]) / 3, abs=0.01)
    assert "below setpoint and still falling" in second["hint"] and "lower pct" in second["hint"]
    assert backup["trend_per_step"] is None  # trends are per sensor: TT-102 has no earlier reading
    assert all(set(r["result"]) == RICH_KEYS for r in hint if r["args"] in ({"name": "pressure"},
                                                                           {"name": "valve_position"}))
    bare = records(calls, tools="bare", variants=["tool_hint"])
    assert isinstance(bare[2]["result"], float)  # bare tools stay bare


def test_tool_hint_says_hold_when_the_reading_is_already_recovering() -> None:
    # Full cooling, then the valve is shut: by step 10 the reactor is still cold but warming up again.
    # TT-102 is read because seed 3 has a TT-101 dropout in this window (cached readings get no hint).
    calls = [COLD, READ_P, READ_V, READ_F, READ_P, READ_V, ("set_coolant", {"pct": 0}), READ_P, READ_B, READ_P, READ_B]
    recs = records(calls, variants=["tool_hint"])
    last = recs[10]["result"]
    assert fresh(recs[8]) and fresh(recs[10]), "pick another seed: a read timed out"
    assert last["deviation"] < -DEV_LIMIT and last["trend_per_step"] > 0
    assert "but moving back toward it" in last["hint"] and "keep the valve" in last["hint"]


def test_tool_hint_trend_survives_a_crash() -> None:
    calls = [COLD, READ_P, READ_T, READ_P, READ_V, READ_T, READ_P, READ_T]
    spec = make_spec("script", horizon=12, seed=3, variants=["tool_hint"])
    whole, _ = run(spec, ScriptPolicy(calls))
    store = Store(":memory:")
    runner = Runner(store, runs_dir=None)
    with pytest.raises(SimulatedCrash):
        runner.start(spec, ScriptPolicy(calls), crash_after=3)
    assert runner.resume(spec.run_id, ScriptPolicy(calls)) == whole
    assert store.records(spec.run_id)[5]["result"]["trend_per_step"] is not None  # needs the reading from step 2


# ---- control constraint ----------------------------------------------------------------------
GUARD_SCRIPT: list[tuple[str | None, Any]] = [
    COLD, READ_P, READ_V, READ_F, READ_P, READ_V,  # steps 0-5: acting and reading other sensors is fine at first
    READ_F,  # 6: refused, no temperature reading yet
    READ_T,  # 7: accepted; the reading is far below the setpoint, so the guard arms
    ("write_note", {"key": "k", "text": "x"}),  # 8: refused, control comes first
    READ_B,  # 9: accepted, first cross-check
    READ_T,  # 10: accepted, second cross-check
    READ_B,  # 11: refused, the cross-check allowance is used up
    ("set_coolant", {"pct": 40}),  # 12: accepted, the guard disarms
    ("read_notes", {}),  # 13: accepted again
    (None, None),  # 14: a text-only step is still just a wasted step
]


def test_guard_refuses_out_of_order_actions_without_executing_them() -> None:
    recs = records(GUARD_SCRIPT, horizon=15, variants=["guard"])
    assert all(fresh(recs[i]) for i in (7, 9, 10)), "pick another seed: a read timed out"
    blocked = [r["step"] for r in recs if r["flags"]["guard_blocked"]]
    assert blocked == [6, 8, 11]
    assert "TEMPERATURE READING REQUIRED" in recs[6]["result"]["error"] and recs[6]["result"]["ok"] is False
    assert "CONTROL REQUIRED" in recs[8]["result"]["error"] and "lower pct" in recs[8]["result"]["error"]
    assert "CONTROL REQUIRED" in recs[11]["result"]["error"]
    # a refusal is not a malformed call, and the refused note was never written
    assert not any(r["flags"]["invalid_args"] for r in recs) and max(r["invalid_streak"] for r in recs) == 0
    assert recs[13]["result"]["value"] == {}
    assert recs[12]["decision"] and recs[12]["result"]["ok"]
    assert ARM_GRACE == 2 and MAX_READ_AGE == 6  # the script above is written for these values


def test_guard_never_refuses_finish_and_text_only_steps_carry_the_requirement() -> None:
    calls = [*GUARD_SCRIPT[:8], (None, None), ("finish", FINISH)]
    spec = make_spec("script", horizon=20, seed=3, variants=["guard"])
    v, store = run(spec, ScriptPolicy(calls))
    recs = store.records(spec.run_id)
    assert recs[8]["tool"] is None and recs[8]["flags"]["guard_blocked"]  # armed, and nothing was done
    assert recs[9]["tool"] == "finish" and not recs[9]["flags"]["guard_blocked"] and v["end_reason"] == "finished"


def test_guard_state_survives_a_crash() -> None:
    spec = make_spec("script", horizon=15, seed=3, variants=["guard"])
    whole, _ = run(spec, ScriptPolicy(GUARD_SCRIPT))
    store = Store(":memory:")
    runner = Runner(store, runs_dir=None)
    with pytest.raises(SimulatedCrash):
        runner.start(spec, ScriptPolicy(GUARD_SCRIPT), crash_after=7)  # killed right after the guard armed
    assert runner.resume(spec.run_id, ScriptPolicy(GUARD_SCRIPT)) == whole  # the checkpoint restores the policy
    assert [r["step"] for r in store.records(spec.run_id) if r["flags"]["guard_blocked"]] == [6, 8, 11]


def test_a_guarded_run_replays_step_by_step() -> None:
    spec = make_spec("random", horizon=40, seed=2, variants=["tool_hint", "guard"])
    _, store = run(spec)
    assert any(r["flags"]["guard_blocked"] for r in store.records(spec.run_id))  # some random calls were refused
    assert replay(store, spec.run_id)["ok"]  # actions, results, flags, true state, verdict and the policy itself


def reading(value: float | None, step: int, at: int, ok: bool = True, confidence: float = 1.0) -> ToolOutcome:
    result = {"value": value, "ok": ok, "error": None, "confidence": confidence, "age_steps": step - at}
    return ToolOutcome(result, reading={"key": "temperature", "data_step": at} if value is not None else None)


def test_guard_acts_only_on_readings_the_tool_itself_trusts() -> None:
    guard, state = ReactorGuard(), {}
    temp, backup = Action("read_sensor", {"name": "temp"}), Action("read_sensor", {"name": "temp_backup"})
    other = Action("get_alarms", {})
    guard.observe(temp, reading(184.0, 3, 3, confidence=0.5), 3, state)  # drifting sensor, low confidence
    assert not state.get("armed") and state["temp_failed"] and guard.check(other, 4, state) is None
    guard.observe(temp, reading(184.0, 5, 2, ok=False), 5, state)  # cached value from step 2
    assert not state.get("armed") and "temp_step" not in state
    guard.observe(temp, reading(None, 6, 6, ok=False), 6, state)  # timeout
    msg = guard.check(other, 7, state)
    assert msg is not None and "temp_backup (temp is not returning a usable value)" in msg
    guard.observe(backup, reading(184.0, 7, 7, confidence=0.8), 7, state)  # trusted and off target
    assert state["armed"] and "CONTROL REQUIRED" in (guard.check(other, 8, state) or "")
    guard.observe(backup, reading(180.4, 8, 8, confidence=0.8), 8, state)  # trusted and back on target
    assert not state["armed"] and guard.check(other, 9, state) is None
    state["armed"] = True
    guard.observe(Action("set_coolant", {"pct": 150}), ToolOutcome(None, invalid_args=True), 9, state)
    assert state["armed"]  # a command the tool layer rejected does not count as a control action
    summary = Action("write_note", {"key": "context_summary", "text": "..."}, meta={"note": AUTO_SUMMARY_NOTE})
    assert guard.check(summary, 10, state) is None  # the agent's own context digest is never refused
    assert "CONTROL REQUIRED" in (guard.check(Action("write_note", {"key": "k", "text": "x"}), 10, state) or "")


def test_llm_agent_sees_refusals_as_tool_errors_and_as_nudges() -> None:
    cycle = [READ_P, READ_V, READ_F]

    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
        last = body["messages"][-1]
        if n <= MAX_READ_AGE:  # steps 0..5
            return completion(call(*cycle[n % 3], cid=f"r{n}"))
        if n == MAX_READ_AGE + 1:  # step 6: a tool call that is out of order
            return completion(call("get_alarms", cid="late"))
        if n == MAX_READ_AGE + 2:  # step 7: the refusal came back as that call's result; now reply with text only
            assert last["role"] == "tool" and last["tool_call_id"] == "late"
            assert "TEMPERATURE READING REQUIRED" in last["content"] and '"ok": false' in last["content"]
            return completion(content="Everything looks normal.")
        if n == MAX_READ_AGE + 3:  # step 8: the requirement rides on the nudge
            assert last["role"] == "user" and "without a tool call" in last["content"]
            assert "TEMPERATURE READING REQUIRED" in last["content"]
            return completion(call(*READ_T, cid="t"))
        return completion(call("finish", FINISH, cid="f"))

    spec = make_spec("llm", horizon=14, seed=3, variants=["guard"], llm=LLMConfig(model="fake-model").to_dict())
    server = FakeServer(reply)
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(server))
    v, store = run(spec, agent)
    recs = store.records(spec.run_id)
    assert [r["step"] for r in recs if r["flags"]["guard_blocked"]] == [6, 7]
    assert recs[8]["tool"] == "read_sensor" and not recs[8]["flags"]["guard_blocked"]
    assert v["invalid_actions"] == 0 and v["end_reason"] == "finished"


# ---- bookkeeping -----------------------------------------------------------------------------
def test_variants_are_recorded_validated_and_reported_separately(tmp_path: Path) -> None:
    assert _variants("guard, ctx_rule", "reactor") == ["ctx_rule", "guard"]  # canonical order
    with pytest.raises(SystemExit):
        _variants("ctx_rule,nope", "reactor")
    spec = make_spec("pid", variants=["tool_hint", "guard"])
    assert policy_label(spec) == "pid+tool_hint+guard"
    assert policy_label(make_spec("llm", llm={"model": "m"}, variants=["guard"])) == "llm:m+guard"
    runs = tmp_path / "runs"
    assert main(["--runs-dir", str(runs), "run", "--policy", "pid", "--horizon", "20", "--seeds", "1",
                 "--name", "v", "--variant", "guard"]) == 0
    assert Store(runs / "hb.sqlite").spec("v-pid-rich-h20-dev000").variants == ["guard"]


def test_the_levers_leave_the_reference_controller_in_control() -> None:
    """Public dev seeds only. The PI controller already does what the levers ask for, so they
    must not cost it control; the guard may refuse a few admin steps at a session boundary."""
    for variants in (["tool_hint"], ["guard"], ["ctx_rule", "tool_hint", "guard"]):
        kept = refused = 0
        for seed in range(10):
            spec = make_spec("pid", horizon=60, seed=seed, variants=variants)
            v, store = run(spec)
            kept += v["checks"]["no_lost_control"]
            refused += sum(1 for r in store.records(spec.run_id) if r["flags"].get("guard_blocked"))
        assert kept == 10 and refused <= 5, (variants, kept, refused)
