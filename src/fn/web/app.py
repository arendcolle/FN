"""The local web app: routes, host and origin checks, security headers, error pages and fn-serve."""
import json
import logging
import sys
import traceback
from calendar import month_name
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import get_args
from urllib.parse import parse_qs, urlencode, urlsplit

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fn import config, net, orgs, rank
from fn.config import Settings
from fn.contracts import (
    CONTRACTS_VERSION,
    Ask,
    Candidate,
    Chip,
    Chips,
    Claim,
    HttpClient,
    LaneOut,
    Org,
    Place,
    RankOut,
    ResolveOut,
    Search,
    Source,
    StepRun,
    group_key,
    name_key,
)
from fn.llm import StructuredLLM, from_settings
from fn.steps import redact, setup_logging
from fn.store import Store
from fn.web.html import Safe, h, page, table
from fn.worker import Worker, new_id, now

log = logging.getLogger("fn.web")

MAX_QUESTION = 1000
MAX_CHIP = 200
MAX_CHIPS = 20
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; connect-src 'self' https://tiles.openfreemap.org; "
        "worker-src blob:; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
}
ASKS = get_args(Ask)
TRACED = {"LaneOut": LaneOut, "ResolveOut": ResolveOut, "RankOut": RankOut}

router = APIRouter()


def store_of(request: Request) -> Store:
    return request.app.state.store


def worker_of(request: Request) -> Worker:
    return request.app.state.worker


def error_page(title: str, text: str) -> str:
    return page(title, h.div(h.h1(title, class_="text-title"), h.pre(text), class_="fn-page"))


def refusal(request: Request) -> Response | None:
    """A 403 for a state-changing request from another site or origin, else None.

    Origin must be the app's own. A browser sends Origin: null from the app's own forms because of
    Referrer-Policy: no-referrer, so null passes only when Sec-Fetch-Site says same-origin.
    """
    if request.method in SAFE_METHODS:
        return None
    origin, site = request.headers.get("origin"), request.headers.get("sec-fetch-site")
    allowed = {None, f"http://{request.headers.get('host')}"} | ({"null"} if site == "same-origin" else set())
    if origin not in allowed or site not in (None, "same-origin", "none"):
        return HTMLResponse(error_page("Refused", "This request comes from another site."), 403)
    return None


async def form_of(request: Request) -> dict[str, list[str]]:
    return parse_qs((await request.body()).decode(errors="replace"), keep_blank_values=True)


def first(form: dict[str, list[str]], name: str) -> str:
    return " ".join(form.get(name, [""])[0].split())


def duration(step: StepRun) -> str:
    if step.ended_at is None:
        return "running" if step.status == "running" else "-"
    return f"{(step.ended_at - step.started_at).total_seconds():.2f}s"


def plural(count: int, one: str, many: str) -> str:
    return f"{count:,} {one if count == 1 else many}"


