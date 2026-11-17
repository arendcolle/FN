"""Seed lane: topic, role and institution chips as a quoted FTS5 query over the claims, with a second pass on related
words, or people near a lone place."""
from collections.abc import Callable
from typing import get_args

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


def phrase(text: str) -> str | None:
    """text as one FTS5 string with inner quotes doubled; None when it holds no letter or digit."""
    return f'"{text.replace('"', '""')}"' if any(c.isalnum() for c in text) else None


def excluded(chips: Chips) -> tuple[SourceKind, ...]:
    """The source kinds the search leaves out: OpenAlex and ORCID records unless the question asks for research."""
    return () if parse.wants_research(chips) else ("record",)


def fts_query(chips: Chips, aliases: Callable[[str], list[str]] = lambda _: []) -> str:
    """The content words of every topic and role chip and every token of every institution chip ORed, plus each alias
    as a phrase.

    Terms are quoted, so FTS5 operators and punctuation in a chip are plain text. Empty when no chip has a term.
    """
    terms = [phrase(w) for chip in chips.topics for w in parse.content_words(chip.text)]
    terms += [phrase(w) for chip in chips.roles for w in parse.content_words(chip.text)]
    terms += [phrase(t) for chip in chips.institutions for t in chip.text.split()]
    terms += [phrase(a) for chip in chips.institutions for a in aliases(chip.text)]
    return " OR ".join(dict.fromkeys(t for t in terms if t))


def related_query(chips: Chips, first: str) -> str:
    """Each related word of every topic and role chip as one phrase ORed, leaving out a term already in first.

    Empty for chips without related words, as version 1 chips are.
    """
    seen = {t.casefold() for t in first.split(" OR ")}
    terms = [phrase(r) for chip in [*chips.topics, *chips.roles] for r in chip.related]
    return " OR ".join(dict.fromkeys(t for t in terms if t and t.casefold() not in seen))


def area_of(ctx: StepContext, chips: Chips) -> GeoArea | None:
    """geo.area of the place chip; None without an HTTP client or when the city dump cannot be fetched."""
    if ctx.http is None or chips.place is None:
        return None
    try:
        return geo.area(ctx.http, chips.place)
    except HttpError as exc:
        ctx.log.warning("seed lane: no city index, so no place search: %s", exc)
        return None


def near(ctx: StepContext, area: GeoArea, chips: Chips) -> list[tuple[str, float | None, evidence.Place | None]]:
    """Each person with a record in the area's box, with their nearest current place inside the radius and its
    distance, nearest first; None for a person with no such place.

    Only claims from sources of no kind in excluded(chips) count, and evidence.where decides whether a person is inside.
    """
    skip = excluded(chips)
    canonical = ctx.store.canonical_ids(ctx.store.persons_near(area.lat, area.lon, area.radius_km, skip))
    people = list(dict.fromkeys(canonical.values()))
    claims = ctx.store.claims_of(people)
    kinds = ctx.store.source_kinds(list({c.source_id for c in claims}))
    facts = ctx.store.get_orgs(list({c.org_id for c in claims if c.org_id}))
    when, own = as_of(ctx), {}
    for c in claims:
        if kinds.get(c.source_id) not in skip:
            own.setdefault(c.person_id, []).append(c)
    found, ask = [], Question(area=area)
    for person in people:
        where = evidence.where(evidence.places(own.get(person, []), facts, when), ask)
        found.append((person, where.km, where.nearest) if where.fit == "inside" else (person, None, None))
    return sorted(found, key=lambda f: (f[1] is None, f[1] or 0.0, f[0]))


def must_place(chips: Chips) -> bool:
    """Whether the question requires its place (version 2 chips with a place of need must)."""
    return chips.version >= 2 and chips.place is not None and chips.place.need == "must"


