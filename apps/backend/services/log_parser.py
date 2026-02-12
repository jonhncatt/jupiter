import re
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class ParsedLog:
    errors: List[str]
    warnings: List[str]
    highlights: List[str]
    tokens: Dict[str, Any]


class LogParser:
    def parse(self, raw: str) -> ParsedLog:
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        errors = [l for l in lines if "error" in l.lower() or "[ERROR]" in l]
        warnings = [l for l in lines if "warn" in l.lower() or "[WARN]" in l]

        # 提取疑似关键字
        tokens = {
            "mentions_csts_rdy": "csts" in raw.lower() and "rdy" in raw.lower(),
            "mentions_timeout": "timeout" in raw.lower(),
            "mentions_apst": bool(re.search(r"\bAPST\b", raw, re.I)),
        }

        # 取最后 N 行做 timeline/highlight
        highlights = []
        for l in errors[:10]:
            highlights.append(l)
        for l in warnings[:10]:
            highlights.append(l)

        return ParsedLog(errors=errors[:50], warnings=warnings[:50], highlights=highlights[:30], tokens=tokens)
