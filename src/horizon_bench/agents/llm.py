"""LLM operator over any OpenAI-compatible /chat/completions endpoint with tool calling.

One model response may contain several tool calls; each one is executed as its own step.
Guards: hard budgets (agent steps, tokens per call, total tokens, wall time), a context budget
handled by a rolling window that saves a summary of the dropped messages to notes, loop
warnings from the runner, and malformed calls returned to the model as error observations.
"""

from __future__ import annotations

import copy
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from horizon_bench.agents.base import Action, Observation, Policy
from horizon_bench.family import Family
from horizon_bench.spec import RunSpec

SUMMARY_KEY = "context_summary"


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:8b"
    max_steps: int = 10_000  # agent actions (the horizon also caps the run)
    max_tokens_per_call: int = 1024
    max_total_tokens: int = 2_000_000
    wall_time_s: float = 4 * 3600.0  # summed model latency
    context_budget_tokens: int = 8000  # estimated as characters / 4
    keep_last_messages: int = 24
    temperature: float = 0.0
    timeout_s: float = 300.0
    max_consecutive_errors: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fresh_state() -> dict[str, Any]:
    return {"messages": [], "queue": [], "pending": None, "nudge": False, "tokens": 0, "calls": 0,
            "actions": 0, "wall_s": 0.0, "errors": 0, "summaries": 0}


