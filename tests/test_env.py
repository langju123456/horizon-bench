from __future__ import annotations

from conftest import make_spec, run
from horizon_bench.env import Reactor, make_scenario


def _trajectory(seed: int, read_between: bool = False) -> list[dict[str, object]]:
    env = Reactor(seed, 120)
    out = []
    for t in range(120):
        if read_between:
            for name in ("temp", "temp_backup", "pressure"):
                env.measure(name)
        env.command_valve(50 + (t % 7))
        out.append(env.truth())
        env.advance()
    return out


def test_dynamics_are_deterministic_per_seed() -> None:
    assert _trajectory(3) == _trajectory(3)
    assert _trajectory(3) != _trajectory(4)


def test_reading_sensors_does_not_change_the_plant() -> None:
    assert _trajectory(5) == _trajectory(5, read_between=True)


def test_longer_horizons_extend_the_same_scenario() -> None:
    short = make_scenario(7, 60)
    long = make_scenario(7, 240)
    assert short == [d for d in long if d.start < 60]
    assert len(long) > len(short)


def test_bare_and_rich_modes_share_dynamics() -> None:
    # naive ignores the extra rich fields, so it takes the same actions in both modes
    (_, a), (_, b) = run(make_spec("naive", "bare", seed=2)), run(make_spec("naive", "rich", seed=2))
    truth_a = [r["truth"] for r in a.records(make_spec("naive", "bare", seed=2).run_id)]
    truth_b = [r["truth"] for r in b.records(make_spec("naive", "rich", seed=2).run_id)]
    assert truth_a == truth_b


def test_uncontrolled_feed_increase_leaves_the_band() -> None:
    env = Reactor(1, 120)  # seed 1 has a +14.9 % feed composition step at step 16
    temps = []
    while env.step < 60 and not env.terminated:
        env.advance()
        temps.append(env.s.temp)
    assert max(temps) > 185.0


def test_state_round_trips_through_dict() -> None:
    env = Reactor(9, 120)
    for _ in range(30):
        env.advance()
    clone = Reactor.from_dict(env.to_dict())
    for _ in range(30):
        env.advance()
        clone.advance()
    assert env.truth() == clone.truth()
    assert env.alarms == clone.alarms
