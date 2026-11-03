"""Reciprocal rank fusion over the lane lists and the belgian_years list, and the section of each candidate."""
import math
import re

from fn import orgs
from fn.contracts import (
    Candidate,
    Claim,
    Entry,
    ListStatus,
    Org,
    RankIn,
    RankOut,
    ScorePart,
    Section,
)
from fn.steps import StepContext

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


def belgian_list(entries: list[Entry], claims: list[Claim], facts: dict[str, Org]) -> dict[str, ScorePart]:
    """The belgian_years part of each entry on the list, by name key.

    An entry's count is the number of units over the Belgian claims of its hit records. Entries with
    none are left out; the rest rank by count, and equal counts share a rank (1, 2, 2, 4).
    """
    by_person: dict[str, list[Claim]] = {}
    for c in claims:
        by_person.setdefault(c.person_id, []).append(c)
    found = {}
    for entry in entries:
        ids, covered = counted([c for p in entry.hit_person_ids for c in by_person.get(p, [])], facts)
        if covered:
            found[entry.name_key] = (len(covered), ids)
    counts = sorted((n for n, _ in found.values()), reverse=True)
    parts = {}
    for key, (n, ids) in found.items():
        r = counts.index(n) + 1
        parts[key] = ScorePart(feature="belgian_years", rank=r, points=1 / (K + r), claim_ids=ids,
                               detail=f"{n} year{'' if n == 1 else 's'} at Belgian organizations; 1 / ({K} + {r})")
    return parts


def parts(entry: Entry, belgian: ScorePart | None = None) -> list[ScorePart]:
    """One part per lane that ranked the entry, worth 1 / (K + rank), then its belgian_years part when it has one."""
    lanes = [ScorePart(feature=lane, rank=r, points=1 / (K + r), detail=f"1 / ({K} + {r})")
             for lane, r in entry.lane_ranks.items()]
    return lanes + ([belgian] if belgian else [])


def score(found: list[ScorePart]) -> float:
    return math.fsum(p.points for p in found)


def fuse(search_id: str, entries: list[Entry], statuses: dict[str, ListStatus],
         belgian: dict[str, ScorePart] | None = None) -> list[Candidate]:
    """Score each entry by the sum of its parts and number it within its section.

    belgian holds the belgian_years parts by name key. Section network holds entries with a record
    in the list; equal scores are ordered by the first person id.
    """
    belgian = belgian or {}
    ordered = sorted(((e, parts(e, belgian.get(e.name_key))) for e in entries),
                     key=lambda ep: (-score(ep[1]), ep[0].person_ids[0]))
    counts: dict[Section, int] = {"network": 0, "new": 0}
    found = []
    for entry, entry_parts in ordered:
        section: Section = "network" if any(statuses.get(p) == "in_list" for p in entry.person_ids) else "new"
        counts[section] += 1
        found.append(Candidate(
            search_id=search_id, person_id=entry.person_ids[0], person_ids=entry.person_ids, section=section,
            rank=counts[section], score=score(entry_parts),
            lane_ranks=entry.lane_ranks, reason_claim_ids=entry.claim_ids, score_parts=entry_parts,
        ))
    return found


def run(ctx: StepContext, inp: RankIn) -> RankOut:
    persons = ctx.store.get_persons([p for e in inp.entries for p in e.person_ids])
    statuses = {p: person.list_status for p, person in persons.items()}
    claims = ctx.store.claims_of([p for e in inp.entries for p in e.hit_person_ids])
    facts = ctx.store.get_orgs(list(dict.fromkeys(c.org_id for c in claims if c.org_id)))
    return RankOut(candidates=fuse(ctx.search_id, inp.entries, statuses, belgian_list(inp.entries, claims, facts)))
