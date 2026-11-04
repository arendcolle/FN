# How the FN slice is built: architecture and contracts

2026-11-04 · version 3.1 (the web and LinkedIn lanes join the seed and OpenAlex lanes; 3.0 dropped the tie label, so institutions are records and the ranker scores Belgian affiliation claims directly; 2.3 moved place ordering into the OpenAlex lane), after six independent architecture reviews (principal engineer, security, data and contracts, debuggability, product fit, new maintainer), one plan review and one review per build task, plus four independent reviews of the web lanes plan (code fit, ownership, inputs and tests, vendor facts and safety)

**TL;DR.** One Python package, `fn`, runs a FastAPI app on 127.0.0.1 with one SQLite file. A search is a sequence of named steps. Each step takes one Pydantic model and returns one, and reaches the outside world only through a `StepContext`. The runner writes a step row before the step starts and records its input, output, every HTTP and LLM call, timing, cost and full traceback. Lanes store sources, people and claims as they find them, through one identity function, and pass ids onward instead of text. Four lanes find people: the seed lists, OpenAlex, a web search through Parallel and a LinkedIn profile search through Apify. The web and LinkedIn lanes keep every person they find, the seed lane keeps its top 100 and the OpenAlex lane keeps its in-scope authors among the first 2,000 it reads. The ranker owns the order of the fused list and has no cut. Institutions are records with facts from ROR, Wikidata or OpenAlex. The ranker fuses the lane rankings with one more ranked list, people ordered by the years their claims place them at a Belgian organization, and stores each term as a score part. Every lane also reports what it considered and why it dropped each person, so the gold runner can say for each known pick where it was lost. LLM calls go through the Claude CLI on the owner's subscription, with record, replay and prefer fixtures for tests and gold runs. Pages are plain HTML from an escape-by-default builder, and the map is MapLibre with a pinned copy of the OpenFreeMap Positron style.

## Ties are evidence, not a label

The owner decided this on 2026-11-02, after the first build, and it is built as of version 3.0. The build plan is `notes/mvp0/ties-as-evidence-plan.md`.

FN does not store or compute a tie type. A person's ties are affiliation claims (studied at, worked at, member of, born in), each with its source, quote and date. The ranker takes those claims as inputs, alongside topic and place claims, and scores them directly, for example a dated claim at a Flemish institution. No intermediate tie value sits between the claims and the score. An institution's region is a fact about the organization, looked up from ROR, not a fact about the person. Any badge or filter shown to staff is computed from the same claims when it is shown.

In this slice the ranker scores one feature from those claims, `belgian_years`: the distinct years of claims at organizations with country code BE. Topic and place reach the score through the lanes' own rankings. Region, name language and born-in claims are not scored.

The owner settled three more points the same day:

- Every Belgian organization counts the same for ranking. Region and name language are shown on the card, not scored.
- Any claim that places a person at a Belgian organization counts, whatever its relation: studied, worked, member (KVAB foreign members too), fellow, consul, hosted.
- fn-gold prints the gold tie next to the evidence and gives no verdict.

How the build handles the facts it met:

- ROR gives VUB and ULB the same region, `BRU`. The language of the ROR display name tells them apart (VUB `nl`, ULB `fr`), and the card shows both facts. Neither changes the score, by the first decision above.
- KVAB has no ROR record, so its facts come from Wikidata (Q1301699, country through P17 and P297).
- A born-in claim names a place, not an institution. The web lane stores born_in and lives_in claims as location claims with no coordinates, so the map skips them, and place-of-birth lookups are not built.
- Companies have no ROR id. An employer claim without one keeps `org_id` empty, does not count and shows its spelling.

## Requirements for this slice

**Goal.** Let the owner run real questions end to end and see why each person was or was not found, so the full MVP is built on contracts that have already been tested.

**User.** The owner alone, on a laptop, debugging the pipeline.

**Acceptance criteria.**

1. A question becomes chips (topics, institutions, place, ask type), and an edited chip set reruns the search as a new search linked to the first (F1).
2. Every search, its steps, calls and results are stored and can be reopened (F2).
3. The seed lane ranks the 4,940 people from the five seed lists, each result with the claim that matched (F3 shape).
4. The OpenAlex lane finds authors with dated affiliations, each stored as a claim at an institution record (F4, part).
5. Every shown claim has a source link, a quote found at stored offsets in the source text, and a date with its method, or undated when the source states none. A person with no claim at a Belgian organization shows "No Belgian organization found in" with the sources that were read. When an institution's facts are not stored, the card says "org facts not stored for" those ids instead (F5, F6).
6. One person never shows twice in one result list. Name-only matches are flagged, never merged (F9, part).
7. A map toggle shows people with a dated location claim (F8, part).
8. The debug pages show every step with status, duration, cost, its calls, links to its full input and output JSON, its log lines and, on failure, the full traceback. Any unhandled request error shows its traceback and is stored.
9. `uv run python -m unittest` passes. `uv run fn-gold` runs all 28 gold cases and prints per pick: found, event page or missed, section, rank, the gold tie next to the person's Belgian claims and `belgian_years` count, and the step where a miss was lost. Its `report.md` also holds the lanes behind each pick and each search's cost.

**Success measure.** On the dev cases GS-02 and GS-10, at least 3 of the 4 picks that `data/gold/reach.json` marks reachable from the question's own chips (all four are GS-10; no GS-02 pick is reachable, see reach.json's note) rank in the top 10 of their section, and every miss has a step and reason in the gold report. The held-out cases (GS-15, GS-16, GS-23, GS-24, GS-28) are reported, not targeted. Picks that no slice lane can reach are labelled "no lane in slice", not "missed".

**Out of scope.** FN's own page reader (the web lane takes page text from Parallel, and FN fetches no page itself), Add, Skip and Merge, the list page, export, import of the old sheet, login, depths beyond Quick, DBOS, embeddings, replay of a step, payload purging and any styling.

## Paradigms

- **Contracts are Pydantic models in one module.** Every value that crosses a module boundary is a frozen model or Literal from `fn/contracts.py`, including every step's input and output. Modules never pass dicts or rows to each other. `CONTRACTS_VERSION` is stored with every serialized payload.
- **Functional core, thin shell.** Parsing checks, the FTS query builder, year counting, duplicate flags and ranking are pure functions. Only `store.py` runs SQL, only `net.py` and `llm.py` make outside calls, and only `web/` handles HTTP requests.
- **Steps reach the world only through `StepContext`.** A step is `(ctx, InputModel) -> OutputModel`. `ctx` is frozen and holds `search_id`, `store`, `llm`, `http` (an `HttpClient` protocol that net.py implements), `now()`, `new_id()`, `log` and `settings`. Tests swap every one of them.
- **Write as you go, idempotently.** A lane step writes its sources, people and claims before it returns, using upserts on natural keys, so a rerun or a future DBOS retry writes nothing new. Later steps receive ids, quotes and values, never source text.
- **Errors stay visible.** A step row exists before the step runs. A failure stores the traceback, marks the search failed and stops the search. Nothing is retried silently, and every caught exception is recorded.
- **Plain SQL with numbered migrations.** No ORM. An applied migration is never edited; a change is a new `NNN_name.sql`.

## Module layout

