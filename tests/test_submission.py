"""Keep the intervention model-facing and keep eligibility separate from the hidden verdict."""

import httpx
import pytest

from horizon_bench.agents.base import Observation
from horizon_bench.agents.llm import LLMAgent, LLMConfig
from horizon_bench.cli import main
from horizon_bench.env.annual_handoff import ANNUAL_HANDOFF
from horizon_bench.spec import RunSpec
from horizon_bench.store import Store


@pytest.mark.parametrize("arm", ["auto", "fields", "evidence", "grounded", "reminder", "task_tools"])
def test_submission_strategies_change_only_the_promised_part(arm):
    cfg = LLMConfig(model="test", submission=arm)
    spec = RunSpec(run_id="test", batch="tests", policy="llm", tools="rich", horizon=12, session_len=12,
                   seed=3, seed_index=1, split="dev", family="annual_handoff", variants=["handoff_full"],
                   llm=cfg.to_dict())
    agent = LLMAgent(spec, ANNUAL_HANDOFF, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    agent.start_session(0, 0)
    names = {tool["function"]["name"] for tool in agent.tools}
    assert names == ({"read_handoff", "open_source", "finish"} if arm == "task_tools"
                     else set(ANNUAL_HANDOFF.toolbox.names()))
    assert ("amount_thousand_cny" in agent.system) == (arm in ("fields", "evidence", "grounded"))
    assert ("source_pages 是支撑最终数值的证据页" in agent.system) == (arm == "evidence")
    assert "34,092,341" not in agent.system and "保留人民币原单位" not in agent.system
    assert ("submission" in cfg.to_dict()) == (arm != "auto")
    for step in (1, 2):
        agent.st["nudge"] = True
        agent._absorb(Observation(step, 0))
        assert ("审阅人还没有收到报告" in agent.st["messages"][-1]["content"]) == (arm == "reminder" and step == 1)
        saved = agent.get_state()
        agent.set_state(saved)


def test_both_documents_have_distinct_cli_runs_and_independent_citations(tmp_path):
    cli = ["--runs-dir", str(tmp_path)]
    run = [*cli, "run", "--family", "annual_handoff", "--name", "reference", "--horizon", "12"]
    for doc in ("catl", "transfer", "holdout", "validation"):
        assert main([*run, "--handoff-doc", doc]) == 0
    db = Store(tmp_path / "hb.sqlite")
    runs = db.runs(["reference"])
    assert len(runs) == 8
    for spec, verdict in runs:
        assert verdict["success"] and main([*cli, "replay", spec.run_id]) == 0
        final = next(r["args"]["report"] for r in db.records(spec.run_id) if r["tool"] == "finish")
        pages, amount = [
            ([11, 12], 52559552), ([11], 133219982), ([11], 8712123), ([10], 34092341),
            ([11], 5544220), ([10], 16643908), ([10], 5544220), ([9], 16643908),
        ][spec.seed]
        assert final["source_pages"] == pages and final["amount_thousand_cny"] == amount
