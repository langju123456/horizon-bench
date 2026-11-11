"""Prompt (prefix) caching: how much of each model call's prompt repeats the previous call, and why it stops.

An inference server keeps the KV cache of the last prompt it processed (Ollama and llama.cpp per slot, vLLM with
automatic prefix caching across requests). A new prompt that starts with the same tokens reuses those entries and
only the new tail is computed. For an agent loop that is most of every prompt: the system prompt, the tool schemas
and the whole conversation so far, plus one new tool result. The harness decides whether that holds:

* ``append``        the new prompt is the previous prompt plus the previous reply plus new messages: everything
                    before the new messages can be reused;
* ``trim``          the rolling window dropped old messages and inserted a note after the system prompt, so the
                    prompt now differs right after the system prompt: only the tools and the system prompt are
                    reusable, the rest is recomputed once;
* ``session_reset`` a context reset at a session boundary: same, only tools + system prompt are reusable;
* ``first``         the first call of the run;
* ``changed``       an earlier message differs for another reason (should not happen in this agent).

Two numbers per call, kept apart because they mean different things:

* ``prefix_reuse_tokens`` is computed here, from the messages, on the client: whole messages shared with the
  previous call (tools and system included), estimated as characters / 4 like ``context_tokens``. It does not
  depend on the server, so it can be compared across servers and runs. Whole messages only, so it is a lower
  bound on what a token-level cache can reuse.
* ``cached_tokens`` is what the server says it reused, when it says it: ``usage.prompt_tokens_details.cached_tokens``
  (OpenAI, vLLM with ``--enable-prompt-tokens-details``, recent llama.cpp server) or ``usage.cache_read_input_tokens``
  (Anthropic-style). Ollama's OpenAI-compatible endpoint does not report it; there the effect shows in latency:
  compare calls after ``append`` with calls after a break (``hb report`` does).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

BREAKS = ("first", "trim", "session_reset", "changed")


def _unit(obj: Any) -> tuple[str, int]:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(text.encode()).hexdigest()[:16], len(text)


def fingerprint(tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> list[list[Any]]:
    """[digest, characters] per prompt unit in prompt order: the tool schemas first, then each message.

    Small enough to keep in the agent's checkpoint (a resumed run keeps measuring against the right prefix).
    """
    return [list(_unit(tools)), *[list(_unit(m)) for m in messages]]


def shared_prefix(previous: list[list[Any]] | None, current: list[list[Any]]) -> tuple[int, int]:
    """(units, characters) at the start of ``current`` that are identical to the start of ``previous``."""
    units = chars = 0
    for a, b in zip(previous or [], current, strict=False):
        if a[0] != b[0]:
            break
        units, chars = units + 1, chars + int(b[1])
    return units, chars


def classify(previous: list[list[Any]] | None, current: list[list[Any]], *, trimmed: bool, reset: bool) -> str | None:
    """None when the previous prompt (and reply) is a prefix of this one; otherwise why the prefix broke."""
    if previous is None:
        return "first"
    if reset:
        return "session_reset"
    if trimmed:
        return "trim"
    units, _ = shared_prefix(previous, current)
    return None if units == len(previous) else "changed"


def reported_cached_tokens(usage: dict[str, Any] | None) -> int | None:
    """Cached prompt tokens as the server reports them, or None when it does not report them."""
    if not usage:
        return None
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and details.get("cached_tokens") is not None:
        return int(details["cached_tokens"])
    if usage.get("cache_read_input_tokens") is not None:
        return int(usage["cache_read_input_tokens"])
    return None
