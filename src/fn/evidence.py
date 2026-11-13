"""What the records on a card show for a question: topic words, institution, Belgian tie, place and sources."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from fn import geo, orgs, parse, rank
from fn.contracts import Chip, Claim, Identifier, Org, Question, RoleFit, TieGrade, name_key

RECENT_YEARS = 5
EMPLOYER = ("works_at", "affiliated_with")
OPENALEX_SCHEMES = frozenset({"openalex", "orcid"})
DATE = re.compile(r"[0-9]{4}(-[0-9]{2}){0,2}")
# Words of a claim that place it in Belgium, folded like name_key.
BELGIAN_TEXT = re.compile(r"\b(belgi\w*|belge\w*|flemish|flanders|vlaams\w*|vlaanderen|antwerp\w*|ghent|gent|leuven|"
                          r"louvain|brussel\w*|bruxelles|liege|hasselt|mechelen|bruges|brugge|kortrijk|namur|walloni\w*)\b")
# Seed lists whose rows are curated by the list's own body; every other list gives a medium tie.
STRONG_LISTS = frozenset({"baef", "francqui", "fayat", "consuls", "climate"})
STRONG_MARKERS = frozenset(f"seed:{name}" for name in STRONG_LISTS)
ACADEMIC = ("professor", "hoogleraar", "docent", "lecturer", "postdoc", "phd student", "phd candidate", "phd researcher",
            "doctoral student", "doctoral candidate", "doctoral researcher", "doctoraatsstudent", "doctorandus", "doctorant",
            "professeur", "maitre de conferences", "charge de cours", "research fellow")
RESEARCHER = ("researcher", "scientist", "research scientist", "onderzoeker", "wetenschapper", "chercheur", "scientifique")
UNIVERSITY = ("university", "universiteit", "universite", "universidad", "college", "hogeschool", "polytechnic",
              "institute of technology", "school of medicine", "medical school")
GRADE_ORDER: tuple[TieGrade, ...] = ("strong", "medium", "weak")
Basis = Literal["stated", "employer"]
Fit = Literal["inside", "outside", "unknown"]


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float
    text: str
    country: str | None
    basis: Basis
    claim_id: str
    year: int | None


@dataclass(frozen=True)
class Topic:
    match: bool = False
    words: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    related: bool = False


@dataclass(frozen=True)
class Institution:
    match: bool = False
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tie:
    kinds: dict[str, tuple[str, ...]] = field(default_factory=dict)
    claim_ids: tuple[str, ...] = ()
    years: int = 0
    last: int | None = None
    grade: TieGrade = "none"


@dataclass(frozen=True)
class Role:
    fit: RoleFit = "unknown"
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Where:
    fit: Fit = "unknown"
    km: float | None = None
    nearest: Place | None = None
    countries: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Evidence:
    topic: Topic = field(default_factory=Topic)
    institution: Institution = field(default_factory=Institution)
    belgian: Tie = field(default_factory=Tie)
    role: Role = field(default_factory=Role)
    place: Where = field(default_factory=Where)
    sources: int = 0
    only_openalex: bool = False


def recent(stamp: str | None, today: date) -> bool:
    """Whether a YYYY, YYYY-MM or YYYY-MM-DD date reaches into the RECENT_YEARS years before today."""
    if not stamp or not DATE.fullmatch(stamp):
        return False
    return stamp >= f"{today.year - RECENT_YEARS:04d}-{today:%m-%d}"[:len(stamp)]


def places(claims: list[Claim], facts: dict[str, Org], today: date, names: geo.Names | None = None) -> list[Place]:
    """The stated places of a person's claims, then the cities of their recent employers, in claim order.

    A stated place is a located location claim of any date that is not a birthplace or an origin; its country comes from names.
    An employer's city needs a works_at or affiliated_with claim whose valid_to, else claim_date, is recent.
    """
    found = [Place(c.lat, c.lon, c.value, geo.country_at(names, c.lat, c.lon) if names else None, "stated", c.id,
                   rank.year(c.valid_to or c.claim_date))
             for c in claims if c.kind == "location" and c.relation not in ("born_in", "origin") and c.lat is not None and c.lon is not None]
    for c in claims:
        org = facts.get(c.org_id or "")
        stamp = c.valid_to or c.claim_date
        if c.relation in EMPLOYER and org and org.city and org.lat is not None and org.lon is not None and recent(stamp, today):
            found.append(Place(org.lat, org.lon, org.city, org.country_code, "employer", c.id, rank.year(stamp)))
    return found


def card_of(identifiers: dict[str, list[Identifier]], records: list[str]) -> dict[str, frozenset[str]]:
    """Each record's identifier schemes, plus seed:<list> for each seed identifier, the list being its value before the first |."""
    return {p: frozenset(s for i in identifiers.get(p, []) for s in
                         ((i.scheme, f"seed:{i.value.split('|')[0]}") if i.scheme == "seed" else (i.scheme,)))
            for p in records}


