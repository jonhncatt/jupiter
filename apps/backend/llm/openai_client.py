from openai import OpenAI
from apps.backend.core.config import settings


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def chat(system: str, user: str) -> str:
    c = _client()
    r = c.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return r.choices[0].message.content or ""
