"""Prompt-prefix reuse: measured per model call, classified (append / trim / session reset), reported."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from conftest import make_spec, run
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.family import get_family
from horizon_bench.prefix_cache import classify, fingerprint, reported_cached_tokens, shared_prefix
from horizon_bench.report import build_report
from horizon_bench.runner import replay
from horizon_bench.store import Store
from test_llm_agent import FakeServer, call, completion

TOOLS = [{"type": "function", "function": {"name": "t"}}]


def test_shared_prefix_counts_whole_identical_units_from_the_start() -> None:
    a = fingerprint(TOOLS, [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}])
    b = fingerprint(TOOLS, [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"},
                            {"role": "assistant", "content": "x"}])
    c = fingerprint(TOOLS, [{"role": "system", "content": "s"}, {"role": "user", "content": "other"},
                            {"role": "user", "content": "hello"}])
    assert shared_prefix(a, b) == (3, sum(u[1] for u in a))
    assert shared_prefix(b, c)[0] == 2  # tools + system; the rest shifted
    assert classify(None, a, trimmed=False, reset=False) == "first"
    assert classify(a, b, trimmed=False, reset=False) is None
    assert classify(b, c, trimmed=True, reset=False) == "trim"
    assert classify(b, c, trimmed=False, reset=True) == "session_reset"
    assert classify(b, c, trimmed=False, reset=False) == "changed"


def test_server_reported_cache_fields() -> None:
    assert reported_cached_tokens({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 7}}) == 7
    assert reported_cached_tokens({"cache_read_input_tokens": 5}) == 5
    assert reported_cached_tokens({"prompt_tokens": 10}) is None and reported_cached_tokens(None) is None


class PrefixCachingServer(FakeServer):
    """Stands in for a server with a prefix cache: it reports, as cached, the characters / 4 its new prompt shares
    with the previous prompt plus the reply it gave (one slot, like llama.cpp)."""

    def __init__(self, reply: Any, report: bool = True) -> None:
        super().__init__(reply)
        self.report, self.slot = report, ""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        text = json.dumps([body["tools"], *body["messages"]])
        shared = next((i for i, (a, b) in enumerate(zip(self.slot, text, strict=False)) if a != b),
                      min(len(self.slot), len(text)))
        out = self.reply(body, len(self.requests))
        if self.report:
            out["usage"] = {**out["usage"], "prompt_tokens": len(text) // 4,
                            "prompt_tokens_details": {"cached_tokens": shared // 4}}
        msg = out["choices"][0]["message"]
        self.slot = json.dumps([body["tools"], *body["messages"], msg])[:-1]
        return httpx.Response(200, json=out)


def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
    return completion(call("read_sensor", {"name": ["temp", "pressure"][n % 2]}, cid=f"c{n}"))


def llm_run(server: FakeServer, horizon: int = 60, store: Store | None = None, **cfg: Any) -> tuple[Any, Store, Any]:
    spec = make_spec("llm", horizon=horizon, session_len=30, llm=LLMConfig(model="fake", **cfg).to_dict())
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(server))
    verdict, store = run(spec, agent, store)
    return verdict, store, spec


def test_each_call_is_classified_and_append_calls_extend_the_previous_prompt() -> None:
    server = FakeServer(reply)
    _, store, spec = llm_run(server, context_budget_tokens=2500, keep_last_messages=6)
    calls = [r for r in store.records(spec.run_id) if r["llm_call"]]
    breaks = [r["prefix_break"] for r in calls]
    assert breaks[0] == "first" and "trim" in breaks and "session_reset" in breaks
    assert all(r["cached_tokens"] is None for r in calls)  # this fake server reports no cache
    for prev, cur, rec in zip(server.requests, server.requests[1:], calls[1:], strict=False):
        if rec["prefix_break"] is None:  # append: the previous prompt is a strict prefix of this one
            assert cur["messages"][: len(prev["messages"])] == prev["messages"]
            assert rec["prefix_reuse_tokens"] > (len(json.dumps(prev["messages"])) // 4) - 50
        else:  # after a break only the tools and the system prompt are shared
            assert cur["messages"][0] == prev["messages"][0] and cur["messages"][1] != prev["messages"][1]
            units = fingerprint(cur["tools"], cur["messages"])
            assert rec["prefix_reuse_tokens"] == (units[0][1] + units[1][1]) // 4


def test_server_reported_cached_tokens_track_the_client_estimate() -> None:
    server = PrefixCachingServer(reply)
    verdict, store, spec = llm_run(server, context_budget_tokens=2500, keep_last_messages=6)
    calls = [r for r in store.records(spec.run_id) if r["llm_call"]]
    for r in calls[1:]:
        # whole messages (client) never claim more than the server's token-level prefix
        assert r["prefix_reuse_tokens"] <= r["cached_tokens"] + 5
    cache = verdict["usage"]["prefix_cache"]
    assert cache["cached_tokens_reported"] == sum(r["cached_tokens"] for r in calls)
    assert cache["breaks"]["trim"] >= 1 and cache["breaks"]["session_reset"] == 1


def test_measured_runs_replay_and_report(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "hb.sqlite"))
    llm_run(PrefixCachingServer(reply), store=store, context_budget_tokens=2500, keep_last_messages=6)
    spec = make_spec("llm", horizon=60, session_len=30)
    assert replay(store, spec.run_id)["ok"]
    out = build_report(store, ["test"], "cache", tmp_path / "reports")
    text = (out / "report.md").read_text()
    assert "## Prompt prefix reuse" in text and "of prompt tokens" in text


def test_scripted_runs_have_no_cache_fields_or_report_section(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "hb.sqlite"))
    spec = make_spec("pid", horizon=20)
    verdict, _ = run(spec, store=store)
    assert "prefix_cache" not in verdict["usage"]
    assert all("prefix_break" not in r for r in store.records(spec.run_id))
    text = (build_report(store, ["test"], "scripted", tmp_path / "reports") / "report.md").read_text()
    assert "Prompt prefix reuse" not in text


def test_window_settings_get_their_own_report_row() -> None:
    from horizon_bench.report import policy_label

    assert policy_label(make_spec("llm", llm=LLMConfig(model="m").to_dict())) == "llm:m"
    assert policy_label(make_spec("llm", llm=LLMConfig(model="m", keep_last_messages=8).to_dict())) == "llm:m[keep8]"
    assert policy_label(make_spec("pid")) == "pid"
