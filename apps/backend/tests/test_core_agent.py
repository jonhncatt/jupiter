import pytest

from apps.backend.agents.core_agent import CoreAgent
from apps.backend.core.config import settings
from apps.backend.core.models import ToolResult, Evidence

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


async def test_core_agent_finalize(monkeypatch):
    from apps.backend.agents import core_agent as core_mod

    monkeypatch.setattr(core_mod, "chat", lambda system, user: "总结：ok\n可能根因：x")
    agent = CoreAgent()
    summary = await agent.finalize(
        query="why",
        parsed={"highlights": ["[ERROR] timeout"]},
        core_plan={"need_rag": True, "selected_tools": ["spec"]},
        expert_reports=[ToolResult(tool="spec", ok=True, summary="ok", evidences=[Evidence(source="s", snippet="x")])],
    )
    assert "总结" in summary


async def test_core_agent_llm_plan(monkeypatch):
    from apps.backend.agents import core_agent as core_mod

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        core_mod,
        "chat",
        lambda system, user, temperature=None: '{"selected_tools":["spec","jira"],"reason":"llm route","round_hint":1,"expert_queries":{"spec":"spec q","jira":"jira q"}}',
    )

    agent = CoreAgent()
    out = await agent.plan(
        "之前有没有类似问题，顺便解释命令返回",
        {
            "tokens": {"mentions_timeout": True},
            "highlights": ["[ERROR] timeout"],
            "domain_context": {"nvmecore": {"command_lines": ["identify", "status"]}},
        },
    )
    assert out["planner_source"] == "llm"
    assert out["selected_tools"] == ["spec", "jira"]
    assert out["expert_queries"]["spec"] == "spec q"


async def test_core_agent_plan_fallback_to_rules(monkeypatch):
    from apps.backend.agents import core_agent as core_mod

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(core_mod, "chat", lambda system, user, temperature=None: "not json")

    agent = CoreAgent()
    out = await agent.plan(
        "why fail",
        {"tokens": {"mentions_timeout": False}, "highlights": ["[ERROR] timeout"]},
    )
    assert out["planner_source"] == "rules_fallback"
    assert out["selected_tools"] == ["spec", "tp"]
