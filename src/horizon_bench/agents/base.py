"""What a policy sees and returns at each step."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

AUTO_SUMMARY_NOTE = "automatic context summary"  # marks the LLM agent's own context digest (a synthetic write_note)


@dataclass
class Action:
    tool: str | None  # None: no tool call this step (e.g. the model replied with text only)
    args: Any = None
    error: str | None = None  # the call was malformed before it reached the tool layer
    abort: str | None = None  # the agent stops for good (e.g. a budget is exhausted)
    call_id: str | None = None  # tool_call id when the action came from a model
    meta: dict[str, Any] = field(default_factory=dict)  # LLM usage for the call that produced it

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Action:
        return cls(**d)


@dataclass
class Observation:
    step: int
    session: int
    result: Any = None  # agent-visible result of this agent's previous action
    warnings: list[str] = field(default_factory=list)


class Policy(ABC):
    name: str = "policy"

    def start_session(self, session: int, step: int) -> None:  # noqa: B027 - optional hook
        """Called at step 0 and at every session boundary; context must not survive it."""

    @abstractmethod
    def act(self, obs: Observation) -> Action: ...

    @abstractmethod
    def get_state(self) -> dict[str, Any]: ...

    @abstractmethod
    def set_state(self, state: dict[str, Any]) -> None: ...


class ScriptedPolicy(Policy):
    """Keeps all memory in one JSON-able dict so a checkpoint can capture it."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.mem: dict[str, Any] = {}

    def get_state(self) -> dict[str, Any]:
        return copy.deepcopy(self.mem)

    def set_state(self, state: dict[str, Any]) -> None:
        self.mem = copy.deepcopy(state)
