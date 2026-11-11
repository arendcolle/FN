# Lanes, resolver, ranker, place lookup and organization data

Summary. A search runs `parse`, then four lanes in a fixed order (`seeds`, `openalex`, `web`, `linkedin`), then `resolve`, `rank` and `save` (`src/fn/search.py:25-36`, `src/fn/lanes/__init__.py:15`). Each lane turns chips into `LaneHit`s with a rank and stores persons, sources and claims. `resolve` groups hits by name only. `rank` fuses the lane ranks and a Belgian-years list with reciprocal rank fusion (K=60), cuts nothing and ignores the place chip. Only the OpenAlex lane gives a location claim coordinates. LinkedIn is the only lane that is off by default. A lane that raises fails the whole search.

All references are repo-relative and describe the code as it is today.

## 1. The four lanes

### Common frame

| Fact | Where |
|---|---|
| Every lane gets the same `LaneIn` (search id, chips, depth) and returns a `LaneOut` (lane, query text, total_seen, hits, considered) | `src/fn/contracts.py:455-466` |
| A `LaneHit` holds person id, name key, lane, rank, score, `matched_on` text and claim ids | `src/fn/contracts.py:330-337` |
| A `Considered` row is a trace line: person key, name, stage, kept flag, reason | `src/fn/contracts.py:340-345` |
| Each lane runs as one recorded step named `lane:<name>`; the step row keeps cost, tokens, model, log lines and the traceback | `src/fn/search.py:33`, `src/fn/steps.py:137-182` |
| An exception in any lane propagates and marks the whole search failed; there is no per-lane isolation | `src/fn/worker.py:89-94` |
| Only `topics` and `institutions` chips create a query in every lane. `ask` is read by no lane | all four `run` functions |
| `Chips` has topics, institutions, one `Place` and `ask`; `Place.kind` is `metro`, `anywhere_us`, `abroad` or None | `src/fn/contracts.py:96-114` |

### Seeds lane (`src/fn/lanes/seeds.py`)

| Item | Fact |
|---|---|
| Inputs | Topic and institution chips. Place and ask are unused. |
| Query | Every whitespace token of every topic and institution chip, quoted and ORed, plus each institution's alias spellings from `data/org_aliases.csv` as whole quoted phrases (`seeds.py:27-34`, `seeds.py:38`). |
| External calls | None. One local FTS5 query on `claims_fts` over the `value` and `quote` columns, tokenizer `porter unicode61 remove_diacritics 2` (`src/fn/migrations/001_init.sql:122-126`). Cost 0. |
| Reads | Claims from sources of kind other than `record`, `vendor_record`, `vendor_page` (`seeds.py:19`, `src/fn/store.py:305-333`). So only seed pages, pages and imports match. |
| Writes | Nothing. |
| Returns | One hit per person, best claim only. Rank is the position by bm25 (best first, ties by person id). Score is minus bm25. `claim_ids` is that one claim (`seeds.py:44-48`, `store.py:322-326`). |
| Caps | `MAX_HITS = 100` (`seeds.py:17`). People below rank 100 appear in `considered` with `kept=False` (`seeds.py:45-51`). |
| No query | Returns a single `Considered` row "no topic or institution chip" (`seeds.py:39-41`). |
| Place | Not used. |

### OpenAlex lane (`src/fn/lanes/openalex.py`)

