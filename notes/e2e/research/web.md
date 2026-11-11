# Web layer of FN, as it works today

The web layer is one FastAPI module (`src/fn/web/app.py`, 845 lines) that builds HTML strings with a small escape-by-default helper (`src/fn/web/html.py`, 117 lines), plus static CSS, one JS file for the map and a vendored MapLibre. There are no templates and no front-end build. Every route reads the SQLite `Store` and returns a full HTML page, JSON, or a redirect. The only JS-driven page is the results page, which has a list/map switch and a MapLibre map; a running search is followed by a `<meta http-equiv="refresh">` every 2 seconds, not by JS polling. There is no login: `user_id` exists on `Search` but is always `None`. State-changing requests are guarded by host and origin checks only.

## 1. Routes

All routes live on one `APIRouter` (`src/fn/web/app.py:66`), included at `src/fn/web/app.py:812`. Docs, redoc and openapi are off (`src/fn/web/app.py:810`). HTTP errors render through `error_page` (`src/fn/web/app.py:815-817`).

| Method | Path | Handler (line) | Reads from the store | Returns |
|---|---|---|---|---|
| GET | `/` | `home` (`app.py:669`) | `list_searches(50)`, `count_candidates(ids)` (`app.py:663-666`) | HTML Ask page: question box and recent searches |
| POST | `/searches` | `create` (`app.py:674`) | nothing to read; `worker.create_search` writes, `worker.submit` runs | 303 to `/searches/{id}`; 400 HTML Ask page with a message on an empty or over-1000-character question |
| GET | `/searches/{search_id}` | `show` (`app.py:697`) | `get_search`, then `person_cards` reads candidates, claims, persons, sources, orgs; steps for the empty notice | HTML results page, view `list` |
| GET | `/searches/{search_id}/map` | `show_map` (`app.py:702`) | same as above | same page, view `map` |
| GET | `/api/searches/{search_id}/geo` | `geo_json` (`app.py:707`) | candidates, claims, persons (`geo_features`, `app.py:444`) | JSON FeatureCollection |
| GET | `/sources/{source_id}?claim=` | `show_source` (`app.py:722`) | `get_sources`, `get_claim` (`get_source`, `app.py:712`) | HTML source text with the claim's quote in `<mark id="quote">` |
| GET | `/debug` | `debug_index` (`app.py:750`) | `list_searches(50)` | HTML table of searches |
| GET | `/debug/searches/{search_id}` | `debug_search` (`app.py:755`) | search, steps, calls, candidates, claims, flags, lane payloads, orgs | HTML debug page |
| GET | `/debug/searches/{search_id}/trace?name=` | `trace` (`app.py:732`) | steps and stored payloads | HTML trace table |
| POST | `/searches/{search_id}/rerun` | `rerun` (`app.py:737`) | `get_search`; writes a new search via the worker | 303 to `/searches/{new_id}`; 400 debug page with a message on bad chips; 404 on unknown search |
| GET | `/debug/sources/{source_id}?claim=` | `debug_source` (`app.py:727`) | `get_sources`, `get_claim` | HTML source facts |
| GET | `/debug/steps/{step_id}/input.json` | `step_input` (`app.py:775`) | `get_step`, `get_payload` | pretty-printed JSON, 404 if missing |
| GET | `/debug/steps/{step_id}/output.json` | `step_output` (`app.py:780`) | same, index 1 | JSON, 404 when the step has no output (`app.py:770`) |
| GET | `/debug/steps/{step_id}/calls` | `step_calls` (`app.py:785`) | `get_step`, `list_calls` | HTML table of calls |
| GET | `/debug/errors` | `request_errors` (`app.py:790`) | `list_request_errors` | HTML list of stored tracebacks |
| GET | `/static/*` | `StaticFiles` mount (`app.py:813`) | files on disk | CSS, JS, fonts, style JSON |

Helpers for the routes:

