from apps.backend.llm.openai_client import _resolve_temperature


def test_resolve_temperature():
    assert _resolve_temperature(None) is None
    assert _resolve_temperature("") is None
    assert _resolve_temperature("0.2") == 0.2
    assert _resolve_temperature(0.0) == 0.0
    assert _resolve_temperature("bad") is None
