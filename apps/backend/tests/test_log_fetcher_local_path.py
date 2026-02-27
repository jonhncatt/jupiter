import io
import zipfile

import pytest

from apps.backend.core.errors import LogFetchError
from apps.backend.services.log_fetcher import LogFetcher
from apps.backend.tools.zeus_portal import ZeusPortalClient

pytestmark = pytest.mark.asyncio


async def test_fetch_raw_log_from_local_directory(tmp_path, monkeypatch):
    zip_path = tmp_path / "logsarchive.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.log", "[ERROR] timeout waiting for controller ready\n")
    zip_path.write_bytes(buf.getvalue())

    fetcher = LogFetcher(ZeusPortalClient())

    async def _should_not_call_http(*args, **kwargs):
        raise AssertionError("HTTP download should not be called for local path")

    monkeypatch.setattr(fetcher.zeus, "download_logs_zip", _should_not_call_http)

    raw = await fetcher.fetch_raw_log(
        sku=None,
        matrix_id=None,
        test_id=None,
        zeus_test_url=str(tmp_path),
    )
    assert "timeout waiting for controller ready" in raw

    detail = await fetcher.fetch_raw_log_detail(
        sku=None,
        matrix_id=None,
        test_id=None,
        zeus_test_url=str(tmp_path),
    )
    meta = detail["meta"]
    assert meta["downloaded_zip_path"].endswith("logsarchive.zip")
    assert meta["extract_status"] == "ok"
    assert meta["zip_member_count"] >= 1
    assert "main.log" in meta["selected_text_files"]


async def test_fetch_raw_log_from_invalid_explicit_path_raises(tmp_path):
    fetcher = LogFetcher(ZeusPortalClient())
    bad_path = str(tmp_path / "not-exist")

    with pytest.raises(LogFetchError):
        await fetcher.fetch_raw_log(
            sku=None,
            matrix_id=None,
            test_id=None,
            zeus_test_url=bad_path,
        )