def mention_only(card: dict[str, frozenset[str]], claim: Claim) -> bool:
    """Whether the claim belongs to a web person record, whose role may be a page title."""
    return card.get(claim.person_id) == frozenset({"mention"})


def usable_role(card: dict[str, frozenset[str]], claim: Claim) -> bool:
    """A role claim; one of a web person counts only when its value stands in its quote, not when it is the page title."""
    return claim.kind == "role" and (not mention_only(card, claim) or name_key(claim.value) in name_key(claim.quote))


def match_text(card: dict[str, frozenset[str]], claim: Claim) -> str:
    """The text of a claim a topic may match: an organization's name is taken out of an affiliation (one with a relation),
    and a web person claim counts only as a topic claim or as a role the quote states."""
    if mention_only(card, claim):
        if claim.kind == "topic":
            return f"{claim.value} {claim.quote}"
        return claim.value if usable_role(card, claim) else ""
    if claim.kind == "affiliation" and claim.relation:
        return name_key(claim.quote).replace(name_key(claim.value), " ")
    return f"{claim.value} {claim.quote}"


def topic(claims: list[Claim], chips: list[Chip], card: dict[str, frozenset[str]]) -> Topic:
    """The chip words found in the claims, the claims holding them with the most words first, and whether one claim
    holds every word of a chip.

    Without such a claim a related entry of a chip, held whole by one claim, matches and sets related.
    """
    words = list(dict.fromkeys(w for chip in chips for w in parse.chip_words(chip.text)))
    held = [(c, parse.words_in(words, f"{c.value} {c.quote}")) for c in claims]
    held = sorted((h for h in held if h[1]), key=lambda h: -len(h[1]))
    found = [w for w in words if any(w in ws for _, ws in held)]
    texts = {c.id: match_text(card, c) for c in claims}
    ids = [c.id for c, _ in held]
    if parse.topic_match([chip.text for chip in chips], [texts[c.id] for c, _ in held]):
        return Topic(match=True, words=tuple(found), claim_ids=tuple(ids))
    related = [c.id for c in claims if parse.topic_match([r for chip in chips for r in chip.related], [texts[c.id]])]
    return Topic(match=bool(related), words=tuple(found), claim_ids=tuple(dict.fromkeys([*ids, *related])),
                 related=bool(related))


def academic(value: str) -> bool:
    """Whether a role value reads as an academic research job; a researcher counts only beside a university word."""
    def has(phrases: tuple[str, ...]) -> bool:
        return any(len(parse.words_in(w := name_key(p).split(), value)) == len(w) for p in phrases)
    return has(ACADEMIC) or (has(RESEARCHER) and has(UNIVERSITY))


def role(claims: list[Claim], card: dict[str, frozenset[str]], question: Question) -> Role:
    """met when a role claim holds the words of a role chip or one of its related entries; fails when every role chip
    is not a research role, none is met, and a role claim reads as an academic job or an OpenAlex-only card has none."""
    chips = question.chips.roles
    if not chips:
        return Role()
    own = [c for c in claims if usable_role(card, c)]
    met = [c.id for c in own if any(parse.topic_match([chip.text, *chip.related], [c.value]) for chip in chips)]
    if met:
        return Role("met", tuple(met))
    if any(chip.research is not False for chip in chips):
        return Role()
    jobs = [c.id for c in own if academic(c.value)]
    return Role("fails", tuple(jobs)) if jobs or (not own and only_openalex(card)) else Role()


