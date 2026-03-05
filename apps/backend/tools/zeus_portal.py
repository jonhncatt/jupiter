import json
import logging
import string
import httpx
from typing import Any, Dict, Optional
from apps.backend.core.config import settings
from apps.backend.core.errors import ConfigError, ZeusDownloadError
from apps.backend.core.tls import tls_verify

logger = logging.getLogger(__name__)


def build_test_url(matrix_id: str, test_id: str, *, sku: Optional[str] = None) -> str:
    if not settings.zeus_test_url_template:
        raise ConfigError("ZEUS_TEST_URL_TEMPLATE is empty")
    template = settings.zeus_test_url_template
    values = {
        "matrix_id": matrix_id,
        "test_id": test_id,
        "sku": (sku or settings.zeus_sku_default or "").strip(),
    }

    fields = {field_name for _, field_name, _, _ in string.Formatter().parse(template) if field_name}
    unsupported_fields = [name for name in fields if name not in values]
    if unsupported_fields:
        raise ConfigError(
            f"Unsupported placeholders in ZEUS_TEST_URL_TEMPLATE: {', '.join(sorted(unsupported_fields))}. "
            "Supported placeholders: {matrix_id}, {test_id}, {sku}"
        )

    missing_fields = [name for name in fields if not values.get(name)]
    if missing_fields:
        raise ConfigError(
            f"Missing Zeus URL params for template: {', '.join(sorted(missing_fields))}. "
            "Please provide request.sku or set ZEUS_SKU_DEFAULT."
        )

    return template.format(**values)


def _headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 SequoiaBot",
    }
    if settings.zeus_cookie:
        # 直接把浏览器复制的 Cookie header 全串填进 ZEUS_COOKIE
        headers["Cookie"] = settings.zeus_cookie

    if settings.zeus_extra_headers_json:
        try:
            extra = json.loads(settings.zeus_extra_headers_json)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except Exception as e:
            logger.warning("ZEUS_EXTRA_HEADERS_JSON parse failed: %s", e)
    return headers


class ZeusPortalClient:
    """
    Strategy:
    - We assume logsarchive.zip can be fetched under:
      {test_url}/{ZEUS_LOG_ZIP_NAME}  (default)
    - If your portal uses another pattern, only adjust `resolve_zip_url`.
    """

    def resolve_zip_url(self, test_url: str) -> str:
        # 默认：test_url 后面直接拼 zip 名
        return test_url.rstrip("/") + "/" + settings.zeus_log_zip_name

    async def download_logs_zip_detail(self, *, test_url: str) -> Dict[str, Any]:
        zip_url = self.resolve_zip_url(test_url)
        headers = _headers()
        meta: Dict[str, Any] = {
            "test_url": test_url,
            "zip_url": zip_url,
            "has_cookie_header": "Cookie" in headers,
        }

        logger.info("Downloading Zeus zip: %s", zip_url)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True, verify=tls_verify()) as client:
                r = await client.get(zip_url, headers=headers)
                meta.update(
                    {
                        "status_code": r.status_code,
                        "final_url": str(r.url),
                        "content_type": r.headers.get("Content-Type", ""),
                        "content_length": len(r.content),
                    }
                )
                if r.status_code in (401, 403):
                    raise ZeusDownloadError(
                        "Zeus download unauthorized. Please set ZEUS_COOKIE (copy from browser) or headers."
                    )
                r.raise_for_status()
                if len(r.content) < 1024:
                    logger.warning("zip content too small, may be HTML error page")
                return {
                    "zip_bytes": r.content,
                    "meta": meta,
                }
        except ZeusDownloadError:
            raise
        except Exception as e:
            meta.update({"error": str(e)})
            raise ZeusDownloadError(f"Failed to download logsarchive.zip: {e}") from e

    async def download_logs_zip(self, *, test_url: str) -> bytes:
        detail = await self.download_logs_zip_detail(test_url=test_url)
        return detail["zip_bytes"]
