# What the FN documents say a change must respect

2026-11-12 · digest of the design and architecture documents, read read-only. Every reference points at a document line, not at code, unless the line says `src/`.

**Summary.** FN is a local FastAPI app with one SQLite file. It helps a delegation's staff find people with a Belgian tie and shows every claim with a source, a verbatim quote and a date. The documents fix a small set of rules: one identity function, quotes found at stored offsets, name-only matches flagged and never merged, and no tie label. They split the code into modules with one owner each. The staff pages Ask, Results and Source are designed and (per the restyle brief) restyled. Add, Skip, Undo, merge, the Person page, the Network page, export, import and login are designed or listed in the story map and not built. Logging, per-step cost and a 28-case gold runner exist. The documents say nothing about GDPR beyond a terms note.

References below use these short forms. `arch` = `notes/mvp0/architecture.md`, `plan0` = `notes/mvp0/plan.md`, `prog` = `notes/mvp0/progress.md`, `ref` = `notes/research/mvp-tech-reference.md`, `dec` = `notes/design/decisions.md`, `dplan` = `notes/design/plan.md`, `brief` = `notes/design/restyle-brief.md`, `map` = `notes/design/story-map.md`. The four `notes/design/` files are in the main checkout, not yet in this worktree.

## 1. The product

**Users.**

| Who | Source |
| --- | --- |
| This slice: the owner alone, on a laptop, debugging the pipeline | `notes/mvp0/architecture.md:30` |
| Later: delegation staff, 5 to 20 people | `notes/design/decisions.md:9`, `notes/research/mvp-tech-reference.md:5` |
| Identity: FN's own, with no government or FIT branding, because the owner has no official affiliation | `notes/design/decisions.md:10` |

**What FN is for.**

- A staff member types a question and sees people with a Belgian tie, from the network first and then new people found by the lanes (`notes/design/story-map.md:34`, `notes/design/decisions.md:26`).
- The goal of the first slice is to run real questions end to end and see why each person was or was not found (`notes/mvp0/architecture.md:28-30`).
- The ask types are talk, mentor, host, join and other (`notes/mvp0/architecture.md:133`).
- The gold set is 28 scorable cases plus 3 controls, built from past delegation events (`notes/research/mvp-tech-reference.md:261`).

**What it must never do.**

| Rule | Source |
| --- | --- |
| Show a claim without a source link, a verbatim quote at stored offsets, and a date or "undated" | `notes/mvp0/architecture.md:40`, `:169` |
| Merge people on a shared name alone | `notes/mvp0/architecture.md:166`, `:384` |
| Date a claim by the day FN read the page | `notes/mvp0/architecture.md:170` |
| Store or compute a tie label | `notes/mvp0/architecture.md:11` |
| Show a place no source supports on the map (the map reads location claims only) | `notes/mvp0/architecture.md:382` |
| Log in to LinkedIn (it reads profiles through Apify) | `notes/research/mvp-tech-reference.md:59`, `:521` |
| Retry a page around a 403, login wall or CAPTCHA | `notes/research/mvp-tech-reference.md:30` |
| Turn generated answers or vendor reasoning into claims | `notes/research/mvp-tech-reference.md:522` |
| Invent institutions; an institution resolves to ROR or stays quoted text | `notes/research/mvp-tech-reference.md:524` |
| Show staff scores, lanes, chips, traces, record breakdowns, org-facts notes or step statuses | `notes/design/decisions.md:29`, `notes/design/plan.md:123` |
| Run the app on a host other than 127.0.0.1 or ::1 in this slice | `notes/mvp0/architecture.md:295` |
| Hold contact details (out of the MVP in the research doc; the story map later lists email and phone columns, see section 7) | `notes/research/mvp-tech-reference.md:525`, `notes/design/story-map.md:127-128` |

## 2. Architecture invariants

