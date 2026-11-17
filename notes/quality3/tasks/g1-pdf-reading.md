# Task G1: read the text of a PDF

## Goal

`pageread.read` refuses every PDF with "a PDF, not a web page" (`src/fn/pageread.py:259`). On the owner's database 6 of the 59 people the lookup step looked up met a PDF, for 2 the only page. The HTTP cache holds 7 PDF bodies (the seventh from another read). Most are CVs, with the current job, place, email and phone. pypdf read all seven bodies in 0.01 to 0.57 s with 99 to 100% of the words, each with a modification date. This task reads a PDF's text, title and date in a child process with a time limit.

## What to build

### `pyproject.toml`, `uv.lock`

`uv add pypdf` in the worktree (7.1.0 on 2026-11-17). No extras, no other dependency.

### `src/fn/pdftext.py` (new)

- `PDF_PAGES = 60`.
- `text_of(body: bytes, max_chars: int) -> dict`: `PdfReader(io.BytesIO(body))` (default, not strict). When `reader.is_encrypted`, raise `pypdf.errors.FileNotDecryptedError("the PDF is encrypted")` (pypdf opens a file with an empty user password by itself). Then for the first `PDF_PAGES` pages, stopping before a page once the text passes `max_chars`: `page.extract_text()`, NULs removed, lone surrogates replaced (`.encode("utf-8", "replace").decode()`), stripped, empty pages left out, joined by "\n". Returns `{"title", "text", "modified", "created", "more"}`: `title` is `metadata.title` stripped, or None when empty or without metadata; `modified` and `created` are the days (`date().isoformat()`) of `metadata.modification_date` and `metadata.creation_date`, None when missing, and None on `ValueError` (pypdf 7.1.0 raises it for a malformed date string); `more` is true when pages were left unread.
- `main()`: reads stdin as bytes, `max_chars` from `sys.argv[1]`, writes `json.dumps(text_of(...))` to stdout; any `Exception` gives `{"error": f"{type(exc).__name__}: {exc}"}`. Exit 0 in both cases. `if __name__ == "__main__": main()`.
- No limit of `pageread` and no import of any `fn` module.

### `src/fn/pageread.py`

- `PDF_SECONDS = 20`.
- `pdf_read(url: str, body: bytes) -> Read`: `subprocess.run([sys.executable, "-m", "fn.pdftext", str(MAX_CHARS)], input=body, capture_output=True, timeout=PDF_SECONDS, check=False)`. `subprocess.run` kills the child when the limit passes. Reasons, word for word, none with `retry`:
  - `TimeoutExpired`: `a PDF that took over {PDF_SECONDS}s to read`.
  - A non-zero exit, stdout that is not a JSON object, or an `error` key: `a PDF that could not be read: {error}`, where error is the `error` value, else the last non-empty stderr line, else `the reader ended with status {returncode}`, made `" ".join(error.split())[:120]`.
  - `len(text) < MIN_CHARS`: `a PDF with {len(text)} characters of text, under {MIN_CHARS}` (title kept, as for HTML).
  - Else `Read(url, title, text[:MAX_CHARS], None, len(text) > MAX_CHARS or more, published)` with `published = next((d for d in (modified, created) if d and _is_day(d)), None)` (`_is_day`, line 228).
- `read`, line 259: `if body.startswith(b"%PDF-"): return pdf_read(url, body)`. The old reason goes.

### `tests/helpers.py`

Checked with pypdf 7.1.0: lines, title and both dates read back.

```python
def pdf_bytes(pages: list[list[str]], title: str | None = None, modified: str | None = None,
              created: str | None = None) -> bytes:
    """A valid PDF with one page per entry, each line drawn in Helvetica; title and dates go into the Info dictionary.

    Dates are PDF date strings such as "D:20240305120000Z". Lines are latin-1 without parentheses or backslashes.
    """
    n = len(pages)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(n)), n),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, lines in enumerate(pages):
        draw = b"BT /F1 11 Tf 14 TL 72 760 Td " + b" ".join(b"(%s) Tj T*" % line.encode("latin-1") for line in lines) + b" ET"
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                       b"/Contents %d 0 R >>" % (5 + 2 * i))
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(draw), draw))
    info = b"".join(b"/%s (%s) " % (key, value.encode("latin-1"))
                    for key, value in ((b"Title", title), (b"ModDate", modified), (b"CreationDate", created)) if value)
    objects.append(b"<< %s>>" % info)
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % at for at in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, len(objects), xref)
    return bytes(out)
```

### Callers, unchanged

- Lookup step (`deepen.py:193-205`): `windows(text, [name], limit=PAGE_CHARS)` (5,500 characters around the name, or the first 5,500), `titled` puts the title first, a source of kind `page` with `date_method` `page_date` when dated, else `read_date`; then `extract_person`, the held-fact check and contacts from employer or own pages only.
- Scout lane (`lanes/scout.py:84-95`): the same with 12,000 characters around the leads' names, then `extract_leads`.
- Nothing is wrong. Accepted: a word split across PDF lines can hide a held fact (the lookup says "not sure"); a title such as "Microsoft Word - CV" stands first; people whose lookup met a PDF keep that row for 90 days, except through "Look up more".

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Fetch, PDF-or-HTML switch, time limit, character limit and cut, failure reasons, which date counts | `pageread.py` |
| PDF bytes to title, page text, dates, unread pages; the page cap; refusing an encrypted file | `pdftext.py` |
| What a page's text becomes | `deepen.py`, `lanes/scout.py`, `extract.py` (unchanged) |
| PDF bytes for tests | `tests/helpers.pdf_bytes` |

