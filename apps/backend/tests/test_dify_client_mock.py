import pytest
from apps.backend.tools.dify_client import _normalize_base, dify_text_and_citations


def test_dify_compat_extract():
    text, cites = dify_text_and_citations({"answer": "ok", "metadata": {"citations": [{"quote": "x"}]}})
    assert text == "ok"
    assert cites and cites[0]["quote"] == "x"


def test_normalize_base_tolerates_bad_forms():
    assert _normalize_base("http:10.22.57.219:28882") == "http://10.22.57.219:28882/v1"
    assert _normalize_base("10.22.57.219:28882") == "http://10.22.57.219:28882/v1"
    assert _normalize_base("http://10.22.57.219:28882/v1/caht-messages") == "http://10.22.57.219:28882/v1"
