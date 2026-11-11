"""Web lane: one Parallel Search and one Extract call per search, each page stored and every person it names a hit."""
import json
import logging

from fn import extract
from fn.contracts import (
    Chips,
    Claim,
    Considered,
    LaneHit,
    LaneIn,
    LaneName,
    LaneOut,
    Source,
    page_source,
)
from fn.net import MissingKey
from fn.steps import StepContext

name: LaneName = "web"
log = logging.getLogger("fn.lanes.web")
SEARCH_URL = "https://api.parallel.ai/v1/search"
EXTRACT_URL = "https://api.parallel.ai/v1/extract"
MAX_QUERIES = 5
MAX_CHARS = 12_000
FETCH_TIMEOUT_S = 20
EXTRACT_TIMEOUT_S = 90
NO_QUERY = "no topic or institution chip"
# Dollars per count of each SKU in a response's `usage`, as live calls named them on 2026-11-03.
PRICES = {"sku_search": 0.001, "sku_extract_excerpts": 0.001}


def note(reason: str, kept: bool = False, stage: str = "query") -> Considered:
    return Considered(person_key="-", name="", stage=stage, kept=kept, reason=reason)


def objective(chips: Chips) -> str:
    """One sentence for what the search wants, built from the chips."""
    parts = ["People with a connection to Belgium"]
    if chips.topics:
        parts.append("who work on " + ", ".join(c.text for c in chips.topics))
    if chips.institutions:
        linked = ", ".join(c.text for c in chips.institutions)
        parts.append(f"{'and' if chips.topics else 'who'} have a link to {linked}")
    if chips.place:
        parts.append(f"in {chips.place.text}")
    return " ".join(parts)


def request(chips: Chips) -> dict:
    """The Search body: the objective, then one query per topic chip with the place text and one per institution chip.

    At most 5 queries, which is Parallel's limit. A chip set with neither topics nor institutions has no query.
    """
    place = f" {chips.place.text}" if chips.place else ""
    queries = [f"{c.text}{place}" for c in chips.topics] + [c.text for c in chips.institutions]
    return {"objective": objective(chips), "search_queries": queries[:MAX_QUERIES], "mode": "fast"}


def extract_body(urls: list[str], objective: str) -> dict:
    """The Extract body: full content up to 12,000 characters a page and a 20 s live-fetch timeout."""
    return {"urls": urls, "objective": objective,
            "advanced_settings": {"full_content": {"max_chars_per_result": MAX_CHARS},
                                  "fetch_policy": {"timeout_seconds": FETCH_TIMEOUT_S}}}


def usage_cost(body: bytes) -> float | None:
    """Dollars for the response's `usage` at PRICES.

    None when it lists no SKU, and None with a warning when one is not in PRICES.
    """
    usage = json.loads(body).get("usage") or []
    unknown = [u["name"] for u in usage if u["name"] not in PRICES]
    if unknown:
        log.warning("Parallel usage names SKUs without a price: %s", ", ".join(unknown))
        return None
    return sum(PRICES[u["name"]] * u["count"] for u in usage) if usage else None


def listed(claim: Claim) -> str:
    """A claim as a mention row lists it: relation or kind and value, then org id and date when set."""
    return " ".join([claim.relation or claim.kind, repr(claim.value), *filter(None, (claim.org_id, claim.claim_date))])


