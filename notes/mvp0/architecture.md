# How the FN slice is built: architecture and contracts

2026-11-12 · version 4.0 (the network: staff decisions stored as events, merges as pointers, CSV import and export, the ranker cut, people shown while a search runs, and the staff pages; 3.2 made the OpenAlex lane keep every author it fetches, Belgian or not; 3.1 added the web and LinkedIn lanes to the seed and OpenAlex lanes; 3.0 dropped the tie label, so institutions are records and the ranker scores Belgian affiliation claims directly; 2.3 moved place ordering into the OpenAlex lane), after six independent architecture reviews (principal engineer, security, data and contracts, debuggability, product fit, new maintainer), one plan review and one review per build task, plus four independent reviews of the web lanes plan (code fit, ownership, inputs and tests, vendor facts and safety) and six panels of three reviewers on the network design

**TL;DR.** One Python package, `fn`, runs a FastAPI app on 127.0.0.1 with one SQLite file. A search is a sequence of named steps. Each step takes one Pydantic model and returns one, and reaches the outside world only through a `StepContext`. The runner writes a step row before the step starts and records its input, output, every HTTP and LLM call, timing, cost and full traceback. Lanes store sources, people and claims as they find them, through one identity function, and pass ids onward instead of text. Four lanes find people: the seed lists, OpenAlex, a web search through Parallel and a LinkedIn profile search through Apify. The web and LinkedIn lanes keep every person they find, the seed lane keeps its top 100 and the OpenAlex lane keeps the first 2,000 authors it reads. The ranker owns the order of the fused list and one cut: it marks the people that only OpenAlex found and that have no Belgian evidence, and the pages leave them out. Institutions are records with facts from ROR, Wikidata or OpenAlex. The ranker fuses the lane rankings with one more ranked list, people ordered by the years their claims place them at a Belgian organization, and stores each term as a score part. Every lane also reports what it considered and why it dropped each person, so the gold runner can say for each known pick where it was lost. Staff build a network of people. A person joins through Add on a result card or through a CSV import, and every staff decision (Add, Skip, merge, keep apart, remove a fact, edit a contact detail, import, export) is one row in an append-only events table that Undo can reverse. A merge sets a pointer on one record and moves no claim, so claims stay evidence and a merge can be undone. The search publishes its people after each lane, so the results page fills while the search runs, and a lane that fails no longer stops the search. LLM calls go through the Claude CLI on the owner's subscription, with record, replay and prefer fixtures for tests and gold runs. Pages are plain HTML from an escape-by-default builder, styled by the design system's CSS, and the map is MapLibre with a pinned copy of the OpenFreeMap Positron style.

## Ties are evidence, not a label

The owner decided this on 2026-11-02, after the first build, and it is built as of version 3.0. The build plan is `notes/mvp0/ties-as-evidence-plan.md`.

FN does not store or compute a tie type. A person's ties are affiliation claims (studied at, worked at, member of, born in), each with its source, quote and date. The ranker takes those claims as inputs, alongside topic and place claims, and scores them directly, for example a dated claim at a Flemish institution. No intermediate tie value sits between the claims and the score. An institution's region is a fact about the organization, looked up from ROR, not a fact about the person. Any badge or filter shown to staff is computed from the same claims when it is shown.

In this slice the ranker scores one feature from those claims, `belgian_years`: the distinct years of claims at organizations with country code BE. Topic and place reach the score through the lanes' own rankings. Region, name language and born-in claims are not scored.

The owner settled three more points the same day:

- Every Belgian organization counts the same for ranking. Region and name language are shown on the debug card, not scored.
- Any claim that places a person at a Belgian organization counts, whatever its relation: studied, worked, member (KVAB foreign members too), fellow, consul, hosted.
- fn-gold prints the gold tie next to the evidence and gives no verdict.

How the build handles the facts it met:

- ROR gives VUB and ULB the same region, `BRU`. The language of the ROR display name tells them apart (VUB `nl`, ULB `fr`), and the debug card shows both facts. Neither changes the score, by the first decision above.
- KVAB has no ROR record, so its facts come from Wikidata (Q1301699, country through P17 and P297).
- A born-in claim names a place, not an institution. The web lane stores a born_in claim as a location claim with no coordinates, so the map skips it. A lives_in claim gets the coordinates `geo.coordinates` finds for the place text, or none, with a log line, when it finds no city. Place-of-birth lookups are not built.
- Companies have no ROR id. An employer claim without one keeps `org_id` empty, does not count and shows its spelling.

## Requirements for this slice

**Goal.** Let the owner run real questions end to end and see why each person was or was not found, so the full MVP is built on contracts that have already been tested. Version 4.0 adds the staff flows of the story map (`notes/design/story-map.md`): import, search, add, browse, reopen and export.

**User.** The owner alone, on a laptop, debugging the pipeline.

**Acceptance criteria.**

1. A question becomes chips (topics, institutions, place, ask type), and an edited chip set reruns the search as a new search linked to the first (F1).
2. Every search, its steps, calls and results are stored and can be reopened (F2).
3. The seed lane ranks the 5,035 people from the six seed lists, each result with the claim that matched (F3 shape).
4. The OpenAlex lane finds authors with dated affiliations, each stored as a claim at an institution record (F4, part).
5. Every shown claim has a source link, a quote found at stored offsets in the source text, and a date with its method, or undated when the source states none. Staff pages show the quote only for a prose source (page, seed_page, vendor_page) and otherwise cite the source and date. The debug search page shows every quote. There a person with no claim at a Belgian organization shows "No Belgian organization found in" with the sources that were read, and when an institution's facts are not stored it says "org facts not stored for" those ids instead (F5, F6).
6. One person never shows twice in one result list. Name-only matches are flagged and never merged by FN; staff decide (F9, part).
7. A map beside the list shows people with a location claim that has coordinates (F8, part).
8. The debug pages show every step with status, duration, cost, its calls, links to its full input and output JSON, its log lines and, on failure, the full traceback. Any unhandled request error shows its traceback and is stored. `/debug/stats` and `/debug/feedback` show where searches spend time and what staff did with results.
9. `uv run python -m unittest` passes. `uv run fn-gold` runs all 28 gold cases and prints per pick: found, event page or missed, section, rank, the gold tie next to the person's Belgian claims and `belgian_years` count, and the step where a miss was lost. Its `report.md` also holds the lanes behind each pick and each search's cost.
10. Add puts a person in the network in one click, Skip hides a person in this and later searches, "Same person" and "Add as new" settle a same-name match, and Undo reverses the latest decision about a person (flow 3).
11. A CSV file uploads, shows a preview and imports its people into the network, and the network and a search export to CSV that imports again (flows 1 and 7).
12. The Network page lists and filters the network beside a map. The Person page shows every fact with its source, marks facts that arrived since staff last looked, and removes a wrong fact (flows 4 and 5).
13. The results page shows 20 people at a time, fills while the search runs, and says when a lane failed (flow 2).

**Success measure.** On the dev cases GS-02 and GS-10, at least 3 of the 4 picks that `data/gold/reach.json` marks reachable from the question's own chips (all four are GS-10; no GS-02 pick is reachable, see reach.json's note) rank in the top 10 of their section, and every miss has a step and reason in the gold report. The held-out cases (GS-15, GS-16, GS-23, GS-24, GS-28) are reported, not targeted. Picks that no slice lane can reach are labelled "no lane in slice", not "missed".

**Out of scope.** FN's own page reader (the web lane takes page text from Parallel, and FN fetches no page itself), login and several users, depths beyond Quick, Excel import and a step that guesses columns, editing a fact by hand, DBOS, embeddings, replay of a step and payload purging. Add, Skip, merge, the list page, CSV import and export are built.

## Paradigms

