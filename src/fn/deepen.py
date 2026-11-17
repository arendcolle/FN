"""The lookup step: a web search per chosen person for the pages that show what they do today, read by FN itself."""
from datetime import timedelta
from typing import NamedTuple
from urllib.parse import urlsplit

from fn import evidence, extract, pageread, rank, scout
from fn.contracts import (
    Candidate,
    Chips,
    Claim,
    Considered,
    DeepenIn,
    DeepenOut,
    Identifier,
    Located,
    Lookup,
    LookupAnswer,
    LookupOutcome,
    LookupPage,
    Org,
    PersonMention,
    Source,
    clean_name,
    name_key,
    page_source,
)
from fn.lanes.scout import same_person, titled
from fn.llm import FixtureMissing
from fn.steps import StepContext, as_of, fan_out

TASK = "lookup"
KIND = "web_person"
MAX_LOOKUPS = 20
CONTACT_TOP = 10
DAYS = 90
PAGES = 2
FACTS = 14
SECOND = ("works_at", "worked_at", "affiliated_with", "studied_at", "fellow_of")
CONTACT_PAGES = ("employer", "own")
UNLISTED = ("location", "email", "phone")


class Pick(NamedTuple):
    candidate: Candidate
    name: str
    missing: list[str]
    contact: bool


def records_of(candidate: Candidate) -> list[str]:
    return candidate.card_person_ids or candidate.hit_person_ids or candidate.person_ids[:1]


def people(ctx: StepContext) -> list[tuple[Candidate, list[str], list[Claim], dict[str, frozenset[str]]]]:
    """The open list: kept new-section people without an aside under headings 1 to 3, by rank, with their card's
    records, claims and identifier schemes."""
    kept = [c for c in ctx.store.list_candidates(ctx.search_id, kept_only=True)
            if c.section == "new" and c.cut_reason is None and c.aside is None and c.tier is not None
            and rank.heading(c.tier, c.fit.tie_grade if c.fit else "none") <= 3]
    kept.sort(key=lambda c: c.rank)
    records = list(dict.fromkeys(p for c in kept for p in records_of(c)))
    by_person: dict[str, list[Claim]] = {}
    for claim in ctx.store.claims_of(records):
        by_person.setdefault(claim.person_id, []).append(claim)
    schemes = evidence.card_of(ctx.store.identifiers_of(records), records)
    return [(c, records_of(c), [x for p in records_of(c) for x in by_person.get(p, [])],
             {p: schemes.get(p, frozenset()) for p in records_of(c)}) for c in kept]


def picks(ctx: StepContext, chips: Chips) -> list[Pick]:
    """The people to look up, by rank: the first MAX_LOOKUPS of the open list who miss a place, a job or a recent
    fact, and those of its first CONTACT_TOP without an email or phone claim, who get contact.

    Anyone with a lookup in the last DAYS days that did not fail is left out.
    """
    found = people(ctx)
    today = as_of(ctx).date()
    since = ctx.store.lookups_since(KIND, list(dict.fromkeys(p for _, rs, _, _ in found for p in rs)),
                                    ctx.now() - timedelta(days=DAYS))
    names = ctx.store.get_persons([c.person_id for c, _, _, _ in found])
    chosen, missed = [], 0
    for at, (c, records, claims, card) in enumerate(found):
        if since & set(records):
            continue
        missing = [what for what, lacks in (
            ("place", chips.place is not None and c.fit is not None and c.fit.place == "unknown"),
            ("job", evidence.job(claims, card, today) != "known"),
            ("recent", not evidence.recent_fact(claims, today))) if lacks]
        missing = missing if missed < MAX_LOOKUPS else []
        missed += bool(missing)
        contact = at < CONTACT_TOP and not any(x.kind in ("email", "phone") for x in claims)
        if missing or contact:
            chosen.append(Pick(c, names[c.person_id].display_name, missing, contact))
    return chosen


def block(name: str, claims: list[Claim]) -> str:
    """The name, then up to FACTS distinct lines "<relation or kind>: <value>", without places or contact details."""
    lines = dict.fromkeys(f"{(c.relation or c.kind).replace('_', ' ')}: {' '.join(c.value.split())}"
                          for c in claims if c.kind not in UNLISTED)
    return "\n".join([" ".join(name.split()), *list(lines)[:FACTS]])


