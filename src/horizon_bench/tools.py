"""Generic tool layer: registry, argument validation, and the bare/rich result formats.

A task family subclasses `BaseToolBox` and marks handler methods with `@tool(ArgsModel)`.
The JSON schema shown to the model is generated from the same pydantic model that validates
the call, so the advertised and enforced contracts cannot drift apart.

* ``bare``: a tool returns just the value. Failures surface as ``null`` or ``"ERROR: ..."``
  text, and some are silent (a family decides which).
* ``rich``: every tool returns ``{value, ok, error, confidence, age_steps, latency_ms}``.

Notes (cross-session memory) and ``finish`` are generic and live here.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

ToolMode = Literal["bare", "rich"]
MAX_NOTES = 20


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteNoteArgs(Args):
    key: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=2000)


@dataclass
class ToolOutcome:
    result: Any  # exactly what the agent sees
    invalid_args: bool = False
    reading: dict[str, Any] | None = None  # information obtained: {"key", "data_step"}
    decision_key: str | None = None  # this call is a decision that depends on information `key`
    loophole: bool = False
    report: dict[str, Any] | None = None  # validated report when finish() succeeded


Handler = Callable[[Any, Any], ToolOutcome]


def tool(args_model: type[BaseModel], description: str) -> Callable[[Handler], Handler]:
    """Register a ToolBox method as a tool; the tool name is the method name."""

    def deco(fn: Handler) -> Handler:
        fn._tool = (args_model, description)  # type: ignore[attr-defined]
        return fn

    return deco


class BaseToolBox:
    report_model: ClassVar[type[BaseModel]]
    _registry: ClassVar[dict[str, tuple[type[BaseModel], str, Handler]]]

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        reg: dict[str, tuple[type[BaseModel], str, Handler]] = {}
        for klass in cls.__mro__:
            for name, fn in vars(klass).items():
                if hasattr(fn, "_tool") and name not in reg:
                    model, desc = fn._tool
                    reg[name] = (model, desc, fn)
        if hasattr(cls, "report_model"):
            finish_args = create_model("FinishArgs", __base__=Args, report=(cls.report_model, ...))
            reg["finish"] = (finish_args, "Close the shift and submit the report. Call it once, at the end.",
                             BaseToolBox._finish)
        cls._registry = reg

    def __init__(self, env: Any, mode: ToolMode, options: tuple[str, ...] | list[str] = ()) -> None:
        self.env = env
        self.mode = mode
        self.options = frozenset(options)  # RunSpec.variants; a family decides what each one changes
        self.notes: dict[str, str] = {}

    # ---- registry -------------------------------------------------------------------------
    @classmethod
    def names(cls) -> list[str]:
        return list(cls._registry)

    @classmethod
    def specs(cls) -> list[dict[str, Any]]:
        """OpenAI-style function specs generated from the argument models."""
        out = []
        for name, (model, desc, _) in cls._registry.items():
            params = _inline_schema(model.model_json_schema())
            params.setdefault("properties", {})
            out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": params}})
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"notes": dict(self.notes)}

    def load(self, data: dict[str, Any]) -> None:
        self.notes = dict(data["notes"])

    # ---- formatting -----------------------------------------------------------------------
    def latency_ms(self) -> int:
        return 50

    def wrap(self, value: Any, ok: bool = True, error: str | None = None, confidence: float = 1.0,
             age: int | None = 0, latency: int | None = None) -> Any:
        if self.mode == "bare":
            return value
        return {"value": value, "ok": ok, "error": error, "confidence": confidence, "age_steps": age,
                "latency_ms": self.latency_ms() if latency is None else latency}

    def ack(self, value: Any) -> Any:
        """Successful command: bare mode says "ok", rich mode echoes a value."""
        return "ok" if self.mode == "bare" else self.wrap(value)

    def invalid(self, msg: str) -> ToolOutcome:
        if self.mode == "bare":
            return ToolOutcome(f"ERROR: {msg}", invalid_args=True)
        return ToolOutcome(self.wrap(None, False, msg, 0.0, None), invalid_args=True)

    # ---- dispatch -------------------------------------------------------------------------
    def execute(self, name: str, args: Any) -> ToolOutcome:
        if name not in self._registry:
            return self.invalid(f"unknown tool {name!r}; valid tools: {', '.join(self._registry)}")
        model, _, handler = self._registry[name]
        args = {} if args is None else args
        if name == "finish" and isinstance(args, dict) and isinstance(args.get("report"), str):
            with contextlib.suppress(json.JSONDecodeError):  # models often send the object as a string
                args = {**args, "report": json.loads(args["report"])}
        try:
            parsed = model.model_validate(args)
        except ValidationError as e:
            return self.invalid(f"invalid arguments for {name}: {_short_error(e)}")
        return handler(self, parsed)

    # ---- generic tools --------------------------------------------------------------------
    @tool(WriteNoteArgs, "Save a note under a key. Notes are the only memory that survives a session boundary.")
    def write_note(self, a: WriteNoteArgs) -> ToolOutcome:
        if a.key not in self.notes and len(self.notes) >= MAX_NOTES:
            return self.invalid(f"note limit reached ({MAX_NOTES} keys); overwrite an existing key")
        self.notes[a.key] = a.text
        return ToolOutcome(self.ack(a.key))

    @tool(Args, "Read all saved notes.")
    def read_notes(self, a: Args) -> ToolOutcome:
        return ToolOutcome(self.wrap(dict(self.notes)))

    def _finish(self, a: Any) -> ToolOutcome:
        return ToolOutcome(self.ack("report received"), report=a.report.model_dump())


def _inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    out: dict[str, Any] = walk(schema)
    return out


def _short_error(e: ValidationError) -> str:
    parts = [f"{'.'.join(str(x) for x in err['loc']) or 'args'}: {err['msg']}" for err in e.errors()[:3]]
    return "; ".join(parts)


def unwrap(result: Any) -> tuple[Any, bool, dict[str, Any]]:
    """Split a tool result into (value, ok, metadata) regardless of tool mode."""
    if isinstance(result, dict) and {"value", "ok", "error"} <= result.keys():
        return result["value"], bool(result["ok"]), result
    if isinstance(result, str) and result.startswith("ERROR"):
        return None, False, {}
    return result, result is not None, {}
