import io
import zipfile
from typing import List, Tuple


PRIMARY_LOG_FILES = [
    "pcb_testlog_console_output.txt",
    "nvmecore_log.txt",
]


def list_zip_members(zip_bytes: bytes) -> List[str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        return z.namelist()


def extract_text_files(
    zip_bytes: bytes,
    *,
    include_keywords: List[str] | None = None,
    max_files: int = 30,
    max_total_chars: int = 400_000,
) -> List[Tuple[str, str]]:
    """
    Return list of (filename, content).
    - only small-ish text files
    - include_keywords: if provided, keep files whose path contains any keyword
    """
    include_keywords = include_keywords or ["log", "txt", "console", "result", "error"]
    out: List[Tuple[str, str]] = []
    total = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        names = z.namelist()

        # 简单排序：优先更像“主 log”的文件
        def score(n: str) -> int:
            nl = n.lower()
            s = 0
            for idx, target in enumerate(PRIMARY_LOG_FILES):
                if nl.endswith(target):
                    s += 100 - idx * 10
            if "main" in nl:
                s += 5
            if "console" in nl:
                s += 4
            if "error" in nl:
                s += 3
            if nl.endswith(".log") or nl.endswith(".txt"):
                s += 2
            return -s

        names.sort(key=score)

        for name in names:
            if len(out) >= max_files:
                break
            nl = name.lower()
            if not (nl.endswith(".log") or nl.endswith(".txt") or nl.endswith(".out")):
                continue
            if include_keywords and not any(k in nl for k in include_keywords):
                continue

            with z.open(name, "r") as f:
                raw = f.read()
            # 尝试 utf-8，不行就忽略错误
            try:
                text = raw.decode("utf-8")
            except Exception:
                text = raw.decode("utf-8", errors="ignore")

            if not text.strip():
                continue

            text = _trim_text_by_filename(name, text)

            total += len(text)
            if total > max_total_chars:
                break
            out.append((name, text))
    return out


def merge_texts(files: List[Tuple[str, str]]) -> str:
    chunks = []
    for fn, txt in files:
        chunks.append(f"\n===== FILE: {fn} =====\n")
        chunks.append(txt)
    return "\n".join(chunks)


def _trim_text_by_filename(name: str, text: str) -> str:
    nl = name.lower()
    if nl.endswith("nvmecore_log.txt"):
        lines = text.splitlines()
        tail = lines[-200:] if len(lines) > 200 else lines
        return "\n".join(tail)
    if nl.endswith("pcb_testlog_console_output.txt"):
        lines = text.splitlines()
        if len(lines) > 400:
            lines = lines[:220] + ["", "===== SNIP =====", ""] + lines[-180:]
        return "\n".join(lines)
    return text
