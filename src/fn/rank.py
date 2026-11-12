"""Reciprocal rank fusion over the lane lists and the evidence lists, the order by evidence and the cuts."""
import math
import re

from fn import evidence, geo, orgs, parse
from fn.contracts import (
    Candidate,
    Claim,
    CutReason,
    Entry,
    ListStatus,
    Org,
    Question,
    RankIn,
    RankOut,
    ScorePart,
    Section,
)
from fn.steps import StepContext, as_of

K = 60
UNDATED = "undated"


def year(value: str | None) -> int | None:
    """The year in the first four characters of a date, or None when they are not a 4-digit year."""
    return int(value[:4]) if value and re.fullmatch(r"[0-9]{4}", value[:4]) else None


def units(claim: Claim) -> frozenset[str]:
    """The years a claim covers: the years its source lists, else each year from valid_from to valid_to when both
    are set and in order.

    Otherwise the years of valid_from, valid_to and claim_date that are set, and 'undated' when none is.
    """
    if claim.years:
        return frozenset(str(y) for y in claim.years)
    start, end = year(claim.valid_from), year(claim.valid_to)
    if start is not None and end is not None and start <= end:
        return frozenset(str(y) for y in range(start, end + 1))
    found = {str(y) for y in (start, end, year(claim.claim_date)) if y is not None}
    return frozenset(found or {UNDATED})


def years_text(found: frozenset[str]) -> str:
    """Units as the card writes them: runs of years as '1999-2002', a lone year as '2018', joined by ', '."""
    years = sorted(int(u) for u in found if u != UNDATED)
    runs: list[list[int]] = []
    for y in years:
        if runs and runs[-1][1] == y - 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return ", ".join([f"{a}-{b}" if a < b else str(a) for a, b in runs] + ([UNDATED] if UNDATED in found else []))


def counted(claims: list[Claim], facts: dict[str, Org]) -> tuple[list[str], frozenset[str]]:
    """The ids of the claims at Belgian organizations, in claim order, and the union of their units."""
    found = [c for c, _ in orgs.belgian_claims(claims, facts)]
    return [c.id for c in found], frozenset().union(*(units(c) for c in found))


def hits(entry: Entry) -> list[str]:
    """The persons a lane hit; an entry stored without hit ids counts its first person as the hit."""
    return entry.hit_person_ids or entry.person_ids[:1]


def card(entry: Entry) -> list[str]:
    """The records whose claims count for an entry: its card records, else its hit records."""
    return entry.card_person_ids or hits(entry)


def belgian_list(entries: list[Entry], claims: list[Claim], facts: dict[str, Org]) -> dict[str, ScorePart]:
    """The belgian_years part of each entry on the list, by the entry's first person id.

    An entry's count is the number of units over the Belgian claims of its card records. Entries with
    none are left out; the rest rank by count, and equal counts share a rank (1, 2, 2, 4).
    """
    by_person: dict[str, list[Claim]] = {}
    for c in claims:
        by_person.setdefault(c.person_id, []).append(c)
    found = {}
    for entry in entries:
        ids, covered = counted([c for p in card(entry) for c in by_person.get(p, [])], facts)
        if covered:
            found[entry.person_ids[0]] = (len(covered), ids)
    counts = sorted((n for n, _ in found.values()), reverse=True)
    parts = {}
    for key, (n, ids) in found.items():
        r = counts.index(n) + 1
        parts[key] = ScorePart(feature="belgian_years", rank=r, points=1 / (K + r), claim_ids=ids,
                               detail=f"{n} year{'' if n == 1 else 's'} at Belgian organizations; 1 / ({K} + {r})")
    return parts


def ranked(feature: str, found: dict[str, tuple[float, list[str], str]], low_first: bool) -> dict[str, ScorePart]:
    """A part per key from (value, claim ids, detail), ranked by value with equal values sharing a rank (1, 2, 2, 4)."""
    first: dict[float, int] = {}
    for n, value in enumerate(sorted((v for v, _, _ in found.values()), reverse=not low_first), 1):
        first.setdefault(value, n)
    out = {}
    for key, (value, ids, detail) in found.items():
        r = first[value]
        out[key] = ScorePart(feature=feature, rank=r, points=1 / (K + r), claim_ids=ids, detail=detail)
    return out