| Item | Fact |
|---|---|
| Inputs | Topic chips, institution chips, and the place chip for ordering only. An institution chip needs a ROR id: its `ror:` ref, else the id `data/org_aliases.csv` gives its text; without one the chip is skipped with a `considered` note (`openalex.py:52-55`, `openalex.py:79-82`). |
| Call 1, per institution chip | `GET /authors` with filter `last_known_institutions.ror:<ror>,affiliations.institution.country_code:BE`, 200 per page, up to `MAX_PAGES = 4` pages, fields `id,display_name` (`openalex.py:83-94`). At most 800 authors per chip. A note is added when there are more. |
| Call 2, per topic chip | `GET /works` with `search=<chip>` and `filter=institutions.country_code:BE`, one page of 100 works (`openalex.py:96-102`). Every author on those works is seen. |
| Call 3 | `GET /authors` by id filter in batches of 100 for the first `MAX_AUTHORS = 2000` authors seen (up to 20 calls) (`openalex.py:106-113`, `openalex.py:231`). |
| Call 4 | `GET /institutions` in batches of 100 for the distinct first last-known institution of each fetched author (`openalex.py:233-235`). |
| Call 5 | If the place chip is `metro` or has no kind: `geo.area` downloads the GeoNames cities file once per HTTP client (`openalex.py:183-186`, section 4). |
| Cost | The code sets no price. The HTTP client records `meta.cost_usd` from an OpenAlex response when present (`src/fn/net.py:105-112`). The OpenAlex key is optional (`net.py:33`). |
| Order of authors seen | Institution authors first, then topic authors, so the 2,000 cut drops topic authors first (`openalex.py:77`). |
| Writes, per fetched author | A person with identifiers `openalex` and, if present, `orcid` (`openalex.py:242-244`). A `record` source holding the author record (`openalex.py:121-132`). Org rows for affiliations with years, written with `replace=False`, so a stored row is kept (`openalex.py:135-139`, `openalex.py:246`). One `affiliated_with` claim per affiliation that has years, dated by the years, with `years` listed (`openalex.py:142-159`). One `location` claim (section 5). |
| Hit | Every fetched author is a hit, Belgian or not (`openalex.py:1`, `openalex.py:216-221`). Rank is the position after sorting by (place group, order first seen) (`openalex.py:237`). Score is the count of works plus institution lists the author was found on, and it orders nothing (`openalex.py:211-213`). `claim_ids` are the affiliation claims whose value is a Belgian affiliation name, plus the location claim (`openalex.py:250-253`). |
| Caps | 4 pages per institution chip, 1 page of 100 works per topic chip, 2,000 authors fetched. Authors past 2,000 and authors with no returned record get a `considered` row with `kept=False` (`openalex.py:256-263`). |
| Place use | See section 5. Order only. Nobody is dropped for being far away. |
| Missing client | Raises `RuntimeError` (`openalex.py:225-226`). |

### Web lane (`src/fn/lanes/web.py`, `src/fn/extract.py`)

