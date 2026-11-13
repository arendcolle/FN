"""Scout lane: a web researcher names people and pages, FN reads the pages itself and keeps only the leads on them."""
from fn import extract, pageread, scout
from fn.contracts import (
    Considered,
    LaneHit,
    LaneIn,
    LaneName,
    LaneOut,
    ScoutLead,
    Source,
    clean_name,
    name_key,
    page_source,
)
from fn.lanes import web
from fn.steps import StepContext

name: LaneName = "scout"
MAX_PAGES = 40
PAGES_PER_LEAD = 2


def same_person(lead: str, found: str) -> bool:
    """Whether a page's name is the lead: the same words, or the same last word with an initial for the first word."""
    a, b = (name_key(clean_name(x)).split() for x in (lead, found))
    if not a or not b:
        return False
    return a == b or (a[-1] == b[-1] and any(len(x[0]) == 1 and y[0].startswith(x[0]) for x, y in ((a, b), (b, a))))


def note(ctx: StepContext, inp: LaneIn) -> str | None:
    """Why the lane makes no call, or None when it runs."""
    if not ctx.settings.scout:
        return "web research is off"
    if inp.chips.version == 1:
        return "chips stored before this round, so no web research"
    return None if inp.question else "no question text"


def to_read(leads: list[ScoutLead]) -> tuple[dict[str, str], list[Considered]]:
    """The pages to read by address key, first pages before second pages, and a row for each left out by the limit."""
    wanted: dict[str, str] = {}
    over: dict[str, str] = {}
    for at in range(PAGES_PER_LEAD):
        for lead in leads:
            if at < len(lead.pages):
                key = scout.page_key(lead.pages[at])
                if key in wanted or key in over:
                    continue
                (wanted if len(wanted) < MAX_PAGES else over)[key] = lead.pages[at]
    rows = [Considered(person_key=url, name="", stage="page", kept=False,
                       reason=f"{url}: over the limit of {MAX_PAGES} pages") for url in over.values()]
    for lead in leads:
        if not any(scout.page_key(p) in wanted for p in lead.pages[:PAGES_PER_LEAD]):
            rows.append(Considered(person_key=name_key(lead.name), name=lead.name, stage="mention", kept=False,
                                   reason=f"{lead.name}: over the limit of {MAX_PAGES} pages"))
    return wanted, rows


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Ask the researcher, read the pages it names and keep the leads they name, or return a note and make no call.

    Notes: the lane is off, chips stored before version 2, no question text. Raises RuntimeError without an HTTP
    client or LLM, and what scout.find raises when every angle failed.
    """
    if reason := note(ctx, inp):
        return LaneOut(lane=name, query="", total_seen=0, considered=[web.note(reason)])
    if ctx.http is None or ctx.llm is None:
        raise RuntimeError("the scout lane needs an HTTP client and an LLM")
    leads, considered = scout.find(ctx, inp.question, inp.chips)
    query = "; ".join(scout.angles(inp.chips))
    wanted, rows = to_read(leads)
    considered += rows
    givers = {key: [lead for lead in leads if key in {scout.page_key(p) for p in lead.pages[:PAGES_PER_LEAD]}]
              for key in wanted}
    reads = pageread.read_all(ctx, list(wanted.values())) if wanted else []
    stored: list[tuple[int, Source]] = []
    unread: set[str] = set()
    with ctx.store.tx():
        for read in reads:
            names = [lead.name for lead in givers[scout.page_key(read.url)]]
            text = None if read.failed or not read.text else pageread.windows(read.text, names)
            source = text and page_source(read.url, read.title, text, {"scout": {"leads": names, "truncated": read.truncated}},
                                          ctx.now(), None, kind="page", plain=True)
            if not source or not source.text:
                reason = f"FN could not read it ({read.failed})" if read.failed else "no text"
                considered.append(Considered(person_key=read.url, name="", stage="page", kept=False,
                                             reason=f"{read.url}: {reason}"))
                unread.add(scout.page_key(read.url))
                continue
            ctx.store.upsert_source(source)
            stored.append((len(stored) + 1, source))
            considered.append(Considered(person_key=read.url, name="", stage="page", kept=True,
                                         reason=f"{read.title or read.url}: {len(source.text)} characters read by FN"))
    matched: list[tuple[Source, str, ScoutLead]] = []

    def focus(source: Source, found: str) -> bool:
        leads_here = [lead for lead in givers[scout.page_key(source.url)] if same_person(lead.name, found)]
        matched.extend((source, found, lead) for lead in leads_here)
        return bool(leads_here)

    hits = web.people(ctx, stored, considered, name, focus=focus)
    hits = add_places(ctx, hits, matched, stored, considered)
    named = {lead.name for _, _, lead in matched}
    for lead in leads:
        keys = [scout.page_key(p) for p in lead.pages[:PAGES_PER_LEAD] if scout.page_key(p) in wanted]
        if lead.name in named or not keys:
            continue
        said = (f"{lead.name}: none of its pages could be read" if all(k in unread for k in keys)
                else f"{lead.name}: named on none of its read pages")
        considered.append(Considered(person_key=name_key(lead.name), name=lead.name, stage="mention", kept=False,
                                     reason=said))
    ctx.log.info("scout lane: %d leads, %d pages read, %d people", len(leads), len(stored), len(hits))
    return LaneOut(lane=name, query=query, total_seen=len(leads), hits=hits, considered=considered)


def add_places(ctx: StepContext, hits: list[LaneHit], matched: list[tuple[Source, str, ScoutLead]],
               stored: list[tuple[int, Source]], considered: list[Considered]) -> list[LaneHit]:
    """Give each hit whose lead has a place and no lives_in claim the place the lead's first fitting page states."""
    ids = ctx.store.person_ids_by_identifier("mention", [extract.identifier(s.url, f).value for s, f, _ in matched])
    by_person: dict[str, dict[str, ScoutLead]] = {}
    for source, found, lead in matched:
        if person := ids.get(extract.identifier(source.url, found).value):
            by_person.setdefault(person, {})[lead.name] = lead
    pages = {scout.page_key(s.url): s for _, s in stored}
    out = []
    with ctx.store.tx():
        for hit in hits:
            claim_ids = list(hit.claim_ids)
            for lead in by_person.get(hit.person_id, {}).values():
                if not lead.place or any(c and c.relation == "lives_in" for c in map(ctx.store.get_claim, claim_ids)):
                    continue
                for url in lead.pages[:PAGES_PER_LEAD]:
                    source = pages.get(scout.page_key(url))
                    if source and (draft := extract.stated_place(hit.person_id, source, lead.name, lead.place, ctx)):
                        claim_ids.append(ctx.store.upsert_claim(draft, ctx.now()).id)
                        considered.append(Considered(person_key=extract.identifier(source.url, lead.name).value,
                                                     name=lead.name, stage="mention", kept=True,
                                                     reason=f"{lead.name}: place {lead.place} from the page line"))
                        break
            out.append(hit.model_copy(update={"claim_ids": claim_ids}))
    return out