def cut(text: str, limit: int) -> str:
    """The text, or its words up to limit characters and '…' when it is longer."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def days_ago(at: datetime, today: date) -> str:
    """A past moment as people say it: today, yesterday, 3 days ago, last week, else 3 March 2026."""
    local = at.astimezone()
    days = (today - local.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 7 else "last week" if days < 14 else f"{local.day} {local:%B %Y}"


def search_box(question: str = "", message: str | None = None) -> Safe:
    """The question box and its Search button; message is a refused question, shown under the box."""
    return h.form(
        h.div(
            h.textarea(question, name="question", rows="3" if len(question) > 80 else "1", class_="fn-input text-body",
                       placeholder="Flemish experts in 6G research near New York", aria_label="Question",
                       aria_invalid="true" if message else None, aria_describedby="question-error" if message else None),
            h.p(message, class_="fn-error text-small", id="question-error") if message else None,
            class_="fn-search__field",
        ),
        h.button("Search", type="submit", class_="fn-btn fn-btn--dark text-control"),
        method="post", action="/searches", class_="fn-search",
    )


def recent_meta(search: Search, people_count: int, today: date) -> Safe:
    if search.status in ("queued", "running"):
        return h.span("Searching…", class_="fn-recent__meta fn-recent__meta--running text-meta-strong")
    if search.status in ("failed", "interrupted"):
        return h.span("Failed", class_="fn-recent__meta fn-recent__meta--failed text-meta-strong")
    return h.span(f"{plural(people_count, 'person', 'people')} · {days_ago(search.created_at, today)}",
                  class_="fn-recent__meta text-meta")


def home_page(searches: list[Search], counts: dict[str, int], message: str | None = None, question: str = "") -> str:
    """The Ask page: the question box, then the recent searches with their state; counts holds people per search."""
    today = now().astimezone().date()
    rows = [h.li(h.a(cut(s.question, 200), href=f"/searches/{s.id}", class_="text-body"),
                 recent_meta(s, counts.get(s.id, 0), today)) for s in searches]
    recent = h.section(h.h2("Recent searches", class_="fn-section text-label"), h.ul(rows, class_="fn-recent"),
                       class_="fn-page") if rows else None
    return page("Searches", search_box(question, message), recent, current="search")


def chip_inputs(name: str, chips: list[Chip]) -> Safe:
    return h.p([h.input(type="text", name=name, value=c.text) for c in chips], h.input(type="text", name=name))


def trace_url(search_id: str, name: str) -> str:
    return f"/debug/searches/{search_id}/trace?{urlencode({'name': name})}"


def source_cell(claim: Claim, sources: dict[str, Source]) -> list[Safe]:
    source = sources[claim.source_id]
    return [h.a(source.title or source.url, href=source.url), " ",
            h.a("quote in source", href=f"/sources/{claim.source_id}?claim={claim.id}#quote"), " ",
            h.a("source facts", href=f"/debug/sources/{claim.source_id}?claim={claim.id}")]


def date_text(claim: Claim) -> str:
    return f"{claim.claim_date} ({claim.date_precision}, {claim.date_method})" if claim.claim_date else "no date"


def titles(claims: list[Claim], sources: dict[str, Source]) -> str:
    """The title (else URL) of each source the claims quote, once each, or 'no source'."""
    return ", ".join(dict.fromkeys(sources[c.source_id].title or sources[c.source_id].url for c in claims)) or "no source"


def belgian_rows(claims: list[Claim], sources: dict[str, Source], facts: dict[str, Org],
                 scored: list[str]) -> list[Safe]:
    """The claims at Belgian organizations with org region, name language and claim years, and the org ids without facts.

    A claim whose id is in scored, the belgian_years part's claims, is marked yes. Only when every org id
    has facts and none is Belgian does it say no Belgian organization was found.
    """
    found, missing = orgs.belgian_claims(claims, facts), orgs.missing_facts(claims, facts)
    if not found and not missing:
        return [h.p(f"No Belgian organization found in {titles(claims, sources)}")]
    rows = [[org.name, org.region or "", org.name_lang or "", f"{c.kind} {c.relation or ''}".strip(), c.value,
             c.quote, source_cell(c, sources), date_text(c), rank.years_text(rank.units(c)),
             "yes" if c.id in scored else ""] for c, org in found]
    return [h.p(f"org facts not stored for {', '.join(missing)}") if missing else None,
            [h.h4("Claims at Belgian organizations"),
             table(["Institution", "Region", "Name language", "Claim", "Value", "Quote", "Source", "Date", "Years",
                    "Scored"], rows)]
            if found else None]


def card(search_id: str, candidate: Candidate, store_data: tuple) -> Safe:
    persons, claims_by_person, claims, sources, flags, matched, facts = store_data
    lanes = ", ".join([f"{p.feature} #{p.rank}" for p in candidate.score_parts]
                      or [f"{lane} #{r}" for lane, r in candidate.lane_ranks.items()])
    records = []
    for i, person_id in enumerate(candidate.person_ids, 1):
        own = claims_by_person.get(person_id, [])
        rows = [[
            f"{c.kind} {c.relation or ''}".strip(),
            f"{c.value} (matched)" if c.id in candidate.reason_claim_ids else c.value,
            c.quote,
            source_cell(c, sources),
            date_text(c),
        ] for c in own]
        records += [h.h4(f"Record {i}: {persons[person_id].display_name}, in {titles(own, sources)}"),
                    table(["Claim", "Value", "Quote", "Source", "Date"], rows)]
    parts = [[p.feature, p.rank, f"{p.points:.4f}", p.detail, ", ".join(claims[c].value for c in p.claim_ids if c in claims)]
             for p in candidate.score_parts]
    name = persons[candidate.person_id].display_name
    return h.fieldset(
        h.legend(f"{candidate.section} #{candidate.rank} {name}"),
        h.p(f"Score {candidate.score:.4f} from {lanes}. ", h.a("trace", href=trace_url(search_id, name))),
        [h.p(f"Found by {lane}: {how}") for p in candidate.person_ids for lane, how in matched.get(p, [])],
        h.p(f"Same name in {len(candidate.person_ids)} records, not merged: "
            f"{'; '.join(f.reason for f in flags if f.person_id == candidate.person_id)}")
        if len(candidate.person_ids) > 1 else None,
        [h.h4("Score parts"), table(["Feature", "Rank", "Points", "Detail", "Claims"], parts)] if parts
        else h.p("score parts not stored (contracts v1)") if candidate.score > 0 else None,
        belgian_rows([c for p in candidate.person_ids for c in claims_by_person.get(p, [])], sources, facts,
                     next((p.claim_ids for p in candidate.score_parts if p.feature == "belgian_years"), [])),
        records,
    )


def lane_matches(store: Store, search_id: str) -> dict[str, list[tuple[str, str]]]:
    """Each person's (lane, matched_on) from the stored lane outputs of a search."""
    found: dict[str, list[tuple[str, str]]] = {}
    for step in store.list_steps(search_id):
        output = store.get_payload(step.id)[1] if step.output_model == "LaneOut" else None
        for hit in LaneOut.model_validate_json(output).hits if output else []:
            found.setdefault(hit.person_id, []).append((hit.lane, hit.matched_on))
    return found


