# Task K4: the LinkedIn lane runs within the month's budget and finds people by job title

## Goal

Five of 20 benchmark questions have nobody invitable in the first ten. The LinkedIn lane is off, never sends role chips, and stores no place or title (all 25 stored LinkedIn people have place "unknown"). Live, job titles found 14 architects in Los Angeles where keywords found founders. The lane now runs on the staff server after a free check of Apify's plan and budget, sends job titles and stores a place and a role. Brief K4.

## What to build

### `src/fn/contracts.py` and `src/fn/net.py`

`CacheMode` (contracts.py:48) gains `"none"`. `get` gains `cache: CacheMode = "refresh"` and `post` gains `before: Callable[[], None] | None = None`, in `HttpClient` (contracts.py:94-101) and `Client` (net.py:218, :248), passed to `_send` (net.py:154). There `"none"` in replay records "never cached" and raises `CacheMiss` unsent, else skips the cache read and write (also the redirect write, net.py:243). After `_sign`: `if before: before()`.

### `src/fn/config.py` and `src/fn/web/app.py`

`Settings.linkedin_auto: bool = False`. `from_env(server: bool = False)` sets it to `server and env.get("FN_LINKEDIN") != "0"`. Only `serve` (app.py:120) passes `server=True`; `gold.py:352-362` is untouched.

### `src/fn/parse.py`

After `asks_researchers` (line 103), `researchers_only(chips) -> bool`: `bool(chips.roles) and all(r.research for r in chips.roles)`; null counts as false, as there.

### `src/fn/lanes/linkedin.py`

```python
MAX_TITLES = 12
# Run timeout, call timeout and profiles per run; chips before version 2 keep round three's, so their recorded run replays.
SIZES = {1: (240, 290, 25), 2: (270, 295, 10)}
ACCOUNT_URL = "https://api.apify.com/v2/users/me"
LIMITS_URL = "https://api.apify.com/v2/users/me/limits"
RESEARCHERS = "researchers only; LinkedIn not asked"
FREE_PLAN = "Apify's free plan runs this actor ten times in total; a paid plan is needed"
NO_ROOM = "the month's Apify budget has no room for a run (${used:.2f} of ${cap:.2f} used)"
NO_ACCOUNT = "could not read the Apify account; no paid run"
```

Every lookup is `SIZES[min(chips.version, 2)]`. `RUN_TIMEOUT_S` and `CALL_TIMEOUT_S` go. `NO_QUERY = "no role, topic or institution chip"`. `LOCATIONS`: Chicago `["Greater Chicago Area"]`, Houston `["Greater Houston"]`.

New:

- `title(text) -> str`: quotes dropped, lower case; a last word "people" or "persons" dropped; the last word's "ies" becomes "y", else a final "s" not after "s" goes.
- `job_titles(chips) -> tuple[list[str], list[str]]`: distinct non-empty titles in chip order, the first `MAX_TITLES` and the rest.
- `may_run_live(settings, chips) -> bool`: `settings.linkedin_live or (settings.linkedin_auto and settings.apify_token is not None and chips.version >= 2)`.
- `NoPaidRun(Exception)`, `check_account(http) -> None`: GET `ACCOUNT_URL`, `cache="none"`; `data.plan.tier` (via `dig`, line 117) missing or not a non-empty string raises `NO_ACCOUNT`, as the account cannot be read; "free" in any case `FREE_PLAN`. GET `LIMITS_URL` likewise; `data.limits.maxMonthlyUsageUsd` or `data.current.monthlyUsageUsd` not a number (bool excluded) raises `NO_ACCOUNT`; `round(cap - used, 6) < MAX_CHARGE_USD` raises `NO_ROOM`. `HttpError` or `ValueError` raises `NO_ACCOUNT` `from None`. Nothing is logged or kept.
- `place_claim(person_id, source, spans, profile, ctx) -> ClaimDraft | None`: value the first non-empty string of `location.parsed.text`, `location.linkedinText`; quote the `location.linkedinText` line; `None` without either. Point from `geo.coordinates` (geo.py:198) as `extract.stated_place` does (extract.py:443-456). `location`, `lives_in`, dated by the source date (day, `record_field`).

Changed:

- `actor_input`: version 2 with titles sends `currentJobTitles` and no `searchQuery`; `maxItems` from `SIZES`. Version 1 is today's input.
- `drafts` (line 148): an entry with no lines is skipped; affiliations as today; a current job with a non-empty `position` adds a `role` claim, no relation, quote and dates of its `works_at` claim; a job without a company has no `works_at` claim and so gets no `role` claim.
- `people` (line 178): calls `geo.cities(ctx.http)` (geo.py:69) once before `ctx.store.tx()`, so no download runs inside the write (S4); also stores `place_claim`; "job claims" counts `works_at` and `worked_at`, so reasons stay.
- `run` (line 219): `researchers_only` returns `RESEARCHERS` before any call. Version 2 uses `job_titles`; with titles, topics are unread and extra titles get `f"more than {MAX_TITLES} job titles; left out: {...}"`; `query` reads `job titles a, b; locations ...`. `live = may_run_live(ctx.settings, chips)` replaces line 235 and picks both the cache mode and the `CacheMiss` note. The post takes `SIZES` timeouts, `cache="prefer" if live else "only"`, `before=lambda: check_account(ctx.http)`; `NoPaidRun` becomes a note.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Researchers only | `parse.researchers_only` |
| Reading `FN_LINKEDIN`; which program is the server | `config.from_env` |
| Whether a run may go out | `linkedin.may_run_live` |
| Plan and budget | the Apify account, read by `linkedin.check_account` |
| Cache rules; a check only before a real call | `net.Client._send` |
| Titles, size, locations | `linkedin.actor_input` |
| A place's point | `geo.coordinates` |
| Profile claims | `linkedin.drafts`, `linkedin.place_claim` |