| # | Invariant | Section and line |
| --- | --- | --- |
| 1 | Every value crossing a module boundary is a frozen Pydantic model or Literal from `fn/contracts.py`. Modules never pass dicts or rows. `CONTRACTS_VERSION` is stored with each payload. | Paradigms, `notes/mvp0/architecture.md:52` |
| 2 | Only `store.py` runs SQL, only `net.py` and `llm.py` call outside, only `web/` handles HTTP. | Paradigms, `notes/mvp0/architecture.md:53` |
| 3 | A step is `(ctx, InputModel) -> OutputModel` and reaches the world only through a frozen `StepContext`. | `notes/mvp0/architecture.md:54` |
| 4 | A lane writes its sources, people and claims before it returns, by upsert on natural keys. A rerun writes nothing new. Later steps get ids, never source text. | `notes/mvp0/architecture.md:55` |
| 5 | A step row exists before the step runs. A failure stores the traceback, fails the search and stops it. Nothing retries silently. | `notes/mvp0/architecture.md:56` |
| 6 | Plain SQL, numbered migrations, an applied migration is never edited. | `notes/mvp0/architecture.md:57` |
| 7 | One identity function: `store.resolve_person(identifiers, display_name)` is the only way to get a person id. `person_identifiers` has UNIQUE(scheme, value). | Rules, Identity, `notes/mvp0/architecture.md:166` |
| 8 | A shared name never joins two people. `resolve.py` groups same-name records into one card and flags them ("same name in N records, not merged"). | `notes/mvp0/architecture.md:166`, `:168` |
| 9 | Every claim is valid only if `source.text[quote_start:quote_end] == quote`. The ClaimDraft validator and `store.upsert_claim` both check it. | `notes/mvp0/architecture.md:140`, `:169` |
| 10 | A web-page claim gets a date only when its quote states a year. `claim_date` is never the read date. | `notes/mvp0/architecture.md:170` |
| 11 | An institution is an `orgs` row. `orgs.save` is the only writer. A spelling not in `data/org_aliases.csv` leaves `org_id` empty. | `notes/mvp0/architecture.md:171` |
| 12 | A claim is Belgian when its org has `country_code = BE`, whatever its relation. Region and name language are shown, never scored. Nothing stores the label. | `notes/mvp0/architecture.md:172`, `:17-18` |
| 13 | The ranker counts Belgian evidence only for records a lane returned, never for a record that shares only the name. | `notes/mvp0/architecture.md:172` |
| 14 | Ranking is reciprocal rank fusion, `1 / (60 + rank)` per list, no hand-set weights, each term stored as a ScorePart. | `notes/mvp0/architecture.md:222` |
| 15 | `rank.py` owns the order of the fused list and any cut across lanes. It has no cut today. | `notes/mvp0/architecture.md:224`, `:344` |
| 16 | Keys are `SecretStr`, travel in a header to their own host over https only, and `redact()` replaces every secret value with `***` everywhere. | `notes/mvp0/architecture.md:173`, `:262` |
| 17 | LLM data goes in tagged blocks on stdin. Output is used only as schema fields and is escaped like other text. | `notes/mvp0/architecture.md:174` |
| 18 | HTML comes from the escape-by-default builder; links accept http, https and relative URLs only. | `notes/mvp0/architecture.md:297` |
| 19 | Non-GET requests are refused unless the Origin is the app's own or absent. The CSP is `default-src 'self'` plus the tile host. | `notes/mvp0/architecture.md:295` |
| 20 | Section `network` means `list_status = in_list`. Nothing sets that yet, so every result is in section `new`. | `notes/mvp0/architecture.md:167` |
| 21 | Vocabularies are Literals defined once, with no SQL CHECK constraints. | `notes/mvp0/architecture.md:103`, `:383` |
| 22 | A lane has `name` and `run(ctx, LaneIn) -> LaneOut`, listed in `LANES`. Adding one follows a fixed checklist. | `notes/mvp0/architecture.md:229` |
| 23 | The seed lane excludes `record`, `vendor_record` and `vendor_page` claims from its search. | `notes/mvp0/architecture.md:231` |
| 24 | `var/` is gitignored with mode 0700. | `notes/mvp0/architecture.md:178` |

