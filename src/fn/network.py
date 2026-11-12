"""Who is in the network: the staff decisions, each one event that undo can reverse."""
import hashlib
import uuid
from datetime import datetime

from fn import identity
from fn.contracts import (
    AddedVia,
    ClaimDraft,
    Event,
    EventKind,
    Identifier,
    Section,
    Source,
    normalize,
)
from fn.store import Store

CONTACT_KINDS = ("email", "phone")
MAX_CONTACT = 200
LATER = "Someone made a later decision about this person, so this one can no longer be undone."


class UndoRefused(Exception):
    """An undo FN will not do; the message is one sentence for staff."""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _canonical(store: Store, person_ids: list[str]) -> list[str]:
    """The canonical ids of the persons, once each, in order; raises ValueError for an unknown id."""
    found = store.canonical_ids(person_ids)
    if missing := [p for p in person_ids if p not in found]:
        raise ValueError(f"no person with id {missing[0]}")
    return list(dict.fromkeys(found[p] for p in person_ids))


def _pairs(store: Store, person_ids: list[str]) -> set[frozenset[str]]:
    """The stored not-same pairs that touch the ids, as canonical ids; a pair inside one person is dropped."""
    raw = store.not_same_pairs(person_ids)
    canonical = store.canonical_ids([p for pair in raw for p in pair])
    pairs = {frozenset(canonical.get(p, p) for p in pair) for pair in raw}
    return {pair for pair in pairs if len(pair) == 2}


def _event(store: Store, kind: EventKind, now: datetime, detail: dict, **fields) -> Event:
    event = Event(id=str(uuid.uuid4()), at=now, kind=kind, detail=detail, **fields)
    store.add_event(event)
    return event


def add(store: Store, hit_person_ids: list[str], *, via: AddedVia, now: datetime, search_id: str | None = None,
        rank: int | None = None, section: Section | None = None, import_id: str | None = None,
        not_same_as: list[str] = ()) -> Event:
    """Merge each later record that identity finds sure or likely the first one's person into it, and add that person.

    A record with a veto against one already merging stays apart too. When the person is in the network already
    and nothing would merge, nothing is written and its latest add event comes back.
    """
    with store.tx():
        target, *others = _canonical(store, hit_person_ids)
        prior = store.get_persons([target])[target].list_status
        known = identity.load(store, [target, *others]) if others else identity.Known()
        apart_from = _pairs(store, [r.id for p in [target, *others] for r in store.records_of(p)])
        merging, left_apart = [], []
        for other in others:
            if known.links(target, other) and not any(known.veto(other, m) for m in merging):
                merging.append(other)
            else:
                left_apart.append(other)
        if prior == "in_list" and not merging:
            latest = next((e for e in store.events_of(target) if e.kind == "add" and e.person_id == target), None)
            if latest:
                return latest
        prior_merged = {}
        for other in merging:
            for record in store.records_of(other):
                prior_merged[record.id] = {"merged_into": record.merged_into, "merged_at": _iso(record.merged_at)}
                store.set_merged_into(record.id, target, now)
        store.set_list_status(target, "in_list")
        store.set_seen(target, now)
        added = [p for p in _canonical(store, list(not_same_as))
                 if p != target and frozenset((target, p)) not in apart_from]
        for p in added:
            store.add_not_same(target, p, now)
        detail = {"via": via, "prior_status": prior, "merged": list(prior_merged), "prior_merged": prior_merged,
                  "left_apart": left_apart, "not_same": added}
        return _event(store, "add", now, detail, person_id=target, search_id=search_id, rank=rank, section=section,
                      import_id=import_id)


def skip(store: Store, hit_person_ids: list[str], *, now: datetime, search_id: str | None = None,
         rank: int | None = None, section: Section | None = None) -> Event:
    """Set the person of every hit to skipped; raises ValueError when one of them is in the network."""
    with store.tx():
        persons = _canonical(store, hit_person_ids)
        found = store.get_persons(persons)
        if any(found[p].list_status == "in_list" for p in persons):
            raise ValueError("This person is in your network, so they cannot be skipped.")
        prior = {p: found[p].list_status for p in persons}
        for p in persons:
            store.set_list_status(p, "skipped")
        return _event(store, "skip", now, {"prior_status": prior}, person_id=persons[0], search_id=search_id,
                      rank=rank, section=section)