- `get_search` (`app.py:690`) raises 404 "No such search".
- `get_step` (`app.py:760`) raises 404 "No such step".
- `get_source` (`app.py:712`) raises 404 when the source is missing, or when a `claim` is given and is missing or belongs to another source.
- `store_of` and `worker_of` (`app.py:69-74`) read `request.app.state`, set at `app.py:811`.
- `create_app(settings, llm, http)` (`app.py:797`) builds `Store` and `Worker`. The lifespan calls `store.migrate()` and `worker.sweep()` on start and `worker.shutdown()` and `store.close()` on exit (`app.py:802-807`).
- `serve()` (`app.py:839`) exits unless the host is `127.0.0.1` or `::1`, calls `setup_logging`, and runs uvicorn with `log_config=None`.

All handlers are `async def` but call the synchronous `Store` directly.

## 2. How a page is built

Pages are Python strings assembled from nested function calls. There is no template file.

### Helpers in `html.py`

| Name | What it does | Where |
|---|---|---|
| `Safe` | `str` subclass marking already-escaped HTML | `html.py:14` |
| `esc(value)` | escapes anything not `Safe` | `html.py:18` |
| `safe_url(url)` | keeps http, https and relative URLs, else `#`; `//host` and `/\host` become `#` | `html.py:23` |
| `_attrs` | writes attributes: trailing `_` dropped, other `_` become `-`, `True` writes a bare attribute, `None`/`False` drops it, `href`/`src`/`action` pass through `safe_url`, names must match `[a-z][a-z0-9-]*` | `html.py:34` |
| `_children` | skips `None`, flattens lists and tuples, escapes the rest | `html.py:50` |
| `tag(name, *children, **attrs)` | one element; void tags are `input meta link br hr` | `html.py:62`, `VOID` at `html.py:8` |
| `h` | `_Tags()` instance; `h.div(...)` is `tag("div", ...)` for any tag name | `html.py:76-81` |
| `table(headers, rows)` | table with a header row, every cell escaped | `html.py:84` |
| `page(...)` | full document, see below | `html.py:92` |

### Page shell

`page(title, *body, refresh, extra_head, debug, current, body_class)` (`html.py:92-117`) writes `<!doctype html>`, then `head` with charset, viewport, title, optional meta refresh, `extra_head`, then `/static/tokens.css` and `/static/fn.css` (`html.py:99-107`).

- Normal header: a `.fn-header` with the logo link `FN` to `/` and a `.fn-nav` containing one link, `Search` (`html.py:111-116`). `current="search"` sets `aria-current="page"`.
- Debug header (`debug=True`): a bare `<p>` with links to `/debug` and `/debug/errors` (`html.py:109`). The body gets class `fn-debug`.
- `app.py` pages that are not debug pass `current="search"` only on the Ask and results pages. The source page and `error_page` use the normal header with no current link.

### Escaping

Every string child and attribute value is escaped unless it is a `Safe`. `Safe` objects come only from `h.*` calls and `Safe("".join(...))` in `cards` (`app.py:267`). Tests assert hostile text is escaped on every page (`tests/test_web.py:81-125`).

### Typography and CSS

Elements carry two kinds of class: a part class from `fn.css` (`fn-card`, `fn-btn`) and a text class from `tokens.css` (`text-body`, `text-name`). `tokens.css` is "generated from the FN design system's tokens.json" (`tokens.css:1`) and holds fonts, colour, space, radius and width variables. `fn.css` says colours, spacing and radii come from tokens and text size comes from `text-*` classes (`fn.css:1`). A last block, "Site additions", lists rules "to move into the design system" (`fn.css:156-165`).

## 3. How a person card is built

A card is built in the inner `card` function of `person_cards` (`src/fn/web/app.py:369-379`), inside `person_cards` (`app.py:357-383`). One candidate can hold several person records (`candidate.person_ids`); the card pools their claims: `claims = [c for p in candidate.person_ids for c in by_person.get(p, [])]` (`app.py:370`).

Card structure (`app.py:373-379`):

1. `h3.fn-card__name`: `persons[candidate.person_id].display_name`. The display name is the first record's only.
2. `p.fn-card__role`: `" · ".join(x for x in (employer_of(claims), place) if x)`.
3. `p.fn-card__ties`: `orgs_line(found)`, only when `found` is not empty.
4. `quote_block(quote, sources[quote.source_id])`, only when a quote claim exists.
5. The `article` has `class_="fn-card"` and `data_person=candidate.person_id`, the key the map JS uses.

### Role line