## 3. Module map

Responsibility table: `notes/mvp0/architecture.md:312-351`. Module layout: `notes/mvp0/architecture.md:59-97`.

| Module | Owns | Line |
| --- | --- | --- |
| `contracts.py` | every model and Literal, `normalize()`, `record_source`, `page_source`, `clean_name`, `CONTRACTS_VERSION` | `notes/mvp0/architecture.md:64`, `:316` |
| `config.py` | frozen Settings: paths, mode, host, port, LLM mode, secret keys, the `FN_LINKEDIN` switch | `:65` |
| `db.py`, `migrations/` | per-thread connections (WAL, foreign keys, busy timeout, secure_delete); `migrate()`; schema changes | `:66-67`, `:318` |
| `store.py` | every SQL statement, `resolve_person`, upserts, reads for pages and debug | `:68`, `:317` |
| `net.py` | the one outbound HTTP client: timeouts, size cap, keys per host, cache modes, retries, call recording | `:69`, `:320` |
| `llm.py`, `prompts/` | the Claude CLI wrapper and fixtures; record, replay, prefer | `:70-72`, `:324` |
| `steps.py` | StepContext, `run_step`, recorder, `redact`, log capture | `:73`, `:325` |
| `worker.py` | one-thread executor, search lifecycle, startup sweep | `:74`, `:326` |
| `search.py` | order of steps in a Quick search | `:75`, `:327` |
| `parse.py` | question to chips, span check | `:76`, `:328` |
| `extract.py` | page text to named people, located quotes, mention identity, claim drafts | `:77`, `:336-337` |
| `lanes/` | `seeds` (FTS query and search), `openalex`, `web` (Parallel), `linkedin` (Apify); each lane keeps its own hits and their order | `:78-82`, `:330-334`, `:345-346` |
| `orgs.py`, `orgjob.py` | spelling to org id, org facts, `belgian_claims`; fn-orgs job | `:83-84`, `:340-342` |
| `resolve.py` | one entry per group key, name-only flags | `:85`, `:343` |
| `rank.py` | belgian_years list, RRF, sections, cut, `units` | `:86`, `:344`, `:347` |
| `seedload.py` | seed files to persons, sources, claims | `:87`, `:339` |
| `geo.py` | place chip to coordinates and radius; `area()` shared by two lanes | `:88`, `:348` |
| `gold.py` | fn-gold runner, event-page label, report, cost per search | `:89`, `:351` |
| `web/app.py`, `web/html.py`, `web/static/` | routes, middleware, error pages, escape-by-default builders, MapLibre, CSS | `:90-92`, `:350` |

Lane-local ownership: prices for vendors with no cost report and the `keep` rule for caching belong to the calling lane (`notes/mvp0/architecture.md:321-322`); the LinkedIn city-to-location table belongs to `lanes/linkedin.py` (`:349`).

Ownership for the design system and the site: token values and part looks belong to the design system, HTML structure and `map.js` to the restyle session (`notes/design/plan.md:117-132`). A value change starts in the design system (`notes/design/plan.md:134`).

## 4. Decisions on staff pages and features

Status key: **decided** (choice is final), **designed** (written down, not built), **deferred** (named as later or not doing). "Built" is only as far as the documents say.

