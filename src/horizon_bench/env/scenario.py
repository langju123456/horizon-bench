"""Seeded disturbance schedule.

The episode is cut into 60-step blocks and every block draws its own disturbances from
`default_rng([seed, 1, block])`, so the first 60 steps of a 120-step episode are identical to
a 60-step episode with the same seed. Longer horizons therefore contain strictly more events.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

BLOCK = 60
REPORTABLE = ("feed_change", "sensor_drift", "sensor_dropout", "valve_stuck")
EQUIPMENT_CODES = ("AGITATOR_VIBRATION", "SEAL_PRESSURE_LOW", "COOLANT_PUMP_TEMP")
PERSISTENT = 1_000_000  # a feed composition change stays in effect until the next one


@dataclass(frozen=True)
class Disturbance:
    kind: str  # one of REPORTABLE or "equipment_alarm"
    start: int
    duration: int
    magnitude: float = 0.0  # feed_change: new composition factor; sensor_drift: degC per step
    code: str = ""  # equipment_alarm only

    def active(self, step: int) -> bool:
        return self.start <= step < self.start + self.duration

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def make_scenario(seed: int, horizon: int) -> list[Disturbance]:
    """Return the disturbances for one episode, sorted by start step."""
    events: list[Disturbance] = []
    for block in range(math.ceil(horizon / BLOCK)):
        lo = block * BLOCK + 5
        hi = min((block + 1) * BLOCK, horizon) - 20  # leave time to see and report the event
        if hi <= lo:
            continue
        rng = np.random.default_rng([seed, 1, block])

        def when(rng: np.random.Generator = rng, lo: int = lo, hi: int = hi) -> int:
            return int(rng.integers(lo, hi))

        sign = float(rng.choice([-1.0, 1.0]))
        events.append(
            Disturbance("feed_change", when(), PERSISTENT, round(1.0 + sign * rng.uniform(0.10, 0.18), 3))
        )
        events.append(Disturbance("sensor_dropout", when(), int(rng.integers(6, 13))))
        if rng.random() < 0.5:
            events.append(Disturbance("valve_stuck", when(), int(rng.integers(8, 16))))
        else:
            rate = float(rng.choice([-1.0, 1.0])) * rng.uniform(0.20, 0.30)
            events.append(Disturbance("sensor_drift", when(), int(rng.integers(18, 26)), round(rate, 3)))
        code = str(rng.choice(EQUIPMENT_CODES))
        events.append(Disturbance("equipment_alarm", when(), 1, code=code))
    return sorted(events, key=lambda d: (d.start, d.kind))
