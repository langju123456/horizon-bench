from __future__ import annotations

import pytest

from horizon_bench.agents.base import Action, Observation, Policy
from horizon_bench.env.annual_handoff import ANNUAL_HANDOFF, AnnualHandoffEnv, AnnualHandoffToolBox
from horizon_bench.runner import Runner, SimulatedCrash, replay
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store


@pytest.mark.parametrize(
    "seed,mode,success",
    [
        (0, "handoff_last", False),
        (0, "handoff_recent3", True),
        (0, "handoff_full", True),
        (0, "handoff_card", True),
        (1, "handoff_last", False),
        (1, "handoff_recent3", False),
        (1, "handoff_full", True),
        (1, "handoff_card", True),
    ],
)
def test_catalog_reference_replays_for_each_handoff_mode(seed: int, mode: str, success: bool) -> None:
    spec = RunSpec(
        run_id=f"handoff-{seed}-{mode}",
        batch="test",
        family="annual_handoff",
        policy="catalog",
        tools="rich",
        horizon=5,
        seed=seed,
        split="dev",
        seed_index=seed,
        variants=[mode],
    )
    store = Store(":memory:")
    verdict = Runner(store, runs_dir=None).start(spec, ANNUAL_HANDOFF.policies["catalog"](spec))
    assert verdict["success"] is success
    assert replay(store, spec.run_id)["ok"]


def test_catalog_state_restores_after_checkpoint_without_new_session(tmp_path) -> None:
    spec = RunSpec(
        run_id="handoff-resume",
        batch="test",
        family="annual_handoff",
        policy="catalog",
        tools="rich",
        horizon=5,
        seed=0,
        split="dev",
        seed_index=0,
        variants=["handoff_card"],
    )
    store = Store(tmp_path / "handoff.sqlite")
    with pytest.raises(SimulatedCrash):
        Runner(store, runs_dir=None).start(spec, ANNUAL_HANDOFF.policies["catalog"](spec), crash_after=1)
    verdict = Runner(store, runs_dir=None).resume(spec.run_id, ANNUAL_HANDOFF.policies["catalog"](spec))
    assert verdict["success"] and replay(store, spec.run_id)["ok"]


class WrongReportPolicy(Policy):
    name = "wrong_report"

    def __init__(self, spec: RunSpec) -> None:
        self.i, self.broken = 0, str(spec.variants[1])

    def act(self, obs: Observation) -> Action:
        good = {
            "period": "第四季度",
            "amount_thousand_cny": 52559552,
            "unit": "千元",
            "source_pages": [11, 12],
            "reviewer_note": "审阅备注：按千元列示，不四舍五入。",
        }
        if self.i == 0:
            action = Action("read_handoff", {})
        elif self.i == 1:
            action = Action("open_source", {"page": 12 if self.broken == "unread_header" else 11})
        elif self.i == 2:
            action = Action("open_source", {"page": 12})
        else:
            if self.broken == "period":
                good["period"] = "全年"
            if self.broken == "pages":
                good["source_pages"] = [11]
            if self.broken == "note":
                good["reviewer_note"] = "审阅备注：按千元列示。"
            action = Action("finish", {"report": good})
        self.i += 1
        return action

    def get_state(self) -> dict[str, object]:
        return {"i": self.i, "broken": self.broken}

    def set_state(self, state: dict[str, object]) -> None:
        self.i, self.broken = int(state["i"]), str(state["broken"])


@pytest.mark.parametrize(
    "broken,check",
    [("period", "latest_period"), ("pages", "correct_source_pages"), ("note", "reviewer_note_preserved"),
     ("unread_header", "opened_required_source")],
)
def test_wrong_period_note_or_source_fails_independently(broken: str, check: str) -> None:
    spec = RunSpec(
        run_id=f"wrong-{broken}",
        batch="test",
        family="annual_handoff",
        policy="wrong_report",
        tools="rich",
        horizon=6,
        seed=0,
        split="dev",
        seed_index=0,
        variants=["handoff_card", broken],
    )
    # Test invokes the policy directly so the extra test-only selector never reaches the Toolbox.
    store = Store(":memory:")
    verdict = Runner(store, runs_dir=None).start(spec, WrongReportPolicy(spec))
    assert not verdict["success"]
    assert not verdict["checks"][check]


def test_exactly_one_handoff_variant_is_required() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AnnualHandoffToolBox(AnnualHandoffEnv(0, 4), "rich", [])


def test_type_card_is_compiled_from_visible_event_types() -> None:
    env = AnnualHandoffEnv(0, 4)
    card = env.handoff("handoff_card")
    assert "更新范围：不要全年数，改成第四季度。" in card
    assert "审阅备注：按千元列示，不四舍五入。" in card
