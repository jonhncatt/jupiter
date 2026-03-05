import logging
import os
import tempfile
import uuid
from typing import Optional

from apps.backend.core.errors import LogFetchError
from apps.backend.tools.zeus_portal import ZeusPortalClient, build_test_url
from apps.backend.core.config import settings
from apps.backend.services.zip_utils import extract_text_files, list_zip_members, merge_texts

logger = logging.getLogger(__name__)


class LogFetcher:
    def __init__(self, zeus: ZeusPortalClient):
        self.zeus = zeus

    async def fetch_raw_log_detail(
        self,
        *,
        sku: Optional[str],
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> dict:
        explicit_source = bool((zeus_test_url or "").strip() or (matrix_id and test_id))
        meta = {
            "source": "unresolved",
            "reason": "",
            "test_url": zeus_test_url,
            "files_count": 0,
            "steps": [],
        }
        # allow direct url override
        if zeus_test_url:
            test_url = zeus_test_url
            meta["steps"].append({"step": "input.resolve", "strategy": "direct_url_or_path"})
        elif matrix_id and test_id:
            test_url = build_test_url(matrix_id, test_id, sku=sku)
            meta["steps"].append(
                {
                    "step": "input.resolve",
                    "strategy": "template",
                    "template": settings.zeus_test_url_template,
                    "sku": sku,
                    "matrix_id": matrix_id,
                    "test_id": test_id,
                }
            )
        else:
            reason = "missing_matrix_or_test_or_url"
            logger.warning("No matrix_id/test_id/test_url provided")
            meta.update({"reason": reason})
            meta["steps"].append({"step": "fetch.skip", "reason": reason})
            raise LogFetchError("No matrix_id/test_id/test_url provided")

        meta["test_url"] = test_url
        try:
            if _is_local_source(test_url):
                meta["source"] = "local_zip"
                zip_bytes, local_meta = _read_local_zip_bytes_detail(test_url)
                meta.update(local_meta)
                meta["downloaded_zip_path"] = local_meta.get("selected_zip_path", "")
                meta["steps"].append(
                    {
                        "step": "fetch.local_zip",
                        "selected_zip_path": local_meta.get("selected_zip_path"),
                        "mode": local_meta.get("local_mode"),
                    }
                )
            else:
                meta["source"] = "zeus_http"
                zeus_detail = await self.zeus.download_logs_zip_detail(test_url=test_url)
                zip_bytes = zeus_detail["zip_bytes"]
                meta.update(zeus_detail.get("meta", {}))
                meta["downloaded_zip_path"] = _save_debug_zip(zip_bytes)
                meta["steps"].append(
                    {
                        "step": "fetch.zeus_http",
                        "zip_url": meta.get("zip_url"),
                        "status_code": meta.get("status_code"),
                        "final_url": meta.get("final_url"),
                        "content_type": meta.get("content_type"),
                        "content_length": meta.get("content_length"),
                        "has_cookie_header": meta.get("has_cookie_header"),
                        "downloaded_zip_path": meta.get("downloaded_zip_path"),
                    }
                )
            members = list_zip_members(zip_bytes)
            meta["zip_member_count"] = len(members)
            meta["zip_members_preview"] = members[:20]
            meta["zip_members_full"] = members[:200]
            files = extract_text_files(zip_bytes)
            if not files:
                reason = "zip_has_no_text_files"
                logger.warning("zip extracted no text files")
                meta.update({"reason": reason, "files_count": 0})
                meta["extract_status"] = "empty"
                meta["steps"].append(
                    {
                        "step": "zip.extract",
                        "status": "empty",
                        "reason": reason,
                        "zip_member_count": meta.get("zip_member_count", 0),
                    }
                )
                raise LogFetchError(f"Fetched zip but no supported text logs were found from source: {test_url}")
            meta.update(
                {
                    "reason": "ok",
                    "files_count": len(files),
                    "top_files": [name for name, _ in files[:5]],
                    "selected_text_files": [name for name, _ in files],
                    "extract_status": "ok",
                }
            )
            meta["steps"].append(
                {
                    "step": "zip.extract",
                    "status": "ok",
                    "files_count": len(files),
                    "top_files": [name for name, _ in files[:5]],
                    "selected_text_files": [name for name, _ in files],
                    "zip_member_count": meta.get("zip_member_count", 0),
                }
            )
            return {"raw_log": merge_texts(files), "meta": meta}
        except LogFetchError:
            raise
        except Exception as e:
            reason = f"fetch_failed:{e}"
            logger.warning("fetch_raw_log failed: %s", e)
            meta.update({"reason": reason})
            meta.setdefault("extract_status", "error")
            meta["steps"].append({"step": "fetch.failed", "reason": reason})
            raise LogFetchError(f"Fetch failed for source `{test_url}`: {e}") from e

    async def fetch_raw_log(
        self,
        *,
        sku: Optional[str],
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> str:
        # backward-compatible API for existing callers/tests
        detail = await self.fetch_raw_log_detail(
            sku=sku,
            matrix_id=matrix_id,
            test_id=test_id,
            zeus_test_url=zeus_test_url,
        )
        return detail["raw_log"]


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
    data, _ = _read_local_zip_bytes_detail(path_or_url)
    return data


def _read_local_zip_bytes_detail(path_or_url: str) -> tuple[bytes, dict]:
    path = (path_or_url or "").strip()
    if path.lower().startswith("file://"):
        path = path[7:]
    meta: dict = {
        "local_input_path": path,
        "local_mode": "",
        "selected_zip_path": "",
    }

    # Case 1: direct zip file path.
    if os.path.isfile(path):
        meta.update({"local_mode": "direct_zip", "selected_zip_path": path})
        with open(path, "rb") as f:
            return f.read(), meta

    # Case 2: directory path containing logsarchive.zip (or other zip fallback).
    if os.path.isdir(path):
        meta["local_mode"] = "directory_scan"
        direct_zip = os.path.join(path, settings.zeus_log_zip_name)
        if os.path.isfile(direct_zip):
            meta.update({"selected_zip_path": direct_zip})
            with open(direct_zip, "rb") as f:
                return f.read(), meta

        zip_candidates = [
            os.path.join(path, name)
            for name in os.listdir(path)
            if name.lower().endswith(".zip")
        ]
        meta["zip_candidates"] = zip_candidates[:20]
        if zip_candidates:
            zip_candidates.sort()
            meta.update({"selected_zip_path": zip_candidates[0]})
            with open(zip_candidates[0], "rb") as f:
                return f.read(), meta

        raise FileNotFoundError(f"No zip found under directory: {path}")

    raise FileNotFoundError(f"Local path not found: {path}")


def _save_debug_zip(zip_bytes: bytes) -> str:
    base_dir = os.path.join(tempfile.gettempdir(), "sequoia_fetch")
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, f"{uuid.uuid4().hex}.zip")
    with open(path, "wb") as f:
        f.write(zip_bytes)
    return path