def same_one(text: str, claims: list[Claim], facts: dict[str, Org], identifiers: list[Identifier]) -> str | None:
    """The held fact the text also states: a SECOND claim's value or organization name, or an ORCID or OpenAlex id."""
    for c in claims:
        if c.relation in SECOND:
            for org in dict.fromkeys(filter(None, (c.value, facts[c.org_id].name if c.org_id in facts else None))):
                if extract.names_org(org, text):
                    return f"{c.relation.replace('_', ' ')} {org}"
    return next((f"{i.scheme} {i.value}" for i in identifiers if i.scheme in ("orcid", "openalex") and i.value in text),
                None)


def named_as(person: str, found: str) -> bool:
    """Whether a page's name is the person: the researcher lane's rule, or the same first and last word around others,
    so a middle name on one side does not hide the person."""
    a, b = (name_key(clean_name(x)).split() for x in (person, found))
    return same_person(person, found) or (len(a) > 1 and len(b) > 1 and a[0] == b[0] and a[-1] == b[-1])


def chosen_pages(answer: LookupAnswer) -> tuple[list[LookupPage], list[str]]:
    """The answer's first PAGES distinct pages FN may fetch, and a note per page left out as not fetchable."""
    pages, notes, seen = [], [], set()
    for page in answer.pages:
        if not scout.fetchable(page.url):
            scheme = urlsplit(page.url).scheme
            notes.append(f"{page.url}: not fetchable" if scheme in ("http", "https") else f"a {scheme or 'bare'} address: not fetchable")
        elif scout.page_key(page.url) not in seen and len(pages) < PAGES:
            seen.add(scout.page_key(page.url))
            pages.append(page)
    return pages, notes


class Plan(NamedTuple):
    pick: Pick
    answer: LookupAnswer | Exception
    pages: list[LookupPage]
    notes: list[str]


class Page(NamedTuple):
    page: LookupPage
    read: pageread.Read
    source: Source | None
    found: tuple[list[tuple[Located, PersonMention]], list[Considered]] | None


