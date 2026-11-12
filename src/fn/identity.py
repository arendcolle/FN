"""Who is one person: the name key two records must share, the level of a pair, and the records a card reads."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from fn.contracts import Candidate, name_key

if TYPE_CHECKING:
    from fn.store import Store

Level = Literal["sure", "likely", "possible", "no"]
PARTICLES = frozenset({"van", "von", "de", "den", "der", "des", "du", "la", "le", "ten", "ter", "te", "di", "da", "del",
                       "dos", "el", "al"})
VETO_SCHEMES = ("orcid", "profile_url")
# An organization held by this many person records or more is too large to back a link.
BIG_ORG = 300
# A name key held by at most this many person records, web mentions left out, is rare.
RARE = 3
# Two rows of one seed list are one row only when their years are at most this far apart.
SEED_YEARS = 10


def parts(name: str) -> tuple[str, list[str], str]:
    """The first given name, the middle tokens and the joined surname of a name, folded like name_key.

    A last token of one letter goes when the name has three or more tokens. The surname runs from the first
    particle after the first token to the end, else it is the last token; a one-token name has no surname.
    """
    tokens = name_key(name).split()
    if len(tokens) >= 3 and len(tokens[-1]) == 1:
        tokens = tokens[:-1]
    if len(tokens) < 2:
        return (tokens[0] if tokens else ""), [], ""
    start = next((i for i in range(1, len(tokens) - 1) if tokens[i] in PARTICLES), len(tokens) - 1)
    return tokens[0], tokens[1:start], "".join(tokens[start:])


def key(name: str) -> str:
    """The key two names must share to be compared: the first given name and the joined surname."""
    first, _, surname = parts(name)
    return f"{first} {surname}".strip()


def _within(short: list[str], long: list[str]) -> bool:
    rest = iter(long)
    return all(c in rest for c in short)


def middle_clash(a: str, b: str) -> bool:
    """Whether both names have middle tokens and neither one's initials are a subsequence of the other's."""
    mine, theirs = ([t[0] for t in parts(n)[1]] for n in (a, b))
    return bool(mine and theirs) and not (_within(mine, theirs) or _within(theirs, mine))


@dataclass
class Known:
    """What the rules need about a set of records, loaded once; ids are records, facts are kept per person."""
    names: dict[str, str] = field(default_factory=dict)
    canonical: dict[str, str] = field(default_factory=dict)
    held: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    orgs: dict[str, set[str]] = field(default_factory=dict)
    org_sizes: dict[str, int] = field(default_factory=dict)
    key_counts: dict[str, int] = field(default_factory=dict)
    apart: set[frozenset[str]] = field(default_factory=set)
    same_key: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    network: set[str] = field(default_factory=set)

    def person(self, record: str) -> str:
        return self.canonical.get(record, record)

    def veto(self, a: str, b: str) -> str | None:
        """The word of the first veto between the two records, or None."""
        pa, pb = self.person(a), self.person(b)
        if frozenset((pa, pb)) in self.apart:
            return "not_same"
        for scheme in VETO_SCHEMES:
            mine, theirs = self.held.get(pa, {}).get(scheme), self.held.get(pb, {}).get(scheme)
            if mine and theirs and not mine & theirs:
                return scheme
        return "middle" if middle_clash(self.names.get(a, ""), self.names.get(b, "")) else None

    def _seed_rows(self, person: str) -> set[tuple[tuple[str, ...], str]]:
        """The person's seed row keys split into the key without its year and the year."""
        rows = [v.split("|") for v in self.held.get(person, {}).get("seed", set())]
        return {((*row[:2], *row[3:]), row[2]) for row in rows if len(row) > 2}

    def same_seed_row(self, a: str, b: str) -> bool:
        """Whether the two persons hold rows of one seed list that differ only in years at most SEED_YEARS apart."""
        theirs = self._seed_rows(b)
        return any(row == other and (year == when or year.isdigit() and when.isdigit()
                                     and abs(int(year) - int(when)) <= SEED_YEARS)
                   for row, year in self._seed_rows(a) for other, when in theirs)

    def far_seed_rows(self, a: str, b: str) -> bool:
        """Whether the two persons hold rows of one seed list whose years are more than SEED_YEARS apart."""
        theirs = self._seed_rows(b)
        return any(row == other and year.isdigit() and when.isdigit() and abs(int(year) - int(when)) > SEED_YEARS
                   for row, year in self._seed_rows(a) for other, when in theirs)

    def level(self, a: str, b: str) -> tuple[Level, str]:
        """How sure it is that the two records are one person, and the reason word."""
        pa, pb = self.person(a), self.person(b)
        if pa == pb:
            return "sure", "merged"
        if why := self.veto(a, b):
            return "no", why
        na, nb = self.names.get(a, ""), self.names.get(b, "")
        if not key(na) or key(na) != key(nb):
            return "no", "name"
        if min(len(parts(na)[0]), len(parts(nb)[0])) == 1:
            return "possible", "initial"
        # The list's own organization would otherwise link two of its rows decades apart.
        if self.far_seed_rows(pa, pb):
            return "possible", "name_only"
        shared = self.orgs.get(pa, set()) & self.orgs.get(pb, set())
        if any(self.org_sizes.get(o, 0) < BIG_ORG for o in shared):
            return "likely", "shared_org"
        if self.same_seed_row(pa, pb):
            return "likely", "same_seed_row"
        rare = self.key_counts.get(key(na), 0) <= RARE
        if shared and rare:
            return "likely", "rare_name_org"
        if rare and any(set(self.held.get(p, {})) == {"mention"} for p in (pa, pb)):
            return "likely", "rare_name_mention"
        return "possible", "name_only"

    def links(self, a: str, b: str) -> bool:
        """Whether the two records go on one card: sure, or likely when neither belongs to a network person."""
        level, _ = self.level(a, b)
        return level == "sure" or (level == "likely" and not {self.person(a), self.person(b)} & self.network)


