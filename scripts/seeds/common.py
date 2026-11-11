import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "data" / "seeds"
USER_AGENT = "FN-prototype/0.1 (personal research)"
RELATIONS = {"home", "host", "employer", "member_of", "student"}
REQUIRED = {
    "list": str, "row_key": str, "name": str, "name_on_page": str, "year": (int, type(None)),
    "role": (str, type(None)), "institutions": list, "field": (str, type(None)),
    "place": (str, type(None)), "jurisdiction": (list, type(None)), "profile_url": (str, type(None)),
    "source_url": str, "source_title": str, "source_date": (str, type(None)), "date_method": str,
    "page": (int, type(None)), "quote": str, "raw_path": str, "fetched_at": str,
}

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
_last_hit: dict[str, float] = {}


def fetch(url: str) -> httpx.Response:
    """GET a URL at most once a second per domain.

    Raises httpx.HTTPStatusError on any non-2xx answer, so a 403 or a moved page stops the run.
    """
    host = urlparse(url).netloc
    wait = _last_hit.get(host, 0) + 1.0 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    resp = _client.get(url)
    _last_hit[host] = time.monotonic()
    resp.raise_for_status()
    return resp


def norm(text: str) -> str:
    """Fold text the way the Claim extractor will: NFC, NBSP to space, straight quotes, single spaces."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def save_raw(list_name: str, filename: str, content: bytes, text: str) -> str:
    """Save the fetched bytes and their normalized text layer; return the text layer's repo path."""
    folder = SEEDS / "raw" / list_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(content)
    text_path = folder / (filename + ".txt")
    text_path.write_text(norm(text), encoding="utf-8")
    return str(text_path.relative_to(ROOT))


def row_key(list_name: str, name: str, year: int | None, extra: str = "") -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "|".join([list_name, re.sub(r"[^a-z]+", "-", folded).strip("-"), str(year or ""), extra])


def write_rows(list_name: str, rows: list[dict]) -> Path:
    """Validate every row, then replace data/seeds/<list>.jsonl in one rename.

    Raises ValueError on a missing field, a wrong type, an empty name, a bad institution
    relation, a quote that lacks the name, or a quote absent from its raw text layer.
    """
    if not rows:
        raise ValueError(f"{list_name}: no rows")
    keys, texts = set(), {}
    for i, row in enumerate(rows):
        for field, kind in REQUIRED.items():
            if field not in row or not isinstance(row[field], kind):
                raise ValueError(f"{list_name} row {i}: bad {field}: {row.get(field)!r}")
        if set(row) - set(REQUIRED):
            raise ValueError(f"{list_name} row {i}: unknown fields {set(row) - set(REQUIRED)}")
        if not row["name"].strip() or row["list"] != list_name:
            raise ValueError(f"{list_name} row {i}: empty name or wrong list")
        for inst in row["institutions"]:
            if set(inst) != {"name", "relation"} or inst["relation"] not in RELATIONS:
                raise ValueError(f"{list_name} row {i}: bad institution {inst!r}")
        if norm(row["name_on_page"]) not in norm(row["quote"]):
            raise ValueError(f"{list_name} row {i}: quote lacks name_on_page")
        text = texts.setdefault(row["raw_path"], (ROOT / row["raw_path"]).read_text(encoding="utf-8"))
        if norm(row["quote"]) not in text:
            raise ValueError(f"{list_name} row {i}: quote not in {row['raw_path']}")
        if row["row_key"] in keys:
            raise ValueError(f"{list_name} row {i}: duplicate row_key {row['row_key']}")
        keys.add(row["row_key"])
    out = SEEDS / f"{list_name}.jsonl"
    tmp = out.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, out)
    return out
