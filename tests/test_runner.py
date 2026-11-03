from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ScriptPolicy, make_spec, run
from horizon_bench.runner import KILL_ENV, LoopDetector, Runner, SimulatedCrash, replay
from horizon_bench.store import Store


def _strip(v: dict) -> dict:
    return {k: val for k, val in v.items() if k != "run_id"}


def test_kill_and_resume_matches_uninterrupted_run() -> None:
    spec = make_spec("pid", "bare", horizon=120, seed=4)
    whole, s1 = run(spec)
    s2 = Store(":memory:")
    with pytest.raises(SimulatedCrash):
        Runner(s2, runs_dir=None).start(spec, crash_after=57)
    assert s2.status(spec.run_id) == "running" and len(s2.records(spec.run_id)) == 58
    resumed = Runner(s2, runs_dir=None).resume(spec.run_id)
    assert s1.records(spec.run_id) == s2.records(spec.run_id)
    assert whole == resumed


def test_sigkill_and_resume_through_the_cli(tmp_path: Path) -> None:
    """A real SIGKILL of the `hb run` process, then `hb resume`, ends identical to a clean run."""
    hb = [sys.executable, "-m", "horizon_bench.cli", "--runs-dir", str(tmp_path / "runs")]
    common = ["--policy", "pid", "--tools", "bare", "--horizon", "120", "--seeds", "1"]
    env = {**os.environ, KILL_ENV: "63"}
    killed = subprocess.run([*hb, "run", *common, "--name", "killed"], env=env, capture_output=True, cwd=tmp_path)
    assert killed.returncode == -9
    clean_env = {k: v for k, v in os.environ.items() if k != KILL_ENV}
    subprocess.run([*hb, "resume", "killed-pid-bare-h120-dev000"], env=clean_env, check=True, cwd=tmp_path)
    subprocess.run([*hb, "run", *common, "--name", "clean"], env=clean_env, check=True, cwd=tmp_path,
                   capture_output=True)
    def artifact(name: str, file: str) -> str:
        return (tmp_path / "runs" / f"{name}-pid-bare-h120-dev000" / file).read_text()

    assert artifact("killed", "trace.jsonl") == artifact("clean", "trace.jsonl")
    killed_v, clean_v = (json.loads(artifact(n, "verdict.json")) for n in ("killed", "clean"))
    assert _strip(killed_v) == _strip(clean_v)


def test_replay_reproduces_and_detects_tampering() -> None:
    spec = make_spec("pid", "rich", horizon=120, seed=6)
    _, store = run(spec)
    assert replay(store, spec.run_id)["ok"]
    rec = store.records(spec.run_id)[40]
    rec["result"] = {"value": 999.0, "ok": True, "error": None, "confidence": 1.0, "age_steps": 0, "latency_ms": 1}
    store.db.execute("UPDATE steps SET record = ? WHERE run_id = ? AND step = 40", (json.dumps(rec), spec.run_id))
    out = replay(store, spec.run_id)
    assert not out["ok"] and out["env_divergence"]["step"] == 40


def test_loop_detector() -> None:
    d = LoopDetector({"set_coolant": ("pct", 15.0)})
    assert [d.update("get_alarms", {}) for _ in range(5)][-1] is not None
    d = LoopDetector({"set_coolant": ("pct", 15.0)})
    flags = [d.update("set_coolant", {"pct": p}) for p in (50, 80, 40, 90, 30)]
    assert flags[:4] == [None] * 4 and "flip-flopping" in str(flags[4])
    d = LoopDetector({"set_coolant": ("pct", 15.0)})
    assert all(d.update("set_coolant", {"pct": p}) is None for p in (50, 52, 49, 53, 48, 51))


def test_loop_is_a_failure_onset_and_the_agent_is_warned(script: type[ScriptPolicy]) -> None:
    v, _ = run(make_spec(horizon=30), script([("read_sensor", {"name": "temp"})]))
    assert v["onset_cause"] == "loop" and v["onset_step"] == 4
    assert v["loop_events"] == 1


def test_invalid_action_streak_is_a_failure_onset(script: type[ScriptPolicy]) -> None:
    calls = [("read_sensor", {"name": "temp"}), ("set_coolant", {"pct": 150}), ("read_sensor", {"name": "nope"}),
             ("teleport", {}), ("get_alarms", {})] + [("read_sensor", {"name": n}) for n in ("temp", "pressure")] * 30
    v, _ = run(make_spec(horizon=30), script(calls))
    assert v["onset_cause"] == "invalid_streak" and v["onset_step"] == 3
    assert v["invalid_actions"] == 3


def test_stale_reads_counted_for_dropout_in_bare_mode_only() -> None:
    # during a TT-101 dropout bare mode serves the cached value as a plain number
    bare, sb = run(make_spec("pid", "bare", seed=4))
    rich, _ = run(make_spec("pid", "rich", seed=4))
    assert bare["stale_read_errors"] > 0 and rich["stale_read_errors"] == 0
    stale = [r for r in sb.records(make_spec("pid", "bare", seed=4).run_id) if r["flags"]["stale_read_used"]]
    assert all(r["basis_age"] > 3 and "sensor_dropout" in r["truth"]["active"] for r in stale)


def test_acting_without_any_reading_is_stale(script: type[ScriptPolicy]) -> None:
    _, store = run(make_spec(horizon=10), script([("set_coolant", {"pct": 55}), ("get_alarms", {}),
                                                   ("read_notes", {})]))
    first = store.records(make_spec(horizon=10).run_id)[0]
    assert first["flags"]["stale_read_used"] and first["basis_age"] is None


def test_hb_run_resumes_an_interrupted_run_instead_of_skipping_it(tmp_path: Path) -> None:
    from horizon_bench.cli import main

    runs = tmp_path / "runs"
    args = ["--runs-dir", str(runs), "run", "--policy", "pid", "--tools", "rich", "--horizon", "40", "--seeds", "1",
            "--name", "t"]
    assert main(args) == 0
    store = Store(runs / "hb.sqlite")
    run_id = "t-pid-rich-h40-dev000"
    done = store.verdict(run_id)
    # pretend the process was killed after step 10: drop later steps and mark the run as running again
    store.db.execute("DELETE FROM steps WHERE run_id = ? AND step > 10", (run_id,))
    store.db.execute("DELETE FROM checkpoints WHERE run_id = ? AND step > 10", (run_id,))
    store.db.execute("UPDATE runs SET status = 'running', verdict = NULL WHERE run_id = ?", (run_id,))
    store.db.commit()
    assert main(args) == 0
    assert Store(runs / "hb.sqlite").status(run_id) == "done"
    assert Store(runs / "hb.sqlite").verdict(run_id) == done