def _web_only(idents: list) -> bool:
    return bool(idents) and all(i.scheme == "mention" for i in idents)


def load(store: "Store", record_ids: list[str], wide: bool = True) -> Known:
    """What the rules need about the records and every record merged with them, in a fixed number of queries.

    wide also loads the stored records that share each record's key, their facts, the counts per key and the
    sizes of the organizations, which level needs and veto does not.
    """
    ids = list(dict.fromkeys(record_ids))
    persons = store.get_persons(ids)
    names = {p: person.name_key for p, person in persons.items()}
    same_key = store.person_ids_by_group_key(list({key(n) for n in names.values()} - {""})) if wide else {}
    for found in same_key.values():
        names |= dict(found)
    canonical = store.canonical_ids(list(names))
    canonical |= store.merged_records(list(set(canonical.values())))
    every = list(dict.fromkeys([*names, *canonical, *canonical.values()]))
    persons |= store.get_persons([p for p in every if p not in persons])
    names |= {p: person.name_key for p, person in persons.items() if p not in names}
    pairs = store.not_same_pairs(every)
    canonical |= store.canonical_ids([p for pair in pairs for p in pair if p not in canonical])
    known = Known(names=names, canonical=canonical, same_key=same_key,
                  network={p for p, person in persons.items() if person.list_status == "in_list"},
                  apart={frozenset(canonical.get(p, p) for p in pair) for pair in pairs})
    idents = store.identifiers_of(every)
    for record, found in idents.items():
        for i in found:
            known.held.setdefault(known.person(record), {}).setdefault(i.scheme, set()).add(i.value)
    if wide:
        for record, found in store.org_ids_of(every).items():
            known.orgs.setdefault(known.person(record), set()).update(found)
        known.org_sizes = store.org_sizes(list({o for found in known.orgs.values() for o in found}))
        known.key_counts = {k: sum(not _web_only(idents.get(p, [])) for p, _ in found) for k, found in same_key.items()}
    return known


def same_person(store: "Store", a: str, b: str) -> tuple[Level, str]:
    """How sure it is that records a and b are one person, and the reason word."""
    return load(store, [a, b]).level(a, b)


def on_card(store: "Store", candidate: Candidate) -> list[str]:
    """The records a card reads: its card records minus those declared not the same as the first.

    A candidate stored without card records reads its hit records, else its first record.
    """
    if not candidate.card_person_ids:
        return candidate.hit_person_ids or candidate.person_ids[:1]
    first, *rest = candidate.card_person_ids
    pairs = store.not_same_pairs(candidate.card_person_ids)
    if not pairs:
        return candidate.card_person_ids
    canonical = store.canonical_ids([*candidate.card_person_ids, *(p for pair in pairs for p in pair)])
    apart = {frozenset(canonical.get(p, p) for p in pair) for pair in pairs}
    mine = canonical.get(first, first)
    return [first, *(p for p in rest if frozenset((mine, canonical.get(p, p))) not in apart)]
