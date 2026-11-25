# Task M1: the LinkedIn lane finds people through Google on the free Apify plan

## Goal

Five of 20 benchmark questions have nobody invitable in the first ten cards. On the free plan `check_account` (linkedin.py:142) raises `NoPaidRun` and the lane ends with a note. Google limited to `www.linkedin.com/in` plus one Parallel read found 3 to 13 people in the area with a Belgian school per question. This becomes the lane's second route. Brief M1.

## What to build

### `src/fn/websearch.py`

`extract_body(urls, objective, max_chars: int = MAX_CHARS)` puts `max_chars` in `max_chars_per_result`. New:

```python
def extract_pages(ctx: StepContext, urls: list[str], objective: str, max_chars: int = MAX_CHARS,
                  cache: CacheMode = "refresh") -> dict:
    """Read the urls in one Extract call with full content up to max_chars a page; the answer as JSON.

    Raises MissingKey without a Parallel key, CacheMiss on a miss that may not go out, HttpError for a failed call."""
```

It posts `EXTRACT_URL` with `timeout_s=EXTRACT_TIMEOUT_S, cost=usage_cost, cache=cache`. `find` (line 88) calls `extract_pages(ctx, list(unique), objective)`, so its body and cache key stay the same.

### `src/fn/lanes/linkedin.py`

Constants:

```python
GOOGLE_URL = "https://api.apify.com/v2/acts/scraperlink~google-search-results-serp-scraper/run-sync-get-dataset-items"
GOOGLE_PARAMS = {"maxTotalChargeUsd": "0.05", "timeout": "120"}
GOOGLE_TIMEOUT_S = 150
GOOGLE_USD = 0.001
SITE = "site:www.linkedin.com/in"
MAX_ROLES = 3
SCHOOLS_PER_QUERY = 3
MAX_PROFILES = 20
PROFILE_CHARS = 40_000
PROFILE_OBJECTIVE = "Where this person lives, their jobs and where they studied"
NO_PARALLEL = "LinkedIn lane skipped: no key for api.parallel.ai; set PARALLEL_API_KEY or store it in the Keychain"
NO_ADDRESSES = "Google found no LinkedIn profile address; Parallel not called"
NONE_PARSED = "no profile of this run could be parsed"
```

`PLACES`: the nine `LOCATIONS` keys to the two phrases of brief decision 4, in that order. `LOCATIONS` stays for the strict route.

New functions:

