"""Sanity checks for the three levers on PUBLIC dev seeds with scripted policies (no model, no eval seeds).

    python scripts/retest_sanity.py            # prints a markdown table, about 10 s

Questions answered before any model run:
  1. Do the levers leave a controller that already behaves well alone?
  2. Is the ctx_rule procedure enough to keep control if it is followed to the letter?
  3. Can the guard keep control for an operator that never acts unless it is refused?
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from horizon_bench.agents.base import Action, Observation, Policy, ScriptedPolicy
from horizon_bench.runner import Runner
from horizon_bench.spec import RunSpec, make_run_id
from horizon_bench.store import Store
from horizon_bench.tools import unwrap

SEEDS, HORIZON, SETPOINT, DEV_LIMIT = 20, 60, 180.0, 1.5
OTHER = ("pressure", "valve_position", "feed_rate")


def p_law(temp: float) -> dict[str, float]:
    return {"pct": round(min(100.0, max(0.0, 50.0 + 6.0 * (temp - SETPOINT))), 1)}


class ProcedureFollower(ScriptedPolicy):
    """Does exactly what the ctx_rule text says and nothing else: no alarms, no notes, no report."""

    def __init__(self, spec: RunSpec) -> None:
        super().__init__(spec.seed)
        self.mem = {"last": None, "temp": None, "act": False, "failed": False, "n": 0}

    def start_session(self, session: int, step: int) -> None:
        self.mem = {"last": None, "temp": None, "act": False, "failed": False, "n": self.mem["n"]}

    def act(self, obs: Observation) -> Action:
        m = self.mem
        last = m["last"]
        was_temp = bool(last) and last[0] == "read_sensor" and last[1]["name"].startswith("temp")
        if was_temp:
            value, ok, meta = unwrap(obs.result)
            if isinstance(value, (int, float)) and ok and (not meta or meta.get("age_steps") == 0):
                m["temp"], m["act"], m["failed"] = float(value), abs(float(value) - SETPOINT) > DEV_LIMIT, False
            else:
                m["failed"] = True
        m["n"] += 1
        if m["act"]:
            m["act"] = False
            call: list[Any] = ["set_coolant", p_law(m["temp"])]
        elif was_temp and not m["failed"]:
            call = ["read_sensor", {"name": OTHER[m["n"] % 3]}]
        else:
            call = ["read_sensor", {"name": "temp_backup" if m["failed"] else "temp"}]
        m["last"] = call
        return Action(call[0], call[1])


class Watcher(ScriptedPolicy):
    """The failure pattern seen in the traces: cycles through five sensors and a text-only step and never
    controls. If the guard refuses a call it obeys: with the proportional law, or timidly (5 points)."""

    CYCLE = ("temp", "pressure", "valve_position", "feed_rate", "temp_backup", None)

    def __init__(self, spec: RunSpec, timid: bool = False) -> None:
        super().__init__(spec.seed)
        self.timid = timid
        self.mem = {"i": 0, "temp": SETPOINT, "valve": 50.0, "last": None}

    def start_session(self, session: int, step: int) -> None:
        self.mem = {**self.mem, "i": 0}

    def act(self, obs: Observation) -> Action:
        m = self.mem
        value, ok, meta = unwrap(obs.result)
        if m["last"] in ("temp", "temp_backup") and isinstance(value, (int, float)) and ok:
            m["temp"] = float(value)
        text = " ".join(obs.warnings) + " " + str(meta.get("error") if meta else obs.result)
        if "CONTROL REQUIRED" in text:
            m["valve"] = p_law(m["temp"])["pct"] if not self.timid else min(
                100.0, max(0.0, m["valve"] + (5.0 if m["temp"] > SETPOINT else -5.0)))
            m["last"] = "control"
            return Action("set_coolant", {"pct": round(m["valve"], 1)})
        if "TEMPERATURE READING REQUIRED" in text:
            m["last"] = "temp_backup" if "temp_backup" in text else "temp"
            return Action("read_sensor", {"name": m["last"]})
        name = self.CYCLE[m["i"] % len(self.CYCLE)]
        m["i"] += 1
        m["last"] = name
        return Action(None) if name is None else Action("read_sensor", {"name": name})


def cell(label: str, policy: str, variants: list[str], factory: Callable[[RunSpec], Policy] | None = None) -> str:
    kept = success = refused = 0
    in_band = 0.0
    for seed in range(SEEDS):
        spec = RunSpec(run_id=make_run_id("sanity", policy, "rich", HORIZON, "dev", seed), batch="sanity",
                       policy=policy, tools="rich", horizon=HORIZON, seed=seed, split="dev", seed_index=seed,
                       variants=variants)
        store = Store(":memory:")
        v = Runner(store, runs_dir=None).start(spec, factory(spec) if factory else None)
        kept += v["checks"]["no_lost_control"]
        success += v["success"]
        in_band += v["metrics"]["time_in_band"]
        refused += sum(1 for r in store.records(spec.run_id) if r["flags"].get("guard_blocked"))
    return (f"| {label} | {', '.join(variants) or '-'} | {kept}/{SEEDS} | {success}/{SEEDS} | "
            f"{in_band / SEEDS:.3f} | {refused / SEEDS:.1f} |")


def main() -> None:
    print("| scripted policy | variants | control kept | success | time in band | guard refusals / run |")
    print("|---|---|---|---|---|---|")
    for variants in ([], ["tool_hint"], ["guard"], ["ctx_rule", "tool_hint", "guard"]):
        print(cell("pid (reference PI controller)", "pid", variants))
    print(cell("follows the ctx_rule procedure literally", "procedure", [], ProcedureFollower))
    print(cell("watcher: never controls", "watcher", [], Watcher))
    print(cell("watcher, obeys refusals with the proportional law", "watcher", ["guard"], Watcher))
    print(cell("watcher, obeys refusals with 5-point moves", "watcher", ["guard"], lambda s: Watcher(s, timid=True)))


if __name__ == "__main__":
    main()
