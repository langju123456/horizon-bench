import json
from copy import deepcopy

import httpx

from horizon_bench.agents.base import Observation
from horizon_bench.agents.citation_support import bind_support
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.env.annual_handoff import ANNUAL_HANDOFF
from horizon_bench.spec import RunSpec


def pages():
    return {"37": {"source_url": "https://example.org/a.pdf", "text":
        "单位：千元。\n指标 | 2025 年全年 | 2024 年全年\n经营活动产生的现金流量净额 | 120 | 99\n"
        "指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度"},
        "38": {"source_url": "https://example.org/a.pdf", "text":
        "接第37页，表头和单位在前页。\n经营活动产生的现金流量净额 | 20 | 30 | 30 | 40"}}


def report(period="全年", amount=120):
    return {"period": period, "amount_thousand_cny": amount, "unit": "千元", "source_pages": [37, 38]}


def test_exact_cell_and_header_support_without_read_page_overinclusion():
    assert bind_support(pages(), report(), "2025")["pages"] == [37]
    assert bind_support(pages(), report("第四季度", 40), "2025")["pages"] == [37, 38]
    source = pages()
    source["38"]["text"] = ("单位：千元。\n指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度\n"
                            "经营活动产生的现金流量净额 | 20 | 30 | 30 | 40")
    assert bind_support(source, report("第四季度", 40), "2025")["pages"] == [38]


def test_no_support_does_not_invent_or_guess_pages():
    assert bind_support({}, report(), "2025") is None
    assert bind_support({"38": pages()["38"]}, report("第四季度", 40), "2025") is None
    assert bind_support(pages(), report(amount=99), "2025") is None
    assert bind_support(pages(), report(amount=121), "2025") is None
    source = pages()
    source["38"]["source_url"] = "https://example.org/b.pdf"
    assert bind_support(source, report(), "2025") is None
    source = pages()
    source["39"] = deepcopy(source["37"])
    assert bind_support(source, report(), "2025") is None
    source = pages()
    source["37"]["text"] = source["37"]["text"].replace("单位：千元。", "")
    assert bind_support(source, report(), "2025") is None


def test_runtime_preserves_model_claims_and_binds_only_observed_evidence():
    spec = RunSpec(run_id="binding", batch="test", family="annual_handoff", policy="llm", tools="rich",
                   horizon=12, session_len=12, seed=0, seed_index=0, split="dev", variants=["handoff_full"],
                   llm=LLMConfig(model="test", submission="grounded").to_dict())
    agent = LLMAgent(spec, ANNUAL_HANDOFF, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    agent.start_session(0, 0)
    proposed = {**report(), "reviewer_note": "keep the original conclusion"}
    call = {"tool": "finish", "args": {"report": proposed}, "id": "submit", "error": None}
    assert agent._emit(call, {}).args["report"] == proposed
    for page, source in pages().items():
        agent.st["pending"] = {"id": "read" + page, "name": "open_source"}
        agent._absorb(Observation(1, 0, {"ok": True, "value": {**source, "page": int(page), "ok": True}}))
    saved = agent.get_state()
    agent.start_session(1, 1)
    assert agent._emit(call, {}).args["report"] == proposed  # new session must re-read sources
    agent.set_state(saved)
    emitted = agent._emit(call, {"prompt_tokens": 17})
    assert emitted.args["report"] == {**proposed, "source_pages": [37]}
    assert proposed["source_pages"] == [37, 38]  # raw model proposal is untouched
    assert emitted.meta["prompt_tokens"] == 17
    assert json.loads(emitted.meta["note"])["model_source_pages"] == [37, 38]
    wrong = {**call, "args": {"report": {**proposed, "amount_thousand_cny": 121}}}
    assert agent._emit(wrong, {}).args == wrong["args"]  # never repair the claimed amount
    agent.client.close()