- `places(chips, area) -> list[str]`: `PLACES[area.city]` when the place kind is neither `abroad` nor `anywhere_us` and `area.city` is in `PLACES`, else `locations(chips, area)` (line 106).
- `schools(chips) -> list[str]`: the `SCHOOLS` whose `orgs.org_id` equals that of an institution chip; all nine when none does.
- `google_queries(chips, area) -> tuple[list[str], list[str]]`: role terms follow `run` (line 322): `job_titles(chips)[0]` when the version is 2 or later and that list is not empty, each multi-word title in double quotes; else `query_terms(chips)[0]` as it comes, since it already quotes multi-word terms. The first `MAX_ROLES` are used and the rest returned. One query per group of `SCHOOLS_PER_QUERY` from `schools`: `f"{SITE} ({roles}) ({places}) ({group})"`, each part joined by ` OR `, places and schools in double quotes with inner quotes dropped.
- `results_of(body) -> list[dict] | None`: the `results` list of the answer's first item; `None` when the answer is not a JSON list or that item holds no `results` list. We read brief decision 7 as "no results list": an empty list is cached, so a replay of that search serves it and is not a fault.
- `search_google(ctx, query, live) -> list[dict]`: POST `GOOGLE_URL`, body `{"keyword": query, "limit": "10", "country": "US", "hl": "en"}`, `GOOGLE_PARAMS`, `timeout_s=GOOGLE_TIMEOUT_S`, `cost=lambda _: GOOGLE_USD`, `keep=lambda b: results_of(b) is not None`, cache default when live, else `"only"`. Returns the dicts of `results_of`, or `[]`.
- `profile_address(url) -> str | None`: host `www.linkedin.com` or `linkedin.com`, path `/in/<id>`; segments after the id are dropped; then `canonical`. Else `None`.
- `addresses(answers: list[list[dict]]) -> tuple[list[str], int]`: result 1 of each query in turn, then result 2, distinct, at most `MAX_PROFILES`; also the count of results that are no profile address.
- `read_profile(text, url, acquired_at) -> dict | None`: Parallel's text as the strict actor's profile dict. When `len(text) >= PROFILE_CHARS` the last line is dropped. The header is the lines before the first `# ` heading: `first name`, `last name`, `Headline` (or a lowercase `headline` bullet with the text on its nested `- ` line), `Locality`. Each `# Experience` gives `{"companyName", "position": Title, "location": Locality, "startDate": {"year", "text"}, "endDate": {"text": "Present"} if is current is true, else {"year", "text"}}`. Each `# Education` gives `{"degree", "startDate": {"year"}, "endDate": {"year"}}`, `schoolName` from the `- Name:` under the `## School` that follows, `fieldOfStudy` from `## Field Of Study`. Lines under any other `#` or `##` heading are skipped. Years are ints and empty values are left out. Adds `linkedinUrl` and `_meta.scrapedAt = acquired_at`. `None` without a first or last name.
- `belgian_school(school, facts) -> bool`: `orgs.fold(school)` contains a folded `SCHOOLS` name, or `facts[orgs.org_id(school)].country_code == "BE"`. `facts` is `ctx.store.get_orgs` (store.py:485) of the org ids of every parsed education school, loaded once per run after parsing.
- `google_route(ctx, chips, area, live, off, considered) -> LaneOut`:
  1. Note `f"Google route: more than {MAX_ROLES} role terms; left out: {...}"` for extra terms.
  2. When `live`, `http_mode != "replay"` and there is no `parallel_api_key`: log a warning, note `NO_PARALLEL`, return.
  3. Query in order. A `CacheMiss` on the first query notes `off` and returns; on a later one it propagates. An answer where under half the results are profile addresses (`profile_count`) lost the site limit: note `ASKED_AGAIN`, send the query once more with `SITE` at the end, and use the answer with more profile addresses. The second query has its own recording, so a replay serves both.
  4. No address: note `NO_ADDRESSES`. Else `websearch.extract_pages(ctx, urls, PROFILE_OBJECTIVE, PROFILE_CHARS, cache)`, results matched by `canonical(url)`.
  5. Per address in order, numbered n: unread gives `f"result {n}: not read ({error_type or 'missing'})"`; unparsed gives `f"result {n}: no first and last name; not read"`; no Belgian school gives `f"result {n}: no Belgian school among {k} schools; not kept"`. Each row has `person_key=f"result {n}"`, `name=""`, `stage="profile"`.
  6. `NONE_PARSED` when nothing parsed, then `people(ctx, kept, considered, numbers)`.
  7. One read note: `f"Google route: {q} queries, {r} results, {a} profile addresses, {p} read"`. `query=" | ".join(queries)`, `total_seen=len(urls)`.
- `expected_misses(calls: list[StepCall]) -> set[int]`: the `seq` of every call whose `request` holds `ACTOR_URL`, plus the first holding `GOOGLE_URL`.

Changed:

- `people` (line 266) gains `numbers: list[int] | None = None`, the result number of each profile, defaulting to 1 to n.
- `run` (line 314): `area = geo.area(...)` once, passed to `actor_input`. `CacheMiss` calls `google_route` with `off` set to today's note (replay note when live, else `OFF`). `NoPaidRun` appends its note and calls `google_route` with the replay note. `MissingKey` is unchanged, since Google needs the same token.

### `src/fn/score.py`

`degraded` (line 290) skips a call's `response cache` error only when the step is `OFF_BY_DESIGN` and its `seq` is in `linkedin.expected_misses(calls)`. The comment at line 36 changes to match.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| When the Google route runs | `linkedin.run` |
| The route's steps, notes, considered rows and Parallel key check | `linkedin.google_route` |
| Whether a call may go out | `linkedin.may_run_live` |
| Strict plan and budget | `linkedin.check_account` |
| Query text and area names | `linkedin.google_queries`, `linkedin.PLACES` |
| The Google call, price, caching | `linkedin.search_google` |
| Profile addresses and their order | `linkedin.profile_address`, `linkedin.addresses` |
| Canonical address | `contracts.profile_url` |
| Extract body, price, call | `websearch.extract_pages` |
| Profile text to fields | `linkedin.read_profile` |
| Which profiles are kept | `linkedin.belgian_school` |
| Sources, identifiers, claims | `linkedin.people` |
| Misses that are off by design | `linkedin.expected_misses` |
| Whether a run is degraded | `score.degraded` |
| Cache rules | `net.Client._send` |

## Recorded answers, replay and stored searches

No prompt or model call changes. The web Extract body keeps its default, so web recordings replay. Without Google recordings a replay notes `OFF` as today and `fn-rerank` reads stored outputs, so version-1 searches keep their order exactly. A replayed step records two misses, both skipped.