| Feature | Decision | Status | Source |
| --- | --- | --- | --- |
| Staff pages | Ask `/`, Results `/searches/{id}`, Person `/people/{id}`, Source `/sources/{id}`, Network `/people` | Ask, Results, Source decided and restyled by the brief; Person and Network designed, built later | `notes/design/decisions.md:28` |
| Staff view | One question box; chips, scores, lanes, traces, breakdowns, org-facts notes and step statuses move to `/debug`, with no link from a staff page | decided | `notes/design/decisions.md:29-30` |
| Results card | Name, role and employer, place, one line of Belgian ties, one quote as the reason with its source, Add and Skip. People already in the network show no buttons | decided; the buttons are not rendered until the logic exists | `notes/design/decisions.md:31`, `notes/design/restyle-brief.md:42` |
| Results layout | Cards and map side by side from 900px, a List/Map switch below | decided | `notes/design/decisions.md:32`, `notes/design/restyle-brief.md:34` |
| Add | Button turns into "Added to your network" with Undo. Add is one SQLite transaction: person, claims shown and decision | state decided in the design system; logic not built | `notes/design/decisions.md:45`, `notes/research/mvp-tech-reference.md:133`, `notes/design/story-map.md:53` |
| Skip | Card shrinks to one line with Undo; the dot leaves the map. Skip writes a decision the resolver reads next time | state decided; logic not built | `notes/design/decisions.md:45`, `notes/research/mvp-tech-reference.md:133`, `notes/design/story-map.md:56` |
| Undo | Undo for Add and Skip | state decided; logic not built | `notes/design/story-map.md:57` |
| Duplicates and merge | Not shown in results. Finding duplicates and merging are steps of the Add flow, "designed later". Research design: merge re-points records and keeps both sets of sources; "Keep separate" stores a not-the-same judgement; borderline pairs go to one Sonnet call | deferred in `decisions.md`; research design only | `notes/design/decisions.md:34`, `notes/research/mvp-tech-reference.md:130`, `:133`, `:442` |
| Add flow choice | Add as new, merge into the existing person, or keep apart | not built | `notes/design/story-map.md:55` |
| Person page | Parts exist in the design system (a claim with quote, source and date); full page not designed. Marks new facts "new since you last looked" | designed in parts only, not built | `notes/design/decisions.md:46`, `notes/design/story-map.md:76`, `:118` |
| Network page | Parts (a list row) exist; full page not designed. The Network link stays out of the header until the page exists | not built | `notes/design/decisions.md:46`, `notes/design/restyle-brief.md:43` |
| Network starts empty | Nobody is in the network at the start; it fills through import and Add; the 4,940 seed people stay candidates | decided (D1) | `notes/design/story-map.md:116` |
| Import | CSV with fixed column names (`name`, `email`, `phone`, `organization`, `role`, `city`, `state`, `country`, `linkedin_url`, `orcid`); preview shows rows read, skipped, ignored columns and possible duplicates. The old plan was `openpyxl` for Excel | CSV decided (D3, D4); Excel deferred; not built | `notes/design/story-map.md:120-139`, `notes/research/mvp-tech-reference.md:133` |
| New facts about a network person | FN adds them and marks them; staff remove a wrong fact; a same-name match stays a possible match | decided (D2); not built | `notes/design/story-map.md:118` |
| Export | CSV with one row per person (name, role, organization, place, Belgian ties, source link); scope: whole network, a filtered list or one search | listed as missing, no design; the research design uses XlsxWriter and `csv` | `notes/design/story-map.md:91-98`, `notes/research/mvp-tech-reference.md:230` |
| Login | Out of scope in this slice. Research design: oauth2-proxy with the Entra ID provider, allowed tenants and an email allowlist. `Search.user_id` is `None` | deferred | `notes/mvp0/architecture.md:48`, `:134`, `:394`, `notes/research/mvp-tech-reference.md:232`, `notes/design/story-map.md:110` |
| Several staff | 5 to 20 users named, with a record of who added whom listed as a possible flow; shared mode and the admin list for debug pages not built | deferred | `notes/design/decisions.md:9`, `notes/design/story-map.md:110`, `notes/mvp0/architecture.md:394` |
| Searching state | "Searching… N people so far" with a moving blue bar; people appear as FN finds them | state designed; live updates are for a later session. Today the page refreshes every 2 s | `notes/design/decisions.md:42`, `notes/design/plan.md:131`, `:141`, `notes/mvp0/architecture.md:216` |
| Failed and no-results states | "This search stopped" with Try again, no technical details; no-results says how many sources were read and hides the map | decided | `notes/design/decisions.md:43-44` |
| "In your network" section | Exists, stays empty until people are added | partial | `notes/design/story-map.md:40` |
| Remove, edit by hand, browse the network as a list, look up one person | listed as "flows this map may be missing" | not decided | `notes/design/story-map.md:102-110` |

