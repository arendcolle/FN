# Task d1: link employer names to organizations through ROR

## Goal

In the owner's Washington search, 19 of the 23 tier-1 people without a known place have employer claims without an organization, so `evidence.places` (`evidence.py:114-128`) finds no city. The store holds 2,727 such claims under 1,910 distinct names. `fn-orgs --match` asks ROR once per name and links a chosen match, with its place, to every claim of that name (D1).

## ROR's API, as documented

- `GET https://api.ror.org/v2/organizations?affiliation=<text>`, no key. Each of `items` has `chosen`, `score`, `matching_type`, `substring` and `organization`, a v2 record whose `locations[].geonames_details` has `name`, `lat`, `lng`, `country_code`. At most one item is chosen; when none is, ROR says not to pick by score. https://ror.readme.io/docs/api-affiliation
- Single search (whole string, one query) is the default since May 2026; `&multisearch` splits strings into substrings. FN sends `single_search` explicitly. Same URL.
- Rate limit: 2,000 requests per 5 minutes per IP. https://ror.readme.io/docs/rest-api
- Without a `Client-Id` header the documented limit is 50 per 5 minutes, but ROR does not enforce it yet and has paused registration. https://ror.readme.io/docs/client-id
- Live on 2026-11-17: "Research Institute for Nature and Forest" gives one chosen item, `https://ror.org/00j54wy13`, Brussels, BE. "Research Institute for Agriculture" gives none chosen, the first at score 0.95.

## What to build

### `src/fn/migrations/013_org_matches.sql`

`CREATE TABLE org_matches (fold_key TEXT PRIMARY KEY, name TEXT NOT NULL, org_id TEXT, asked_at TEXT NOT NULL);`. A null `org_id` means no match.

### `src/fn/store.py`

- `unlinked_affiliations(relations: tuple[str, ...]) -> list[tuple[str, str]]`: (claim id, value) of every claim with `org_id IS NULL` and one of the relations, by id, rejected ones too so their fact key (`store.py:79-81`) moves with the rest.
- `org_answers() -> dict[str, str | None]`, `save_org_answer(fold_key: str, name: str, org_id: str | None, at: datetime) -> None` (insert or replace). Keyed by `orgs.fold(value)`.
- `link_claims(claim_ids: list[str], org_id: str) -> int`: sets the org where `org_id IS NULL`; returns the rows changed.
- `upsert_claim` (`store.py:378-385`): a draft without an org keeps the stored one: `org_id = COALESCE(excluded.org_id, claims.org_id)`, and the WHERE compares that value with `claims.org_id`. Else the next `fn-seed` or page reread unlinks. Its docstring says a draft's org_id replaces the stored one only when set.

### `src/fn/contracts.py`

`class OrgMatchIn(Model): pace_s: float = 0.2` and `class OrgMatchOut(Model): asked: int; chosen: int; linked: int; failed: int`.

### `src/fn/orgs.py`

- `MATCH_RELATIONS = ("works_at", "worked_at", "affiliated_with", "hosted_by", "studied_at")`, `MIN_CHARS = 3`, `MAX_NAME_CHARS = 200`.
- `askable(name: str) -> bool`: false when `name_key(name)` holds under `MIN_CHARS` letters or digits, the name exceeds `MAX_NAME_CHARS`, or `fold(name)` is in `unmapped()` (`orgs.py:58`).
- `chosen(body: dict, fetched_at: datetime) -> tuple[OrgFacts, Source] | None`: the one chosen item read with `ror_record` (`orgs.py:110`); None when none or more than one is chosen. Raises `OrgError` for a body without `items` or a record `ror_record` refuses; wraps `ValueError`, `KeyError`, `TypeError` into it (as `orgs.py:204-205`).
- `match(ctx: StepContext, inp: OrgMatchIn) -> OrgMatchOut`: `RuntimeError` without an HTTP client. Groups `unlinked_affiliations(MATCH_RELATIONS)` by `fold(value)`; the name sent is the group's first value. Per group, in key order:
  - an answer with an org in `org_answers()`: `link_claims`, no call; a null answer: skip;
  - not `askable`: skip, store nothing;
  - else sleep `inp.pace_s` (not before the first call), `ctx.http.get(ROR_API, {"affiliation": name, "single_search": ""})`, then in one `store.tx()`: `save(..., replace=False)` (`orgs.py:96`) when chosen, `save_org_answer`, `link_claims`.
  - An `HttpError` with status 429, 5xx or None (network, replay miss) raises `OrgError` naming the name; earlier answers stay. Another 4xx, a body that is not JSON or an `OrgError` from `chosen` adds to `failed`, is not stored, and the run goes on.
