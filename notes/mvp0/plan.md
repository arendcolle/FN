# Build the first FN slice

2026-10-30 · build plan for `notes/mvp0/architecture.md` (version 2.1), revised after the Opus plan review

**Goal.** A local FastAPI app that turns a question into chips, finds people in the five seed lists and in OpenAlex, shows sourced cards and a map, and records every step so a miss can be traced. The approach is the architecture doc as written; this file orders the work.

## Done check

1. `uv run python -m unittest` passes with no skips.
2. `uv run fn-seed` loads 4,940 seed people; a second run changes nothing (`conn.total_changes == 0`).
3. `FN_LLM=record uv run fn-gold GS-02 GS-10` (live OpenAlex, cache written) ranks in the top 10 of their section the 4 picks that `data/gold/reach.json` marks reachable from the question's own chips, misses at most one of them, and names a step and reason for every miss. Then `FN_LLM=record uv run fn-gold` runs all 28 cases.
4. `FN_LLM=replay FN_HTTP=replay uv run fn-gold GS-02 GS-10` gives the same per-pick rows (pick, found, section, rank, tie, lost at) without network access. Timestamps, search ids and costs are left out of the comparison.
5. Headless Playwright screenshots (`uv run --with playwright`, not a project dependency) of `/`, the GS-02 results page, its map and its debug page. A forced failure, `FN_HTTP=replay` with an empty cache, shows the OpenAlex step's traceback on the debug page. A seed person renamed `<img src=x onerror=alert(1)>` in a test database shows as text in the map popup.

## File map

| File | Responsibility | Task |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project, src layout, scripts, `[tool.uv] python-preference = "only-managed"`, Python 3.13; deps fastapi, uvicorn, httpx, pydantic | 1a |
| `src/fn/contracts.py` | every model and Literal, ClaimDraft validator, normalize(), CONTRACTS_VERSION, the `HttpClient` protocol | 1a |
| `src/fn/config.py` | Settings from env; keys from the Keychain (`security find-generic-password`) when the env var is unset | 1a |
| `src/fn/db.py`, `src/fn/migrations/001_init.sql` | connections and the full schema | 1a |
| `src/fn/store.py` | all SQL | 1a, grows in 2 and 3 |
| `src/fn/steps.py`, `src/fn/worker.py`, `src/fn/search.py` | runner, recorder, redaction, logging, lifecycle, step order | 1a |
| `src/fn/llm.py`, `src/fn/prompts/parse.md`, `src/fn/parse.py` | Claude CLI, fixtures, parse step | 1b |
| `src/fn/web/app.py`, `src/fn/web/html.py`, `src/fn/web/static/fn.css` | pages, middleware, error pages | 1c, grows in 2, 3, 4 |
| `data/gold/reach.json`, `tests/fixtures/http/openalex/` | recorded OpenAlex responses for the 9 GS-02 and GS-10 picks; which lane can reach each | 0 |
| `src/fn/seedload.py`, `data/ties.csv`, `src/fn/ties.py` | seed loading with the mapping table, tie rules | 2 |
| `src/fn/lanes/__init__.py`, `src/fn/lanes/seeds.py` | lane protocol, seed lane | 2 |
| `src/fn/resolve.py`, `src/fn/rank.py` | entries per name, flags, fused ranking | 2 |
| `src/fn/net.py`, `src/fn/lanes/openalex.py`, `src/fn/geo.py` | outbound HTTP, OpenAlex lane, place lookup | 3 |
| `src/fn/web/static/maplibre-gl.*`, `positron.json`, `map.js` | map | 4 |
| `src/fn/gold.py` | gold runner | 5 |

## Page ownership

| Page | Task |
| --- | --- |
| `/`, `POST /searches`, `/searches/{id}` (chips and status), `POST /searches/{id}/rerun`, `/debug/searches/{id}`, `/debug/steps/{id}/input.json`, `/output.json`, `/calls`, `/debug/errors` | 1c |
| cards on `/searches/{id}`, `/sources/{id}`, `/debug/searches/{id}/trace` | 2 |
| `/searches/{id}/map`, `/api/searches/{id}/geo` | 4 |

## Tasks

### Task 0: record what OpenAlex returns for the dev picks

