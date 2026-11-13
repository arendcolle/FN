"""The staff router: Home, All searches, the results page, the Network page with their map data, the Person page
with its decisions, the import pages, the CSV export and the source page."""
import email.policy
import re
from email.parser import BytesParser
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from fn import exporter, identity, importer, network
from fn.contracts import (
    IMPORT_COLUMNS,
    BackLink,
    Candidate,
    Claim,
    ImportPreview,
    ListPlace,
    NetworkFilter,
    ResultsHeading,
    Search,
    Source,
    normalize,
)
from fn.present import (
    PROSE,
    RESULTS_STEP,
    card,
    card_candidate,
    cut,
    geo,
    label_of,
    network_view,
    passage,
    person_views,
    plural,
    profile,
    results,
    shown_for,
    source_sentence,
    sources_read,
    walk,
)
from fn.store import Store, fold
from fn.web.html import Safe, h, page
from fn.web.parts import (
    NETWORK_STEP,
    back_line,
    banner,
    contact_block,
    count_line,
    empty_network,
    fact_groups,
    filter_bar,
    found_as_block,
    import_columns,
    import_counts,
    import_notes,
    import_rows,
    importable,
    is_filtered,
    name_matches,
    network_href,
    network_row,
    nobody_matches,
    notice,
    person_href,
    possible_block,
    profile_banner,
    profile_head,
    recent_list,
    result_card,
    results_href,
    search_box,
    show_more,
    skipped_line,
    status_line,
    status_note,
    summary_list,
    upload_form,
)
from fn.web.requests import first, form_of, store_of, worker_of
from fn.worker import now

MAX_QUESTION = 1000
# Room for the multipart framing around a file of the importer's 5 MB.
UPLOAD_CAP = importer.MAX_BYTES + 64 * 1024
NO_FILE = "Choose a CSV file to upload."
SECTIONS = {"network": "In your network", "new": "New"}
INCOMPLETE = "Some sources could not be read, so this list may be incomplete."
STOPPED = "This search stopped before it finished."
ORIGINS = ("card", "row", "popup", "import")
CONTACT_KINDS = ("email", "phone")
CARD_ACTIONS = ("add", "skip", "same", "new")

router = APIRouter()


MAP_HEAD = [h.link(rel="stylesheet", href="/static/maplibre-gl.css"), h.script(src="/static/maplibre-gl.js", defer=True),
            h.script(src="/static/map.js", defer=True)]
RESULTS_HEAD = [*MAP_HEAD, h.script(src="/static/results.js", defer=True)]