def cards(store: Store, search: Search) -> Safe | None:
    """One card per candidate: lane matches, score parts, claims at Belgian organizations, flags and each record's claims."""
    candidates = store.list_candidates(search.id)
    if not candidates:
        return h.p("No results.") if search.status == "done" else None
    person_ids = [p for c in candidates for p in c.person_ids]
    own = store.claims_of(person_ids)
    by_person: dict[str, list[Claim]] = {}
    for claim in own:
        by_person.setdefault(claim.person_id, []).append(claim)
    data = (store.get_persons(person_ids), by_person, {c.id: c for c in own},
            store.get_sources(list({c.source_id for c in own})), store.list_flags(search.id),
            lane_matches(store, search.id), store.get_orgs(list({c.org_id for c in own if c.org_id})))
    return Safe("".join(card(search.id, c, data) for c in candidates))


def chips_form(search: Search, message: str | None = None) -> list[Safe]:
    """The search's chips as a form that reruns the question with the edited chips."""
    chips = search.chips
    if chips is None:
        return [h.h2("Chips"), h.p("No chips yet.")]
    return [h.h2("Chips" if search.chips_origin is None else f"Chips ({search.chips_origin})"), h.form(
        h.fieldset(h.legend("Topics"), chip_inputs("topics", chips.topics)),
        h.fieldset(h.legend("Institutions"), chip_inputs("institutions", chips.institutions)),
        h.fieldset(h.legend("Place"), h.input(type="text", name="place", value=chips.place.text if chips.place else "")),
        h.fieldset(h.legend("Ask"), h.select(
            h.option("", value=""),
            [h.option(a, value=a, selected=chips.ask == a) for a in ASKS],
            name="ask",
        )),
        h.p(message, class_="error") if message else None,
        h.p(h.button("Run again with these chips", type="submit")),
        method="post", action=f"/searches/{search.id}/rerun",
    )]


SECTIONS = {"network": "In your network", "new": "New"}
EMPLOYED = ("works_at", "worked_at", "affiliated_with")


