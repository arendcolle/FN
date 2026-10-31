"""One entry per name in a result list; records that share only a name are flagged, never merged."""
from fn.contracts import (
    Entry,
    LaneName,
    LaneOut,
    MatchFlag,
    ResolveIn,
    ResolveOut,
    group_key,
)
from fn.steps import StepContext

SAME_NAME = "same name, no shared identifier"
SAME_BUT_INITIALS = "same name apart from middle initials, no shared identifier"


def group(outs: list[LaneOut], same_name: dict[str, list[tuple[str, str]]]) -> ResolveOut:
    """Group hits by group key into entries, add the other stored records of that key, and flag each extra record.

    same_name holds (person id, name key) per group key. Persons appear in the order their best hit
    was found; lane_ranks keeps each lane's best rank.
    """
    entries: dict[str, tuple[dict[str, str], dict[LaneName, int], list[str]]] = {}
    for out in outs:
        for hit in sorted(out.hits, key=lambda h: h.rank):
            persons, lane_ranks, claim_ids = entries.setdefault(group_key(hit.name_key), ({}, {}, []))
            persons.setdefault(hit.person_id, hit.name_key)
            lane_ranks[hit.lane] = min(lane_ranks.get(hit.lane, hit.rank), hit.rank)
            claim_ids.extend(c for c in hit.claim_ids if c not in claim_ids)
    found, flags = [], []
    for key, (persons, lane_ranks, claim_ids) in entries.items():
        for person_id, own in same_name.get(key, []):
            persons.setdefault(person_id, own)
        person_ids = list(persons)
        flag = f"same name in {len(person_ids)} records, not merged" if len(person_ids) > 1 else None
        found.append(Entry(name_key=key, person_ids=person_ids, lane_ranks=lane_ranks, claim_ids=claim_ids, flag=flag))
        first = persons[person_ids[0]]
        flags += [MatchFlag(person_id=person_ids[0], other_person_id=p,
                            reason=SAME_NAME if persons[p] == first else SAME_BUT_INITIALS) for p in person_ids[1:]]
    return ResolveOut(entries=found, flags=flags)


def run(ctx: StepContext, inp: ResolveIn) -> ResolveOut:
    keys = list(dict.fromkeys(group_key(h.name_key) for out in inp.outs for h in out.hits))
    return group(inp.outs, ctx.store.person_ids_by_group_key(keys))
