import pytest

from apps.backend.agents.fetch_agent import FetchAgent
from apps.backend.core.errors import LogFetchError
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.tools.zeus_portal import ZeusPortalClient

pytestmark = pytest.mark.asyncio


async def test_fetch_agent_rejects_missing_input():
    agent = FetchAgent(LogFetcher(ZeusPortalClient()))
    with pytest.raises(LogFetchError):
        await agent.run(sku=None, matrix_id=None, test_id=None, zeus_test_url=None)
