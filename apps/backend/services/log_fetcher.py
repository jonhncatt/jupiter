import logging
from typing import Optional
from apps.backend.tools.zeus_portal import ZeusPortalClient, build_test_url
from apps.backend.services.zip_utils import extract_text_files, merge_texts

logger = logging.getLogger(__name__)


class LogFetcher:
    def __init__(self, zeus: ZeusPortalClient):
        self.zeus = zeus

    async def fetch_raw_log(
        self,
        *,
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> str:
        # allow direct url override
        if zeus_test_url:
            test_url = zeus_test_url
        elif matrix_id and test_id:
            test_url = build_test_url(matrix_id, test_id)
        else:
            logger.warning("No matrix_id/test_id/test_url provided -> fallback mock log")
            return _mock_log()

        try:
            zip_bytes = await self.zeus.download_logs_zip(test_url=test_url)
            files = extract_text_files(zip_bytes)
            if not files:
                logger.warning("zip extracted no text files -> fallback mock log")
                return _mock_log()
            return merge_texts(files)
        except Exception as e:
            logger.warning("fetch_raw_log failed: %s -> fallback mock", e)
            return _mock_log()


def _mock_log() -> str:
    return "\n".join(
        [
            "[INFO] test start: PCBasher Running",
            "[WARN] latency spike detected",
            "[ERROR] timeout waiting for controller ready (CSTS.RDY=0)",
            "[INFO] end",
        ]
    )