class LLMAgent(Policy):
    name = "llm"

    def __init__(self, spec: RunSpec, family: Family, transport: httpx.BaseTransport | None = None,
                 api_key: str | None = None) -> None:
        self.cfg = LLMConfig(**(spec.llm or {}))
        self.spec = spec
        self.system = family.system_prompt(spec) + (
            "\nEach tool result is JSON {\"step\": <step the call ran at>, \"result\": ...}.")
        self.tools = family.toolbox.specs()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(base_url=self.cfg.base_url, headers=headers, timeout=self.cfg.timeout_s,
                                   transport=transport)
        self.st = _fresh_state()

    def get_state(self) -> dict[str, Any]:
        return copy.deepcopy(self.st)

    def set_state(self, state: dict[str, Any]) -> None:
        self.st = copy.deepcopy(state)

    def start_session(self, session: int, step: int) -> None:
        keep = {k: self.st[k] for k in ("tokens", "calls", "actions", "wall_s", "summaries")}
        self.st = {**_fresh_state(), **keep}
        n = math.ceil(self.spec.horizon / self.spec.session_len)
        intro = f"Session {session + 1} of {n} starts at step {step}. "
        intro += ("Your earlier conversation was erased; call read_notes() to recover your handoff notes."
                  if session else "The shift begins now.")
        self.st["messages"] = [{"role": "system", "content": self.system}, {"role": "user", "content": intro}]

    # ---- one step ---------------------------------------------------------------------------
    def act(self, obs: Observation) -> Action:
        st = self.st
        self._absorb(obs)
        if st["queue"]:
            return self._emit(st["queue"].pop(0), {})
        reason = self._budget_exhausted()
        if reason:
            return Action(None, abort=reason)
        if self._context_tokens() > self.cfg.context_budget_tokens:
            summary = self._trim(obs.step)
            if summary is not None:
                return summary
        return self._call_model()

    def _absorb(self, obs: Observation) -> None:
        """Turn the previous action's result (and any runner warnings) into messages."""
        st, warn = self.st, "\n".join(obs.warnings)
        pending, st["pending"] = st["pending"], None
        if pending and pending.get("id"):
            content = json.dumps({"step": obs.step - 1, "result": obs.result})
            st["messages"].append({"role": "tool", "tool_call_id": pending["id"], "name": pending["name"],
                                   "content": content + (f"\n{warn}" if warn else "")})
        elif st["nudge"] or warn:
            text = f"(now step {obs.step}) "
            text += "You replied without a tool call, so a step passed with no action. " if st["nudge"] else ""
            st["messages"].append({"role": "user", "content": text + warn})
        st["nudge"] = False

    def _emit(self, call: dict[str, Any], meta: dict[str, Any]) -> Action:
        self.st["actions"] += 1
        self.st["pending"] = {"id": call["id"], "name": call["tool"]}
        return Action(call["tool"], call["args"], error=call["error"], call_id=call["id"], meta=meta)

    def _budget_exhausted(self) -> str | None:
        st, c = self.st, self.cfg
        if st["actions"] >= c.max_steps:
            return "max_steps"
        if st["tokens"] >= c.max_total_tokens:
            return "max_total_tokens"
        if st["wall_s"] >= c.wall_time_s:
            return "wall_time"
        return None

    def _context_tokens(self) -> int:
        return (len(json.dumps(self.st["messages"])) + len(json.dumps(self.tools))) // 4

    def _trim(self, step: int) -> Action | None:
        """Rolling window: keep the system prompt and the last N messages (never starting on an
        orphaned tool result), and save a summary of the dropped part to notes as a real step."""
        msgs, keep = self.st["messages"], self.cfg.keep_last_messages
        if len(msgs) <= keep + 2:
            return None
        cut = len(msgs) - keep
        while cut < len(msgs) and msgs[cut]["role"] == "tool":
            cut += 1
        dropped = msgs[1:cut]
        self.st["summaries"] += 1
        note = (f"[step {step}] Older messages were removed to fit the context budget; a summary of them "
                f"was saved to note '{SUMMARY_KEY}' (read_notes).")
        self.st["messages"] = [msgs[0], {"role": "user", "content": note}, *msgs[cut:]]
        self.st["actions"] += 1
        self.st["pending"] = {"id": None, "name": "write_note"}  # synthetic: no tool message follows
        return Action("write_note", {"key": SUMMARY_KEY, "text": summarize(dropped)},
                      meta={"note": "automatic context summary"})

    def _call_model(self) -> Action:
        st, c = self.st, self.cfg
        context = self._context_tokens()
        payload = {"model": c.model, "messages": st["messages"], "tools": self.tools, "tool_choice": "auto",
                   "max_tokens": c.max_tokens_per_call, "temperature": c.temperature}
        t0 = time.perf_counter()
        try:
            resp = self.client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            latency = (time.perf_counter() - t0) * 1000
            st["wall_s"] += latency / 1000
            st["errors"] += 1
            if st["errors"] >= c.max_consecutive_errors:
                return Action(None, abort=f"llm_errors ({type(e).__name__}: {str(e)[:120]})")
            return Action(None, meta={"llm_call": True, "latency_ms": latency, "context_tokens": context,
                                      "note": f"llm error: {type(e).__name__}: {str(e)[:200]}"})
        latency = (time.perf_counter() - t0) * 1000
        usage = data.get("usage") or {}
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        st["tokens"] += pt + ct
        st["calls"] += 1
        st["wall_s"] += latency / 1000
        st["errors"] = 0
        meta = {"llm_call": True, "prompt_tokens": pt, "completion_tokens": ct, "latency_ms": latency,
                "context_tokens": context}

        content = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            call_id = tc.get("id") or f"call_{st['calls']}_{i}"
            args, err = parse_arguments(fn.get("arguments"))
            calls.append({"id": call_id, "tool": str(fn.get("name") or ""), "args": args, "error": err,
                          "raw": fn.get("arguments") if isinstance(fn.get("arguments"), str) else json.dumps(args)})
        assistant: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            assistant["tool_calls"] = [{"id": x["id"], "type": "function",
                                        "function": {"name": x["tool"], "arguments": x["raw"] or "{}"}} for x in calls]
        st["messages"].append(assistant)
        if not calls:
            st["actions"] += 1
            st["nudge"] = True
            return Action(None, meta={**meta, "note": content[:200]})
        st["queue"] = [{k: x[k] for k in ("id", "tool", "args", "error")} for x in calls[1:]]
        return self._emit(calls[0], meta)


def parse_arguments(raw: Any) -> tuple[Any, str | None]:
    """Return (args, error). Malformed arguments become an error the model will see."""
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return raw, "malformed tool call: arguments must be a JSON object"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return raw, f"malformed tool call: arguments are not valid JSON ({e.msg} at char {e.pos})"
    if not isinstance(parsed, dict):
        return raw, "malformed tool call: arguments must be a JSON object"
    return parsed, None


def summarize(messages: list[dict[str, Any]], limit: int = 1500) -> str:
    """Deterministic digest of dropped messages: the calls made and what they returned."""
    lines = []
    for m in messages:
        if m["role"] == "assistant":
            for tc in m.get("tool_calls", []):
                lines.append(f"call {tc['function']['name']}({tc['function']['arguments'][:80]})")
            if m.get("content"):
                lines.append(f"said: {m['content'][:120]}")
        elif m["role"] == "tool":
            lines.append(f"  -> {m['content'][:160]}")
    text = "\n".join(lines)
    return text[-limit:]
