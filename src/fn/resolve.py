"""One entry per name in a result list; records that share only a name are flagged, never merged."""
from dataclasses import dataclass, field

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


@dataclass
class _Building:
    persons: dict[str, str] = field(default_factory=dict)
    hits: list[str] = field(default_factory=list)
    lane_ranks: dict[LaneName, int] = field(default_factory=dict)
    claim_ids: list[str] = field(default_factory=list)


def group(outs: list[LaneOut], same_name: dict[str, list[tuple[str, str]]], canonical: dict[str, str] | None = None,
          not_same: set[frozenset[str]] | None = None, orcids: dict[str, list[str]] | None = None) -> ResolveOut:
    """Group hits by person, then by group key into entries, add the other stored records of that key, and flag each.

    same_name holds (record id, name key) per group key, canonical each record's canonical id and orcids each
    record's ORCIDs. Two persons with a not_same pair or different ORCIDs go in separate entries: a person goes
    in the first entry of its key that holds nobody it must stay apart from. lane_ranks keeps each lane's best rank.
    """
    canonical = canonical or {}
    pairs = {frozenset(canonical.get(p, p) for p in pair) for pair in not_same or set()}
    held: dict[str, set[str]] = {}
    for record, values in (orcids or {}).items():
        held.setdefault(canonical.get(record, record), set()).update(values)

    def apart(a: str, b: str) -> bool:
        return frozenset((a, b)) in pairs or bool(held.get(a) and held.get(b) and not held[a] & held[b])

    def fits(entry: _Building, person_id: str) -> bool:
        return not any(apart(person_id, other) for other in entry.persons)

    entries: dict[str, list[_Building]] = {}
    keys: dict[str, str] = {}
    for out in outs:
        for hit in sorted(out.hits, key=lambda h: h.rank):
            person_id = canonical.get(hit.person_id, hit.person_id)
            found = entries.setdefault(keys.setdefault(person_id, group_key(hit.name_key)), [])
            entry = next((e for e in found if person_id in e.persons), None) or next(
                (e for e in found if fits(e, person_id)), None)
            if entry is None:
                found.append(entry := _Building())
            if person_id not in entry.persons:
                entry.persons[person_id] = hit.name_key
                entry.hits.append(person_id)
            entry.lane_ranks[hit.lane] = min(entry.lane_ranks.get(hit.lane, hit.rank), hit.rank)
            entry.claim_ids.extend(c for c in hit.claim_ids if c not in entry.claim_ids)
    result, flags = [], []
    for key, found in entries.items():
        for record, own in same_name.get(key, []):
            person_id = canonical.get(record, record)
            if person_id in keys or any(person_id in e.persons for e in found):
                continue
            if entry := next((e for e in found if fits(e, person_id)), None):
                entry.persons[person_id] = own
        for entry in found:
            person_ids = list(entry.persons)
            flag = f"same name in {len(person_ids)} records, not merged" if len(person_ids) > 1 else None
            result.append(Entry(name_key=key, person_ids=person_ids, hit_person_ids=entry.hits,
                                lane_ranks=entry.lane_ranks, claim_ids=entry.claim_ids, flag=flag))
            first = entry.persons[person_ids[0]]
            flags += [MatchFlag(person_id=person_ids[0], other_person_id=p,
                                reason=SAME_NAME if entry.persons[p] == first else SAME_BUT_INITIALS)
                      for p in person_ids[1:]]
    return ResolveOut(entries=result, flags=flags)


def run(ctx: StepContext, inp: ResolveIn) -> ResolveOut:
    """Group the lanes' hits with the stored same-name records, their canonical ids, not-same pairs and ORCIDs."""
    keys = list(dict.fromkeys(group_key(h.name_key) for out in inp.outs for h in out.hits))
    same_name = ctx.store.person_ids_by_group_key(keys)
    hit_ids = [h.person_id for out in inp.outs for h in out.hits]
    records = list(dict.fromkeys([*hit_ids, *(p for found in same_name.values() for p, _ in found)]))
    canonical = ctx.store.canonical_ids(records)
    everyone = list(dict.fromkeys([*records, *canonical.values()]))
    not_same = ctx.store.not_same_pairs(everyone)
    canonical |= ctx.store.canonical_ids([p for pair in not_same for p in pair])
    orcids = {p: [i.value for i in found if i.scheme == "orcid"]
              for p, found in ctx.store.identifiers_of(everyone).items()}
    return group(inp.outs, same_name, canonical, not_same, orcids)