def remove(store: Store, person_id: str, *, now: datetime) -> Event:
    """Take a network person out of the network, back to candidate; raises ValueError for anyone else."""
    with store.tx():
        (person,) = _canonical(store, [person_id])
        if store.get_persons([person])[person].list_status != "in_list":
            raise ValueError("This person is not in your network.")
        store.set_list_status(person, "candidate")
        return _event(store, "remove", now, {"prior_status": "in_list"}, person_id=person)


def merge(store: Store, person_ids: list[str], into_id: str, *, now: datetime, search_id: str | None = None,
          rank: int | None = None, section: Section | None = None) -> Event:
    """Merge each person into the person of into_id, with the records already merged into them, so depth stays one.

    A not-same pair between them goes. When one of them is in the network, the merged person is.
    Raises ValueError when a person would merge into itself.
    """
    with store.tx():
        (into,) = _canonical(store, [into_id])
        moving = _canonical(store, person_ids)
        if into in moving:
            raise ValueError("A person cannot be merged into themselves.")
        statuses = {p: person.list_status for p, person in store.get_persons([into, *moving]).items()}
        pairs = store.not_same_pairs([r.id for p in [into, *moving] for r in store.records_of(p)])
        owner = store.canonical_ids([p for pair in pairs for p in pair])
        removed = [sorted(pair) for pair in pairs
                   if {owner.get(p, p) for p in pair} in ({into, m} for m in moving)]
        merged = [{"id": r.id, "merged_into": r.merged_into, "merged_at": _iso(r.merged_at)}
                  for p in moving for r in store.records_of(p)]
        for a, b in removed:
            store.remove_not_same(a, b)
        for record in merged:
            store.set_merged_into(record["id"], into, now)
        if statuses[into] != "in_list" and any(statuses[m] == "in_list" for m in moving):
            store.set_list_status(into, "in_list")
        detail = {"merged": merged, "prior_status": statuses[into], "not_same_removed": removed}
        return _event(store, "merge", now, detail, person_id=into, other_person_id=moving[0], search_id=search_id,
                      rank=rank, section=section)


def not_same(store: Store, person_id: str, other_id: str, *, now: datetime) -> Event:
    """Store that the two are different people; a record merged into the other's person is separated first."""
    with store.tx():
        if person_id == other_id:
            raise ValueError("A record is always the same person as itself.")
        (a,), (b,) = _canonical(store, [person_id]), _canonical(store, [other_id])
        separated = None
        if a == b:
            record = other_id if other_id != b else person_id
            found = store.get_persons([record])[record]
            separated = {"id": record, "merged_into": found.merged_into, "merged_at": _iso(found.merged_at)}
            store.set_merged_into(record, None, None)
            (a,), (b,) = _canonical(store, [person_id]), _canonical(store, [other_id])
        added = frozenset((a, b)) not in _pairs(store, [a, b])
        if added:
            store.add_not_same(a, b, now)
        detail = {"separated": separated, "pair": sorted((a, b)), "pair_added": added}
        return _event(store, "not_same", now, detail, person_id=a, other_person_id=b)


def reject_claim(store: Store, claim_id: str, *, now: datetime) -> Event:
    """Mark the claim rejected, which hides it and its same-value claims of that person."""
    with store.tx():
        claim = store.get_claim(claim_id)
        if claim is None:
            raise ValueError("That fact no longer exists.")
        (person,) = _canonical(store, [claim.person_id])
        store.set_claim_rejected(claim_id, now)
        return _event(store, "reject_claim", now, {"prior_rejected_at": _iso(claim.rejected_at)}, person_id=person,
                      claim_id=claim_id)