## Inputs a real run will meet

Brief list plus: an answer that is not JSON (9), a role or place with quote marks (1), four role chips (1), an institution chip that maps to no school (1), Parallel's URL with a slash (6), a profile with no Education block (4), live with `FN_HTTP=replay` (8).

## Tests (each must fail without the change)

Made-up names and fixtures `tests/fixtures/http/linkedin/google.json` (three Apify answers) and `extract.json` (Parallel answer, labelled text). In `tests/test_linkedin.py`:

1. `test_google_queries_name_three_titles_the_area_phrases_and_three_schools`: the brief's first query, exactly; "KU Leuven" chip gives one query; version 1; version 2 with only a topic chip and with only an institution chip use `query_terms` without double quoting; quoted multi-word role; four roles; no place, abroad and Seattle.
2. `test_without_a_paid_run_google_runs_and_with_one_only_the_scraper`: free, no room, unreadable: no `ACTOR_URL` POST, three `GOOGLE_URL` POSTs, caps, 150 s, $0.001 each. Paid with room: no Google call. A recorded strict answer: one served call, nothing else.
3. `test_a_kept_profile_is_one_person_with_dated_education_job_role_and_place`: claims and years; `evidence.of` job "known", `rank.place_fit` "inside" New York.
4. `test_a_profile_without_a_belgian_school_stores_nothing_and_names_nobody`: seeded store; "Universiteit Gent", "Université libre de Bruxelles" and "Rega School, KU Leuven" kept.
5. `test_only_the_header_experience_and_education_are_read`: summary, skills and collaborators absent from source and raw; education without school, school without name, job without company, header only, one-word name, a 40,000-character cut, `NONE_PARSED`.
6. `test_addresses_alternate_queries_drop_repeats_and_non_profiles_and_stop_at_20`.
7. `test_a_parallel_error_or_missing_result_leaves_a_row`.
8. `test_off_without_a_recorded_first_query_is_ok_and_a_later_miss_fails`: step status, `score.degraded` False and True.
9. `test_an_answer_without_a_results_list_is_not_cached_and_an_empty_one_is`.
10. `test_the_strict_routes_person_is_the_same_record_through_google`.
11. `test_researchers_only_no_token_and_no_parallel_key_note_and_call_nothing`.
12. `test_an_answer_that_lost_the_site_limit_is_asked_once_more_with_the_limit_at_the_end`: added after the first live run, in which 3 of 13 Google calls came back with other websites.

`tests/test_web_lane.py`: `test_extract_body_takes_a_character_limit`. `tests/test_score.py`: `test_a_linkedin_step_counts_a_miss_that_is_not_off_by_design`.

## Existing tests that change, approved by the lead

Helpers in `LinkedInLaneTest`: `handle` answers `GOOGLE_URL` from `self.google` and `EXTRACT_URL` from `self.extract`, both set in `setUp`. `run_lane` keeps its behaviour and now calls a new helper `in_step`, which other tests use to run a function inside a lane step.

- `test_the_lane_off_with_no_recorded_run_notes_it_and_makes_no_transport_call`: one call with a miss becomes two (actor, first Google query). The note and the ok step are unchanged.
- `test_the_account_decides_a_paid_run_and_its_answer_is_kept_nowhere`: each `NoPaidRun` case changes from `[note]` to `[note, NO_PARALLEL]`, since the test settings have no Parallel key. There is still no POST and no hit.

No other existing test may change. If one does, stop and report.

## Hand check

Run `uv run python -m unittest` and expect all tests to pass. A scratch script sets `FN_VAR` to a `mktemp -d` folder holding a backup copy of `var/fn.sqlite3` and the GeoNames cache file. It runs `lane:linkedin` twice:

1. `http_mode="live"`, `linkedin_auto=True` and made-up keys, over an `httpx.MockTransport` that answers: `CITIES_URL` with the bytes of the copied GeoNames cache file, since live mode refetches it; a free account; each Google query from `google/<q>-take20.json` (it fails on a query not in `queries`); Extract with its `read`.
2. `http_mode="replay"` with the lane off, which makes no transport call.

For `bq06` (journalists, editors; New York) and `bq13` (importers, traders; Chicago), print kept and dropped counts. Expect 13 to 17 kept of 20 for bq06 and 14 to 16 for bq13. Every kept person must have a `studied_at` claim on a Belgian school. Print no names.

## Not doing

The brief's list. Also no change to the strict route's input, `LOCATIONS`, `check_account` or `find`'s behaviour.
