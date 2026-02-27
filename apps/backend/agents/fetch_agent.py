from typing import Any, Dict, Optional

from apps.backend.services.log_fetcher import LogFetcher


class FetchAgent:
    """
    FetchAgent owns the log acquisition step.
    It can evolve to call multiple tools (zeus/http/local cache) without changing graph wiring.
    """

    name = "fetch_agent(logs)"

    def __init__(self, fetcher: LogFetcher):
        self.fetcher = fetcher

    async def run(
        self,
        *,
        sku: Optional[str],
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> Dict[str, Any]:
        detail = await self.fetcher.fetch_raw_log_detail(
            sku=sku,
            matrix_id=matrix_id,
            test_id=test_id,
            zeus_test_url=zeus_test_url,
        )
        raw_log = detail["raw_log"]
        meta = detail.get("meta", {})
        return {
            "raw_log": raw_log,
            "fetch_meta": {
                "agent": self.name,
                "sku": sku,
                "matrix_id": matrix_id,
                "test_id": test_id,
                "zeus_test_url": zeus_test_url,
                **meta,
            },
        }
