"""Place chip to coordinates and a radius, from the GeoNames cities15000 dump fetched through the step's HTTP client."""
import csv
import io
import logging
import math
import zipfile
from collections.abc import Callable
from functools import cache
from itertools import product
from typing import NamedTuple
from weakref import WeakKeyDictionary

from fn.config import ROOT
from fn.contracts import GeoArea, HttpClient, Place, name_key
from fn.net import HttpError

CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
CITIES_FILE = "cities15000.txt"
ALIASES = ROOT / "data" / "place_aliases.csv"
METRO_RADIUS_KM = 100.0
# The place kinds that name a metro area to locate; abroad and anywhere_us do not.
METRO_KINDS = (None, "metro")
MAX_WORDS = 4
SHORT_FORMS = {"us", "uk"}
# Words that join or qualify places in a chip and must never be read as a city name.
STOPWORDS = {"and", "en", "et", "und", "or", "of", "the", "de", "near", "in", "around", "area", "region", "regio",
             "greater", "metro", "metropolitan", "city", "county", "state", "us", "usa"}


class City(NamedTuple):
    label: str
    lat: float
    lon: float
    population: int
    country: str = ""
    state: str = ""


Names = dict[str, list[City]]
Region = tuple[str, str]

_loaded: WeakKeyDictionary[HttpClient, Names] = WeakKeyDictionary()


def index(text: str) -> Names:
    """Every folded name, ASCII name and ASCII alternate name of the cities15000 rows, to its cities, best first.

    A city's own name beats an alternate name, so Menlo Park is not Edison; then the larger population wins.
    """
    ranked: dict[str, list[tuple[bool, int, City]]] = {}
    for line in text.splitlines():
        cols = line.split("\t")
        city = City(f"{cols[1]}, {cols[8]}", float(cols[4]), float(cols[5]), int(cols[14] or 0), cols[8], cols[10])
        own = {name_key(cols[1]), name_key(cols[2])}
        for key in own | {name_key(a) for a in cols[3].split(",") if a.isascii()}:
            if key and key not in STOPWORDS and len(key.split()) <= MAX_WORDS:
                ranked.setdefault(key, []).append((key in own, city.population, city))
    return {key: [c for *_, c in sorted(rows, key=lambda r: r[:2], reverse=True)] for key, rows in ranked.items()}


