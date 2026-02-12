import logging
import httpx
from typing import Dict, Any, Optional
from apps.backend.core.config import settings
from apps.backend.core.errors import DifyError

logger = logging.getLogger(__name__)


def _normalize_base(url: str) -> str:
    if not url:
        return ""
    u = url.rstrip("/")
    # allow user pass without /v1
    if not u.endswith("/v1"):
        u = u + "/v1"
    return u


class DifyClient:
    """
    Use Dify Chat Messages API (default).
    We assume each knowledge base corresponds to an APP (spec app / tp app), identified by API key.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base = _normalize_base(settings.dify_base_url)

    async def ask(self, query: str, *, user: str = "jupiter", conversation_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.base or not self.api_key:
            raise DifyError("Dify base url or api key not configured")

        url = f"{self.base}/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # IMPORTANT: 让 Dify 输出“可引用证据”，并尽量带 citation/来源字段（如果你们 Dify 配置支持）
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": user,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            raise DifyError(f"Dify ask failed: {e}") from e


def dify_text_and_citations(resp: Dict[str, Any]) -> tuple[str, list[dict]]:
    """
    Dify 返回字段在不同版本可能有差异，这里做兼容：
    - text: answer / data.answer / message
    - citations: resp.get("metadata", {}).get("citations", ...) 或自定义字段
    """
    text = ""
    if "answer" in resp and isinstance(resp["answer"], str):
        text = resp["answer"]
    elif "data" in resp and isinstance(resp["data"], dict) and isinstance(resp["data"].get("answer"), str):
        text = resp["data"]["answer"]
    elif "message" in resp and isinstance(resp["message"], str):
        text = resp["message"]

    citations = []
    meta = resp.get("metadata") or resp.get("data", {}).get("metadata") or {}
    if isinstance(meta, dict):
        c = meta.get("citations") or meta.get("sources") or []
        if isinstance(c, list):
            citations = c
    return text, citations
