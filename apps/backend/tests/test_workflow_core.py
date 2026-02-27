import pytest

from apps.backend.core.models import AnalyzeRequest, Evidence, ToolResult
from apps.backend.services.cache import TTLCache
from jupiter_core.workflow import run_analysis

pytestmark = pytest.mark.asyncio


async def test_run_analysis_shared_core(monkeypatch):
    from apps.backend.agents.core_agent import CoreAgent
    from apps.backend.agents.intent_parser_agent import IntentParserAgent
    from apps.backend.agents.fetch_agent import FetchAgent
    from apps.backend.agents.spec_agent import SpecAgent
    from apps.backend.agents.tp_agent import TpAgent

    async def fake_spec_tp(self, query, context):
        return ToolResult(
            tool=self.name,
            ok=True,
            summary="fake",
            evidences=[Evidence(source="fake", snippet="evidence", meta={})],
        )

    async def fake_plan(self, query, parsed, raw_log=""):
        return {
            "selected_tools": ["spec", "tp"],
            "reason": "mocked",
            "need_rag": True,
            "round_hint": 2,
        }

    async def fake_finalize(self, *, query, parsed, core_plan, expert_reports):
        return "总结：mock\n根因：mock\n建议：mock"

    async def fake_intent(self, **kwargs):
        return {
            "sku": None,
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

    monkeypatch.setattr(SpecAgent, "run", fake_spec_tp)
    monkeypatch.setattr(TpAgent, "run", fake_spec_tp)
    monkeypatch.setattr(CoreAgent, "plan", fake_plan)
    monkeypatch.setattr(CoreAgent, "finalize", fake_finalize)
    monkeypatch.setattr(IntentParserAgent, "run", fake_intent)
    monkeypatch.setattr(FetchAgent, "run", fake_fetch)

    resp = await run_analysis(
        AnalyzeRequest(request_id="r1", user_query="why failed"),
        use_cache=False,
        cache=TTLCache(600),
    )
    assert resp.request_id == "r1"
    assert "mock" in resp.overall_summary
    assert len(resp.tool_results) == 2