| Item | Fact |
|---|---|
| Inputs | Topic chips, institution chips, and the place text. |
| Call 1 | One Parallel Search `POST https://api.parallel.ai/v1/search`, mode `fast`, at most 5 queries (`MAX_QUERIES`): one per topic chip with the place text appended, then one per institution chip (`web.py:50-57`, `web.py:125`). The code sets no result count. |
| Call 2 | One Parallel Extract `POST .../v1/extract` over all result URLs: full content up to 12,000 characters per page, 20 s fetch timeout, 90 s HTTP timeout (`web.py:60-64`, `web.py:141-142`). Skipped when Search returns nothing (`web.py:130-132`). |
| Price | $0.001 per `sku_search` and per `sku_extract_excerpts` count in the response `usage`. An unknown SKU gives no cost and a warning (`web.py:30`, `web.py:67-77`). |
| Call 3, per chunk | One LLM call per chunk of at most 6,000 characters of a page, task `extract`, prompt `src/fn/prompts/extract.md`, model `haiku` through the `claude` CLI on the owner's subscription (`extract.py:26`, `extract.py:50-69`, `extract.py:124-146`, `src/fn/llm.py:23`, `llm.py:73-80`). The CLI reports a cost; the gold report labels it "subscription" (`gold.py:314`). A failed chunk is a `considered` row and the next chunk goes on (`extract.py:137-141`). |
| Page text | The first non-empty of Extract full content, Extract excerpts, Search excerpts, stripped of markdown. A page with none is skipped (`web.py:149-164`). |
| Writes | A `vendor_page` source per page (`contracts.py:199-215`). A person per (page URL, name): identifier `mention` = `<url>#<name key>` (`extract.py:72-74`). A `role` claim (the mention's role, else page title, else host). An `affiliation` claim per kept relation, with `org_id` from the alias file, which is None when the alias is unknown. A `location` claim for `born_in` and `lives_in`, without coordinates (`extract.py:156-179`). A claim is dated only by years its quote states (`extract.py:149-154`). |
| Quote checks | A name needs two words and must stand in its quote. A relation quote must lie within 1,500 characters after the mention quote and name its org (or an alias of it). A relation that would be the same claim as an earlier one is dropped (`extract.py:27`, `extract.py:86-121`). |
| Hit | One per person per search, in page order then mention order. Score is `1 / page rank`, and nothing reads it (`web.py:85-107`). |
| Without a Parallel key | The client raises `MissingKey`; the lane returns a note and no hits (`web.py:126-128`, `net.py:34-35`). |
| Place use | Appended to topic queries and to the objective sentence as text. It is not geocoded and its kind is not checked (`web.py:45-46`, `web.py:55-56`). |

### LinkedIn lane (`src/fn/lanes/linkedin.py`)

| Item | Fact |
|---|---|
| Inputs | Topic chips, else institution chips (topics win when both exist), joined with ` OR `, multi-word terms in double quotes, cut to the leading whole terms that fit 300 characters (`linkedin.py:72-88`). Place chip. |
| Call | One Apify actor run `POST .../harvestapi~linkedin-profile-search/run-sync-get-dataset-items`, input: search query, the nine Belgian schools in `SCHOOLS`, locations, `profileScraperMode: Full`, `takePages: 1`, `maxItems: 25` (`linkedin.py:27`, `linkedin.py:38-39`, `linkedin.py:104-107`). Run timeout 240 s, call timeout 290 s, `maxTotalChargeUsd` 0.25. |
| Cost | Estimated, because the actor reports none: $0.10 per search page plus $0.004 per profile, so about $0.20 for 25 profiles (`linkedin.py:30`, `linkedin.py:32-33`, `linkedin.py:124-126`). |
| Cache | Only a response that holds at least one profile with a `linkedinUrl` is cached (`has_profiles`, `linkedin.py:119-121`). |
| Writes | A `vendor_record` source per profile (name, headline, location text, education and experience lines). A person with identifier `profile_url` = canonical LinkedIn URL. One `affiliation` claim per education entry (`studied_at`) and per job (`works_at` if the end date text is "Present", else `worked_at`), with `org_id` from the alias file and years from the entry (`linkedin.py:145-187`, `linkedin.py:199-214`). No location claim. |
| Skipped profiles | No `linkedinUrl`, or a name with fewer than two words (`linkedin.py:201-208`). School spellings that map to no org id are listed in `considered` (`linkedin.py:214`, `linkedin.py:225-227`). |
| Hit | One per profile, rank in the actor's order, score `1 / result rank` (read by nothing) (`linkedin.py:218-219`). |
| Cap | 25 profiles (`maxItems`). |
| Place use | Not distance. The place becomes LinkedIn location names. No place or `anywhere_us` sends "United States". `abroad`, or a place geo.py cannot locate, sends the place text. Otherwise the city label maps through `LOCATIONS` (nine US metros), else the bare city name (`linkedin.py:41-51`, `linkedin.py:91-101`, `linkedin.py:245`). |

## 2. Resolve (`src/fn/resolve.py`)

How records become one card.

- Hits from all lanes are grouped by `group_key(hit.name_key)` (`resolve.py:26`). `name_key` folds accents and case and keeps letters and digits. `group_key` also drops one-character middle tokens, so "a b c" and "a c" group together (`contracts.py:57-71`).
- The order of entries is the order in which lanes list their hits (lane order, then lane rank). Each entry keeps the best rank per lane in `lane_ranks` and the union of the hits' claim ids (`resolve.py:24-29`).
- After grouping, every other stored person with the same group key is added to the entry, from the whole `persons` table, not only this search's hits (`resolve.py:33-35`, `store.py:335-346`). The hit persons come first in `person_ids`; `hit_person_ids` holds only them (`resolve.py:32`, `contracts.py:355-362`).
- An entry with more than one person gets `flag = "same name in N records, not merged"` (`resolve.py:36`). The ranker then shows it as one card: `person_id` is `person_ids[0]` and `person_ids` lists all (`rank.py:110-111`).
- A `MatchFlag` (person id, other person id, reason, shared fact) is written once per extra person against the first one in the entry. The reason is "same name, no shared identifier" when the name keys are equal, else "same name apart from middle initials, no shared identifier" (`resolve.py:13-14`, `resolve.py:40-41`, `contracts.py:348-352`). `shared_fact` is never set today.
- Flags are stored by `save_candidates`, which deletes and rewrites the search's candidates and flags in one transaction (`store.py:374-392`, table `match_flags` in `src/fn/migrations/001_init.sql:151-158`).
- What is never merged: persons. Two persons merge only inside `Store.resolve_person`, when a lane passes an identifier a stored person already holds (`store.py:218-247`). Identifier schemes are `seed`, `openalex`, `orcid`, `profile_url`, `mention` (`contracts.py:35`). No identifier is shared across lanes, so records from different lanes are never merged. `Person.merged_into` is typed `None` (`contracts.py:259-264`). An identifier held by another person stays with that person (`store.py:222`, `store.py:244-246`).

## 3. Rank (`src/fn/rank.py`)

### Scoring

- Two kinds of list, one reciprocal rank fusion with `K = 60` (`rank.py:19`).
- Lane lists: each lane that ranked the entry gives a part worth `1 / (60 + rank)`, where rank is the entry's best rank in that lane (`rank.py:84-88`).
- The `belgian_years` list: for each entry, the count of distinct year units over the claims at Belgian organizations. Entries with a count above zero are sorted by count, descending. Equal counts share a rank (1, 2, 2, 4), and the part is worth `1 / (60 + rank)` (`rank.py:61-81`).
- A claim covers its `years` list, else each year from `valid_from` to `valid_to`, else the years of `valid_from`, `valid_to` and `claim_date`, else the unit `undated` (`rank.py:28-40`). `undated` counts as one unit.
- Belgian means the claim's org row has `country_code = BE`. Any claim kind and relation counts. A claim without `org_id`, or whose org has no stored row, never counts (`orgs.py:83-88`).
- The Belgian claims come from `store.claims_of(hit_person_ids)`, which returns every stored claim of those persons, including claims written by earlier searches (`rank.py:121`, `store.py:354-361`).
- The score is `math.fsum` of the parts (`rank.py:91-92`).
- `LaneHit.score` is not read by resolve or rank. Only `LaneHit.rank` counts.
- The place chip is not used: `RankIn` carries `chips`, and `rank.run` never touches it (`rank.py:118-123`).

### Ties, sections, cuts and order

- Sort key: score descending, then `person_ids[0]` ascending. That id is a random UUID, so a tie breaks arbitrarily but the same way every time for stored data (`rank.py:103-104`, `store.py:236`).
- Section `network` if any person in the entry has `list_status = in_list`, else `new` (`rank.py:108`). `rank` counts up separately within each section (`rank.py:105`, `rank.py:109`).
- Nothing is cut or capped in rank. Every entry from resolve becomes a candidate (`rank.py:107-114`). The seeds lane (100) and the OpenAlex lane (2,000) set the practical limits.
- The stored list order is network first, then new, each by rank (`store.py:394-398`). Gold's top five takes the first five of that list (`gold.py:234`).

### Stored per candidate

`candidates` row: search id, `person_id`, `person_ids`, section, rank, score, `lane_ranks`, `reason_claim_ids` and `score_parts` as JSON (`store.py:376-387`, `src/fn/migrations/004_score_parts.sql`). Each `ScorePart` has `feature` (a lane name or `belgian_years`), `rank`, `points`, `claim_ids` (set for `belgian_years` only) and a `detail` string such as "3 years at Belgian organizations; 1 / (60 + 2)" (`contracts.py:365-370`, `rank.py:79-80`).

## 4. Place lookup (`src/fn/geo.py`)

- Data file: the GeoNames `cities15000.zip` (cities with more than 15,000 people), downloaded from `https://download.geonames.org/export/dump/cities15000.zip` through the step's HTTP client, unzipped in memory. It is not stored in the repo (`geo.py:10-11`, `geo.py:51-56`). A test fixture extract is at `tests/fixtures/geo/cities15000-extract.txt`. The download is cached once per client object, so each process downloads it again in live mode, because `get` always calls out (`geo.py:28`, `net.py:179-183`).
- Index: every folded name, ASCII name and ASCII alternate name of a row maps to one `City(label, lat, lon, population)`. The label is `"<name>, <country code>"` (`geo.py:31-48`). A key that is a stopword (`and`, `of`, `the`, `area`, `greater`, `metro`, `us`, `usa` and others) or longer than 4 words is not indexed (`geo.py:15-18`, `geo.py:43`).
- Same-name cities: one city per key. A city's own name beats an alternate name, then the larger population wins (`geo.py:44-47`). State, province and country are not part of the key and are not read from the file for matching.
- Locate: the place text is folded into words, scanned left to right, longest phrase first (up to 4 words), and each hit is a city. If several are found, the most populous wins. The result is a `GeoArea` with place, city label, lat, lon and a fixed radius of 100 km (`geo.py:12`, `geo.py:59-76`, `contracts.py:429-434`). None when no word names a city.
- Kinds: `area()` returns None for no place, or a kind other than None or `metro`, without downloading the file (`geo.py:14`, `geo.py:79-86`).
- Distance: haversine on a 6,371 km sphere (`geo.py:89-93`).
- Callers: `openalex.place_area` (`openalex.py:186`, distance at `openalex.py:201`) and `linkedin.run` (`linkedin.py:245`). Nothing else in `src/` calls it. `rank.py` and `web.py` do not.

## 5. How a location claim gets lat and lon

| Lane | Location claim | Coordinates |
|---|---|---|
| seeds | None written. Seed rows give `role`, `affiliation` and `topic` claims (`src/fn/seedload.py:70-80`) | none |
| openalex | `kind=location`, value "city, region, country" of the author's first last-known institution, dated the day it was read, `date_method=read_date` (`openalex.py:162-176`) | `lat` and `lon` copied from the OpenAlex institution record's `geo` (`openalex.py:175`). None when the institution has no coordinates, and then no claim is written. |
| web | `location` claim with relation `born_in` or `lives_in`, value the org text the model gave (`extract.py:175-176`) | none |
| linkedin | None. The profile's location text is in the source text but no claim quotes it (`linkedin.py:152`) | none |

The map reads only location claims with a date and both coordinates, taking each person's newest by `claim_date` (`src/fn/web/app.py:295-301`). In practice these come from the OpenAlex lane only. The claim is the last known institution, which can be outside Belgium.

How the OpenAlex lane uses the place: `placed()` puts each author in group 0 (inside the 100 km radius, or no usable place chip), group 1 (place chip located but the author has no institution coordinates) or group 2 (outside). The lane sorts by (group, order first seen) (`openalex.py:193-203`, `openalex.py:237`). The reason string is kept in `matched_on` and `considered`.

## 6. Organizations

### What an org row holds

Table `orgs` (`src/fn/migrations/002_orgs.sql:3-11`) and model `Org` (`contracts.py:217-234`): `id`, `name`, `country_code`, `region`, `name_lang`, `source_id`, `fetched_at`. The id is `ror:<id>`, `wikidata:<Q>` or `openalex:<I>`; `ror:` and `wikidata:` ids come from the alias file, `openalex:` ids only from the OpenAlex lane (`contracts.py:46-47`, `openalex.py:58-60`).

| Writer | Fills |
|---|---|
| `fn-orgs` from ROR | `name` (the `ror_display` name), `name_lang`, `country_code` and `region` (country subdivision code) from the first location's GeoNames details (`orgs.py:110-129`) |
| `fn-orgs` from Wikidata | `name` (English label), `country_code` (ISO code of the item's country) only; no region or language (`orgs.py:145-163`) |
| OpenAlex lane | `id`, `name`, `country_code` from the author's affiliations with years; no region; a stored row is kept, not overwritten (`openalex.py:135-139`, `orgs.py:96-107`) |

### Name mapping

`data/org_aliases.csv` has columns `alias,org_id`: 121 data rows, 68 distinct org ids today, of which the ids must match `ror:` or `wikidata:` form (`orgs.py:38-49`). An alias is matched after NFC normalization, case folding and whitespace collapse; a repeated alias raises `ValueError` (`orgs.py:34-35`, `orgs.py:44-47`). Helpers: `org_id(text)`, `ref(text)` (ROR ids only), `names(org)` (all spellings), `ids()` (`orgs.py:63-80`). `data/org_aliases_unmapped.txt` lists 3 strings checked and left out on purpose (`orgs.py:57-60`).

Callers: the parser gives an institution chip its `ref` (`src/fn/parse.py:78`); the seeds lane expands aliases (`seeds.py:38`); LinkedIn, seed loading and web extraction set claim `org_id` (`linkedin.py:182`, `seedload.py:72-76`, `extract.py:178`); the OpenAlex lane finds a ROR id for a chip (`openalex.py:54`).

### The fn-orgs job

`fn-orgs` (`pyproject.toml:16`, `src/fn/orgjob.py`) records one `searches` row of kind `job` with a single `orgs` step over every id in the alias file (`orgjob.py:13-26`). The step fetches each id one by one: ROR v2 `GET https://api.ror.org/v2/organizations/<id>`, or Wikidata `wbgetentities` plus two `wbgetclaims` calls (`orgs.py:166-186`, `orgs.py:189-201`). It overwrites stored rows (`replace=True`). It stops at the first failed fetch with `OrgError` naming the id; orgs before it stay saved. It needs an HTTP client and no LLM. Exit code 0 when the job is done, else 1 (`orgjob.py:29-40`).

## 7. Gold (`src/fn/gold.py`)

- Gold set: `data/gold/gold-set.json`, 28 questions rebuilt from real events, 99 known picks in total. Each pick has a `tie` (`flemish`, `belgian`, `none`, `unverified`). The file's note says "known good" means the person was picked for that event, not that they are the best answer (`gold.py:31`, `gold.py:47-70`).
- `data/gold/reach.json`: written 2026-10-30, 9 picks checked for whether a lane can return them (4 reachable, 5 not), with an OpenAlex id pin for matching (`gold.py:32`, `gold.py:57`).
- Groups: dev = GS-02, GS-10; held-out = GS-15, GS-16, GS-23, GS-24, GS-28; every other case is "other" (`gold.py:33-34`, `gold.py:43-44`).
- What it does: `fn-gold [case ids]` runs each question as a normal search (parse, lanes, resolve, rank, save), then matches each known pick to the candidate list. The match uses the pinned OpenAlex person when the store has it, else the group key of the name; with several candidates the best wins, network first (`gold.py:73-83`, `gold.py:211-217`).
- Verdicts: `found` (candidate rank 10 or better inside its section), `event page` (found, but every reason claim sits on the case's own event page), `no lane in slice` (not found and reach.json says no lane can reach it), `missed` (otherwise) (`gold.py:174-192`). A miss is traced to the step where it was lost: rank, first dropped trace row, last kept row, or the lanes that did not find it (`gold.py:86-101`).
- Metrics printed per run:
  - Per case line: `case search <id> <status>`, then each pick: verdict, section and rank, gold tie, Belgian claims text, lost step and reason (`gold.py:253-257`, `gold.py:358-360`).
  - Summary table per group: cases, picks, found in network, found in new, event page, missed, no lane in slice (`gold.py:276-293`).
  - A dev success measure: reachable dev picks found in the top 10 of their section, target 3 (`DEV_TARGET`) (`gold.py:269-273`, `gold.py:289-290`).
- Files: `var/gold/<timestamp>/report.md` (run header with code sha, dirty flag, LLM and HTTP mode; summary; a picks table per case with HTTP cost and LLM cost) and `top5.csv` (top five cards per case with an empty `good_pick` column for the owner) (`gold.py:296-331`, `gold.py:361-367`).
- Exit code: 0 if every search is done, 1 if one is not, 2 for an unknown case id or for `FN_LINKEDIN=1` with other than exactly one case (`gold.py:337-350`).
- Running without paid calls: set `FN_LLM=replay FN_HTTP=replay`, for example `FN_LLM=replay FN_HTTP=replay uv run fn-gold GS-02`. The LLM then reads `tests/fixtures/llm/<task>-<sha16>.json` (30 fixtures today) and HTTP reads `var/cache/<sha256>.json` (`src/fn/llm.py:146-186`, `src/fn/net.py:116-129`). This reads and writes the real `var/` database, so use `FN_VAR=<other dir>` to keep it apart; `FN_VAR` also moves the cache, so copy the cache there first. In replay a missing LLM fixture raises `FixtureMissing` in the parse step and fails that search; a missing HTTP cache entry raises `CacheMiss` and fails the search in the OpenAlex and web lanes, but the LinkedIn lane catches it (`linkedin.py:252-254`). `FN_ENV=test` refuses to start the real Claude CLI (`llm.py:78-79`). The unit tests need no network: `uv run python -m unittest`.
- Paid calls in a live run: Parallel (Search and Extract, about $0.001 per SKU count), and Apify only with `FN_LINKEDIN=1`. OpenAlex, ROR, Wikidata and GeoNames have no price in the code. The LLM calls use the Claude CLI on the subscription.

## 8. Lanes that are off by default

| Lane | Default | How it is turned on |
|---|---|---|
| seeds | On, local only | Needs seed rows loaded with `fn-seed` (`pyproject.toml:14`) |
| openalex | On; key optional | An `OPENALEX_API_KEY` is sent when set (`net.py:33`, `config.py:71`) |
| web | On; skipped with a note when there is no key | `PARALLEL_API_KEY` from the environment or the macOS Keychain (`config.py:55-59`, `web.py:126-128`) |
| linkedin | Off. It serves only a recorded response; with none, it notes "off" and returns no hits (`linkedin.py:35`, `linkedin.py:250-253`) | `FN_LINKEDIN=1` (`config.py:71`) sets `linkedin_live`: serve a recorded response if one exists, else call Apify live (about $0.20) with `APIFY_TOKEN`; without the token the lane notes that and returns no hits (`linkedin.py:247-256`) |

There is no per-lane enable setting; `LANES` is a fixed list (`lanes/__init__.py:15`). With `FN_HTTP=replay`, LinkedIn with `FN_LINKEDIN=1` notes that no recorded run exists instead of calling out (`linkedin.py:253`).

## Gaps worth knowing

- `LaneHit.score` and `Considered` rows are for the trace only; ranking uses ranks.
- Seeds can hit persons that other lanes also wrote, but seed records have no identifier in common with OpenAlex, LinkedIn or web records, so the same human appears as separate persons grouped by name.
- No lane filters by the place chip; the OpenAlex lane reorders, LinkedIn and web change the query text.