def newest_places(claims: list[Claim]) -> dict[str, Claim]:
    """Each person's newest dated location claim with coordinates, by person id."""
    newest: dict[str, Claim] = {}
    for claim in sorted(claims, key=lambda c: (c.claim_date or "", c.id)):
        if claim.kind == "location" and claim.claim_date and claim.lat is not None and claim.lon is not None:
            newest[claim.person_id] = claim
    return newest


def employer_of(claims: list[Claim]) -> str | None:
    """The organization of the newest works_at, worked_at or affiliated_with claim, or None."""
    jobs = [c for c in claims if c.relation in EMPLOYED]
    return max(jobs, key=lambda c: (c.valid_to or c.claim_date or "", c.claim_date or "")).value if jobs else None


def belgian_orgs(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[str, list[int]]]:
    """Each Belgian organization the claims name with the years of those claims, earliest first."""
    years: dict[str, set[int]] = {}
    for claim, org in orgs.belgian_claims(claims, facts):
        years.setdefault(org.name, set()).update(int(u) for u in rank.units(claim) if u != rank.UNDATED)
    return sorted(((name, sorted(found)) for name, found in years.items()), key=lambda t: (t[1][:1] or [9999], t[0]))


def orgs_line(found: list[tuple[str, list[int]]]) -> list[object]:
    """The first three organizations as 'KU Leuven 2008–2013', joined by ' · ', then '+2 more' for the rest."""
    parts: list[object] = []
    for name, years in found[:3]:
        span = f"{years[0]}–{years[-1]}" if len(years) > 1 else "".join(map(str, years))
        parts += [" · " if parts else None, name, [" ", h.span(span, class_="text-year")] if span else None]
    return parts + ([f" · +{len(found) - 3} more"] if len(found) > 3 else [])


def evidence(candidate: Candidate, claims: list[Claim], facts: dict[str, Org]) -> Claim | None:
    """The claim to quote on a card: the newest at a Belgian organization, else the first the search matched."""
    belgian = [c for c, _ in orgs.belgian_claims(claims, facts)]
    if belgian:
        return max(belgian, key=lambda c: (c.claim_date or "", c.id))
    return next((c for c in claims if c.id in candidate.reason_claim_ids), None)


def date_words(claim: Claim) -> str:
    """The claim's date as people write it: 2025, March 2024, 3 March 2024 or date unknown."""
    parts = [int(p) for p in (claim.claim_date or "").split("-") if p.isdigit()]
    precision = claim.date_precision or ("year", "month", "day")[min(len(parts), 3) - 1] if parts else None
    if precision == "day" and len(parts) == 3:
        return f"{parts[2]} {month_name[parts[1]]} {parts[0]}"
    if precision in ("month", "day") and len(parts) >= 2:
        return f"{month_name[parts[1]]} {parts[0]}"
    return str(parts[0]) if parts else "date unknown"


def quote_block(claim: Claim, source: Source) -> Safe:
    """The claim's quote in quote marks, cut at 240 characters, with its source and date under it."""
    text = " ".join(claim.quote.split()).replace('"', "'").replace("“", "‘").replace("”", "’")
    label = source.title or urlsplit(source.url).hostname or source.url
    return h.blockquote(
        f"“{cut(text, 240)}”",
        h.cite(h.a(label, href=f"/sources/{claim.source_id}?claim={claim.id}#quote"), f", {date_words(claim)}",
               class_="fn-quote__cite text-small"),
        class_="fn-quote text-quote",
    )


