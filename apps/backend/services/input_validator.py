from __future__ import annotations

import string
from typing import Any, Dict

from apps.backend.core.config import settings


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

        if zeus_test_url and not _looks_like_supported_source(zeus_test_url):
            warnings.append("zeus_test_url format not recognized as http/local path")

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