## Inputs a real run will meet

The brief's list, plus: a malformed date string (pypdf raises), a creation date beside an impossible modification date, a child that crashes with a long multi-line error. Each has a test below. A repeated address is deduplicated by the callers (`scout.page_key`), as today.

## Tests (each must fail without the change)

In `tests/test_pageread.py`:

- `test_pdfs_are_read_by_their_first_bytes_side_by_side_and_a_web_page_at_a_pdf_address_stays_html`: an 8-page PDF at `https://a.example/cv` (title "  CV of Ada Example ", modified 2024-03-05, created 2021-01-01), another PDF at `https://b.example/cv` and an HTML page at `https://c.example/page.pdf` in one `read_all`: each text its own, pages in order, title stripped, `published` "2024-03-05".
- `test_a_pdf_date_falls_back_to_creation_and_an_impossible_or_missing_date_gives_none`: modified 1970 with created 2021-06-15 gives "2021-06-15"; modified 2999, "D:garbage" or none give None; no title gives None.
- `test_a_scan_fails_with_its_character_count`: three empty pages give `a PDF with 0 characters of text, under 300`.
- `test_a_300_page_pdf_reads_60_pages_and_is_truncated`: "page 59" is in the text, "page 60" is not.
- `test_a_2_mb_pdf_is_cut_at_max_chars`: 900 pages of 45 lines; text length `MAX_CHARS`, truncated.
- `test_a_nul_character_is_removed`.
- `test_an_encrypted_pdf_fails`: built with `PdfWriter(clone_from=...)` and `encrypt("", "owner", algorithm="RC4-128")`; reason `a PDF that could not be read: FileNotDecryptedError: the PDF is encrypted`.
- `test_a_pdf_read_over_the_time_limit_fails_without_retry`: `PDF_SECONDS` patched to 0.01; reason `a PDF that took over 0.01s to read`, `retry` false.
- `test_a_crashed_reader_gives_its_last_error_line_cut_to_120_characters`: `subprocess.run` patched to exit 1 with a traceback ending `MemoryError: ` and 300 x's.

## Existing tests that change, approved by the lead

`tests/test_pageread.py`, `test_every_failure_gives_its_reason_word_for_word`: the `%PDF-1.7 binary` body was `a PDF, not a web page`; it becomes `a PDF that could not be read: PdfStreamError: Stream has ended unexpectedly` (pypdf 7.1.0). No other existing test may change; stop and report a failure.

## Recorded answers and replays (S6)

No prompt changes. A cached PDF now gives text whose extract call has no recording. With `FN_LLM=replay` the scout lane's `extract_leads` chunk fails with `FixtureMissing` (logged as a warning) and the lookup's `extract_person` chunk fails silently ("the page reading failed"); the search ends done with the same people as before. `fn-score run --mode replay` marks a search whose scout lane read such a PDF as degraded and exits 2 without `--allow-degraded`. `rescore` and `rerank` read no page and do not change.

## Hand check

1. `uv run python -m unittest`: all green.
2. `mkvar.sh g1`, then with `FN_VAR=<copy> FN_HTTP=replay`, a script run with `uv run python -` that takes the URLs from `SELECT detail FROM lookups WHERE kind = 'web_person' AND detail LIKE '%a PDF, not a web page%'` (split on "; ", keep entries ending ": a PDF, not a web page", cut that ending), builds a `StepContext` as `rerank_main` does (`search.py:303`), calls `pageread.read_all` inside `run_step` as `run_in_step` in `tests/test_pageread.py` does, and prints per URL only `n, len(text or ""), published, failed` with the URL replaced by `<url>`. Expected: 6 reads, each over 300 characters, each with a date, no failure. No URL in any file or commit.

## Lead rulings before the build

- **Text SQLite can store.** A broken font map can make pypdf return a lone surrogate, which SQLite cannot encode, so the source would fail to store. `pdftext` gets `clean(text: str) -> str`: NULs removed, then `text.encode("utf-8", "replace").decode()`. `text_of` calls it on each page's text. One more test in `tests/test_pageread.py`: `pdftext.clean("a\x00b\ud800c")` gives `"ab?c"`.
- **pypdf's own words are not pinned.** In `test_every_failure_gives_its_reason_word_for_word` the PDF entry is compared by its fixed start, `a PDF that could not be read: `, and by having a non-empty rest; the other entries stay word for word. The rest is pypdf's message and changes with its version.

## Not doing

OCR. Encrypted PDFs. Tables and layout. The web lane's vendor reading. PDFs over the 5 MB fetch limit. Word files. A memory limit for the child. Cleaning PDF titles. Any prompt change.
