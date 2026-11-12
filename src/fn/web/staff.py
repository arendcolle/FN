"""The staff router: Home, All searches, the results page, the Network page with their map data and the source page."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from fn.contracts import Claim, NetworkFilter, Search, Source
from fn.present import geo, network_view, results, sources_read
from fn.store import Store
from fn.web.html import Safe, h, page
from fn.web.parts import (
    NETWORK_STEP,
    empty_network,
    filter_bar,
    is_filtered,
    network_href,
    network_row,
    nobody_matches,
    notice,
    person_card,
    recent_list,
    search_box,
    show_more,
)
from fn.web.requests import form_of, store_of, worker_of
from fn.worker import now

MAX_QUESTION = 1000
SECTIONS = {"network": "In your network", "new": "New"}

router = APIRouter()


MAP_HEAD = [h.link(rel="stylesheet", href="/static/maplibre-gl.css"), h.script(src="/static/maplibre-gl.js", defer=True),
            h.script(src="/static/map.js", defer=True)]


def network_block(store: Store, flt: NetworkFilter, limit: int, view: str, home: bool) -> tuple[Safe, dict]:
    """The network list beside its map, as on the Network page and Home, and the facts the request log keeps.

    An empty network shows its notice, and a filter that matches nobody 'Nobody matches'; both hide the map.
    """
    found = network_view(store, flt, limit, now().astimezone().date())
    filtered = is_filtered(flt)
    everyone = store.list_network(NetworkFilter(), 0)[1] if filtered and not found.total else found.total
    import_name = (store.import_filename(flt.import_id) or flt.import_id) if flt.import_id else None
    path = "/" if home else "/people"
    if not everyone:
        rows = [empty_network(home)]
    elif not found.total:
        rows = [filter_bar(flt, 0, 0, "/people", import_name), nobody_matches(flt, import_name, everyone)]
    else:
        rows = [filter_bar(flt, found.total, found.not_on_map, "/people", import_name),
                [network_row(v, n) for n, v in enumerate(found.people, 1)],
                show_more(found.shown, found.total, network_href(flt, limit + NETWORK_STEP, view))]
    views = [h.a(name.title(), href=network_href(flt, limit, name, path), data_view=name,
                 aria_current="page" if name == view else None) for name in ("list", "map")]
    placed = found.total > found.not_on_map
    block = h.div(
        h.nav(views, class_="fn-switch text-switch", aria_label="View"),
        h.div(h.div(h.h2("In your network", class_="fn-section text-label"), class_="fn-sectionbar"), rows,
              class_="fn-results__list"),
        h.div(id="map", class_="fn-map", role="region", aria_label="Map of your network",
              data_geo=network_href(flt, path="/api/people/geo")),
        class_=" ".join(["fn-results", *(["fn-results--page"] if home else []), *([] if placed else ["fn-results--no-map"])]),
        data_view=view,
    )
    return block, {"rows": found.shown, "total": found.total, "filtered": filtered}


def home_page(store: Store, view: str, message: str | None = None, question: str = "") -> tuple[str, dict]:
    """Home: the question box, the three newest searches with All searches past three, then the network block."""
    today, searches = now().astimezone().date(), store.list_searches(4)
    recent = h.section(
        h.h2("Recent searches", class_="fn-section text-label"),
        recent_list(searches[:3], store.count_candidates([s.id for s in searches[:3]]), today),
        h.p(h.a("All searches", href="/searches"), class_="fn-recent__all text-meta") if len(searches) > 3 else None,
        class_="fn-page fn-page--plain",
    ) if searches else None
    block, facts = network_block(store, NetworkFilter(), NETWORK_STEP, view, home=True)
    return page("Searches", search_box(question, message), recent, block, current="search", extra_head=MAP_HEAD), facts


def searches_page(store: Store) -> tuple[str, dict]:
    """All searches: every search, newest first, under its count."""
    searches = store.list_searches(None)
    rows = recent_list(searches, store.count_candidates([s.id for s in searches]), now().astimezone().date())
    heading = h.h1("All searches ", h.span(f"{len(searches):,}"), class_="fn-section text-label")
    return (page("All searches", h.main(heading, rows if searches else None, class_="fn-page"), current="search"),
            {"rows": len(searches), "total": len(searches), "filtered": False})


def network_page(store: Store, flt: NetworkFilter, limit: int, view: str) -> tuple[str, dict]:
    block, facts = network_block(store, flt, limit, view, home=False)
    return page("Network", block, current="network", body_class="fn-app", extra_head=MAP_HEAD), facts


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
        refresh=2 if active else None, current="search", body_class="fn-app", extra_head=MAP_HEAD,
    )


def geo_features(store: Store, search: Search) -> dict:
    """GeoJSON of the search's people: one point per card whose person has a place with coordinates."""
    found = results(store, search, now().astimezone().date())
    return geo(found.network + found.new)


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
    view = "map" if request.query_params.get("view") == "map" else "list"
    text, request.state.facts = home_page(store_of(request), view, message, question)
    return text


@router.get("/")
async def home(request: Request) -> HTMLResponse:
    return HTMLResponse(recent(request))


@router.get("/searches")
async def all_searches(request: Request) -> HTMLResponse:
    text, request.state.facts = searches_page(store_of(request))
    return HTMLResponse(text)


def network_query(request: Request) -> tuple[NetworkFilter, int, str]:
    """The filter, the limit (a positive step of 200, else 200) and the view of a network request's query."""
    params = request.query_params
    flt = NetworkFilter(text=params.get("q", ""), import_id=params.get("import") or None, new_only=params.get("new") == "1")
    raw = params.get("limit", "")
    limit = int(raw) if raw.isdigit() and len(raw) <= 6 else 0
    return flt, limit if limit > 0 and limit % NETWORK_STEP == 0 else NETWORK_STEP, params.get("view", "list")


@router.get("/people")
async def people(request: Request) -> HTMLResponse:
    flt, limit, view = network_query(request)
    text, request.state.facts = network_page(store_of(request), flt, limit, "map" if view == "map" else "list")
    return HTMLResponse(text)


@router.get("/api/people/geo")
async def people_geo(request: Request) -> JSONResponse:
    flt = network_query(request)[0]
    return JSONResponse(geo(network_view(store_of(request), flt, None, now().astimezone().date()).people))


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

