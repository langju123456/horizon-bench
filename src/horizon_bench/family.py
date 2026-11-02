"""The task-family interface. The runner, telemetry, replay and report only use this module,
so a new family (env + tools + judge + prompt + scripted policies) plugs in via `FAMILIES`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from horizon_bench.agents.base import Policy
from horizon_bench.spec import RunSpec
from horizon_bench.tools import BaseToolBox


class Env(Protocol):
    """Simulated world. `truth()` and `true_events()` are hidden from the agent: only the
    verifier and analysis code read them. `truth()["active"]` lists active disturbances."""

    horizon: int

    @property
    def step(self) -> int: ...
    @property
    def terminated(self) -> bool: ...
    def advance(self) -> None: ...
    def truth(self) -> dict[str, Any]: ...
    def true_events(self, until: int | None = None) -> list[dict[str, Any]]: ...
    def audit_view(self) -> Any: ...  # agent-editable audit trail, for the naive-grader comparison
    def to_dict(self) -> dict[str, Any]: ...


@dataclass
class Judgement:
    """A family's domain verdict, computed only from true state and the true event log."""

    checks: dict[str, bool]  # every check must pass for success
    metrics: dict[str, Any] = field(default_factory=dict)
    onset: tuple[int, str] | None = None  # domain-specific loss of control: (step, cause)
    naive_grader_pass: bool | None = None  # what a grader trusting agent-editable records would say


@dataclass
class EpisodeEnd:
    reason: str  # finished | horizon | terminated | abort:<why>
    finish_step: int | None = None
    report: dict[str, Any] | None = None
    audit_at_finish: Any = None


@dataclass(frozen=True)
class Family:
    name: str
    make_env: Callable[[int, int], Env]  # (seed, horizon)
    load_env: Callable[[dict[str, Any]], Env]
    toolbox: type[BaseToolBox]
    judge: Callable[[RunSpec, list[dict[str, Any]], Any, EpisodeEnd], Judgement]
    system_prompt: Callable[[RunSpec], str]
    policies: dict[str, Callable[[RunSpec], Policy]]  # scripted policies by name
    event_window: tuple[int, int] = (-5, 20)  # reported step may be this far from the true start
    flipflop: dict[str, tuple[str, float]] = field(default_factory=dict)  # tool -> (arg, min swing)


def get_family(name: str) -> Family:
    from horizon_bench.env.reactor_family import REACTOR  # local import avoids a cycle

    families = {REACTOR.name: REACTOR}
    if name not in families:
        raise KeyError(f"unknown family {name!r}; available: {', '.join(families)}")
    return families[name]
