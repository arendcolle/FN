# Data model and storage layer

FN keeps everything in one SQLite file (`var/fn.sqlite3`, `src/fn/config.py:31`). `src/fn/store.py` is the only module that holds SQL, apart from `src/fn/db.py` (connections and migrations) and two tests that insert rows directly. The file has 5 migrations and 14 tables plus one FTS5 index. Two groups of tables exist. The run log (`searches`, `step_runs`, `step_payloads`, `step_calls`, `request_errors`) records what a search did. The knowledge tables (`persons`, `person_identifiers`, `sources`, `claims`, `orgs`) hold what lanes learned, and `candidates` and `match_flags` hold one search's ranked result. A person is a name plus identifiers plus quoted claims. `persons.list_status` is read once, by the ranker, and no code writes any value other than the default `candidate`. All calls are synchronous. The web app and the worker thread each get their own connection.

## 1. Tables and indexes

Schema: `src/fn/migrations/001_init.sql` unless another file is named. Row models are in `src/fn/contracts.py`.

| Table | Columns (all in `001_init.sql` unless noted) | Written by | Read by |
|---|---|---|---|
| `schema_migrations` | `version` PK (`db.py:26`) | `db.migrate` (`db.py:35`) | `db.migrate` (`db.py:27`) |
| `searches` (001:1-19) | `id` PK, `question`, `depth`, `chips_json`, `chips_origin`, `status`, `error`, `created_at`, `finished_at`, `rerun_of` FK self, `code_sha`, `dirty`, `llm_mode`, `settings_json`, `boot_id`, `user_id`, `contracts_version`; `kind` added in `002_orgs.sql:1` (default `'search'`) | `create_search` (`worker.py:60`), `set_search_status` (`worker.py:84,94,96`), `set_search_chips` (`search.py:31`), `sweep` | `get_search`, `list_searches`, `sweep` |
| `step_runs` (001:22-43) | `id` PK, `search_id` FK, `seq`, `step`, `status`, `started_at`, `ended_at`, `input_model`, `output_model`, `contracts_version`, `cost_usd`, `tokens_in`, `tokens_out`, `model`, `prompt_sha`, `error_type`, `error_message`, `traceback`, `log`; UNIQUE (`search_id`, `seq`) | `start_step`, `finish_step` (both from `steps.py:149,169,193,194`), `sweep` | `list_steps`, `get_step`, `next_step_seq` |
| `step_payloads` (001:45-49) | `step_run_id` PK FK, `input_json`, `output_json` | `start_step`, `finish_step` | `get_payload` |
| `step_calls` (001:51-65) | PK (`step_run_id`, `seq`), `kind`, `request`, `status`, `duration_ms`, `response_sha`, `response_path`, `tokens_in`, `tokens_out`, `cost_usd`, `error` | `add_call` (`steps.py:72`) | `list_calls` |
| `persons` (001:67-73) | `id` PK, `display_name`, `name_key`, `list_status`, `merged_into` FK self | `resolve_person` (`store.py:240`) | `get_persons`, `person_ids_by_group_key`, `match_claims` |
| `person_identifiers` (001:76-81) | `scheme`, `value`, `person_id` FK; UNIQUE (`scheme`, `value`) | `resolve_person` (`store.py:243`) | `resolve_person`, `person_ids_by_identifier` |
| `sources` (001:84-97) | `id` PK, `kind`, `url`, `title`, `text`, `raw_json`, `content_hash`, `normalize_version`, `source_date`, `date_method`, `fetched_at`; UNIQUE (`kind`, `url`, `content_hash`) | `upsert_source` (from `upsert_claim`, `orgs.save`, `lanes/web.py:162`) | `get_sources`, `match_claims` (join), `upsert_source` |
| `claims` (001:99-119) | `rowid` INTEGER PK, `id` UNIQUE, `person_id` FK, `kind`, `relation`, `org_id`, `value`, `quote`, `quote_start`, `quote_end`, `source_id` FK, `claim_date`, `date_precision`, `date_method`, `valid_from`, `valid_to`, `lat`, `lon`; UNIQUE (`person_id`, `kind`, `value`, `source_id`, `quote_start`); `years_json` added in `005_claim_years.sql:1` | `upsert_claim`; migration 002 rewrites `org_id` (`002_orgs.sql:13-77`) | `claims_of`, `get_claim`, `match_claims` |
| `claims_fts` (001:122-126) | FTS5 over `value`, `quote`, external content of `claims` | triggers `claims_ai`, `claims_ad`, `claims_au` (001:127-136) | `match_claims` |
| `candidates` (001:138-149) | PK (`search_id`, `person_id`), `person_ids_json`, `section`, `rank`, `score`, `lane_ranks_json`, `reason_claim_ids_json`; `tie_json` dropped and `score_parts_json` added in `004_score_parts.sql:1-2` | `save_candidates` | `list_candidates`, `count_candidates` |
| `match_flags` (001:151-158) | PK (`search_id`, `person_id`, `other_person_id`), `reason`, `shared_fact` | `save_candidates` | `list_flags` |
| `request_errors` (001:160-165) | `id` PK, `route`, `traceback`, `at` | `add_request_error` (`web/app.py:830`) | `list_request_errors` (`web/app.py:792`) |
| `orgs` (`002_orgs.sql:3-11`) | `id` PK, `name`, `country_code`, `region`, `name_lang`, `source_id` FK, `fetched_at` | `upsert_org` (`orgs.py:107`) | `get_orgs` |

