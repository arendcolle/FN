"""One entry per name in a result list; records that share only a name are flagged, never merged."""
from dataclasses import dataclass, field

from fn import identity
from fn.contracts import (
    Entry,
    LaneName,
    LaneOut,
    MatchFlag,
    ResolveIn,
    ResolveOut,
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
    card: list[str] = field(default_factory=list)


def group(outs: list[LaneOut], same_name: dict[str, list[tuple[str, str]]],
          known: identity.Known | None = None) -> ResolveOut:
    """Group hits by person, then by identity key into entries, add the other stored records of that key, and flag each.

    same_name holds (record id, name key) per identity key and known what identity knows of every record. A hit
    joins the first entry of its key where it is sure or likely with a member and has a veto against none. A stored
    record joins the first entry where it is sure or likely with a hit, on the card too, else the first it has no
    veto against. lane_ranks keeps each lane's best rank.
    """
    known = known or identity.Known(names={h.person_id: h.name_key for out in outs for h in out.hits})

    def linked(person_id: str, members: list[str]) -> bool:
        return any(known.links(person_id, m) for m in members)

    def fits(entry: _Building, person_id: str) -> bool:
        return not any(known.veto(person_id, other) for other in entry.persons)

    entries: dict[str, list[_Building]] = {}
    keys: dict[str, str] = {}
    for out in outs:
        for hit in sorted(out.hits, key=lambda h: h.rank):
            person_id = known.person(hit.person_id)
            found = entries.setdefault(keys.setdefault(person_id, identity.key(hit.name_key)), [])
            entry = next((e for e in found if person_id in e.persons), None) or next(
                (e for e in found if fits(e, person_id) and linked(person_id, e.hits)), None)
            if entry is None:
                found.append(entry := _Building())
            if person_id not in entry.persons:
                entry.persons[person_id] = hit.name_key
                entry.hits.append(person_id)
                entry.card.append(person_id)
            entry.lane_ranks[hit.lane] = min(entry.lane_ranks.get(hit.lane, hit.rank), hit.rank)
            entry.claim_ids.extend(c for c in hit.claim_ids if c not in entry.claim_ids)
    result, flags = [], []
    for key, found in entries.items():
        for record, own in same_name.get(key, []):
            person_id = known.person(record)
            if person_id in keys or any(person_id in e.persons for e in found):
                continue
            if entry := next((e for e in found if fits(e, person_id) and linked(person_id, e.hits)), None):
                entry.card.append(person_id)
            if entry := entry or next((e for e in found if fits(e, person_id)), None):
                entry.persons[person_id] = own
        for entry in found:
            person_ids = list(entry.persons)
            flag = f"same name in {len(person_ids)} records, not merged" if len(person_ids) > 1 else None
            result.append(Entry(name_key=key, person_ids=person_ids, hit_person_ids=entry.hits,
                                lane_ranks=entry.lane_ranks, claim_ids=entry.claim_ids, flag=flag,
                                card_person_ids=entry.card))
            first = entry.persons[person_ids[0]]
            flags += [MatchFlag(person_id=person_ids[0], other_person_id=p,
                                reason=SAME_NAME if entry.persons[p] == first else SAME_BUT_INITIALS)
                      for p in person_ids[1:]]
    return ResolveOut(entries=result, flags=flags)


def run(ctx: StepContext, inp: ResolveIn) -> ResolveOut:
    """Group the lanes' hits with the stored records of their identity keys, as identity knows them."""
    known = identity.load(ctx.store, [h.person_id for out in inp.outs for h in out.hits])
    return group(inp.outs, known.same_key, known)