Suggested build order: import then network list, map and Person page; then export; then Add, Skip and merge plus the "In your network" section; then new facts (`notes/design/story-map.md:143-150`). The stricter ranker cut and the card claim format fit slice 3 (`:150`).

## 5. Technology choices and reasons

| Choice | Reason given | Source |
| --- | --- | --- |
| Python 3.13, uv, `python-preference = "only-managed"` | Without the setting, uv picked the conda base Python of the owner's shell | `notes/research/mvp-tech-reference.md:15`, `notes/mvp0/plan.md:19` |
| FastAPI on uvicorn, Pydantic, httpx | The only dependencies in the first slice; no other new dependency allowed | `notes/mvp0/plan.md:19`, `:135` |
| One SQLite file, WAL, FTS5, no ORM | One file per prototype fits 10,000 people and 5 to 20 users; plain SQL with numbered migrations | `notes/research/mvp-tech-reference.md:208`, `notes/mvp0/architecture.md:57` |
| No CHECK constraints | SQLite needs a table rebuild to change one; vocabularies stay Literals | `notes/mvp0/architecture.md:383` |
| No Jinja2 or template engine | Jinja2 is a new dependency the owner has not approved; `html.py` escapes by default and a test renders every page | `notes/mvp0/architecture.md:381`, `:391` |
| Form posts via `urllib.parse.parse_qs` | `Form()` needs python-multipart, not approved | `notes/mvp0/architecture.md:297` |
| MapLibre GL JS, vendored, with a pinned copy of the OpenFreeMap Positron style | A hash is checked by a test; the CSP allows only the tile host. Two reviewers would cut the map; it stays because the owner asked and it reads location claims only | `notes/mvp0/architecture.md:295`, `:382`, `:5` |
| No JavaScript framework, no CSS framework, no SSE | Server-rendered HTML; the design system has no React components or `bundle.js` | `notes/mvp0/architecture.md:391`, `notes/design/decisions.md:57` |
| Claude through the `claude` CLI on the owner's subscription | No API key; tests use fixtures keyed by prompt hash; Pydantic AI is deferred because it needs a key | `notes/mvp0/architecture.md:273-276`, `:389` |
| Reciprocal rank fusion | Bounded top k, no hand weights | `notes/mvp0/architecture.md:222`, `notes/research/mvp-tech-reference.md:209` |
| Fonts: Source Serif 4, IBM Plex Sans, IBM Plex Mono, woff2 files committed locally | Open licences; the CSP forbids a font CDN; static 400 and 600 files at one optical size avoid a new variable-font download | `notes/design/decisions.md:19`, `notes/design/plan.md:15` |
| Light theme only, accent `#2d5a47` | Dossier feel; accent only for Add, the picked card and map markers | `notes/design/decisions.md:12-20` |
| Dependencies: allowed list | The research doc approved the Python stack on 2026-10-29 (DBOS, Pydantic AI, sqlite-vec, trafilatura and others), but the first slice built none of them. The engineering rule is to ask the owner before adding any | `notes/research/mvp-tech-reference.md:15`, `:201`, `notes/mvp0/architecture.md:388` |
| Research design not built: DBOS, Pydantic AI, sqlite-vec, Qwen3 embeddings, Inspect AI, XlsxWriter, openpyxl, oauth2-proxy | Listed in the stack table as the full-MVP choice; the slice names them "not doing" | `notes/research/mvp-tech-reference.md:206-236`, `notes/mvp0/architecture.md:388-389` |
| OpenAlex, Parallel Search and Extract, Apify LinkedIn actor, ROR, Wikidata, GeoNames | Vendor lanes; prices and the reasons for each are in the lane sections | `notes/mvp0/architecture.md:229-256` |
| Keep the parse model on Haiku | Cheap structured output; the web extract task also uses Haiku | `notes/mvp0/architecture.md:273` |