- Employer: `employer_of` (`app.py:303-306`). It takes claims whose `relation` is in `EMPLOYED = ("works_at", "worked_at", "affiliated_with")` (`app.py:291`) and returns the `value` of the one with the greatest `(valid_to or claim_date or "", claim_date or "")`. Strings compare as text. It returns `None` when there is none.
- Place: `place = next((places[p].value for p in candidate.person_ids if p in places), "location not found")` (`app.py:371`). `places` is `newest_places(own)` (`app.py:294-300`): per person, the newest `kind == "location"` claim that has a `claim_date`, `lat` and `lon`, sorted by `(claim_date, id)`. A location claim without a date or coordinates is ignored. The first record of the candidate that has a place wins.
- So a card with no employer and no place reads `location not found`.

### Ties line

`belgian_orgs` (`app.py:309-314`) takes every claim whose org has `country_code == "BE"` (`orgs.belgian_claims`, `src/fn/orgs.py:83-88`; any claim kind or relation counts, a claim without `org_id` never does). It groups by `org.name` and collects years from `rank.units(claim)` (`src/fn/rank.py:28`), skipping `"undated"`. It sorts by first year, then name, with orgs without years last (`9999`).

`orgs_line` (`app.py:317-323`) writes the first three as `Name <span class="text-year">2008–2013</span>` joined by ` · `, then ` · +N more`. A single year shows as `2009`, a span as `first–last` with an en dash, and an org with no year shows no span. Years are the first and last of the sorted set, so a gap is hidden: 2001 and 2008 show as `2001–2008`. The card never uses `rank.years_text`, which the debug page uses.

### Quote

- Choice: `evidence` (`app.py:326-331`). The newest Belgian claim by `(claim_date or "", id)`; otherwise the first claim whose id is in `candidate.reason_claim_ids`; otherwise `None` and no quote shows.
- Cut: `quote_block` (`app.py:345-354`) collapses whitespace, replaces `"` with `'`, `“` with `‘` and `”` with `’`, then `cut(text, 240)` and wraps in `“…”`. `cut` (`app.py:114-118`) returns the text if it is at most 240 characters, else it cuts at 240, drops the last partial word with `rsplit(" ", 1)[0]`, strips trailing ` ,;:.` and appends `…`.
- Cite: `<cite class="fn-quote__cite">` holds a link to `/sources/{source_id}?claim={claim_id}#quote` labelled with `source.title`, else the URL hostname, else the URL, then `, ` and the date.

### Dates

`date_words` (`app.py:334-342`) writes `3 March 2024` (day precision), `March 2024` (month, or day with fewer than three parts), `2025` (anything else with a year), or `date unknown`. Precision comes from `claim.date_precision`, else from the number of date parts. Note the expression on line 337 mixes `or` and a conditional; it reads `(claim.date_precision or (...)[...]) if parts else None`.

### Several records of one person

The card shows one name, one role line and one quote. The records are pooled silently; nothing on the card says the person has several records. The debug card does say it: `Same name in N records, not merged: <flag reasons>` (`app.py:233-235`).

## 4. Sections and refresh on the results page

### Sections

- Section is decided in the ranker, not in the web layer: `fuse` sets `"network"` when any of the entry's person records has `list_status == "in_list"`, else `"new"` (`src/fn/rank.py:108`; `statuses` built at `rank.py:120`). Ranks count within a section (`rank.py:109-112`).
- `store.list_candidates` orders network first, then by rank (`src/fn/store.py:394-397`).
- The web layer maps names with `SECTIONS = {"network": "In your network", "new": "New"}` (`app.py:290`). `person_cards` writes an `h2.fn-section` per non-empty group with the count in a `<span>` (`app.py:381-382`). Empty sections get no heading.

### Page states (`search_page`, `app.py:415-441`)

| State | Top element | Cards | Map |
|---|---|---|---|
| queued or running | status line `Searching…` with an animated bar (`app.py:424`) | shown if candidates already exist | shown if any person has a place |
| done with people | none | shown | shown if any has a place |
| done, none found | `notice()`: "No people found" with the number of sources read (`app.py:408-412`) | none | hidden (`fn-results--no-map`) |
| failed or interrupted | `notice()`: "This search stopped" with a Try again form posting the same question to `/searches` (`app.py:397-407`) | none, `person_cards` is not called (`app.py:422`) | hidden |

