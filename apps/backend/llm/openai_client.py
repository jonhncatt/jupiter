from functools import lru_cache

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


def chat(system: str, user: str) -> str:
    c = _client()
    r = c.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return r.choices[0].message.content or ""