def _checked(kind: str, value: str) -> str:
    """The typed contact value trimmed; raises ValueError with a sentence a page can show."""
    if kind not in CONTACT_KINDS:
        raise ValueError(f"A contact is an email or a phone number, not {kind}.")
    value = normalize(value)
    if len(value) > MAX_CONTACT:
        raise ValueError(f"That is too long: at most {MAX_CONTACT} characters.")
    if kind == "email" and "@" not in value.strip("@"):
        raise ValueError("Enter an email address like name@example.org.")
    if kind == "phone" and sum(c.isdigit() for c in value) < 7:
        raise ValueError("Enter a phone number with at least 7 digits.")
    return value


def staff_source(event_id: str, line: str, now: datetime) -> Source:
    """A staff source holding the one line staff typed, dated today."""
    text = normalize(line)
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    url = f"fn:staff/{event_id}"
    return Source(id=hashlib.sha1(f"staff\0{url}\0{content_hash}".encode()).hexdigest(), kind="staff", url=url,
                  title="Typed by staff", text=text, content_hash=content_hash, source_date=now.date().isoformat(),
                  date_method="staff_edit", fetched_at=now)


def set_contact(store: Store, person_id: str, kind: str, value: str, *, now: datetime,
                replaces: str | None = None) -> Event:
    """Write a typed email or phone number as a staff claim on the person, and reject the claim it replaces.

    A typed email also becomes the person's email identifier. Raises ValueError with a sentence for a bad
    value or an email another person holds.
    """
    value = _checked(kind, value)
    with store.tx():
        (person,) = _canonical(store, [person_id])
        added = False
        if kind == "email":
            address = Identifier(scheme="email", value=value.lower())
            holder = store.person_ids_by_identifier("email", [address.value]).get(address.value)
            if holder and _canonical(store, [holder])[0] != person:
                raise ValueError("Another person in FN already has this email address.")
            added = holder is None and store.add_identifier(person, address)
        prior = None
        if replaces:
            replaced = store.get_claim(replaces)
            if replaced is None:
                raise ValueError("The fact this replaces no longer exists.")
            prior = _iso(replaced.rejected_at)
            store.set_claim_rejected(replaces, now)
        event_id = str(uuid.uuid4())
        source = staff_source(event_id, f"{kind}: {value}", now)
        claim = store.upsert_claim(ClaimDraft(
            person_id=person, kind=kind, value=value, quote=source.text, quote_start=0, quote_end=len(source.text),
            source=source, claim_date=now.date().isoformat(), date_precision="day", date_method="staff_edit",
        ), at=now)
        detail = {"claim_id": claim.id, "replaces": replaces, "prior_rejected_at": prior, "identifier_added": added}
        event = Event(id=event_id, at=now, kind="edit_contact", person_id=person, claim_id=claim.id, detail=detail)
        store.add_event(event)
        return event


def record_import(store: Store, import_id: str, *, now: datetime, detail: dict) -> Event:
    with store.tx():
        return _event(store, "import", now, detail, import_id=import_id)


def record_export(store: Store, *, now: datetime, detail: dict) -> Event:
    with store.tx():
        return _event(store, "export", now, detail)


def mark_seen(store: Store, person_id: str, *, now: datetime) -> None:
    """Move the person's seen_at to now; no event, because opening a profile is no decision."""
    with store.tx():
        (person,) = _canonical(store, [person_id])
        store.set_seen(person, now)


def _persons(event: Event) -> set[str]:
    """Every person the event names, the skipped ones included."""
    named = {event.person_id, event.other_person_id}
    if event.kind == "skip":
        named |= set(event.detail["prior_status"])
    return {p for p in named if p}


def _undo_add(store: Store, event: Event, now: datetime) -> None:
    for record, prior in event.detail["prior_merged"].items():
        store.set_merged_into(record, prior["merged_into"], _at(prior["merged_at"]))
    for p in event.detail["not_same"]:
        store.remove_not_same(event.person_id, p)
    store.set_list_status(event.person_id, event.detail["prior_status"])


def _undo_merge(store: Store, event: Event, now: datetime) -> None:
    for record in event.detail["merged"]:
        store.set_merged_into(record["id"], record["merged_into"], _at(record["merged_at"]))
    for a, b in event.detail["not_same_removed"]:
        store.add_not_same(a, b, now)
    store.set_list_status(event.person_id, event.detail["prior_status"])


