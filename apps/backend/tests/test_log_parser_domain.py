from apps.backend.services.log_parser import LogParser


def test_log_parser_extracts_pcb_and_nvmecore_context():
    raw = """
===== FILE: PCB_TESTLOG_CONSOLE_OUTPUT.txt =====
setup
MyNvmeTest FAIL RevA #456

===== FILE: nvmecore_log.txt =====
send cmd: identify controller
completion status: 0x1
"""
    parsed = LogParser().parse(raw)
    assert parsed.domain_context["pcb_console"]["status"] == "fail"
    assert parsed.domain_context["pcb_console"]["revision"] == "A"
    assert parsed.domain_context["pcb_console"]["script_line"] == "456"
    assert parsed.tokens["nvmecore_has_commands"] is True
    assert any("NVMECORE" in item for item in parsed.highlights)