- **Builds:** a one-off script `scripts/gold/probe_openalex.py` that calls OpenAlex with the owner's key in the Authorization header, at most 60 calls, and saves each response under `tests/fixtures/http/openalex/`. It covers the 9 picks of GS-02 and GS-10: their author records, the topic works query, and the institution author query `authors?filter=last_known_institutions.ror:https://ror.org/042nb2s44,affiliations.institution.country_code:BE` for MIT. It writes `data/gold/reach.json`: per pick, the lane (seeds, openalex or none), the query path, and reachable yes or no with the evidence.
- **Provides:** recorded fixtures for task 3's tests; reach.json for task 5 and the done check.
- **Hand check:** read reach.json; every pick has a line, and the evidence names a response file.

### Task 1a: steps run and are recorded

- **Builds:** project setup, contracts (complete), config, db and migration, store for searches, steps, payloads, calls and request errors, steps.py, worker.py, search.py running only the parse step, a `python -m fn.search "question"` entry that runs one search in the foreground. The parse step uses a FixtureLLM stub defined in the test.
- **Provides:** `run_step(ctx, name, fn, inp) -> out`, `StepContext`, `HttpClient` protocol, `store.create_search`, `store.get_search`, `store.list_steps`, `worker.submit(search_id)`, `worker.sweep()`.
- **Tests (`python -m unittest tests.test_steps tests.test_worker tests.test_db`):** a failing step stores status error and a traceback, and the search ends failed; a step row exists with status running while the step runs; redaction removes a secret value from payload, traceback, error message and log line; the sweep marks running searches interrupted; an exception outside any step still marks the search failed; migrate() twice is a no-op; FTS5 with the chosen tokenizer exists.
- **Hand check:** `uv run python -m fn.search "test"` with a stub, then `sqlite3 var/fn.sqlite3 "select step, status from step_runs"`.

### Task 1b: the Claude CLI parses a question

- **Uses:** 1a.
- **Builds:** llm.py (ClaudeCli and FixtureLLM with live, record and replay), `prompts/parse.md`, parse.py and its span check.
- **Provides:** `StructuredLLM.structured(task, data, schema) -> LLMResult[T]`, `parse.run(ctx, ParseIn) -> ParseOut`.
- **Tests (`tests.test_llm tests.test_parse`):** replay raises on a missing fixture and names the key; ClaudeCli refuses to run under `FN_ENV=test`; the argv built for a prompt that starts with `--` holds no prompt text, which goes to stdin; a CLI result with `is_error` raises `LLMCallError` with stderr; parse rejects a span that is not in the question and keeps edited chips without spans.
- **Hand check:** one live parse with `FN_LLM=record`; the fixture file appears and the step shows its cost.

### Task 1c: the pages and the debug view

- **Uses:** 1a and 1b.
- **Builds:** html.py, app.py with the routes in the page table, TrustedHostMiddleware, the Origin and Sec-Fetch-Site check, security headers, the exception handlers that store request errors, form parsing with `parse_qs`, logging setup, `fn-serve` (which refuses a host other than 127.0.0.1 or ::1).
- **Tests (`tests.test_web`, TestClient with `base_url="http://127.0.0.1"`):** every page in the table renders `<script>` and `javascript:` inputs escaped; a foreign Host is refused; a cross-site POST is refused; an empty question and a 1,001-character question are refused with a message and create no search; an unhandled route error is stored and shows its traceback; the debug page lists a failed step's traceback.
- **Hand check:** `uv run fn-serve`, ask "Who knows offshore wind near Boston?", see chips; open the debug page and the parse step's call, cost and payloads.

### Task 2: the seed lane returns sourced cards

- **Uses:** 1a to 1c.
- **Builds:** seedload.py with a mapping table (seed relation home to `affiliated_with`, host to `hosted_by`, employer to `works_at`, member_of to `member_of`; seed date methods to `DateMethod`; a null year falls back to `source_date`), `fn-seed`, `store.resolve_person`, source and claim upserts through ClaimDraft, `data/ties.csv` and ties.py, the Lane protocol, lanes/seeds.py, resolve.py with Entries per name_key, rank.py with RRF over entries, the tie, resolve, rank and save steps, the cards, `/sources/{id}` and the trace page.
- **Provides:** `Lane.run(ctx, LaneIn) -> LaneOut`, `ties.label(claims) -> TieLabel`, `store.upsert_source`, `store.upsert_claim(draft)`.
- **Tests (`tests.test_seedload tests.test_seeds_lane tests.test_ties tests.test_resolve tests.test_rank`):**
  - `fts_query` on `e-health`, `C++`, `"6G"`, `AND OR NOT`, an empty chip and Dutch accents raises nothing and matches;
  - every one of the 4,940 seed rows yields a dated claim using only vocabulary values;
  - a second seed load leaves `total_changes == 0`;
  - two seed rows with the same name stay two persons and show as one entry with a flag;
  - tie rules for KU Leuven, KULeuven, VUB, ULB, IMEC, iMinds, Ghent University, TU Delft, MIT and an unknown institution;
  - every institution string with 5 or more seed rows maps in ties.csv or appears on its unmapped list;
  - an "MIT" chip finds Julien de Wit's "M.I.T." row;
  - rank ties break by person id;
  - the GS-10 chips (institution MIT) return Goemans, de Wit and Janjevic as entries.