## Recorded answers, replay and stored searches (S6)

No prompt changes. `fitcheck.line_of` now shows a LinkedIn person's role, so a fit batch holding one has new text; no recorded batch holds one. Version 1 keeps today's input, so the recorded GS-02 answer replays; in an `fn-score` rerun its 25 people gain a place and a role. Version-2 inputs have no recording. `fn-rerank` reads stored lane outputs, so version-1 searches keep their order exactly.

## Inputs a real run will meet

Test 1: quotes, a chip of only "people", one title from two chips, 13 titles. Test 2: topics beside roles, version 1 with roles, Chicago, Houston. Test 3: research null, true, mixed. Test 4: no token, `FN_LINKEDIN=0`, version 1. Test 5: replay, a recorded answer, tier "free" (`FREE_PLAN`) or missing (`NO_ACCOUNT`), not JSON, HTTP 500, room equal to the cap, a cent short, a missing field. Test 6: no location, no `parsed.text`, an unplaceable place, two current jobs, a job without position or company, a person stored earlier. Test 7: a place outside the area.

## Tests (each must fail without the change)

Made-up names. In `tests/test_linkedin.py`:

1. `test_role_chips_become_singular_lower_case_job_titles`: roles "architects", "designers", Los Angeles: `currentJobTitles ["architect", "designer"]`, no `searchQuery`, `maxItems` 10, "Los Angeles Metropolitan Area". "business development people", "Economists", "secretaries", "business", '"Editors"', "people" give "business development", "economist", "secretary", "business", "editor", "".
2. `test_titles_win_over_topics_and_version_1_sends_todays_input`.
3. `test_a_question_for_researchers_only_gets_the_note_and_no_call`.
4. `test_only_the_staff_server_runs_version_2_chips_without_fn_linkedin`: `serve` sets `linkedin_auto` (mock `uvicorn.run`); version 1 or no token gives `OFF`, no warning.
5. `test_the_account_decides_a_paid_run_and_its_answer_is_kept_nowhere`: each case its note; paid: GET me, GET limits, POST; "made.up@example.org" in no file under `var_dir`, DEBUG log record or call row.
6. `test_a_profile_gives_a_located_place_and_a_role_per_current_job`: a current job with a position and no company gives no `role` claim.
7. `test_a_linkedin_person_has_a_known_job_and_a_place_that_fits_the_area`: `evidence.of` job "known"; `rank.place_fit` "inside" for New York, "outside" for Los Angeles.

In `tests/test_net.py`: `test_a_get_with_cache_none_never_reads_or_writes_the_cache`, `test_before_runs_only_when_a_post_goes_out`.

## Existing tests that change, approved by the lead

In `LinkedInLaneTest`, helpers: `handle` answers the account URLs with a paid plan and room, `posts` keeps POSTs, `calls` keeps rows holding "POST ".

- `test_every_profile_is_a_hit_with_the_exact_education_and_job_claims_it_lists`: 10 claims to 15 (three `lives_in`, two `role`).
- `test_a_place_abroad_or_anywhere_in_the_us_sends_its_text_without_fetching_the_city_list`: becomes `..._fetches_the_city_list_only_after_the_post`.
- `test_one_profile_url_in_two_spellings_is_one_person_one_hit_and_one_set_of_claims`: claims 5 to 7.
- `test_a_person_listed_twice_is_one_hit_holding_the_claims_of_both_entries`: 11 to 15.
- `test_a_refusal_from_apify_fails_the_step_with_its_message`: account calls answered; expectation unchanged.
- `test_the_lane_off_serves_a_recorded_run_without_a_transport_call`: `len(self.sent) == 1` becomes `len(self.posts()) == 1`; the account GETs and GeoNames fetches are allowed.

No other existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. A scratch script outside the repo, with `FN_VAR=$(mktemp -d) FN_HTTP=replay FN_LLM=replay`, copies the GeoNames file into that cache (`net.cache_file`), then runs `lane:linkedin` on version-2 chips twice: first with settings overridden to `http_mode="live"` and `linkedin_live=True` over an `httpx.MockTransport` serving GeoNames, a paid account holding "made.up@example.org" and the first 10 profiles of a saved answer, then with `http_mode="replay"`. For `x1/bq17-titles.json` (Los Angeles; architects, designers) and `x1/bq06-titles-salvaged.json` (New York; journalists, editors), the planner counted: 10 hits, 10 places within 100 km, 13 roles each; no file under `FN_VAR` holds the address. Print no names.

## Not doing

Short mode, salvaged runs, a second page, staff-visible notes, email search, the fit check, ranker and parse, other area names, a budget setting.
