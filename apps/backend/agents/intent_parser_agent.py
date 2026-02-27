import json
import logging
import re
from typing import Any, Dict, Optional

from apps.backend.core.config import settings
from apps.backend.llm.openai_client import chat

logger = logging.getLogger(__name__)

SYSTEM_INTENT = """你是请求参数解析器。把用户问题解析为严格 JSON，字段如下：
{
  "sku": "string|null",
  "matrix_id": "string|null",
  "test_id": "string|null",
  "zeus_test_url": "string|null",
  "normalized_query": "string",
  "confidence": 0.0,
  "notes": "string"
}
要求：
1) 只返回 JSON，不要额外文本。
2) 无法确定就填 null，confidence 降低。
3) 不要编造 matrix_id/test_id。"""


class IntentParserAgent:
    name = "intent_parser_agent(llm)"

    async def run(
        self,
        *,
        user_query: str,
        sku: Optional[str],
        matrix_id: Optional[str],
        test_id: Optional[str],
        zeus_test_url: Optional[str],
    ) -> Dict[str, Any]:
        # Start with user-provided structured fields as strongest prior.
        seed = {
            "sku": _clean(sku),
            "matrix_id": _clean(matrix_id),
            "test_id": _clean(test_id),
            "zeus_test_url": _clean(zeus_test_url),
            "normalized_query": (user_query or "").strip(),
            "confidence": 0.2,
            "notes": "seed_from_request",
            "source": "seed",
        }

        # LLM parsing is optional; skip when API key is not configured.
        if not _llm_available():
            return _merge_with_heuristic(seed, user_query, note="llm_unavailable_fallback")

        user_prompt = (
            f"用户问题：{user_query}\n"
            f"请求附带字段：sku={sku}, matrix_id={matrix_id}, test_id={test_id}, zeus_test_url={zeus_test_url}\n"
            "请只输出 JSON。"
        )
        try:
            temperature = settings.openai_intent_temperature or settings.openai_temperature or None
            raw = chat(SYSTEM_INTENT, user_prompt, temperature=temperature)
            llm_obj = _try_parse_json(raw)
            if not isinstance(llm_obj, dict):
                return _merge_with_heuristic(seed, user_query, note="llm_json_invalid")
            parsed = {
                "sku": _clean(llm_obj.get("sku")) or seed["sku"],
                "matrix_id": _clean(llm_obj.get("matrix_id")) or seed["matrix_id"],
                "test_id": _clean(llm_obj.get("test_id")) or seed["test_id"],
                "zeus_test_url": _clean(llm_obj.get("zeus_test_url")) or seed["zeus_test_url"],
                "normalized_query": _clean(llm_obj.get("normalized_query")) or seed["normalized_query"],
                "confidence": _safe_conf(llm_obj.get("confidence"), default=0.6),
                "notes": _clean(llm_obj.get("notes")) or "",
                "source": "llm",
                "llm_raw_preview": (raw or "")[:600],
            }
            return _merge_with_heuristic(parsed, user_query, note="llm_plus_heuristic")
        except Exception as e:
            logger.warning("Intent parser LLM failed: %s", e)
            return _merge_with_heuristic(seed, user_query, note=f"llm_error:{e}")


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _safe_conf(v: Any, default: float) -> float:
    try:
        x = float(v)
        return max(0.0, min(1.0, x))
    except Exception:
        return default


def _llm_available() -> bool:
    key = (settings.openai_api_key or "").strip()
    return bool(key and key != "CHANGE_ME")


def _try_parse_json(raw: str) -> Any:
    if not raw:
        return None
    txt = raw.strip()
    try:
        return json.loads(txt)
    except Exception:
        pass
    # tolerate fenced block / extra prefix/suffix
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _merge_with_heuristic(base: Dict[str, Any], query: str, note: str) -> Dict[str, Any]:
    out = dict(base)
    q = query or ""
    # URL / UNC detection
    url_match = re.search(r"(https?://[^\s]+)", q)
    if url_match and not out.get("zeus_test_url"):
        out["zeus_test_url"] = url_match.group(1)
    unc_match = re.search(r"(\\\\[^\s]+)", q)
    if unc_match and not out.get("zeus_test_url"):
        out["zeus_test_url"] = unc_match.group(1)

    # lightweight ID extraction, only when explicit labels appear.
    if not out.get("matrix_id"):
        m = re.search(r"(?:matrix(?:[_\s-]?id)?\s*[:=]?\s*)(\d{2,})", q, re.I)
        if m:
            out["matrix_id"] = m.group(1)
    if not out.get("test_id"):
        t = re.search(r"(?:test(?:[_\s-]?id)?\s*[:=]?\s*)(\d{2,})", q, re.I)
        if t:
            out["test_id"] = t.group(1)

    out["source"] = out.get("source", "heuristic")
    out["notes"] = (out.get("notes") or "") + f" | {note}"
    return out
