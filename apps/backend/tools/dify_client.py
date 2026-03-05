import logging
import httpx
import re
from typing import Dict, Any, Optional
from apps.backend.core.config import settings
from apps.backend.core.errors import DifyError
from apps.backend.core.tls import tls_verify

logger = logging.getLogger(__name__)


def _normalize_base(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    # tolerate values like "http:10.22.57.219:28882"
    if re.match(r"^https?:[^/]", u):
        if u.startswith("http:"):
            u = "http://" + u[len("http:") :]
        elif u.startswith("https:"):
            u = "https://" + u[len("https:") :]
    # tolerate host:port without scheme
    if re.match(r"^[A-Za-z0-9_.-]+:\d+", u):
        u = "http://" + u

    u = u.rstrip("/")
    for suffix in ("/chat-messages", "/caht-messages", "/workflow-runs"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
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

    def chat_messages_url(self) -> str:
        return f"{self.base}/chat-messages"

    async def ask(self, query: str, *, user: str = "sequoia", conversation_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.base or not self.api_key:
            raise DifyError("Dify base url or api key not configured")

        url = self.chat_messages_url()
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
            async with httpx.AsyncClient(timeout=60, verify=tls_verify()) as client:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:800]
            except Exception:
                body = ""
            raise DifyError(
                f"Dify ask failed: status={e.response.status_code} url={url} body={body}"
            ) from e
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