```text
pyproject.toml              uv project; scripts fn-serve, fn-seed, fn-gold, fn-orgs
src/fn/
  contracts.py              every model, Literal and normalize(); record_source(), page_source(), clean_name(); CONTRACTS_VERSION
  config.py                 Settings (frozen): paths, mode, host, port, llm mode, keys as SecretStr, the FN_LINKEDIN switch
  db.py                     connect() per thread (WAL, foreign keys, busy_timeout, secure_delete); migrate()
  migrations/               001_init (the tables below), 002_orgs, 003_chip_refs, 004_score_parts, 005_claim_years
  store.py                  all SQL; resolve_person(); upserts; reads for pages and debug
  net.py                    the one outbound HTTP client, GET and POST: timeouts, size cap, scheme check, keys per host, call recording, cache modes
  llm.py                    StructuredLLM protocol; ClaudeCli; FixtureLLM (record, replay and prefer)
  prompts/parse.md          system prompt for the parse task
  prompts/extract.md        system prompt for the extract task (the people one part of a page names)
  steps.py                  StepContext, run_step(), CallRecorder, redact(), log capture
  worker.py                 one-thread executor, the search lifecycle, the startup sweep
  search.py                 the Quick workflow: which steps run in which order
  parse.py                  question -> Chips, span checks
  extract.py                page text -> the people it names, quotes located in the text, claim drafts
  lanes/__init__.py         Lane protocol, LANES registry
  lanes/seeds.py            seed lane: fts_query() and the FTS5 search
  lanes/openalex.py         OpenAlex lane: works -> authors -> affiliations, considered list
  lanes/web.py              web lane: Parallel Search and Extract, pages as vendor_page sources, people through extract.py
  lanes/linkedin.py         LinkedIn lane: Apify profile search, profiles as vendor_record sources with dated claims
  orgs.py                   spelling -> org id from data/org_aliases.csv; ROR and Wikidata records -> facts; save(); belgian_claims()
  orgjob.py                 fn-orgs: fetches every id in the alias file and saves its facts, as a job with one step
  resolve.py                one entry per name (group key) in a result list; name-only match flags
  rank.py                   the belgian_years list, reciprocal rank fusion with score parts, section assignment
  seedload.py               data/seeds/*.jsonl -> persons, sources, claims (fn-seed)
  geo.py                    place chip -> coordinates and radius, from a GeoNames cities15000 extract fetched through net.py; area() is the lookup the OpenAlex and LinkedIn lanes share
  gold.py                   fn-gold: runs cases, matches picks, labels event-page finds, writes the report and a scoring CSV
  web/app.py                routes, middleware (host, origin, CSP), error pages, request_errors
  web/html.py               escape-by-default builders; Safe only inside this module
  web/static/               vendored maplibre-gl, pinned positron.json, map.js, fn.css
data/org_aliases.csv        spelling -> org id (ror:<id> or wikidata:<Q>); 121 spellings, 65 ids
data/org_aliases_unmapped.txt  seed and LinkedIn spellings with no id yet
data/gold/gold-set.json     copy of the delegation gold set
tests/                      unittest; helpers.make_db(); fixtures/llm, fixtures/http
```

## Contracts

### Vocabularies

Each is a `Literal` defined once in `contracts.py`. SQL stores them as text without CHECK constraints, so a vocabulary grows by changing one line.

