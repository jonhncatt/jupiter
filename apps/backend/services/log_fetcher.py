import logging
import os
from typing import Optional

from apps.backend.tools.zeus_portal import ZeusPortalClient, build_test_url
from apps.backend.core.config import settings
from apps.backend.services.zip_utils import extract_text_files, merge_texts

logger = logging.getLogger(__name__)


class LogFetcher:
    def __init__(self, zeus: ZeusPortalClient):
        self.zeus = zeus

    async def fetch_raw_log(
        self,
        *,
        sku: Optional[str],
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> str:
        # allow direct url override
        if zeus_test_url:
            test_url = zeus_test_url
        elif matrix_id and test_id:
            test_url = build_test_url(matrix_id, test_id, sku=sku)
        else:
            logger.warning("No matrix_id/test_id/test_url provided -> fallback mock log")
            return _mock_log()

        try:
            if _is_local_source(test_url):
                zip_bytes = _read_local_zip_bytes(test_url)
            else:
                zip_bytes = await self.zeus.download_logs_zip(test_url=test_url)
            files = extract_text_files(zip_bytes)
            if not files:
                logger.warning("zip extracted no text files -> fallback mock log")
                return _mock_log()
            return merge_texts(files)
        except Exception as e:
            logger.warning("fetch_raw_log failed: %s -> fallback mock", e)
            return _mock_log()


def _is_local_source(path_or_url: str) -> bool:
    v = (path_or_url or "").strip()
    lower = v.lower()
    if lower.startswith(("http://", "https://")):
        return False
    if lower.startswith("file://"):
        return True
    if v.startswith("\\\\"):  # UNC path on Windows
        return True
    if "\\" in v:  # Windows-style path
        return True
    if v.startswith(("/", "./", "../")):
        return True
    return len(v) >= 2 and v[1] == ":" and v[0].isalpha()  # e.g. C:\foo


def _read_local_zip_bytes(path_or_url: str) -> bytes:
    path = (path_or_url or "").strip()
    if path.lower().startswith("file://"):
        path = path[7:]

    # Case 1: direct zip file path.
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()

    # Case 2: directory path containing logsarchive.zip (or other zip fallback).
    if os.path.isdir(path):
        direct_zip = os.path.join(path, settings.zeus_log_zip_name)
        if os.path.isfile(direct_zip):
            with open(direct_zip, "rb") as f:
                return f.read()

        zip_candidates = [
            os.path.join(path, name)
            for name in os.listdir(path)
            if name.lower().endswith(".zip")
        ]
        if zip_candidates:
            zip_candidates.sort()
            with open(zip_candidates[0], "rb") as f:
                return f.read()

        raise FileNotFoundError(f"No zip found under directory: {path}")

    raise FileNotFoundError(f"Local path not found: {path}")


def _mock_log() -> str:
    return "\n".join(
        [
            "[INFO] test start: PCBasher Running",
            "[WARN] latency spike detected",
            "[ERROR] timeout waiting for controller ready (CSTS.RDY=0)",
            "[INFO] end",
        ]
    )