def person_cards(store: Store, search: Search) -> tuple[list[Safe], bool]:
    """One card per candidate under its section heading, and whether any of them has a place on the map."""
    candidates = store.list_candidates(search.id)
    own = store.claims_of([p for c in candidates for p in c.person_ids])
    by_person: dict[str, list[Claim]] = {}
    for claim in own:
        by_person.setdefault(claim.person_id, []).append(claim)
    persons = store.get_persons([c.person_id for c in candidates])
    sources = store.get_sources(list({c.source_id for c in own}))
    facts = store.get_orgs(list({c.org_id for c in own if c.org_id}))
    places = newest_places(own)

    def card(candidate: Candidate) -> Safe:
        claims = [c for p in candidate.person_ids for c in by_person.get(p, [])]
        place = next((places[p].value for p in candidate.person_ids if p in places), "location not found")
        found, quote = belgian_orgs(claims, facts), evidence(candidate, claims, facts)
        return h.article(
            h.h3(persons[candidate.person_id].display_name, class_="fn-card__name text-name"),
            h.p(" · ".join(x for x in (employer_of(claims), place) if x), class_="fn-card__role text-body"),
            h.p(orgs_line(found), class_="fn-card__ties text-body") if found else None,
            quote_block(quote, sources[quote.source_id]) if quote else None,
            class_="fn-card", data_person=candidate.person_id,
        )

    sections = [[h.h2(title, " ", h.span(f"{len(group):,}"), class_="fn-section text-label"), [card(c) for c in group]]
                for section, title in SECTIONS.items() if (group := [c for c in candidates if c.section == section])]
    return sections, any(p in places for c in candidates for p in c.person_ids)


def sources_read(store: Store, search: Search) -> int:
    """How many records the search's lanes looked at."""
    total = 0
    for step in store.list_steps(search.id):
        output = store.get_payload(step.id)[1] if step.output_model == "LaneOut" else None
        total += LaneOut.model_validate_json(output).total_seen if output else 0
    return total


def notice(store: Store, search: Search) -> Safe:
    """What the page says instead of people: that the search stopped, with Try again, or that it found nobody."""
    if search.status in ("failed", "interrupted"):
        why = "FN was restarted while this search ran" if search.status == "interrupted" else (
            "FN ran into a problem during this search")
        return h.div(
            h.h2("This search stopped", class_="fn-notice__title text-title"),
            h.p(f"{why}, so nothing it found is shown.", class_="text-body"),
            h.form(h.input(type="hidden", name="question", value=search.question),
                   h.button("Try again", type="submit", class_="fn-btn fn-btn--dark text-control"),
                   method="post", action="/searches"),
            class_="fn-notice fn-notice--failed",
        )
    read = sources_read(store, search)
    what = (f"FN read {plural(read, 'source', 'sources')} and found nobody with a Belgian tie for this question."
            if read else "FN found no sources for this question.")
    return h.div(h.h2("No people found", class_="fn-notice__title text-title"),
                 h.p(what, " A broader topic or a wider area may find more.", class_="text-body"), class_="fn-notice")


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
        top = None if found else notice(store, search)
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
    """GeoJSON of the search's people: one point per person from their newest dated location claim, with its quote.

    Each point carries the id of the card it belongs to and that card's employer.
    """
    candidates = store.list_candidates(search.id)
    ordered = [(c, p) for c in candidates for p in c.person_ids]
    person_ids = [p for _, p in ordered]
    own = store.claims_of(person_ids)
    by_person: dict[str, list[Claim]] = {}
    for claim in own:
        by_person.setdefault(claim.person_id, []).append(claim)
    newest = newest_places(own)
    employers = {c.person_id: employer_of([x for p in c.person_ids for x in by_person.get(p, [])]) for c in candidates}
    persons = store.get_persons(person_ids)
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [claim.lon, claim.lat]},
        "properties": {
            "id": candidate.person_id, "name": persons[person_id].display_name,
            "employer": employers[candidate.person_id], "place": claim.value, "quote": claim.quote,
            "claim_date": claim.claim_date, "date_method": claim.date_method,
            "section": candidate.section, "rank": candidate.rank,
            "source_page": f"/sources/{claim.source_id}?claim={claim.id}#quote",
        },
    } for candidate, person_id in ordered if (claim := newest.get(person_id))]
    return {"type": "FeatureCollection", "features": features}


def debug_index_page(searches: list[Search]) -> str:
    rows = [[h.a(s.question[:120], href=f"/debug/searches/{s.id}"), s.status, s.created_at.isoformat()] for s in searches]
    return page("Debug", h.h1("Debug"), table(["Question", "Status", "Created"], rows), debug=True)


