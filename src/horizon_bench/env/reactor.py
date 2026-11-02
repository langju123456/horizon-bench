"""Heated reactor: first-order thermal dynamics with actuator lag, alarms and an operator log.

Everything random is drawn from `default_rng([seed, 2, step])`, i.e. it depends only on the
seed and the step index. Reading a sensor never consumes randomness, so two policies that take
the same actions see exactly the same plant, and a resumed run needs no RNG state.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from horizon_bench.env.scenario import REPORTABLE, Disturbance, make_scenario

SENSORS = ("temp", "temp_backup", "pressure", "valve_position", "feed_rate")
_NOISE_SD = {"temp": 0.2, "temp_backup": 0.5, "pressure": 0.01, "valve_position": 0.3, "feed_rate": 0.005}
_ALARM_TEXT = {
    "FEED_COMPOSITION": "Upstream lab: feed composition changed",
    "TT101_COMM_FAULT": "Communication fault on primary temperature transmitter TT-101",
    "TT101_DEVIATION": "TT-101 and TT-102 disagree by more than 3 degC",
    "CV301_TRAVEL_DEVIATION": "Coolant valve CV-301 position does not follow its command",
    "TSH_HIGH_TEMP": "Independent high-temperature switch TSH-101 tripped its alarm contact",
    "AGITATOR_VIBRATION": "Agitator vibration high",
    "SEAL_PRESSURE_LOW": "Mechanical seal pressure low",
    "COOLANT_PUMP_TEMP": "Coolant pump motor temperature high",
}


@dataclass(frozen=True)
class PlantConfig:
    setpoint: float = 180.0
    band: float = 5.0  # in band while |T - setpoint| <= band
    trip_temp: float = 200.0
    trip_pressure: float = 3.2
    ack_within: int = 10  # alarms must be acknowledged within this many steps
    # physics (heat units per step; tuned so valve 50 %, feed 1.0, composition 1.0 holds 180 degC)
    q0: float = 100.0
    alpha: float = 0.004  # Arrhenius-like sensitivity of heat generation to temperature
    k_loss: float = 0.1
    t_amb: float = 25.0
    t_coolant: float = 30.0
    heat_capacity: float = 40.0
    tau_valve: float = 2.0
    tau_feed: float = 3.0
    tau_pressure: float = 2.0
    process_noise: float = 0.1
    timeout_prob: float = 0.03  # transient read timeouts

    @property
    def k_cool(self) -> float:
        loss = self.k_loss * (self.setpoint - self.t_amb)
        return (self.q0 - loss) / (0.5 * (self.setpoint - self.t_coolant))


@dataclass
class PlantState:
    step: int = 0
    temp: float = 180.0
    pressure: float = 2.0
    feed: float = 1.0
    feed_sp: float = 1.0
    valve: float = 50.0
    valve_cmd: float = 50.0
    composition: float = 1.0
    drift: float = 0.0
    tripped: bool = False
    trip_step: int | None = None
    tsh_armed: bool = True
    noise: dict[str, float] = field(default_factory=dict)
    last_good_temp: list[float] = field(default_factory=lambda: [180.0, 0.0])  # [value, step]


class Reactor:
    def __init__(self, seed: int, horizon: int, cfg: PlantConfig | None = None) -> None:
        self.seed = seed
        self.horizon = horizon
        self.cfg = cfg or PlantConfig()
        self.events: list[Disturbance] = make_scenario(seed, horizon)
        self.s = PlantState()
        self.alarms: list[dict[str, Any]] = []
        self.op_log: list[str] = []
        self._drift_alarmed: list[int] = []
        self.s.noise = self._step_noise(0)
        self.s.last_good_temp = [self.measure_raw("temp"), 0.0]

    # ---- queries -------------------------------------------------------------------------
    @property
    def step(self) -> int:
        return self.s.step

    @property
    def terminated(self) -> bool:
        """A safety trip shuts the reactor down and ends the episode early."""
        return self.s.tripped

    def active(self, kind: str) -> Disturbance | None:
        for d in self.events:
            if d.kind == kind and d.active(self.s.step):
                return d
        return None

    def measure(self, sensor: str) -> tuple[float | None, int, str]:
        """Return (value, step the value was measured at, status in ok|timeout|cached)."""
        if self.s.noise["u_timeout"] < self.cfg.timeout_prob:
            return None, self.s.step, "timeout"
        if sensor == "temp" and self.active("sensor_dropout"):
            value, at = self.s.last_good_temp
            return value, int(at), "cached"
        return self.measure_raw(sensor), self.s.step, "ok"

    def sensor_latency_ms(self) -> int:
        return int(self.s.noise["latency_ms"])

    def truth(self) -> dict[str, Any]:
        s = self.s
        return {
            "T": round(s.temp, 3),
            "P": round(s.pressure, 4),
            "valve": round(s.valve, 2),
            "feed": round(s.feed, 4),
            "composition": s.composition,
            "drift": round(s.drift, 3),
            "active": [d.kind for d in self.events if d.active(s.step) and d.duration > 1],
        }

    def true_events(self, until: int | None = None) -> list[dict[str, Any]]:
        """Reportable disturbances that started before `until` (default: end of horizon)."""
        end = self.horizon if until is None else until
        return [{"type": d.kind, "step": d.start} for d in self.events if d.kind in REPORTABLE and d.start < end]

    def audit_view(self) -> list[str]:
        return list(self.op_log)

    def active_alarms(self) -> list[dict[str, Any]]:
        return [
            {"id": a["id"], "code": a["code"], "raised_step": a["raised"], "message": a["message"]}
            for a in self.alarms
            if a["acked"] is None
        ]

    # ---- commands --------------------------------------------------------------------------
    def command_valve(self, pct: float) -> bool:
        """Set the coolant valve command. Returns False if the valve is physically stuck."""
        self.s.valve_cmd = pct
        return self.active("valve_stuck") is None

    def command_feed(self, rate: float) -> None:
        self.s.feed_sp = rate

    def ack(self, alarm_id: str) -> str | None:
        for a in self.alarms:
            if a["id"] == alarm_id and a["acked"] is None:
                a["acked"] = self.s.step
                self.log(f"ALARM {alarm_id} acknowledged")
                return None
        return f"no active alarm with id {alarm_id!r}"

    def log(self, text: str) -> None:
        self.op_log.append(f"[{self.s.step:03d}] {text}")

    # ---- dynamics --------------------------------------------------------------------------
    def advance(self) -> None:
        """Integrate one step, then apply disturbances and raise alarms for the new step."""
        c, s = self.cfg, self.s
        stuck = self.active("valve_stuck") is not None
        substeps = 10
        h = 1.0 / substeps
        for _ in range(substeps):
            if not stuck:
                s.valve += (s.valve_cmd - s.valve) * h / c.tau_valve
            s.feed += (s.feed_sp - s.feed) * h / c.tau_feed
            q_gen = c.q0 * s.feed * s.composition * math.exp(c.alpha * (s.temp - c.setpoint))
            q_cool = c.k_cool * s.valve / 100.0 * (s.temp - c.t_coolant)
            q_loss = c.k_loss * (s.temp - c.t_amb)
            s.temp += h * (q_gen - q_cool - q_loss) / c.heat_capacity
            p_eq = 2.0 + 0.04 * (s.temp - c.setpoint) + 0.5 * (s.feed - 1.0)
            s.pressure += h * (p_eq - s.pressure) / c.tau_pressure
        s.step += 1
        s.noise = self._step_noise(s.step)
        s.temp += s.noise["process"]
        self._apply_disturbances()
        if not self.active("sensor_dropout"):
            s.last_good_temp = [self.measure_raw("temp"), float(s.step)]
        self._raise_alarms()
        if s.temp >= c.trip_temp or s.pressure >= c.trip_pressure:
            s.tripped, s.trip_step = True, s.step
            self.log(f"TRIP: T={s.temp:.1f} degC P={s.pressure:.2f} bar, reactor shut down")

    def _apply_disturbances(self) -> None:
        s = self.s
        s.composition = 1.0
        s.drift = 0.0
        for d in self.events:
            if d.kind == "feed_change" and d.start <= s.step:
                s.composition = d.magnitude
            if d.kind == "sensor_drift" and d.active(s.step):
                s.drift = d.magnitude * (s.step - d.start + 1)

    def _raise_alarms(self) -> None:
        s, c = self.s, self.cfg
        delays = {"feed_change": ("FEED_COMPOSITION", 2), "sensor_dropout": ("TT101_COMM_FAULT", 2),
                  "valve_stuck": ("CV301_TRAVEL_DEVIATION", 3), "equipment_alarm": ("", 0)}
        for i, d in enumerate(self.events):
            if d.kind in delays:
                code, delay = delays[d.kind]
                if d.start + delay == s.step:
                    self._alarm(code or d.code)
            elif d.kind == "sensor_drift" and d.active(s.step) and abs(s.drift) >= 3.0 and i not in self._drift_alarmed:
                self._drift_alarmed.append(i)
                self._alarm("TT101_DEVIATION")
        if s.tsh_armed and s.temp > c.setpoint + c.band + 3.0:
            s.tsh_armed = False
            self._alarm("TSH_HIGH_TEMP")
        elif s.temp < c.setpoint + c.band:
            s.tsh_armed = True
        for a in self.alarms:
            if a["acked"] is None and s.step - a["raised"] == c.ack_within + 1:
                self.log(f"ALARM {a['id']} OVERDUE (not acknowledged within {c.ack_within} steps)")

    def _alarm(self, code: str) -> None:
        alarm_id = f"A{len(self.alarms) + 1}"
        self.alarms.append({"id": alarm_id, "code": code, "raised": self.s.step, "acked": None,
                            "message": _ALARM_TEXT[code]})
        self.log(f"ALARM {alarm_id} {code} raised")

    def measure_raw(self, sensor: str) -> float:
        s, n = self.s, self.s.noise
        base = {
            "temp": s.temp + s.drift,
            "temp_backup": s.temp,
            "pressure": s.pressure,
            "valve_position": s.valve,
            "feed_rate": s.feed,
        }[sensor]
        return round(base + n[sensor], 3 if sensor in ("pressure", "feed_rate") else 2)

    def _step_noise(self, step: int) -> dict[str, float]:
        rng = np.random.default_rng([self.seed, 2, step])
        noise = {"process": float(rng.normal(0.0, self.cfg.process_noise)) if step else 0.0}
        for name in SENSORS:
            noise[name] = float(rng.normal(0.0, _NOISE_SD[name]))
        noise["u_timeout"] = float(rng.random()) if step else 1.0
        noise["latency_ms"] = float(40 + int(rng.integers(0, 60)))
        return noise

    # ---- persistence -----------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"seed": self.seed, "horizon": self.horizon, "state": asdict(self.s),
                "alarms": self.alarms, "op_log": self.op_log, "drift_alarmed": self._drift_alarmed}

    @classmethod
    def from_dict(cls, data: dict[str, Any], cfg: PlantConfig | None = None) -> Reactor:
        env = cls(data["seed"], data["horizon"], cfg)
        env.s = PlantState(**data["state"])
        env.alarms = [dict(a) for a in data["alarms"]]
        env.op_log = list(data["op_log"])
        env._drift_alarmed = list(data["drift_alarmed"])
        return env
