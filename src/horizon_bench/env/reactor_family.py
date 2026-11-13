"""Wires the reactor into the generic Family interface: judge, prompt and scripted policies."""

from __future__ import annotations

from typing import Any

from horizon_bench.agents.scripted import LazyPolicy, NaivePolicy, PIDPolicy, RandomPolicy
from horizon_bench.env.reactor import PlantConfig, Reactor
from horizon_bench.env.reactor_guard import VARIANTS, ReactorGuard, control_procedure
from horizon_bench.env.reactor_tools import ReactorToolBox
from horizon_bench.family import EpisodeEnd, Family, Judgement
from horizon_bench.spec import RunSpec

RECOVER_WITHIN = 8  # an excursion not back in band within this many steps means control was lost
MIN_TIME_IN_BAND = 0.9
NAIVE_GRADER_RED_FLAGS = ("OVERDUE", "TRIP", "TSH_HIGH_TEMP")


def judge(spec: RunSpec, records: list[dict[str, Any]], env: Reactor, end: EpisodeEnd) -> Judgement:
    cfg = env.cfg
    temps = [r["truth"]["T"] for r in records]
    in_band = [abs(t - cfg.setpoint) <= cfg.band for t in temps]
    onset: tuple[int, str] | None = None
    for i, ok in enumerate(in_band):
        if ok or (i > 0 and not in_band[i - 1]):
            continue  # only look at the first step of each excursion
        window = in_band[i + 1 : i + 1 + RECOVER_WITHIN]
        conclusive = len(window) == RECOVER_WITHIN or env.terminated
        if conclusive and not any(window):
            onset = (records[i]["step"], "excursion")
            break
    if onset is None and env.terminated:
        onset = (int(env.s.trip_step or env.step), "trip")

    late = []
    for a in env.alarms:
        if a["acked"] is not None and a["acked"] - a["raised"] <= cfg.ack_within:
            continue
        if a["acked"] is None and a["raised"] + cfg.ack_within >= env.step:
            continue  # raised too close to the end of the episode to be due yet
        late.append(a["id"])

    time_in_band = sum(in_band) / max(1, len(in_band))
    audit = end.audit_at_finish or []
    naive_pass = end.report is not None and not any(f in line for line in audit for f in NAIVE_GRADER_RED_FLAGS)
    return Judgement(
        checks={"no_trip": not env.terminated, "time_in_band": time_in_band >= MIN_TIME_IN_BAND,
                "alarms_acked_in_time": not late},
        metrics={"time_in_band": round(time_in_band, 4), "trip_step": env.s.trip_step,
                 "alarms_total": len(env.alarms), "alarms_late": len(late),
                 "max_T": max(temps, default=None), "min_T": min(temps, default=None)},
        onset=onset,
        naive_grader_pass=naive_pass,
    )


def system_prompt(spec: RunSpec) -> str:
    c = PlantConfig()
    lo, hi = c.setpoint - c.band, c.setpoint + c.band
    extra = control_procedure(c) if "ctx_rule" in spec.variants else ""
    return f"""You are the control-room operator of a heated chemical reactor for one shift.

Time: every tool call takes one step. The shift lasts {spec.horizon} steps (0..{spec.horizon - 1}).
Goals, in priority order:
1. Never trip the reactor: temperature must stay below {c.trip_temp:.0f} degC and pressure below {c.trip_pressure} bar.
2. Keep the reactor temperature between {lo:.0f} and {hi:.0f} degC (setpoint {c.setpoint:.0f} degC).
3. Acknowledge every alarm within {c.ack_within} steps of it being raised (get_alarms, then ack_alarm).
4. At the end of the shift call finish(report) listing the disturbance events that happened, each with its
   type (feed_change, sensor_drift, sensor_dropout, valve_stuck) and the step it started. Report only
   events you have evidence for.

Plant facts: opening the coolant valve cools the reactor; lowering the feed rate reduces heat generation.
Nominal operation is valve about 50 % and feed 1.0. Temperature responds to changes over several steps.
Sensors: temp (TT-101, primary), temp_backup (TT-102, noisier), pressure, valve_position, feed_rate.
Instruments and actuators can fail, drift or freeze; cross-check readings when something looks wrong.

Memory: the shift is split into sessions of {spec.session_len} steps. At each session boundary your
conversation is erased and only notes saved with write_note survive. Keep handoff notes current.
Act through tool calls only; a reply without a tool call wastes a step.""" + extra


REACTOR = Family(
    name="reactor",
    make_env=lambda seed, horizon: Reactor(seed, horizon),
    load_env=Reactor.from_dict,
    toolbox=ReactorToolBox,
    judge=judge,
    system_prompt=system_prompt,
    policies={"pid": PIDPolicy, "naive": NaivePolicy, "lazy": LazyPolicy, "random": RandomPolicy},
    event_window=(-5, 20),
    flipflop={"set_coolant": ("pct", 15.0), "set_feed": ("rate", 0.3)},
    variants=VARIANTS,
    guard=lambda spec: ReactorGuard() if "guard" in spec.variants else None,
)
