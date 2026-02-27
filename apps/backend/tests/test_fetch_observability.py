import pytest

from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.tools.zeus_portal import ZeusPortalClient

pytestmark = pytest.mark.asyncio


async def test_fetch_agent_exposes_mock_reason_when_input_missing():
    agent = FetchAgent(LogFetcher(ZeusPortalClient()))
    out = await agent.run(sku=None, matrix_id=None, test_id=None, zeus_test_url=None)
    fetch_meta = out["fetch_meta"]
    assert fetch_meta["source"] == "mock"
    assert fetch_meta["reason"] == "missing_matrix_or_test_or_url"
    assert fetch_meta["steps"][-1]["step"] == "fetch.skip"
    assert "timeout waiting for controller ready" in out["raw_log"]
