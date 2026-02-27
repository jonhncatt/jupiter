from __future__ import annotations

import os
import string
import threading
import queue
from typing import Any, Dict

from apps.backend.core.config import settings
from apps.backend.tools.zeus_portal import build_test_url


class InputValidator:
    """
    Validate and sanitize resolved intent before tool execution.
    """

    def validate(self, intent: Dict[str, Any], request_payload: Dict[str, Any]) -> Dict[str, Any]:
        sku = _clean(intent.get("sku")) or _clean(request_payload.get("sku")) or _clean(settings.zeus_sku_default)
        matrix_id = _clean(intent.get("matrix_id")) or _clean(request_payload.get("matrix_id"))
        test_id = _clean(intent.get("test_id")) or _clean(request_payload.get("test_id"))
        zeus_test_url = _clean(intent.get("zeus_test_url")) or _clean(request_payload.get("zeus_test_url"))
        normalized_query = _clean(intent.get("normalized_query")) or _clean(request_payload.get("user_query")) or ""
        effective_source = zeus_test_url

        errors: list[str] = []
        warnings: list[str] = []

        if matrix_id and not _looks_like_id(matrix_id):
            warnings.append("matrix_id format unusual")
        if test_id and not _looks_like_id(test_id):
            warnings.append("test_id format unusual")

        template = settings.zeus_test_url_template or ""
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        if not zeus_test_url:
            if not matrix_id or not test_id:
                errors.append("missing_matrix_or_test_or_zeus_test_url")
            if "sku" in fields and not sku:
                errors.append("missing_sku_for_template")
            if not errors:
                try:
                    effective_source = build_test_url(matrix_id, test_id, sku=sku)
                except Exception as e:
                    errors.append(f"template_resolve_failed:{e}")

        source_to_check = effective_source or zeus_test_url

        if source_to_check and not _looks_like_supported_source(source_to_check):
            warnings.append("zeus_test_url format not recognized as http/local path")
        if source_to_check and _looks_like_local_source(source_to_check):
            exists = _local_source_exists(source_to_check)
            if exists is False:
                errors.append("local_path_not_found")
            elif exists is None:
                errors.append("local_path_check_timeout_or_unreachable")

        valid = len(errors) == 0
        return {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "resolved": {
                "sku": sku,
                "matrix_id": matrix_id,
                "test_id": test_id,
                "zeus_test_url": zeus_test_url,
                "effective_source": effective_source,
                "user_query": normalized_query,
            },
        }


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _looks_like_id(v: str) -> bool:
    if not v:
        return False
    if len(v) > 64:
        return False
    # accept numeric or mixed ascii token
    return v.replace("-", "").replace("_", "").isalnum()


def _looks_like_supported_source(v: str) -> bool:
    s = (v or "").strip()
    lower = s.lower()
    if lower.startswith(("http://", "https://", "file://")):
        return True
    if s.startswith("\\\\"):  # UNC
        return True
    if s.startswith(("/", "./", "../")):
        return True
    if "\\" in s:
        return True
    return len(s) >= 2 and s[1] == ":" and s[0].isalpha()  # Windows drive path


def _looks_like_local_source(v: str) -> bool:
    s = (v or "").strip()
    lower = s.lower()
    if lower.startswith(("http://", "https://")):
        return False
    return _looks_like_supported_source(s)


def _local_source_exists(v: str) -> bool:
    s = (v or "").strip()
    if s.lower().startswith("file://"):
        s = s[7:]
    result_q: queue.Queue[bool | Exception] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_q.put(os.path.exists(s))
        except Exception as e:
            result_q.put(e)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=2.0)
    if thread.is_alive():
        return None
    try:
        result = result_q.get_nowait()
    except queue.Empty:
        return False
    if isinstance(result, Exception):
        return False
    return bool(result)