def evidence_lists(found: dict[str, "evidence.Evidence"]) -> dict[str, list[ScorePart]]:
    """The topic, place and seed_list parts by first person id: topic ranks by the words found, place ranks the
    people inside by distance, and a card with a seed-list record gets a fixed 1 / (K + 1)."""
    topic = ranked("topic", {k: (len(e.topic.words), list(e.topic.claim_ids), ", ".join(e.topic.words))
                             for k, e in found.items() if e.topic.words}, low_first=False)
    place = ranked("place", {k: (e.place.km, [e.place.nearest.claim_id], f"{e.place.nearest.basis}: {e.place.nearest.text}")
                             for k, e in found.items() if e.place.fit == "inside" and e.place.nearest}, low_first=True)
    out: dict[str, list[ScorePart]] = {}
    for k, e in found.items():
        seed = ScorePart(feature="seed_list", rank=1, points=1 / (K + 1), claim_ids=list(e.belgian.kinds["seed_list"]),
                         detail=f"seed-list record; 1 / ({K} + 1)") if "seed_list" in e.belgian.kinds else None
        out[k] = [p for p in (topic.get(k), place.get(k), seed) if p]
    return out


def parts(entry: Entry, belgian: ScorePart | None = None) -> list[ScorePart]:
    """One part per lane that ranked the entry, worth 1 / (K + rank), then its belgian_years part when it has one."""
    lanes = [ScorePart(feature=lane, rank=r, points=1 / (K + r), detail=f"1 / ({K} + {r})")
             for lane, r in entry.lane_ranks.items()]
    return lanes + ([belgian] if belgian else [])


def score(found: list[ScorePart]) -> float:
    return math.fsum(p.points for p in found)


def abroad(found: "evidence.Evidence", question: Question | None) -> bool:
    """Whether every place of the person lies outside the question's country and no institution chip matches."""
    country, countries = question.country if question else None, found.place.countries
    return bool(country and countries and country not in countries and not found.institution.match)


def group(found: "evidence.Evidence | None", question: Question | None) -> int:
    """0 for a Belgian tie with a topic match, or for a tie alone when no topic chip has content words; else 1."""
    if found is None or not found.belgian.kinds:
        return 1
    asked = question is not None and any(parse.chip_words(c.text) for c in question.chips.topics)
    return 0 if found.topic.match or not asked else 1


def band(section: Section, found: "evidence.Evidence | None", question: Question | None, grp: int) -> int:
    """The new section's order before score: group 0 then 1, each not outside the area before outside, then the
    people placed only outside the question's country without an institution match. The network section is one band."""
    if section == "network" or found is None:
        return 0
    return 4 if abroad(found, question) else 2 * grp + (found.place.fit == "outside")


def cut_reason(section: Section, found: "evidence.Evidence", question: Question | None) -> CutReason | None:
    """The first cut that applies to a new-section person whose records all come from OpenAlex, or None.

    no_belgian_evidence: no Belgian years. weak_openalex: no topic word, at most 2 Belgian years or none since 2016,
    not inside, no institution match. no_claim: no topic word, no institution match, not inside. outside_country: see abroad.
    """
    if section != "new" or not found.only_openalex:
        return None
    bare, inside = not found.topic.words, found.place.fit == "inside"
    if not found.belgian.years:
        return "no_belgian_evidence"
    if bare and not inside and not found.institution.match and (found.belgian.years <= 2 or (found.belgian.last or 0) < 2016):
        return "weak_openalex"
    if bare and not inside and not found.institution.match:
        return "no_claim"
    return "outside_country" if abroad(found, question) else None


def unread_cut(section: Section, entry: Entry, found: list[ScorePart]) -> CutReason | None:
    """no_belgian_evidence for an entry whose records were not read: in the new section, hit by OpenAlex alone and
    without a belgian_years part."""
    if section == "new" and set(entry.lane_ranks) == {"openalex"} and not any(p.feature == "belgian_years" for p in found):
        return "no_belgian_evidence"
    return None


