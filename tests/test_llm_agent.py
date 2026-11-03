"""The LLM agent against an in-process fake OpenAI-compatible server (httpx.MockTransport)."""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise
from typing import Any

import httpx
import pytest

from conftest import make_spec, run
from horizon_bench.agents.llm import SUMMARY_KEY, LLMAgent, LLMConfig, parse_arguments
from horizon_bench.family import get_family
from horizon_bench.runner import Runner, SimulatedCrash
from horizon_bench.store import Store

Reply = Callable[[dict[str, Any], int], dict[str, Any]]
FINISH = {"report": {"events": [], "status": "normal"}}


class FakeServer:
    def __init__(self, reply: Reply) -> None:
        self.reply = reply
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(200, json=self.reply(body, len(self.requests)))


def call(name: str, args: Any = None, raw: str | None = None, cid: str = "c") -> dict[str, Any]:
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": raw if raw is not None else json.dumps(args or {})}}


def completion(*calls: dict[str, Any], content: str = "", pt: int = 100, ct: int = 20) -> dict[str, Any]:
    msg = {"role": "assistant", "content": content, "tool_calls": list(calls)}
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}


def llm_run(reply: Reply, horizon: int = 20, **cfg: Any) -> tuple[dict[str, Any], list[dict[str, Any]], FakeServer]:
    spec = make_spec("llm", horizon=horizon, llm=LLMConfig(model="fake-model", **cfg).to_dict(),
                     prices={"fake-model": [1.0, 2.0]})
    server = FakeServer(reply)
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(server))
    v, store = run(spec, agent)
    return v, store.records(spec.run_id), server


def test_malformed_call_and_bad_arguments_become_error_observations() -> None:
    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
        last = body["messages"][-1]
        if n == 1:
            return completion(call("read_sensor", raw='{"name": "temp"', cid="a"))
        if n == 2:
            assert last["role"] == "tool" and last["tool_call_id"] == "a"
            assert "malformed tool call" in last["content"]
            return completion(call("set_coolant", {"pct": 150}, cid="b"))
        if n == 3:
            assert "invalid arguments for set_coolant" in last["content"]
            return completion(call("finish", FINISH, cid="c"))
        raise AssertionError("no more calls expected")

    v, recs, server = llm_run(reply)
    assert len(server.requests) == 3
    assert recs[0]["flags"]["invalid_args"] and recs[0]["error"].startswith("malformed tool call")
    assert recs[1]["flags"]["invalid_args"] and recs[2]["tool"] == "finish"
    assert v["end_reason"] == "finished" and v["steps"] == 20
    # usage comes from the API response and the price table
    assert recs[0]["prompt_tokens"] == 100 and recs[0]["cost_usd"] == pytest.approx(140 / 1e6)
    assert v["usage"]["llm_calls"] == 3


def test_model_that_never_stops_is_ended_by_the_token_budget() -> None:
    v, _, server = llm_run(lambda body, n: completion(call("read_sensor", {"name": "temp"}, cid=f"x{n}"),
                                                         pt=400, ct=100), horizon=40, max_total_tokens=4000)
    assert len(server.requests) == 8
    assert v["end_reason"] == "abort:max_total_tokens"
    assert v["agent_steps"] == 9 and v["steps"] == 40  # the plant keeps running without an operator
    assert v["onset_cause"] == "loop"  # it was also repeating itself
    assert any("LOOP DETECTED" in m["content"] for m in server.requests[5]["messages"] if m["role"] == "tool")


def test_step_budget_and_multiple_calls_per_response() -> None:
    reply = lambda body, n: completion(call("read_sensor", {"name": "temp"}, cid=f"a{n}"),  # noqa: E731
                                       call("read_sensor", {"name": "pressure"}, cid=f"b{n}"))
    v, recs, server = llm_run(reply, max_steps=4)
    assert len(server.requests) == 2 and [r["tool"] for r in recs[:4]] == ["read_sensor"] * 4
    assert recs[0]["llm_call"] and not recs[1]["llm_call"]  # usage is attributed to the first call
    assert v["end_reason"] == "abort:max_steps"
    tool_msgs = [m for m in server.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a1", "b1"]


def test_text_only_reply_costs_a_step_and_is_nudged() -> None:
    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
        if n == 1:
            return completion(content="<think>hmm</think>Let me think about the plan first.")
        assert "without a tool call" in body["messages"][-1]["content"]
        assert body["messages"][-2]["content"] == "Let me think about the plan first."  # <think> stripped
        return completion(call("finish", FINISH))

    v, recs, _ = llm_run(reply)
    assert recs[0]["tool"] is None and recs[1]["tool"] == "finish" and v["finish_step"] == 1


def test_session_boundary_erases_context_but_notes_survive() -> None:
    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
        msgs = body["messages"]
        if n == 1:
            return completion(call("write_note", {"key": "handoff", "text": "feed changed at step 3"}, cid="w"))
        if msgs[-1]["role"] == "user" and msgs[-1]["content"].startswith("Session 2"):
            assert len(msgs) == 2  # only the system prompt and the session intro remain
            return completion(call("read_notes", cid="r"))
        if msgs[-1].get("tool_call_id") == "r":
            assert "feed changed at step 3" in msgs[-1]["content"]
            return completion(call("finish", FINISH, cid="f"))
        sensor = ["temp", "pressure"][n % 2]
        return completion(call("read_sensor", {"name": sensor}, cid=f"s{n}"))

    spec = make_spec("llm", horizon=60, llm=LLMConfig(model="fake").to_dict(), session_len=20)
    server = FakeServer(reply)
    v, store = run(spec, LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(server)))
    assert v["finish_step"] == 21
    assert store.records(spec.run_id)[20]["tool"] == "read_notes"