def run(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
    """Look up the picked people, read the pages the lookups name, and attach a page's facts to a person when the
    page names them and states a fact FN holds; one lookup row per person, except for a missing recording.

    A note and no call for chips stored before version 2, without an HTTP client or model, or with nobody picked.
    """
    if inp.chips.version < 2:
        return DeepenOut(note="chips stored before this round, so no lookup")
    if ctx.http is None or ctx.llm is None:
        return DeepenOut(note="no HTTP client or model, so no lookup")
    chosen = picks(ctx, inp.chips)
    if not chosen:
        return DeepenOut(note="nobody to look up")
    blocks = [block(p.name, ctx.store.claims_of(records_of(p.candidate))) for p in chosen]
    answers = fan_out(lambda text: ctx.llm.structured(TASK, {"person": text}, LookupAnswer).value, blocks,
                      ctx.settings.llm_workers)
    if all(isinstance(a, FixtureMissing) for a in answers):
        return DeepenOut(note="no recorded lookup")
    plans = [Plan(p, a, *(([], []) if isinstance(a, Exception) else chosen_pages(a)))
             for p, a in zip(chosen, answers) if not isinstance(a, FixtureMissing)]
    unique: dict[str, str] = {}
    for plan in plans:
        for page in plan.pages:
            unique.setdefault(scout.page_key(page.url), page.url)
    reads = dict(zip(unique, pageread.read_all(ctx, list(unique.values())) if unique else []))
    sources: dict[tuple[int, str], Source] = {}
    for at, plan in enumerate(plans):
        for page in plan.pages:
            read = reads[scout.page_key(page.url)]
            if read.failed or not read.text:
                continue
            text = titled(read.title, pageread.windows(read.text, [plan.pick.name]))
            sources[at, page.url] = page_source(
                read.url, read.title, text, {"lookup": {"truncated": read.truncated}}, ctx.now(),
                read.published or ctx.now().date().isoformat(), kind="page", plain=True,
                date_method="page_date" if read.published else "read_date")
    found = dict(zip(sources, extract.read_person(ctx, [(s, plans[at].pick.name) for (at, _), s in sources.items()])))
    lookups, claim_ids = [], []
    for at, plan in enumerate(plans):
        lookup, added = store(ctx, plan, [Page(page, reads[scout.page_key(page.url)], sources.get((at, page.url)),
                                               found.get((at, page.url))) for page in plan.pages])
        lookups.append(lookup)
        claim_ids += added
    return DeepenOut(lookups=lookups, claim_ids=list(dict.fromkeys(claim_ids)))


def store(ctx: StepContext, plan: Plan, pages: list[Page]) -> tuple[Lookup, list[str]]:
    """Store what the confirmed pages give the person and the lookup row in one transaction; the row and the new
    claim ids. A failed call, or an error while storing, gives a failed row and no claim."""
    person_id = plan.pick.candidate.person_id
    try:
        if isinstance(plan.answer, Exception):
            raise plan.answer
        with ctx.store.tx():
            lookup, added = attach(ctx, plan, pages)
            ctx.store.save_lookup(lookup, ctx.now())
        return lookup, added
    except Exception as exc:  # noqa: BLE001 one person's failure must not lose the others' lookups
        if exc is plan.answer:
            detail = f"the lookup failed: {type(exc).__name__}: {exc}"
        else:
            ctx.log.warning("the lookup of %s could not be stored: %s: %s", person_id, type(exc).__name__, exc)
            detail = f"storing failed: {type(exc).__name__}"
        lookup = Lookup(person_id=person_id, kind=KIND, verdict="failed", detail=detail)
        with ctx.store.tx():
            ctx.store.save_lookup(lookup, ctx.now())
        return lookup, []


def attach(ctx: StepContext, plan: Plan, pages: list[Page]) -> tuple[Lookup, list[str]]:
    """The lookup row and the ids of the claims the confirmed pages added; the first outcome that applies wins:
    added, nothing new from a confirmed page, not sure, failed, nothing new."""
    pick = plan.pick
    records = records_of(pick.candidate)
    claims = ctx.store.claims_of(records)
    held = {c.id for c in claims}
    facts = ctx.store.get_orgs(list(dict.fromkeys(c.org_id for c in claims if c.org_id)))
    identifiers = [i for ids in ctx.store.identifiers_of(records).values() for i in ids]
    detail = list(plan.notes)
    confirmed = unsure = failed = False
    added: list[str] = []
    for page, read, source, found in pages:
        if source is None or found is None:
            failed |= read.retry
            detail.append(f"{page.url}: {read.failed or 'no text'}")
            continue
        mentions, considered = found
        named = [located for located, _ in mentions if named_as(pick.name, located.name)]
        fact = same_one(source.text, claims, facts, identifiers) if named else None
        if fact is None:
            if not named and any(c.stage == "chunk" for c in considered):
                failed = True
                detail.append(f"{page.url}: the page reading failed")
                continue
            unsure = True
            detail.append(f"{page.url}: {'states no held fact' if named else 'does not name the person'}")
            continue
        confirmed = True
        new = []
        drafts = []
        for located in named:
            found = extract.drafts(pick.candidate.person_id, source, located, ctx)
            drafts += found if located.role else found[1:]
        if page.kind in CONTACT_PAGES:
            drafts += extract.contacts(pick.candidate.person_id, source, pick.name)
        for draft in drafts:
            claim = ctx.store.upsert_claim(draft, ctx.now())
            if claim.id not in held and claim.id not in new:
                new.append(claim.id)
        added += new
        detail.append(f"{page.url}: {page.kind} page, {fact}, {len(new)} new claims")
    if not plan.pages and not plan.notes:
        detail.append("no page found")
    outcome: LookupOutcome = ("added" if added else "nothing_new" if confirmed else "not_sure" if unsure
                              else "failed" if failed else "nothing_new")
    lookup = Lookup(person_id=pick.candidate.person_id, kind=KIND, verdict=outcome, detail="; ".join(detail))
    return lookup, added