def debug_search_page(store: Store, search: Search, message: str | None = None) -> str:
    """The search's facts, chips, steps with their logs and tracebacks, and one card per candidate with how it scored.

    message is a refused chip edit, shown in the chips form.
    """
    steps = store.list_steps(search.id)
    rows = []
    for step in steps:
        calls = store.list_calls(step.id)
        rows.append([
            step.seq, step.step, step.status, duration(step), f"${step.cost_usd:.4f}", step.model or "",
            h.a(f"{len(calls)} calls", href=f"/debug/steps/{step.id}/calls"),
            [h.a("input", href=f"/debug/steps/{step.id}/input.json"), " ",
             h.a("output", href=f"/debug/steps/{step.id}/output.json") if step.output_model else None],
        ])
    details = []
    for step in steps:
        if step.traceback or step.log:
            details.append(h.h3(f"{step.seq} {step.step}"))
            details.append(h.p(f"{step.error_type}: {step.error_message}") if step.traceback else None)
            details.append(h.pre(step.traceback) if step.traceback else None)
            details.append(h.pre(step.log) if step.log else None)
    facts = [
        ["status", search.status], ["created", search.created_at.isoformat()],
        ["finished", search.finished_at.isoformat() if search.finished_at else ""],
        ["code sha", f"{search.code_sha} dirty={search.dirty}"], ["llm mode", search.llm_mode],
        ["boot", search.boot_id], ["rerun of", h.a(search.rerun_of, href=f"/debug/searches/{search.rerun_of}") if search.rerun_of else ""],
    ]
    results = cards(store, search)
    return page(
        "Debug search",
        h.h1(search.question),
        h.p(h.a("results page", href=f"/searches/{search.id}")),
        h.form(h.input(type="text", name="name"), h.button("Trace a person", type="submit"),
               method="get", action=f"/debug/searches/{search.id}/trace"),
        table(["Field", "Value"], facts),
        h.pre(search.error) if search.error else None,
        h.details(h.summary("settings"), h.pre(search.settings_json)),
        chips_form(search, message),
        h.h2("Steps"),
        table(["#", "Step", "Status", "Time", "Cost", "Model", "Calls", "Payloads"], rows),
        details,
        h.h2("Results") if results else None,
        results,
        debug=True,
    )


def calls_page(store: Store, step: StepRun) -> str:
    rows = [
        [c.seq, c.kind, c.request, "" if c.status is None else c.status, f"{c.duration_ms} ms",
         f"{c.tokens_in or 0}/{c.tokens_out or 0}", f"${c.cost_usd or 0:.4f}", c.error or ""]
        for c in store.list_calls(step.id)
    ]
    return page(
        "Step calls",
        h.h1(f"Calls of step {step.step}"),
        h.p(h.a("debug page", href=f"/debug/searches/{step.search_id}")),
        table(["#", "Kind", "Request", "Status", "Time", "Tokens in/out", "Cost", "Error"], rows),
        debug=True,
    )


def trace_rows(store: Store, search: Search, term: str) -> list[list[object]]:
    """Where one person went in each lane, resolve and rank step: considered, kept, dropped and why.

    term is a name, matched by group key, or a lane's person key or a person id. A row found by id adds
    that person's name, so the later steps follow it. A payload stored under another contracts version
    gets a note row instead of being parsed.
    """
    keys = {k for k in [group_key(name_key(term))] if k}
    rows: list[list[object]] = []
    person_ids: list[str] = []
    for step in store.list_steps(search.id):
        model = TRACED.get(step.output_model or "")
        output = store.get_payload(step.id)[1]
        if model is None or output is None:
            continue
        if step.contracts_version != CONTRACTS_VERSION:
            rows.append([step.seq, step.step, "-", "-", f"stored under contracts v{step.contracts_version}, not shown"])
            continue
        out = model.model_validate_json(output)
        found: list[list[object]] = []
        missing = "not present"
        if isinstance(out, LaneOut):
            keys |= {group_key(name_key(c.name)) for c in out.considered if c.person_key == term}
            keys |= {group_key(hit.name_key) for hit in out.hits if hit.person_id == term}
            keys.discard("")
            for c in out.considered:
                if c.person_key == term or group_key(name_key(c.name)) in keys:
                    found.append([c.stage, "kept" if c.kept else "dropped", c.reason])
            for hit in out.hits:
                if (hit.person_id == term or group_key(hit.name_key) in keys) and hit.person_id not in person_ids:
                    person_ids.append(hit.person_id)
            missing = f"not present; query {out.query or '(none)'}"
        elif isinstance(out, ResolveOut):
            for entry in out.entries:
                if entry.name_key in keys or term in entry.person_ids:
                    person_ids += [p for p in entry.person_ids if p not in person_ids]
                    count = len(entry.person_ids)
                    reason = f"{count} record{'s' if count > 1 else ''}, lane ranks {entry.lane_ranks}"
                    found.append(["entry", "kept", f"{reason}; {entry.flag}" if entry.flag else reason])
        elif isinstance(out, RankOut):
            found = [["rank", "kept", f"{c.section} #{c.rank}, score {c.score:.4f}"]
                     for c in out.candidates if c.person_id in person_ids]
        rows += [[step.seq, step.step, *r] for r in found] or [[step.seq, step.step, "-", "-", missing]]
    return rows