def people(ctx: StepContext, pages: list[tuple[int, Source]], considered: list[Considered]) -> list[LaneHit]:
    """One hit per person the pages name, in page order, then mention order, with every mention's claims stored.

    A person named twice on a page is one hit with the claims of both mentions. Each kept mention, and each
    mention, relation or chunk dropped, is added to considered.
    """
    hits: dict[str, LaneHit] = {}
    for rank, source in pages:
        found, dropped = extract.mentions(ctx, source)
        considered += dropped
        page = f"page {rank}, {source.title}, {source.url}" if source.title else f"page {rank}, {source.url}"
        with ctx.store.tx():
            for located in found:
                ident = extract.identifier(source.url, located.name)
                person = ctx.store.resolve_person([ident], located.name)
                claims = [ctx.store.upsert_claim(d) for d in extract.drafts(person.id, source, located, ctx)]
                hit = hits.get(person.id) or LaneHit(person_id=person.id, name_key=person.name_key, lane=name,
                                                     rank=len(hits) + 1, score=1 / rank, matched_on=page)
                ids = list(dict.fromkeys([*hit.claim_ids, *(c.id for c in claims)]))
                hits[person.id] = hit.model_copy(update={"claim_ids": ids})
                considered.append(Considered(person_key=ident.value, name=located.name, stage="mention", kept=True,
                                             reason=f"{page}: {'; '.join(listed(c) for c in claims)}"))
    return list(hits.values())


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search Parallel for the chips, store each result page as a vendor_page source and read the people it names.

    A page's text is the first of Extract full content, Extract excerpts and Search excerpts with plain text left
    after its markdown is stripped; a page with none is skipped. Every person a page names is a hit. Without a
    Parallel key it returns a note. Raises RuntimeError without an HTTP client or LLM, HttpError for a failed call.
    """
    chips = inp.chips
    if not chips.topics and not chips.institutions:
        return LaneOut(lane=name, query="", total_seen=0, considered=[note(NO_QUERY)])
    if ctx.http is None or ctx.llm is None:
        raise RuntimeError("the web lane needs an HTTP client and an LLM")
    body = request(chips)
    query = "; ".join(body["search_queries"])
    try:
        found = ctx.http.post(SEARCH_URL, body, cost=usage_cost).json()
    except MissingKey as exc:
        ctx.log.warning("web lane skipped: %s", exc)
        return LaneOut(lane=name, query=query, total_seen=0, considered=[note(f"web lane skipped: {exc}")])
    results = found.get("results") or []
    if not results:
        return LaneOut(lane=name, query=query, total_seen=0,
                       considered=[note("Parallel Search returned no results; Extract not called")])
    pages: dict[str, tuple[int, dict]] = {}
    considered: list[Considered] = []
    for rank, result in enumerate(results, 1):
        if result["url"] in pages:
            considered.append(Considered(person_key=result["url"], name="", stage="page", kept=False,
                                         reason=f"rank {rank}: same URL as rank {pages[result['url']][0]}"))
        else:
            pages[result["url"]] = (rank, result)
    answer = ctx.http.post(EXTRACT_URL, extract_body(list(pages), body["objective"]), timeout_s=EXTRACT_TIMEOUT_S,
                           cost=usage_cost).json()
    read = {r["url"]: r for r in answer.get("results") or []}
    failed = {e["url"]: e for e in answer.get("errors") or []}
    stored: list[tuple[int, Source]] = []
    with ctx.store.tx():
        for url, (rank, result) in pages.items():
            got = read.get(url, {})
            candidates = [("Extract full content", got.get("full_content") or ""),
                          ("Extract excerpts", "\n\n".join(got.get("excerpts") or [])),
                          ("Search excerpts", "\n\n".join(result.get("excerpts") or []))]
            title = got.get("title") or result.get("title")
            raw = {"search": result, "extract": got or failed.get(url)}
            published = got.get("publish_date") or result.get("publish_date")
            built = ((h, page_source(url, title, md, raw, ctx.now(), published)) for h, md in candidates)
            how, source = next(((h, s) for h, s in built if s.text), ("", None))
            unread = f"; Extract could not read it ({failed[url]['error_type']})" if url in failed else ""
            if source is None:
                considered.append(Considered(person_key=url, name="", stage="page", kept=False,
                                             reason=f"rank {rank}: no text in Extract or Search; skipped{unread}"))
                continue
            ctx.store.upsert_source(source)
            stored.append((rank, source))
            reason = f"rank {rank}, {title or url}: {len(source.text)} characters from {how}{unread}"
            if how == "Extract full content" and len(got["full_content"]) >= MAX_CHARS:
                reason += f"; may be truncated at {MAX_CHARS:,} characters"
            considered.append(Considered(person_key=url, name="", stage="page", kept=True, reason=reason))
    hits = people(ctx, stored, considered)
    ctx.log.info("web lane: %d results, %d pages, %d stored, %d people", len(results), len(pages), len(stored),
                 len(hits))
    return LaneOut(lane=name, query=query, total_seen=len(pages), hits=hits, considered=considered)