def inside_first(ctx: StepContext, area: GeoArea, chips: Chips, ranked: list) -> tuple[list[LaneHit], list[Considered]]:
    """The hits of a required place on one rank counter under MAX_HITS, and the verdict of each.

    Word and related matches inside the area come first in their order, then people inside without a match, nearest
    first, then the other matches in their order.
    """
    found = near(ctx, area, chips)
    persons = ctx.store.get_persons([p for p, _, _ in found])
    inside = {p: (km, place) for p, km, place in found if place is not None}
    matched = {m[0].merged_into or m[0].id for m, _ in ranked}
    is_in = [(r[0][0].merged_into or r[0][0].id) in inside for r in ranked]
    entries = [("match", r) for r, i in zip(ranked, is_in) if i] + [("place", p) for p in inside if p not in matched]
    entries += [("match", r) for r, i in zip(ranked, is_in) if not i]
    hits, considered = [], []
    for rank, (how, entry) in enumerate(entries, 1):
        kept = rank <= MAX_HITS
        if how == "match":
            (person, claim, score), label = entry
            hit = LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=-score,
                          matched_on=claim.value, claim_ids=[claim.id])
            reason = f"fts rank {rank}, {label}matched {claim.value!r}" if kept else f"fts rank {rank}, {label}below the top {MAX_HITS}"
            stage, who = "fts", person
        else:
            km, place = inside[entry]
            who = persons[entry]
            hit = LaneHit(person_id=entry, name_key=who.name_key, lane=name, rank=rank, score=0.0,
                          matched_on=f"based in {place.text}", claim_ids=[place.claim_id])
            reason = (f"based in {place.text!r}, {km:.0f} km from {area.city}" if kept else
                      f"based in {place.text!r}, below the top {MAX_HITS}")
            stage = "place"
        hits += [hit] if kept else []
        considered.append(Considered(person_key=who.id, name=who.display_name, stage=stage, kept=kept, reason=reason))
    considered += [Considered(person_key=p, name=persons[p].display_name, stage="place", kept=False,
                              reason=f"no current place within {area.radius_km:.0f} km of {area.city}")
                   for p, _, place in found if place is None and p not in matched]
    return hits, considered


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    chips = inp.chips
    query = fts_query(chips, lambda text: orgs.names(orgs.org_id(text)))
    related = related_query(chips, query)
    # A place search beside a topic or institution lifted people who match only the city above topic matches.
    lone_place = not any(parse.content_words(c.text) for c in chips.topics) and not chips.institutions
    must = must_place(chips)
    area = area_of(ctx, chips) if lone_place or must else None
    if not query and not related and area is None:
        return LaneOut(lane=name, query="", total_seen=0,
                       considered=[Considered(person_key="-", name="", stage="query", kept=False, reason=NO_QUERY)])
    hits, considered = [], []
    # OpenAlex and ORCID records count only when the question asks for research, and rank after every other kind.
    groups = [("record",)]
    if parse.wants_research(chips):
        groups.append(tuple(k for k in get_args(SourceKind) if k != "record"))
    ranked, seen = [], set()
    for exclude in groups:
        for q, label in ((query, ""), (related, "related word, ")):
            for m in ctx.store.match_claims(q, exclude=exclude) if q else []:
                if m[0].id not in seen:
                    seen.add(m[0].id)
                    ranked.append((m, label))
    if must and area:
        hits, considered = inside_first(ctx, area, chips, ranked)
    else:
        for rank, ((person, claim, score), label) in enumerate(ranked, 1):
            kept = rank <= MAX_HITS
            if kept:
                hits.append(LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=-score,
                                    matched_on=claim.value, claim_ids=[claim.id]))
            reason = (f"fts rank {rank}, {label}matched {claim.value!r}" if kept else
                      f"fts rank {rank}, {label}below the top {MAX_HITS}")
            considered.append(Considered(person_key=person.id, name=person.display_name, stage="fts", kept=kept,
                                         reason=reason))
    matched, added = sum(not label for _, label in ranked), 0
    if area and not must:
        found = near(ctx, area, chips)
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
    ctx.log.info("seed lane: %d people match %s, %d more on related words, %d place hits added near %s", matched,
                 query, len(ranked) - matched, added, area.city if area else "no located city")
    shown = f"{query}; related: {related}" if related else query
    return LaneOut(lane=name, query=shown, total_seen=len(considered), hits=hits, considered=considered)