## 6. Logging, traces, cost, evaluation and the gold set

**Logging and traces.**

- stdlib logging writes to `var/log/fn.log` with rotation. A contextvar filter adds `search_id` and `step`. A redacting filter runs on the file and stderr handlers. Records inside a step also go to `step_runs.log` (`notes/mvp0/architecture.md:301`).
- The runner records, per step: status, duration, input and output JSON (in `step_payloads`, kept apart so they can be purged later), every HTTP and LLM call, tokens, cost, model, prompt sha and the full traceback (`notes/mvp0/architecture.md:154`, `:185`, `:393`).
- Every search stores `code_sha`, `dirty`, `llm_mode`, `settings_json` and `boot_id` (`notes/mvp0/architecture.md:134`, `:377`).
- Debug pages: steps with status, duration, cost and call count, full payloads, calls, a person trace ("considered, kept, dropped and why") and stored request errors (`notes/mvp0/architecture.md:288-292`).
- Every lane returns a `considered` list with the stage and reason for each person it dropped (`notes/mvp0/architecture.md:148`, `:361`).
- Payloads stored under an older `CONTRACTS_VERSION` show a note, not a parse (`notes/mvp0/architecture.md:162`).

**Costs.**

- OpenAlex cost comes from its `meta.cost_usd`. Parallel and Apify costs come from a lane price function. A cached or replayed call records 0.0 (`notes/mvp0/architecture.md:266`, `:239`, `:252`).
- LLM costs are what the CLI reports; the subscription does not bill them (`notes/mvp0/architecture.md:308`).
- Per-search cost in the gold report splits vendor calls and LLM (`notes/mvp0/architecture.md:160`, `:308`).
- Figures: a 28-case gold run costs about $0.31 in Parallel calls, one LinkedIn run about $0.20 in 178 s, the web lane about $0.011 for 10 pages and a median 186 s (`notes/mvp0/architecture.md:403`, `:256`, `:239`, `notes/mvp0/progress.md:30`).
- Spending guards: the LinkedIn lane calls out only with `FN_LINKEDIN=1`, and fn-gold refuses that flag for more than one case (`notes/mvp0/architecture.md:253`, `:310`). No spend limit across searches exists (`:403`).
- Research targets per depth (estimates, not measured): Quick about $0.06, Extended about $0.40, Deep about $3.50 (`notes/research/mvp-tech-reference.md:303-309`). The research design wants OpenTelemetry GenAI field names and genai-prices (`:134`, `:456`), not built.

**Evaluation and the gold set.**

- `fn-gold [CASES]` runs `data/gold/gold-set.json` (28 cases), stores each run as a normal search and writes `var/gold/<timestamp>/report.md` and `top5.csv` (`notes/mvp0/architecture.md:305`).
- Per pick it prints found (top 10 of its section), event page, missed or "no lane in slice", the lanes behind it, the gold tie next to the Belgian claims, and for a miss the step and reason (`notes/mvp0/architecture.md:44`, `:305`, `:124`).
- `data/gold/reach.json` records which picks a lane can reach; the dev measure is 3 of the 4 reachable GS-10 picks in the top 10 (`notes/mvp0/architecture.md:46`).
- Dev cases are GS-02 and GS-10; held-out cases GS-15, GS-16, GS-23, GS-24 and GS-28 are reported, not targeted (`notes/mvp0/architecture.md:46`).
- A pick found only on the case's own event page gets the label `event page` and counts as not found (`notes/mvp0/architecture.md:307`).
- Replay: `FN_LLM=replay FN_HTTP=replay` repeats a gold run without network; fn-gold runs with `FN_LLM=prefer` so the 28 parse fixtures give the same chips (`notes/mvp0/plan.md:12`, `notes/mvp0/architecture.md:276`).
- Latest recorded result: 3 of 99 picks found on both sides, dev measure 3 of 4 met, GS-02 target not met (`notes/mvp0/progress.md:30-31`).
- Research benchmark (arms A to E, bootstrap intervals, precision@5 by human review, citation accuracy target 100%) is a plan for the full MVP, not part of the slice (`notes/research/mvp-tech-reference.md:240-297`, `:270-278`).

