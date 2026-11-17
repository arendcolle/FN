"""Reads a PDF's title, text and dates; run as a module it takes the PDF on stdin and prints one JSON object."""
import io
import json
import sys

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

PDF_PAGES = 60


def clean(text: str) -> str:
    """text without NUL characters and without lone surrogates, which SQLite cannot store."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode()


def _day(read_date) -> str | None:
    """The ISO day of a metadata date, or None when it is missing or malformed."""
    try:
        value = read_date()
    except ValueError:
        return None
    return value.date().isoformat() if value else None


def text_of(body: bytes, max_chars: int) -> dict:
    """The title, text, modified day, created day and whether pages were left unread, for a PDF's first PDF_PAGES pages.

    Pages are read until the text passes max_chars. An encrypted file raises FileNotDecryptedError.
    """
    reader = PdfReader(io.BytesIO(body))
    if reader.is_encrypted:
        raise FileNotDecryptedError("the PDF is encrypted")
    pages, size, seen = [], 0, 0
    for page in reader.pages[:PDF_PAGES]:
        if size > max_chars:
            break
        seen += 1
        text = clean(page.extract_text()).strip()
        if text:
            pages.append(text)
            size += len(text)
    meta = reader.metadata
    title = (meta.title or "").strip() if meta else ""
    return {"title": title or None, "text": "\n".join(pages),
            "modified": _day(lambda: meta.modification_date) if meta else None,
            "created": _day(lambda: meta.creation_date) if meta else None,
            "more": seen < len(reader.pages)}


def main() -> None:
    """Read the PDF on stdin and print its text_of as JSON, or {"error": ...}; the exit status is 0 in both cases."""
    try:
        out = text_of(sys.stdin.buffer.read(), int(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 every failure goes to the parent as a reason
        out = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
