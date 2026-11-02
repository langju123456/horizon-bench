from __future__ import annotations

from typing import Any

import pytest

from horizon_bench.agents.base import Action, Observation, Policy
from horizon_bench.runner import Runner
from horizon_bench.spec import RunSpec, make_run_id
from horizon_bench.store import Store


def make_spec(policy: str = "pid", tools: str = "rich", horizon: int = 60, seed: int = 0, **kw: Any) -> RunSpec:
    batch = kw.pop("batch", "test")
    return RunSpec(run_id=make_run_id(batch, policy, tools, horizon, "dev", seed), batch=batch, policy=policy,
                   tools=tools, horizon=horizon, seed=seed, split="dev", seed_index=seed, **kw)


def run(spec: RunSpec, policy: Policy | None = None, store: Store | None = None) -> tuple[dict[str, Any], Store]:
    store = store or Store(":memory:")
    return Runner(store, runs_dir=None).start(spec, policy), store


class ScriptPolicy(Policy):
    """Plays a fixed list of (tool, args) and then repeats the last one."""

    name = "script"

    def __init__(self, calls: list[tuple[str | None, Any]]) -> None:
        self.calls = calls
        self.i = 0

    def act(self, obs: Observation) -> Action:
        tool, args = self.calls[min(self.i, len(self.calls) - 1)]
        self.i += 1
        return Action(tool, args)

    def get_state(self) -> dict[str, Any]:
        return {"i": self.i}

    def set_state(self, state: dict[str, Any]) -> None:
        self.i = state["i"]


@pytest.fixture
def script() -> type[ScriptPolicy]:
    return ScriptPolicy