Explicit indexes:

| Index | Defined | Used by |
|---|---|---|
| `searches_status` on `searches (status)` | 001:20 | `sweep` (`store.py:205`) |
| `persons_name_key` on `persons (name_key)` | 001:74 | No query. `person_ids_by_group_key` reads every row (`store.py:340`). |
| `person_identifiers_person` on `person_identifiers (person_id)` | 001:82 | No query in `store.py` filters by `person_id` here. |
| `claims_person` on `claims (person_id)` | 001:120 | `claims_of` (`store.py:357`) |

The UNIQUE constraints above create implicit indexes. `person_identifiers (scheme, value)` serves the `resolve_person` lookup.

Fields written and never read back by code: `sources.raw_json`, `sources.normalize_version` (grep of `src/`), `searches.user_id` (always None, `contracts.py:134`), `persons.merged_into` (typed `None`, `contracts.py:264`). `match_flags.shared_fact` is always NULL (`resolve.py:40` never sets it). `searches.contracts_version` is written at `store.py:95` and dropped on read at `store.py:105`.

## 2. Public methods of Store

All in `src/fn/store.py`. "Tests" lists the test files that call the method.

| Method (line) | Signature | Reads / writes | Callers in `src/` |
|---|---|---|---|
| `__init__` (55) | `(path: Path)` | none | `seedload.py:104`, `search.py:50`, `gold.py:351`, `orgjob.py:31`, `web/app.py:799` |
| `conn` property (60) | `-> sqlite3.Connection` | opens the calling thread's connection | `seedload.py:106,108`; tests |
| `close` (66) | `() -> None` | closes the calling thread's connection | `seedload.py:109`, `orgjob.py:39`, `web/app.py:808`, `worker.py:105` (via pool) |
| `migrate` (72) | `() -> list[int]` | `schema_migrations` and all DDL | `seedload.py:105`, `search.py:51`, `gold.py:352`, `orgjob.py:32`, `web/app.py:804` |
| `tx` (76) | `() -> ContextManager[Connection]` | `BEGIN IMMEDIATE` | `seedload.py:86`, `orgs.py:104`, `lanes/openalex.py:239`, `lanes/web.py:96,146`, `lanes/linkedin.py:198` |
| `create_search` (89) | `(search: Search) -> None` | W `searches` | `worker.py:60` |
| `get_search` (109) | `(search_id) -> Search \| None` | R `searches` | `worker.py:81,97`, `web/app.py:691` |
| `list_searches` (113) | `(limit: int) -> list[Search]` | R `searches` where `kind='search'` | `web/app.py:665,752` |
| `set_search_status` (118) | `(search_id, status, error=None, finished_at=None)` | W `searches` | `worker.py:84,94,96` |
| `set_search_chips` (126) | `(search_id, chips, origin)` | W `searches` | `search.py:31` |
| `next_step_seq` (132) | `(search_id) -> int` | R `step_runs` | `steps.py:146,189` |
| `start_step` (136) | `(run: StepRun, input_json: str)` | W `step_runs`, `step_payloads` in a tx | `steps.py:149,193` |
| `finish_step` (147) | `(run: StepRun, output_json: str \| None)` | W `step_runs`, `step_payloads` in a tx | `steps.py:169,194` |
| `list_steps` (157) | `(search_id) -> list[StepRun]` | R `step_runs` | `search.py:55`, `gold.py:205,241`, `orgjob.py:34`, `web/app.py:247,389,483,551` |
| `get_step` (163) | `(step_run_id) -> StepRun \| None` | R `step_runs` | `web/app.py:761` |
| `get_payload` (169) | `(step_run_id) -> tuple[str, str \| None] \| None` | R `step_payloads` | `web/app.py:248,390,553,769` |
| `add_call` (175) | `(call: StepCall)` | W `step_calls` | `steps.py:72` |
| `list_calls` (181) | `(step_run_id) -> list[StepCall]` | R `step_calls` | `gold.py:241`, `web/app.py:486,530` |
| `add_request_error` (187) | `(error_id, route, traceback, at)` | W `request_errors` | `web/app.py:830` |
| `list_request_errors` (193) | `() -> list[RequestError]` | R `request_errors` | `web/app.py:792` |
| `sweep` (197) | `(boot_id, now) -> list[str]` | R/W `searches`, W `step_runs`, in a tx | `worker.py:101` (from `web/app.py:805`) |
| `resolve_person` (218) | `(identifiers: list[Identifier], display_name: str) -> Person` | R/W `persons`, `person_identifiers`, in a tx | `seedload.py:93`, `lanes/openalex.py:244`, `lanes/linkedin.py:211`, `lanes/web.py:99` |
| `upsert_source` (249) | `(source: Source)` | R/W `sources` | `orgs.py:105`, `lanes/web.py:162`, `upsert_claim` |
| `upsert_claim` (262) | `(draft: ClaimDraft) -> Claim` | W `sources`, `claims` (and FTS by trigger), in a tx | `seedload.py:95`, `lanes/web.py:100`, `lanes/openalex.py:247,253`, `lanes/linkedin.py:212` |
| `upsert_org` (287) | `(org: Org, replace: bool)` | W `orgs` | `orgs.py:107` |
| `get_orgs` (298) | `(org_ids: list[str]) -> dict[str, Org]` | R `orgs` | `orgs.py:201`, `gold.py:130,148`, `rank.py:122`, `web/app.py:266,366` |
| `match_claims` (305) | `(query: str, exclude: tuple[SourceKind, ...]) -> list[tuple[Person, Claim, float]]` | R `claims_fts`, `claims`, `persons`, `sources` | `lanes/seeds.py:44` |
| `get_persons` (328) | `(person_ids) -> dict[str, Person]` | R `persons` | `rank.py:119`, `gold.py:219`, `web/app.py:264,364,458` |
| `person_ids_by_group_key` (335) | `(keys) -> dict[str, list[tuple[str, str]]]` | R `persons` (full scan) | `resolve.py:47`, `gold.py:144` |
| `person_ids_by_identifier` (345) | `(scheme, values) -> dict[str, str]` | R `person_identifiers` | `gold.py:220` |
| `claims_of` (354) | `(person_ids) -> list[Claim]` | R `claims` | `rank.py:121`, `gold.py:129,147,198`, `web/app.py:260,360,452` |
| `get_claim` (363) | `(claim_id) -> Claim \| None` | R `claims` | `gold.py:235`, `web/app.py:716` |
| `get_sources` (367) | `(source_ids) -> dict[str, Source]` | R `sources` | `gold.py:118,153,199`, `web/app.py:265,365,715` |
| `save_candidates` (374) | `(search_id, candidates, flags) -> int` | W `candidates`, `match_flags` (delete then insert, in a tx) | `search.py:21` |
| `list_candidates` (394) | `(search_id) -> list[Candidate]` | R `candidates` | `gold.py:218`, `web/app.py:256,359,449` |
| `count_candidates` (409) | `(search_ids) -> dict[str, int]` | R `candidates` | `web/app.py:666` |
| `list_flags` (417) | `(search_id) -> list[MatchFlag]` | R `match_flags` | `web/app.py:265` |

