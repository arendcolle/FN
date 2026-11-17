# Task U2b: the pages for deaths, age and lookups

## Goal

On the Washington search 8 people stand in "People who have died", and each card still shows a role line, the death as a reason line, and Add and Skip. The old-record words are glued to the tie line. A person page shows no lookup, cannot look up anyone outside the first 20, and shows a found email without its source. This task builds the version 13 parts for these.

## What to build

### `src/fn/contracts.py`

`CardState` (line 61) gains `"died"`; `ReasonView` gains `year: str | None = None`; `CardView` gains `old_year: int | None = None`; `ContactView` gains `found: bool = False`; `ProfileView` gains `lookup: LookupView | None = None`. New: `LookupView(Model): state: Literal["before", "running", "after", "stopped"]; words: str | None = None` and `LookupIn(Model): person_id: str`.

### `src/fn/deepen.py`

- `STEP = "deepen"`, `JOB = "fn-lookup"`, `job_question(person_id)` gives `f"{JOB} {person_id}"`. `search.py` line 115 uses `deepen.STEP`.
- Structural commit first: `Pick` (line 43) holds `person_id, records, name, missing, contact`, not `candidate`; `run` lines 162 to 192 become `look_up(ctx, chosen) -> DeepenOut`.
- `one(ctx, inp: LookupIn) -> DeepenOut`: `run`'s note without HTTP or model, else one `Pick` (records from `store.records_of`, `missing=[]`, `contact=True`) through `look_up`, with no 90-day check.
- `run_job(ctx, job: Search)`: `run_step(ctx, STEP, one, LookupIn(person_id=job.question.removeprefix(f"{JOB} ")))`.

### `src/fn/store.py`, `src/fn/worker.py`

`last_lookup(person_ids, kind) -> tuple[Lookup, datetime] | None`, the newest row; `latest_job(question) -> Search | None`, the newest job row. `Worker.submit(search_id, workflow=None)` (line 61) passes `workflow` to `execute`.

### `src/fn/present.py`

- Constants: `ADDED = "Looked up on {date}: added {parts}."`, `NOTHING`, `NOT_SURE`, `STOPPED` as in STRINGS.md.
- `looking(store, search) -> bool`: running, chips version 2 or more, and a `deepen.STEP` step row with status running.
- `death_reason` (line 776) becomes `death_line`: `ReasonView(text="Died", year=claim.value, ...)`.
- `card_view` (line 785): with a death line, it is `aside_line`; the view drops role, employer and place; no reason; `fit = view.tie or NO_TIE`; state `"died"` unless skipped. An old record sets `old_year` and leaves `fit` alone.
- `summary_of` (line 1061) gains `member`; the Contact row is for members only. `contact_of` (line 1083) sets `found=prose(source)`.
- `lookup_view(store, records, person_id, today) -> LookupView`, first row that applies:

| State | When | Words |
| --- | --- | --- |
| running | latest job queued or running | none |
| stopped | latest job failed, interrupted or done, and no row at or after its start; or the newest row's verdict is `failed` | `STOPPED` |
| before | no row | none |
| after | `added` with a part | `ADDED` |
| after | `added` with no part (an older degree, a topic), `nothing_new` | `NOTHING` |
| after | `not_sure` | `NOT_SURE` |

Parts come from the not-rejected claims of `records` whose source's `raw_json` has a `lookup` key and whose `first_seen_at` is at most 60 s before the row's time and not after it (attach stores each claim with its own `ctx.now()`, deepen.py:255, before the row, deepen.py:204), each counted once: email, phone, location, a role without relation or `works_at`, else `evidence.recent_fact`. Joined with ", " and a last " and "; the date as `added_on` (line 369). `profile` (line 1187) sets `lookup` over all records of `persons`.

### `src/fn/web/parts.py`

- `status_line(people, looking=False)` (line 117) says "Looking up missing facts…" when looking.
- `proof(view, label, back)`, cut out of `claim_line` (lines 547 to 552), which calls it.
- `person_card` (line 149): `aside.year` in `<span class="text-year">`; new `old=None` renders `OLD_LINE` as its own `fn-card__fit text-small` paragraph, the year in `text-year`, after the fit line. `result_card` passes `card.old_year`.
- `contact_block` (line 488): non-members show only kinds with a value, no Edit. A `found` value is `<div class="fn-contact__value text-body">` with the link and `proof(claim.model_copy(update={"quote": None}), f"Source for the {NOUN[kind]}: {source}", here)`, so only the cite line shows, as in the mockup; `NOUN = {"email": "email address", "phone": "phone number"}`.
- `lookup_line(view, person_id, here)`: the Profile markup per state, `id="lookup" role="status" tabindex="-1"`, the button a `post_form` (line 387) to `/people/{id}/lookup` with `next=f"{here}#lookup"`.

### `src/fn/web/staff.py`