`placed` (any person with a place) toggles the class `fn-results--no-map` (`app.py:434`).

### Refresh

`refresh=2 if active else None` (`app.py:438`) makes `page()` write `<meta http-equiv="refresh" content="2">` (`html.py:103`). The browser reloads the whole page every 2 seconds while the status is `queued` or `running`; the reload also re-runs `map.js` and re-creates the map. There is no JS polling and no partial update. The switch keeps its view across reloads because it rewrites the URL with `history.replaceState` (`map.js:13`), and the server renders the matching view for `/searches/{id}` or `/searches/{id}/map`.

The recent-searches list on the Ask page has no refresh. It shows `Searching…`, `Failed`, or `N people · when` (`recent_meta`, `app.py:147-153`). `days_ago` (`app.py:121-129`) gives `today`, `yesterday`, `N days ago` (under 7), `last week` (under 14), else `3 March 2026`. `interrupted` is shown as `Failed`.

## 5. The map

### Geo JSON shape

`geo_features` (`app.py:444-470`) returns a GeoJSON FeatureCollection. Order follows candidates (network first, then rank), then `person_ids` within a candidate. One feature per person record whose newest dated location claim has coordinates:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [lon, lat]},
      "properties": {
        "id": "<candidate.person_id>",
        "name": "<display name of this record>",
        "employer": "<employer_of pooled claims, or null>",
        "place": "<location claim value>",
        "quote": "<location claim quote>",
        "claim_date": "<claim_date or null>",
        "date_method": "<date_method or null>",
        "section": "network" | "new",
        "rank": 3,
        "source_page": "/sources/<source_id>?claim=<claim_id>#quote"
      }
    }
  ]
}
```

- `id` is the candidate's lead `person_id`, matching the card's `data-person`. Two records of one candidate share it and can produce two features at two points.
- `name` is the record's own `display_name`, so it can differ from the card name.
- `employer` is pooled over all records of the candidate (`app.py:457`).
- The `quote` here is the location claim's quote, not the card quote.
- Unknown search gives 404 JSON-less HTML via `error_page`.
- `tests/test_map.py:55-81` asserts one point per person with a dated location claim, newest wins, and 404 for an unknown search.

### `map.js` (151 lines)

- Start: `start()` runs unless the container has class `fn-results--no-map` (`map.js:151`). It builds a `maplibregl.Map` with style `/static/positron.json`, center `[0, 30]`, zoom 1, compact attribution, and a zoom-only `NavigationControl` (`map.js:21-24`).
- Data load: on `map.on("load")`, it fetches `element.dataset.geo` (`/api/searches/{id}/geo`) and throws on a non-OK response (`map.js:85-88`).
- Spots: features are grouped by exact coordinate string into `spots` with a `people` list, de-duplicated by `properties.id`. `spotsOf` maps a person id to the set of spot indices (`map.js:89-99`).
- Single person at a point: a GeoJSON source `people` with a circle layer. Radius 7, or 10 when feature-state `big` is true. Fill is the `--accent` token, stroke is `--raised` (`map.js:101-106`). Feature id is `index + 1`.
- Shared point (two or more people): a DOM `maplibregl.Marker` holding a `span.fn-marker.fn-marker--count` with the people count, `aria-label` listing names (`map.js:107-119`).
- Fit: bounds extend over all spots; `fit()` uses padding 64, `maxZoom: 11`, no animation. A `ResizeObserver` resizes the map and fits once if not yet fitted, which handles a map first shown from `display: none` (`map.js:33-38`, `142-146`).
- Ready flag: `element.dataset.ready = String(data.features.length)` (`map.js:147`).

### Hover and pick link between card and dot

- `hoverSpot(index, on)` (`map.js:47-51`) updates a `hovered` set, repaints the dot, and toggles class `is-hot` on every card of that spot.
- Dot to card: mouse move over the circle layer calls `hoverSpot`, and mouse leave clears it (`map.js:121-135`). Count markers use `mouseenter` and `mouseleave` (`map.js:115-116`).
- Card to dot: each card gets `mouseenter` and `mouseleave` that add or remove its spots in `hovered` and repaint (`map.js:137-140`). It does not toggle `is-hot` on the card itself.
- `paint(index)` (`map.js:40-45`): a count marker toggles `is-hot` on its child; a circle sets feature-state `big`. A dot is big when hovered or picked.
- Click: `choose(index)` (`map.js:81-83`). On a wide screen (`min-width: 900px`, i.e. not `(max-width: 899px)`), `pick(index)` marks the spot's cards `aria-current="true"`, clears the previous pick, makes the dot big and scrolls the first card into view (smooth unless reduced motion) (`map.js:53-63`). On a narrow screen, `popup(index)` shows a MapLibre popup (`map.js:65-79`).
- Popup: built with `textContent` (no HTML), one name line (`fn-popup__name text-popup`) and one role line (`employer · place`) per person. It first calls `map.jumpTo` to center the spot, then opens a popup with offset 12 and max width 240px.
- `fn.css` styles: `.fn-card.is-hot` and `aria-current="true"` borders (`fn.css:50-51`), marker classes (`fn.css:96-103`, `161-164`).

### List and Map switch

- The server writes a `nav.fn-switch` with two anchors, `List` to `/searches/{id}` and `Map` to `/searches/{id}/map`, each with `data-view` (`app.py:427-428`). The wrapper `div.fn-results` has `data-view`.
- `map.js:7-15` intercepts clicks, sets `results.dataset.view`, moves `aria-current`, and calls `history.replaceState`.
- The switch is shown only below 900px (`fn.css:91`, `144`). CSS hides the map in `list` view and the list in `map` view (`fn.css:147-148`). At 900px and up the list and map sit side by side in a grid (`fn.css:135`) and `data-view` has no effect.
- `fn.css` also has rules for `.fn-switch button` (`fn.css:92-93`), but the markup uses anchors; the anchor rules are in the last block (`fn.css:159-160`).

### Vendored files

`vendor.json` (12 lines) records `maplibre-gl` 5.24.0, a sha512 integrity of the npm tarball, the style source `https://tiles.openfreemap.org/styles/positron`, and sha256 of `maplibre-gl.js`, `maplibre-gl.css`, `maplibre-gl.LICENSE.txt` and `positron.json`. `tests/test_map.py:18-30` checks each hash and that every URL in the style has host `tiles.openfreemap.org`. The CSP allows `connect-src 'self' https://tiles.openfreemap.org` and `worker-src blob:` (`app.py:57-60`).