- **Hand check:** ask the GS-10 question; see the BAEF and Francqui records for Goemans on one card, with quotes, dates and tie labels; open a source and see the quote marked.

### Task 3: OpenAlex finds new people, and misses can be traced

- **Uses:** 0 to 2.
- **Builds:** net.py (Authorization header, timeouts, size cap, recording, cache written in live mode, `FN_HTTP=replay`), the OpenAlex lane with both queries and batched author fetches, geo.py with a cities15000 extract fetched through net.py and a small committed test extract, location claims from institution geo, `considered` lists shown on the trace page.
- **Provides:** `net.Client.get(url, params) -> httpx.Response`.
- **Tests (`tests.test_net tests.test_openalex tests.test_geo`, responses from task 0's fixtures through `httpx.MockTransport`):** the key never appears in a recorded call, payload or log; a 429 with Retry-After over 30 s fails the step and names the wait; replay raises on a cache miss; the recorded Baeyens record (empty last known institutions) becomes one person with an IMEC affiliation claim and place unknown; the recorded Janjevic record gives a ULB claim and a Cambridge location claim, with quotes at their offsets; an author with no Belgian affiliation appears in `considered` with that reason; "New York and New Jersey" resolves to coordinates with a radius.
- **Hand check:** ask the GS-02 question; see the reachable picks from reach.json; open the trace page for a missed pick and read where it was lost.

### Task 4: the map

- **Uses:** 1 to 3.
- **Builds:** vendored MapLibre GL JS (exact 5.x version), with a test that checks the files against the npm registry's `dist.integrity` for that version; a pinned `positron.json` pointing at OpenFreeMap tiles; `map.js` with popups built from DOM text; the map and geo routes.
- **Tests (`tests.test_map`):** the vendored tarball contents match the registry integrity; the geo endpoint returns only entries with a location claim and puts that claim's quote in the properties.
- **Hand check:** the GS-10 map shows Cambridge markers; the popup shows name and quote. The XSS popup check runs in the done check's Playwright pass.

### Task 5: the gold runner

- **Uses:** 0 to 4.
- **Builds:** gold.py and `fn-gold`, reading reach.json for "no lane in slice"; the report and `top5.csv`; dev and held-out split; network and new recall apart; tie agreement.
- **Tests (`tests.test_gold`):** matching by identifier and by name key; found means top 10 of its section; a reachable pick missing from every lane is labelled with the step and reason from the trace; an unreachable pick is labelled "no lane in slice".
- **Hand check:** the done check runs 3 and 4.

## Inputs the spec does not mention

| Input | Expected behaviour | Test in task |
| --- | --- | --- |
| An empty or whitespace question | the form shows "Type a question"; no search is created | 1c |
| A question over 1,000 characters | refused with a message naming the limit | 1c |
| FTS operators, quotes, hyphens or `C++` in a chip | quoted tokens; no SQL error | 2 |
| A question in Dutch | chips in the question's language; spans still checked | 1b |
| A question with only a place | the lanes return no hits and say "no topic or institution chip" in `considered` | 2 |
| Edited chips with every topic and institution removed | same as above | 2 |
| The same question twice in a row | two searches; no new person rows | 2 |
| The Claude CLI missing or logged out | the parse step fails with the CLI's stderr on the debug page | 1b |
| OpenAlex 429, 5xx or timeout | the step fails with status and wait time; the search shows failed | 3 |
| A server restart during a search | the search shows interrupted after restart | 1a |
| Names with accents, particles or capitals | stored as on the page; name_key folds them | 2 |
| An author with no last known institution | kept with "place unknown" | 3 |

## Responsibility table

See the architecture doc; this plan adds no responsibilities. Task 0's probe script is a one-off and owns nothing at run time.

## Not doing

Everything under "Out of scope" and "Not doing" in the architecture doc, plus: no commit, no push, no dependency beyond fastapi, uvicorn, httpx and pydantic. Playwright runs through `uv run --with` for screenshots only.
