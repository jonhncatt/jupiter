import io
import zipfile
from apps.backend.services.zip_utils import extract_text_files, merge_texts


def test_extract_and_merge():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.log", "hello\n[ERROR] boom\n")
        z.writestr("img.png", b"\x89PNG")
    data = buf.getvalue()

    files = extract_text_files(data)
    assert any("main.log" in f[0] for f in files)
    merged = merge_texts(files)
    assert "FILE: main.log" in merged


def test_prioritize_pcb_and_trim_nvmecore():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zzz.log", "hello\n")
        z.writestr("PCB_TESTLOG_CONSOLE_OUTPUT.txt", "line1\nPASS test RevA #123\n")
        z.writestr("nvmecore_log.txt", "\n".join(f"cmd line {i}" for i in range(300)))
    data = buf.getvalue()

    files = extract_text_files(data)
    assert files[0][0].endswith("PCB_TESTLOG_CONSOLE_OUTPUT.txt")
    nvmecore = next(text for name, text in files if name.endswith("nvmecore_log.txt"))
    assert "cmd line 299" in nvmecore
    assert "cmd line 0" not in nvmecore
