from functools import lru_cache
from typing import Optional

import httpx
from openai import OpenAI

from apps.backend.core.config import settings
from apps.backend.core.tls import tls_verify


@lru_cache(maxsize=1)
def _http_client() -> httpx.Client:
    return httpx.Client(timeout=60, verify=tls_verify())


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        http_client=_http_client(),
    )


def _resolve_temperature(value: Optional[float | str]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def chat(system: str, user: str, *, temperature: Optional[float | str] = None) -> str:
    c = _client()
    kwargs = {
        "model": settings.openai_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    temp = _resolve_temperature(temperature)
    if temp is not None:
        kwargs["temperature"] = temp
    try:
        r = c.chat.completions.create(**kwargs)
    except Exception as e:
        # Some Azure/OpenAI-compatible deployments reject any explicit temperature value.
        if temp is not None and _supports_retry_without_temperature(e):
            kwargs.pop("temperature", None)
            r = c.chat.completions.create(**kwargs)
        else:
            raise
    return r.choices[0].message.content or ""


def _supports_retry_without_temperature(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "temperature" in msg and ("unsupported" in msg or "does not support" in msg)
