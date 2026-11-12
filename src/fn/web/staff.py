"""The staff router: the Ask page, the results page with its map data and the source page."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from fn.contracts import Claim, Search, Source
from fn.present import cut, results, sources_read
from fn.store import Store
from fn.web.html import Safe, h, page
from fn.web.parts import notice, person_card, recent_meta, search_box
from fn.web.requests import form_of, store_of, worker_of
from fn.worker import now

MAX_QUESTION = 1000
SECTIONS = {"network": "In your network", "new": "New"}

router = APIRouter()


def home_page(searches: list[Search], counts: dict[str, int], message: str | None = None, question: str = "") -> str:
    """The Ask page: the question box, then the recent searches with their state; counts holds people per search."""
    today = now().astimezone().date()
    rows = [h.li(h.a(cut(s.question, 200), href=f"/searches/{s.id}", class_="text-body"),
                 recent_meta(s, counts.get(s.id, 0), today)) for s in searches]
    recent = h.section(h.h2("Recent searches", class_="fn-section text-label"), h.ul(rows, class_="fn-recent"),
                       class_="fn-page") if rows else None
    return page("Searches", search_box(question, message), recent, current="search")


def person_cards(store: Store, search: Search) -> tuple[list[Safe], bool]:
    """One card per candidate under its section heading, and whether any of them has a place on the map."""
    found = results(store, search, now().astimezone().date())
    sections = [[h.h2(title, " ", h.span(f"{len(group):,}"), class_="fn-section text-label"), [person_card(v) for v in group]]
                for section, title in SECTIONS.items() if (group := getattr(found, section))]
    return sections, any(v.lat is not None for v in found.network + found.new)


def search_page(store: Store, search: Search, view: str = "list") -> str:
    """The results page: the question box, then the people's cards beside a map of where they are.

    A running search shows the status line, and a stopped or empty one a notice with the map hidden. view picks
    the list or the map on narrow screens; each has its own URL, so the refresh while a search runs keeps it.
    """
    active, stopped = search.status in ("queued", "running"), search.status in ("failed", "interrupted")
    found, placed = ([], False) if stopped else person_cards(store, search)
    if active:
        top = h.p(h.span("Searching…"), h.span(class_="fn-status__bar"), class_="fn-status text-strong")
    else:
        top = None if found else notice(search, sources_read(store, search))
    views = [h.a(name.title(), href=f"/searches/{search.id}" + ("/map" if name == "map" else ""), data_view=name,
                 aria_current="page" if name == view else None) for name in ("list", "map")]
    results = h.div(
        h.nav(views, class_="fn-switch text-switch", aria_label="View"),
        h.div(top, found, class_="fn-results__list"),
        h.div(id="map", class_="fn-map", role="region", aria_label="Map of the people in this search",
              data_geo=f"/api/searches/{search.id}/geo"),
        class_="fn-results" if placed else "fn-results fn-results--no-map", data_view=view,
    )
    return page(
        "Search", search_box(search.question), results,
        refresh=2 if active else None, current="search", body_class="fn-app",
        extra_head=[h.link(rel="stylesheet", href="/static/maplibre-gl.css"),
                    h.script(src="/static/maplibre-gl.js", defer=True), h.script(src="/static/map.js", defer=True)],
    )


def geo_features(store: Store, search: Search) -> dict:
    """GeoJSON of the search's people: one point per card whose person has a place with coordinates."""
    found = results(store, search, now().astimezone().date())
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [view.lon, view.lat]},
        "properties": {"id": view.person_id, "name": view.name, "employer": view.employer, "place": view.place,
                       "section": section},
    } for section in SECTIONS for view in getattr(found, section) if view.lat is not None and view.lon is not None]
    return {"type": "FeatureCollection", "features": features}


def source_page(source: Source, claim: Claim | None) -> str:
    text = source.text
    body = [text[:claim.quote_start], h.mark(claim.quote, id="quote"), text[claim.quote_end:]] if claim else text
    return page(
        "Source",
        h.div(
            h.h1(source.title or source.url, class_="fn-source__title text-title"),
            h.p(h.a(source.url, href=source.url), class_="fn-source__url text-small"),
            h.pre(body, class_="fn-source__text text-body"),
            class_="fn-source",
        ),
    )


def recent(request: Request, message: str | None = None, question: str = "") -> str:
    store = store_of(request)
    searches = store.list_searches(50)
    return home_page(searches, store.count_candidates([s.id for s in searches]), message, question)


@router.get("/")
async def home(request: Request) -> HTMLResponse:
    return HTMLResponse(recent(request))


@router.post("/searches")
async def create(request: Request) -> Response:
    question = (await form_of(request)).get("question", [""])[0].strip()
    message = None
    if not question:
        message = "Type a question"
    elif len(question) > MAX_QUESTION:
        message = f"Questions are limited to {MAX_QUESTION:,} characters; this one has {len(question):,}."
    if message:
        return HTMLResponse(recent(request, message, question), 400)
    worker = worker_of(request)
    found = worker.create_search(question)
    worker.submit(found.id)
    return RedirectResponse(f"/searches/{found.id}", 303)


def get_search(request: Request, search_id: str) -> Search:
    found = store_of(request).get_search(search_id)
    if found is None:
        raise HTTPException(404, "No such search")
    return found


@router.get("/searches/{search_id}")
async def show(request: Request, search_id: str) -> HTMLResponse:
    return HTMLResponse(search_page(store_of(request), get_search(request, search_id)))


@router.get("/searches/{search_id}/map")
async def show_map(request: Request, search_id: str) -> HTMLResponse:
    return HTMLResponse(search_page(store_of(request), get_search(request, search_id), "map"))


@router.get("/api/searches/{search_id}/geo")
async def geo_json(request: Request, search_id: str) -> JSONResponse:
    return JSONResponse(geo_features(store_of(request), get_search(request, search_id)))


def get_source(request: Request, source_id: str, claim: str) -> tuple[Source, Claim | None]:
    """The source and, when claim is given, that claim; 404 when either is missing or the claim quotes another source."""
    store = store_of(request)
    source = store.get_sources([source_id]).get(source_id)
    marked = store.get_claim(claim) if claim else None
    if source is None or (claim and (marked is None or marked.source_id != source_id)):
        raise HTTPException(404, "No such source or claim")
    return source, marked


@router.get("/sources/{source_id}")
async def show_source(request: Request, source_id: str, claim: str = "") -> HTMLResponse:
    return HTMLResponse(source_page(*get_source(request, source_id, claim)))