- `results_list` (line 229) passes `looking` and appends `" looking"` to `data-progress`; `search_status` (line 465) adds `"looking": true` only when true.
- `person_page` (line 641): skips `network.mark_seen` (line 674) when `x-requested-with` is `fetch`, as line 526 reads it; `lookup_line` after `summary_list`; `contact_block` for members or anyone with a contact claim; while running, `refresh=2` and `/static/lookup.js`.
- `POST /people/{person_id}/lookup`: `canonical_of`; without a queued or running `latest_job`, `worker.create_search(deepen.job_question(canonical), kind="job")` and `worker.submit(id, deepen.run_job)`; then `back_to(form, f"/people/{canonical}#lookup")`.

### `src/fn/web/static/results.js`, `src/fn/web/static/lookup.js` (new)

`poll` adds `" looking"` to `wanted` when `progress.looking`. `lookup.js` refetches the page every 2 s with the header `X-Requested-With: fetch` while `#lookup` has `fn-status`, copies the fresh class and children into the old element, and stops on any other state.

## Strings used, from STRINGS.md

"Looking up missing facts…", "Died `{year}` · `{source}`", "First record `{year}`, nothing recent", "Look up more", "Look up again", "Looking up more…", "Looked up on `{d Month yyyy}`: added `{parts}`.", "a current job", "a place", "a recent fact", "`{n}` recent facts", "an email address", "a phone number", "Looked up on `{d Month yyyy}`. Nothing new found.", "Looked up on `{d Month yyyy}`. Nothing added, because FN could not be sure the pages it found are about this person.", "This lookup stopped before it finished. Nothing was added.", "Try again", "Source for the email address: `{source}`", "Source for the phone number: `{source}`", "`{page title}`, `{Month yyyy}` · Original page", "Email", "Phone".

## Who owns what

| Responsibility | Owner |
| --- | --- |
| One lookup, the job's name and step | `deepen.py` |
| Lookup and job rows | `store.py` |
| Running a job off the request | `Worker.submit` |
| Lookup state, words, card lines, contacts shown | `present.py` |
| Markup | `parts.py` |
| One job per person | `staff.py` |
| Live updates | `lookup.js`, `results.js` |

## Inputs a real run will meet

Two posts or tabs; a post queued behind a search; an unknown or merged id; a restart mid-lookup; a `failed` row; a failed job older than a row; no model or recording; a row on a merged record; rejected claims; a row from before this change; three recent facts; two emails; 40 added claims; a died card skipped, with a rejected death claim, or on version 1; an old aside card; a non-member without contact; a member with an imported and a found value; a 200-character email.

## Tests (each must fail without the change)

- New `tests/test_lookup_page.py`, made-up names: every table row and input above; an `added` row whose claims are 5 ms older than the row lists its parts; an `added` row with only a topic reads `NOTHING`; a failed job older than a newer row shows the after state; a script fetch leaves the member's facts unseen; "3 recent facts"; redirect to `#lookup`; refresh and script only while running.
- `test_deepen.py`: `one` runs within 90 days; `run_job` reads the id.
- `test_results_headings.py`: died card markup without reason, role or acts; status words on version 2 only; `looking` in JSON and `data-progress`.
- `test_profile_page.py`: a non-member's found email with its proof, no Edit, no summary row; a member's found value keeps Edit.
- `test_worker.py`: `submit` runs a given workflow.

## Existing tests that change, approved by the lead

A probe on a copy showed these fail, and nothing else:

- `test_results_headings.py` `test_a_died_card_names_the_death_and_its_source`: the death text moves from the reason line to the first `fit` line.
- `test_an_old_first_record_ends_the_second_line_on_version_2_only`: the old line is its own paragraph.
- `test_profile_page.py` `test_the_summary_has_the_newest_study_the_tie_and_the_contact_or_not_found`: `ada` becomes a member.
- `test_card_lines.py` `test_the_why_block_sits_between_the_head_and_the_summary_and_needs_a_search`: the why block precedes `id="lookup"`.
- `test_person_content.py` `test_the_tie_row_follows_the_ranker_fit_and_reads_belgium_for_a_brussels_foundation`: the weak page has no summary list.

No other existing test may change; stop and report.

## Recorded model answers and replay (S6)

No prompt changes. For a person whose card is not combined from unmerged records, a job sends `lookup` the input a search sent, so replay finds it while the person's facts are unchanged; otherwise replay shows the stopped line. No ranking code changes, so version-1 order holds.

## Hand check

`uv run python -m unittest` all green. On a copy of the owner's data (task R1), `FN_HTTP=replay FN_LLM=replay FN_PORT=8791 uv run fn-serve`; screenshot the died group, a looked-up person and a pressed "Look up more" at 1280 and 390 px beside the mockups, with JavaScript on and off.

## Not doing

"New" marks on looked-up facts and the Places exception; focus on an after state; network people in a group; Wikidata; a separate job thread.