def network_block(store: Store, flt: NetworkFilter, limit: int, view: str, home: bool) -> tuple[Safe, dict]:
    """The network list beside its map, as on the Network page and Home, and the facts the request log keeps.

    An empty network shows its notice, and a filter that matches nobody 'Nobody matches'; both hide the map.
    """
    found = network_view(store, flt, limit, now().astimezone().date())
    filtered = is_filtered(flt)
    everyone = store.list_network(NetworkFilter(), 0)[1] if filtered and not found.total else found.total
    import_name = (store.import_filename(flt.import_id) or flt.import_id) if flt.import_id else None
    path = "/" if home else "/people"
    here = network_href(flt, limit, view, path)
    if not everyone:
        rows = [empty_network(home)]
    elif not found.total:
        rows = [filter_bar(flt, 0, 0, "/people", import_name), nobody_matches(flt, import_name, everyone)]
    else:
        rows = [filter_bar(flt, found.total, found.not_on_map, "/people", import_name, found.new_facts),
                [network_row(v, n, here) for n, v in enumerate(found.people, 1)],
                show_more(found.shown, found.total, network_href(flt, limit + NETWORK_STEP, view))]
    views = [h.a(name.title(), href=network_href(flt, limit, name, path), data_view=name,
                 aria_current="page" if name == view else None) for name in ("list", "map")]
    placed = found.total > found.not_on_map
    block = h.div(
        h.nav(views, class_="fn-switch text-switch", aria_label="View"),
        h.div(h.div(h.h2("In your network", class_="fn-section text-label"),
                    h.p(h.a("Import", href="/imports/new"), class_="fn-sectionbar__acts text-meta"), class_="fn-sectionbar"),
              rows,
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


def network_page(store: Store, flt: NetworkFilter, limit: int, view: str, top: Safe | None = None) -> tuple[str, dict]:
    """The Network page; top is the Banner over it, if any."""
    block, facts = network_block(store, flt, limit, view, home=False)
    return page("Network", top, block, current="network", body_class="fn-app", extra_head=MAP_HEAD), facts


def section_heading(title: str, count: int) -> Safe:
    """A heading of the results list with the number of people under it; no number when it is zero."""
    return h.h2(title, " ", h.span(f"{count:,}") if count else None, class_="fn-section text-label")


def person_cards(store: Store, search: Search, shown: int, show_skipped: bool, view: str,
                 active: bool) -> tuple[list[object], bool, dict]:
    """The count line, the shown cards under their section headings, Show more and the skipped line.

    Also whether anyone has a place on the map, and the facts the request log keeps; nothing when nobody is kept.
    """
    found = results(store, search, now().astimezone().date(), shown, show_skipped)
    here = results_href(search.id, shown, show_skipped, view)
    facts = {"kept": found.total, "shown": found.shown}
    if not found.cards and not found.skipped_hidden:
        return [], False, facts
    counts = {"network": len(found.network), "new": len(found.new)}
    firsts = {x.first_key: x for x in found.headings}
    sections = [[None if section == "new" and firsts else
                 section_heading(title, counts[section]),
                 [[section_heading(firsts[c.key].title, firsts[c.key].count) if c.key in firsts else None,
                   result_card(c, search.id, here, shown)] for c in group]]
                for section, title in SECTIONS.items() if (group := [c for c in found.cards if c.section == section])]
    count = None if active else count_line(found.total, found.not_on_map,
                                           [h.a("Export", href=f"/searches/{search.id}/export.csv")] if found.total else [])
    more = show_more(found.shown, found.total, results_href(search.id, shown + RESULTS_STEP, show_skipped, view),
                     RESULTS_STEP, f"card-{found.next_key}") if found.next_key else None
    hidden = skipped_line(found.skipped_hidden, show_skipped, results_href(search.id, shown, not show_skipped, view))
    return [count, sections, more, hidden], found.total > found.not_on_map, facts


def results_list(store: Store, search: Search, view: str, shown: int,
                 show_skipped: bool) -> tuple[Safe, bool, bool, dict]:
    """The results list: the status line, note or notice, then the count line, the cards, Show more and the skipped line.

    Also whether it has cards, whether anyone has a place on the map, and the request log facts. A running list names the status and
    fragment URLs results.js polls; progress is read before the cards, so they are never older than it.
    """
    active, stopped = search.status in ("queued", "running"), search.status in ("failed", "interrupted")
    progress = store.search_progress(search.id) if active else None
    found, placed, facts = person_cards(store, search, shown, show_skipped, view, active)
    if progress:
        top = status_line(progress.people)
    elif stopped:
        top = status_note(STOPPED, "Run again", search.question) if found else notice(search, 0)
    elif store.failed_lanes(search.id):
        top = [status_note(INCOMPLETE, "Search again", search.question),
               None if found else notice(search, sources_read(store, search))]
    else:
        top = None if found else notice(search, sources_read(store, search))
    query = urlencode({k: v for k, v in (("shown", shown if shown != RESULTS_STEP else None),
                                         ("skipped", 1 if show_skipped else None),
                                         ("view", "map" if view == "map" else None)) if v})
    poll = {"data_status": f"/searches/{search.id}/status", "data_progress": f"{progress.status} {progress.version}",
            "data_cards": f"/searches/{search.id}/cards" + (f"?{query}" if query else "")} if progress else {}
    return h.div(top, found, class_="fn-results__list", data_placed=placed, **poll), bool(found), placed, facts


def search_page(store: Store, search: Search, view: str = "list", shown: int = RESULTS_STEP,
                show_skipped: bool = False) -> tuple[str, dict]:
    """The results page: the question box, then the people's cards beside a map of where they are.

    A running search shows the status line, and a page without people a notice with the map hidden. view picks
    the list or the map on narrow screens; each has its own URL, so the refresh while a search runs keeps it.
    """
    active = search.status in ("queued", "running")
    found, cards, placed, facts = results_list(store, search, view, shown, show_skipped)
    views = [h.a(name.title(), href=results_href(search.id, shown, show_skipped, name), data_view=name,
                 aria_current="page" if name == view else None) for name in ("list", "map")]
    results = h.div(
        h.nav(views, class_="fn-switch text-switch", aria_label="View"),
        found,
        h.div(id="map", class_="fn-map", role="region", aria_label="Map of the people in this search",
              data_geo=f"/api/searches/{search.id}/geo" + (f"?shown={shown}" if shown != RESULTS_STEP else "")),
        class_="fn-results" if placed else "fn-results fn-results--no-map", data_view=view,
    )
    return page(
        "Search", search_box(search.question), results,
        refresh=2 if active else None, current="search", body_class="fn-app",
        extra_head=RESULTS_HEAD if active or cards else MAP_HEAD,
    ), facts


def geo_features(store: Store, search: Search, shown: int = RESULTS_STEP) -> dict:
    """GeoJSON of the search's people who are not skipped: one point per person with a place with coordinates.

    It also says, per person, whether the first shown cards hold them, the list link that opens at their card and
    the link to their page.
    """
    found = results(store, search, now().astimezone().date(), shown=0)
    listed: dict[str, dict] = {}
    # A person behind two cards links to the first of them.
    for n, (person, key) in enumerate(found.order):
        listed.setdefault(person, {
            "shown": n < shown, "href": f"/searches/{search.id}?shown={(n // RESULTS_STEP + 1) * RESULTS_STEP}#card-{key}",
            "profile": person_href(person, search.id, shown_for(n + 1, shown), key, "popup")})
    return geo(found.network + found.new, listed)


def source_page(store: Store, source: Source, claim: Claim | None, back: BackLink | None = None) -> str:
    """A source in words staff can read: the person, the fact as a sentence, the passage, the link and the stored text.

    Without a claim the page shows the source label and the stored text. back is the link to the page it was
    opened from. id="quote" is on the passage, or on the sentence when there is no passage, so #quote never opens the record.
    """
    person = org = None
    if claim:
        found = store.get_persons([store.canonical_ids([claim.person_id]).get(claim.person_id, claim.person_id)])
        person = next(iter(found.values()), None)
        org = store.get_orgs([claim.org_id]).get(claim.org_id) if claim.org_id else None
    title = person.display_name if person else label_of(source)
    shown = bool(claim) and source.kind in PROSE
    text = source.text
    stored = [text[:claim.quote_start], h.mark(claim.quote),
              text[claim.quote_end:]] if claim else text
    before, quote, after = passage(source, claim) if shown else ("", "", "")
    return page(
        title if person else "Source",
        h.main(
            back_line(back, None),
            h.h1(title, class_="fn-source__title text-title"),
            h.p(source_sentence(claim, source, org), id=None if shown else "quote", class_="fn-source__lead text-body") if claim else None,
            h.p(before, h.mark(quote, id="quote"), after, class_="fn-source__passage text-body") if shown else None,
            None if source.url.startswith("fn:") else h.p(h.a("Open the original page", href=source.url),
                                                          class_="fn-source__url text-small"),
            h.details(h.summary("Show the stored record", class_="text-meta"),
                      h.pre(stored, class_="fn-source__text text-body"), class_="fn-source__stored"),
            class_="fn-source",
        ),
        current="search" if leads_to_search(back) else None,
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
    limit = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 6 else 0
    return flt, limit if limit > 0 and limit % NETWORK_STEP == 0 else NETWORK_STEP, params.get("view", "list")


def import_banner(store: Store, request: Request) -> Safe | None:
    """The Banner after a confirm (?imported=<id>) or a discard (?discarded=<id>), once the import has that status."""
    params = request.query_params
    if (found := importer.get(store, params.get("imported", ""))) and found.status == "confirmed":
        return banner(f"{plural(importable(found), 'person', 'people')} imported from {found.filename}.",
                      ("Show them", network_href(NetworkFilter(import_id=found.import_id))))
    if (found := importer.get(store, params.get("discarded", ""))) and found.status == "discarded":
        return banner(f"{found.filename} discarded. Nothing was imported.")
    return None


@router.get("/people")
async def people(request: Request) -> HTMLResponse:
    flt, limit, view = network_query(request)
    store = store_of(request)
    text, request.state.facts = network_page(store, flt, limit, "map" if view == "map" else "list",
                                             import_banner(store, request))
    return HTMLResponse(text)


@router.get("/people/export.csv")
async def export_people(request: Request) -> Response:
    """The filtered network as a CSV download, all of it, recorded as an export event."""
    flt, store, today = network_query(request)[0], store_of(request), now().astimezone().date()
    found = network_view(store, flt, None, today).people
    text = exporter.csv_text(store, found, str(request.base_url).rstrip("/"))
    network.record_export(store, now=now(), detail={"count": len(found), "filtered": is_filtered(flt)})
    request.state.facts = {"people": len(found), "filtered": is_filtered(flt)}
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fn-network-{today.isoformat()}.csv"'})


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


def shown_of(raw: str) -> int:
    """A shown count from a query: a positive number of at most six digits, else 20."""
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 6 and int(raw) > 0 else RESULTS_STEP


def results_query(request: Request) -> tuple[int, bool]:
    """?shown= (a positive number, else 20) and ?skipped=1 of a results request."""
    return shown_of(request.query_params.get("shown", "")), request.query_params.get("skipped") == "1"


def results_page(request: Request, search_id: str, view: str) -> HTMLResponse:
    """The results page in the given view, with ?shown= and ?skipped=1, and its facts for the request log."""
    text, request.state.facts = search_page(store_of(request), get_search(request, search_id), view,
                                            *results_query(request))
    return HTMLResponse(text)


@router.get("/searches/{search_id}")
async def show(request: Request, search_id: str) -> HTMLResponse:
    return results_page(request, search_id, "list")


@router.get("/searches/{search_id}/map")
async def show_map(request: Request, search_id: str) -> HTMLResponse:
    return results_page(request, search_id, "map")


@router.get("/searches/{search_id}/status")
async def search_status(request: Request, search_id: str) -> JSONResponse:
    """The search's status, people count and version, which goes up with each publish; results.js polls it."""
    progress = store_of(request).search_progress(search_id)
    if progress is None:
        raise HTTPException(404, "No such search")
    request.state.facts = {"version": progress.version, "people": progress.people}
    return JSONResponse(progress.model_dump())


@router.get("/searches/{search_id}/cards")
async def search_cards(request: Request, search_id: str) -> HTMLResponse:
    """The results list alone, as on the page, for results.js to swap in; ?view=map keeps the map view's links."""
    view = "map" if request.query_params.get("view") == "map" else "list"
    found, _, _, request.state.facts = results_list(store_of(request), get_search(request, search_id), view,
                                                    *results_query(request))
    return HTMLResponse(found)


def candidate_of(store: Store, search_id: str, person_id: str) -> Candidate:
    """The search's kept candidate of that person id; 404 for an unknown search or person."""
    if store.get_search(search_id) is None:
        raise HTTPException(404, "No such search")
    found = next((c for c in store.list_candidates(search_id, kept_only=True) if c.person_id == person_id), None)
    if found is None:
        raise HTTPException(404, "No such person in this search")
    return found


def card_decision(store: Store, candidate: Candidate, action: str, match: str) -> None:
    """Add, skip, merge into the same-name network person, or add as new; a second press changes nothing."""
    hits = identity.on_card(store, candidate)
    where = {"search_id": candidate.search_id, "rank": candidate.rank, "section": candidate.section}
    theirs = store.canonical_ids([match]).get(match) if match else None
    known = theirs in network.name_matches(store, hits) if theirs else False
    if action == "add":
        network.add(store, hits, via="search", now=now(), **where)
    elif action == "skip":
        statuses = {p.list_status for p in store.get_persons(list(set(store.canonical_ids(hits).values()))).values()}
        if "in_list" not in statuses and statuses != {"skipped"}:
            network.skip(store, hits, now=now(), **where)
    elif action == "same" and known:
        network.merge(store, hits, theirs, now=now(), **where)
    elif action == "new":
        network.add(store, hits, via="search", now=now(), not_same_as=[theirs] if known else [], **where)


@router.post("/searches/{search_id}/people/{person_id}/{action}")
async def card_action(request: Request, search_id: str, person_id: str, action: str) -> Response:
    """A card's decision; a fetch request gets the card back, any other goes to the results page at the card or to
    the Person page it was pressed on."""
    if action not in CARD_ACTIONS:
        raise HTTPException(404, "No such action")
    store, form = store_of(request), await form_of(request)
    candidate = candidate_of(store, search_id, person_id)
    card_decision(store, candidate, action, first(form, "match"))
    request.state.facts = {"action": action}
    here = local_path(form.get("next", [""])[0]) or ""
    if re.fullmatch(r"/people/[^/]+", urlsplit(here).path):
        return RedirectResponse(here, 303)
    here = here if here.split("?")[0] in (f"/searches/{search_id}", f"/searches/{search_id}/map") else f"/searches/{search_id}"
    if request.headers.get("x-requested-with") == "fetch":
        shown = shown_of(parse_qs(urlsplit(here).query).get("shown", [""])[0])
        return HTMLResponse(result_card(card(store, candidate, now().astimezone().date()), search_id, here, shown))
    return RedirectResponse(f"{here}#card-{person_id}", 303)


@router.get("/searches/{search_id}/export.csv")
async def export_search(request: Request, search_id: str) -> Response:
    """The search's kept people who are not skipped as a CSV download, one row each, recorded as an export event."""
    store, today = store_of(request), now().astimezone().date()
    get_search(request, search_id)
    candidates = store.list_candidates(search_id, kept_only=True, include_skipped=False)
    views = person_views(store, [c.hit_person_ids or c.person_ids[:1] for c in candidates], today)
    people = list({v.person_id: v for v in views}.values())
    text = exporter.csv_text(store, people, str(request.base_url).rstrip("/"))
    network.record_export(store, now=now(), detail={"count": len(people), "search_id": search_id})
    request.state.facts = {"people": len(people)}
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fn-search-{today.isoformat()}.csv"'})


@router.get("/api/searches/{search_id}/geo")
async def geo_json(request: Request, search_id: str) -> JSONResponse:
    return JSONResponse(geo_features(store_of(request), get_search(request, search_id), results_query(request)[0]))


def get_source(request: Request, source_id: str, claim: str) -> tuple[Source, Claim | None]:
    """The source and, when claim is given, that claim; 404 when either is missing or the claim quotes another source."""
    store = store_of(request)
    source = store.get_sources([source_id]).get(source_id)
    marked = store.get_claim(claim) if claim else None
    if source is None or (claim and (marked is None or marked.source_id != source_id)):
        raise HTTPException(404, "No such source or claim")
    return source, marked


@router.get("/sources/{source_id}")
async def show_source(request: Request, source_id: str, claim: str = "", back: str = "") -> HTMLResponse:
    store = store_of(request)
    return HTMLResponse(source_page(store, *get_source(request, source_id, claim), back_link(store, back)))


def local_path(value: str) -> str | None:
    """The value when it is a path on this site, else None; //host, /\\host and control characters are refused."""
    if not value.startswith("/") or value[1:2] in ("/", "\\") or re.search(r"[\x00-\x1f\\]", value):
        return None
    parts = urlsplit(value)
    return value if not parts.scheme and not parts.netloc else None


MAX_BACK = 2000
BACK_PATH = re.compile(r"/(?:people(?:/[^/]+)?|searches/[^/]+(?:/map)?)?")


def leads_to_search(back: BackLink | None) -> bool:
    return bool(back and back.href.startswith("/searches/"))


def back_link(store: Store, value: str) -> BackLink | None:
    """The link back to a page of this site named by value: your network, a person or a search's results.

    None for a value that is not a local path of those forms, is longer than 2,000 characters or names an unknown
    person or search; a person merged since reads by their canonical name.
    """
    if len(value) > MAX_BACK or not local_path(value):
        return None
    path = urlsplit(value).path
    if not BACK_PATH.fullmatch(path):
        return None
    kind, _, rest = path.strip("/").partition("/")
    if kind == "searches":
        found = store.get_search(rest.removesuffix("/map"))
        return BackLink(label=results_label(found), href=value) if found else None
    if kind == "people" and rest:
        canonical = store.canonical_ids([rest]).get(rest)
        return BackLink(label=f"Back to {store.get_persons([canonical])[canonical].display_name}", href=value) if canonical else None
    return BackLink(label="Back to your network", href=value)


def results_label(search: Search) -> str:
    return f"Back to the results for “{cut(search.question, 60)}”"


def search_back(search: Search, shown: int, key: str) -> BackLink:
    """The link to the search's results at the shown count and the card the page was opened from."""
    anchor = f"#card-{quote(key, safe='')}" if key else ""
    return BackLink(label=results_label(search), href=results_href(search.id, shown, False) + anchor)


def list_place(store: Store, search: Search, shown: int, key: str) -> ListPlace | None:
    """The card's place in the search's list with the links to the people before and after it."""
    if not (found := walk(store, search, key)):
        return None
    position, total, before, after = found

    def href(step: tuple[str, str] | None, at: int) -> str | None:
        return person_href(step[0], search.id, shown_for(at, shown), step[1], "card") if step else None

    return ListPlace(position=position, total=total, previous=href(before, position - 1), next=href(after, position + 1))


def person_here(person_id: str, params: dict[str, str]) -> str:
    """The Person page's path with the query that keeps its state: the search, shown count and card it was opened
    from, the page it returns to and every fact shown."""
    keys = ("search", "shown", "card", "back", "all")
    query = urlencode({k: params[k] for k in keys if params.get(k)})
    return f"/people/{person_id}?{query}" if query else f"/people/{person_id}"


def person_page(store: Store, person_id: str, params: dict[str, str], error: str | None = None,
                typed: str | None = None, edit: str | None = None) -> str:
    """The Person page of a canonical id; a network person's New marks are then cleared for the next visit.

    params is the page's query; error and typed re-open the edit field of kind edit with a refused value.
    """
    search = store.get_search(params.get("search", ""))
    shown, key = shown_of(params.get("shown", "")), params.get("card", "")
    candidate = card_candidate(store, search.id, person_id, key) if search and key else None
    topic = next((p.detail for p in candidate.score_parts if p.feature == "topic"), "") if candidate else ""
    view = profile(store, person_id, now().astimezone().date(), identity.on_card(store, candidate) if candidate else None,
                   topic.split(", ") if topic else [])
    here = person_here(person_id, params)
    route = f"/searches/{search.id}/people/{candidate.person_id}" if candidate else None
    back = search_back(search, shown, key) if search else back_link(store, params.get("back", ""))
    place = list_place(store, search, shown, key) if search and key else None
    edit = edit or (params.get("edit") if params.get("edit") in CONTACT_KINDS else None)
    member = view.person.status == "in_list"
    text = page(
        view.person.name,
        profile_banner(view, params.get("undo") == "refused", here),
        h.main(h.div(profile_head(view, back, place, here, route), summary_list(view.summary),
                     fact_groups(view, here, params.get("all")),
                     contact_block(view, here, edit, error, typed) if member else None, found_as_block(view, here),
                     possible_block(view, here), class_="fn-column"), class_="fn-page"),
        current="search" if leads_to_search(back) else "network",
    )
    if member:
        network.mark_seen(store, person_id, now=now())
    return text


def canonical_of(store: Store, person_id: str) -> str:
    """The canonical id of the person; 404 for an unknown id."""
    found = store.canonical_ids([person_id]).get(person_id)
    if found is None:
        raise HTTPException(404, "No such person")
    return found


def back_to(form: dict[str, list[str]], fallback: str, query: str = "") -> RedirectResponse:
    """A 303 to the form's next path when it is on this site, else to fallback, with query added before its anchor."""
    target, mark, anchor = (local_path(form.get("next", [""])[0]) or fallback).partition("#")
    url = f"{target}{'&' if '?' in target else '?'}{query}" if query else target
    return RedirectResponse(f"{url}{mark}{anchor}", 303)


@router.get("/people/{person_id}")
async def person(request: Request, person_id: str) -> Response:
    store = store_of(request)
    canonical = canonical_of(store, person_id)
    if canonical != person_id:
        query = request.url.query
        return RedirectResponse(f"/people/{canonical}?{query}" if query else f"/people/{canonical}", 303)
    origin = request.query_params.get("from")
    request.state.facts = {"from": origin} if origin in ORIGINS else {}
    return HTMLResponse(person_page(store, person_id, dict(request.query_params)))


@router.post("/people/{person_id}/add")
async def add_person(request: Request, person_id: str) -> Response:
    store, form = store_of(request), await form_of(request)
    canonical = canonical_of(store, person_id)
    apart = first(form, "not_same")
    network.add(store, [canonical], via="profile", now=now(),
                not_same_as=[apart] if apart and store.canonical_ids([apart]) else [])
    return back_to(form, f"/people/{canonical}")


@router.post("/people/{person_id}/skip")
async def skip_person(request: Request, person_id: str) -> Response:
    store, form = store_of(request), await form_of(request)
    canonical = canonical_of(store, person_id)
    if store.get_persons([canonical])[canonical].list_status == "candidate":
        network.skip(store, [canonical], now=now())
    return back_to(form, f"/people/{canonical}")


@router.post("/people/{person_id}/remove")
async def remove_person(request: Request, person_id: str) -> Response:
    store, form = store_of(request), await form_of(request)
    canonical = canonical_of(store, person_id)
    if store.get_persons([canonical])[canonical].list_status == "in_list":
        network.remove(store, canonical, now=now())
    return back_to(form, f"/people/{canonical}")


@router.post("/people/{person_id}/contact")
async def edit_contact(request: Request, person_id: str) -> Response:
    """Save a typed email or phone number; a refused value re-opens the field with its sentence, status 400."""
    store, form = store_of(request), await form_of(request)
    canonical = canonical_of(store, person_id)
    kind, value = first(form, "kind"), form.get("value", [""])[0]
    if kind not in CONTACT_KINDS:
        raise HTTPException(400, "A contact is an email or a phone number.")
    held = {fold(c.value) for c in store.claims_of([canonical]) if c.kind == kind}
    if fold(normalize(value)) not in held:
        try:
            network.set_contact(store, canonical, kind, value, now=now(), replaces=first(form, "replaces") or None)
        except ValueError as refused:
            next_path = local_path(form.get("next", [""])[0]) or ""
            params = {k: v[0] for k, v in parse_qs(urlsplit(next_path).query).items()}
            return HTMLResponse(person_page(store, canonical, params, str(refused), value, kind), 400)
    return back_to(form, f"/people/{canonical}")


@router.post("/people/{person_id}/merge")
async def merge_person(request: Request, person_id: str) -> Response:
    """The other person joins this one; a second press finds them one person already and changes nothing."""
    store, form = store_of(request), await form_of(request)
    canonical, other = canonical_of(store, person_id), first(form, "other")
    theirs = store.canonical_ids([other]).get(other)
    if theirs in network.possible_matches(store, canonical):
        network.merge(store, [theirs], canonical, now=now())
    return back_to(form, f"/people/{canonical}")


@router.post("/people/{person_id}/not-same")
async def not_same_person(request: Request, person_id: str) -> Response:
    """Separate a record of this person, or mark a possible match as someone else; once only."""
    store, form = store_of(request), await form_of(request)
    canonical, other = canonical_of(store, person_id), first(form, "other")
    theirs = store.canonical_ids([other]).get(other)
    if other != canonical and (theirs == canonical or theirs in network.possible_matches(store, canonical)):
        network.not_same(store, canonical, other, now=now())
    return back_to(form, f"/people/{canonical}")


@router.post("/claims/{claim_id}/reject")
async def reject(request: Request, claim_id: str) -> Response:
    store, form = store_of(request), await form_of(request)
    claim = store.get_claim(claim_id)
    if claim is None:
        raise HTTPException(404, "No such fact")
    if claim.rejected_at is None:
        network.reject_claim(store, claim_id, now=now())
    return back_to(form, f"/people/{canonical_of(store, claim.person_id)}#claim-{claim_id}")


@router.post("/events/{event_id}/undo")
async def undo(request: Request, event_id: str) -> Response:
    """Undo the decision; a refused undo goes back with the code of its Banner, a second press changes nothing."""
    store, form = store_of(request), await form_of(request)
    event = store.get_event(event_id)
    if event is None:
        raise HTTPException(404, "No such decision")
    fallback = f"/people/{canonical_of(store, event.person_id)}" if event.person_id else "/"
    if event.person_id and any(e.undoes == event.id for e in store.events_of(event.person_id)):
        return back_to(form, fallback)
    try:
        network.undo(store, event_id, now=now())
    except network.UndoRefused:
        return back_to(form, fallback, "undo=refused")
    return back_to(form, fallback)
def upload_page(error: str | None = None) -> str:
    """The Import page: the CSV file Field, error under it, and the columns FN reads."""
    return page("Import people", h.main(h.div(
        h.h1("Import people", class_="fn-page__title text-title"),
        h.p("Upload a CSV file with one person per row. FN shows you what it will do before anything is imported.",
            class_="fn-page__lead text-body"),
        upload_form(error), import_columns(IMPORT_COLUMNS),
        class_="fn-column"), class_="fn-page"), current="network")


def import_summary(store: Store, preview: ImportPreview) -> Safe:
    """The ImportSummary of an import in preview: counts, notes, name matches, Import and Discard.

    A confirmed or discarded import shows what happened instead, without buttons.
    """
    title, count = h.h1(f"Check {preview.filename}", class_="fn-page__title text-title"), importable(preview)
    if preview.status == "discarded":
        return h.div(title, h.p(f"{preview.filename} discarded. Nothing was imported.", class_="fn-page__lead text-body"),
                     class_="fn-summary")
    if preview.status == "confirmed":
        done = [f"{plural(count, 'person', 'people')} imported from {preview.filename}. ",
                h.a("Show them", href=network_href(NetworkFilter(import_id=preview.import_id)))]
        return h.div(title, h.p(done, class_="fn-page__lead text-body"), import_counts(preview), class_="fn-summary")
    matched = [r for r in preview.rows if r.outcome == "name_match" and r.person_id]
    views = dict(zip([r.person_id for r in matched],
                     person_views(store, [[r.person_id] for r in matched], now().astimezone().date())))
    discard = h.button("Discard", class_="fn-btn fn-btn--quiet text-control", formaction=f"/imports/{preview.import_id}/discard")
    word = plural(count, "person", "people")
    return h.form(
        title, h.p(f"Nothing is imported until you press Import {word}.", class_="fn-page__lead text-body"),
        import_counts(preview), import_notes(preview), name_matches(preview.rows, views),
        h.div(h.button(f"Import {word}", class_="fn-btn fn-btn--dark text-control") if count else None, discard,
              class_="fn-summary__acts"),
        h.p("You can remove anyone later from their profile.", class_="fn-note text-small") if count else None,
        class_="fn-summary", method="post", action=f"/imports/{preview.import_id}/confirm",
    )


def preview_page(store: Store, preview: ImportPreview) -> str:
    return page(f"Check {preview.filename}", h.main(h.div(import_summary(store, preview), class_="fn-column"),
                                                    import_rows(preview, IMPORT_COLUMNS), class_="fn-page"),
                current="network")


async def capped_body(request: Request) -> tuple[bytes, bool]:
    """The request body up to UPLOAD_CAP bytes and whether it goes past them; reading stops there."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > UPLOAD_CAP:
            return bytes(body[:UPLOAD_CAP]), True
    return bytes(body), False


def uploaded_file(content_type: str, body: bytes) -> tuple[str, bytes] | None:
    """The file name and bytes of the multipart field 'file', or None when no file was chosen."""
    if not content_type.startswith("multipart/form-data"):
        return None
    head = b"Content-Type: " + content_type.encode("latin-1", errors="replace") + b"\r\n\r\n"
    message = BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == "file" and (name := part.get_filename()):
            return name.replace("\\", "/").rsplit("/", 1)[-1], part.get_payload(decode=True) or b""
    return None


def get_import(request: Request, import_id: str) -> ImportPreview:
    found = importer.get(store_of(request), import_id)
    if found is None:
        raise HTTPException(404, "No such import")
    return found


@router.get("/imports/new")
async def new_import() -> HTMLResponse:
    return HTMLResponse(upload_page())


@router.post("/imports")
async def upload(request: Request) -> Response:
    body, too_big = await capped_body(request)
    found = uploaded_file(request.headers.get("content-type", ""), body)
    if too_big:
        error = importer.TOO_BIG.format(file=found[0] if found else "This file")
    elif found is None:
        error = NO_FILE
    else:
        try:
            import_id = importer.upload(worker_of(request), *found, now())
        except importer.ImportRefused as exc:
            error = str(exc)
        else:
            preview = get_import(request, import_id)
            request.state.facts = {"rows": len(preview.rows), **preview.counts}
            return RedirectResponse(f"/imports/{import_id}", 303)
    request.state.facts = {"refused": True}
    return HTMLResponse(upload_page(error), 400)


@router.get("/imports/{import_id}")
async def show_import(request: Request, import_id: str) -> HTMLResponse:
    preview = get_import(request, import_id)
    request.state.facts = {"rows": len(preview.rows), **preview.counts}
    return HTMLResponse(preview_page(store_of(request), preview))


@router.post("/imports/{import_id}/confirm")
async def confirm_import(request: Request, import_id: str) -> RedirectResponse:
    """Import the rows, merging the ticked name matches, or every one when the header box is ticked."""
    form, preview = await form_of(request), get_import(request, import_id)
    if form.get("same_all"):
        merge = {r.n for r in preview.rows if r.outcome == "name_match"}
    else:
        merge = {int(v) for v in form.get("merge", []) if v.isdigit() and len(v) <= 9}
    try:
        done = importer.confirm(worker_of(request), import_id, merge, now())
    except importer.ImportRefused:
        return RedirectResponse(f"/imports/{import_id}", 303)
    request.state.facts = {"rows": len(done.rows), **done.counts}
    return RedirectResponse(f"/people?imported={import_id}", 303)


@router.post("/imports/{import_id}/discard")
async def discard_import(request: Request, import_id: str) -> RedirectResponse:
    preview = get_import(request, import_id)
    try:
        importer.discard(store_of(request), import_id)
    except importer.ImportRefused:
        return RedirectResponse(f"/imports/{import_id}", 303)
    request.state.facts = {"rows": len(preview.rows)}
    return RedirectResponse(f"/people?discarded={import_id}", 303)
