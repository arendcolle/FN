"""What the records on a card show for a question: topic words, institution, Belgian tie, place and sources."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from fn import geo, orgs, parse, rank
from fn.contracts import Claim, Org, Question, name_key

RECENT_YEARS = 5
EMPLOYER = ("works_at", "affiliated_with")
OPENALEX_SCHEMES = frozenset({"openalex", "orcid"})
DATE = re.compile(r"[0-9]{4}(-[0-9]{2}){0,2}")
# Words of a claim that place it in Belgium, folded like name_key.
BELGIAN_TEXT = re.compile(r"\b(belgi\w*|belge\w*|flemish|flanders|vlaams\w*|vlaanderen|antwerp\w*|ghent|gent|leuven|"
                          r"louvain|brussel\w*|bruxelles|liege|hasselt|mechelen|bruges|brugge|kortrijk|namur|walloni\w*)\b")
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

    A stated place is a located location claim of any date that is not a birthplace; its country comes from names.
    An employer's city needs a works_at or affiliated_with claim whose valid_to, else claim_date, is recent.
    """
    found = [Place(c.lat, c.lon, c.value, geo.country_at(names, c.lat, c.lon) if names else None, "stated", c.id,
                   rank.year(c.valid_to or c.claim_date))
             for c in claims if c.kind == "location" and c.relation != "born_in" and c.lat is not None and c.lon is not None]
    for c in claims:
        org = facts.get(c.org_id or "")
        stamp = c.valid_to or c.claim_date
        if c.relation in EMPLOYER and org and org.city and org.lat is not None and org.lon is not None and recent(stamp, today):
            found.append(Place(org.lat, org.lon, org.city, org.country_code, "employer", c.id, rank.year(stamp)))
    return found


def topic(claims: list[Claim], chips: list[str]) -> Topic:
    """The chip words found in the claims, the claims holding them with the most words first, and whether one claim
    holds every word of a chip."""
    words = list(dict.fromkeys(w for chip in chips for w in parse.chip_words(chip)))
    held = [(c, parse.words_in(words, f"{c.value} {c.quote}")) for c in claims]
    held = sorted((h for h in held if h[1]), key=lambda h: -len(h[1]))
    found = [w for w in words if any(w in ws for _, ws in held)]
    match = parse.topic_match(chips, [f"{c.value} {c.quote}" for c, _ in held])
    return Topic(match=match, words=tuple(found), claim_ids=tuple(c.id for c, _ in held))


def institution(claims: list[Claim], question: Question) -> Institution:
    """The claims at the organization of an institution chip."""
    wanted = {orgs.org_id(chip.text) or chip.ref for chip in question.chips.institutions} - {None}
    ids = tuple(c.id for c in claims if c.org_id in wanted)
    return Institution(match=bool(ids), claim_ids=ids)


def tie(card: dict[str, frozenset[str]], claims: list[Claim], facts: dict[str, Org], found: list[Place],
        inst: Institution) -> Tie:
    """Each kind of Belgian tie on the card with the claims that show it, in a fixed order, and the Belgian years.

    A seed-list record is a tie even when it holds no claim.
    """
    seeded = any("seed" in schemes for schemes in card.values())
    org_ids, units = rank.counted(claims, facts)
    shown = {
        "seed_list": [c.id for c in claims if "seed" in card.get(c.person_id, frozenset())],
        "belgian_org": org_ids,
        "belgian_text": [c.id for c in claims if BELGIAN_TEXT.search(name_key(f"{c.value} {c.quote}"))],
        "belgian_place": [p.claim_id for p in found if p.country == "BE"],
        "institution": list(inst.claim_ids),
    }
    years = sorted(int(u) for u in units if u != rank.UNDATED)
    return Tie(kinds={k: tuple(ids) for k, ids in shown.items() if ids or (k == "seed_list" and seeded)},
               claim_ids=tuple(dict.fromkeys(i for ids in shown.values() for i in ids)),
               years=len(units), last=years[-1] if years else None)


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
    inst = institution(own, question)
    return Evidence(
        topic=topic(own, [chip.text for chip in question.chips.topics]), institution=inst,
        belgian=tie(card, own, facts, found, inst), place=where(found, question), sources=len({c.source_id for c in own}),
        only_openalex=bool(card) and all(schemes <= OPENALEX_SCHEMES for schemes in card.values()),
    )