## 6. Debug pages

All use `page(..., debug=True)`. They show internal data and are not linked from normal pages.

| Page | Route | Shows |
|---|---|---|
| Debug index | `/debug` (`debug_index_page`, `app.py:473`) | table of the 50 newest searches: question (first 120 characters, linked), status, created time |
| Debug search | `/debug/searches/{id}` (`debug_search_page`, `app.py:478`) | question; link to results page; "Trace a person" form; facts table (status, created, finished, code sha with dirty flag, llm mode, boot id, rerun-of link); error text; settings JSON in `<details>`; chips form; Steps table (seq, step, status, time, cost, model, link to calls, input and output JSON links); per-step log and traceback; one card per candidate |
| Debug card | inside the above (`card`, `app.py:210`) | legend `section #rank name`; score and lane ranks with a trace link; which lane found each record and how; "Same name in N records, not merged" with flag reasons; score parts table (feature, rank, points, detail, claims); Belgian-org claims table (`belgian_rows`, `app.py:190`) with a "Scored" column; one claims table per record |
| Calls | `/debug/steps/{id}/calls` (`calls_page`, `app.py:526`) | per step: seq, kind, request, status, ms, tokens in/out, cost, error |
| Trace | `/debug/searches/{id}/trace?name=` (`trace_page`, `app.py:587`; `trace_rows`, `app.py:541`) | where one person went in each lane, resolve and rank step; matches by group key of the name, a lane person key or a person id; steps stored under another `CONTRACTS_VERSION` get a note row instead of being parsed |
| Debug source | `/debug/sources/{id}?claim=` (`debug_source_page`, `app.py:618`) | kind, date and method, fetched time, content hash, and the marked claim's span |
| Request errors | `/debug/errors` (`app.py:790`) | route, time and traceback of each stored unhandled error |
| Payloads | `/debug/steps/{id}/input.json`, `output.json` | raw stored step JSON, re-indented |