## 7. Open questions and deferred items

**Open.**

- Whether CSV rows from a newer file update people or add them (`notes/design/story-map.md:109`).
- Whether to build the flows listed as "may be missing": list and filter the network, look up one person, edit by hand, remove someone, merge inside the network (`notes/design/story-map.md:102-110`).
- Contact details: the research doc puts them out of the MVP and notes the europarl email field is ignored (`notes/research/mvp-tech-reference.md:525`), and the story map's import columns include `email` and `phone` and say a new contact field is needed first (`notes/design/story-map.md:127-128`, `:137`). The documents do not reconcile the two.
- The web search backend: the benchmark was to decide it; the slice used Parallel without the benchmark (`notes/research/mvp-tech-reference.md:5`, `notes/mvp0/architecture.md:237`).
- Five gaps nobody has researched: KBO director listings, the delegation's LinkedIn posts, Instagram for creative asks, Google SERP resellers, a company-list source (`notes/research/mvp-tech-reference.md:48`).
- Nobody measured whether Instant meets p50 under 2 s, or whether Dutch query rows add recall (`notes/research/mvp-tech-reference.md:481`, `:510`).
- The design brief says the "page set is still open" in its intro and "Nothing" open at the end (`notes/design/decisions.md:3`, `:68`).

**Deferred or not doing (slice).**

| Item | Source |
| --- | --- |
| FN's own page reader; Add, Skip, Merge, the list page, export, import of the old sheet, login, depths beyond Quick, DBOS, embeddings, step replay, payload purging | `notes/mvp0/architecture.md:48`, `:388-393` |
| Tie badge or filter; they come with the list page and are computed from claims | `notes/mvp0/architecture.md:396` |
| Weighting Flanders above Wallonia or by language | `notes/mvp0/architecture.md:395` |
| Place-of-birth lookups and org facts for companies | `notes/mvp0/architecture.md:397` |
| Paging the results page (the MIT search renders 387 candidates in 5.9 MB) | `notes/mvp0/architecture.md:398` |
| Calling Parallel or Haiku concurrently; up to about 30 Haiku calls in a row per web search | `notes/mvp0/architecture.md:400` |
| A cut in `rank.py`; a spend limit across searches | `notes/mvp0/architecture.md:402-403` |
| Moving the OpenAlex place ordering into the ranker | `notes/mvp0/architecture.md:405` |
| Dropping the Belgian filters from OpenAlex queries | `notes/mvp0/architecture.md:406` |
| Turning a vendor refusal into a note | `notes/mvp0/architecture.md:408` |
| Location claims from LinkedIn profiles; a second Apify run by past Belgian employer | `notes/mvp0/architecture.md:401` |
| Catching other pages about the same event | `notes/mvp0/architecture.md:407` |
| Dark theme, logo, tagline, React components | `notes/design/plan.md:142` |
| Excel import (needs openpyxl) | `notes/design/story-map.md:139` |
| A mapping step that guesses columns | `notes/design/story-map.md:120` |
| Research design pieces: depths Extended and Deep, FRIS, SEC EDGAR, iTunes, Staatsblad lanes, embeddings | `notes/research/mvp-tech-reference.md:136-160`, `:517-547` |

**Known defects the documents state.**

