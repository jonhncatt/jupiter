import pytest
from apps.backend.tools.dify_client import dify_text_and_citations


def test_dify_compat_extract():
    text, cites = dify_text_and_citations({"answer": "ok", "metadata": {"citations": [{"quote": "x"}]}})
    assert text == "ok"
    assert cites and cites[0]["quote"] == "x"
