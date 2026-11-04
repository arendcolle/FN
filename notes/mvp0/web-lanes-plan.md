# Add the web and LinkedIn lanes

2026-11-03 · build plan for two new lanes on top of PR1, after the owner's answers the same day and four independent plan reviews (code fit, ownership, inputs and tests, vendor facts and safety)

**TL;DR.** Two lanes join seeds and OpenAlex. The web lane sends one Parallel Search call and one Parallel Extract call per search, stores each result page as vendor page text, and asks Haiku for every person each part of a page names, with quotes FN then finds in the stored text. The LinkedIn lane runs the Apify `harvestapi/linkedin-profile-search` actor with the topic, Belgian schools and the metro, and stores each profile as a vendor record with dated education and job claims. Lanes only provide input: they keep everyone they find, and the ranker owns ordering and any cut. net.py learns POST, per-host keys, a body-aware cache and cache-first reads, so LinkedIn spends Apify credit only when switched on and never twice for the same input. fn-gold labels a pick found only on the case's own event page and names the lanes behind every pick.

## Owner decisions (2026-11-03)

- **Quotes come from vendor text.** The web lane quotes Parallel Extract's full page content, and falls back to excerpts for a page Extract could not read. FN does not fetch pages itself in this slice. This reverses the reference doc's "FN fetches every page itself" and "a vendor snippet is stored only for a page FN cannot fetch".
- **LinkedIn spends credit only on purpose.** One or two live runs prove the lane works. After that the lane is off unless `FN_LINKEDIN=1`, and it serves recorded runs for free. How the lane spends once FN goes live is open and not part of this plan. Apify stays on the Free plan.
- **Lanes provide input; the ranker owns ranking and cutting.** The web lane keeps every person a page names, not only people the page ties to Belgium. The LinkedIn lane keeps every profile the actor returns. No lane caps how many people it reads from a page.
- **fn-gold labels event-page finds.** A found pick whose evidence all sits on the case's own event page is reported as `event page`, not `found`.
- **FN calls LinkedIn through Apify.** This reverses the reference doc's "FN itself never logs in to or scrapes LinkedIn" for this lane. FN still never logs in to LinkedIn.

## Test updates that need the owner's OK

Adding two lanes changes what four existing tests assert. None of them weakens a check.

| Test | Today | After |
| --- | --- | --- |
| `tests/test_web.py:333-335` | the step list ends `lane:openalex, resolve, rank, save` | `lane:web` and `lane:linkedin` sit after `lane:openalex` |
| `tests/test_gold.py:157` | a missed pick's lost step is `lane:seeds, lane:openalex` | `lane:seeds, lane:openalex, lane:web, lane:linkedin`, because `gold.lost_at` names every lane that did not see the pick |
| `tests/test_openalex.py:134-135` | `match_claims(..., exclude="seed_page")` and `exclude="record"` | the same assertions with `exclude=("seed_page",)` and `exclude=("record",)` |
| `tests/test_gold.py:86-88` | a pick reach.json calls unreachable takes reach.json's evidence as its lost reason (`"in none of the files"`) | it keeps the trace's step and reason, and reach.json's evidence follows it (task 5) |

## What the vendors give (checked 2026-11-02 and 2026-11-03)

- **Parallel Search.** `POST https://api.parallel.ai/v1/search` with the key in `x-api-key`. The v1 body is `{objective, search_queries, mode}`, with `search_queries` required (1 to 5) and every other setting under `advanced_settings`. The schema refuses unknown fields with a 422. The default is 10 results. Each result has `url`, `title`, a nullable `publish_date` and `excerpts`. The response carries `usage`, a list of `{name, count}` SKUs. Fast mode costs $1 per 1,000 calls with 10 results included. In the 2026-10-29 sweep, fast mode found 5 of 74 held-out picks against Exa's 6, and 200 of 206 excerpt segments matched live page text. `publish_date` was null on 4 of 10 English results.
- **Parallel Extract.** `POST https://api.parallel.ai/v1/extract` with `{urls, objective, advanced_settings: {full_content: {max_chars_per_result}, fetch_policy: {timeout_seconds}}}`. Excerpts cannot be switched off on v1. Each result has `url`, `title`, `publish_date`, `excerpts` and markdown `full_content`. URLs it could not read come back in `errors`. Nothing in the answer says a page was truncated. It costs $1 per 1,000 URLs.
- **Apify.** `POST https://api.apify.com/v2/actors/harvestapi~linkedin-profile-search/run-sync-get-dataset-items` with the token in `Authorization: Bearer`, plus `timeout` and `maxTotalChargeUsd` as query parameters. The sync call waits up to 300 s and answers 201 with the dataset items. A run that is still going at 300 s gets a 408. It reports no cost. The actor charges $0.10 per search page of 25 and $0.004 per full profile. The Free plan allows 10 runs of this actor in total. The account had made 12 by 2026-11-02, and the 12th still ran, so the next run may be refused.
- **The 2026-11-02 run.** It used the async endpoint with GS-02 keywords, 2 schools and 2 locations. It returned 23 profiles in 56 s for $0.192, 1.24 MB in all. Every profile had a Belgian school, education was dated on 21 of 23 and jobs on 23 of 23, and Sweldens and Baeyens were in it. Its input differs from what the lane will send, so it is a shape reference, never a cache entry.
- **Profile shape.** Names are `firstName` and `lastName`. `location` is an object with `linkedinText`. Education entries hold `schoolName`, `degree`, `fieldOfStudy`, `startDate.year` and `endDate.year`. Jobs hold `companyName`, `position`, `location`, `startDate` and `endDate`, with `endDate.text == "Present"` for a current job. `profileTopEducation` and `currentPosition` repeat entries, so the lane reads only `education` and `experience`. `_meta.pagination.totalElements` gives the size of the match.
- **Alias coverage.** Of the Belgian school spellings in that run, the alias file maps "KU Leuven", "Katholieke Universiteit Leuven", "Ghent University", "Universiteit Gent" and "Vrije Universiteit Brussel". It misses "University of Leuven", "Katholieke University Leuven", "Vlerick Business School", "Vlerick Leuven-Gent Management School", "University College Ghent", "EHSAL Management School" and a Sint-Truiden secondary school.

