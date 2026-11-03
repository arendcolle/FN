# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "climate"
SITE = "https://www.climatecentre.be"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BANNER = "Catalogue of Climate Scientific Experts"
OWN_INSTITUTION = "belgian climate centre"
LABELS = ("Discipline", "Expertise(s)", "Keywords")
TITLE_PREFIX = re.compile(r"^(?:(?:Prof|Dr|Ir|Mr|Mrs|Ms|Em)\.?\s+)+", re.IGNORECASE)


class Page(HTMLParser):
    """Collects the text of every h1 and h2 inside <main>, plus the <title>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.tag = None
        self.buf: list[str] = []
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        elif tag == "title":
            self.in_title = True
        elif self.in_main and tag in ("h1", "h2") and self.tag is None:
            self.tag, self.buf = tag, []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "main":
            self.in_main = False
        elif tag == self.tag:
            text = common.norm("".join(self.buf).replace("\u200b", ""))
            (self.h1 if tag == "h1" else self.h2).append(text)
            self.tag = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.tag:
            self.buf.append(data)


def die(msg: str):
    """Print the structure problem and exit non-zero before anything is written."""
    sys.exit(f"{LIST}: {msg}")


def expert_sitemap() -> list[tuple[str, str]]:
    """Find the expert sitemap from robots.txt and the sitemap index; return (url, lastmod) pairs."""
    robots = common.fetch(f"{SITE}/robots.txt").text
    index_url = next((l.split(":", 1)[1].strip() for l in robots.splitlines() if re.match(r"(?i)sitemap:.*/sitemap\.xml$", l.strip())), None)
    if not index_url:
        die("no sitemap.xml in robots.txt")
    index = ET.fromstring(common.fetch(index_url).content)
    experts = [e.text.strip() for e in index.findall("s:sitemap/s:loc", NS) if "catalogue-experts" in e.text]
    if len(experts) != 1:
        die(f"expected one expert sitemap in the index, got {experts}")
    urlset = ET.fromstring(common.fetch(experts[0]).content)
    pairs = []
    for u in urlset.findall("s:url", NS):
        loc, last = u.findtext("s:loc", namespaces=NS), u.findtext("s:lastmod", namespaces=NS)
        if not loc or not loc.startswith(f"{SITE}/catalogue-experts/") or not last or not re.match(r"\d{4}-\d\d-\d\d", last):
            die(f"unexpected sitemap entry {loc!r} {last!r}")
        pairs.append((loc.strip(), last.strip()[:10]))
    if not pairs or len({p[0] for p in pairs}) != len(pairs):
        die("empty or duplicated expert sitemap")
    return pairs


def raw_name(url: str) -> str:
    """Return a file name for the saved page from the unescaped slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", unquote(urlparse(url).path.rsplit("/", 1)[1]).lower()).strip("-")
    return f"{slug or 'page'}.html"


def parse(url: str, html_text: str) -> dict:
    """Parse one expert page into its fields; exit non-zero when the expected headings are off."""
    p = Page()
    p.feed(html_text)
    h1, h2 = p.h1, p.h2
    if len(h1) != 5 or h1[0] != BANNER or h1[2] != "URL" or not h1[1]:
        die(f"{url}: unexpected h1 structure {h1}")
    if not all(l in h2 for l in LABELS):
        die(f"{url}: missing labels in h2 {h2}")
    values = {l: (h2[h2.index(l) + 1] if h2.index(l) + 1 < len(h2) else "") for l in LABELS}
    if values["Discipline"] in LABELS or values["Expertise(s)"] in LABELS or values["Keywords"] in LABELS:
        die(f"{url}: label followed by label in {h2}")
    title = common.norm(p.title)
    if not title:
        die(f"{url}: no title")
    return {"h1": h1, "h2": h2, "values": values, "title": title}


def build_row(url: str, lastmod: str, parsed: dict, raw_path: str, text: str) -> dict:
    """Turn a parsed page into one seed row."""
    name_on_page = parsed["h1"][1]
    name = TITLE_PREFIX.sub("", name_on_page).strip() or name_on_page
    inst_line, role = parsed["h1"][3], parsed["h1"][4]
    institutions = []
    for part in (inst_line or "").split(","):
        part = part.strip()
        if part and part.lower() != OWN_INSTITUTION and part not in [i["name"] for i in institutions]:
            institutions.append({"name": part, "relation": "employer"})
    v = parsed["values"]
    field = "; ".join(x for x in (v["Discipline"], v["Expertise(s)"], v["Keywords"]) if x) or None
    return {
        "list": LIST, "row_key": common.row_key(LIST, name, None), "name": name, "name_on_page": name_on_page,
        "year": None, "role": role or None, "institutions": institutions, "field": field, "place": None,
        "jurisdiction": None, "profile_url": url, "source_url": url, "source_title": parsed["title"],
        "source_date": lastmod, "date_method": "sitemap_lastmod", "page": None, "quote": text,
        "raw_path": raw_path, "fetched_at": date.today().isoformat(),
    }


def main():
    """Fetch every expert page, save raw and text layers, and write the JSONL only if all pages parse."""
    pairs = expert_sitemap()
    folder = common.SEEDS / "raw" / LIST
    rows = []
    for i, (url, lastmod) in enumerate(pairs, 1):
        cached = folder / raw_name(url)
        content = cached.read_bytes() if cached.exists() else common.fetch(url).content
        parsed = parse(url, content.decode("utf-8"))
        text = common.norm(" ".join(parsed["h1"][1:] + parsed["h2"]))
        raw_path = common.save_raw(LIST, raw_name(url), content, text)
        rows.append(build_row(url, lastmod, parsed, raw_path, text))
        if i % 25 == 0:
            print(f"{i}/{len(pairs)}", file=sys.stderr, flush=True)
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
