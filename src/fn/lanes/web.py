"""Web lane: one Parallel Search and one Extract call per search, each page stored and every person it names a hit."""

from collections.abc import Callable

from fn import extract, websearch
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
NO_QUERY = "no topic, role or institution chip"


def note(reason: str, kept: bool = False, stage: str = "query") -> Considered:
    return Considered(person_key="-", name="", stage=stage, kept=kept, reason=reason)


def has_query(chips: Chips) -> bool:
    """True when the chips give a web search something to ask for."""
    return bool(chips.topics or chips.roles or chips.institutions)


def objective(chips: Chips, tie: bool = True) -> str:
    """One sentence for what the search wants, built from the chips; tie=False leaves the Belgian tie out."""
    parts = ["People with a connection to Belgium" if tie else "People"]
    if chips.roles:
        parts.append("who are " + ", ".join(c.text for c in chips.roles))
    if chips.topics:
        parts.append(f"{'and' if chips.roles else 'who'} work on " + ", ".join(c.text for c in chips.topics))
    if chips.institutions:
        linked = ", ".join(c.text for c in chips.institutions)
        parts.append(f"{'and' if chips.roles or chips.topics else 'who'} have a link to {linked}")
    if chips.place:
        parts.append(f"in {chips.place.text}")
    return " ".join(parts)


def request(chips: Chips) -> dict:
    """The Search body for the chips: their objective and rule queries."""
    return websearch.search_body(objective(chips), websearch.rule_queries(chips))


def listed(claim: Claim) -> str:
    """A claim as a mention row lists it: relation or kind and value, then org id and date when set."""
    return " ".join([claim.relation or claim.kind, repr(claim.value), *filter(None, (claim.org_id, claim.claim_date))])


def people(ctx: StepContext, pages: list[tuple[int, Source]], considered: list[Considered], lane: LaneName,
           focus: Callable[[Source, str], bool] | None = None) -> list[LaneHit]:
    """One hit per person the pages name, in page order, then mention order, with every mention's claims stored.

    With focus, a person for whom focus(source, name) is false is not stored and gets a dropped mention row.

    A person named twice on a page is one hit with the claims of both mentions. Each kept mention, and each
    mention, relation or chunk dropped, is added to considered.
    """
    hits: dict[str, LaneHit] = {}
    read = extract.read_all(ctx, [source for _, source in pages])
    for (rank, source), (found, dropped) in zip(pages, read):
        considered += dropped
        page = f"page {rank}, {source.title}, {source.url}" if source.title else f"page {rank}, {source.url}"
        with ctx.store.tx():
            for located in found:
                ident = extract.identifier(source.url, located.name)
                if focus and not focus(source, located.name):
                    considered.append(Considered(person_key=ident.value, name=located.name, stage="mention", kept=False,
                                                 reason=f"{page}: {located.name} is not a lead"))
                    continue
                person = ctx.store.resolve_person([ident], located.name)
                claims = [ctx.store.upsert_claim(d, ctx.now()) for d in extract.drafts(person.id, source, located, ctx)]
                hit = hits.get(person.id) or LaneHit(person_id=person.id, name_key=person.name_key, lane=lane,
                                                     rank=len(hits) + 1, score=1 / rank, matched_on=page)
                ids = list(dict.fromkeys([*hit.claim_ids, *(c.id for c in claims)]))
                hits[person.id] = hit.model_copy(update={"claim_ids": ids})
                considered.append(Considered(person_key=ident.value, name=located.name, stage="mention", kept=True,
                                             reason=f"{page}: {'; '.join(listed(c) for c in claims)}"))
    return list(hits.values())


def collect(ctx: StepContext, objective: str, queries: list[str], lane: LaneName) -> LaneOut:
    """Find pages for the queries, store each as a vendor_page source and read the people it names for lane.

    A page's text is the first of Extract full content, Extract excerpts and Search excerpts with plain text left
    after its markdown is stripped; a page with none is skipped. Every person a page names is a hit. Without a
    Parallel key it returns a note. Raises RuntimeError without an HTTP client or LLM, HttpError for a failed call.
    """
    if ctx.http is None or ctx.llm is None:
        raise RuntimeError("the web lane needs an HTTP client and an LLM")
    query = "; ".join(queries[:websearch.MAX_QUERIES])
    try:
        found = websearch.find(ctx, objective, queries)
    except MissingKey as exc:
        ctx.log.warning("%s lane skipped: %s", lane, exc)
        return LaneOut(lane=lane, query=query, total_seen=0, considered=[note(f"{lane} lane skipped: {exc}")])
    if found.note:
        return LaneOut(lane=lane, query=query, total_seen=0, considered=[note(found.note)])
    considered = list(found.considered)
    stored: list[tuple[int, Source]] = []
    with ctx.store.tx():
        for page in found.pages:
            built = ((h, page_source(page.url, page.title, md, page.raw, ctx.now(), page.published))
                     for h, md in page.texts)
            how, source = next(((h, s) for h, s in built if s.text), ("", None))
            unread = f"; Extract could not read it ({page.unread})" if page.unread else ""
            if source is None:
                considered.append(Considered(person_key=page.url, name="", stage="page", kept=False,
                                             reason=f"rank {page.rank}: no text in Extract or Search; skipped{unread}"))
                continue
            ctx.store.upsert_source(source)
            stored.append((page.rank, source))
            reason = f"rank {page.rank}, {page.title or page.url}: {len(source.text)} characters from {how}{unread}"
            if how == "Extract full content" and len(page.raw["extract"]["full_content"]) >= websearch.MAX_CHARS:
                reason += f"; may be truncated at {websearch.MAX_CHARS:,} characters"
            considered.append(Considered(person_key=page.url, name="", stage="page", kept=True, reason=reason))
    hits = people(ctx, stored, considered, lane)
    ctx.log.info("%s lane: %d results, %d pages, %d stored, %d people", lane, len(found.pages) + len(found.considered),
                 len(found.pages), len(stored), len(hits))
    return LaneOut(lane=lane, query=query, total_seen=len(found.pages), hits=hits, considered=considered)


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search the web for the chips' roles, topics and institutions, without a topic, role or institution a note."""
    chips = inp.chips
    if not has_query(chips):
        return LaneOut(lane=name, query="", total_seen=0, considered=[note(NO_QUERY)])
    return collect(ctx, objective(chips), websearch.rule_queries(chips), name)
