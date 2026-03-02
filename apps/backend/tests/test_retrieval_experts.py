import pytest

from apps.backend.agents.jira_agent import JiraAgent
from apps.backend.agents.spec_agent import SpecAgent
from apps.backend.agents.tp_agent import TpAgent


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def ask(self, query: str, *, user: str = "jupiter", conversation_id=None):
        self.calls.append(query)
        if self.responses:
            return self.responses.pop(0)
        return {"answer": "fallback answer"}


@pytest.mark.asyncio
async def test_spec_agent_uses_multi_query_retrieval():
    client = FakeClient(
        [
            {"answer": "too short"},
            {
                "answer": "规范条款解释 " * 20,
                "metadata": {"citations": [{"quote": "CSTS.RDY shall indicate ready state"}]},
            },
        ]
    )
    agent = SpecAgent(client)
    result = await agent.run(
        "解释 identify 命令返回是否异常",
        {
            "round_hint": 3,
            "tokens": {"mentions_timeout": True, "mentions_csts_rdy": True},
            "domain_context": {
                "pcb_console": {"status": "fail", "test_name": "case_a", "revision": "R1", "script_line": "456"},
                "nvmecore": {"command_lines": ["identify", "CSTS.RDY=0", "status timeout"]},
            },
        },
    )
    assert result.ok is True
    assert len(client.calls) == 2
    assert result.debug["strategy"] == "retrieval-first-multi-query"
    assert result.debug["selected_query"] in result.debug["retrieval_queries"]


@pytest.mark.asyncio
async def test_tp_agent_uses_retrieval_queries():
    client = FakeClient(
        [
            {"answer": "没有定位到函数"},
            {
                "answer": "命中代码 " * 40,
                "metadata": {"citations": [{"quote": "pcbasher.cpp:456 run_case()"}]},
            },
        ]
    )
    agent = TpAgent(client)
    result = await agent.run(
        "帮我找测试代码",
        {
            "round_hint": 3,
            "highlights": ["[ERROR] fail at step"],
            "domain_context": {
                "pcb_console": {
                    "status": "fail",
                    "test_name": "pcbasher",
                    "revision": "RevA",
                    "script_line": "456",
                    "status_line": "FAIL pcbasher RevA #456",
                }
            },
        },
    )
    assert result.ok is True
    assert len(client.calls) == 2
    assert result.debug["strategy"] == "retrieval-first-multi-query"


@pytest.mark.asyncio
async def test_jira_agent_uses_retrieval_queries():
    client = FakeClient(
        [
            {"answer": "未命中"},
            {
                "answer": "历史缺陷 " * 40,
                "metadata": {"citations": [{"quote": "JIRA-123 fixed by updating APST timing"}]},
            },
        ]
    )
    agent = JiraAgent(client)
    result = await agent.run(
        "之前有类似问题吗",
        {
            "round_hint": 3,
            "highlights": ["[ERROR] timeout waiting for ready"],
            "domain_context": {
                "pcb_console": {"status_line": "FAIL timeout waiting for ready", "test_name": "ready_case"},
                "nvmecore": {"command_lines": ["set features APST", "timeout"]},
            },
        },
    )
    assert result.ok is True
    assert len(client.calls) == 2
    assert result.debug["strategy"] == "retrieval-first-multi-query"