Notes on the table:

- Methods taking a list pass it to SQLite as one JSON string and expand it with `json_each` (for example `store.py:300`), so there is no parameter limit.
- Tests call most methods; the ones no test calls directly are `set_search_chips`, `get_step`, `add_call`, `upsert_source`, `upsert_org`, `person_ids_by_group_key` and `count_candidates` (grep of `tests/`). Tests also run SQL through `store.conn` (`tests/test_web.py:555`, `tests/test_orgs.py:81`, `tests/test_db.py:49`).
- Row-to-model glue is in the store: `STEP_COLUMNS` and the other column lists come from `model_fields` (`store.py:37-42`), so adding a model field without a column breaks the SELECT.

## 3. How a person is resolved

`resolve_person` (`store.py:218-247`):

1. Raise `ValueError` if the identifier list is empty (`store.py:223`).
2. Open `tx()`, which is `BEGIN IMMEDIATE`, so the write lock is held from the lookup to the insert (`store.py:76-87`).
3. Walk the identifiers in the order given. For each, look up `(scheme, value)` in `person_identifiers` joined to `persons`. Stop at the first hit (`store.py:227-234`).
4. With a hit, return that person unchanged. The `display_name` argument is ignored, and the name is never compared (`store.py:235-236`).
5. With no hit, create a person: uuid4 id, the given display name, `name_key(display_name)`, `list_status` `candidate` (`store.py:238-242`; `Person` default at `contracts.py:263`).
6. `INSERT OR IGNORE` every identifier with the chosen person's id (`store.py:243-246`).

