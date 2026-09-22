"""Local text/PDF extraction only; no network or embedded executable content."""

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_CHARS = 200_000
MAX_CHUNKS = 100


class ParseError(RuntimeError):
    pass


def parse_bytes(data, suffix):
    pages = []
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ParseError("document_invalid_pdf")
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ParseError("document_encrypted_pdf")
            if len(reader.pages) > 100:
                raise ParseError("document_page_limit")
            total = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_CHARS:
                    raise ParseError("document_text_limit")
                # Do not silently accept scanned/mixed pages as complete extraction.
                if not text.strip():
                    raise ParseError("document_pdf_ocr_required")
                pages.append((number, text))
        except ParseError:
            raise
        except Exception:  # noqa: BLE001 -- normalize untrusted parser errors, never expose PDF content
            raise ParseError("document_invalid_pdf") from None
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ParseError("document_requires_utf8") from None
        if "\x00" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise ParseError("document_invalid_text")
        pages = [(None, text)]
    if sum(len(t) for _, t in pages) > MAX_CHARS:
        raise ParseError("document_text_limit")
    chunks = []
    for page, text in pages:
        text = text.replace("\r\n", "\n").strip()
        start = 0
        while start < len(text):
            end = min(start + 2400, len(text))
            chunks.append({"page": page, "content": text[start:end]})
            if len(chunks) > MAX_CHUNKS:
                raise ParseError("document_chunk_limit")
            if end == len(text):
                break
            start = end - 200
    if not chunks:
        raise ParseError("document_empty_text")
    return chunks


def parse_isolated(data, filename):
    with tempfile.TemporaryDirectory(prefix="kcs-parse-") as folder:
        source = Path(folder) / ("source" + Path(filename).suffix.lower())
        source.write_bytes(data)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "kcs.document_parser", str(source)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ParseError("document_parse_timeout") from None
        if result.returncode or len(result.stdout) > 2_000_000:
            raise ParseError("document_parse_failed")
        value = json.loads(result.stdout)
        if "error" in value:
            raise ParseError(value["error"])
        return value["chunks"]


if __name__ == "__main__":
    from .parser_limits import limit_memory

    memory_limit_handle = limit_memory()
    path = Path(sys.argv[1])
    try:
        output = {"chunks": parse_bytes(path.read_bytes(), path.suffix)}
    except ParseError as error:
        output = {"error": str(error)}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=True).encode("ascii"))