The debug search page is also where the chip edit form lives (`chips_form`, `app.py:270-287`). Production results pages link to nothing under `/debug` (`tests/test_web.py:202-226`).

## 7. Forms, POST handling, validation, auth

### Forms

| Form | Where | Posts to | Fields |
|---|---|---|---|
| Ask | `search_box` (`app.py:132-144`), on the Ask page and the results page | `POST /searches` | `question` textarea, max 1000 characters |
| Try again | `notice` (`app.py:403-405`) | `POST /searches` | hidden `question` |
| Chips | `chips_form` (`app.py:275-287`), debug search page | `POST /searches/{id}/rerun` | repeated `topics`, `institutions` text inputs (an extra blank one each), `place`, `ask` select |
| Trace | debug pages | `GET .../trace` | `name` |

### Parsing and validation

- Forms are parsed by hand: `form_of` (`app.py:96-97`) calls `parse_qs` on the request body with blank values kept. There is no `python-multipart` or pydantic form model. `first` (`app.py:100-101`) returns the first value with whitespace collapsed.
- `create` (`app.py:674-687`): strips the question; empty gives "Type a question", more than `MAX_QUESTION = 1000` gives "Questions are limited to 1,000 characters; this one has N." Either returns HTTP 400 with the Ask page re-rendered, the textarea refilled and the message under it (`aria-invalid`, `aria-describedby`; `app.py:136-139`). Otherwise the search is created and submitted and the response is 303.
- `chips_from_form` (`app.py:633-660`): trims, de-duplicates and drops blanks; at most `MAX_CHIPS = 20` chips of `MAX_CHIP = 200` characters per list, place at most 200; an unknown `ask` (checked against `get_args(Ask)`, `app.py:63`) fails with "Not a valid ask". A chip or place whose text matches the source search keeps its `ref` or `kind`; an edited text loses it. Errors raise `ValueError`; `rerun` returns 400 with the debug page and the message in the chips form (`app.py:741-743`, `284`).
- Both create paths call `worker.create_search(...)` then `worker.submit(id)` (`app.py:685-686`, `745-746`), and the `Worker` runs the pipeline on a thread pool.
- Errors render as plain pages through `error_page` (`app.py:77-78`): title and `<pre>` of the message.

### CSRF and origin

`refusal` (`app.py:81-93`) runs in the `guard` middleware (`app.py:821-834`) for every request not in `SAFE_METHODS = ("GET", "HEAD", "OPTIONS")`.

- Origin must be absent or `http://<Host header>`. `null` is allowed only with `Sec-Fetch-Site: same-origin` (the app sends `Referrer-Policy: no-referrer`, so browsers send `Origin: null` from its own forms).
- `Sec-Fetch-Site` must be absent, `same-origin` or `none`.
- A failure returns 403 "This request comes from another site." No token exists.
- `TrustedHostMiddleware` allows hosts `127.0.0.1`, `localhost`, `[::1]` (`app.py:55`, `819`); others get 400 (`tests/test_web.py:310-314`).
- Every response gets `Content-Security-Policy` (`default-src 'self'`; `img-src 'self' data: blob:`; `connect-src 'self' https://tiles.openfreemap.org`; `worker-src blob:`; `frame-ancestors 'none'`) and `Referrer-Policy: no-referrer` (`app.py:56-62`, `833`). There is no `script-src` or `style-src`, so `default-src 'self'` applies: no inline scripts or styles.

### Auth and user_id

There is no authentication and no session. `Search.user_id: None = None` (`src/fn/contracts.py:134`) is typed as always `None`, and the `searches` table has a `user_id TEXT` column (`src/fn/migrations/001_init.sql:17`). Nothing in `src/fn/web` reads or sets it. The server binds loopback only (`app.py:842-843`).

### Unhandled errors

The guard catches any exception, redacts secrets from the traceback with `redact(..., settings.secrets())`, stores it with `store.add_request_error`, logs it, and returns a 500 page showing the traceback (`app.py:825-832`). The 500 page prints the traceback to the browser by design (`tests/test_web.py:375-389`).

## 8. How the tests drive the app

