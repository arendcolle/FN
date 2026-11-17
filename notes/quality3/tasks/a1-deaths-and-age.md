# Task A1: deaths and age

## Goal

Two people who died in 1966 and 1922 stood in the Washington first 50; no claim states a death, and a 400-character window gave 2 of 10 death lines to the wrong person (diag-age section 6). This task stores a death only from the person's own entry, sets them aside (A1), and sorts old records (A2) and retired-looking people (A3) lower. A read-only trial of the rule on the owner's data finds 15 deaths, all correct, 8 on kept Washington cards, and spares the living neighbour.

## What to build

### `src/fn/contracts.py`

`ClaimKind` (line 25) gains `"death"`; `Aside` (line 54) gains `"died"`. New `DeathsIn(Model)` with no fields and `DeathsOut(Model)` with `pages: int`, `deaths: int`, beside `PlacesOut` (line 887). No migration: `claims.kind` and `candidates.aside` are free text.

### `src/fn/extract.py`

- `DIED_LINE = re.compile(r"^\|?[ \t]*Died[ \t]*[:|][^\n]*", re.MULTILINE)`, `YEAR = re.compile(r"(?<![0-9])(1[0-9]{3}|20[0-9]{2})(?![0-9])")`, `ENTRY_CHARS = 600`, `LIFE_YEARS = (25, 110)`.
- `deaths(source: Source, people: dict[str, tuple[str, list[Span]]], today: date) -> list[ClaimDraft]`. Keys are person ids, or a mention identifier for a person not stored. For each person: `q` is their first quote start; `lo` is the latest of 0, `q - ENTRY_CHARS` and the end of every other person's span ending at or before `q`. A `DIED_LINE` match starting in `[lo, q)` counts when no other person's span overlaps `[match start, q)`, the person's surname (last word of `clean_name`, as `_near` line 251 takes it) stands in `text[lo:match start]`, and its first `YEAR` is at most `today.year`. Take the last such line. Without one, a lifespan counts: surname, then `\s*\(([^()\n]{4,60})\)`, case-insensitive, starting in `[lo, q)` or inside one of the person's spans, whose parenthesis holds exactly two years with a dash `[-–—]` between them, apart by `LIFE_YEARS`, the second at most `today.year`. A death line wins over a lifespan. One draft per person: `kind="death"`, `value` the year, quote from `_line` (line 266), `claim_date` the year, `date_precision="year"`, `date_method="stated_in_quote"`.
- `deaths_stored(store: Store, today: date) -> DeathsOut`: for every source of kind page, seed_page or vendor_page with claims, `store.page_people` gives the people; upsert each draft in one `store.tx()` per page.

### `src/fn/store.py`

`page_people(kinds: tuple[SourceKind, ...]) -> dict[str, dict[str, tuple[str, list[Span]]]]`: by source id, each record's display name and quote spans, without death claims (a rerun then finds the same line). `UNMATCHED_KINDS` (line 53) gains `"death"`, so the stored-lists lane never shows a death quote as a match.

### `src/fn/lanes/web.py`

`people` (line 58): per page, key every located person's spans by person id, or `ident.value` when not stored, and upsert the `extract.deaths` drafts of stored people. They join no hit or considered row, so lane outputs stay unchanged. Callers: the web lane and `scout.py` line 111, which passes leads, so only the leads are located there and the surname guard alone keeps a neighbour's line out.

### `src/fn/orgjob.py`

Built like `--places`: `DEATHS_JOB = "fn-orgs --deaths"`, step `deaths(ctx, DeathsIn) -> DeathsOut` calling `extract.deaths_stored(ctx.store, ctx.now().date())`, `fill_deaths(store, settings, _: HttpClient) -> Search`, flag `--deaths`, done line `fn-orgs --deaths job {id} done: {deaths} death claims on {pages} pages`.

### `src/fn/evidence.py`