def test_context_budget_trims_window_and_saves_summary_to_notes() -> None:
    reply = lambda body, n: completion(call("read_sensor", {"name": ["temp", "pressure"][n % 2]}, cid=f"c{n}"))  # noqa: E731
    _, recs, server = llm_run(reply, horizon=40, context_budget_tokens=2000, keep_last_messages=6)
    summaries = [r for r in recs if r["tool"] == "write_note" and r["args"]["key"] == SUMMARY_KEY]
    assert summaries and summaries[0]["note"] == "automatic context summary"
    assert "call read_sensor" in summaries[0]["args"]["text"]
    sizes = [(len(json.dumps(b["messages"])) + len(json.dumps(b["tools"]))) // 4 for b in server.requests]
    assert max(sizes) <= 2000 + 100  # never more than one message over budget
    assert any(b < a for a, b in pairwise(sizes))  # the window actually shrank
    roles_after_trim = [m["role"] for m in server.requests[-1]["messages"][:3]]
    assert roles_after_trim[:2] == ["system", "user"] and roles_after_trim[2] != "tool"


def test_llm_run_resumes_after_a_crash() -> None:
    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:  # depends only on the conversation
        k = sum(1 for m in body["messages"] if m["role"] == "tool")
        name, args = [("read_sensor", {"name": "temp"}), ("set_coolant", {"pct": 50 + k % 3}),
                      ("get_alarms", {})][k % 3]
        return completion(call(name, args, cid=f"k{k}"))

    spec = make_spec("llm", horizon=50, llm=LLMConfig(model="fake").to_dict(), session_len=20)

    def agent() -> LLMAgent:
        return LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(FakeServer(reply)))

    whole, s1 = run(spec, agent())
    s2 = Store(":memory:")
    with pytest.raises(SimulatedCrash):
        Runner(s2, runs_dir=None).start(spec, agent(), crash_after=27)
    resumed = Runner(s2, runs_dir=None).resume(spec.run_id, agent())

    def no_clock(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k != "llm_latency_ms"} for r in recs]

    assert no_clock(s1.records(spec.run_id)) == no_clock(s2.records(spec.run_id))
    assert whole["checks"] == resumed["checks"] and whole["onset_step"] == resumed["onset_step"]


def test_http_errors_do_not_crash_the_run() -> None:
    spec = make_spec("llm", horizon=10, llm=LLMConfig(model="fake").to_dict())
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    v, _ = run(spec, agent)
    assert v["end_reason"].startswith("abort:llm_errors") and v["agent_steps"] == 3
    assert v["usage"]["llm_errors"] == 2 and v["usage"]["llm_calls"] == 0


def test_parse_arguments() -> None:
    assert parse_arguments('{"pct": 5}') == ({"pct": 5}, None)
    assert parse_arguments("") == ({}, None)
    assert parse_arguments("[1, 2]")[1] == "malformed tool call: arguments must be a JSON object"
    assert parse_arguments("{oops")[1].startswith("malformed tool call: arguments are not valid JSON")


def test_no_think_switch_reaches_system_prompt_and_session_intro() -> None:
    def reply(body: dict[str, Any], n: int) -> dict[str, Any]:
        return completion(call("finish", FINISH))

    _, _, server = llm_run(reply, horizon=10, no_think=True)
    first = server.requests[0]["messages"]
    assert first[0]["role"] == "system" and first[0]["content"].endswith("/no_think")
    assert first[1]["role"] == "user" and first[1]["content"].endswith("/no_think")

    _, _, plain = llm_run(reply, horizon=10)
    assert "/no_think" not in json.dumps(plain.requests[0]["messages"])


def test_local_endpoints_bypass_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from horizon_bench.agents.llm import is_loopback

    assert is_loopback("http://localhost:11434/v1") and is_loopback("http://127.0.0.1:11434/v1")
    assert is_loopback("http://[::1]:11434/v1") and not is_loopback("https://api.example.com/v1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")
    local = LLMAgent(make_spec("llm", llm=LLMConfig(base_url="http://localhost:11434/v1").to_dict()),
                     get_family("reactor"))
    remote = LLMAgent(make_spec("llm", llm=LLMConfig(base_url="https://api.example.com/v1").to_dict()),
                      get_family("reactor"))
    assert local.client.trust_env is False and remote.client.trust_env is True