- **Contracts are Pydantic models in one module.** Every value that crosses a module boundary is a frozen model or Literal from `fn/contracts.py`, including every step's input and output. Modules never pass dicts or rows to each other. `CONTRACTS_VERSION` is stored with every serialized payload.
- **Functional core, thin shell.** Parsing checks, the FTS query builder, year counting, duplicate flags and ranking are pure functions. Only `store.py` runs SQL, only `net.py` and `llm.py` make outside calls, and only `web/` handles HTTP requests.
- **Steps reach the world only through `StepContext`.** A step is `(ctx, InputModel) -> OutputModel`. `ctx` is frozen and holds `search_id`, `store`, `llm`, `http` (an `HttpClient` protocol that net.py implements), `now()`, `new_id()`, `log` and `settings`. Tests swap every one of them.
- **Write as you go, idempotently.** A lane step writes its sources, people and claims before it returns, using upserts on natural keys, so a rerun or a future DBOS retry writes nothing new. Later steps receive ids, quotes and values, never source text.
- **Errors stay visible.** A step row exists before the step runs. A failure stores the traceback on the step. A failing lane keeps its error row and the search goes on; any other failing step marks the search failed and stops it, and so does every lane failing. Nothing is retried silently, and every caught exception is recorded.
- **A staff decision is data.** Every Add, Skip, merge, keep-apart decision, removed fact, contact edit, import and export writes one row to the append-only `events` table. Undo writes a second row that names the first.
- **A merge is a pointer.** Merging sets `merged_into` on a record. No claim or identifier moves.
- **One module decides how a person reads.** `present.py` builds the view models that the card, the network row, the profile, the map popup and the export row share.
- **Plain SQL with numbered migrations.** No ORM. An applied migration is never edited; a change is a new `NNN_name.sql`.

## Module layout

```text
pyproject.toml              uv project; scripts fn-serve, fn-seed, fn-gold, fn-score, fn-orgs, fn-rerank, fn-enrich
src/fn/
  contracts.py              every model, Literal and normalize(); record_source(), page_source(), profile_url(), clean_name(); IMPORT_COLUMNS; CONTRACTS_VERSION
  config.py                 Settings (frozen): paths, mode, host, port, llm mode, keys as SecretStr, the FN_LINKEDIN switch
  db.py                     connect() per thread (WAL, foreign keys, busy_timeout, secure_delete); migrate()
  migrations/               001_init (the tables below), 002_orgs, 003_chip_refs, 004_score_parts, 005_claim_years, 006_network, 007_cut_reason, 008_org_places, 009_card_records, 010_candidate_group, 011_lookups
  store.py                  all SQL; resolve_person(); upserts; claims_of(); reads for pages, debug and stats
  net.py                    the one outbound HTTP client, GET and POST: timeouts, size cap, scheme check, keys per host, call recording, cache modes
  llm.py                    StructuredLLM protocol; ClaudeCli; FixtureLLM (record, replay and prefer); live mode records its answers in var/llm
  prompts/parse.md          system prompt for the parse task
  prompts/extract.md        system prompt for the extract task (the people one part of a page names)
  steps.py                  StepContext, run_step(), CallRecorder, redact(), log capture; fan_out() runs the calls of one step at the same time; as_of() is the date a search ranks as of
  worker.py                 one-thread executor, the search lifecycle, the startup sweep
  search.py                 the Quick workflow: which steps run in which order, with a publish step after each lane but the last; finish() holds the steps after the lanes; refinish() runs them again on a stored search (fn-rerank)
  parse.py                  question -> Chips, span checks
  extract.py                page text -> the people it names, quotes located in the text, claim drafts
  lanes/__init__.py         Lane protocol, LANES registry
  lanes/seeds.py            seed lane: fts_query() over the topic words that carry meaning and the FTS5 search; for a question that names only a place, the 20 nearest people based there
  lanes/openalex.py         OpenAlex lane: works -> authors -> affiliations, the matching works as topic claims, considered list; store_author() for enrich
  lanes/web.py              web lane: Parallel Search and Extract, pages as vendor_page sources, people through extract.py
  lanes/linkedin.py         LinkedIn lane: Apify profile search, profiles as vendor_record sources with dated claims
  orgs.py                   spelling -> org id from data/org_aliases.csv; ROR and Wikidata records -> facts; save(); belgian_claims()
  orgjob.py                 fn-orgs: fetches every id in the alias file and saves its facts, as a job with one step; --places fills org cities from stored records and locates stored place claims
  identity.py               who is one person: the name key, same_person(a, b) -> (level, reason), the vetoes, on_card() for the records a card reads
  resolve.py                hits mapped to canonical ids; one entry per person as identity.py links them; name-only match flags
  evidence.py               what the records on a card show for a question: topic words, institution, Belgian tie, places (a stated place, else a recent employer's city), sources
  rank.py                   the belgian_years list, reciprocal rank fusion with score parts, section assignment, groups and bands from evidence.py, the cuts and their reasons
  enrich.py                 fn-enrich: looks up seed people at OpenAlex and ORCID holders' employments, as a job; one row per lookup in the lookups table
  network.py                staff decisions (add, skip, remove, merge, not same, reject a fact, set a contact detail, undo, mark seen) and the event each writes
  present.py                view models: how a person, a claim, a card, the network and a profile read
  importer.py               CSV text to rows, row checks, the preview and the confirm of an import
  exporter.py               people to CSV text
  stats.py                  read models for /debug/stats and /debug/feedback
  seedload.py               data/seeds/*.jsonl -> persons, sources, claims (fn-seed)
  geo.py                    place text -> coordinates and radius, from a GeoNames cities15000 extract fetched through net.py and data/place_aliases.csv; locate() reads qualifiers and metro aliases, locate_city() serves the import, area() is the lookup the OpenAlex and LinkedIn lanes share, coordinates() serves the web lane's lives_in claims
  gold.py                   fn-gold: runs cases, matches picks, labels event-page finds, writes the report and a scoring CSV
  score.py                  fn-score: snapshot freezes the database, cache and LLM fixtures; run scores a snapshot's searches by rescore, rerank (search.finish) or replay into scorecard.json; compare gates two scorecards
  web/app.py                app factory, middleware (host, origin, CSP), the request log, error pages, request_errors, fn-serve
  web/staff.py              staff routes and pages
  web/debug.py              debug routes and pages, and the chip rerun
  web/parts.py              the HTML of each design-system part, one function per part
  web/requests.py           the app's store and worker, and the fields of a posted form
  web/html.py               escape-by-default builders and the page shell; Safe only inside this module
  web/static/               vendored maplibre-gl, pinned positron.json, map.js, results.js, tokens.css, fn.css, fonts/
data/org_aliases.csv        spelling -> org id (ror:<id> or wikidata:<Q>); 129 spellings, 70 ids
data/place_aliases.csv      metro, state and country aliases for geo.py
data/org_aliases_unmapped.txt  seed and LinkedIn spellings with no id yet
data/gold/gold-set.json     copy of the delegation gold set
scripts/gold/cut_gate.py    gate for the ranker cut over a stored database
tests/                      unittest; helpers.make_db(); fixtures/llm, fixtures/http
```

## Contracts

### Vocabularies

Each is a `Literal` defined once in `contracts.py`. SQL stores them as text without CHECK constraints, so a vocabulary grows by changing one line.

