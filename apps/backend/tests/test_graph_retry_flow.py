import pytest

pytestmark = pytest.mark.asyncio


async def test_graph_retries_when_evidence_is_insufficient(monkeypatch):
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.agents.evidence_judge import EvidenceJudge
    from apps.backend.agents.fetch_agent import FetchAgent
    from apps.backend.agents.intent_parser_agent import IntentParserAgent
    from apps.backend.agents.jira_agent import JiraAgent
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent
    from apps.backend.core.models import Evidence, ToolResult
    from apps.backend.graph.build_graph import build
    from apps.backend.graph.nodes import make_nodes
    from apps.backend.services.input_validator import InputValidator
    from apps.backend.services.log_fetcher import LogFetcher
    from apps.backend.services.log_parser import LogParser
    from apps.backend.tools.dify_client import DifyClient
    from apps.backend.tools.zeus_portal import ZeusPortalClient

    call_count = {"spec": 0}

    async def fake_spec(self, q, ctx):
        call_count["spec"] += 1
        if call_count["spec"] == 1:
            return ToolResult(
                tool=self.name,
                ok=True,
                summary="weak evidence",
                evidences=[Evidence(source="dify(spec)", snippet="generic explanation", meta={})],
                debug={"evidence_score": 2, "rounds": [{"citations_count": 0}]},
            )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary="strong evidence",
            evidences=[Evidence(source="dify(spec)", snippet="CSTS.RDY shall indicate ready state", meta={})],
            debug={"evidence_score": 8, "rounds": [{"citations_count": 1}]},
        )

    async def fake_core(self, q, parsed, raw_log=""):
        return {
            "selected_tools": ["spec"],
            "reason": "mock route",
            "need_rag": True,
            "round_hint": 2,
            "expert_queries": {"spec": "explain timeout and CSTS.RDY"},
            "planner_source": "rules",
        }

    async def fake_finalize(self, *, query, parsed, core_plan, expert_reports):
        return "总结：ok"

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
            "raw_log": "[ERROR] timeout\nCSTS.RDY=0",
            "fetch_meta": {"reason": "ok", "source": "test", "files_count": 1, "steps": [{"step": "fetch.test"}]},
        }

    monkeypatch.setattr(SpecAgent, "run", fake_spec)
    monkeypatch.setattr(CoreAgent, "plan", fake_core)
    monkeypatch.setattr(CoreAgent, "finalize", fake_finalize)
    monkeypatch.setattr(IntentParserAgent, "run", fake_intent)
    monkeypatch.setattr(FetchAgent, "run", fake_fetch)

    fetch_agent = FetchAgent(LogFetcher(ZeusPortalClient()))
    intent_parser = IntentParserAgent()
    validator = InputValidator()
    parser = LogParser()
    core = CoreAgent()
    judge = EvidenceJudge()
    spec = SpecAgent(DifyClient("k"))
    tp = TpAgent(DifyClient("k"))
    jira = JiraAgent()

    nodes = make_nodes(fetch_agent, intent_parser, validator, parser, core, judge, spec, tp, jira)
    g = build(*nodes)
    out = await g.ainvoke({"request_id": "x", "user_query": "why", "matrix_id": None, "test_id": None, "zeus_test_url": None})

    assert call_count["spec"] == 2
    assert out["retry_count"] == 1
    assert out["tool_results"][0].summary == "strong evidence"
