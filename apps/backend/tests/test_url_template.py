import pytest
from apps.backend.tools.zeus_portal import build_test_url
from apps.backend.core.config import settings


def test_build_test_url_requires_template(monkeypatch):
    monkeypatch.setattr(settings, "zeus_test_url_template", "https://x/{matrix_id}/{test_id}")
    assert build_test_url("1", "2") == "https://x/1/2"