Consequences:

| Input | Result |
|---|---|
| One identifier, unknown | New person with that identifier. |
| One identifier, known | The stored person. |
| Several identifiers, none known | One new person holding all. OpenAlex passes `openalex` plus `orcid` when the record has one (`lanes/openalex.py:242-243`). |
| Several identifiers, first one known | That person. The remaining identifiers attach to it, unless another person already holds them (`OR IGNORE` on UNIQUE `(scheme, value)`). |
| Several identifiers, held by two different persons | The first identifier in list order wins. The second person keeps its identifier. No merge happens and `merged_into` is never set. |
| No identifier | `ValueError`. |
| Name only | Not possible. Each caller builds an identifier from its source: `seed` from the row key (`seedload.py:93`), `openalex` and `orcid` (`lanes/openalex.py:242-243`), `profile_url` from the LinkedIn URL (`lanes/linkedin.py:211`), `mention` as `<page url>#<name_key of cleaned name>` (`extract.py:72-74`). |

Same person under different names is not decided here. `resolve.py` groups hits by `group_key(name_key)` (`resolve.py:17-42`), adds other stored persons with the same group key (`store.py:335-343`), and writes a `MatchFlag` for each extra record. It "flags, never merges" (`resolve.py:1`). The flags reach `match_flags` through `save_candidates`.

## 4. `list_status`, `in_list`, `skipped`, `candidate`, `network` and Section

Definitions: `ListStatus = Literal["candidate", "in_list", "skipped"]` (`contracts.py:16`), `Section = Literal["network", "new"]` (`contracts.py:17`).

`persons.list_status`:

| Place | What it does |
|---|---|
| `001_init.sql:71` | Column, NOT NULL, no default and no CHECK. |
| `contracts.py:263` | `Person.list_status` defaults to `candidate`. |
| `store.py:240-241` | The only INSERT. It always writes the model default `candidate`. |
| `rank.py:120` | The only read. Builds `statuses = {person_id: list_status}`. |
| `rank.py:108` | An entry is section `network` when any of its persons has status `in_list`, else `new`. |

No `UPDATE persons` exists in `src/` or the migrations (grep). So `in_list` and `skipped` are never written in production code, and every real search yields only section `new`. The `network` section is reachable only when a test passes `in_list` straight into `rank.fuse` (`tests/test_rank.py:48-50`) or builds a `Candidate` by hand (`tests/test_gold.py:77-94`, `tests/test_web.py:545`).

The word `skipped` also means a step status (`contracts.py:29`, `steps.py:190`), unrelated to `ListStatus`. Other occurrences:

| File:line | Use |
|---|---|
| `contracts.py:377`, `525`, `536` | `section` on `Candidate`, `PickResult`, `TopCard`. |
| `store.py:397` | `ORDER BY section = 'new', rank`, so `network` rows come first. |
| `rank.py:105-113` | Separate rank counters per section. |
| `web/app.py:290` | `SECTIONS = {"network": "In your network", "new": "New"}`. |
| `web/app.py:381-382` | One heading per section, empty sections are not drawn. |
| `web/app.py:230,466,581` | Section shown in legends, JSON and the trace. |
| `gold.py:83,285-286,299` | The gold judge prefers a `network` candidate and counts sections. |
| `tests/test_db.py:49`, `tests/test_orgs.py:81,99` | Insert persons with `'candidate'`. |
| `tests/test_seedload.py:18` | Reads `list_status` of loaded seed persons. |
| `tests/test_seeds_lane.py:125` | Expects section `new`. |
| `tests/test_map.py:65-69`, `tests/test_gold.py` (many) | Hand-built candidates with `new` or `network`. |