| Name | Values |
| --- | --- |
| `ListStatus` | candidate, in_list, skipped |
| `Section` | network, new |
| `ClaimKind` | topic, affiliation, role, location, availability |
| `Relation` | studied_at, works_at, worked_at, affiliated_with, hosted_by, fellow_of, member_of, consul_for, born_in, lives_in |
| `DateMethod` | page_date, sitemap, wayback_first_seen, document_heading, record_field, read_date, sheet_date, staff_edit, stated_in_quote |
| `DatePrecision` | year, month, day |
| `SourceKind` | page, record, seed_page, import, vendor_record, vendor_page |
| `IdentifierScheme` | seed, openalex, orcid, profile_url, mention |
| `StepStatus` | running, ok, error, skipped, interrupted |
| `SearchStatus` | queued, running, done, failed, interrupted |
| `SearchKind` | search, job (fn-orgs stores its run as a job) |
| `LaneName` | seeds, openalex, web, linkedin |
| ScorePart `feature` | a `LaneName`, or belgian_years |
| `ChipOrigin` | parsed, edited |
| `LLMMode` | live, record, replay, prefer (the values of `FN_LLM`) |
| `CacheMode` | refresh, prefer, only (what net.py does with its response cache for a call) |
| `GoldTie` | flemish, belgian, none, unverified (the gold set's own label, printed by fn-gold, never computed) |
| `PickVerdict` | found, event page, missed, no lane in slice |

### Models

| Model | Fields | Flow |
| --- | --- | --- |
| `Span` | `start`, `end` | inside Chip |
| `Chip` | `text`, `span: Span \| None`, `origin: ChipOrigin`, `ref: str \| None` (for example `ror:...`) | parse to lanes; the form posts edited chips |
| `Place` | `text`, `span: Span \| None`, `origin`, `kind: metro \| anywhere_us \| abroad \| None` | inside Chips |
| `Chips` | `topics: list[Chip]`, `institutions: list[Chip]`, `place: Place \| None`, `ask: Literal[talk, mentor, host, join, other] \| None` | |
| `Search` | `id`, `kind`, `question`, `depth`, `chips`, `chips_origin`, `status`, `error`, `created_at`, `finished_at`, `rerun_of`, `code_sha`, `dirty`, `llm_mode`, `settings_json`, `boot_id`, `user_id: None` | store to web and gold |
| `Source` | `id` (sha1 of kind and URL; a record, vendor_record or vendor_page source adds its content_hash, so a changed record, profile or page is a new source), `kind`, `url` (http or https only), `title`, `text` (normalized), `raw_json \| None`, `content_hash`, `normalize_version`, `source_date`, `date_method`, `fetched_at` | written by lanes and seedload |
| `OrgFacts` | `id` (`ror:<id>`, `wikidata:<Q>` or `openalex:<I…>`), `name`, `country_code`, `region` (ROR subdivision code), `name_lang` (language of the ROR display name), each `None` when the source has no value | orgs.py and the OpenAlex lane to `orgs.save` |
| `Org` | the OrgFacts fields, plus `source_id` and `fetched_at` | store to rank, web and gold |
| `Claim` | `id` (sha1 of person, kind, value, source, quote_start), `person_id`, `kind`, `relation \| None`, `org_id \| None` (an Org id), `value`, `quote`, `quote_start`, `quote_end`, `source_id`, `claim_date` (ISO partial), `date_precision`, `date_method`, `valid_from`, `valid_to`, `years` (the calendar years the source lists, when it lists them; OpenAlex affiliation years have gaps), `lat`, `lon` (location only) | written by lanes and seedload |
| `Person` | `id` (uuid), `display_name`, `name_key`, `list_status`, `merged_into: None` | `store.resolve_person` only |
| `ClaimDraft` | the Claim fields without ids, plus the Source it quotes; a validator checks `source.text[quote_start:quote_end] == quote` | lanes and seedload to store.upsert_claim |
| `Identifier` | `scheme` (an `IdentifierScheme`), `value` | lane to store.resolve_person |
| `PageRelation` | `relation: Relation`, `org`, `quote`, `year_from: int \| None`, `year_to: int \| None` (years the quote states) | inside PageMention |
| `PageMention` | `name`, `quote`, `role: str \| None`, `relations: list[PageRelation]` | inside PagePeople |
| `PagePeople` | `people: list[PageMention]`, the answer of the extract task for one chunk of a page | llm.py to extract.py |
| `Located` | `name` (cleaned), `role`, `span` (the mention quote's offsets in the page text), `relations: list[tuple[PageRelation, Span]]` (the kept relations with their offsets) | extract.py to `extract.drafts` |
| `LaneIn` | `search_id`, `chips`, `depth` | search.py to every lane |
| `LaneHit` | `person_id`, `name_key`, `lane`, `rank`, `score`, `matched_on` (the FTS match; the OpenAlex query and place; the web page's rank, title and URL; the LinkedIn result's rank, headline and URL), `claim_ids` | inside LaneOut |
| `Considered` | `person_key`, `name`, `stage`, `kept: bool`, `reason` | inside LaneOut |
| `LaneOut` | `lane`, `query`, `total_seen`, `hits`, `considered` | lane to resolve |
| `MatchFlag` | `person_id`, `other_person_id`, `reason`, `shared_fact \| None` | resolve to store |
| `Entry` | `name_key` (the group key), `person_ids` (one or more), `hit_person_ids` (the records a lane returned; the rest share only the name), `lane_ranks`, `claim_ids`, `flag: str \| None` | resolve to rank |
| `ScorePart` | `feature`, `rank` (the entry's rank in that list), `points` (`1 / (60 + rank)`), `claim_ids` (the claims counted), `detail` | inside Candidate |
| `Candidate` | `search_id`, `person_id` (the entry's first person), `person_ids`, `section`, `rank`, `score` (the sum of its parts), `lane_ranks`, `reason_claim_ids`, `score_parts` | rank to store, web, gold |
| `StepRun` | `id`, `search_id`, `seq`, `step`, `status`, `started_at`, `ended_at`, `input_model`, `output_model`, `contracts_version`, `cost_usd`, `tokens_in`, `tokens_out`, `model`, `prompt_sha`, `error_type`, `error_message`, `traceback`, `log` | steps.py |
| `StepCall` | `step_run_id`, `seq`, `kind: http \| llm`, `request` (redacted; a POST holds its compact JSON body), `status`, `duration_ms`, `response_sha`, `response_path`, `tokens_in`, `tokens_out`, `cost_usd`, `error` | net.py and llm.py through the recorder |
| `RequestError` | `id`, `route`, `traceback` (redacted), `at` | store to web |
| `LLMResult[T]` | `value: T`, `model`, `cost_usd`, `tokens_in`, `tokens_out`, `billing` | llm.py to the calling step |
| `GoldCase` | `id`, `question`, `source_url` (the gold set's `source`, the case's own event page; `None` when it has none), `picks` | data/gold to gold.py |
| `PickResult` | `case_id`, `name`, `verdict: PickVerdict`, `section`, `rank`, `gold_tie`, `belgian`, `lanes` (each lane behind the pick's candidate with its rank, such as `seeds #3; web #5`; empty without a candidate), `lost_step`, `lost_reason` | gold.py to the report |
| `CaseResult` | `case_id`, `group`, `question`, `chips`, `search_id`, `status`, `http_cost_usd` and `llm_cost_usd` (the search's vendor call costs and LLM call costs, each summed from its step calls by call kind; a call with no cost counts as 0), `picks`, `top` | gold.py to the report |

Step models are named `<Step>In` and `<Step>Out` and listed in contracts.py next to the step order: `ParseIn(question)` and `ParseOut(chips)`, `LaneIn` and `LaneOut` for every lane, `ResolveIn(outs: list[LaneOut])` and `ResolveOut(entries, flags)`, `RankIn(entries, chips)` and `RankOut(candidates)`, `SaveIn(candidates, flags)` and `SaveOut(count)`. The fn-orgs job has one step, `OrgsIn(ids)` and `OrgsOut(orgs)`. `CONTRACTS_VERSION` is 2 since the tie label went; the trace page shows a payload stored under version 1 as a note instead of parsing it. Version 3.1 added Literal values, models and fields with defaults and changed no existing field, so it stays 2.

### Rules

- **Identity.** `Person.id` is always a uuid. `store.resolve_person(identifiers, display_name)` is the only way to get one: it returns the person that already holds any of the identifiers, else creates one. `person_identifiers` has UNIQUE(scheme, value). A shared name alone never joins two people; resolve.py flags it. A name on a web page gets `Identifier("mention", "<url>#<name key>")` from `extract.identifier`, so a rerun over the same URL finds the same person even when the page text changed. A LinkedIn profile gets `Identifier("profile_url", <canonical URL>)`.
- **Seed people are candidates.** Seed people start as `list_status = candidate` with a `seed:<row_key>` identifier and a `fellow_of` or `member_of` claim. Section `network` means `list_status = in_list`, which no one has until Add exists. So in this slice every result is in section `new`, and the card says which seed list holds the person.
- **One card per name.** resolve.py groups hits that share a person id or a group key into one Entry. The group key is `name_key` without middle initials (`contracts.group_key`), so OpenAlex's "Nick M. Vandewiele" and the seed row "Nick Vandewiele" share a card; a first or last initial stays. The trace page matches names by the same key. The persons stay separate rows; the card lists every record and says "same name in N records, not merged". rank.py fuses lane ranks over the entry, so being found by two lanes lifts a person.
- **Quotes.** `normalize()` (NFC, NBSP to space, straight quotes, single spaces) lives in contracts.py with a version number. A claim is valid only when `source.text[quote_start:quote_end] == quote`. The ClaimDraft validator checks this where the claim is built, and `store.upsert_claim` checks it again on insert. A record Source's `text` holds one `field.path: value` line per field used, and the raw response sits in `raw_json`. A vendor_page Source's `text` is the vendor's markdown as plain text. `contracts.page_source` does the conversion, and links keep their anchor text while emphasis marks, heading markers and backslash escapes go. `extract.locate` finds an LLM quote in that text, and the claim stores the text at those offsets, so the rule holds by construction.
- **Dates.** `claim_date` is the date the quote supports, as `YYYY`, `YYYY-MM` or `YYYY-MM-DD` with its precision. `source_date` is the date of the source. A BAEF row with only a year gets `claim_date = year`, `date_method = record_field`, precision year. A claim from a web page gets a date only when its quote states a year. `valid_from` and `valid_to` then hold the years stated, `claim_date` is the later one, the precision is year and `date_method` is `stated_in_quote`. Otherwise `claim_date` stays empty and the ranker counts one undated unit. The page's own date stays on the Source and shows on its source page. FN never dates a claim by the day it read the page, because a page read in 2026 that says someone studied at KU Leuven says nothing about 2026. A LinkedIn entry takes its years from the entry, with `record_field`.
- **Institutions.** An institution is an `orgs` row. `orgs.org_id(text)` maps a spelling to its id through `data/org_aliases.csv`, a hand-kept list, because ROR's affiliation matcher picked an institution for only 34 of the 80 most common seed spellings, 2 of them wrong. A spelling not in the file leaves `org_id` empty. `orgs.save(store, facts, source, replace=)` is the only writer, and each row points at the Source its facts came from. fn-orgs fetches every id in the alias file from ROR or Wikidata and replaces stored rows. The OpenAlex lane saves the institutions in the author records it already reads and never replaces a stored row. An empty fact stays empty. The web and LinkedIn lanes map the organizations they read through `orgs.org_id` and save no facts. The facts come from fn-orgs, so a new id in the alias file counts as Belgian only after fn-orgs has fetched it.
- **Belgian evidence.** A claim counts as Belgian when its org has `country_code = BE`, whatever its kind or relation (`orgs.belgian_claims`). Region and name language are shown, never scored. The ranker counts it only for the records a lane returned, never for a record that shares only the name. Cards and fn-gold compute what they show from the stored claims each time, through the same function. Nothing stores a label.
- **Secrets.** Keys are `SecretStr`: `OPENALEX_API_KEY`, `PARALLEL_API_KEY` and `APIFY_TOKEN`, each from its env var, else the Keychain. `redact()` replaces every secret value with `***` in payloads, call records, error messages, tracebacks, log lines and request errors. Each key travels in a header, only to its own host over https (see Outbound calls). Traceback locals are never captured.
- **Untrusted text.** The LLM protocol is `structured(task, data: dict[str, str], schema)`. llm.py puts each data value in a tagged block on stdin, and the system prompt says tagged content is data. LLM output is used only as schema fields and is escaped like any other text. A value that holds its own closing tag raises `TagError`, which extract.py handles per chunk.

## Storage

One SQLite file, `var/fn.sqlite3`. `var/` is created with mode 0700 and gitignored. The seed text layers (`data/seeds/raw/**/*.txt`, 2.1 MB) are tracked, because sources and the offset test read them; the raw HTML and PDF copies stay ignored. Each thread opens its own connection with WAL, `foreign_keys=ON`, `busy_timeout=5000` and `secure_delete=ON`.

| Table | Key and notes |
| --- | --- |
| `schema_migrations` | version |
| `searches` | id; fields of Search; `kind` (search or job) |
| `step_runs` | id; metrics only |
| `step_payloads` | step_run_id; input_json and output_json, kept apart so they can be purged later |
| `step_calls` | (step_run_id, seq) |
| `persons` | id; list_status, merged_into |
| `person_identifiers` | UNIQUE(scheme, value); person_id |
| `sources` | id; UNIQUE(kind, url, content_hash) |
| `claims` | rowid INTEGER PRIMARY KEY, id TEXT UNIQUE; UNIQUE(person_id, kind, value, source_id, quote_start) |
| `claims_fts` | FTS5, content='claims', tokenize='porter unicode61 remove_diacritics 2', over value and quote; insert, update and delete triggers |
| `orgs` | id (`ror:`, `wikidata:` or `openalex:`); name, country_code, region, name_lang; source_id REFERENCES sources, fetched_at |
| `candidates` | PRIMARY KEY(search_id, person_id); `score_parts_json` (empty for rows stored before migration 004) |
| `match_flags` | (search_id, person_id, other_person_id) |
| `request_errors` | id; route, traceback, at |

`migrate()` runs each file in a transaction with foreign keys off, then runs `PRAGMA foreign_key_check` and turns them back on. A migration that rebuilds `claims` also rebuilds `claims_fts`. Migration 002 adds `orgs` and `searches.kind` and rewrites every stored claim from the old internal org ids (`ku-leuven`, `kvab` and the rest) to the new ids, setting an old id with no new one to empty. Migration 003 rewrites stored chip refs from `ror:https://ror.org/<id>` to `ror:<id>`. Migration 004 drops `candidates.tie_json` and adds `score_parts_json`. Migration 005 adds `claims.years_json`.

## The Quick workflow

```text
worker.submit(search_id)                         one ThreadPoolExecutor(max_workers=1), made in the app lifespan
  search.run(ctx)                                guarded: any exception sets the search failed with its traceback
    run_step("parse", ParseIn)       -> ParseOut   status skipped when the form sent chips
    run_step("lane:seeds", LaneIn)   -> LaneOut    FTS5 over claims; aggregate bm25 per person
    run_step("lane:openalex", LaneIn)-> LaneOut    works search, author records, institutions; writes as it goes
    run_step("lane:web", LaneIn)     -> LaneOut    Parallel Search and Extract; pages as vendor_page sources; people read per chunk by Haiku
    run_step("lane:linkedin", LaneIn)-> LaneOut    Apify profile search; profiles as vendor_record sources; off unless FN_LINKEDIN=1
    run_step("resolve", ResolveIn)   -> ResolveOut one entry per name (group key); name-only flags
    run_step("rank", RankIn)         -> RankOut    RRF over the lane lists and belgian_years; equal scores ordered by person id
    run_step("save", SaveIn)         -> SaveOut    candidates and flags in one transaction, then status done
```

A lane whose vendor key is missing returns a note and no hits, and the search goes on. A non-2xx answer from a vendor, such as a 402 or a 422, fails the step and the search, as an OpenAlex error does, and so does a call that times out. These give a note and the search goes on: an Extract error for one URL, an empty Parallel Search result, and the LinkedIn lane when it is off or has no recorded run for its input. A replay miss in the web or OpenAlex lane fails the step.

At startup the worker marks every queued or running search from an earlier boot as `interrupted`, and its running steps too. The results page refreshes every 2 s with a meta refresh until the search ends.

fn-orgs runs outside the Quick workflow. It stores one `searches` row of kind `job` with one `orgs` step, so its calls, log and traceback show on the same debug pages. The searches list on `/` shows kind `search` only.

### Ranking

rank.py fuses ranked lists by reciprocal rank fusion: an entry gets `1 / (60 + rank)` from each list it is on, and its score is the sum. No weight is set by hand. Each term is stored as a ScorePart, so the card can show where every point came from.

- **Lane lists.** Each lane's best rank for the entry. The web and LinkedIn lanes keep every person they find, so the web lane adds many people to section `new` (69 from 10 pages on GS-02). The seed lane keeps its top 100 and the OpenAlex lane its in-scope authors among the first 2,000 (see Lanes). rank.py owns the order of the fused list and would own a cut across lanes, and has none.
- **belgian_years.** rank.py reads the stored claims of the entry's hit records and keeps those at an org with `country_code = BE`. Each claim gives units: the years the source lists (`Claim.years`) when it lists them, else every year from `valid_from` to `valid_to` when both are set and in order, else the years of `valid_from`, `valid_to` and `claim_date` that are set, else one `undated` unit. Listed years come first because OpenAlex lists affiliation years with gaps, and filling the span would count years no source states. The entry's count is the number of distinct units, so the same year from two sources counts once. Entries with a count of 0 are not on the list. Equal counts share a rank (1, 2, 2, 4), so no arbitrary order enters the score. A claim whose org has no stored facts does not count, and the card names that org.

### Lanes

A lane is a module in `lanes/` with `name: LaneName` and `run(ctx, LaneIn) -> LaneOut`, listed in `LANES`. search.py runs each as step `lane:<name>`, in the order of `LANES`. A lane reads the chips, stores the sources, people and claims it finds, and returns the people it keeps as hits. The web and LinkedIn lanes keep every person they find, the seed lane its top 100 and the OpenAlex lane its in-scope authors among the first 2,000. The ranker owns the order of the fused list. To add a lane: add its name to `LaneName`, write the module, add it to `LANES`, add fixtures under `tests/fixtures/http/<lane>/` and a test that its claims pass the quote rule.

- **Seed lane.** Topic and institution chips both count as a query. `fts_query(chips)` is pure: it splits each chip into tokens, wraps each in double quotes with inner quotes doubled, ORs tokens within a chip and ORs across chips. Institution chips are expanded through the spellings `data/org_aliases.csv` lists for the same org id, such as "M.I.T.", which the tokenizer splits. The lane returns at most 100 hits (`MAX_HITS`). The SQL groups bm25 by person and keeps the best-matching claim as `matched_on`. Claims from `record`, `vendor_record` and `vendor_page` sources are excluded (`store.match_claims(query, exclude=)` takes a tuple of source kinds), because the OpenAlex, web and LinkedIn lanes rank those themselves and seed ranks would otherwise depend on past searches. `page` and `seed_page` sources stay searchable.
- **OpenAlex lane.** Two queries, each a list call costing $0.0001 to $0.001:
  Institution chips run first, because the lane reads at most 2,000 authors (`MAX_AUTHORS`) and an institution list is the narrower query.
  1. Topic chips: `works?search=<topic>&filter=institutions.country_code:BE&per_page=100`, page 1 only, one call per topic chip, and the authors on those works. `reach.json` was recorded at this depth.
  2. Institution chips: `authors?filter=last_known_institutions.ror:<ror>,affiliations.institution.country_code:BE&per_page=200`, every page until `meta.count` is reached, capped at 4 pages (800 authors). MIT has 362 authors, so 2 calls, about $0.0002; Lermusiaux, de Wit and Goemans sit on page 1 (positions 157, 161, 190) and Janjevic on page 2 (position 47). A question with an institution and no topic still runs. `reach.json` was recorded at this depth. Institution chips resolve to ROR ids through `data/org_aliases.csv`.
  Author records are fetched in batches with `filter=ids.openalex:A1|A2|...`. When the question has a place of kind metro or no kind, `geo.area` turns it into coordinates and a radius (the LinkedIn lane calls the same function), and each author gets a haversine distance to their last known institution only. Place ranks and never drops. The lane's scope is an author with a Belgian affiliation that has years (`in_scope`); it filters and never ranks. The lane orders kept authors by place group (inside the radius or no place chip, then place unknown, then outside), then by the order OpenAlex returned them, and returns every kept author as a hit. Each hit's affiliations are stored as claims at org ids (`ror:<id>`, else `openalex:<I…>`), and their institutions are saved as org rows. Each hit's `matched_on` ends with the distance and the last known institution, and the card shows it. An author with no last known institution or no institution geo is kept and marked "place unknown". The newest affiliation is not a fallback, because OpenAlex affiliations can be wrong (it places Baeyens, who has no last known institution, in Novi, Michigan in 2023). Every author seen goes into `considered` with the stage and reason. `Retry-After` is honoured once up to 30 s; a longer wait fails the step and names the wait. Chips that are only a place produce no hits and say so in `considered`.
- **Web lane.** Two POST calls to Parallel per search, then one Haiku call per chunk of each result page. Chips with neither a topic nor an institution give one note and no call. FN fetches no page itself, so every quote comes from the text Parallel returns.
  1. Search: `request(chips)` builds `{objective, search_queries, mode: "fast"}` from the chips, so an edited chip set changes the query. The objective is one sentence, such as "People with a connection to Belgium who work on 6G, telecom in New York and New Jersey". `search_queries` holds one query per topic chip with the place text, then one per institution chip, at most 5. This call costs $0.001.
  2. Extract: one call for the result URLs, each once in rank order, for up to 12,000 characters of full content a page, with a 20 s live-fetch timeout and `timeout_s=90`. Parallel bills it per URL as `sku_extract_excerpts`, also when it returns full content, so a run over 10 pages costs $0.011 with the Search call. The lane prices a response from its `usage` through a `PRICES` table, and an unknown SKU logs a warning and gives a cost of None.
  Each result becomes a `vendor_page` Source through `contracts.page_source`. Its text is the first of the Extract full content, the Extract excerpts and the Search excerpts that has plain text once the markdown is stripped, and a page with none is skipped with a note. Parallel does not say when it cuts a page, so a full content of 12,000 characters gets a "may be truncated" note. `source_date` is Parallel's `publish_date` with `date_method = record_field`, and it is null on some pages.
  `extract.mentions` reads each page. It splits the text into chunks of at most 6,000 characters, at paragraph breaks, then at line breaks, then with a hard cut, and sends one `extract` task per chunk. A page under 6,000 characters takes one call and a 12,000-character page two or three, so a search of about 10 pages makes up to about 30 Haiku calls in a row, and nothing caps the number. On GS-02, 14 calls over 10 pages took 190 s. The task returns every person the chunk names with each institution or place the text connects them to, Belgian or not. A chunk whose call raises `TagError`, `LLMCallError`, a schema error or `FixtureMissing` gives a `considered` row and a warning, and the next chunk goes on.
  Checks come before any claim:
  - `extract.locate` must find the mention's quote in its chunk, and the cleaned name must stand in that quote (`contracts.clean_name` strips titles and the credentials PhD, Ph.D, MBA and MD in any case, and a one-word name is dropped);
  - a relation's quote must lie in the same chunk within 1,500 characters of the mention quote's start, so each speaker on a list keeps their own line;
  - a relation's quote must name its org, as the model spelled it or as the alias file spells its id;
  - a relation that would make the same claim as an earlier one is dropped.
  Anything that fails goes into `considered` with its reason.
  `extract.drafts` then makes one `role` claim per mention (the role, else the page title, else the URL's host) and one claim per relation, quoting its own passage. An institution relation gives an `affiliation` claim at `orgs.org_id(org)`, and `born_in` and `lives_in` give a `location` claim with no coordinates. The Dates rule above sets each claim's date.
  Every person a page names is a hit, not only people it ties to Belgium. Hits run in page order, then mention order, and `matched_on` holds the page rank, title and URL. The same person twice on a page is one hit with both sets of claims. A rerun over the same URL finds the same person when the name has the same name key. It adds a source only when the page text changed, and a claim only when the extract answer gives a new value or quote offset. The same name on two pages is two records on one card. Every page, mention and drop goes into `considered`.
  Without a Parallel key the lane logs a warning, notes it and returns no hits. A replay run with no recorded Parallel answer fails the step with `CacheMiss`, as a replay miss fails the OpenAlex lane. A quiet note would let a replayed gold run pass with no web results, so a gold run that should include the web lane runs with `FN_HTTP` live. A Parallel 402 or 422 fails the step with the body's message.
- **LinkedIn lane.** One POST to the Apify actor `harvestapi~linkedin-profile-search` (`run-sync-get-dataset-items`) per search. The actor charges $0.10 a search page of 25 and $0.004 a full profile, about $0.20 a run, and reports no cost. FN calls LinkedIn through Apify and never logs in to it. Chips with neither a topic nor an institution give one note and no call.
  1. Input: `actor_input(chips, area)` is pure, with `area` from `geo.area`, the lookup the OpenAlex lane shares. `geo.area` returns None for no place, for a place of kind abroad or anywhere_us (it does not fetch the cities dump then) and for a place that names no city. `searchQuery` is the topic chips, else the institution chips, joined by " OR ", each multi-word chip in double quotes. It keeps whole chips only while the query stays within the actor's 300 characters, and a note names the chips left out. `schools` is `SCHOOLS`, nine Belgian schools, because every Belgian organization counts the same. `locations` comes from `LOCATIONS`, which maps a GeoNames city to LinkedIn's location names ("New York City" to "New York City Metropolitan Area" and "New Jersey"). A city not in the table sends its own name, a place geo.py cannot locate or one abroad sends the place text, and no place or `anywhere_us` sends "United States". The rest is `profileScraperMode: "Full"`, `takePages: 1` and `maxItems: 25`. A live run has confirmed only the two New York names.
  2. Spending: the lane calls with `cache="prefer"` when `FN_LINKEDIN=1` (`Settings.linkedin_live`) is set and `cache="only"` when it is not, so it spends Apify credit only on purpose. A run that returned profiles is cached, so FN does not pay for the same input twice; a run that returned none is not cached, so the next live call with that input pays again. Off with no recorded run for the input, the lane notes that it is off and what a live run costs, and returns. With `FN_LINKEDIN=1`, `FN_HTTP=replay` and no recorded run, the note says that the replay has no recorded run; without `FN_LINKEDIN=1`, that case gets the off note. A live call without an Apify token gives a note. The call sends `timeout=240` and `maxTotalChargeUsd=0.25` as query parameters with `timeout_s=290`, inside the sync call's 300 s limit. `keep` refuses an answer that is not a list holding at least one profile with a `linkedinUrl`, so an empty or failed run never fills the cache. The cost is an estimate, and the log line says so. An Apify refusal (the Free plan's run cap, credit gone, a 408) fails the step with the body's message. fn-gold refuses `FN_LINKEDIN=1` unless it runs exactly one case.
  3. Profiles: each becomes a `vendor_record` Source through `record_source(kind="vendor_record")` at its canonical URL (https, `www.linkedin.com`, no trailing slash), with one `path: value` line per field used. Those are the name, headline and location, and each education and experience entry's fields. `source_date` is the day of `_meta.scrapedAt`. A profile without `linkedinUrl`, or whose cleaned name has fewer than two words, is skipped with a `considered` row and stores nothing. The person comes from `Identifier("profile_url", url)`, named through `contracts.clean_name`.
  4. Claims: each education entry gives a `studied_at` affiliation claim at `orgs.org_id(schoolName)`, and each job gives `works_at` when its end is "Present", else `worked_at`, at `orgs.org_id(companyName)`. A company with no alias keeps `org_id` empty. A claim quotes its entry's lines and takes `valid_from` and `valid_to` from the entry's start and end years, and a current job runs to the scrape year. `claim_date` is the end year, else the start year, with `record_field`. An entry without a year has no `claim_date` and counts as one undated unit.
  Hits are the profiles that are not skipped, in the actor's order, with the education and job claims as `claim_ids`. One URL listed twice is one person and one hit. `considered` has a row per profile, "read N of totalElements profiles", and a note for each school spelling that maps to no org id, so the owner can add it to the alias file. One live run on GS-02 read 25 of 43 matching profiles in 178 s for $0.20.

## Outbound calls

net.py owns every outbound HTTP call, GET and POST. It sends `User-Agent: FN/0.1 (https://github.com/arendcolle/FN) httpx/<version>`, as Wikimedia's policy asks (Wikidata refuses the default one with a 403), and sets timeouts (30 s to read and 10 s to connect, and a call's `timeout_s` replaces the read timeout) and a 5 MB response cap, accepts http and https only, records each call through `ctx` as a StepCall with the redacted URL, and stores the response body under `var/cache/<sha>.json`, written to a temporary file and renamed into place. A POST's record also holds its compact JSON body, redacted, so the debug page shows which queries or actor input a call sent. A non-2xx error message adds the first 300 characters of the response body, redacted. The GeoNames cities15000 zip is 3.36 MB (2026-10), under the 5 MB cap; geo.py fails with that cap's error if the dump outgrows it. `FN_HTTP=replay` serves calls from that cache and raises on a miss, which makes a gold run repeatable. A future page reader adds address checks against loopback and private ranges here, on every redirect hop.

- **Keys by host.** A table maps `api.openalex.org` to `Authorization: Bearer` with the OpenAlex key, `api.parallel.ai` to `x-api-key` with the Parallel key and `api.apify.com` to `Authorization: Bearer` with the Apify token. net.py adds a header only on https to that exact host. A live call to the Parallel or Apify host without its key raises `MissingKey`, a subclass of `HttpError`, before anything is sent, and the lane turns it into a note. OpenAlex works without a key, as before. A cached answer needs no key.
- **Cache key.** A GET keeps `sha256(url)`, so the caches on disk still hit. A POST uses `sha256("POST " + url + "\n" + the JSON body, compact, with sorted keys)`. The URL includes its query parameters, so a change to Apify's `timeout` makes a new entry.
- **Cache modes.** `CacheMode` is `refresh` (call out and write the cache, as a GET does), `prefer` (serve the cache when it holds the key, else call out) or `only` (serve the cache or raise). A miss that may not call out raises `CacheMiss`, a subclass of `HttpError`, with the text "replay: no cached response for ...". That covers replay mode in any cache mode and `only` in live mode.
- **Keeping an answer.** `keep(body)` lets the caller refuse to cache a 2xx answer, such as an empty Apify list. The call is still recorded and returned. A `keep` or `cost` function that raises leaves the call recorded with the error and no cache file.
- **Cost.** `cost(body)` returns dollars or None for a live 2xx answer, because the lane knows its vendor's prices. net.py reads OpenAlex's own `meta.cost_usd`. A call served from the cache or in replay mode records a cost of 0.0, and its request starts with `cache` or `replay`.
- **Retries.** A GET retries once on 429 or 503 with Retry-After up to 30 s. A POST retries only on 429, which the server sends before it starts any work, because a 503 after an Apify run started would otherwise pay for a second run.

## LLM access

`StructuredLLM.structured(task, data, schema) -> LLMResult[T]` has two implementations.

- **`ClaudeCli`** runs `claude -p --model haiku --output-format json --json-schema <schema> --tools "" --setting-sources "" --strict-mcp-config --no-session-persistence --system-prompt <text of prompts/task.md>` with the user turn on stdin, and reads `structured_output` from the result. It runs with a minimal environment (PATH, HOME, USER, LANG, TMPDIR), in its own process group, with a timeout that kills the group (60 s, or the task's own in `TIMEOUTS`; `extract` gets 120 s). It checks `is_error` before parsing and raises `LLMCallError` carrying the return code, stderr and duration. It uses the owner's Claude subscription. A test call took 3 s and wrote 1,486 cache tokens.
- **`FixtureLLM`** keys fixtures by task and the sha of (rendered prompt, schema, model). In `record` mode it calls ClaudeCli and writes the fixture; in `replay` mode a missing fixture raises with its key and the first 200 characters of the prompt. It never returns a default. In `prefer` mode it serves a fixture when one exists, else calls ClaudeCli, and never writes a fixture.

`FN_LLM` is `live`, `record`, `replay` or `prefer`; tests set `replay` and ClaudeCli refuses to start when `FN_ENV=test`. Run fn-gold with `FN_LLM=prefer`, so the 28 tracked parse fixtures give the same chips on every run while the extract calls run live on the subscription. Nothing in fn-gold sets the mode, and the report header records it. `.gitignore` excludes `tests/fixtures/llm/extract-*.json`, so a record run cannot commit real page text. `llm.user_turn` raises `TagError`, a `ValueError`, for a data value that holds its own closing tag.

## Pages

| Route | What it shows |
| --- | --- |
| `GET /` | the question form and past searches |
| `POST /searches` | creates and queues a search, redirects to it |
| `GET /searches/{id}` | the editable chips, then cards. Each card has its score parts, the claims at Belgian organizations (institution, region, name language, years, whether it scored, quote, source, date), every record's claims with quote, source link, date and method, and any match flag. A person with none shows "No Belgian organization found in" and the sources read; when an institution's facts are not stored, the card names those ids instead |
| `POST /searches/{id}/rerun` | queues a new search with the edited chips and `rerun_of` |
| `GET /searches/{id}/map` | a marker per person with a location claim; popups set with text only |
| `GET /api/searches/{id}/geo` | GeoJSON from the newest location claim per person |
| `GET /debug/searches/{id}` | steps with status, duration, cost and call count; log lines; tracebacks; links to payloads |
| `GET /debug/steps/{id}/input.json`, `/output.json` | the full payloads |
| `GET /debug/steps/{id}/calls` | every HTTP and LLM call of a step |
| `GET /debug/searches/{id}/trace?name=` | one person through every step: considered, kept, dropped and why |
| `GET /debug/errors` | stored request errors with tracebacks |
| `GET /sources/{id}` | a source's text with the quoted span marked |

The app runs in `mode = local` only, and fn-serve refuses any host other than 127.0.0.1 or ::1. TrustedHostMiddleware allows only 127.0.0.1, localhost and [::1] and sits inside the guard, so its 400 also carries the security headers. A non-GET request is refused unless its Origin is the app's own or absent, or is `null` with `Sec-Fetch-Site: same-origin` (a browser sends `null` from the app's own forms because of `Referrer-Policy: no-referrer`), and it is refused whenever `Sec-Fetch-Site` is `cross-site` or `same-site`. Every response sends `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; connect-src 'self' https://tiles.openfreemap.org; worker-src blob:; frame-ancestors 'none'` and `Referrer-Policy: no-referrer`. MapLibre is vendored into `web/static` with its sha256 checked by a test.

Form posts are parsed with `urllib.parse.parse_qs`, because FastAPI's `Form()` needs python-multipart, which is not an approved dependency. HTML comes from `web/html.py`. Every value is escaped unless it is a `Safe` built inside html.py, and links accept http, https and relative URLs only. A rerun keeps the `ref` of a chip and the `kind` of the place only when the posted text equals the text of the search being rerun; an edited text gets none, so geo and lane code must treat a missing `ref` or `kind` as unresolved. A test renders every page, and the 400 pages that echo input, with `<script>` and `javascript:` in every text field. The style is the browser default, `font: 12px system-ui`, and grey 1 px borders on fieldsets and tables.

## Logging

stdlib logging writes to `var/log/fn.log` with rotation. A contextvar filter adds `search_id` and `step` to every record, a redacting filter runs on the root logger's handlers (the file and stderr), and the httpx logger sits at WARNING. Records emitted inside a step are also stored in `step_runs.log`. `var/` and `var/log` are created with mode 0700 by `setup_logging`, before the database is opened.

## Gold runner

`fn-gold [CASES]` runs the cases from `data/gold/gold-set.json` (all 28 by default) with the current settings, stores each run as a normal search, and writes `var/gold/<timestamp>/report.md` and `top5.csv`. A pick matches the candidate that holds its pinned person, the stored person for the OpenAlex id `data/gold/reach.json` gives it; without a pin, or when the store does not hold the pinned person, it matches by group key. For each pick the report prints found, event page or missed, section and rank (found means top 10 of its section), the lanes behind the pick, each with its rank in that lane, the gold tie next to the person's Belgian claims and `belgian_years` count, and for a miss the step and reason from the trace. A pick with no candidate gets the Belgian claims of the stored records with its group key, or "no stored record". It gives no verdict on the tie. `top5.csv` holds the top five cards per case with name, reason quote and Belgian claims, plus an empty column for a good-pick mark. The report header holds `code_sha`, `dirty`, the LLM mode and the HTTP mode.

- **Event page.** A pick that would be found gets the label `event page` when it has at least one reason source and every reason source is a `vendor_page` or `page` source at the case's own event page (`GoldCase.source_url`). Two URLs are the same page when their hosts match without a leading `www.` and their decoded paths match without a trailing slash. The query and fragment are ignored. A page elsewhere on the same site is other evidence. So is a LinkedIn profile, whether a `vendor_record` or a web-lane `vendor_page` at its own URL, although 13 cases have a `linkedin.com/posts` source. gold.py compares source kinds and URLs and knows no lane's URL format. The dev success measure counts `event page` as not found, and the summary table has an Event page column.
- **Cost.** `report.md` gives each case two costs. Vendor calls are the sum of the search's http call costs. LLM is the sum of its LLM call costs, which are the Haiku costs the CLI reports; the subscription does not bill them. A parse answer served from a fixture counts the cost recorded with the fixture, although no call ran, while a cached vendor call counts 0. A call with no cost counts as 0. The lanes behind each pick are in `report.md` too, and the stdout of fn-gold prints neither the lanes nor a cost.
- **Unreachable picks.** reach.json was recorded for seeds and OpenAlex only. A pick it calls unreachable that no lane found keeps the trace's lost step and reason, and reach.json's evidence follows them. Its verdict stays `no lane in slice`.
- **The FN_LINKEDIN guard.** fn-gold refuses `FN_LINKEDIN=1` unless it runs exactly one case. It exits with 2 right after reading the settings, before the Store or the Worker exists, so one command cannot start 28 paid runs. Without `FN_LINKEDIN=1` the LinkedIn lane serves a recorded run for the same input at $0.

## Responsibility table

| Responsibility | Owner |
| --- | --- |
| Shape of every value that crosses a module boundary, and normalize() | `contracts.py` |
| Every SQL statement and the stored invariants | `store.py` |
| Person identity at write time | `store.resolve_person` |
| Schema changes | `migrations/` run by `db.migrate()` |
| Outbound GET and POST, the key header per host, missing keys, the cache key, cache modes, retries, error text, timeouts, call recording | `net.py` |
| Prices for vendors that report no cost, passed to net.py as a cost function; net.py reads OpenAlex's own `meta.cost_usd` | the lane that calls the vendor |
| Whether an answer is worth caching, passed to net.py as `keep` | the lane that calls the vendor |
| When the LinkedIn lane may spend | `Settings.linkedin_live`, read by `lanes/linkedin.py` |
| Calling Claude, and fixture or live per LLM call, by `FN_LLM` | `llm.py` |
| Recording steps, calls, logs and tracebacks; redaction | `steps.py` |
| Search lifecycle, the worker thread and the startup sweep | `worker.py` |
| Order of steps in a search | `search.py` |
| Question to chips, and the span check | `parse.py` |
| The lane contract and registry | `lanes/__init__.py` |
| FTS query and seed search | `lanes/seeds.py` |
| Which sources the seed lane searches | `lanes/seeds.py`, through `store.match_claims(exclude=)` |
| OpenAlex calls and mapping | `lanes/openalex.py` |
| Parallel requests, and result pages as `vendor_page` Sources | `lanes/web.py` |
| Actor input from chips, and profiles to Sources, people and claims | `lanes/linkedin.py` |
| Vendor markdown to plain page text | `contracts.page_source` |
| Page text to named people, located quotes, mention identity and claim drafts | `extract.py` with `prompts/extract.md` |
| Offsets of an LLM quote in a page | `extract.locate` (seedload keeps its own offsets for seed rows) |
| Titles and credentials off a person's name | `contracts.clean_name` |
| Loading seed files | `seedload.py` |
| Spelling to institution id, for schools and employers too | `orgs.py` with `data/org_aliases.csv` |
| Institution facts, from ROR, Wikidata or OpenAlex | `orgs.save`, called by fn-orgs (`orgjob.py`) and the OpenAlex lane |
| Which claims are at a Belgian organization | `orgs.belgian_claims`, called by rank, web and gold |
| One entry per name (group key) in a result, name-only flags | `resolve.py` |
| Turning claims into ranked lists, fusing the lanes' lists, sections, ordering entries and any cut of the fused list (none yet) | `rank.py` |
| Which of the people a lane finds it keeps (the seed top 100, the OpenAlex scope and first 2,000 authors, everyone for web and LinkedIn) | each lane, under Lanes |
| Turning a claim into year units | `rank.units`, called by rank, web and gold |
| Place chip to coordinates, radius and city, for every lane that uses a place (`geo.area`) | `geo.py` |
| A city to LinkedIn's location names | `lanes/linkedin.py` |
| HTTP, escaping, security headers, error pages | `web/` |
| Gold scoring and reports, the event-page label, lanes per pick, cost per search, refusing `FN_LINKEDIN=1` for more than one case | `gold.py` |

## Decisions from the reviews

| Decision | Raised by |
| --- | --- |
| One identity function and a `person_identifiers` table with UNIQUE(scheme, value) | principal, contracts, product, maintainer |
| `list_status` on Person, section on Candidate; seed people show as New with their list | principal, contracts |
| Lanes write as they go; later steps pass ids; payloads in their own table, served by link | principal, contracts, debuggability, security |
| One worker thread, a guarded run, a startup sweep, one connection per thread | principal, debuggability, maintainer |
| `considered` lists, a person trace page, step calls and a gold report that names where a miss was lost | principal, debuggability, product |
| Response cache and replay mode; Retry-After capped at 30 s | principal, debuggability |
| Fixtures keyed by prompt hash, record and replay, no default answer | all six |
| Quoted FTS tokens built in a pure function | principal, security, debuggability, product |
| Affiliation claims with relation and org id; ties computed at read time with `checked` (the computed tie label was removed in 3.0, see the top section) | principal, contracts, product, maintainer |
| Partial dates with precision, valid_from and valid_to, one DateMethod list | principal, contracts |
| Quote offsets and record text as `field: value` lines | contracts, product |
| Chip with origin and ref; Place with kind | contracts, maintainer |
| Location is a claim; the map reads location claims only | principal, contracts, product |
| Prompt on stdin, data in tagged blocks, minimal subprocess env, process-group kill | security, debuggability |
| SecretStr and redaction by value everywhere | security |
| Host check, Origin check, CSP, vendored MapLibre, http and https links only | security |
| var/ gitignored with 0700, secure_delete | security |
| net.py as the single owner of outbound HTTP | security |
| A Lane protocol and an "adding a lane" checklist | maintainer |
| Run all 28 gold cases, split dev and held-out, report network and new recall apart, tie agreement (replaced in 3.0 by the gold tie next to the evidence), top-5 CSV | product |
| Code sha, dirty flag, settings and LLM mode stored on every search | debuggability |

Where reviewers disagreed:

- **Jinja2 or html.py.** The principal engineer and the maintainer prefer Jinja2; the security reviewer kept the builders. html.py stays, because Jinja2 is a new dependency the owner has not approved. Its API is documented in the module, and the render test covers every page.
- **The map.** Two reviewers would cut it. It stays because the owner asked for it, and it reads only location claims, so it cannot show a place no source supports.
- **CHECK constraints.** The maintainer wanted them; the contracts reviewer showed that SQLite needs a table rebuild to change one. Vocabularies stay Pydantic Literals only.
- **Grouping seed rows by name.** The product reviewer suggested one person per name. That breaks "nothing merges automatically", so seed rows stay one person each. The plan reviewer then showed that Goemans would get three cards, so resolve.py groups same-name records into one card with a flag, without merging the rows.

## Not doing

- DBOS, Postgres and sqlite-vec in this slice. `run_step` and the idempotent writes keep DBOS a wrapper later.
- Pydantic AI, because it needs an API key; it plugs in behind `StructuredLLM`.
- Embeddings and the Qwen model.
- Jinja2 or any template engine, a JavaScript framework, a CSS framework or SSE.
- Step replay and the diff of two searches.
- Payload purging; the payload table is separate so it can be added.
- Shared mode, login and the admin list for debug pages.
- Weighting Flanders above Wallonia, or by language, or letting the question choose. The owner settled equal weight for all of Belgium in this slice.
- A tie badge or filter. They come with the list page, computed from claims when shown.
- Place-of-birth lookups, and org facts for companies. The web and LinkedIn lanes now store born-in and employer claims, but a born-in claim has no coordinates and an employer not in `data/org_aliases.csv` has no org id, so the map skips the born-in claim and the ranker skips an employer with no org id.
- Paging the results page. The MIT search renders 387 candidates in 5.9 MB of HTML in 0.36 s; at the 2,000-author cap that should be about 30 MB.
- FN's own page reader, and Parallel's Decisions, Task and FindAll. The web lane uses Search and Extract only.
- Calling Parallel or Haiku concurrently. A web search makes up to about 30 Haiku calls in a row, one to three a page, and nothing caps the number.
- Location claims from LinkedIn profiles, company filters on the Apify actor and other Apify actors. A second run filtered by past Belgian employers would reach people with a Belgian job and no Belgian degree, and waits for Apify budget.
- A cut in rank.py. No requirement asks for one yet.
- A spend limit across searches for Parallel. A gold run of 28 cases costs about $0.31 in Parallel calls, and no requirement asks for a limit yet.
- Dutch query rows and `source_policy` domain lists for Parallel Search. The web lane sends the query set it builds from the chips.
- Moving the OpenAlex lane's Belgian-affiliation filter (`in_scope`) into the ranker. The owner raised it as a maybe. It changes GS-10 ranks, so it gets its own change with a gold comparison.
- Catching other pages about the same event. The event-page label compares the page's URL only.
- Turning a vendor refusal (a 402, a 422, an Apify refusal) into a note. It fails the step and the search, as an OpenAlex error does.