Saved vendor docs, for the builders: `/private/tmp/claude-501/-Users-arend-Developer-FN/9fd61545-661b-4831-85db-cb132421e788/scratchpad/lanes-research/verify-parallel/api-reference_search_search.md`, `.../verify-parallel/extract_api.md`, `.../verify-parallel/extract_advanced.md`, `.../lanes-research/search_search-migration-guide.md`, `.../lanes-research/syncpost.md`, `.../lanes-research/build-search.json` (the actor's input schema) and `.../linkedin-probe/items.json` (the 2026-11-02 run; real people, never committed).

## Design

### net.py

`Client.post(url, body, params=None, *, timeout_s=None, cost=None, keep=None, cache="refresh")` joins `get`. Both go through one private send path with today's rules: https and http only, a 5 MB cap, and every call recorded through the step's recorder.

- **Keys by host.** A table maps `api.openalex.org` to `Authorization: Bearer` with the OpenAlex key, `api.parallel.ai` to `x-api-key` with the Parallel key, and `api.apify.com` to `Authorization: Bearer` with the Apify token. net.py adds a header only on https to that exact host. In live mode, a call out to `api.parallel.ai` or `api.apify.com` without its key raises `MissingKey`, a subclass of `HttpError`, before anything is sent. `prefer` and `only` read the cache first, so a cached answer is served without a key. OpenAlex keeps working without a key, as today.
- **Cache key.** GET keeps `sha256(url)`, so the caches on disk still hit. POST uses `sha256("POST " + url + "\n" + json.dumps(body, sort_keys=True, separators=(",", ":")))`.
- **Cache modes** (`CacheMode` in contracts.py):
  - `refresh` calls out and writes the cache, as GET does today;
  - `prefer` serves the cache when it holds the key, else calls out;
  - `only` serves the cache or raises `CacheMiss` without calling out.
  Every miss that does not call out raises `CacheMiss`, a subclass of `HttpError`, with today's "replay: no cached response for ..." text. That covers replay mode in any cache mode and `only` in live mode.
- **Keeping an answer.** `keep(body) -> bool` lets the caller refuse to cache a 2xx answer, such as an empty Apify list. The call is still recorded and returned.
- **Cost.** `cost(body)` returns dollars or None. It runs only on a live 2xx answer, because the lane knows its vendor's prices. A call served from the cache records `cost_usd = 0.0` and starts its recorded request with `replay` or `cache`. The OpenAlex `meta.cost_usd` path stays for live calls.
- **Recorded request.** A POST records the method, the URL and the compact JSON body, redacted. The debug page then shows which queries or actor input a call sent.
- **Errors.** A non-2xx error message adds the first 300 characters of the response body, redacted.
- **Retries.** GET keeps one retry on 429 or 503 with Retry-After up to 30 s. A POST retries only on 429, which the server sends before it starts any work. A 503 after an Apify run started would otherwise pay for a second run.
- **Timeout.** `timeout_s` replaces the 30 s read timeout for that call. Connect stays 10 s.

`HttpClient` in contracts.py gains the same `post`. Settings gains `parallel_api_key` and `apify_token` (SecretStr, from the env var of that name, else the Keychain) and `linkedin_live: bool` (`FN_LINKEDIN=1`). `secrets()` picks the new keys up because it reads every SecretStr field.

### LLM modes

`FN_LLM` gains `prefer`. FixtureLLM in `prefer` serves a fixture when one exists and calls ClaudeCli otherwise, and it never writes a fixture. The gold runs use it. Parse then comes from the 28 tracked parse fixtures, so the chips are the same on every run and on main, and so the LinkedIn input hashes the same. Extraction runs live on the subscription. `.gitignore` gains `tests/fixtures/llm/extract-*.json`, so a record run cannot commit real page text.

`ClaudeCli` takes its timeout per task from `TIMEOUTS = {"extract": 120}`, with 60 s for any other task. `user_turn` raises `TagError`, a subclass of ValueError, for a value that holds its own closing tag.

### Web lane (`lanes/web.py`)

1. No topic and no institution chip: one `query` note and no call.
2. `request(chips)` is pure. Its `objective` is a sentence built from the chips ("People with a connection to Belgium who work on 6G, telecom in New York and New Jersey"). Its `search_queries` hold one query per topic chip with the place text, then one per institution chip, at most 5. The body is `{objective, search_queries, mode: "fast"}`. The lane builds from chips, not from the question, so an edited chip set changes the query.
3. One Search call. `MissingKey` gives one note and a warning in the log, and the lane returns with no hits. No results gives a note and no Extract call.
4. One Extract call for the result URLs, once each in rank order: `extract_body(urls, objective)` gives `{urls, objective, advanced_settings: {full_content: {max_chars_per_result: 12000}, fetch_policy: {timeout_seconds: 20}}}`, sent with `timeout_s=90`.
5. Each page becomes a Source through a new `contracts.page_source`, of the new kind `vendor_page`. Its text is the Extract `full_content`, else the Extract excerpts, else the Search excerpts, joined by blank lines. A page with none is skipped with a note. `page_source` turns the vendor markdown into plain text before `normalize()`: links become their anchor text, and emphasis, heading markers and backslash escapes go. The quote rule then holds against the stored text. `normalize()` and `NORMALIZE_VERSION` do not change. The id is `sha1("vendor_page\0" + url + "\0" + content_hash)`, so a page whose text changed is stored as a new source. `source_date` is the `publish_date` with `date_method = record_field`. `raw_json` holds the Search result and the Extract result for that URL. A `full_content` that reaches 12,000 characters gets a "may be truncated" note.
6. `extract.mentions` (below) reads each page. Each kept mention becomes a person through `store.resolve_person([extract.identifier(source.url, name)], name)`. A rerun over the same URL finds the same person, even when the page text changed. The same name on two pages gives two records on one card, as the group key already does for seed and OpenAlex records.
7. Hits run in page order, then mention order on the page. A hit's `claim_ids` are the claims drafted for that mention. `matched_on` names the page rank, title and URL. Every mention, page and drop goes into `considered`.
8. The cost function reads `usage` and prices each SKU from a table in the lane. An unknown SKU name logs a warning and gives a cost of None.

### People extraction (`extract.py`, `prompts/extract.md`)

The page reader will need the same thing later, so extraction is its own module, and the web lane calls only its entry points.

- **Chunks.** `mentions(ctx, source)` splits `source.text` into chunks of at most 6,000 characters and sends one structured call per chunk. It splits at paragraph breaks, then at a line break inside a paragraph longer than 6,000 characters, then with a hard cut. A 12,000-character page takes 2 or 3 calls, so a search makes up to 30.
- **The call.** `ctx.llm.structured("extract", {"page": chunk}, PagePeople)`. The schema lives in contracts.py:
  - `PagePeople(people: list[PageMention])`;
  - `PageMention(name, quote, role: str | None, relations: list[PageRelation])`;
  - `PageRelation(relation: Relation, org, quote, year_from: int | None, year_to: int | None)`.
  The prompt asks for every person the chunk names, with each institution or place the text connects them to (Belgian or not, including birthplace and home), and quotes copied character for character.
- **Failures per chunk.** A `TagError`, `LLMCallError`, pydantic `ValidationError` or `FixtureMissing` on one chunk gives a `considered` row with the error type and message, and a warning in the log. The lane goes on to the next chunk. A broken page should not take the seed and OpenAlex results down with it.
- **`locate(text, quote, start=0, end=None) -> tuple[int, int] | None`** is pure. It normalizes the quote, then tries an exact match, then a match that treats any run of whitespace as equal, inside `text[start:end]`. It returns offsets into `text`, and the claim's quote is `text[start:end]`, so the quote rule holds by construction.
- **Checks before a claim is made:**
  - a mention's quote must be found in its chunk, and its folded name must appear in the folded quote;
  - a relation's quote must be found in the 1,500 characters that start at the mention quote's start, so "Jan Peeters, PhD, KU Leuven" keeps its own relation;
  - its folded org text, or a spelling `orgs.names(orgs.org_id(org))` lists, must appear in that quote.
  The nearest-after rule gives each person on a speaker list their own line, even when they share a phrase like "PhD, KU Leuven". Anything that fails is dropped with its reason: "quote not found", "name not in quote", "relation quote not near the mention" or "org not in quote".
- **Names.** `contracts.clean_name` strips leading titles (Prof., Dr., Mr., Ms.) and trailing credentials (PhD, Ph.D., MBA, MD) before the name is used. Both new lanes call it. A mention whose cleaned name has fewer than two tokens is dropped with a reason.
- **`identifier(url, name) -> Identifier`** is `Identifier("mention", f"{url}#{name_key(clean_name(name))}")`. It lives here, so the page reader builds mention identities the same way.
- **`drafts(person_id, source, located) -> list[ClaimDraft]`** gives:
  - one `role` claim per mention, quoting it, with the role as its value, else the page title, else the URL's host;
  - one claim per relation:
    - `affiliation` for institution relations, with `org_id = orgs.org_id(org)`;
    - `location` for `born_in` and `lives_in`, with no coordinates.
  The map already skips location claims without coordinates.
- **Dates.** A claim gets a date only when its quote states one. A year counts only when its four digits appear in the relation's quote. Then the claim gets `valid_from` and `valid_to`, `claim_date` is the later year, the precision is year and `date_method` is the new `stated_in_quote`. Otherwise `claim_date` stays empty, and the ranker counts it as one undated unit. The page's own date stays on the Source and shows on the card. FN never dates a claim by the day it read the page, because "studied at KU Leuven" on a page read in 2026 says nothing about 2026.

### LinkedIn lane (`lanes/linkedin.py`)

1. No topic and no institution chip: one note and no call.
2. `actor_input(chips, area)` is pure, with `area` from `geo.locate`:
   - `searchQuery` is the topic chips joined by " OR ", each multi-word chip in double quotes, else the institution chips the same way.
   - `schools` is `SCHOOLS`: KU Leuven, Ghent University, University of Antwerp, Vrije Universiteit Brussel, Hasselt University, Université libre de Bruxelles, UCLouvain, University of Liège, Vlerick Business School. Every Belgian organization counts the same.
   - `locations` comes from `LOCATIONS`, a table that maps a GeoNames city to LinkedIn location names ("New York City" to "New York City Metropolitan Area" and "New Jersey"; "San Francisco" to "San Francisco Bay Area"; also Boston, Washington, Atlanta, Chicago, Los Angeles, Houston and Seattle). A city that is not in the table sends its city name. A place geo.py cannot locate, or one of kind `abroad`, sends the place text. With no place, or `anywhere_us`, it sends "United States".
   - Double quotes inside a chip are dropped before the chip is quoted.
   - The rest is `profileScraperMode: "Full"`, `takePages: 1`, `maxItems: 25`.
3. The lane calls with `cache="prefer"` when `linkedin_live` is set and `cache="only"` when it is not:
   - On `CacheMiss`, it notes "LinkedIn lane is off and has no recorded run for this input; FN_LINKEDIN=1 runs it live for about $0.20" and returns. On `MissingKey`, it notes the missing token and returns.
   - The call sends `timeout=240` and `maxTotalChargeUsd=0.25` as query parameters with `timeout_s=290`. The actor should then stop inside the sync call's 300 s window and return what it has. The docs do not say so, and a 408 or other 4xx fails the step.
   - `keep` refuses an answer that is not a list holding at least one object with `linkedinUrl`, so an empty or failed run is never served from the cache. The lane notes "Apify returned no profiles; not cached".
   - The cost function estimates $0.10 a page plus $0.004 a profile, and the lane's log line calls it an estimate.
4. `fn-gold` refuses `FN_LINKEDIN=1` unless it runs exactly one case, so one command cannot start 28 paid runs. The guard runs right after `config.from_env()`, before the Store or the Worker exists.
5. Each profile becomes a record Source through `record_source(..., kind="vendor_record")`:
   - The URL is `canonical(linkedinUrl)`: https, `www.linkedin.com`, no trailing slash.
   - It has one `path: value` line per field used:
     - `firstName`, `lastName`, `headline` and `location.linkedinText`;
     - each `education.i` school, degree, field and start and end years;
     - each `experience.i` company, position, location and start and end.
   - `source_date` is `_meta.scrapedAt`'s day.
   - A profile without `linkedinUrl` is skipped with a note.
6. The person comes from `resolve_person([Identifier("profile_url", url)], clean_name(f"{firstName} {lastName}"))`.
7. Each education entry gives an `affiliation` claim, `studied_at`, at `orgs.org_id(schoolName)`. Each job gives `works_at` when its end is "Present", else `worked_at`, at `orgs.org_id(companyName)`. A claim quotes that entry's lines. It takes `valid_from` and `valid_to` from the start and end years, and a current job runs to the scrape year. `claim_date` is the end year, or the scrape year for a current job, with `record_field`. An entry without any year has no `claim_date`, which the ranker counts as one undated unit.
8. Hits are every profile in the actor's order, and a hit's `claim_ids` are its education and job claims. `considered` gets:
   - one row per profile;
   - "read N of totalElements profiles";
   - one note per school spelling that maps to no org id, so the owner can add it to the alias file.

### Seed lane scope

`store.match_claims(query, exclude="record")` would match the new vendor claims too. That would make seed ranks depend on past web and LinkedIn searches, which is why the seed lane excludes OpenAlex records today. `match_claims` takes `exclude: tuple[SourceKind, ...]`, implemented with `s.kind NOT IN (SELECT value FROM json_each(?))`. The seed lane passes `("record", "vendor_record", "vendor_page")`. Page sources stay searchable, so the seven tests that build seed fixtures on `page` sources pass unchanged.

### fn-gold

- `GoldCase` gains `source_url` from the gold set's `source`.
- **Event page.** `judge` gets the reason sources' kinds and URLs from `run_case`, as a new argument with an empty default, so the existing `judge` calls in the tests keep working. It labels a pick `event page` when the pick would be found, it has at least one reason source, and every reason source is of kind `vendor_page` or `page` at the event page's URL. URLs compare by host, with a leading `www.` removed, and path, with no query or fragment. A page elsewhere on the same news site, or a LinkedIn profile that the web lane or the LinkedIn lane stored, is other evidence, although 13 cases have a `linkedin.com/posts` source. gold.py reads source kinds and URLs, and never a lane's URL format. The dev measure counts `event page` as not found, and the summary table gains an "Event page" column.
- **Lanes per pick.** The report names the lanes behind every found pick, from `lane_ranks`, and gives the cost of each search as the sum of its step costs. `PickResult` gains `lanes: str` and `CaseResult` gains `cost_usd: float`.
- **Unreachable picks.** reach.json was recorded for seeds and OpenAlex only. A pick it calls unreachable that no lane found keeps the trace's lost step and reason, and reach.json's evidence follows it.
- `PickVerdict` gains `event page`.

### Search order

```diff
 search.run(ctx)
   run_step("parse")
   run_step("lane:seeds")        -> store.match_claims(query, exclude=("record", "vendor_record", "vendor_page"))
   run_step("lane:openalex")
+  run_step("lane:web")
+    http.post(parallel /v1/search)
+    http.post(parallel /v1/extract, timeout_s=90)
+    per page: page_source -> store.upsert_source
+      per chunk: extract.mentions -> llm.structured("extract") -> extract.locate
+      per mention: store.resolve_person(extract.identifier) -> extract.drafts -> store.upsert_claim
+  run_step("lane:linkedin")
+    http.post(apify run-sync-get-dataset-items, cache=prefer|only, keep=profiles)
+    per profile: record_source(vendor_record) -> store.resolve_person(profile_url) -> store.upsert_claim
   run_step("resolve")
   run_step("rank")
   run_step("save")
```

## Responsibility table

| Responsibility | Owner |
| --- | --- |
| Outbound GET and POST, the key header per host, missing keys, the cache key, cache modes, retries, error text, timeouts | `net.py` |
| Prices for vendors that report no cost, passed to net.py as a cost function; net.py reads OpenAlex's own `meta.cost_usd` | the lane that calls the vendor |
| Whether an answer is worth caching, passed to net.py as `keep` | the lane that calls the vendor |
| When the LinkedIn lane may spend | `Settings.linkedin_live`, read by `lanes/linkedin.py`; `fn-gold` refuses it for more than one case |
| Parallel requests, and result pages as `vendor_page` Sources | `lanes/web.py` |
| Vendor markdown to plain page text | `contracts.page_source` |
| Page text to named people, located quotes, mention identity and claim drafts | `extract.py` with `prompts/extract.md` |
| Offsets of an LLM quote in a page | `extract.locate` (seedload keeps its own offsets for seed rows) |
| Titles and credentials off a person's name | `contracts.clean_name` |
| Actor input from chips, and profiles to Sources, people and claims | `lanes/linkedin.py` |
| Place chip to a city | `geo.py` (unchanged); `lanes/linkedin.py` maps the city to LinkedIn's names |
| Fixture or live per LLM call | `llm.py`, by `FN_LLM` |
| Spelling to institution id, for schools and employers too | `orgs.py` with `data/org_aliases.csv` |
| Ordering entries and any cut | `rank.py` (unchanged) |
| Which sources the seed lane searches | `lanes/seeds.py`, through `store.match_claims(exclude=)` |
| The event-page label, lanes per pick, cost per search | `gold.py` |

## File map

| File | Change |
| --- | --- |
| `src/fn/net.py` | `post`, one send path, the host key table, `MissingKey`, `CacheMiss`, cache modes, `keep`, cost only on live calls, the recorded body, the error body, POST retries, `timeout_s` |
| `src/fn/config.py` | `parallel_api_key`, `apify_token`, `linkedin_live`; `from_env` reads them |
| `src/fn/llm.py` | `prefer` mode, `TIMEOUTS`, `TagError` |
| `src/fn/contracts.py` | `HttpClient.post`, `CacheMode`; `LLMMode` adds prefer; `LaneName` adds web and linkedin; `SourceKind` adds vendor_page; `IdentifierScheme` adds mention; `DateMethod` adds stated_in_quote; `PickVerdict` adds event page; `page_source`; `record_source(kind=)`; `clean_name`; `PagePeople`, `PageMention`, `PageRelation`, `Located`; `GoldCase.source_url`, `PickResult.lanes`, `CaseResult.cost_usd` |
| `src/fn/lanes/web.py` | new |
| `src/fn/extract.py`, `src/fn/prompts/extract.md` | new |
| `src/fn/lanes/linkedin.py` | new |
| `src/fn/lanes/__init__.py` | `LANES = [seeds, openalex, web, linkedin]` |
| `src/fn/lanes/seeds.py`, `src/fn/store.py` | `match_claims(query, exclude=tuple)` |
| `src/fn/gold.py` | the event-page label, lanes per pick, cost per search, unreachable reasons, the `FN_LINKEDIN` guard |
| `data/org_aliases.csv`, `data/org_aliases_unmapped.txt`, `tests/fixtures/http/ror/` | the Belgian school spellings above; a ROR fixture for each new id |
| `tests/helpers.py` | `StubHttp.post`, which records the call, raises `net.CacheMiss` for `cache="only"`, and otherwise answers `{"results": []}`. `make_settings` stays without Parallel and Apify keys |
| `tests/test_net.py`, `tests/test_llm.py`, `tests/test_web_lane.py`, `tests/test_extract.py`, `tests/test_linkedin.py`, `tests/test_gold.py`, `tests/test_seeds_lane.py` | new tests |
| `tests/test_web.py`, `tests/test_gold.py`, `tests/test_openalex.py` | the four updates in "Test updates that need the owner's OK" |
| `tests/fixtures/http/web/`, `tests/fixtures/http/linkedin/` | invented pages and profiles, tracked; `tests/fixtures/http/web/v1_fields.json` holds the property names of the saved V1SearchRequest, V1ExtractRequest and their advanced settings |
| `.gitignore` | `tests/fixtures/llm/extract-*.json` |
| `notes/mvp0/architecture.md`, `notes/research/mvp-tech-reference.md`, `notes/mvp0/progress.md` | task 6 |

The repo is public. Tracked fixtures hold invented people only. A builder who keeps a real response stores it under `var/recorded/`, which git ignores and `tests/test_done_check.py` does not scan. That test scans every file under `src/` and `tests/`, ignored ones too, so real page text never goes there. The prompt and the invented fixtures avoid the words the test forbids. Every whole-search test keeps working because test settings carry no Parallel or Apify key. In live mode the web lane then gets `MissingKey` before any call, and the LinkedIn lane gets `CacheMiss`.

## Tasks

Each task is one commit. The tests run with `uv run python -m unittest`, and a task is done when the whole suite passes. Every test that serves a call from the cache asserts that the transport was not called. Every lane test asserts the exact claim set (kind, relation, org id, offsets), because the quote rule alone passes with zero claims.

### 1. net.py POST, keys and cache modes; the LLM prefer mode

- **Files:** `net.py`, `config.py`, `llm.py`, `contracts.py` (`HttpClient.post`, `CacheMode`, `LLMMode`), `tests/helpers.py`, `tests/test_net.py`, `tests/test_llm.py`, `.gitignore`.
- **Provides:**
  - `net.Client.post(url: str, body: dict, params: dict[str, str] | None = None, *, timeout_s: float | None = None, cost: Callable[[bytes], float | None] | None = None, keep: Callable[[bytes], bool] | None = None, cache: CacheMode = "refresh") -> httpx.Response`;
  - `net.CacheMiss(HttpError)` and `net.MissingKey(HttpError)`;
  - `Settings.parallel_api_key`, `Settings.apify_token` and `Settings.linkedin_live`;
  - `FixtureLLM` in `prefer`, `llm.TIMEOUTS` and `llm.TagError`;
  - `StubHttp.post`.
- **Tests (MockTransport):**
  - POST bodies that differ get different cache files, and the same body hits the same file;
  - a replayed POST serves its file, and a replay miss raises `CacheMiss`;
  - `x-api-key` goes only to `https://api.parallel.ai`, and Bearer only to `https://api.apify.com` and `https://api.openalex.org`; nothing goes to an http URL or another host;
  - a live POST to Parallel or Apify without its key raises `MissingKey` with no transport call;
  - the recorded request holds the body and never a key, and the error never holds a key;
  - `only` raises `CacheMiss` without a transport call, and `prefer` serves a file without one;
  - `keep` returning false leaves no cache file;
  - `cost` is recorded on a live call, and a cache-served call records 0;
  - a 402 body appears in the error;
  - a POST answered 503 makes one transport call, and a 429 with Retry-After makes two;
  - `timeout_s` reaches the request;
  - GET cache file names do not change;
  - `FixtureLLM("prefer")` serves a fixture and calls the CLI stub on a miss without writing a file;
  - `user_turn` raises `TagError`.
- **Hand check:** a scratch script in the scratchpad runs one step through `run_step` on a throwaway store with a search row, as `tests/test_net.py:27-42` does, and sends one live Parallel Search POST, `{"objective": "Belgian 6G researchers", "search_queries": ["6G Belgian"], "mode": "fast"}`. It prints the status, the recorded request, the `usage` SKU names and the cache file. This costs $0.001.

### 2. Web lane: Search and Extract to page sources

- **Files:** `lanes/web.py`, `lanes/__init__.py`, `contracts.py` (`LaneName` web, `SourceKind` vendor_page, `page_source`), `tests/test_web_lane.py`, `tests/fixtures/http/web/`, `tests/test_web.py` and `tests/test_gold.py:157` (owner-approved updates).
- **Uses:** `post`, `CacheMiss` and `MissingKey` from task 1.
- **Provides:**
  - `web.request(chips) -> dict`;
  - `web.extract_body(urls, objective) -> dict`;
  - `contracts.page_source(url: str, title: str | None, markdown: str, raw: dict, fetched_at: datetime, source_date: str | None) -> Source`.
- In this task the lane stores page sources and returns no hits. `considered` lists each page.
- **Tests:**
  - the keys of `request()` and `extract_body()`, nested keys under `advanced_settings` included, are a subset of the names in `v1_fields.json`, so an extra key fails without a network call;
  - `request` for chips with topics and a place, with only institutions, and with only a place;
  - the lane with invented recorded responses stores one Source per unique URL;
  - Extract text first, then Extract excerpts, then Search excerpts for a URL in `errors`;
  - a page with no text is noted;
  - the same URL with changed text stores a second Source and raises nothing;
  - `page_source` turns `[Wim Doe](https://x) is **professor**` into `Wim Doe is professor`;
  - a 12,000-character `full_content` gets the truncation note;
  - no key in live mode gives a note and no transport call;
  - the cost function prices the fixture's `usage`, and an unknown SKU gives None and a warning.
- **Hand check:** run the GS-02 question live with `FN_LLM=prefer uv run python -m fn.search "<GS-02 question>"`. Then open `/debug/searches/<id>`: `lane:web` shows two calls with their bodies and costs, and `/sources/<id>` shows a page's plain text. Fill the SKU price table from the Search SKUs of the task 1 hand check and the Extract SKUs of this call, then rerun so both calls show a cost. This costs about $0.022.

### 3. People extraction and web hits

- **Files:** `extract.py`, `prompts/extract.md`, `lanes/web.py`, `contracts.py` (`PagePeople`, `PageMention`, `PageRelation`, `Located`, `clean_name`, `IdentifierScheme` mention, `DateMethod` stated_in_quote), `store.py` and `lanes/seeds.py` (`match_claims(exclude=tuple)`), `tests/test_extract.py`, `tests/test_web_lane.py`, `tests/test_seeds_lane.py`, `tests/test_openalex.py:134-135` (owner-approved update).
- **Uses:** `page_source` and the lane from task 2; `TagError`, `TIMEOUTS` and `FixtureMissing` from task 1.
- **Provides:**
  - `extract.locate(text: str, quote: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None`;
  - `extract.mentions(ctx: StepContext, source: Source) -> tuple[list[Located], list[Considered]]`;
  - `extract.identifier(url: str, name: str) -> Identifier`;
  - `extract.drafts(person_id: str, source: Source, located: Located) -> list[ClaimDraft]`;
  - `contracts.clean_name(name: str) -> str`.
  - `Located` is a frozen model with the cleaned name, the mention's offsets and its kept relations with offsets.
- **Tests:**
  - `locate`: exact, across a line break, with a curly apostrophe, missing, and inside a range;
  - two people on one page who share "PhD, KU Leuven" get different offsets, each after their own name;
  - a StubLLM answer over an invented page gives the exact expected claims;
  - a relation whose org is not in its quote is dropped;
  - a mention whose name is not in its quote is dropped;
  - a year not in the quote leaves `claim_date` empty, and `rank.units` gives one undated unit;
  - "KU Leuven" gets `ror:05f950310`;
  - `born_in` gives a location claim with no coordinates;
  - a page of 13,000 characters makes at least three calls, each with at most 6,000 characters, and one 7,000-character paragraph is split at a line break;
  - an `LLMCallError` on one chunk leaves the other chunk's people stored and the step ok, with a note;
  - a page holding `</page>` gives a `TagError` note, with a stub that calls `llm.user_turn` as ClaudeCli and FixtureLLM do (StubLLM never calls it);
  - a rerun of the lane adds no person, source or claim;
  - "Prof. Dr. Jan Peeters, PhD" becomes "Jan Peeters";
  - a one-word name is dropped;
  - a vendor_page or vendor_record claim matching a seed query is not a seed hit, and a page-source claim still is.
- **Hand check:** the GS-02 search with `FN_LLM=prefer`. Open the trace for "Sweldens" and "Baeyens" and the cards of the web hits. Report the time `lane:web` took and how many mentions and relations `considered` dropped, by reason. Haiku runs on the subscription, and Parallel costs about $0.011.

### 4. LinkedIn lane

- **Files:** `lanes/linkedin.py`, `lanes/__init__.py`, `contracts.py` (`LaneName` linkedin, `record_source(kind=)`), `gold.py` (the `FN_LINKEDIN` guard), `data/org_aliases.csv`, `data/org_aliases_unmapped.txt`, `tests/fixtures/http/ror/`, `tests/test_linkedin.py`, `tests/fixtures/http/linkedin/`, `tests/test_web.py` and `tests/test_gold.py:157` (owner-approved updates for `lane:linkedin`).
- **Uses:** `post`, `keep`, `CacheMiss`, `MissingKey`, `linkedin_live`, `record_source`, `clean_name` and `geo.locate`.
- **Provides:**
  - `linkedin.actor_input(chips, area) -> dict`;
  - `linkedin.canonical(url: str) -> str`;
  - `linkedin.SCHOOLS` and `linkedin.LOCATIONS`.
- **Tests (invented profiles in the 2026-11-02 shape):**
  - `actor_input` on the GS-02 parse fixture's chips gives "New York City Metropolitan Area" and "New Jersey", and quotes multi-word topics;
  - `actor_input` for `anywhere_us`, no place, a city not in the table, a place geo.py cannot locate, `abroad`, a chip holding a double quote, and institution-only chips;
  - the exact claims for one profile;
  - an education entry dated 1990 to 1994 gets `valid_from` 1990 and `valid_to` 1994;
  - a job from 2015 to Present scraped 2026-11-02 is `works_at` with units 2015 to 2026;
  - an undated entry has no `claim_date`;
  - an unmapped school is noted;
  - lane off with no cache file gives a note and no transport call, and lane off with a cache file serves it with no transport call;
  - an empty answer is not cached, and an answer where one profile lacks `linkedinUrl` is;
  - a rerun with the same chips makes no second transport call;
  - "linkedin.com/in/x/" and "https://www.linkedin.com/in/x" are one person;
  - `record_source` without `kind` keeps today's ids;
  - `fn-gold` with `FN_LINKEDIN=1` and two cases exits before any search. The test sets `FN_VAR` to a temp dir and `FN_HTTP` and `FN_LLM` to replay, and patches `run_case` to raise, so a broken guard cannot spend.
- **Alias file:**
  - Add the missing Belgian school spellings above. Spellings of KU Leuven map to `ror:05f950310`.
  - Look up the ROR ids for Vlerick, HoGent and EHSAL's successor on the ROR API. Add each new id's ROR record to `tests/fixtures/http/ror/`, because the seeded test database runs fn-orgs over the alias file.
  - List the secondary school in `org_aliases_unmapped.txt`.
- **Hand check (live, about $0.20, run by the lead, not a builder):**
  1. Print `actor_input` for the GS-02 chips and check it.
  2. Run `FN_LLM=prefer FN_LINKEDIN=1 uv run fn-gold GS-02` once. The cards should show Sweldens and Baeyens with dated KU Leuven claims. The 2026-11-02 run had them, but this input differs, so it is not a given.
  3. Run `FN_LLM=prefer uv run fn-gold GS-02` with the lane off. It serves the same run from the cache, with no transport call and $0 on the call.
  If Apify refuses the run, the LinkedIn result is reported as not run.

### 5. fn-gold: event page, lanes, cost and unreachable reasons

- **Files:** `gold.py`, `contracts.py` (`PickVerdict`, `GoldCase.source_url`, `PickResult.lanes`, `CaseResult.cost_usd`), `tests/test_gold.py` (new tests and the `:86-88` update).
- **Tests:**
  - a found pick whose reason sources are all vendor_page sources at the event page's URL is `event page`;
  - the same with `www.` on one side only, or a query string on one side, is still `event page`;
  - one more reason source at another URL makes it `found`, and so does another page on the event page's host;
  - a LinkedIn-only find in a case whose source is a `linkedin.com/posts` URL is `found`;
  - a web-lane vendor_page at `linkedin.com/in/x` on a `linkedin.com/posts` case is `found`;
  - a pick with no reason claims is never `event page`;
  - a case without a source is unchanged;
  - the dev measure does not count `event page`, and the summary has the column;
  - the report names the lanes behind a found pick and gives the cost of each search;
  - an unreachable missed pick keeps the trace's step and reason, followed by reach.json's evidence.
- **Hand check:** rerun `FN_LLM=prefer uv run fn-gold GS-02` (LinkedIn served from the cache) and read the report.

### 6. Docs and the gold comparison

- **Files:**
  - `architecture.md`: vocabularies, models, the lanes, outbound calls, LLM access, the responsibility table and out of scope. Acceptance criterion 5 changes to "a date with its method, or undated when the source states none".
  - `mvp-tech-reference.md`: the decisions and the two reversed Not-doing lines.
  - `progress.md`.
- **Check:** the done check below.

## Inputs the spec does not mention

| Input | Behaviour | Task |
| --- | --- | --- |
| A question with only a place chip | both lanes note it and make no call | 2, 4 |
| No Parallel key or no Apify token | `MissingKey` before any call; the lane notes it and the search goes on | 1, 2, 4 |
| Parallel returns no results | no Extract call, one note | 2 |
| The same URL twice in the results | one Source, the first rank | 2 |
| A page Extract cannot read | its Extract or Search excerpts are used; with neither, the page is skipped with a note | 2 |
| Extract slower than 90 s | the call fails with its timeout and the step fails, as any vendor error does | 1, 2 |
| A page that reaches 12,000 characters | a "may be truncated" note | 2 |
| A PDF result | quoted from Extract's text like any page | 2 |
| Page text that changed since the last search | a new Source; the same mention person | 2, 3 |
| A Parallel 402 (credit gone) or 422 | the step fails with the body's message | 1, 2 |
| A quote with markdown links or emphasis | stored text is plain, so the quote matches | 2, 3 |
| A chunk whose text holds `</page>` | `TagError` note; the next chunk goes on | 3 |
| An LLM timeout or a schema-breaking answer on one chunk | a note with the error; the next chunk goes on | 3 |
| A quote the model changed | that mention or relation is dropped with its reason | 3 |
| Several people sharing one phrase | each relation quote is the nearest after its own person | 3 |
| An org the quote does not name | the relation is dropped | 3 |
| The same person twice on one page | one person, both sets of claims | 3 |
| A year the quote does not state | no `claim_date`; one undated unit | 3 |
| A page naming 200 people | every one, over as many chunks as the text needs | 3 |
| One paragraph longer than 6,000 characters (PDF or table text) | split at a line break, else cut hard | 3 |
| A place geo.py cannot locate, or a place abroad | the place text goes to LinkedIn as is | 4 |
| A chip holding a double quote | the quote is dropped before the chip is quoted | 4 |
| A name with titles, credentials or one word | titles and credentials stripped; a one-word name dropped | 3, 4 |
| A profile without `linkedinUrl` | skipped with a note | 4 |
| One profile URL in two spellings | one person | 4 |
| More matches than one page of 25 | the first 25; the note gives totalElements | 4 |
| An undated education entry | no `claim_date`; counts as undated | 4 |
| An empty Apify answer | not cached; noted | 1, 4 |
| An Apify refusal (Free run cap, credit gone) | the step fails with the body's message | 4 |
| The same LinkedIn input twice | served from the cache the second time | 4 |
| `FN_LINKEDIN=1` with a 28-case fn-gold | refused before any search | 4 |
| A case without a `source` | no event-page check | 5 |
| A LinkedIn profile on a case whose source is a LinkedIn post | not an event page | 5 |

## Not doing

- FN's own page reader, Parallel Decisions, Task and FindAll.
- Dutch query rows and `source_policy` domain lists.
- Calling Parallel, Extract or Haiku concurrently. A search can make 30 Haiku calls in a row. Task 3's hand check measures how long that takes.
- LinkedIn company filters, which need LinkedIn company URLs, and institution chips as filters. A second run filtered by past Belgian employers (imec, Nokia Antwerp) would reach people with a Belgian job and no Belgian degree, and is the follow-up once Apify has budget.
- Location claims from LinkedIn profiles. The map still shows OpenAlex locations only.
- Other Apify actors, such as the profile scraper by URL and the Google search scraper.
- Moving the OpenAlex lane's Belgian-affiliation filter into the ranker. The owner raised it as a maybe. It changes GS-10 ranks, so it gets its own change with a gold comparison.
- A cut in rank.py. No requirement asks for one yet.
- Catching other pages about the same event. The event-page rule compares the page's URL.
- Updating reach.json, a local file recorded for seeds and OpenAlex. fn-gold prints the trace's reason next to it instead.
- A spend limit across searches for Parallel. A gold run of 28 cases costs about $0.31.
- Turning a vendor refusal (a 402, a 422, an Apify refusal) into a note. It fails the step and the search, as an OpenAlex error does today.

## Done check

1. `uv run python -m unittest` passes, with every failure named if not.
2. **Setup.** The main side uses `/Users/arend/Developer/FN/.claude/worktrees/fn-main-baseline`, detached at main's sha. The branch side is a new worktree detached at the branch's final sha. Each has its own copy of `data/gold/`, `data/seeds/*.jsonl`, `data/seeds/raw/` and `tests/fixtures/http/openalex/`, and its own `var/` with fn-seed and fn-orgs run. If task 4's live run happened, the branch side's `var/cache` also gets its Apify file, copied in.
3. **The runs.** `FN_LLM=replay uv run fn-gold` on main and `FN_LLM=prefer uv run fn-gold` on the branch, all 28 cases, LinkedIn off. Parse comes from the same tracked fixtures on both sides, so the chips match. The comparison shows, per case:
   - picks found, missed and labelled `event page`;
   - which lane found each pick;
   - cost per search.
   Main's gold report has no lanes or cost, so those numbers come from `lane_ranks` in main's candidates and the step costs in main's `var/fn.sqlite3`.
4. **The target.** At least 2 of the 4 GS-02 picks `found` in the top 10, against 0 on main. Picks labelled `event page` do not count toward it, and the report gives both numbers. A miss is reported, not tuned for.
5. **No regression.** The dev success measure stays at 3 or more of the 4 reachable dev picks, as on main, and no pick main finds is missed on the branch. The web lane adds many people to section `new`, so this checks that they do not push known picks out of the top 10.
6. **Screenshot.** The GS-02 results page shows a web card with its quote marked on the source page, and a LinkedIn card with dated KU Leuven claims. If the live run was refused, the LinkedIn part is reported as not run.
7. **Spend.** Total vendor spend for the build is reported: Parallel under $1, Apify under $0.50 in at most two runs.

## Build decisions

- **Task 1.** The POST cache key holds the full request URL with its query parameters, so a later change to Apify's `timeout` or `maxTotalChargeUsd` makes a new cache entry. A call that a caller's `keep` or `cost` function breaks is still recorded, with the error, and leaves no cache file. Cache files are written to a temporary file and renamed into place.
- **Task 2.** A replay run with no recorded Parallel answer fails `lane:web` with `CacheMiss`, as a replay miss fails the OpenAlex lane. A quiet note would let a replayed gold run pass with no web results. A gold run that should include the web lane runs with `FN_HTTP` live.
- **Task 2.** Parallel bills Extract per URL as `sku_extract_excerpts`, also when it returns full content (live call, 2026-11-03), so `PRICES` holds `sku_search` and `sku_extract_excerpts` at $0.001 each. One web lane run costs $0.011.
- **Task 2.** Institution queries carry no place text; the place is in the objective. A page whose markdown has no plain text, such as an image-only page, falls to the next text candidate. `page_source` puts a vendor title on one line.
- **Task 3.** Two relations of one mention that would make the same claim (same kind, org and quote start, so the same claim id in `store.upsert_claim`) keep the first; the second is dropped with "same claim as". The claim id stays as it is, so stored claims keep their ids. A relation quote must lie in the mention's own chunk as well as within 1,500 characters of its start.
- **Task 3.** The web lane fails without an LLM, as the parse step does; every caller passes one. `clean_name` strips Prof., Dr., ir., Mr. and Ms., with or without a space after the dot, because Belgian pages write "Prof. dr. ir.".
- **Task 3.** GS-02 live (FN_LLM=prefer, 2026-11-04): lane:web took 190 s for 14 Haiku calls over 10 pages. It kept 69 people and dropped 5 quotes (1 name not in quote, 4 relation quotes not near the mention). Peter Vetter is a web hit from a KDDI press release that names him President of Nokia Bell Labs. That page states no Belgian tie, so he ranks 221 of 485; the best web-only candidate ranks 73.
- **Task 4.** `searchQuery` keeps whole chips while it stays within the actor's 300-character limit, and notes the chips it leaves out. `canonical` folds every `*.linkedin.com` host into `www.linkedin.com`. Only "New York City Metropolitan Area" and "New Jersey" in `LOCATIONS` are confirmed by a live run; the other metro labels are LinkedIn's usual names and untested.
- **Task 4, live run (2026-11-04, $0.20, the only Apify run of the build).** `FN_LLM=prefer FN_LINKEDIN=1 fn-gold GS-02` sent `telecom OR "6G research"`, the 9 schools and the two New York locations. LinkedIn matched 43 profiles; the lane read 25 in 178 s, each with dated education and job claims. Sweldens and Baeyens were not in those 25. The 2026-11-02 run that found them searched `wireless OR 6G OR telecom` with 2 schools, so either "wireless" matched them or they sit in profiles 26 to 43; a second paid run would tell, and was not made. With the switch off, the same input is served from the cache: 25 hits, $0.
- **Task 4.** Parallel fast mode returned different pages for the same Search body an hour apart: Nokia people pages at 23:39, New York telecom business directories at 00:00. Vetter's web hit came from the first set, so it is not repeatable.
- **Task 5.** `page_key` also decodes percent escapes and drops a trailing slash from the path, so one page spelled either way is the event page. Parallel returns both spellings of the Nokia Bell Labs Murray Hill page (with and without the slash), GS-33's source ends in a slash and GS-29's path holds `%20`. This widens the rule in the task text above and needs the owner's OK.
- **Task 5, hand check (live, 2026-11-04).** `FN_LLM=prefer fn-gold GS-02` with LinkedIn served from the cache: the report shows the Lanes and Event page columns and a search cost of $0.0459 (Parallel $0.011, LinkedIn $0, the rest is the Haiku cost the CLI reports on the subscription). Vetter is `missed` at new #113 (web #5); Sweldens, Baeyens and Klein are `no lane in slice` with each lane's trace reason. No GS-02 pick was found, so no `event page` label was seen on real data.