def trace_page(store: Store, search: Search, name: str) -> str:
    term = name.strip()
    key = group_key(name_key(term))
    form = h.form(h.input(type="text", name="name", value=name), h.button("Trace", type="submit"),
                  method="get", action=f"/debug/searches/{search.id}/trace")
    rows = trace_rows(store, search, term) if key else []
    return page(
        "Trace",
        h.h1(f"Trace of {name}" if key else "Trace a person"),
        h.p(h.a("debug page", href=f"/debug/searches/{search.id}"), " ", h.a("results page", href=f"/searches/{search.id}")),
        form,
        h.p(f"Group key: {key}; a lane person key or a person id also matches") if key else None,
        table(["#", "Step", "Stage", "Kept", "Reason"], rows) if key else None,
        debug=True,
    )


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


def debug_source_page(source: Source, claim: Claim | None) -> str:
    facts = [["kind", source.kind], ["date", f"{source.source_date or 'none'} ({source.date_method or 'no method'})"],
             ["fetched", source.fetched_at.isoformat() if source.fetched_at else ""], ["content hash", source.content_hash]]
    query = f"?claim={claim.id}#quote" if claim else ""
    return page(
        "Debug source",
        h.h1(source.title or source.url),
        h.p(h.a("source page", href=f"/sources/{source.id}{query}")),
        table(["Field", "Value"], facts),
        h.p(f"Marked: the quote of claim {claim.kind} {claim.value!r} at [{claim.quote_start}:{claim.quote_end}]")
        if claim else None,
        debug=True,
    )


def chips_from_form(form: dict[str, list[str]], source: Chips | None = None) -> Chips:
    """Edited chips from a posted form, without spans; raises ValueError for an oversized chip or list.

    A chip or place whose text matches one of source keeps its ref or kind; an edited text loses it.
    """
    def texts(name: str) -> list[str]:
        found = list(dict.fromkeys(t for t in (" ".join(v.split()) for v in form.get(name, [])) if t))
        if len(found) > MAX_CHIPS or any(len(t) > MAX_CHIP for t in found):
            raise ValueError(f"Keep {name} to {MAX_CHIPS} chips of {MAX_CHIP} characters each.")
        return found

    def chips(name: str, old: list[Chip]) -> list[Chip]:
        refs = {c.text: c.ref for c in old}
        return [Chip(text=t, origin="edited", ref=refs.get(t)) for t in texts(name)]

    place, ask = first(form, "place"), first(form, "ask")
    kind = source.place.kind if source and source.place and source.place.text == place else None
    if len(place) > MAX_CHIP:
        raise ValueError(f"Keep the place to {MAX_CHIP} characters.")
    try:
        return Chips(
            topics=chips("topics", source.topics if source else []),
            institutions=chips("institutions", source.institutions if source else []),
            place=Place(text=place, origin="edited", kind=kind) if place else None,
            ask=ask or None,
        )
    except ValidationError as exc:
        raise ValueError(f"Not a valid ask: {ask!r}") from exc


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