| Name | Values |
| --- | --- |
| `ListStatus` | candidate, in_list, skipped |
| `Section` | network, new |
| `ClaimKind` | topic, affiliation, role, location, availability, email, phone |
| `Relation` | studied_at, works_at, worked_at, affiliated_with, hosted_by, fellow_of, member_of, consul_for, born_in, lives_in |
| `DateMethod` | page_date, sitemap, wayback_first_seen, document_heading, record_field, read_date, sheet_date, staff_edit, stated_in_quote |
| `DatePrecision` | year, month, day |
| `SourceKind` | page, record, seed_page, import, vendor_record, vendor_page, staff |
| `IdentifierScheme` | seed, openalex, orcid, profile_url, mention, email, import |
| `StepStatus` | running, ok, error, skipped, interrupted |
| `SearchStatus` | queued, running, done, failed, interrupted |
| `SearchKind` | search, job (fn-orgs and the import steps store their runs as jobs) |
| `LaneName` | seeds, openalex, web, linkedin |
| ScorePart `feature` | a `LaneName`, or belgian_years |
| `ChipOrigin` | parsed, edited |
| `LLMMode` | live, record, replay, prefer (the values of `FN_LLM`) |
| `CacheMode` | refresh, prefer, only (what net.py does with its response cache for a call) |
| `GoldTie` | flemish, belgian, none, unverified (the gold set's own label, printed by fn-gold, never computed) |
| `PickVerdict` | found, event page, missed, no lane in slice |
| `EventKind` | add, skip, merge, not_same, reject_claim, edit_contact, remove, import, export, undo |
| `AddedVia` | search, import, profile (how a person joined, kept in the add event's detail) |
| `CutReason` | no_belgian_evidence |
| `CardState` | network, new, name_match, added, skipped |
| `ImportStatus` | preview, confirmed, discarded |
| `ImportOutcome` | new, update, name_match, skipped |

### Models

| Model | Fields | Flow |
| --- | --- | --- |
| `Span` | `start`, `end` | inside Chip |
| `Chip` | `text`, `span: Span \| None`, `origin: ChipOrigin`, `ref: str \| None` (for example `ror:...`) | parse to lanes; the form posts edited chips |
| `Place` | `text`, `span: Span \| None`, `origin`, `kind: metro \| anywhere_us \| abroad \| None` | inside Chips |
| `Chips` | `topics: list[Chip]`, `institutions: list[Chip]`, `place: Place \| None`, `ask: Literal[talk, mentor, host, join, other] \| None` | |
| `Search` | `id`, `kind`, `question`, `depth`, `chips`, `chips_origin`, `status`, `error`, `created_at`, `finished_at`, `rerun_of`, `code_sha`, `dirty`, `llm_mode`, `settings_json`, `boot_id`, `user_id: None` | store to web and gold |
| `Source` | `id` (sha1 of kind and URL; a record, import, staff, vendor_record or vendor_page source adds its content_hash, so a changed record, profile or page is a new source), `kind`, `url` (http or https; an `fn:` URL only for the import and staff kinds), `title`, `text` (normalized), `raw_json \| None`, `content_hash`, `normalize_version`, `source_date`, `date_method`, `fetched_at` | written by lanes and seedload |
| `OrgFacts` | `id` (`ror:<id>`, `wikidata:<Q>` or `openalex:<I…>`), `name`, `country_code`, `region` (ROR subdivision code), `name_lang` (language of the ROR display name), each `None` when the source has no value | orgs.py and the OpenAlex lane to `orgs.save` |
| `Org` | the OrgFacts fields, plus `source_id` and `fetched_at` | store to rank, web and gold |
| `Claim` | `id` (sha1 of person, kind, value, source, quote_start), `person_id`, `kind`, `relation \| None`, `org_id \| None` (an Org id), `value`, `quote`, `quote_start`, `quote_end`, `source_id`, `claim_date` (ISO partial), `date_precision`, `date_method`, `valid_from`, `valid_to`, `years` (the calendar years the source lists, when it lists them; OpenAlex affiliation years have gaps), `lat`, `lon` (location only), `first_seen_at` (when FN first stored the claim; empty on rows from before migration 006), `rejected_at` (when staff removed the fact) | written by lanes and seedload |
| `Person` | `id` (uuid), `display_name`, `name_key`, `list_status`, `merged_into: str \| None`, `merged_at`, `seen_at` (the last time staff looked at the person) | `store.resolve_person` creates it; `network.py` changes the last four fields and the status |
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
| `Candidate` | `search_id`, `person_id` (the entry's first person), `person_ids`, `section`, `rank`, `score` (the sum of its parts), `lane_ranks`, `reason_claim_ids`, `score_parts`, `hit_person_ids` (the canonical ids of the records a lane found; a card shows and scores only these), `cut_reason` | rank to store, present, web, gold |
| `StepRun` | `id`, `search_id`, `seq`, `step`, `status`, `started_at`, `ended_at`, `input_model`, `output_model`, `contracts_version`, `cost_usd`, `tokens_in`, `tokens_out`, `model`, `prompt_sha`, `error_type`, `error_message`, `traceback`, `log` | steps.py |
| `StepCall` | `step_run_id`, `seq`, `kind: http \| llm`, `request` (redacted; a POST holds its compact JSON body), `status`, `duration_ms`, `response_sha`, `response_path`, `tokens_in`, `tokens_out`, `cost_usd`, `error` | net.py and llm.py through the recorder |
| `RequestError` | `id`, `route`, `traceback` (redacted), `at` | store to web |
| `Event` | `id`, `at`, `kind: EventKind`, `person_id`, `other_person_id`, `search_id`, `rank`, `section`, `import_id`, `claim_id`, `undoes` (for an undo, the id of the event it reverses), `detail` (what undo needs: ids and prior values, never contact values), `user_id: None` | network.py to store |
| `QuoteView`, `ClaimView`, `OrgView`, `PersonView` | a quote with its citation; a claim as pages word it (`what`, `years`, optional quote, label, href, date, `is_new`); an organization with its years; a person as every page shows them (name, role, employer, place, coordinates, up to three organizations, evidence claim, status, day added, count of new facts, email, phone) | present.py to web/parts.py |
| `CardView`, `LastView`, `ResultsView` | a result card in its state with the same-name network person and its Undo; the latest decision that can still be undone, in words; the kept people by section and the cards shown | present.py to web |
| `NetworkFilter`, `NetworkView` | the Network page's filter (text, import, new facts only) and its people, total and count without a place | web to present.network_view, and back |
| `ContactView`, `FactGroup`, `RecordView`, `ProfileView` | everything the Person page shows | present.py to web |
| `ImportRecord`, `ImportRow`, `ImportPreview` | a stored file with its status and summary; one row's outcome (new, update, name_match, skipped), message and cells; the preview with counts and ignored columns | importer.py and store |
| `StepStat`, `SearchStat`, `SearchFeedback` | timings and costs per step and per search; kept, cut, added and skipped people per search | stats.py to web/debug.py |
| `LLMResult[T]` | `value: T`, `model`, `cost_usd`, `tokens_in`, `tokens_out`, `billing` | llm.py to the calling step |
| `GoldCase` | `id`, `question`, `source_url` (the gold set's `source`, the case's own event page; `None` when it has none), `picks` | data/gold to gold.py |
| `PickResult` | `case_id`, `name`, `verdict: PickVerdict`, `section`, `rank`, `gold_tie`, `belgian`, `lanes` (each lane behind the pick's candidate with its rank, such as `seeds #3; web #5`; empty without a candidate), `lost_step`, `lost_reason` | gold.py to the report |
| `CaseResult` | `case_id`, `group`, `question`, `chips`, `search_id`, `status`, `failed_lanes` (the lane steps that ended in error), `http_cost_usd` and `llm_cost_usd` (the search's vendor call costs and LLM call costs, each summed from its step calls by call kind; a call with no cost counts as 0), `picks`, `top` | gold.py to the report |

Step models are named `<Step>In` and `<Step>Out` and listed in contracts.py next to the step order: `ParseIn(question)` and `ParseOut(chips)`, `LaneIn` and `LaneOut` for every lane, `ResolveIn(outs: list[LaneOut])` and `ResolveOut(entries, flags)`, `RankIn(entries, chips)` and `RankOut(candidates)`, `SaveIn(candidates, flags)` and `SaveOut(count)`, and `PublishIn(lanes, chips)` and `PublishOut(count)` for the publish step. `SearchProgress(status, people, version)` is what the status route returns. The fn-orgs job has one step, `OrgsIn(ids)` and `OrgsOut(orgs)`, and an import job has one step, `ImportStepIn(import_id, merge_rows)` and `ImportStepOut(counts)`, whose output holds counts only so no contact value reaches a step payload. `CONTRACTS_VERSION` is 2 since the tie label went; the trace page shows a payload stored under version 1 as a note instead of parsing it. Version 3.1 added Literal values, models and fields with defaults and changed no existing field, so it stays 2. Version 4.0 did the same: its new values, models and fields have defaults, so it stays 2 and the trace page still reads every stored search.

### Rules

- **Identity.** `Person.id` is always a uuid. `store.resolve_person(identifiers, display_name)` is the only way to get one: it returns the person that already holds any of the identifiers, else creates one. `person_identifiers` has UNIQUE(scheme, value). A shared name alone never joins two people; resolve.py flags it and staff decide. A name on a web page gets `Identifier("mention", "<url>#<name key>")` from `extract.identifier`, so a rerun over the same URL finds the same person even when the page text changed. A LinkedIn profile gets `Identifier("profile_url", <canonical URL>)`.
- **Seed people are candidates.** Seed people start as `list_status = candidate` with a `seed:<row_key>` identifier and a `fellow_of` or `member_of` claim. Section `network` means that a hit record's person has `list_status = in_list`. Nobody is in the network until staff add or import them.
- **One card per name.** resolve.py groups hits that share a person id or a group key into one Entry. The group key is `name_key` without middle initials (`contracts.group_key`), so OpenAlex's "Nick M. Vandewiele" and the seed row "Nick Vandewiele" share a card; a first or last initial stays. The trace page matches names by the same key. The persons stay separate rows until staff merge them. The debug card lists every record and says "same name in N records, not merged"; a staff card shows the claims of the hit records only. `resolve.group` puts two persons on separate cards when a `not_same` row joins them or when they hold different ORCIDs. rank.py fuses lane ranks over the entry, so being found by two lanes lifts a person.
- **Quotes.** `normalize()` (NFC, NBSP to space, straight quotes, single spaces) lives in contracts.py with a version number. A claim is valid only when `source.text[quote_start:quote_end] == quote`. The ClaimDraft validator checks this where the claim is built, and `store.upsert_claim` checks it again on insert. A record Source's `text` holds one `field.path: value` line per field used, and the raw response sits in `raw_json`. An import Source's `text` holds one `column: value` line per filled cell, and a staff Source holds the one line staff typed; each of their claims quotes its own line. A vendor_page Source's `text` is the vendor's markdown as plain text. `contracts.page_source` does the conversion, and links keep their anchor text while emphasis marks, heading markers and backslash escapes go. `extract.locate` finds an LLM quote in that text, and the claim stores the text at those offsets, so the rule holds by construction.
- **Dates.** `claim_date` is the date the quote supports, as `YYYY`, `YYYY-MM` or `YYYY-MM-DD` with its precision. `source_date` is the date of the source. A BAEF row with only a year gets `claim_date = year`, `date_method = record_field`, precision year. A claim from a web page gets a date only when its quote states a year. `valid_from` and `valid_to` then hold the years stated, `claim_date` is the later one, the precision is year and `date_method` is `stated_in_quote`. Otherwise `claim_date` stays empty and the ranker counts one undated unit. A claim from an import row gets the day of the upload as `claim_date`, with precision day and `date_method = sheet_date`. A contact detail staff type gets the day typed and `staff_edit`. The page's own date stays on the Source and shows on its source page. FN never dates a claim by the day it read the page, because a page read in 2026 that says someone studied at KU Leuven says nothing about 2026. A LinkedIn entry takes its years from the entry, with `record_field`.
- **Institutions.** An institution is an `orgs` row. `orgs.org_id(text)` maps a spelling to its id through `data/org_aliases.csv`, a hand-kept list, because ROR's affiliation matcher picked an institution for only 34 of the 80 most common seed spellings, 2 of them wrong. A spelling not in the file leaves `org_id` empty. `orgs.save(store, facts, source, replace=)` is the only writer, and each row points at the Source its facts came from. fn-orgs fetches every id in the alias file from ROR or Wikidata and replaces stored rows. The OpenAlex lane saves the institutions in the author records it already reads and never replaces a stored row. An empty fact stays empty. The web and LinkedIn lanes map the organizations they read through `orgs.org_id` and save no facts, and so does the import's `organization` column. The facts come from fn-orgs, so a new id in the alias file counts as Belgian only after fn-orgs has fetched it.
- **Merges.** `persons.merged_into` holds the canonical record's id and `merged_at` the time of the merge. Depth is always one: merging a person that already has merged records points those at the new canonical record too. `store.resolve_person` still returns the record that holds the identifier, so a lane that finds a merged record adds its claims to that record. Readers see one person: `store.canonical_ids` maps a record to its canonical id, `store.claims_of(ids)` returns the claims of each id's whole person once with `person_id` set to the canonical id, and `resolve.group` maps every hit to its canonical id before it groups. Every `network.py` function accepts any record's id and works on the canonical one, because a stored search keeps the ids it was made with.
- **The network.** The network is the set of canonical records with `list_status = in_list`. `network.py` is the only module that changes `list_status`, a merge pointer, a `not_same` row, `seen_at`, a rejection or a contact claim, and the only writer of events. Each decision writes one event whose `detail` holds what Undo needs.
  - **Add** merges each later hit into the first hit's person unless they hold different values in one of `seed`, `openalex`, `orcid` or `profile_url` or a `not_same` row separates them, sets the person `in_list` and sets `seen_at` to now. A hit left apart stays a separate record, and the card says "1 possible match" with a link to the profile. Add on a person already in the network with nothing to merge writes nothing and returns the latest add event when it has one.
  - **Same person or new.** When a network person has the same group key as a card and no shared identifier or `not_same` row, the card shows "Same person" and "Add as new" in place of Add. "Same person" merges the hits into the network person. "Add as new" adds the hits and stores a `not_same` row.
  - **Skip** sets the hit persons to `skipped` across searches, and is refused for a person in the network. A later search leaves them out of the list and counts them as hidden. Add on a skipped person sets `in_list`.
  - **Remove** sets a network person back to `candidate`.
  - **Not same** stores a pair as different people, and first separates a record merged into the other's person.
  - **Undo** reverses an event as its detail recorded it. It is refused with a plain sentence when a later event names one of the same persons, and for an import, an export and an undo.
- **Rejected facts.** Removing a fact sets `claims.rejected_at`. The fact is the claim's person, kind and organization, else its folded value. `store.claims_of` and `store.match_claims` leave out the rejected claim and every other claim of that person with the same fact key, so a lane that finds the fact again does not bring it back. A staff claim of that value first seen after the rejection shows again.
- **New facts.** `store.upsert_claim(draft, at)` sets `first_seen_at` to `at` for a claim it inserts; lanes pass `ctx.now()`. An old row keeps it empty and counts as old. A claim of a merged record counts as first seen at the later of its own time and the record's `merged_at`. A fact is new when its person is in the network and `first_seen_at` is later than the person's `seen_at`. `network.add` and `network.mark_seen` are the only writers of `seen_at`, and opening the profile of a network person calls `mark_seen` after the page is built.
- **Import and staff sources.** An imported row is a source of kind `import` at `fn:import/<import id>#row-<n>`, titled `<file name>, row <n>`. A fact staff type is a source of kind `staff` at `fn:staff/<event id>`. `present.label_of` words them as "Import contacts.csv, row 3" and "Entered in FN", and the source page shows that label with no outside link.
- **Contact details.** `email` and `phone` claims quote their source like any claim and never make a person a search hit. `network.set_contact` writes a typed value as a staff claim and rejects the claim it replaces. A typed email also becomes the person's `email` identifier, and is refused when another person holds the address.
- **Imports.** `contracts.IMPORT_COLUMNS` lists the columns: name (required), email, phone, organization, role, city, state, country, linkedin_url and orcid. The importer reads UTF-8 with or without a byte-order mark, else Windows-1252, takes the comma or semicolon the header row has more of, matches headers by name in any case, ignores other columns and names them in the preview. It refuses a file over 5 MB, an empty one, UTF-16, an `.xlsx`, a tab-separated file and one without a name column. A row finds its person through `store.resolve_person` with its LinkedIn URL (in `contracts.profile_url` form), its ORCID and its lower-cased email; every written row also gets the identifier `import:<import id>:<row>`, so a row with none of the three still has an identifier. A name is never an identifier. A row whose name has the group key of a network person and no shared identifier is a name match: the preview shows an unticked box "Row n. Same as <name>?", a ticked box merges on confirm, and a header box ticks them all. A row with no name, a row identical to an earlier one and a row whose identifiers belong to two different people are skipped with a reason. Preview and confirm both compute the rows from the stored file text. Confirm writes every row in one transaction, and a second confirm changes nothing. Each of the two runs as a job of kind `job` with one step (`import_preview`, `import_confirm`). The `organization` cell becomes a `works_at` claim at `orgs.org_id`, the `role`, `email` and `phone` cells claims of their kind, and the city, state and country cells one `lives_in` location claim, with coordinates from `geo.locate_city` when it finds the city. A value the person already holds is not written again.
- **Export.** `exporter.COLUMNS` is the import columns, then `belgian_organizations`, `added` and `profile`. The file starts with a byte-order mark, ends rows with CRLF and puts an apostrophe before a cell that starts with `=`, `+`, `-` or `@`; the importer drops that apostrophe, so an exported file imports again. Each export writes an `export` event.
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
| `persons` | id; list_status, merged_into, merged_at, seen_at |
| `person_identifiers` | UNIQUE(scheme, value); person_id |
| `sources` | id; UNIQUE(kind, url, content_hash) |
| `claims` | rowid INTEGER PRIMARY KEY, id TEXT UNIQUE; UNIQUE(person_id, kind, value, source_id, quote_start); first_seen_at, rejected_at |
| `claims_fts` | FTS5, content='claims', tokenize='porter unicode61 remove_diacritics 2', over value and quote; insert, update and delete triggers |
| `orgs` | id (`ror:`, `wikidata:` or `openalex:`); name, country_code, region, name_lang; source_id REFERENCES sources, fetched_at |
| `candidates` | PRIMARY KEY(search_id, person_id); `score_parts_json` (empty for rows stored before migration 004), `hit_person_ids_json`, `cut_reason` (no CHECK) |
| `match_flags` | (search_id, person_id, other_person_id) |
| `request_errors` | id; route, traceback, at |
| `not_same` | PRIMARY KEY(person_id, other_person_id); at |
| `events` | id; at, kind, person_id, other_person_id, search_id, rank, section, import_id, claim_id, undoes, detail_json, user_id; append-only |
| `imports` | id; filename, uploaded_at, status, the file's text, summary_json, confirmed_at |

`migrate()` runs each file in a transaction with foreign keys off, then runs `PRAGMA foreign_key_check` and turns them back on. A migration that rebuilds `claims` also rebuilds `claims_fts`. Migration 002 adds `orgs` and `searches.kind` and rewrites every stored claim from the old internal org ids (`ku-leuven`, `kvab` and the rest) to the new ids, setting an old id with no new one to empty. Migration 003 rewrites stored chip refs from `ror:https://ror.org/<id>` to `ror:<id>`. Migration 004 drops `candidates.tie_json` and adds `score_parts_json`. Migration 005 adds `claims.years_json`. Migration 006 adds `persons.seen_at` and `merged_at`, `claims.first_seen_at` and `rejected_at`, `candidates.hit_person_ids_json` and `cut_reason`, and the tables `not_same`, `events` and `imports`; it fills `hit_person_ids_json` from the hit ids in each stored resolve step's output. Migration 007 sets `cut_reason` on stored candidates by the cut rule below.

## The Quick workflow

```text
worker.submit(search_id)                         one ThreadPoolExecutor(max_workers=1), made in the app lifespan
  search.run(ctx)                                guarded: any exception outside a lane sets the search failed with its traceback
    run_step("parse", ParseIn)       -> ParseOut   status skipped when the form sent chips
    run_step("lane:seeds", LaneIn)   -> LaneOut    FTS5 over claims; aggregate bm25 per person
    run_step("publish", PublishIn)   -> PublishOut resolve, rank and save over the lanes so far
    run_step("lane:openalex", LaneIn)-> LaneOut    works search, author records, institutions; writes as it goes
    run_step("publish", PublishIn)   -> PublishOut
    run_step("lane:web", LaneIn)     -> LaneOut    Parallel Search and Extract; pages as vendor_page sources; people read per chunk by Haiku
    run_step("publish", PublishIn)   -> PublishOut
    run_step("lane:linkedin", LaneIn)-> LaneOut    Apify profile search; profiles as vendor_record sources; off unless FN_LINKEDIN=1
    run_step("resolve", ResolveIn)   -> ResolveOut one entry per name (group key); name-only flags
    run_step("rank", RankIn)         -> RankOut    RRF over the lane lists and belgian_years; the cut; equal scores ordered by person id
    run_step("save", SaveIn)         -> SaveOut    candidates and flags in one transaction, then status done
```

A lane whose vendor key is missing returns a note and no hits, and the search goes on. A non-2xx answer from a vendor, such as a 402 or a 422, fails the lane's step, as an OpenAlex error does, and so does a call that times out. A lane whose step fails keeps its error row and counts as an empty output, and the search goes on with the other lanes. The search fails only when all four lanes fail. The results page then says "Some sources could not be read, so this list may be incomplete." These give a note and no failure: an Extract error for one URL, an empty Parallel Search result, and the LinkedIn lane when it is off or has no recorded run for its input. A replay miss in the web or OpenAlex lane fails that lane's step.

A publish step resolves, ranks and saves the outputs of the lanes so far, with the same functions as the final steps, and replaces the search's candidates. People therefore appear after the first lane and move as later lanes report. The last lane has no publish after it, because the final resolve, rank and save follow.

At startup the worker marks every queued or running search from an earlier boot as `interrupted`, and its running steps too. A search that stopped shows the people it had published, under "This search stopped before it finished."

While a search runs, `results.js` asks `GET /searches/{id}/status` every 2 s. The answer holds the status, the number of kept people saved and a version, the count of publish and save steps that ended ok. When the version changes, the script fetches `GET /searches/{id}/cards`, swaps the list in place, keeps the scroll position and redraws the map. It waits while the pointer or the focus is on a card. Without JavaScript the page reloads every 2 s through a meta refresh inside `noscript`.

fn-orgs runs outside the Quick workflow. It stores one `searches` row of kind `job` with one `orgs` step, so its calls, log and traceback show on the same debug pages. The searches lists show kind `search` only. An import stores each of its two steps as a job in the same way.

### Ranking

Since the result quality work ([notes/quality/design.md](../quality/design.md)) the new section is ordered in bands before the score. `evidence.of` says, per card, which topic words its records hold, its Belgian tie and its place. Group 0 holds people with a topic match and a tie, group 1 everyone else. The bands are group 0 not outside the place, group 0 outside it, group 1 not outside, group 1 outside, and last the people placed only outside the question's country. Inside a band, people with more topic words come first, then the fused score below. Four cuts apply to people only OpenAlex found: `no_belgian_evidence`, `weak_openalex`, `no_claim` and `outside_country`; the last three spare a match on an institution chip. The median list went from 518 to 223 people.

rank.py fuses ranked lists by reciprocal rank fusion: an entry gets `1 / (60 + rank)` from each list it is on, and its score is the sum. No weight is set by hand. Each term is stored as a ScorePart, so the card can show where every point came from.

- **Lane lists.** Each lane's best rank for the entry. The web and LinkedIn lanes keep every person they find, so the web lane adds many people to section `new` (69 from 10 pages on GS-02). The seed lane keeps its top 300 and the OpenAlex lane the first 2,000 authors it reads, Belgian or not (see Lanes). An author with no Belgian claim has no belgian_years part, so the fused list places them below Belgian authors with a similar lane rank. In the 2026-11-06 gold run no case had a card without a Belgian claim in its top 10. rank.py owns the order of the fused list and its one cut (see The cut).
- **The cut.** `rank.cut_reason` sets `no_belgian_evidence` on a candidate in section `new` whose only lane is OpenAlex and that has no `belgian_years` part. Everyone else is kept, and a candidate in section `network` is never cut. On the 24 stored searches with results this takes the median from 1,098 to 518 people and cuts none of the 12 gold picks that reach the ranker (`scripts/gold/cut_gate.py`). A cut candidate stays in the `candidates` table with its reason. Kept and cut candidates are numbered apart within a section, each from 1 (searches stored before migration 007 keep their old rank numbers), so rank numbers on a staff page count kept people only. Staff pages read kept candidates only. The debug search page lists the cut ones too, with "cut:" and the reason, and the trace page shows the rank step as dropped with that reason. A skipped person is not a cut: `store.list_candidates` can leave out a candidate whose hit persons are all skipped, so Undo brings the card back without a new rank run.
- **belgian_years.** rank.py reads the claims of the entry's hit persons through `store.claims_of`, which includes the records merged into them and leaves out rejected facts, and keeps those at an org with `country_code = BE`. Each claim gives units: the years the source lists (`Claim.years`) when it lists them, else every year from `valid_from` to `valid_to` when both are set and in order, else the years of `valid_from`, `valid_to` and `claim_date` that are set, else one `undated` unit. Listed years come first because OpenAlex lists affiliation years with gaps, and filling the span would count years no source states. The entry's count is the number of distinct units, so the same year from two sources counts once. Entries with a count of 0 are not on the list. Equal counts share a rank (1, 2, 2, 4), so no arbitrary order enters the score. A claim whose org has no stored facts does not count, and the card names that org.

### Lanes

A lane is a module in `lanes/` with `name: LaneName` and `run(ctx, LaneIn) -> LaneOut`, listed in `LANES`. search.py runs each as step `lane:<name>`, in the order of `LANES`. A lane reads the chips, stores the sources, people and claims it finds, and returns the people it keeps as hits. The web and LinkedIn lanes keep every person they find, the seed lane its top 100 and the OpenAlex lane the first 2,000 authors it reads. Each lane narrows its query to Belgium and keeps what comes back. The ranker owns the order of the fused list. To add a lane: add its name to `LaneName`, write the module, add it to `LANES`, add fixtures under `tests/fixtures/http/<lane>/` and a test that its claims pass the quote rule.

- **Seed lane.** Topic and institution chips both count as a query. `fts_query(chips)` is pure: it splits each chip into tokens, wraps each in double quotes with inner quotes doubled, ORs tokens within a chip and ORs across chips. Institution chips are expanded through the spellings `data/org_aliases.csv` lists for the same org id, such as "M.I.T.", which the tokenizer splits. The lane returns at most 100 hits (`MAX_HITS`). The SQL groups bm25 by person and keeps the best-matching claim as `matched_on`. Claims from `record`, `vendor_record` and `vendor_page` sources are excluded (`store.match_claims(query, exclude=)` takes a tuple of source kinds), because the OpenAlex, web and LinkedIn lanes rank those themselves and seed ranks would otherwise depend on past searches. bm25 still scores against the whole claims index, so the claims other lanes store shift seed ranks a little: on GS-10, 124,000 more OpenAlex record claims swapped seed #1 and #2. `page`, `seed_page`, `import` and `staff` sources stay searchable, because staff entered the last two on purpose. The query also leaves out rejected facts and email and phone claims.
- **OpenAlex lane.** Two queries, each a list call costing $0.0001 to $0.001:
  Institution chips run first, because the lane reads at most 2,000 authors (`MAX_AUTHORS`) and an institution list is the narrower query.
  1. Topic chips: `works?search=<topic>&filter=institutions.country_code:BE&per_page=100`, page 1 only, one call per topic chip, and the authors on those works. `reach.json` was recorded at this depth.
  2. Institution chips: `authors?filter=last_known_institutions.ror:<ror>,affiliations.institution.country_code:BE&per_page=200`, every page until `meta.count` is reached, capped at 4 pages (800 authors). MIT has 362 authors, so 2 calls, about $0.0002; Lermusiaux, de Wit and Goemans sit on page 1 (positions 157, 161, 190) and Janjevic on page 2 (position 47). A question with an institution and no topic still runs. `reach.json` was recorded at this depth. Institution chips resolve to ROR ids through `data/org_aliases.csv`.
  Author records are fetched in batches with `filter=ids.openalex:A1|A2|...`. When the question has a place of kind metro or no kind, `geo.area` turns it into coordinates and a radius (the LinkedIn lane calls the same function), and each author gets a haversine distance to their last known institution only. Place ranks and never drops. The lane keeps every author among the first 2,000 seen that OpenAlex returns a record for, Belgian or not, and drops the rest with the reason "not fetched" or "no author record returned". rank.py's belgian_years list decides how far up an author without a Belgian claim comes. The lane orders kept authors by place group (inside the radius or no place chip, then place unknown, then outside), then by the order OpenAlex returned them, and returns every kept author as a hit. A hit's claim ids are its Belgian affiliation claims and its location claim, so an author with neither has none. Each hit's affiliations are stored as claims at org ids (`ror:<id>`, else `openalex:<I…>`), and their institutions are saved as org rows. Each hit's `matched_on` ends with the distance and the last known institution, and the card shows it. An author with no last known institution or no institution geo is kept and marked "place unknown". The newest affiliation is not a fallback, because OpenAlex affiliations can be wrong (it places Baeyens, who has no last known institution, in Novi, Michigan in 2023). Every author seen goes into `considered` with the stage and reason. `Retry-After` is honoured once up to 30 s; a longer wait fails the step and names the wait. Chips that are only a place produce no hits and say so in `considered`.
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
  `extract.drafts` then makes one `role` claim per mention (the role, else the page title, else the URL's host) and one claim per relation, quoting its own passage. An institution relation gives an `affiliation` claim at `orgs.org_id(org)`, and `born_in` gives a `location` claim with no coordinates, and `lives_in` one with the coordinates `geo.coordinates` finds for the place, or none. The Dates rule above sets each claim's date.
  Every person a page names is a hit, not only people it ties to Belgium. Hits run in page order, then mention order, and `matched_on` holds the page rank, title and URL. The same person twice on a page is one hit with both sets of claims. A rerun over the same URL finds the same person when the name has the same name key. It adds a source only when the page text changed, and a claim only when the extract answer gives a new value or quote offset. The same name on two pages is two records on one card. Every page, mention and drop goes into `considered`.
  Without a Parallel key the lane logs a warning, notes it and returns no hits. A replay run with no recorded Parallel answer fails the step with `CacheMiss`, as a replay miss fails the OpenAlex lane. A quiet note would let a replayed gold run pass with no web results, so a gold run that should include the web lane runs with `FN_HTTP` live. A Parallel 402 or 422 fails the step with the body's message.
- **LinkedIn lane.** One POST to the Apify actor `harvestapi~linkedin-profile-search` (`run-sync-get-dataset-items`) per search. The actor charges $0.10 a search page of 25 and $0.004 a full profile, about $0.20 a run, and reports no cost. FN calls LinkedIn through Apify and never logs in to it. Chips with neither a topic nor an institution give one note and no call.
  1. Input: `actor_input(chips, area)` is pure, with `area` from `geo.area`, the lookup the OpenAlex lane shares. `geo.area` returns None for no place, for a place of kind abroad or anywhere_us (it does not fetch the cities dump then) and for a place that names no city. `searchQuery` is the topic chips, else the institution chips, joined by " OR ", each multi-word chip in double quotes. It keeps whole chips only while the query stays within the actor's 300 characters, and a note names the chips left out. `schools` is `SCHOOLS`, nine Belgian schools, because every Belgian organization counts the same. `locations` comes from `LOCATIONS`, which maps a GeoNames city to LinkedIn's location names ("New York City" to "New York City Metropolitan Area" and "New Jersey"). A city not in the table sends its own name, a place geo.py cannot locate or one abroad sends the place text, and no place or `anywhere_us` sends "United States". The rest is `profileScraperMode: "Full"`, `takePages: 1` and `maxItems: 25`. A live run has confirmed only the two New York names.
  2. Spending: the lane calls with `cache="prefer"` when `FN_LINKEDIN=1` (`Settings.linkedin_live`) is set and `cache="only"` when it is not, so it spends Apify credit only on purpose. A run that returned profiles is cached, so FN does not pay for the same input twice; a run that returned none is not cached, so the next live call with that input pays again. Off with no recorded run for the input, the lane notes that it is off and what a live run costs, and returns. With `FN_LINKEDIN=1`, `FN_HTTP=replay` and no recorded run, the note says that the replay has no recorded run; without `FN_LINKEDIN=1`, that case gets the off note. `FN_HTTP=prefer` serves a cached answer when the cache holds one and calls out otherwise, so a benchmark run pays only for the calls a change adds. A live call without an Apify token gives a note. The call sends `timeout=240` and `maxTotalChargeUsd=0.25` as query parameters with `timeout_s=290`, inside the sync call's 300 s limit. `keep` refuses an answer that is not a list holding at least one profile with a `linkedinUrl`, so an empty or failed run never fills the cache. The cost is an estimate, and the log line says so. An Apify refusal (the Free plan's run cap, credit gone, a 408) fails the step with the body's message. fn-gold refuses `FN_LINKEDIN=1` unless it runs exactly one case.
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

`FN_LLM` is `live`, `record`, `replay` or `prefer`; `live` calls the CLI through a recording FixtureLLM that writes each answer to `var/llm`, and the other modes read `Settings.fixtures_dir` (`FN_FIXTURES`, default `tests/fixtures/llm`); tests set `replay` and ClaudeCli refuses to start when `FN_ENV=test`. Run fn-gold with `FN_LLM=prefer`, so the 28 tracked parse fixtures give the same chips on every run while the extract calls run live on the subscription. Nothing in fn-gold sets the mode, and the report header records it. `.gitignore` excludes `tests/fixtures/llm/extract-*.json`, so a record run cannot commit real page text. `llm.user_turn` raises `TagError`, a `ValueError`, for a data value that holds its own closing tag.

## Pages

Staff pages are built from the design system's parts. `web/parts.py` has one function per part and copies the part's markup and class names, and `web/static/fn.css` and `tokens.css` are copied from the design system, so the site adds no CSS of its own. Staff pages never show scores, ranks, lane names, traces or tracebacks. Those are on the debug pages.

| Route | What it shows |
| --- | --- |
| `GET /` | Home: the question box, the three newest searches with an "All searches" link when there are more, then the network as the Network page shows it. An empty network shows a notice that points to Import and to adding people from a search |
| `GET /searches` | All searches, newest first |
| `POST /searches` | creates and queues a search, redirects to it |
| `GET /searches/{id}`, `GET /searches/{id}/map` | Results: the editable question, then cards under "In your network" (no buttons) and "New" (Add and Skip), beside a map. 20 people at a time, then "Show more" (`?shown=`). A line under the list counts skipped people that are hidden and shows them with `?skipped=1`. While the search runs a status line shows the people so far. `/map` is the same page with the map as the narrow-screen view |
| `GET /searches/{id}/status`, `GET /searches/{id}/cards` | the progress JSON and the list fragment that `results.js` uses |
| `POST /searches/{id}/people/{person_id}/{add,skip,same,new}` | a card decision. A `fetch` request gets the card back; any other request is redirected to the results page at the card |
| `GET /searches/{id}/export.csv` | the kept people of the search who are not skipped, as CSV |
| `GET /api/searches/{id}/geo` | GeoJSON, one point per person with a place |
| `GET /people` | Network: everyone in it as rows beside the map, newest added first. One text box filters on name, place and organization. Two filter tokens narrow the list further: "From import <file>", reached from the banner after an import, and "New facts only", reached from the "n with new facts" link. The count line reads like "214 people · 12 not on the map" and holds the Export link. 200 rows, then "Show more". Import sits on the section bar |
| `GET /people/export.csv`, `GET /api/people/geo` | the filtered network as CSV, and as GeoJSON |
| `GET /people/{id}` | Person: contact details, every fact once with its newest source under "Ties to Belgium", "Work" and "Places", what is new, "Found as" and "Possible matches". A merged record's id redirects to its person and an unknown id gives 404 |
| `POST /people/{id}/add`, `/skip`, `/remove`, `/contact`, `/merge`, `/not-same`; `POST /claims/{id}/reject`; `POST /events/{id}/undo` | the profile's decisions; each redirects back to the page it came from |
| `GET /imports/new`, `POST /imports`, `GET /imports/{id}`, `POST /imports/{id}/confirm`, `POST /imports/{id}/discard` | the upload page with the expected columns, then the preview with Import and Discard |
| `GET /sources/{id}` | a source's text with the quoted span marked; an import or staff source shows its label and no outside link |
| `GET /debug`, `GET /debug/searches/{id}` | searches; one search with its facts, chips form, steps with status, duration, cost and call count, log lines, tracebacks, links to payloads, and a card per candidate with score parts, lane matches and the cut reason |
| `POST /searches/{id}/rerun` | queues a new search with the edited chips and `rerun_of` |
| `GET /debug/steps/{id}/input.json`, `/output.json` | the full payloads |
| `GET /debug/steps/{id}/calls` | every HTTP and LLM call of a step |
| `GET /debug/searches/{id}/trace?name=` | one person through every step: considered, kept, dropped and why |
| `GET /debug/sources/{id}` | a source's facts: kind, date and method, fetch time, content hash |
| `GET /debug/errors` | stored request errors with tracebacks |
| `GET /debug/stats`, `GET /debug/feedback` | timings and costs per step and per search; what staff did with each search's results |

The staff pages in more detail:

- **Results.** A card shows the name as a link to the profile, role, employer and place, up to three Belgian organizations with their years and one claim as evidence. A fact from a database record reads like "Studied at KU Leuven, 2008–2013" and shows its citation; only a prose source shows a quote. After Add the card reads "Added to your network" with Undo. A card for a person whose name matches a network person reads "Same name as … in your network" with "Same person", "Add as new" and Skip. A skipped card shrinks to one line with Undo. A dot on the map opens a popup with the name as a link, role, employer, place and "Open profile". People at one point share a dot with a count. A row click opens its dot's popup from 900 px up.
- **Person.** A network person shows "In your network since …" with Remove, and a profile of anyone else shows Add and Skip or the same-name buttons. Each fact has Remove, and a person in the network can edit email and phone. "Found as" lists each record and source with "Not this person". "Possible matches" lists same-name records with "Same person" and "Different person". Facts are first ten per group, then "Show n more". A fact new since the last visit is marked "New" until the profile is opened again.
- **Import.** The preview counts rows in words, lists skipped rows with their reason, the ignored columns and one box per name match, and offers Import and Discard. After a confirm the Network page shows "n people imported from <file>" with a link to exactly those people.

The app runs in `mode = local` only, and fn-serve refuses any host other than 127.0.0.1 or ::1. TrustedHostMiddleware allows only 127.0.0.1, localhost and [::1] and sits inside the guard, so its 400 also carries the security headers. A non-GET request is refused unless its Origin is the app's own or absent, or is `null` with `Sec-Fetch-Site: same-origin` (a browser sends `null` from the app's own forms because of `Referrer-Policy: no-referrer`), and it is refused whenever `Sec-Fetch-Site` is `cross-site` or `same-site`. Every response sends `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; connect-src 'self' https://tiles.openfreemap.org; worker-src blob:; frame-ancestors 'none'` and `Referrer-Policy: no-referrer`. MapLibre is vendored into `web/static` with its sha256 checked by a test.

Form posts are parsed with `urllib.parse.parse_qs`, because FastAPI's `Form()` needs python-multipart, which is not an approved dependency. A file upload is `multipart/form-data`: `POST /imports` reads the body through `request.stream()`, stops past 5 MB plus the framing, and parses it with the stdlib `email.parser`. HTML comes from `web/html.py`. Every value is escaped unless it is a `Safe` built inside html.py, and links accept http, https, mailto, tel and relative URLs only. A rerun keeps the `ref` of a chip and the `kind` of the place only when the posted text equals the text of the search being rerun; an edited text gets none, so geo and lane code must treat a missing `ref` or `kind` as unresolved. A test renders every page, and the 400 pages that echo input, with `<script>` and `javascript:` in every text field. Every page links `tokens.css` and `fn.css`. Debug pages add the body class `fn-debug` and use plain tables, forms and preformatted text.

## Logging

stdlib logging writes to `var/log/fn.log` with rotation. A contextvar filter adds `search_id` and `step` to every record, a redacting filter runs on the root logger's handlers (the file and stderr), and the httpx logger sits at WARNING. Records emitted inside a step are also stored in `step_runs.log`. `web/app.py` writes one `fn.request` line per request except `/static/`: method, path, status, milliseconds and the facts the handler set. List pages set rows, total and whether a filter was used, results set kept and shown, the status route sets version and people, a card decision sets its action, and an import sets its row counts. A request over 1,000 ms logs at WARNING. `geo.coordinates` logs one line for every web-lane place it finds no city for.

`/debug/stats` shows, per step name over the newest 20 searches, the runs, errors, median and slowest seconds, median cost and median call count, and per search its status, total seconds, cost, people saved and seconds to the first person (the first publish or save step that saved anyone). `/debug/feedback` shows, for the newest 50 searches with an Add or Skip, the people kept and cut, added and skipped (a decision an Undo reversed does not count), the lanes behind the added people, and how many added people stood at ranks 1 to 10, 11 to 50, 51 to 100 and over 100. `var/` and `var/log` are created with mode 0700 by `setup_logging`, before the database is opened.

## Gold runner

`fn-gold [CASES]` runs the cases from `data/gold/gold-set.json` (all 28 by default) with the current settings, stores each run as a normal search, and writes `var/gold/<timestamp>/report.md` and `top5.csv`. A pick matches the candidate that holds its pinned person, the stored person for the OpenAlex id `data/gold/reach.json` gives it; without a pin, or when the store does not hold the pinned person, it matches by group key. For each pick the report prints found, event page or missed, section and rank (found means top 10 of its section), the lanes behind the pick, each with its rank in that lane, the gold tie next to the person's Belgian claims and `belgian_years` count, and for a miss the step and reason from the trace. A pick with no candidate gets the Belgian claims of the stored records with its group key, or "no stored record". It gives no verdict on the tie. `top5.csv` holds the top five cards per case with name, reason quote and Belgian claims, plus an empty column for a good-pick mark. The report header holds `code_sha`, `dirty`, the LLM mode and the HTTP mode.

- **Event page.** A pick that would be found gets the label `event page` when it has at least one reason source and every reason source is a `vendor_page` or `page` source at the case's own event page (`GoldCase.source_url`). Two URLs are the same page when their hosts match without a leading `www.` and their decoded paths match without a trailing slash. The query and fragment are ignored. A page elsewhere on the same site is other evidence. So is a LinkedIn profile, whether a `vendor_record` or a web-lane `vendor_page` at its own URL, although 13 cases have a `linkedin.com/posts` source. gold.py compares source kinds and URLs and knows no lane's URL format. The dev success measure counts `event page` as not found, and the summary table has an Event page column.
- **Cut and failed lanes.** The runner matches picks against kept candidates only. A pick the cut removed has no candidate, so its trace row at the rank step reads dropped, and the report says it was lost at `rank` with the reason `no_belgian_evidence`. A lane that failed on a search that still ended done shows in the case's status, such as "done, lane error in lane:web". `scripts/gold/cut_gate.py DB` checks the cut over a stored database and exits 1 when a pick that reaches the ranker is cut, fewer than 4 picks stand in the first 50 kept people or fewer than 6 in the first 100, or the median kept count falls by less than 40%.
- **Cost.** `report.md` gives each case two costs. Vendor calls are the sum of the search's http call costs. LLM is the sum of its LLM call costs, which are the Haiku costs the CLI reports; the subscription does not bill them. A parse answer served from a fixture counts the cost recorded with the fixture, although no call ran, while a cached vendor call counts 0. A call with no cost counts as 0. The lanes behind each pick are in `report.md` too, and the stdout of fn-gold prints neither the lanes nor a cost.
- **Unreachable picks.** reach.json was recorded for seeds and OpenAlex only. A pick it calls unreachable that no lane found keeps the trace's lost step and reason, and reach.json's evidence follows them. Its verdict stays `no lane in slice`.
- **The FN_LINKEDIN guard.** fn-gold refuses `FN_LINKEDIN=1` unless it runs exactly one case. It exits with 2 right after reading the settings, before the Store or the Worker exists, so one command cannot start 28 paid runs. Without `FN_LINKEDIN=1` the LinkedIn lane serves a recorded run for the same input at $0.

## Responsibility table

| Responsibility | Owner |
| --- | --- |
| Shape of every value that crosses a module boundary, view models, the import column list, and normalize() | `contracts.py` |
| The canonical form of a LinkedIn profile URL | `contracts.profile_url`, called by the LinkedIn lane and the importer |
| Every SQL statement and the stored invariants | `store.py` |
| Person identity at write time | `store.resolve_person` |
| The claims of a whole person (merged records included) and hiding rejected facts | `store.claims_of`, with `store.match_claims` for search |
| `first_seen_at` of a claim | `store.upsert_claim`, with the time its caller passes |
| Who is in the network and what staff decide: add, skip, remove, merge, not same, reject a fact, set a contact detail, undo, mark seen, name matches, the event for each, and `seen_at` | `network.py` |
| Schema changes | `migrations/` run by `db.migrate()` |
| Outbound GET and POST, the key header per host, missing keys, the cache key, cache modes, retries, error text, timeouts, call recording | `net.py` |
| Prices for vendors that report no cost, passed to net.py as a cost function; net.py reads OpenAlex's own `meta.cost_usd` | the lane that calls the vendor |
| Whether an answer is worth caching, passed to net.py as `keep` | the lane that calls the vendor |
| When the LinkedIn lane may spend | `Settings.linkedin_live`, read by `lanes/linkedin.py` |
| Calling Claude, and fixture or live per LLM call, by `FN_LLM` | `llm.py` |
| Recording steps, calls, logs and tracebacks; redaction | `steps.py` |
| Search lifecycle, the worker thread and the startup sweep | `worker.py` |
| Order of steps in a search, publishing people while lanes still run, going on after a failed lane | `search.py` |
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
| CSV text to rows, row checks, the preview and the confirm, and the claims an imported row writes | `importer.py` |
| Network and search results to CSV | `exporter.py` |
| Spelling to institution id, for schools, employers and imported organizations too | `orgs.py` with `data/org_aliases.csv` |
| Institution facts, from ROR, Wikidata or OpenAlex | `orgs.save`, called by fn-orgs (`orgjob.py`) and the OpenAlex lane |
| Which claims are at a Belgian organization | `orgs.belgian_claims`, called by rank, present, the debug pages and gold |
| Mapping hits to canonical ids, one entry per name (group key) in a result, name-only flags, splitting on not-same pairs and different ORCIDs | `resolve.py` |
| Turning claims into ranked lists, fusing the lanes' lists, sections, ordering entries, the cut and its reason | `rank.py` |
| Which of the people a lane finds it keeps (the seed top 300, the first 2,000 OpenAlex authors with a record, everyone for web and LinkedIn) | each lane, under Lanes |
| The order of a lane's own hits (bm25 for seeds, place group then order seen for OpenAlex, page order for web, actor order for LinkedIn) | each lane, under Lanes |
| Turning a claim into year units | `rank.units`, called by rank, present, the debug pages and gold |
| Place text to coordinates, radius and city, the alias file, and the city of an import row (`geo.area`, `geo.locate`, `geo.locate_city`, `geo.coordinates`) | `geo.py` |
| Coordinates on a web-page lives_in claim | `extract.drafts`, through `geo.coordinates` |
| A city to LinkedIn's location names | `lanes/linkedin.py` |
| How a person reads: role line, place, organizations, claim wording, what counts as new, the card state, the network view and the profile | `present.py` |
| The label and link of an `fn:` source | `present.label_of` |
| Read models for the owner: timings, costs, feedback | `stats.py` |
| App factory, host and origin checks, security headers, the request log, error pages | `web/app.py` |
| Staff routes and pages, and which network call each button makes | `web/staff.py` |
| Debug routes and pages, and the chip rerun | `web/debug.py` |
| The HTML of each design-system part | `web/parts.py` |
| Escaping, safe links and the page shell | `web/html.py` |
| Polling the status route and swapping cards in place | `web/static/results.js` |
| Map markers, popups and the row-to-dot link | `web/static/map.js` |
| Token values, part looks and part rules | the design system |
| Site CSS | `web/static/fn.css`, copied from the design system |
| Gold scoring and reports, the event-page label, lanes per pick, cost per search, a cut pick lost at rank, failed lanes, refusing `FN_LINKEDIN=1` for more than one case | `gold.py` |
| Whether the cut keeps the gold picks and shrinks the lists enough | `scripts/gold/cut_gate.py` |
| Who is one person: name rules, evidence levels, vetoes, the records a card reads | `identity.py`; `resolve`, `network`, the importer and `enrich` call it |
| What a card shows for a question, and where a person is | `evidence.py`; `rank.py`, `present.py`, the seed lane and `score.py` read it |
| Running the steps after the lanes again on a stored search | `search.refinish` (`fn-rerank`) |
| The date a search ranks as of | `steps.as_of` |
| Looking up what seed people and ORCID holders miss | `enrich.py` (`fn-enrich`) |
| Coordinates of a place claim, on write and for stored claims | `extract.py` (`drafts`, `locate_stored`) |
| Scoring results and gating a change | `score.py` (`fn-score`) |

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
- Shared mode, login, several users and the admin list for debug pages. `user_id` on searches and events stays empty.
- Weighting Flanders above Wallonia, or by language, or letting the question choose. The owner settled equal weight for all of Belgium in this slice.
- A tie badge or filter. The Network page has one filter box for name, place and organization, and shows Belgian organizations as text.
- Place-of-birth lookups, and org facts for companies. The web and LinkedIn lanes now store born-in and employer claims, but a born-in claim has no coordinates and an employer not in `data/org_aliases.csv` has no org id, so the map skips the born-in claim and the ranker skips an employer with no org id.
- FN's own page reader, and Parallel's Decisions, Task and FindAll. The web lane uses Search and Extract only.
- Calling Parallel or Haiku concurrently. A web search makes up to about 30 Haiku calls in a row, one to three a page, and nothing caps the number.
- Location claims from LinkedIn profiles, company filters on the Apify actor and other Apify actors. A second run filtered by past Belgian employers would reach people with a Belgian job and no Belgian degree, and waits for Apify budget.
- Changing the order of the fused list, and a model that reorders the top results. The cut only removes people. The story map reports that a test of three ways to use the question's place in the ranker found none that helps without losing a gold pick.
- Running lanes at the same time, server-sent events and time estimates. Lanes run one after another and people appear after each.
- Excel import and a step that guesses columns, an undo for a whole import (people are removed one by one), fuzzy or nickname name matching, and a model that judges duplicates.
- Editing a fact by hand. Staff edit email and phone and remove facts.
- Sort controls, map clustering, filtering by the map's bounds, place and organization selects, and statistics on the home page. People at one point share a dot with a count.
- A copy of the design system in the repository, any change to how FN is deployed and any new dependency.
- A spend limit across searches for Parallel. A gold run of 28 cases costs about $0.31 in Parallel calls, and no requirement asks for a limit yet.
- Dutch query rows and `source_policy` domain lists for Parallel Search. The web lane sends the query set it builds from the chips.
- Moving the OpenAlex lane's place ordering into the ranker. Ordering by place is ranking too, so it gets its own change with a gold comparison.
- Dropping the Belgian filters from the OpenAlex queries. They decide which authors the lane sees, and without them the MIT author list would run past the 800 authors the lane reads.
- Catching other pages about the same event. The event-page label compares the page's URL only.
- Turning a vendor refusal (a 402, a 422, an Apify refusal) into a note. It fails the lane's step, as an OpenAlex error does, and the search goes on without that lane.