- A pace of 0.2 s stays under 1,500 calls per 5 minutes. `net.Client` retries a short 429 once (`net.py:205-215`).

### `src/fn/orgjob.py`

`MATCH_JOB = "fn-orgs --match"`; `match_names(store, settings, http) -> Search` built like `fill_places` with one `match` step; a `--match` flag exclusive with `--places`. `main` prints `fn-orgs --match job <id> done: <asked> names asked, <chosen> chosen, <linked> claims linked, <failed> failed in <db>`.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which names are asked, what counts as a match, pacing | `orgs.py` |
| Stored answers and claim links, in SQL | `store.py` |
| Running it as a recorded job | `orgjob.py` |
| What a linked org means for place and tie | `evidence.py`, unchanged |

## Inputs a real run will meet

One name in several spellings; a name answered "no match" before; new claims of a remembered match; an unmapped, a one-letter and a 300-character name; a split name such as "Fisheries and Food (ILVO)"; two chosen items; a chosen org stored with a city; a chosen record without locations; a 429 with Retry-After 300 s; a 400; a stop midway and a rerun; `fn-seed` after a run.

## Tests (each must fail without the change)

Fixtures `tests/fixtures/http/ror-affiliation/inbo.json` and `agriculture.json`: the live answers for the two names above, recorded once with curl, served by `affiliation` through `httpx.MockTransport` (`tests/helpers.py:53`). Made-up people only.

New `MatchTest` in `tests/test_orgs.py`, `pace_s=0`:

- One call stores `ror:00j54wy13` with Brussels, BE and coordinates, and links the claims of that name in three spellings.
- The agriculture answer links nothing and is stored as null; a second run makes no call.
- A new claim of a remembered name is linked by a rerun without a call.
- An unmapped, a one-letter and a 300-character name make no call.
- A made-up answer with two chosen items links nothing; a chosen record without locations links and gives no place.
- A stored org keeps its city.
- A 429 over 30 s fails the step naming the name; earlier answers stay; a rerun asks only the rest.
- A 400 for one name adds to `failed`, is not stored, and the next name is asked.
- After a match, `seedload.load` keeps the link and a second load writes nothing.
- Rerank: V2 chips with the place "the US" (`anywhere_us`), a fake seeds lane hitting a person whose `works_at` claim of the INBO name is dated 2025. The saved fit's place is `unknown` before the job and `abroad` after it and `search.refinish`.

`tests/test_db.py`: migration 013 adds `org_matches` to a database at 012.

## Existing tests that change, approved by the lead

The `migrate()` lists ending in 12 at `tests/test_db.py:77`, `tests/test_db.py:103`, `tests/test_orgs.py:319` and `tests/test_web.py:653` each gain 13 at the end, nothing else. No other existing test may change; stop and report a failure.

## Recorded model answers and replay tests (S6)

Unit tests and `fn-rerank` keep their recorded answers (the test database never runs the job; `refinish` reuses stored fits). After the live job, `fitcheck.line_of` (`fitcheck.py:23`) shows the ROR name for linked employers and a linked place can change who is checked, so a replayed fresh search needs its fit answers recorded again. The lead's live-run note says so.

## Hand check

1. `uv run python -m unittest` all green.
2. On a copy (`mkvar.sh d1`, `FN_VAR` set), `FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` on main and on the branch: same kept count and order everywhere.
3. On that copy, `FN_HTTP=replay uv run fn-orgs --match` stops at the first name with a replay miss, storing nothing. The live run is the lead's.

## Not doing

Fuzzy matching of FN's own, any model call, the ROR dump, a `Client-Id` header, splitting names, writing to `org_aliases.csv`. Undoing a wrong link (ROR or a removed alias) stays a manual SQL update.
