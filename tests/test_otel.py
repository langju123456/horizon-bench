"""OpenTelemetry traces: the span tree of a run, GenAI attributes on model calls, and no effect on the run."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from conftest import make_spec, run
from horizon_bench import otel
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.family import get_family
from horizon_bench.runner import Runner, SimulatedCrash
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store
from test_prefix_cache import PrefixCachingServer, reply


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    otel.configure(exporter=exporter)
    yield exporter
    otel.shutdown()


def by_name(exporter: InMemorySpanExporter, prefix: str) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.name.startswith(prefix)]


def test_a_run_is_one_trace_of_sessions_steps_and_tool_calls(spans: InMemorySpanExporter) -> None:
    spec = make_spec("pid", horizon=45, session_len=20)
    _, store = run(spec)
    (root,) = by_name(spans, "hb.run")
    sessions, steps = by_name(spans, "hb.session"), by_name(spans, "hb.step")
    tools = by_name(spans, "execute_tool")
    assert len(sessions) == 3 and len(steps) == 45
    assert {s.context.trace_id for s in spans.get_finished_spans()} == {root.context.trace_id}
    assert all(s.parent.span_id == root.context.span_id for s in sessions)
    session_ids = {s.context.span_id for s in sessions}
    assert all(s.parent.span_id in session_ids for s in steps)
    records = store.records(spec.run_id)
    for span, rec in zip(sorted(steps, key=lambda s: s.attributes["hb.step"]), records, strict=True):
        assert span.attributes["hb.tool"] == rec["tool"]
        assert span.attributes["hb.truth.T"] == rec["truth"]["T"]
        assert span.attributes["hb.flags.stale_read_used"] == rec["flags"]["stale_read_used"]
    assert len(tools) == sum(1 for r in records if r["tool"])
    assert root.attributes["hb.policy"] == "pid" and root.attributes["hb.seed"] == 0
    assert root.attributes["hb.success"] in (True, False)


def test_model_calls_carry_genai_and_prefix_cache_attributes(spans: InMemorySpanExporter) -> None:
    spec = make_spec("llm", horizon=40, session_len=20,
                     llm=LLMConfig(model="fake", context_budget_tokens=2500, keep_last_messages=6).to_dict())
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(PrefixCachingServer(reply)))
    _, store = run(spec, agent)
    chats = by_name(spans, "chat fake")
    calls = [r for r in store.records(spec.run_id) if r["llm_call"]]
    assert len(chats) == len(calls)
    steps = {s.context.span_id for s in by_name(spans, "hb.step")}
    assert all(c.parent.span_id in steps for c in chats)  # each call nests under the step that made it
    first = min(chats, key=lambda s: s.start_time)
    assert first.attributes["gen_ai.operation.name"] == "chat" and first.attributes["gen_ai.request.model"] == "fake"
    assert first.attributes["gen_ai.usage.output_tokens"] == 20
    assert first.attributes["hb.prefix_break"] == "first"
    breaks = {c.attributes["hb.prefix_break"] for c in chats}
    assert {"none", "session_reset"} <= breaks
    assert sum(c.attributes["gen_ai.usage.cache_read.input_tokens"] for c in chats) == sum(
        r["cached_tokens"] for r in calls)


def test_tracing_does_not_change_the_run(tmp_path: Path, spans: InMemorySpanExporter) -> None:
    spec = make_spec("pid", horizon=40)
    Runner(Store(str(tmp_path / "a.sqlite")), tmp_path / "a").start(spec)
    otel.shutdown()
    Runner(Store(str(tmp_path / "b.sqlite")), tmp_path / "b").start(spec)
    a = (tmp_path / "a" / spec.run_id / "trace.jsonl").read_bytes()
    b = (tmp_path / "b" / spec.run_id / "trace.jsonl").read_bytes()
    assert a == b and spans.get_finished_spans()  # traced once, identical JSONL either way


def test_eval_seeds_are_not_exported_and_onset_is_an_event(spans: InMemorySpanExporter) -> None:
    spec = RunSpec(run_id="t-lazy-eval", batch="t", policy="lazy", tools="rich", horizon=60, seed=2**31 + 7,
                   split="eval", seed_index=0, salt_sha256="x")
    verdict, _ = run(spec)
    (root,) = by_name(spans, "hb.run")
    assert "hb.seed" not in root.attributes and root.attributes["hb.split"] == "eval"
    assert root.status.status_code == StatusCode.ERROR and verdict["success"] is False
    onset = [e for e in root.events if e.name == "failure_onset"]
    assert onset and onset[0].attributes["hb.step"] == verdict["onset_step"]


def test_a_crashed_run_still_closes_its_span(spans: InMemorySpanExporter) -> None:
    spec = make_spec("pid", horizon=30)
    with pytest.raises(SimulatedCrash):
        Runner(Store(":memory:"), runs_dir=None).start(spec, crash_after=10)
    (root,) = by_name(spans, "hb.run")
    assert root.status.status_code == StatusCode.ERROR
    assert any(e.name == "exception" for e in root.events)
