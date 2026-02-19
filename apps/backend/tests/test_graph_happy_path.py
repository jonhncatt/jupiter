import pytest

pytestmark = pytest.mark.asyncio


async def test_graph_runs(monkeypatch):
    # monkeypatch Dify + core finalize to avoid network
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.core.models import ToolResult, Evidence

    async def fake_run(self, q, ctx):
        return ToolResult(tool=self.name, ok=True, summary="fake", evidences=[Evidence(source="fake", snippet="s", meta={})])

    async def fake_core(self, q, parsed, raw_log=""):
        return {"selected_tools": ["spec", "tp"], "reason": "mock route", "need_rag": True, "round_hint": 2}

    async def fake_finalize(self, *, query, parsed, core_plan, expert_reports):
        return "根因：mock\n建议：mock\n下一步：mock"

    monkeypatch.setattr(SpecAgent, "run", fake_run)
    monkeypatch.setattr(TpAgent, "run", fake_run)
    monkeypatch.setattr(CoreAgent, "plan", fake_core)
    monkeypatch.setattr(CoreAgent, "finalize", fake_finalize)

    from apps.backend.services.log_parser import LogParser
    from apps.backend.services.log_fetcher import LogFetcher
    from apps.backend.tools.zeus_portal import ZeusPortalClient
    from apps.backend.agents.fetch_agent import FetchAgent
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.agents.jira_agent import JiraAgent
    from apps.backend.graph.nodes import make_nodes
    from apps.backend.graph.build_graph import build
    from apps.backend.tools.dify_client import DifyClient
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent

    fetch_agent = FetchAgent(LogFetcher(ZeusPortalClient()))
    parser = LogParser()
    core = CoreAgent()

    spec = SpecAgent(DifyClient("k"))
    tp = TpAgent(DifyClient("k"))
    jira = JiraAgent()

    node_fetch, node_parse, node_core_plan, node_experts, node_finalize = make_nodes(
        fetch_agent, parser, core, spec, tp, jira
    )
    g = build(node_fetch, node_parse, node_core_plan, node_experts, node_finalize)
    out = await g.ainvoke({"request_id": "x", "user_query": "why", "matrix_id": None, "test_id": None, "zeus_test_url": None})
    assert "draft_summary" in out
    assert "final_summary" in out
    assert out["core_plan"]["selected_tools"] == ["spec", "tp"]
