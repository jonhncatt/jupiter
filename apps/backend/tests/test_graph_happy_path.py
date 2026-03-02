import pytest

pytestmark = pytest.mark.asyncio


async def test_graph_runs(monkeypatch):
    # monkeypatch Dify + core finalize to avoid network
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.agents.evidence_judge import EvidenceJudge
    from apps.backend.agents.intent_parser_agent import IntentParserAgent
    from apps.backend.agents.fetch_agent import FetchAgent
    from apps.backend.core.models import ToolResult, Evidence

    seen_queries = {}

    async def fake_run(self, q, ctx):
        seen_queries[self.name] = q
        return ToolResult(
            tool=self.name,
            ok=True,
            summary="fake",
            evidences=[Evidence(source="fake", snippet="JIRA-1 /src/main.cpp function_x", meta={})],
            debug={"evidence_score": 8, "rounds": [{"citations_count": 1}]},
        )

    async def fake_core(self, q, parsed, raw_log=""):
        return {
            "selected_tools": ["spec", "tp"],
            "reason": "mock route",
            "need_rag": True,
            "round_hint": 2,
            "expert_queries": {
                "spec": "spec specific query from core",
                "tp": "tp specific query from core",
            },
        }

    async def fake_finalize(self, *, query, parsed, core_plan, expert_reports):
        return "根因：mock\n建议：mock\n下一步：mock"

    async def fake_intent(self, **kwargs):
        return {
            "sku": kwargs.get("sku"),
            "matrix_id": "1",
            "test_id": "2",
            "zeus_test_url": None,
            "normalized_query": kwargs.get("user_query"),
            "source": "test",
            "confidence": 1.0,
            "notes": "test",
        }

    async def fake_fetch(self, *, sku, matrix_id, test_id, zeus_test_url):
        return {
            "raw_log": "[ERROR] timeout",
            "fetch_meta": {
                "agent": self.name,
                "sku": sku,
                "matrix_id": matrix_id,
                "test_id": test_id,
                "zeus_test_url": zeus_test_url,
                "source": "test",
                "reason": "ok",
                "files_count": 1,
                "steps": [{"step": "fetch.test"}],
            },
        }

    monkeypatch.setattr(SpecAgent, "run", fake_run)
    monkeypatch.setattr(TpAgent, "run", fake_run)
    monkeypatch.setattr(CoreAgent, "plan", fake_core)
    monkeypatch.setattr(CoreAgent, "finalize", fake_finalize)
    monkeypatch.setattr(IntentParserAgent, "run", fake_intent)
    monkeypatch.setattr(FetchAgent, "run", fake_fetch)

    from apps.backend.services.log_parser import LogParser
    from apps.backend.services.input_validator import InputValidator
    from apps.backend.services.log_fetcher import LogFetcher
    from apps.backend.tools.zeus_portal import ZeusPortalClient
    from apps.backend.agents.fetch_agent import FetchAgent
    from apps.backend.agents.intent_parser_agent import IntentParserAgent
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.agents.jira_agent import JiraAgent
    from apps.backend.graph.nodes import make_nodes
    from apps.backend.graph.build_graph import build
    from apps.backend.tools.dify_client import DifyClient
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent

    fetch_agent = FetchAgent(LogFetcher(ZeusPortalClient()))
    intent_parser = IntentParserAgent()
    validator = InputValidator()
    parser = LogParser()
    core = CoreAgent()
    judge = EvidenceJudge()

    spec = SpecAgent(DifyClient("k"))
    tp = TpAgent(DifyClient("k"))
    jira = JiraAgent()

    (
        node_intent,
        node_validate,
        node_fetch,
        node_parse,
        node_core_plan,
        node_experts,
        node_evidence_judge,
        node_retry_plan,
        node_finalize,
    ) = make_nodes(
        fetch_agent, intent_parser, validator, parser, core, judge, spec, tp, jira
    )
    g = build(
        node_intent,
        node_validate,
        node_fetch,
        node_parse,
        node_core_plan,
        node_experts,
        node_evidence_judge,
        node_retry_plan,
        node_finalize,
    )
    out = await g.ainvoke({"request_id": "x", "user_query": "why", "matrix_id": None, "test_id": None, "zeus_test_url": None})
    assert "draft_summary" in out
    assert "final_summary" in out
    assert out["core_plan"]["selected_tools"] == ["spec", "tp"]
    assert seen_queries["spec_agent(dify)"] != "why"
    assert seen_queries["spec_agent(dify)"] == "spec specific query from core"