## 5. Claims: storage, dedup and FTS

`upsert_claim` (`store.py:262-285`):

1. Check that `draft.quote` equals `source.text[quote_start:quote_end]` and is not empty. `ClaimDraft` validates the same at build time (`contracts.py:287-294`), so the store repeats it.
2. Build the id as `sha1("\0".join([person_id, kind, value, source.id, str(quote_start)]))` (`store.py:272-273`). `quote_end`, `relation`, `org_id`, dates and `lat`/`lon` are not part of the key.
3. In one tx: `upsert_source(source)`, then `INSERT ... ON CONFLICT (id) DO UPDATE SET org_id, relation, years_json ... WHERE` any of those three differs (`store.py:278-283`).
4. Return the `Claim` built from the draft, not read back from the table.

Dedup rules:

- The same person, kind, value, source and quote start is one row. The table's UNIQUE on those five columns (`001_init.sql:118`) is the same tuple as the id hash.
- On a repeat, only `org_id`, `relation` and `years_json` can change. Dates, `lat`, `lon` and `quote_end` keep the first value.
- `upsert_source` compares only the id. Same id and same `content_hash` is a no-op. Same id and other hash raises `ValueError` (`store.py:249-255`). Record and vendor sources put the content hash in the id (`contracts.py:177,209`), so a changed page becomes a new source. Seed page ids hold only the URL (`seedload.py:47`), so a changed seed text file would raise on reload.
- Re-running the seed load writes nothing (`seedload.py:83`).

`claims_fts`:

- Indexes `value` and `quote` only, tokenized with `porter unicode61 remove_diacritics 2`, external content table `claims` keyed on `rowid` (`001_init.sql:122-126`).
- Insert, delete and update triggers keep it in sync (001:127-136). The conflict update in `upsert_claim` fires `claims_au`, which re-indexes the row even though `value` and `quote` did not change.
- One reader: `match_claims` (`store.py:305-326`), called only by the seeds lane (`lanes/seeds.py:44`) with the query from `fts_query` (`seeds.py:22-30`). It takes `bm25` per claim, joins `sources` to drop kinds `record`, `vendor_record` and `vendor_page` (`seeds.py:19`), groups by person with `MIN(score)`, and orders by score then person id. The lane keeps the top 100 (`seeds.py:17`).
- `tests/test_db.py:43-60` checks the tokenizer: "universite" and "run" both match.

Other claim readers: `claims_of` (ranker, gold, web), `get_claim` (source page, gold). Location claims with `lat` and `lon` feed the map (`web/app.py:298,461`).

## 6. Migrations

`src/fn/db.py:20-47`:

- Files are `src/fn/migrations/NNN_name.sql`, matched by the glob `[0-9][0-9][0-9]_*.sql` and sorted by name (`db.py:29`). The version is the first three digits.
- Applied versions live in `schema_migrations`. A file runs if its version is missing.
- Each file runs through `executescript` as `BEGIN; <file>; INSERT INTO schema_migrations ...;` (`db.py:35`), then `PRAGMA foreign_key_check`, then `COMMIT`. Any exception rolls back (`db.py:40-43`).
- Foreign keys are off during the file and back on afterwards (`db.py:33,45`), so a file can rebuild a table.
- `migrate` returns the versions it applied. It runs at app startup (`web/app.py:804`) and in each CLI entry point (see section 7). There is no down migration.
- To add one: create `src/fn/migrations/006_<name>.sql` with plain SQL and no `BEGIN` or `COMMIT`. If the change adds a column that a model reads, also edit the model in `contracts.py` and the column lists in `store.py:37-42`. `CONTRACTS_VERSION` (`contracts.py:13`) is a separate string, bumped by hand. It is stored on each search and step row; the debug page compares it (`web/app.py:556`).
- `tests/test_db.py` covers three things: a second `migrate` changes nothing (13-20), a failing migration leaves no table and no version (30-40), and the pragmas hold (22-28).
- Existing examples: 002 adds `kind` and the `orgs` table and rewrites claim `org_id` values with 63 `UPDATE` statements (`002_orgs.sql:13-77`). 003 rewrites stored chip JSON. 004 drops and adds a column (`ALTER TABLE ... DROP COLUMN`). 005 adds `years_json`.

## 7. Transactions and connections

Connections (`db.py:8-17`, `store.py:55-73`):