def from_zip(data: bytes) -> Names:
    """The city index of a downloaded cities15000.zip."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return index(archive.read(CITIES_FILE).decode("utf-8"))


def cities(http: HttpClient) -> Names:
    """The city index, fetched and unzipped once per HTTP client."""
    if http not in _loaded:
        _loaded[http] = from_zip(http.get(CITIES_URL).content)
    return _loaded[http]


@cache
def aliases() -> dict[str, dict[str, str]]:
    """The rows of data/place_aliases.csv as kind -> folded alias -> target; a repeated alias of a kind raises."""
    table: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(ALIASES.read_text(encoding="utf-8").splitlines()):
        kind, key = table.setdefault(row["kind"], {}), name_key(row["alias"])
        if key in kind:
            raise ValueError(f"place_aliases.csv: {row['kind']} alias {row['alias']!r} is listed twice")
        kind[key] = row["target"]
    return table


def regions_of(key: str, free_text: bool = False) -> list[Region]:
    """The ("state", code) and ("country", code) a folded name or code stands for, state first.

    Free text skips two-letter codes such as "in" or "or", except us and uk.
    """
    if free_text and len(key) < 3 and key not in SHORT_FORMS:
        return []
    table = aliases()
    return [(kind, table[kind][key]) for kind in ("state", "country") if key in table.get(kind, {})]


def scan[T](words: list[str], lookup: Callable[[str], T | None],
            taken: frozenset[int] = frozenset()) -> list[tuple[T, int, int]]:
    """The longest names found left to right in words, as (value, first, end); words in taken are skipped."""
    found, i = [], 0
    while i < len(words):
        for size in range(min(MAX_WORDS, len(words) - i), 0, -1):
            value = None if taken.intersection(range(i, i + size)) else lookup(" ".join(words[i:i + size]))
            if value:
                found.append((value, i, i + size))
                i += size
                break
        else:
            i += 1
    return found


def pick(groups: list[list[City]], regions: set[Region], strict: bool) -> City | None:
    """The most populous of the groups' best cities in the regions' states and countries.

    A strict pick with no such city is None; a loose one falls back to the cities without the regions.
    """
    states = {code for kind, code in regions if kind == "state"}
    countries = {code for kind, code in regions if kind == "country"}

    def fits(city: City) -> bool:
        in_state = not states or (city.country == "US" and city.state in states)
        return in_state and (not countries or city.country in countries)

    best = [next((c for c in group if fits(c)), None) for group in groups]
    found = [c for c in best if c] or ([] if strict else [g[0] for g in groups])
    return max(found, key=lambda c: c.population, default=None)


def resolve(parts: list[str], names: Names) -> City | None:
    """The city for folded comma parts: the first names the city, the later ones qualify it with a state or country.

    A later part that is both a state and a country (DE, CA) matches either. Without a later part the other words
    of the first are the qualifiers; city names are scanned after them, and a miss rescans for the city alone.
    """
    head, *rest = parts
    words = head.split()
    if rest:
        hits = scan(words, names.get)
        options = [regions_of(p) or [None] for p in rest]
        for combo in product(*options):
            found = pick([h[0] for h in hits], {r for r in combo if r}, strict=True) if hits else None
            if found:
                return found
        return None
    spans = scan(words, lambda key: next(iter(regions_of(key, True)), None))
    taken = frozenset(i for _, a, b in spans for i in range(a, b))
    hits = scan(words, names.get, taken)
    if hits:
        return pick([h[0] for h in hits], {s[0] for s in spans}, strict=False)
    hits = scan(words, names.get)
    return pick([h[0] for h in hits], set(), strict=False) if hits else None


def area_of(place: str, city: City | None) -> GeoArea | None:
    return city and GeoArea(place=place, city=city.label, lat=city.lat, lon=city.lon, radius_km=METRO_RADIUS_KM)


def locate(place: str, names: Names) -> GeoArea | None:
    """The metro area a place text names, with the metro radius; None when it names no city.

    A metro alias wins. Else the part before a comma names the city and later state or country parts must match
    it; with no comma the most populous city named in the words wins, narrowed by a state or country among them.
    """
    parts = [name_key(p) for p in place.split(",")]
    metros = scan(" ".join(parts).split(), aliases().get("metro", {}).get)
    if metros:
        target = max(metros, key=lambda m: m[2] - m[1])[0]
        return area_of(place, resolve([name_key(p) for p in target.split(",")], names))
    return area_of(place, resolve(parts, names))


def locate_city(city: str, state: str | None, country: str | None, names: Names) -> GeoArea | None:
    """The metro area of a city given with its state and country apart, each a name or a code; None when no match.

    A state or country that is not known is ignored, one that is known must match the city.
    """
    hits = scan(name_key(city).split(), names.get)
    regions = {(kind, code) for kind, q in (("state", state), ("country", country)) if q
               if (code := aliases().get(kind, {}).get(name_key(q)))}
    place = ", ".join(p for p in (city, state, country) if p)
    return area_of(place, pick([h[0] for h in hits], regions, strict=True) if hits else None)


def area(http: HttpClient, place: Place | None) -> GeoArea | None:
    """The metro area GeoNames locates for the place chip.

    None for no place, a kind other than metro (the dump is not fetched then), or a place that names no city.
    """
    if place is None or place.kind not in METRO_KINDS:
        return None
    return locate(place.text, cities(http))


def coordinates(http: HttpClient | None, place: str, log: logging.Logger) -> tuple[float, float] | None:
    """The coordinates of the city a place text names; None, with one log line naming the text, when there are none.

    None as well without an HTTP client or when the city dump cannot be fetched.
    """
    if http is None:
        return None
    try:
        found = locate(place, cities(http))
    except HttpError as exc:
        log.warning("no coordinates for %r: %s", place, exc)
        return None
    if found is None:
        log.info("no coordinates for %r: geo names no city", place)
    return (found.lat, found.lon) if found else None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance by the haversine formula on a 6371 km sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))
