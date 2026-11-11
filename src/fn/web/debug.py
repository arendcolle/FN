"""The debug router: every /debug page, the chips form and the rerun of a search with edited chips."""
import json
from typing import get_args
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from fn import orgs, rank
from fn.contracts import (
    CONTRACTS_VERSION,
    Ask,
    Candidate,
    Chip,
    Chips,
    Claim,
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
from fn.store import Store
from fn.web.html import Safe, h, page, table
from fn.web.requests import first, form_of, store_of, worker_of
from fn.web.staff import get_search, get_source

MAX_CHIP = 200
MAX_CHIPS = 20
ASKS = get_args(Ask)
TRACED = {"LaneOut": LaneOut, "ResolveOut": ResolveOut, "RankOut": RankOut}

router = APIRouter()


def duration(step: StepRun) -> str:
    if step.ended_at is None:
        return "running" if step.status == "running" else "-"
    return f"{(step.ended_at - step.started_at).total_seconds():.2f}s"


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