- `geo.py` keeps one city per name worldwide, the most populous, and ignores state and country; "Bay Area" resolves to Bay in the Philippines (`notes/design/story-map.md:5`, `:44-45`, `:137`). The 307-of-2,947 figure is at `notes/design/story-map.md:137`.
- Live, the web lane took 190 s and LinkedIn 178 s on one gold case, and results appear only when every lane is done (`notes/design/story-map.md:39`).
- A seed person that OpenAlex finds always gets a second record, because seed rows carry no OpenAlex id (`notes/design/story-map.md:66`).
- 17 of the 28 stored gold searches return more than 700 people (`notes/design/story-map.md:41`).

## 8. Privacy and data rules

- **Public repo.** The documents never say the repo is public. The User-Agent names `https://github.com/arendcolle/FN` (`notes/mvp0/architecture.md:260`). The architecture tracks the seed text layers (`data/seeds/raw/**/*.txt`, 2.1 MB) because sources and the offset test read them, and ignores the raw HTML and PDF copies (`notes/mvp0/architecture.md:178`). Extract fixtures are ignored so a record run cannot commit real page text (`notes/mvp0/architecture.md:276`).
- **Local only.** The app runs on 127.0.0.1, `var/` is mode 0700 and gitignored, the database uses `secure_delete=ON`, and the app has no network exposure (`notes/mvp0/architecture.md:178`, `:295`, `:373`).
- **Secrets.** Keys come from env vars or the macOS Keychain, never a file, and `redact()` scrubs them from every record (`notes/mvp0/architecture.md:173`, `notes/research/mvp-tech-reference.md:14`).
- **Prompt injection.** Page text goes to the LLM as tagged data, and a value that holds its own closing tag raises `TagError` (`notes/mvp0/architecture.md:174`).
- **Personal data in third-party queries.** Perplexity's Search Addendum 2.3 bars personal data in queries. The owner's rule is that a personal proof of concept is not gated by vendor terms, and Perplexity may receive names (`notes/research/mvp-tech-reference.md:13`, `:98`).
- **Terms for a product.** Parallel, Exa and Perplexity storage terms, Flemish press reservations and GDPR would apply again if FN becomes a product (`notes/research/mvp-tech-reference.md:98`, `:495`). The documents give no GDPR analysis.
- **Staatsblad lookups.** The research design keeps only the municipality and removes register numbers, birth dates and street addresses (`notes/research/mvp-tech-reference.md:125`).
- **Contact details.** Out of the MVP in the research doc (`notes/research/mvp-tech-reference.md:525`); the story map adds email and phone to the import (`notes/design/story-map.md:127-128`).
- **Attribution owed.** GeoNames (CC BY 4.0), Onomaverse (CC BY 4.0), OpenStreetMap on the map (ODbL), Wiktionary (CC BY-SA) if used (`notes/research/mvp-tech-reference.md:495`).
- **Retention.** Payload purging is not built; payloads sit in their own table so it can be added (`notes/mvp0/architecture.md:393`). Skipped and removed people: the documents say Skip writes a decision and merge deletes nothing, with no deletion rule for a person (`notes/research/mvp-tech-reference.md:133`).
- **Scraping stance.** FN reads LinkedIn only through Apify and never logs in; it does not retry a refused page (`notes/research/mvp-tech-reference.md:30`, `:59`).

## Where the documents disagree with each other or with the code

- `notes/mvp0/architecture.md:297` says the style is the browser default; this worktree already ships `tokens.css` and a restyled `fn.css` (`src/fn/web/static/fn.css:7`).
- `notes/mvp0/plan.md:28` plans `data/ties.csv` and `ties.py`; version 3.0 removed the tie label (`notes/mvp0/architecture.md:11`).
- `notes/research/mvp-tech-reference.md:116` says FN fetches every page itself; the 2026-11-04 decision reverses it (`:58`).
- `notes/mvp0/architecture.md:3` calls itself version 3.2 but several lines still describe the earlier counts (`:93` says 121 spellings and 65 ids, the progress log says 116 and 63 at `notes/mvp0/progress.md:13`).
