import pytest

from apps.backend.agents.core_agent import CoreAgent

pytestmark = pytest.mark.asyncio


async def test_core_agent_skip_rag_for_summary_only():
    agent = CoreAgent()
    out = await agent.run("请只总结，不用RAG", {"tokens": {}, "highlights": ["[ERROR] x"]})
    assert out["need_rag"] is False
    assert out["selected_tools"] == []


async def test_core_agent_default_route_on_error_highlights():
    agent = CoreAgent()
    out = await agent.run("why fail", {"tokens": {"mentions_timeout": False}, "highlights": ["[ERROR] timeout"]})
    assert out["need_rag"] is True
    assert out["selected_tools"] == ["spec", "tp"]