def only_openalex(card: dict[str, frozenset[str]]) -> bool:
    """Whether every record on the card holds only OpenAlex or ORCID identifiers."""
    return bool(card) and all(schemes <= OPENALEX_SCHEMES for schemes in card.values())


def institution(claims: list[Claim], question: Question) -> Institution:
    """The claims at the organization of an institution chip."""
    wanted = {orgs.org_id(chip.text) or chip.ref for chip in question.chips.institutions} - {None}
    ids = tuple(c.id for c in claims if c.org_id in wanted)
    return Institution(match=bool(ids), claim_ids=ids)


def tie(card: dict[str, frozenset[str]], claims: list[Claim], facts: dict[str, Org], found: list[Place]) -> Tie:
    """Each kind of Belgian tie on the card with the claims that show it, in a fixed order, the best grade and the
    Belgian years.

    A seed-list record is a tie even when it holds no claim; it is strong when its list is in STRONG_LISTS or the card
    names no list. claim_ids runs from the strong kinds to the weak ones.
    """
    seeds = [schemes for schemes in card.values() if "seed" in schemes]
    seed_strong = any(not any(s.startswith("seed:") for s in schemes) or schemes & STRONG_MARKERS for schemes in seeds)
    org_ids, units = rank.counted(claims, facts)
    belgian = {c.id for c, _ in orgs.belgian_claims(claims, facts)}
    years = sorted(int(u) for u in units if u != rank.UNDATED)
    deep = len(units) >= 3 and bool(years) and years[-1] >= 2016

    def says(c: Claim) -> bool:
        return bool(BELGIAN_TEXT.search(name_key(c.value)))

    shown = {
        "seed_list": ([c.id for c in claims if "seed" in card.get(c.person_id, frozenset())], "strong" if seed_strong else "medium"),
        "belgian_degree": ([c.id for c in claims if c.relation == "studied_at" and (c.id in belgian or says(c))], "strong"),
        "born_in_belgium": ([c.id for c in claims if c.relation == "born_in" and says(c)], "strong"),
        "belgian_origin": ([c.id for c in claims if c.relation == "origin" and says(c)], "strong"),
        "belgian_org": (org_ids, "strong" if deep else "medium"),
        "belgian_place": ([p.claim_id for p in found if p.country == "BE"], "medium"),
        "belgian_text": ([c.id for c in claims if BELGIAN_TEXT.search(name_key(f"{c.value} {c.quote}"))], "weak"),
    }
    kinds = {k: v for k, v in shown.items() if v[0] or (k == "seed_list" and seeds)}
    grades = {grade for _, grade in kinds.values()}
    return Tie(kinds={k: tuple(ids) for k, (ids, _) in kinds.items()},
               claim_ids=tuple(dict.fromkeys(i for grade in GRADE_ORDER for ids, g in kinds.values() if g == grade for i in ids)),
               years=len(units), last=years[-1] if years else None,
               grade=next((g for g in GRADE_ORDER if g in grades), "none"))


def where(found: list[Place], question: Question) -> Where:
    """inside when a place lies within the area's radius, outside when there are places and none does, else unknown.

    A stated place says where the person is; an employer's city only counts when no place is stated. The countries
    are those of every place.
    """
    countries = frozenset(p.country for p in found if p.country)
    area = question.area
    found = [p for p in found if p.basis == "stated"] or found
    if not found or area is None:
        return Where(countries=countries)
    km, nearest = min(((geo.distance_km(area.lat, area.lon, p.lat, p.lon), p) for p in found), key=lambda d: d[0])
    return Where(fit="inside" if km <= area.radius_km else "outside", km=km, nearest=nearest, countries=countries)


def of(card: dict[str, frozenset[str]], claims: list[Claim], facts: dict[str, Org], question: Question, today: date,
       names: geo.Names | None = None) -> Evidence:
    """What the claims of the records on a card show for the question; card maps each record to its identifier schemes.

    Claims of records not on the card are ignored. names locates the country of a stated place.
    """
    own = [c for c in claims if c.person_id in card]
    found = places(own, facts, today, names)
    return Evidence(
        topic=topic(own, question.chips.topics, card), institution=institution(own, question),
        belgian=tie(card, own, facts, found), role=role(own, card, question), place=where(found, question),
        sources=len({c.source_id for c in own}), only_openalex=only_openalex(card),
    )