- `Store` keeps one connection per thread in a `threading.local`, opened on first use of `store.conn`.
- `connect` creates the directory with mode 0700, opens with `isolation_level=None` (autocommit, so the code controls BEGIN) and `check_same_thread=True`, row factory `sqlite3.Row`.
- Pragmas on every connection: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000` (5 s), `secure_delete=ON`.
- `tests/test_db.py:22-28` asserts all four.

Threads in the web process:

| Thread | Connection used for |
|---|---|
| Event loop thread | Every `async def` route (all routes are async, `web/app.py:670-791`), the guard middleware (`web/app.py:822-833`), `migrate`/`sweep` in lifespan (`web/app.py:804-805`), `store.close` at shutdown (`web/app.py:808`). |
| `fn-worker` thread (one, `ThreadPoolExecutor(max_workers=1)`, `worker.py:47`) | `Worker.execute` and so all search writes. `shutdown` submits `store.close` to this pool to close its connection (`worker.py:103-106`). |

So there are at most two connections plus the CLI's own. WAL lets the event loop read while the worker writes. Two writers wait on the 5 s busy timeout. A route that reads a search being written sees the last committed state.

Transactions:

- Single-statement writes (`create_search`, `set_search_status`, `add_call`, `upsert_source` alone, `upsert_org` alone and the like) run in autocommit, one statement each.
- `tx()` runs `BEGIN IMMEDIATE`, rolls back on any `BaseException`, otherwise commits (`store.py:75-87`). Inside an open transaction `tx()` yields the same connection and leaves commit to the outer one (`store.py:78-80`). That is how `upsert_claim` and `resolve_person` join the lane-level transactions.
- Methods that use `tx()` themselves: `start_step`, `finish_step`, `sweep`, `resolve_person`, `upsert_claim`, `save_candidates`.
- Callers that open an outer `tx()`: `seedload.load` (the whole seed load, `seedload.py:86`), `orgs.save` (`orgs.py:104`), the OpenAlex lane (`lanes/openalex.py:239`), the web lane per page and for page storage (`lanes/web.py:96,146`), the LinkedIn lane (`lanes/linkedin.py:198`).
- Step rows are written outside those transactions: `start_step` commits before the step runs and `finish_step` in `finally` (`steps.py:149,169`), so a crashed step leaves a `running` row that `sweep` later marks `interrupted` (`store.py:197-216`).
- `sweep` marks `queued` or `running` searches from another `boot_id` as `interrupted`, and their `running` steps (`store.py:203-215`). It runs at every app start.

## 8. Entry points that open the store

| Entry point | File:line | Mode |
|---|---|---|
| Web app | `web/app.py:799-808` | `Store`, `migrate` + `sweep` in lifespan, `close` at shutdown. |
| `fn-search` | `search.py:50-51` | `Store`, `migrate`, runs a search on the calling thread. No `close`. |
| `fn-seed` | `seedload.py:104-109` | `Store`, `migrate`, `load`, `close`. |
| `fn-orgs` | `orgjob.py:31-39` | `Store`, `migrate`, job, `close`. |
| `fn-gold` | `gold.py:351-352` | `Store`, `migrate`. |

Tests use `make_db` (`tests/helpers.py:35-41`, a temp dir with a fresh migrated file) and `make_seeded_db` (`tests/helpers.py:78-83`, which copies a once-per-process seeded and org-loaded file after a WAL checkpoint, `helpers.py:72`). The seeded fixture has 4,940 persons (`tests/test_seedload.py:30-31`).

## Things that surprised me

- Nothing sets `in_list`, so the `network` section can never appear in a real search (`rank.py:108`, `store.py:240`).
- `person_identifiers_person` and `persons_name_key` indexes serve no query; `person_ids_by_group_key` scans all of `persons` (`store.py:340`).
- `sources.raw_json` and `sources.normalize_version` are written but nothing in `src/` reads them (`001_init.sql:90,92`). `match_flags.shared_fact` is read and written but no code sets a value (`resolve.py:40-41`).
- `upsert_claim` updates only `org_id`, `relation` and `years_json` on a repeat; a changed date or coordinate is silently dropped (`store.py:280-282`).
- `resolve_person` never merges: a second identifier held by another person stays there and `merged_into` is never set (`store.py:243-246`).
- A seed source id has no content hash, so editing a seed text file makes `fn-seed` raise instead of storing a new version (`seedload.py:47`, `store.py:253`).
