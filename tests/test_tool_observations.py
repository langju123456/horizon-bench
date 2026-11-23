"""D003: inspect the actual model-facing tool message through MockTransport."""

from __future__ import annotations

import json
from typing import Any

import httpx

from conftest import make_spec
from horizon_bench.agents.base import Observation
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.family import get_family


def _sent_observation(result: Any, mode: str, tools: str = "rich") -> str:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": []}}]})

    spec = make_spec("llm", tools=tools, llm=LLMConfig(model="fake", tool_observation=mode).to_dict())
    agent = LLMAgent(spec, get_family("reactor"), transport=httpx.MockTransport(handler))
    agent.start_session(0, 0)
    agent.st["pending"] = {"id": "tool-1", "name": "open_source"}
    agent._absorb(Observation(1, 0, result, []))
    agent._call_model()
    return requests[0]["messages"][-1]["content"]


RICH_SUCCESS = {
    "value": {"text": "中文原表", "source_url": "https://example.test/年报"},
    "ok": True,
    "error": None,
    "confidence": 1.0,
    "age_steps": 0,
    "latency_ms": 50,
}


def test_a_business_object_with_wrapper_like_fields_stays_intact() -> None:
    extra = {**RICH_SUCCESS, "source_id": "table-11"}
    assert json.loads(_sent_observation(extra, "business"))["result"] == extra
    assert json.loads(_sent_observation(RICH_SUCCESS, "business", tools="bare"))["result"] == RICH_SUCCESS


def test_default_observation_is_byte_compatible_ascii_json() -> None:
    assert _sent_observation(RICH_SUCCESS, "escaped") == json.dumps({"step": 0, "result": RICH_SUCCESS})


def test_unicode_observation_preserves_chinese_with_same_structure() -> None:
    sent = _sent_observation(RICH_SUCCESS, "unicode")
    assert sent == json.dumps({"step": 0, "result": RICH_SUCCESS}, ensure_ascii=False)
    assert "中文原表" in sent and "\\u4e2d" not in sent


def test_business_observation_unwraps_only_successful_rich_value() -> None:
    sent = _sent_observation(RICH_SUCCESS, "business")
    assert json.loads(sent) == {"step": 0, "result": RICH_SUCCESS["value"]}
    assert "中文原表" in sent and "source_url" in sent and "confidence" not in sent


def test_business_keeps_error_wrapper_and_bare_result() -> None:
    error = {**RICH_SUCCESS, "value": None, "ok": False, "error": "超时：请重试"}
    error_sent = _sent_observation(error, "business")
    assert json.loads(error_sent)["result"]["ok"] is False
    assert json.loads(error_sent)["result"]["error"] == "超时：请重试"
    bare = {"text": "裸工具中文"}
    assert json.loads(_sent_observation(bare, "business")) == {"step": 0, "result": bare}