`tests/test_web.py` (634 lines) and `tests/test_map.py` (99 lines) use `unittest` and `fastapi.testclient.TestClient`.

- Client: `create_app(settings, StubLLM(...), StubHttp())` wrapped in `TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)`, entered with `__enter__` and exited by `addCleanup` so the lifespan runs (`test_web.py:58-63`, `test_map.py:37-40`). The default LLM stub raises if called.
- Helpers from `tests/helpers`: `make_settings`, `make_db`, `make_seeded_db`, `StubLLM`, `StubHttp`, `SECRET`.
- Data: tests insert persons, claims and sources straight through `Store` (`resolve_person`, `upsert_claim`, `create_search`, `save_candidates`) or run a real search through the worker. `create_search` and `run_search` submit to `client.app.state.worker.pool` so the test thread opens no connection of the app's store (`test_web.py:65-73`). `wait_ended` polls the store until the status leaves queued and running (`test_web.py:75-79`).
- Classes: `WebTest`, `SeedCardsTest` (seeded database), `ContractsV1Test` (a database migrated only to 003, then migrated up), `LoggingTest`, `HtmlTest` (pure helper tests), `VendoredMapTest` and `GeoTest`.

### What they assert about HTML

Assertions are substring checks on `response.text`, plus a few `assertRegex` and `html.unescape`. There is no HTML parser.

- Escaping: hostile text appears as `&lt;script&gt;` and never as `<script>`, `<b>` or `href="javascript:` on all pages and on error responses (`test_web.py:81-125`).
- Card: `class="fn-card"` count, the exact `data-person` and `h3` markup, `Nokia Bell Labs · Murray Hill, NJ`, the exact ties string with `<span class="text-year">2001–2004</span>`, `+1 more`, the quote cut (`ran radio…”<cite`), the cite (`>anne-3 page</a>, March 2024</cite>`), `location not found`, `date unknown` (`test_web.py:228-273`).
- The results page hides debug content: no `/debug`, `Score`, `Chips`, `trace`, `Record 1`, `Request errors` (`test_web.py:202-226`).
- Ask page: `Searching…</span>`, `Failed</span>`, `0 people · today</span>` (`test_web.py:289-290`). Notices: `This search stopped`, the hidden question input, `fn-results--no-map`, `No people found` (`test_web.py:291-297`).
- Refresh: `http-equiv="refresh"` present on a queued search and absent when done (`test_web.py:363-373`).
- Map page: exactly 2 `<script` tags, the vendored script and CSS `src`/`href`, and `data-geo="/api/searches/s2/geo"` (`test_map.py:83-95`).
- Security: CSP and `Referrer-Policy` headers on pages, 404s, 400s, host refusals and 403s; cross-site POSTs return 403 and create no search; question limits; chip limits (`test_web.py:299-361`, `436-451`).
- Debug: score line, score parts rows, Belgian claims table cells such as `<td>2013-2018</td>`, step logs and tracebacks, payload links, trace rows, contracts v1 fallback (`test_web.py:127-200`, `316-332`, `391-415`, `491-584`).

Tests do not check CSS, run JS, or test the map in a browser. `map.js` has no test beyond the HTML hooks it needs.

## 9. Static files and cache headers

- `app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")` (`app.py:813`). The directory holds `tokens.css`, `fn.css`, `map.js`, `maplibre-gl.js`, `maplibre-gl.css`, `maplibre-gl.LICENSE.txt`, `positron.json`, `vendor.json` and `fonts/` (11 woff2 files plus three OFL licence files).
- No code in `src/fn/web` sets `Cache-Control`; the only added response headers are the two security headers (`app.py:56-62`, `833`). Starlette's `StaticFiles` adds `ETag` and `Last-Modified` and answers conditional requests with 304, with no `Cache-Control` (Starlette default; not re-checked against the installed version here).
- Fonts are referenced by relative URL `fonts/...` from `tokens.css` (`tokens.css:3-12`) and load from the same origin, which the CSP allows.
- Assets are not fingerprinted; URLs are fixed (`/static/fn.css`). The static mount is behind the same host check and guard middleware as pages.
- `test_web.py:308` checks only that `/static/fn.css` returns 200. `test_map.py` checks the vendored hashes.