- `SOURCE_DATED = ("record_field", "page_date", "sitemap", "stated_in_quote")`, `ACTIVE_YEARS = 10`, `GAP_YEARS = 10`, `OPENALEX_RECENT = 2`, `EMERITUS = re.compile(r"\bemerit(us|a|i|e)\b")`.
- `@dataclass(frozen=True) class Age`: `first: int | None`, `back: int | None` (today's year minus `first`), `recent: bool`, `current: bool`, `emeritus: bool`, `died: str | None` (claim id), all defaulting to empty. `Evidence` gains `age: Age = field(default_factory=Age)`.
- `stated_years(claim, today) -> list[int]`: `claim.years`, the years from `valid_from` to `valid_to`, and `claim_date`'s year when `date_method` is in `SOURCE_DATED`, kept within 1900 and `today.year`.
- `death(claims) -> Claim | None`: the death claim with the lowest year, then id.
- `age(claims, today) -> Age`. `first`: the lowest stated year over claims that are not `born_in` and not death, after dropping the lowest when the next is more than `GAP_YEARS` later. A dated role is a `role` claim without relation or a `works_at` claim. OpenAlex years are the `years` of `affiliated_with` claims. `recent`: a dated role year, or `OPENALEX_RECENT` OpenAlex years, within `ACTIVE_YEARS`. `current`: the same within `RECENT_YEARS`, emeritus roles left out. `emeritus`: a role value matches `EMERITUS` after `name_key`.
- `of` (line 316): `alive = [c for c in own if c.kind != "death"]` goes to `places`, `topic`, `institution`, `tie`, `role`, `where` and `sources`. The full `own` goes to `job(own, card, today)` and `age(own, today)`. `job` (line 232) returns `"none"` when any claim is a death.

### `src/fn/rank.py`

- `OLD_YEARS = 60`, `RETIRED_YEARS = 45`, `LAST_TIER = {1: 2, 2: 4, 3: 6, 4: 7}`, `ASIDES` ends with `"died"`.
- `old(age) -> bool`: `back is not None and back >= OLD_YEARS and not recent`. `retired(age) -> bool`: `emeritus or (back is not None and back >= RETIRED_YEARS and not current)`.
- `aside` (line 251): after the version and network guard, `"died"` when `found.age.died`, before every other reason.
- `order_key` (line 231), version 2 only: `(LAST_TIER[heading] if old else level, heading, old, level, retired, *today's tail from lead on)`. `key[1]` stays the heading, which `capped` and `over_cap` read. Without evidence on version 2 it returns `(7, 4, 0, 7, 0, *BLANK[2:])`, so such rows compare as today. Version 1 keeps today's tuple.

### `src/fn/present.py`

- `ASIDE_HEADINGS["died"] = "People who have died"`, `OLD_LINE = "First record {year}, nothing recent"`.
- `what_of` (line 203): a death reads `Died {year}`; `group_of` leaves it under Work.
- `own_years` (line 179) returns an empty set for a death claim, so the year shows once: `claim_view` gives empty `years`, `reason_of` writes "Died 1966" without ", 1966", and the person page shows no year column beside it.
- `death_reason(store, candidate, today) -> ReasonView | None`, built like `place_reason` (line 682) from `ev.death`. `card_view` (line 695) uses it for a `died` card, giving "Died 1966 · source".
- `card_view`: on version-2 chips, a new-section card not set aside with `rank.old(ev.age(claims, today))` appends `OLD_LINE` to the second line with " · ".

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Finding a death in page text, bounded to the entry | `extract.deaths` |
| Death claims for stored pages | `extract.deaths_stored`, run by `fn-orgs --deaths` |
| Death claims for pages a lane reads | `web.people` |
| Spans per source | `store.page_people` |
| First year, recent, current, emeritus, death; no job after death | `evidence.age`, `evidence.job` |
| Old and retired thresholds, order | `rank.old`, `rank.retired`, `rank.order_key` |
| Setting aside as `died` | `rank.aside` |
| Group heading, card words | `present.py` |

## Inputs a real run will meet

Pages: a living entry between two dead ones; an unstored dead neighbour; a death line inside another's quote; "Died: unknown"; a future year; "died" in prose; an infobox row; "(1830-1930)" after an org; "(born 1959)"; a tenure "(2010–2015)"; a death line plus a lifespan; an empty page; 200 entries; a rerun. People: a rejected death claim; a dead network person; a death plus OpenAlex years to 2024; a lone 1910 before 1991 on; `born_in` 1940; a read-date role; an emeritus role dated 2025; years 1791 and 2027.

## Tests (each must fail without the change)

- `tests/test_extract.py`: one test per page input; an unknown neighbour whose Died line is within 600 characters before the lead, rejected by the surname guard alone.
- `tests/test_orgs.py`: `fn-orgs --deaths` stores one claim on a two-person page, a rerun gives the same `DeathsOut` and no new row.
- `tests/test_web_lane.py`: a page with a death line stores the claim; hits and considered rows equal those without it.
- `tests/test_evidence.py`: one test per people input except the rejected and network ones; a death quote naming Belgium adds no tie.
- `tests/test_db.py`: a rejected death claim is dropped by `Store.claims_of`, so `evidence.of` gives `age.died` None.
- `tests/test_rank.py`: a dead tier-1 person stands under `died` after `unfit`, and on version 1 keeps tier 1; `died` beats `outside`; a dead network person keeps aside None; under a required place an old tier-1 person follows tier 2 and precedes heading 2; an old tier-5 person follows tier-6 tied people, precedes heading 4 and counts in heading 3's cap; a professor with a 1958 degree and a 2025 role stays; an emeritus person follows a lower-scored active one; 46 years back with two OpenAlex years since 2021 stays, with only a read-date role moves; version 1 keeps its order.
- `tests/test_results_headings.py`: the died group follows the other groups; its card reads "Died 1966 · source"; a version-2 old card ends "First record 1958, nothing recent", the same card on version 1 does not.
- `tests/test_fitcheck.py`: a died person is not sent.
- `tests/test_present.py`: a death fact reads "Died 1966" under Work with empty `years`, on the card reason and the person page.

## Existing tests that change, approved by the lead

None. No other existing test may change; stop and report.

## Recorded model answers and replay (S6)

No prompt changes, no new call, and no test fixture holds a death line, so recorded keys stay. On the owner's data a full replay (the benchmark) of a version-2 search misses fit-check recordings whenever the order changes: a dead person drops out, or an old or retired person moves within the first 120, and `fitcheck.candidates` batches by rank. Reranks read stored verdicts; test fixtures hold parse recordings only.

## Hand check

`uv run python -m unittest` all green. Copy the owner's data to `$A` and `$B` as in task R1; these commands fill deaths on `$B` and rerank both, with `FN_HTTP=replay FN_LLM=replay`:

```sh
FN_VAR=$B uv run fn-orgs --deaths
FN_VAR=$A uv run fn-rerank --all   # from a worktree pinned to main
FN_VAR=$B uv run fn-rerank --all   # from this worktree
```

The first command reports 15 death claims. Version-1 candidate rows differing in section, rank, cut reason or tier: 0. On `$B` the Washington search has 8 rows with aside `died` and no open row with a death claim on its card.

## Not doing

Wikidata, web lookups, closed groups, new markup or CSS, a birth year as an age signal.
