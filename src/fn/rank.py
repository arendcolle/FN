"""Reciprocal rank fusion over entries, and the section of each candidate."""
from fn import ties
from fn.contracts import (
    Candidate,
    Entry,
    ListStatus,
    RankIn,
    RankOut,
    Section,
    TieLabel,
)
from fn.steps import StepContext

K = 60


def score(entry: Entry) -> float:
    return sum(1 / (K + r) for r in entry.lane_ranks.values())


def fuse(search_id: str, entries: list[Entry], labels: dict[str, TieLabel],
         statuses: dict[str, ListStatus]) -> list[Candidate]:
    """Score each entry by the sum of 1 / (K + rank) over its lanes and number it within its section.

    Section network holds entries with a record in the list; equal scores are ordered by the first person id.
    """
    ordered = sorted(entries, key=lambda e: (-score(e), e.person_ids[0]))
    counts: dict[Section, int] = {"network": 0, "new": 0}
    found = []
    for entry in ordered:
        section: Section = "network" if any(statuses.get(p) == "in_list" for p in entry.person_ids) else "new"
        counts[section] += 1
        found.append(Candidate(
            search_id=search_id, person_id=entry.person_ids[0], person_ids=entry.person_ids, section=section,
            rank=counts[section], score=score(entry),
            lane_ranks=entry.lane_ranks, reason_claim_ids=entry.claim_ids,
            tie=ties.combine([labels[p] for p in entry.person_ids if p in labels]),
        ))
    return found


def run(ctx: StepContext, inp: RankIn) -> RankOut:
    persons = ctx.store.get_persons([p for e in inp.entries for p in e.person_ids])
    statuses = {p: person.list_status for p, person in persons.items()}
    return RankOut(candidates=fuse(ctx.search_id, inp.entries, inp.labels, statuses))