@router.get("/debug/sources/{source_id}")
async def debug_source(request: Request, source_id: str, claim: str = "") -> HTMLResponse:
    return HTMLResponse(debug_source_page(*get_source(request, source_id, claim)))


@router.get("/debug/searches/{search_id}/trace")
async def trace(request: Request, search_id: str, name: str = "") -> HTMLResponse:
    return HTMLResponse(trace_page(store_of(request), get_search(request, search_id), name))


@router.post("/searches/{search_id}/rerun")
async def rerun(request: Request, search_id: str) -> Response:
    source = get_search(request, search_id)
    try:
        chips = chips_from_form(await form_of(request), source.chips)
    except ValueError as exc:
        return HTMLResponse(debug_search_page(store_of(request), source, str(exc)), 400)
    worker = worker_of(request)
    found = worker.create_search(source.question, chips, "edited", rerun_of=source.id)
    worker.submit(found.id)
    return RedirectResponse(f"/searches/{found.id}", 303)


@router.get("/debug")
async def debug_index(request: Request) -> HTMLResponse:
    return HTMLResponse(debug_index_page(store_of(request).list_searches(50)))


@router.get("/debug/searches/{search_id}")
async def debug_search(request: Request, search_id: str) -> HTMLResponse:
    return HTMLResponse(debug_search_page(store_of(request), get_search(request, search_id)))


def get_step(request: Request, step_id: str) -> StepRun:
    step = store_of(request).get_step(step_id)
    if step is None:
        raise HTTPException(404, "No such step")
    return step


def payload(request: Request, step_id: str, index: int) -> Response:
    get_step(request, step_id)
    text = store_of(request).get_payload(step_id)[index]
    if text is None:
        raise HTTPException(404, "This step has no output")
    return Response(json.dumps(json.loads(text), indent=2, ensure_ascii=False), media_type="application/json")


@router.get("/debug/steps/{step_id}/input.json")
async def step_input(request: Request, step_id: str) -> Response:
    return payload(request, step_id, 0)


@router.get("/debug/steps/{step_id}/output.json")
async def step_output(request: Request, step_id: str) -> Response:
    return payload(request, step_id, 1)


@router.get("/debug/steps/{step_id}/calls")
async def step_calls(request: Request, step_id: str) -> HTMLResponse:
    return HTMLResponse(calls_page(store_of(request), get_step(request, step_id)))


@router.get("/debug/errors")
async def request_errors(request: Request) -> HTMLResponse:
    errors = store_of(request).list_request_errors()
    body = [[h.h3(f"{e.route} at {e.at.isoformat()}"), h.pre(e.traceback)] for e in errors] or h.p("No request errors.")
    return HTMLResponse(page("Request errors", h.h1("Request errors"), body, debug=True))


def create_app(settings: Settings, llm: StructuredLLM | None, http: HttpClient | None = None) -> FastAPI:
    """The app for settings, with a store, a worker and the guard middleware; lifespan migrates and sweeps."""
    store = Store(settings.db_path)
    worker = Worker(store, settings, llm, http)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.migrate()
        worker.sweep()
        yield
        worker.shutdown()
        store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.worker = store, worker
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
        return HTMLResponse(error_page(str(exc.status_code), str(exc.detail)), exc.status_code)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = refusal(request)
        if response is None:
            try:
                response = await call_next(request)
            except Exception:  # noqa: BLE001 the guard stores every unhandled request error
                error = redact(traceback.format_exc(), settings.secrets())
                route = f"{request.method} {request.url.path}"
                store.add_request_error(new_id(), route, error, now())
                log.error("request %s failed\n%s", route, error)
                response = HTMLResponse(error_page("Server error", error), 500)
        response.headers.update(SECURITY_HEADERS)
        return response

    return app


def serve() -> None:
    """Run the app on settings.host and settings.port; exits when the host is not loopback."""
    settings = config.from_env()
    if settings.host not in ("127.0.0.1", "::1"):
        sys.exit(f"fn-serve binds 127.0.0.1 or ::1 only, not {settings.host!r}")
    setup_logging(settings)
    uvicorn.run(create_app(settings, from_settings(settings), net.Client(settings)), host=settings.host, port=settings.port, log_config=None)
