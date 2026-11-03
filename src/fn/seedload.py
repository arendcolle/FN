"""data/seeds/*.jsonl to persons, sources and claims; fn-seed."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from fn import orgs
from fn.config import ROOT
from fn.contracts import (
    ClaimDraft,
    DateMethod,
    DatePrecision,
    Identifier,
    Relation,
    Source,
    normalize,
)
from fn.store import Store

SEEDS = ROOT / "data" / "seeds"
# Each list's organization by its name in data/org_aliases.csv.
LISTS: dict[str, tuple[Relation, str]] = {
    "baef": ("fellow_of", "Belgian American Educational Foundation"),
    "francqui": ("fellow_of", "Francqui Foundation"),
    "kvab": ("member_of", "KVAB"),
    "climate": ("member_of", "Belgian Climate Centre"),
    "consuls": ("consul_for", "Belgium"),
}
RELATIONS: dict[str, Relation] = {
    "home": "affiliated_with", "host": "hosted_by", "employer": "works_at", "member_of": "member_of",
}
DATE_METHODS: dict[str, DateMethod | None] = {
    "none": None,
    "document heading": "document_heading",
    "document note (last modified September 2025)": "document_heading",
    "sitemap_lastmod": "sitemap",
    "page text": "page_date",
}
PRECISION: dict[int, DatePrecision] = {4: "year", 7: "month", 10: "day"}


def source_of(row: dict) -> Source:
    """The seed page a row quotes, with the normalized text of its raw text layer."""
    text = normalize((ROOT / row["raw_path"]).read_text(encoding="utf-8"))
    return Source(
        id=hashlib.sha1(f"seed_page\0{row['source_url']}".encode()).hexdigest(), kind="seed_page",
        url=row["source_url"], title=row["source_title"], text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(), source_date=row["source_date"],
        date_method=DATE_METHODS[row["date_method"]], fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )


def drafts(row: dict, person_id: str, source: Source) -> list[ClaimDraft]:
    """The list claim, one affiliation claim per institution and a topic claim, all quoting the row.

    A row's year dates its claims as a record field; without one they take the source's date.
    Raises KeyError for an unknown list, relation or date method, and ValueError when the quote is not in the source.
    """
    quote = normalize(row["quote"])
    start = source.text.find(quote)
    if start < 0:
        raise ValueError(f"{row['row_key']}: quote not in {row['raw_path']}")
    base = {"person_id": person_id, "quote": quote, "quote_start": start, "quote_end": start + len(quote),
            "source": source}
    if row["year"] is not None:
        base |= {"claim_date": str(row["year"]), "date_precision": "year", "date_method": "record_field"}
    else:
        base |= {"claim_date": source.source_date, "date_precision": PRECISION[len(source.source_date)],
                 "date_method": source.date_method}
    relation, list_org = LISTS[row["list"]]
    found = [ClaimDraft(kind="role", relation=relation, org_id=orgs.org_id(list_org),
                        value=row["role"] or row["source_title"], **base)]
    for inst in row["institutions"]:
        found.append(ClaimDraft(kind="affiliation", relation=RELATIONS[inst["relation"]],
                                org_id=orgs.org_id(inst["name"]), value=inst["name"], **base))
    if row["field"]:
        found.append(ClaimDraft(kind="topic", value=row["field"], **base))
    return found


def load(store: Store, seeds: Path = SEEDS) -> int:
    """Load every seed row in one transaction and return the row count; a second load writes nothing."""
    sources: dict[str, Source] = {}
    count = 0
    with store.tx():
        for path in sorted(seeds.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["raw_path"] not in sources:
                    sources[row["raw_path"]] = source_of(row)
                source = sources[row["raw_path"]]
                person = store.resolve_person([Identifier(scheme="seed", value=row["row_key"])], row["name"])
                for draft in drafts(row, person.id, source):
                    store.upsert_claim(draft)
                count += 1
    return count


def main() -> int:
    from fn import config

    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    before = store.conn.total_changes
    count = load(store)
    print(f"{count} seed rows loaded into {settings.db_path}; {store.conn.total_changes - before} rows changed")
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
