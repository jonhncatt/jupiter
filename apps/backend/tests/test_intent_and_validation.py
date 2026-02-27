from apps.backend.agents.intent_parser_agent import IntentParserAgent
from apps.backend.services.input_validator import InputValidator
from apps.backend.core.config import settings

import pytest


@pytest.mark.asyncio
async def test_intent_parser_heuristic_without_llm(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "CHANGE_ME")
    agent = IntentParserAgent()
    out = await agent.run(
        user_query="请分析 matrix 40255 test 5894735 在 \\\\kiczeus-fs02\\share 下的日志",
        sku=None,
        matrix_id=None,
        test_id=None,
        zeus_test_url=None,
    )
    assert out["matrix_id"] == "40255"
    assert out["test_id"] == "5894735"
    assert out["zeus_test_url"].startswith("\\\\kiczeus-fs02")


def test_input_validator_requires_source():
    v = InputValidator()
    out = v.validate(intent={}, request_payload={"user_query": "why fail"})
    assert out["valid"] is False
    assert "missing_matrix_or_test_or_zeus_test_url" in out["errors"]


def test_input_validator_rejects_missing_local_path():
    v = InputValidator()
    out = v.validate(
        intent={"zeus_test_url": r"C:\definitely-not-exist\logs"},
        request_payload={"user_query": "why fail"},
    )
    assert out["valid"] is False
    assert "local_path_not_found" in out["errors"]


def test_input_validator_rejects_missing_template_resolved_local_path(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", r"C:\logs\{matrix_id}\{test_id}")
    v = InputValidator()
    out = v.validate(
        intent={"matrix_id": "40255", "test_id": "5894735"},
        request_payload={"user_query": "why fail"},
    )
    assert out["valid"] is False
    assert "local_path_not_found" in out["errors"]
    assert out["resolved"]["effective_source"].endswith(r"40255\5894735")
