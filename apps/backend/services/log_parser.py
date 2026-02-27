import re
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class ParsedLog:
    errors: List[str]
    warnings: List[str]
    highlights: List[str]
    tokens: Dict[str, Any]
    domain_context: Dict[str, Any]


class LogParser:
    def parse(self, raw: str) -> ParsedLog:
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        file_map = _split_merged_files(raw)
        pcb_text = _find_file_text(file_map, "pcb_testlog_console_output.txt")
        nvmecore_text = _find_file_text(file_map, "nvmecore_log.txt")
        errors = [l for l in lines if "error" in l.lower() or "[ERROR]" in l]
        warnings = [l for l in lines if "warn" in l.lower() or "[WARN]" in l]

        # 提取疑似关键字
        tokens = {
            "mentions_csts_rdy": "csts" in raw.lower() and "rdy" in raw.lower(),
            "mentions_timeout": "timeout" in raw.lower(),
            "mentions_apst": bool(re.search(r"\bAPST\b", raw, re.I)),
            "has_pcb_console_output": bool(pcb_text),
            "has_nvmecore_log": bool(nvmecore_text),
        }

        domain_context = {
            "pcb_console": _parse_pcb_console(pcb_text),
            "nvmecore": _parse_nvmecore(nvmecore_text),
        }
        tokens["pcb_status"] = domain_context["pcb_console"].get("status")
        tokens["pcb_has_script_line"] = bool(domain_context["pcb_console"].get("script_line"))
        tokens["nvmecore_has_commands"] = bool(domain_context["nvmecore"].get("command_lines"))

        # 取最后 N 行做 timeline/highlight
        highlights = []
        pcb_status = domain_context["pcb_console"].get("status")
        if pcb_status:
            highlights.append(f"[PCB] status={pcb_status}")
        if domain_context["pcb_console"].get("test_name"):
            highlights.append(
                f"[PCB] test={domain_context['pcb_console'].get('test_name')} rev={domain_context['pcb_console'].get('revision')} line={domain_context['pcb_console'].get('script_line')}"
            )
        for l in domain_context["nvmecore"].get("tail_lines", [])[-10:]:
            if l:
                highlights.append(f"[NVMECORE] {l}")
        for l in errors[:10]:
            highlights.append(l)
        for l in warnings[:10]:
            highlights.append(l)

        return ParsedLog(
            errors=errors[:50],
            warnings=warnings[:50],
            highlights=highlights[:30],
            tokens=tokens,
            domain_context=domain_context,
        )


def _split_merged_files(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    current_name: str | None = None
    buffer: List[str] = []
    for line in raw.splitlines():
        m = re.match(r"=+\s*FILE:\s*(.*?)\s*=+$", line.strip())
        if m:
            if current_name is not None:
                result[current_name] = "\n".join(buffer).strip()
            current_name = m.group(1).strip()
            buffer = []
            continue
        if current_name is not None:
            buffer.append(line)
    if current_name is not None:
        result[current_name] = "\n".join(buffer).strip()
    return result


def _find_file_text(file_map: Dict[str, str], filename: str) -> str:
    filename = filename.lower()
    for path, text in file_map.items():
        if path.lower().endswith(filename):
            return text
    return ""


def _parse_pcb_console(text: str) -> Dict[str, Any]:
    if not text:
        return {"present": False}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    status = None
    status_line = ""
    for line in reversed(lines[-40:]):
        m = re.search(r"\b(pass|fail|skip)\b", line, re.I)
        if m:
            status = m.group(1).lower()
            status_line = line
            break

    test_name = ""
    revision = ""
    script_line = ""
    if status_line:
        rev_match = re.search(r"\bRev(?:ision)?\s*[:=]?\s*([A-Za-z0-9._-]+)", status_line, re.I)
        if rev_match:
            revision = rev_match.group(1)
        line_match = re.search(r"#\s*(\d+)", status_line)
        if line_match:
            script_line = line_match.group(1)
        prefix = re.split(r"\b(pass|fail|skip)\b", status_line, flags=re.I)[0].strip(" :-")
        test_name = prefix or test_name

    return {
        "present": True,
        "status": status,
        "status_line": status_line,
        "test_name": test_name,
        "revision": revision,
        "script_line": script_line,
        "tail_lines": lines[-20:],
    }


def _parse_nvmecore(text: str) -> Dict[str, Any]:
    if not text:
        return {"present": False}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tail_lines = lines[-60:]
    command_lines = [
        line
        for line in tail_lines
        if re.search(r"\b(cmd|command|opcode|admin|io|identify|get log|set features|completion|status)\b", line, re.I)
    ]
    return {
        "present": True,
        "tail_lines": tail_lines,
        "command_lines": command_lines[:20],
    }
