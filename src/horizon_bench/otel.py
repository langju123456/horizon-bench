"""OpenTelemetry traces for runs: one trace per run, a span per session, per step, per tool call, per model call.

Off unless ``configure()`` is called (``hb run --otel``); without the ``otel`` extra installed every hook is a
no-op, and the JSONL trace and SQLite records are byte-identical with or without tracing (a test checks this), so
the OTel trace is a second view of the same run, never an input to the verdict.

Span tree of one run::

    hb.run  run_id, policy, tools, horizon, model; at the end: success, end_reason, onset step and cause
    └── hb.session  index, first step
        └── hb.step  step, tool, args, result, flags (loop, stale read, invalid args, loophole), true plant state
            ├── chat <model>       GenAI semantic conventions: model, max_tokens, temperature, token usage,
            │                      finish reason, cached prompt tokens (server-reported), plus
            │                      hb.prefix_reuse_tokens / hb.prefix_break (horizon_bench.prefix_cache)
            └── execute_tool <tool>

Model-call spans use the OpenTelemetry GenAI attribute names (``gen_ai.operation.name``, ``gen_ai.request.model``,
``gen_ai.usage.input_tokens`` ...), so Langfuse, Phoenix or Jaeger show them as LLM calls without a custom mapping.
Prompts and replies are not attached (they are in the JSONL trace); ``hb.response`` holds the first 1000
characters of the reply text. Eval-split seeds are not exported, only dev seeds (eval hygiene, see README).

Where the spans go is standard OTLP configuration: ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_HEADERS``,
or ``hb run --otel --otel-endpoint http://localhost:4318/v1/traces``; ``--otel-console`` prints them instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

try:
    from opentelemetry import trace as _trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # the otel extra is not installed: every hook below is a no-op
    _trace = None  # type: ignore[assignment]

_provider: Any = None
TRUNC = 1000


def enabled() -> bool:
    return _provider is not None


def configure(endpoint: str | None = None, *, console: bool = False, exporter: Any = None,
              service_name: str = "horizon-bench") -> Any:
    """Install a tracer provider. ``exporter`` (tests) wins over ``console``, which wins over OTLP/HTTP."""
    global _provider
    if _trace is None:
        raise RuntimeError("OpenTelemetry is not installed: pip install -e '.[otel]'")
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint) if endpoint
                                                       else OTLPSpanExporter()))
    _provider = provider
    return provider


def shutdown() -> None:
    """Flush and stop; call before the process exits or batched spans are lost."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def _tracer() -> Any:
    return _provider.get_tracer("horizon_bench")


def _json(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:TRUNC]