def _undo_not_same(store: Store, event: Event, now: datetime) -> None:
    if event.detail["pair_added"]:
        store.remove_not_same(*event.detail["pair"])
    if separated := event.detail["separated"]:
        store.set_merged_into(separated["id"], separated["merged_into"], _at(separated["merged_at"]))


def _undo_contact(store: Store, event: Event, now: datetime) -> None:
    store.set_claim_rejected(event.detail["claim_id"], now)
    if event.detail["replaces"]:
        store.set_claim_rejected(event.detail["replaces"], _at(event.detail["prior_rejected_at"]))
    if event.detail["identifier_added"]:
        claim = store.get_claim(event.detail["claim_id"])
        store.remove_identifier(event.person_id, Identifier(scheme="email", value=claim.value.lower()))


def _undo_skip(store: Store, event: Event, now: datetime) -> None:
    for person, status in event.detail["prior_status"].items():
        store.set_list_status(person, status)


def _undo_remove(store: Store, event: Event, now: datetime) -> None:
    store.set_list_status(event.person_id, event.detail["prior_status"])


def _undo_reject(store: Store, event: Event, now: datetime) -> None:
    store.set_claim_rejected(event.claim_id, _at(event.detail["prior_rejected_at"]))


UNDO = {"add": _undo_add, "skip": _undo_skip, "remove": _undo_remove, "merge": _undo_merge,
        "not_same": _undo_not_same, "reject_claim": _undo_reject, "edit_contact": _undo_contact}


def _later(newest_first: list[Event], event: Event) -> bool:
    """Whether a person's events hold one written after the event; equal times are told apart by their order."""
    ids = [e.id for e in newest_first]
    if event.id in ids:
        return ids.index(event.id) > 0
    return any(e.at > event.at for e in newest_first)


def refusal(store: Store, event: Event) -> str | None:
    """Why FN will not undo the event, as one sentence for staff, or None when it can."""
    if event.kind == "undo":
        return "An undo cannot itself be undone."
    if event.kind not in UNDO:
        return "An import or an export cannot be undone."
    if any(_later(store.events_of(p), event) for p in _persons(event)):
        return LATER
    return None


def undo(store: Store, event_id: str, *, now: datetime) -> Event:
    """Reverse the event as its detail recorded it and write an undo event.

    Raises UndoRefused when a later event names one of its persons, or when it is an undo, an import or an export.
    """
    with store.tx():
        event = store.get_event(event_id)
        if event is None:
            raise UndoRefused("That decision no longer exists.")
        if why := refusal(store, event):
            raise UndoRefused(why)
        UNDO[event.kind](store, event, now)
        return _event(store, "undo", now, {}, person_id=event.person_id, other_person_id=event.other_person_id,
                      search_id=event.search_id, undoes=event.id)


def name_matches(store: Store, hit_person_ids: list[str]) -> list[str]:
    """Network people whose name has a hit's identity key, who are no hit's person and have a veto against none."""
    hits = _canonical(store, hit_person_ids)
    keys = {identity.key(p.name_key) for p in store.get_persons(hit_person_ids).values()}
    network = store.network_by_group_key()
    found = [p for key in sorted(keys) for p in network.get(key, []) if p not in hits]
    known = identity.load(store, [*hit_person_ids, *found], wide=False)
    return list(dict.fromkeys(p for p in found if not any(known.veto(p, h) for h in hit_person_ids)))


def possible_matches(store: Store, person_id: str) -> list[str]:
    """Other persons whose name has this person's identity key, minus those with a veto against it."""
    (person,) = _canonical(store, [person_id])
    key = identity.key(store.get_persons([person])[person].name_key)
    records = [p for p, _ in store.person_ids_by_group_key([key]).get(key, [])]
    canonical = store.canonical_ids(records)
    others = list(dict.fromkeys(canonical[p] for p in records if canonical[p] != person))
    known = identity.load(store, [person, *others], wide=False)
    return [p for p in others if not known.veto(person, p)]
