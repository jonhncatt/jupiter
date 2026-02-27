import pytest
from apps.backend.tools.zeus_portal import build_test_url
from apps.backend.core.config import settings
from apps.backend.core.errors import ConfigError


def test_build_test_url_requires_template(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", "https://x/{matrix_id}/{test_id}")
    monkeypatch.setattr(settings, "zeus_sku_default", "")
    assert build_test_url("1", "2") == "https://x/1/2"


def test_build_test_url_with_sku(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", "https://x/{sku}/{matrix_id}/{test_id}")
    monkeypatch.setattr(settings, "zeus_sku_default", "")
    assert build_test_url("1", "2", sku="nx1") == "https://x/nx1/1/2"


def test_build_test_url_uses_default_sku(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", "https://x/{sku}/{matrix_id}/{test_id}")
    monkeypatch.setattr(settings, "zeus_sku_default", "nx1")
    assert build_test_url("1", "2") == "https://x/nx1/1/2"


def test_build_test_url_missing_sku_raises(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", "https://x/{sku}/{matrix_id}/{test_id}")
    monkeypatch.setattr(settings, "zeus_sku_default", "")
    with pytest.raises(ConfigError):
        build_test_url("1", "2")