def _set(span: Any, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
            span.set_attribute(key, list(value))
        else:
            span.set_attribute(key, value if isinstance(value, (bool, int, float, str)) else _json(value))


# ---- runs, sessions, steps ------------------------------------------------------------------
class RunTracer:
    """Owns the run span and the current session span; opens step spans under the session."""

    def __init__(self, spec: Any, resumed_at: int | None = None) -> None:
        self.active = enabled()
        self.session_span: Any = None
        self.session: int | None = None
        if not self.active:
            return
        llm = spec.llm or {}
        self.run_span = _tracer().start_span(f"hb.run {spec.run_id}", attributes={
            "hb.run_id": spec.run_id, "hb.batch": spec.batch, "hb.family": spec.family, "hb.policy": spec.policy,
            "hb.tools": spec.tools, "hb.horizon": spec.horizon, "hb.session_len": spec.session_len,
            "hb.split": spec.split, "hb.seed_index": spec.seed_index})
        if spec.split == "dev":
            self.run_span.set_attribute("hb.seed", spec.seed)
        _set(self.run_span, {"gen_ai.request.model": llm.get("model"), "hb.resumed_from_step": resumed_at})

    def _session(self, session: int, step: int) -> Any:
        if session != self.session:
            if self.session_span is not None:
                self.session_span.end()
            ctx = _trace.set_span_in_context(self.run_span)
            self.session_span = _tracer().start_span(f"hb.session {session}", context=ctx,
                                                     attributes={"hb.session": session, "hb.first_step": step})
            self.session = session
        return self.session_span

    @contextmanager
    def step(self, step: int, session: int) -> Iterator[Any]:
        if not self.active:
            yield None
            return
        parent = _trace.set_span_in_context(self._session(session, step))
        span = _tracer().start_span(f"hb.step {step}", context=parent, attributes={"hb.step": step})
        with _trace.use_span(span, end_on_exit=True):  # model and tool spans nest under the step
            yield span

    def finish(self, verdict: dict[str, Any] | None, error: BaseException | None = None) -> None:
        if not self.active:
            return
        if self.session_span is not None:
            self.session_span.end()
        if verdict is not None:
            usage = verdict.get("usage") or {}
            _set(self.run_span, {
                "hb.success": bool(verdict.get("success")), "hb.end_reason": verdict.get("end_reason"),
                "hb.onset_step": verdict.get("onset_step"), "hb.onset_cause": verdict.get("onset_cause"),
                "hb.failed": ",".join(verdict.get("failed") or []), "hb.llm_calls": usage.get("llm_calls"),
                "gen_ai.usage.input_tokens": usage.get("prompt_tokens"),
                "gen_ai.usage.output_tokens": usage.get("completion_tokens")})
            if verdict.get("onset_step") is not None:
                self.run_span.add_event("failure_onset", {"hb.step": verdict["onset_step"],
                                                          "hb.cause": verdict.get("onset_cause") or "",
                                                          "hb.context": _json(verdict.get("onset_context"))})
            if not verdict.get("success"):
                self.run_span.set_status(Status(StatusCode.ERROR, "run did not succeed"))
        if error is not None:
            self.run_span.record_exception(error)
            self.run_span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        self.run_span.end()


def step_done(span: Any, record: dict[str, Any]) -> None:
    if span is None:
        return
    flags = record.get("flags") or {}
    if record.get("tool"):
        span.update_name(f"hb.step {record['step']} {record['tool']}")
    _set(span, {"hb.session": record.get("session"), "hb.agent_active": record.get("agent_active"),
                "hb.tool": record.get("tool"), "hb.args": record.get("args"), "hb.error": record.get("error"),
                "hb.abort": record.get("abort"), "hb.result": record.get("result"), "hb.note": record.get("note"),
                "hb.decision": record.get("decision"), "hb.basis_age": record.get("basis_age"),
                "hb.invalid_streak": record.get("invalid_streak")})
    for name, value in flags.items():
        span.set_attribute(f"hb.flags.{name}", bool(value))
    for key, value in (record.get("truth") or {}).items():
        span.set_attribute(f"hb.truth.{key}", value if isinstance(value, (int, float, str)) else _json(value))
    if flags.get("loop"):
        span.add_event("loop_detected")
    if flags.get("stale_read_used"):
        span.add_event("stale_read_used", {"hb.basis_age": record.get("basis_age") or -1})
    if flags.get("invalid_args") or flags.get("loophole_used"):
        span.set_status(Status(StatusCode.ERROR, "loophole used" if flags.get("loophole_used") else "invalid args"))


def tool_span(tool: str | None) -> Any:
    if not enabled() or tool is None:
        return nullcontext()
    return _tracer().start_as_current_span(f"execute_tool {tool}", attributes={
        "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool})


# ---- model calls ----------------------------------------------------------------------------
@contextmanager
def chat_span(model: str, base_url: str, payload: dict[str, Any], context_tokens: int,
              cache: dict[str, Any]) -> Iterator[Any]:
    if not enabled():
        yield None
        return
    provider = "ollama" if ":11434" in base_url else "openai"
    attrs = {"gen_ai.operation.name": "chat", "gen_ai.provider.name": provider, "gen_ai.request.model": model,
             "gen_ai.request.max_tokens": payload.get("max_tokens"),
             "gen_ai.request.temperature": payload.get("temperature"), "hb.context_tokens": context_tokens,
             "hb.messages": len(payload.get("messages") or []), "hb.prefix_reuse_tokens": cache["prefix_reuse_tokens"],
             "hb.prefix_break": cache["prefix_break"] or "none"}
    with _tracer().start_as_current_span(f"chat {model}", kind=_trace.SpanKind.CLIENT) as span:
        _set(span, attrs)
        yield span


def chat_done(span: Any, data: dict[str, Any], prompt_tokens: int, completion_tokens: int,
              cached_tokens: int | None) -> None:
    if span is None:
        return
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = [((tc.get("function") or {}).get("name") or "") for tc in message.get("tool_calls") or []]
    _set(span, {"gen_ai.response.model": data.get("model"), "gen_ai.response.id": data.get("id"),
                "gen_ai.response.finish_reasons": [choice.get("finish_reason") or ""],
                "gen_ai.usage.input_tokens": prompt_tokens, "gen_ai.usage.output_tokens": completion_tokens,
                "gen_ai.usage.cache_read.input_tokens": cached_tokens, "hb.tool_calls": ",".join(calls),
                "hb.response": (message.get("content") or "")[:TRUNC]})


def chat_failed(span: Any, error: BaseException) -> None:
    if span is None:
        return
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, type(error).__name__))
    span.set_attribute("error.type", type(error).__name__)
