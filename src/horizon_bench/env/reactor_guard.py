"""The three opt-in levers for the reactor family (RunSpec.variants). Each changes one layer and
nothing else, so their effect can be measured against the same seeds:

* ``ctx_rule``  - context: the system prompt gains an explicit control procedure.
* ``tool_hint`` - tool feedback: a fresh temperature reading (rich tools) also carries its deviation
                  from the setpoint, an in-band flag, the trend and, when off target, a one-line hint.
* ``guard``     - control constraint: the harness refuses out-of-order actions (this module).

All three use only what the agent can observe (sensor readings), never the true state.
"""

from __future__ import annotations

from typing import Any

from horizon_bench.agents.base import AUTO_SUMMARY_NOTE, Action
from horizon_bench.env.reactor import PlantConfig
from horizon_bench.tools import ToolOutcome, unwrap

VARIANTS = ("ctx_rule", "tool_hint", "guard")
DEV_LIMIT = 1.5  # degC from the setpoint that calls for a control action (3 sigma of TT-102 noise)
READ_EVERY = 4  # ctx_rule: the procedure asks for a temperature reading at least this often
MAX_READ_AGE = 6  # guard: the latest fresh temperature reading may not be older than this (the scripted
#                   PI controller's own longest gap, at a session boundary, so the guard never refuses it)
ARM_GRACE = 2  # guard: temperature re-reads still accepted after an off-target reading, before control is forced
CONF_MIN = 0.7  # guard: a rich-mode reading below this confidence is not acted on (the PI controller's own rule)
TREND_MIN = 0.3  # degC per step, over at least two steps, before a trend is named in a hint
TEMP_SENSORS = ("temp", "temp_backup")
CONTROL_TOOLS = ("set_coolant", "set_feed")


def control_procedure(cfg: PlantConfig) -> str:
    """Text appended to the system prompt by ``ctx_rule``."""
    sp = cfg.setpoint
    return f"""

Control procedure (apply it on every step):
- Control to the setpoint ({sp:.0f} degC), not to the edge of the band.
- After each temperature reading, compare it with the setpoint. If it is more than {DEV_LIMIT} degC away,
  your next call must be set_coolant with pct = 50 + 6 x (reading - {sp:.0f}), limited to 0-100. That closes
  the valve when the reactor is cold and opens it when the reactor is hot.
- Read the temperature again within {READ_EVERY} steps of your last reading. If temp fails, read temp_backup."""


def reading_fields(value: float, step: int, prev: tuple[float, int] | None, cfg: PlantConfig) -> dict[str, Any]:
    """Extra fields ``tool_hint`` adds to a fresh temperature reading. `prev` is the previous fresh
    reading of the same sensor as (value, step)."""
    dev = round(value - cfg.setpoint, 2)
    trend = None
    if prev is not None and step > prev[1]:
        trend = round((value - prev[0]) / (step - prev[1]), 2)
    hint = None
    if abs(dev) > DEV_LIMIT:
        side, action = ("below", "reduce cooling now (set_coolant with a lower pct)") if dev < 0 else (
            "above", "add cooling now (set_coolant with a higher pct)")
        moving = ""
        if trend is not None and prev is not None and step - prev[1] >= 2 and abs(trend) >= TREND_MIN:
            if (trend < 0) == (dev < 0):
                moving = " and still falling" if trend < 0 else " and still rising"
            else:
                moving, action = " but moving back toward it", "keep the valve where it is and read again"
        hint = f"reading is {abs(dev):.1f} degC {side} setpoint{moving}: {action}"
    return {"setpoint": cfg.setpoint, "deviation": dev, "in_band": abs(dev) <= cfg.band,
            "trend_per_step": trend, "hint": hint}


def _temp_sensor(action: Action) -> str | None:
    """The sensor name if the action is a temperature read, else None."""
    if action.tool != "read_sensor" or not isinstance(action.args, dict):
        return None
    name = action.args.get("name")
    return name if name in TEMP_SENSORS else None


class ReactorGuard:
    """Two rules, checked before an action runs. Both use only readings the agent itself obtained.

    1. Must act. If the latest trusted temperature reading is more than DEV_LIMIT from the setpoint
       and no control action has followed it, only set_coolant / set_feed are accepted. Up to
       ARM_GRACE temperature re-reads are accepted first, so the agent may cross-check a sensor.
    2. Must look. If there is no trusted temperature reading from the last MAX_READ_AGE steps, only a
       temperature read is accepted.

    "Trusted" means fresh (measured at this step) and, in rich mode, ok with confidence >= CONF_MIN,
    so the guard never forces a control action on a reading the tool itself marks as doubtful.
    A refused action is not executed; the step still passes, as it would on a real plant. finish()
    is never refused. State lives in the run checkpoint, so it survives a context reset or a crash.
    """

    def __init__(self, cfg: PlantConfig | None = None) -> None:
        self.cfg = cfg or PlantConfig()

    def check(self, action: Action, step: int, state: dict[str, Any]) -> str | None:
        if action.tool == "finish" or action.meta.get("note") == AUTO_SUMMARY_NOTE:
            return None
        if state.get("armed"):
            if action.tool in CONTROL_TOOLS:
                return None
            if _temp_sensor(action) is not None and int(state.get("armed_reads", 0)) < ARM_GRACE:
                return None
            dev = float(state["temp"]) - self.cfg.setpoint
            side, fix = ("below", "lower") if dev < 0 else ("above", "higher")
            return (f"CONTROL REQUIRED: the last temperature reading ({state['temp']:.2f} degC at step "
                    f"{state['temp_step']}) is {abs(dev):.1f} degC {side} the setpoint and no control action has "
                    f"followed it. Call set_coolant with a {fix} pct (or set_feed) now; this call was not executed.")
        seen = state.get("temp_step")
        if (seen is None and step >= MAX_READ_AGE) or (seen is not None and step - seen > MAX_READ_AGE):
            if _temp_sensor(action) is not None:
                return None
            age = "has not been read yet" if seen is None else f"was last read {step - seen} steps ago"
            which = "temp_backup (temp is not returning a usable value)" if state.get("temp_failed") else "temp"
            return (f"TEMPERATURE READING REQUIRED: the reactor temperature {age}. Call read_sensor with name "
                    f"{which} now; this call was not executed.")
        return None

    def observe(self, action: Action, outcome: ToolOutcome, step: int, state: dict[str, Any]) -> None:
        sensor = _temp_sensor(action)
        if sensor is not None:
            value, ok, meta = unwrap(outcome.result)
            fresh = (outcome.reading is not None and int(outcome.reading["data_step"]) == step
                     and isinstance(value, (int, float)))
            trusted = fresh and (not meta or (ok and float(meta.get("confidence", 1.0)) >= CONF_MIN))
            if state.get("armed"):
                state["armed_reads"] = int(state.get("armed_reads", 0)) + 1
            if trusted:
                off_target = abs(float(value) - self.cfg.setpoint) > DEV_LIMIT
                if not (off_target and state.get("armed")):
                    state["armed_reads"] = 0
                state["temp"], state["temp_step"], state["armed"] = float(value), step, off_target
                if sensor == "temp":
                    state["temp_failed"] = False
            elif sensor == "temp":
                state["temp_failed"] = True
        elif outcome.decision_key == "temperature" and not outcome.invalid_args:
            state["armed"], state["armed_reads"] = False, 0
