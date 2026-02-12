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
