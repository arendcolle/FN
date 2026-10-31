"""Place chip to coordinates and a radius, from the GeoNames cities15000 dump fetched through the step's HTTP client."""
import io
import math
import zipfile
from typing import NamedTuple
from weakref import WeakKeyDictionary

from fn.contracts import GeoArea, HttpClient, name_key

CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
CITIES_FILE = "cities15000.txt"
METRO_RADIUS_KM = 100.0
MAX_WORDS = 4
# Words that join or qualify places in a chip and must never be read as a city name.
STOPWORDS = {"and", "en", "et", "und", "or", "of", "the", "de", "near", "in", "around", "area", "region", "regio",
             "greater", "metro", "metropolitan", "city", "county", "state", "us", "usa"}


class City(NamedTuple):
    label: str
    lat: float
    lon: float
    population: int


_loaded: WeakKeyDictionary[HttpClient, dict[str, City]] = WeakKeyDictionary()


def index(text: str) -> dict[str, City]:
    """Every folded name, ASCII name and ASCII alternate name of the cities15000 rows, to one city.

    A city's own name beats an alternate name, so Menlo Park is not Edison; then the larger population wins.
    """
    best: dict[str, tuple[bool, int]] = {}
    found: dict[str, City] = {}
    for line in text.splitlines():
        cols = line.split("\t")
        city = City(f"{cols[1]}, {cols[8]}", float(cols[4]), float(cols[5]), int(cols[14] or 0))
        own = {name_key(cols[1]), name_key(cols[2])}
        for key in own | {name_key(a) for a in cols[3].split(",") if a.isascii()}:
            if not key or key in STOPWORDS or len(key.split()) > MAX_WORDS:
                continue
            rank = (key in own, city.population)
            if rank > best.get(key, (False, -1)):
                best[key], found[key] = rank, city
    return found


def cities(http: HttpClient) -> dict[str, City]:
    """The city index, fetched and unzipped once per HTTP client."""
    if http not in _loaded:
        with zipfile.ZipFile(io.BytesIO(http.get(CITIES_URL).content)) as archive:
            _loaded[http] = index(archive.read(CITIES_FILE).decode("utf-8"))
    return _loaded[http]


def locate(place: str, names: dict[str, City]) -> GeoArea | None:
    """The most populous city named in place, longest names first, with the metro radius; None when none is named."""
    words = name_key(place).split()
    matched: list[City] = []
    i = 0
    while i < len(words):
        for size in range(min(MAX_WORDS, len(words) - i), 0, -1):
            city = names.get(" ".join(words[i:i + size]))
            if city:
                matched.append(city)
                i += size
                break
        else:
            i += 1
    if not matched:
        return None
    best = max(matched, key=lambda c: c.population)
    return GeoArea(place=place, city=best.label, lat=best.lat, lon=best.lon, radius_km=METRO_RADIUS_KM)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance by the haversine formula on a 6371 km sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))