def fuse(search_id: str, entries: list[Entry], statuses: dict[str, ListStatus],
         belgian: dict[str, ScorePart] | None = None, found: dict[str, "evidence.Evidence"] | None = None,
         question: Question | None = None) -> list[Candidate]:
    """Score each entry by the sum of its parts, order the new section by band, then score, and number each section,
    kept entries apart from cut ones.

    belgian holds the belgian_years parts and found the evidence, by first person id. Section network holds
    entries with a hit person in the list; equal scores are ordered by the first person id.
    """
    belgian, found = belgian or {}, found or {}
    extra = evidence_lists(found)
    rows = []
    for e in entries:
        key = e.person_ids[0]
        section: Section = "network" if any(statuses.get(p) == "in_list" for p in hits(e)) else "new"
        entry_parts = parts(e, belgian.get(key)) + extra.get(key, [])
        ev = found.get(key)
        grp = group(ev, question)
        reason = cut_reason(section, ev, question) if ev else unread_cut(section, e, entry_parts)
        words = len(ev.topic.words) if ev and section == "new" else 0
        rows.append((band(section, ev, question, grp), e, section, entry_parts, grp, reason, words))
    rows.sort(key=lambda r: (r[0], -r[6], -score(r[3]), r[1].person_ids[0]))
    counts: dict[tuple[Section, bool], int] = {}
    out = []
    for _, entry, section, entry_parts, grp, reason, _ in rows:
        counts[section, reason is not None] = counts.get((section, reason is not None), 0) + 1
        out.append(Candidate(
            search_id=search_id, person_id=entry.person_ids[0], person_ids=entry.person_ids, section=section,
            rank=counts[section, reason is not None], score=score(entry_parts),
            lane_ranks=entry.lane_ranks, reason_claim_ids=entry.claim_ids, score_parts=entry_parts,
            hit_person_ids=hits(entry), cut_reason=reason, card_person_ids=entry.card_person_ids, group=grp,
        ))
    return out


def question_of(ctx: StepContext, inp: RankIn) -> tuple[Question, geo.Names | None]:
    """The question evidence reads, and the city index; neither area nor country without an HTTP client or the dump."""
    try:
        names = geo.cities(ctx.http) if ctx.http else None
    except Exception as exc:  # noqa: BLE001 without the city index the ranking goes on with every place unknown
        ctx.log.warning("no city index, so no place: %s", exc)
        names = None
    place = inp.chips.place
    area = geo.locate(place.text, names) if names and place and place.kind in geo.METRO_KINDS else None
    return Question(chips=inp.chips, area=area, country=geo.question_country(names, place, area)), names


def run(ctx: StepContext, inp: RankIn) -> RankOut:
    """Rank the entries by their lanes and card evidence, as of the creation of the search it reruns, else its own."""
    persons = ctx.store.get_persons([p for e in inp.entries for p in e.person_ids])
    statuses = {p: person.list_status for p, person in persons.items()}
    records = list(dict.fromkeys(p for e in inp.entries for p in card(e)))
    claims = ctx.store.claims_of(records)
    facts = ctx.store.get_orgs(list(dict.fromkeys(c.org_id for c in claims if c.org_id)))
    schemes = {p: frozenset(i.scheme for i in found) for p, found in ctx.store.identifiers_of(records).items()}
    today = as_of(ctx)
    question, names = question_of(ctx, inp)
    by_person: dict[str, list[Claim]] = {}
    for c in claims:
        by_person.setdefault(c.person_id, []).append(c)
    found = {}
    for e in inp.entries:
        on_card = card(e)
        found[e.person_ids[0]] = evidence.of({p: schemes.get(p, frozenset()) for p in on_card},
                                             [c for p in on_card for c in by_person.get(p, [])], facts, question, today, names)
    return RankOut(candidates=fuse(ctx.search_id, inp.entries, statuses, belgian_list(inp.entries, claims, facts),
                                   found, question))
