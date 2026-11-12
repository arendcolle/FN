"""Seed lane: topic and institution chips as a quoted FTS5 query over the seed claims, or people near a lone place."""
from collections.abc import Callable

from fn import evidence, geo, orgs, parse
from fn.contracts import (
    Chips,
    Considered,
    GeoArea,
    LaneHit,
    LaneIn,
    LaneName,
    LaneOut,
    Question,
    SourceKind,
)
from fn.net import HttpError
from fn.steps import StepContext, as_of

name: LaneName = "seeds"
MAX_HITS = 300
MAX_PLACE_HITS = 20
NO_QUERY = "no topic or institution chip"
EXCLUDED: tuple[SourceKind, ...] = ("record", "vendor_record", "vendor_page")


def phrase(text: str) -> str | None:
    """text as one FTS5 string with inner quotes doubled; None when it holds no letter or digit."""
    return f'"{text.replace('"', '""')}"' if any(c.isalnum() for c in text) else None


def fts_query(chips: Chips, aliases: Callable[[str], list[str]] = lambda _: []) -> str:
    """The content words of every topic chip and every token of every institution chip ORed, plus each alias as a phrase.

    Terms are quoted, so FTS5 operators and punctuation in a chip are plain text. Empty when no chip has a term.
    """
    terms = [phrase(w) for chip in chips.topics for w in parse.content_words(chip.text)]
    terms += [phrase(t) for chip in chips.institutions for t in chip.text.split()]
    terms += [phrase(a) for chip in chips.institutions for a in aliases(chip.text)]
    return " OR ".join(dict.fromkeys(t for t in terms if t))


def area_of(ctx: StepContext, chips: Chips) -> GeoArea | None:
    """geo.area of the place chip; None without an HTTP client or when the city dump cannot be fetched."""
    if ctx.http is None or chips.place is None:
        return None
    try:
        return geo.area(ctx.http, chips.place)
    except HttpError as exc:
        ctx.log.warning("seed lane: no city index, so no place search: %s", exc)
        return None


def near(ctx: StepContext, area: GeoArea) -> list[tuple[str, float | None, evidence.Place | None]]:
    """Each person with a record in the area's box, with their nearest current place inside the radius and its
    distance, nearest first; None for a person with no such place.

    Only claims from sources of no EXCLUDED kind count, and evidence.where decides whether a person is inside.
    """
    canonical = ctx.store.canonical_ids(ctx.store.persons_near(area.lat, area.lon, area.radius_km, EXCLUDED))
    people = list(dict.fromkeys(canonical.values()))
    claims = ctx.store.claims_of(people)
    kinds = {s.id: s.kind for s in ctx.store.get_sources(list({c.source_id for c in claims})).values()}
    facts = ctx.store.get_orgs(list({c.org_id for c in claims if c.org_id}))
    when, own = as_of(ctx), {}
    for c in claims:
        if kinds.get(c.source_id) not in EXCLUDED:
            own.setdefault(c.person_id, []).append(c)
    found, ask = [], Question(area=area)
    for person in people:
        where = evidence.where(evidence.places(own.get(person, []), facts, when), ask)
        found.append((person, where.km, where.nearest) if where.fit == "inside" else (person, None, None))
    return sorted(found, key=lambda f: (f[1] is None, f[1] or 0.0, f[0]))


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    query = fts_query(inp.chips, lambda text: orgs.names(orgs.org_id(text)))
    # A place search beside a topic or institution lifted people who match only the city above topic matches.
    area = area_of(ctx, inp.chips) if not query and not inp.chips.institutions else None
    if not query and area is None:
        return LaneOut(lane=name, query="", total_seen=0,
                       considered=[Considered(person_key="-", name="", stage="query", kept=False, reason=NO_QUERY)])
    hits, considered = [], []
    # EXCLUDED is the source kinds that searches write; seed, import and staff claims were entered on purpose.
    for rank, (person, claim, score) in enumerate(ctx.store.match_claims(query, exclude=EXCLUDED) if query else [], 1):
        kept = rank <= MAX_HITS
        if kept:
            hits.append(LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=-score,
                                matched_on=claim.value, claim_ids=[claim.id]))
        reason = f"fts rank {rank}, matched {claim.value!r}" if kept else f"fts rank {rank}, below the top {MAX_HITS}"
        considered.append(Considered(person_key=person.id, name=person.display_name, stage="fts", kept=kept,
                                     reason=reason))
    matched, added = len(considered), 0
    if area:
        found = near(ctx, area)
        persons = ctx.store.get_persons([p for p, _, _ in found])
        for person, km, place in found:
            kept = place is not None and added < MAX_PLACE_HITS
            if kept:
                added += 1
                hits.append(LaneHit(person_id=person, name_key=persons[person].name_key, lane=name,
                                    rank=len(hits) + 1, score=0.0, matched_on=f"based in {place.text}",
                                    claim_ids=[place.claim_id]))
            reason = (f"no current place within {area.radius_km:.0f} km of {area.city}" if place is None else
                      f"based in {place.text!r}, {km:.0f} km from {area.city}" if kept else
                      f"based in {place.text!r}, below the nearest {MAX_PLACE_HITS}")
            considered.append(Considered(person_key=person, name=persons[person].display_name, stage="place",
                                         kept=kept, reason=reason))
    ctx.log.info("seed lane: %d people match %s, %d place hits added near %s", matched, query, added,
                 area.city if area else "no located city")
    return LaneOut(lane=name, query=query, total_seen=len(considered), hits=hits, considered=considered)
