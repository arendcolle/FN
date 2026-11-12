# Ranking research

## TL;DR

The ranker sums 1 / (60 + rank) over lanes whose ranks mean unrelated things, adds Belgian years from the hit records only, and never reads the question's chips. The top 20 is 69% people only OpenAlex found. In the 19 searches with a located place, 42% of top-20 people have a known place outside the 100 km radius, mostly in Belgium. Only 32% of top-20 cards hold a claim that names a topic word. Ranking can only help 13 of the 83 gold picks, because the other 70 never reach the ranker. Replayed on stored data without live calls, an evidence-first order raises gold picks in the top 10 from 2 to 4 and in the top 50 from 4 to 6. That order drops stop words from the seed query, counts evidence over every record of an entry, adds topic, place and seed-list parts, ranks people with topic and tie evidence first and known-outside places last, and cuts weak OpenAlex-only people. It also cuts the median kept list from 510 to 417 people and known-outside places in the top 20 from 42% to 2%. The cost: more top-20 cards say "location not found" (43% to 78%), because the lanes find few people with a known place in the question's city. Show 20 cards per page. A model rerank step is not worth building until OpenAlex stores topic claims and a labelled top-20 set exists.

## How the numbers were made

- Scripts and outputs are in the scratchpad folder `quality/ranking/`, not in the repository. `features.py` copies the owner's database with the SQLite backup API from a read-only connection and works on the copy. It then replays `resolve.run` and `rank.fuse` from each search's stored lane outputs (`step_payloads`). `evaluate.py` scores each variant. No live call, no write to `var/fn.sqlite3`.
- 25 finished searches have candidates. 24 of them are gold cases with 83 picks. The 26th search with results, e4caaf4e, is not a gold case.
- "Today" means the replay of the current code on the current data. It differs slightly from the stored rows: the stored rows give 3 picks in the top 10, the replay 2. Two picks at 9 and 10 in the stored rows are at 7 and 11 in the replay.
- Gold picks match a candidate as `scripts/gold/cut_gate.py` does: by the pinned OpenAlex id from reach.json, else by group key.
- Topic word: a word of a topic chip after dropping stop words and generic words ("research", "science", "university", "US", "tech"). Matching is case-insensitive at a word start, with a trailing "s" dropped and "AI" also matching "artificial intelligence" and "machine learning".
- Place: `geo.locate` on the cached GeoNames file, radius 100 km (`geo.METRO_RADIUS_KM`). An entry is inside when any location claim of any of its records lies within the radius. It is outside when it has located claims and none lies within the radius, and unknown when it has none.
- Tie evidence: a seed-list claim, a claim at an org with country BE, a claim whose text names Belgium, Flanders or a Belgian city, or a location claim in Belgium. Strong tie: a seed-list claim or 3 or more Belgian years.

## Findings

### 1. What decides order and cut today

- Score is the sum of 1 / (60 + lane rank) per lane, plus a belgian_years part ranked by Belgian years (`src/fn/rank.py:20`, `:90-98`, `:67-87`). Ties break on person id.
- belgian_years counts claims of the hit records only (`rank.py:76`). An entry also holds same-name records that no lane hit, and their claims are neither scored nor shown. The card also reads hit records only (`src/fn/present.py:272`). In e4caaf4e, 46 of the 510 shown entries hold more than one record.
- `RankIn` carries the chips (`src/fn/contracts.py:667-669`) and `rank.run` never reads them (`rank.py:134-139`). Topic and place play no part in rank.
- The only cut is `no_belgian_evidence`: a new-section entry that only OpenAlex found and that has no belgian_years part (`rank.py:101-106`). It cuts a median 55.8% of candidates (cut_gate run on the stored rows: median total 1,154, kept 510).
- Each lane rank means something different, yet RRF weighs rank 1 of every lane the same (1/61):
  - Seeds: bm25 over every word of every topic and institution chip, ORed, stop words included, first 100 people (`src/fn/lanes/seeds.py:17`, `:27-34`, `:44`).
  - OpenAlex: place group of the last known institution (inside, unknown, outside), then the order the author was first seen: institution lists, then the authors of page 1 of Belgian works per topic (`src/fn/lanes/openalex.py:237`). The hit score counts works and lists but "orders nothing" (`openalex.py:211`). A median of 993 OpenAlex hits per search; 359 of them (36%) have a Belgian affiliation (lane payloads, 25 searches).
  - Web: the page's place in Parallel's results, then the order people are named on it (`src/fn/lanes/web.py:102`).
- Two lanes that agree double the score, but only 13% of top-20 entries come from more than one lane.
- The results page shows 50 cards per step (`present.py:45`, `RESULTS_STEP`).

### 2. Gold picks today

| Measure | Stored rows | Replay today |
|---|---|---|
| Picks in the 24 gold cases with results | 83 | 83 |
| Picks that reach the ranker | 12 | 13 |
| Picks kept | 12 | 12 |
| In the top 10 / 20 / 50 | 3 / 3 / 4 | 2 / 3 / 4 |
| Median position of kept picks | 118.5 | 111.5 |

Recall over the 13 picks that reach the ranker is 15% at 10, 23% at 20 and 31% at 50 in the replay. Over all 83 picks it is 2%, 4% and 5%. 70 of 83 picks never reach the ranker. That is a lane and record problem, and no ranker can fix it. 8 of the 13 reached picks come from two cases (GS-10, GS-28), so a change of one pick is within noise.

### 3. Noise in the top 20

The table counts the 500 top-20 slots of the 25 searches (380 slots in the 19 searches with a located place).

| Signal | Share of top-20 slots |
|---|---|
| Only OpenAlex found them | 69% |
| Only seeds / only web | 16% / 2% |
| More than one lane | 13% |
| A claim names a topic word | 32% |
| Topic word or OpenAlex works-on-topic signal | 95% |
| Tie evidence / strong tie | 99% / 96% |
| Place inside / outside / unknown (located searches) | 9% / 42% / 49% |
| Card says "location not found" (hit records) | 43% |
| No place on any record of the entry | 41% |
| Distinct sources per card | 1.95 |

The biggest noise classes, by top-20 slots:

1. Known place outside the radius: 158 slots. Pattern: an OpenAlex author whose last known institution is a Belgian university. In e4caaf4e, 9 of the top 20 are 5,260 to 5,610 km from Boston.
2. No claim names the topic: 340 slots (68%). Pattern: an OpenAlex co-author of a Belgian work that matched the topic. The lane stores affiliation and location claims only, so the card cannot say why the person fits the topic.
3. Seed hits on stop words or generic words: 18 top-20 slots, but 488 of 1,664 seed hits (29%) across the 25 searches. In two searches all 100 seed hits are noise: a telecom question whose seed hits matched only "research", and a founders question whose hits matched only "to", "the" or "US". In e4caaf4e my matcher finds 53 of 100. The earlier count of 54 matched only "in".
4. Weak OpenAlex-only people (no topic claim, at most 2 Belgian years or none since 2016, place not inside): 21 slots.
5. Web-only people with no tie evidence: 4 slots.
6. Duplicates: 0 top-20 slots share a last name and a first initial. Across all 13,889 kept entries, 115 groups do, and 9 have one member in a top 20. The 3 groups in e4caaf4e are all two OpenAlex records, one with an initial and one with a full first name. I did not find the seed-versus-OpenAlex duplicate the owner saw with this test. The resolve research owns that question.

Merging records alone does not fix "location not found" in the top 20: counting every record of the entry lowers it from 43% to 41%. Seed records carry no location claim, and OpenAlex last-known institutions often lack coordinates.

### 4. Experiments on stored data

Columns: gold picks kept (of 13), picks in the top 10, 20 and 50, the median position of kept picks, the median kept people per search, then top-20 shares: topic claim, OpenAlex-only, known-outside place (located searches) and "location not found". The last two columns count top-20 slots with seed-noise hits and with weak OpenAlex-only people. Median position is not comparable across rows that keep different picks.

| Variant | Kept | @10 | @20 | @50 | Med pos | Med kept | Topic | OA only | Outside | No place | Seed noise | Weak OA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Today | 12 | 2 | 3 | 4 | 111.5 | 510 | 32% | 69% | 42% | 43% | 18 | 21 |
| Seed lane without stop words | 11 | 2 | 3 | 4 | 81 | 481 | 32% | 70% | 42% | 41% | 11 | 22 |
| Seed lane, words ANDed per chip | 13 | 2 | 3 | 4 | 92 | 446 | 26% | 81% | 47% | 36% | 3 | 31 |
| Topic part (RRF list by matched words) | 12 | 2 | 3 | 5 | 79 | 510 | 86% | 28% | 30% | 60% | 6 | 0 |
| Place part (inside, by distance) | 12 | 3 | 3 | 4 | 112 | 510 | 32% | 70% | 40% | 42% | 17 | 21 |
| Seed-list prior (1/61) | 12 | 3 | 3 | 4 | 70.5 | 510 | 51% | 32% | 37% | 65% | 70 | 14 |
| At most 5 OpenAlex-only in top 20 | 12 | 2 | 3 | 4 | 111.5 | 510 | 49% | 25% | 26% | 71% | 48 | 3 |
| Topic and tie evidence first | 12 | 2 | 3 | 3 | 122.5 | 510 | 32% | 74% | 44% | 39% | 0 | 24 |
| Cut weak OpenAlex-only | 12 | 2 | 3 | 4 | 106 | 405 | 34% | 67% | 43% | 41% | 21 | 0 |
| Belgian years over all records | 12 | 1 | 3 | 4 | 98 | 510 | 39% | 55% | 57% | 54% | 33 | 23 |
| Known-outside place last | 12 | 3 | 4 | 4 | 73.5 | 510 | 35% | 60% | 0% | 69% | 27 | 38 |
| Recommended (below) | 13 | 4 | 4 | 6 | 88 | 417 | 68% | 36% | 2% | 78% | 0 | 0 |
| Recommended, then cut entries without evidence | 9 | 3 | 4 | 5 | 31 | 329 | 73% | 30% | 53% | 61% | 0 | 0 |

The recommended variant combines these steps:

- Seed lane without stop words or generic words, first 300 hits instead of 100.
- Score: today's lane parts, plus belgian_years over every record, plus a topic part, a place part and a seed-list prior.
- Order: people with tie evidence and a topic match first. A topic match covers at least half of one chip's words, comes from an OpenAlex works-on-topic hit, or matches an institution chip. People with weaker evidence follow, then people with neither. Within each group, a known-outside place goes last.
- Cut weak OpenAlex-only people.

The 300-hit cap matters: with the 100 cap, dropping "science" from a climate question pushes a gold seed pick past rank 100, and it is lost.

Per pick, the recommended order moves picks up as follows: 237 to 9, 201 to 42, 144 to 35, 129 to 95, 383 to 137, 11 to 6 and 7 to 4. Three picks fall. A web-only pick with no machine-readable tie falls from 38 to 620. A pick whose only place is a Belgian city falls from 126 to 421 when the event is in the Bay Area. A web-only pick with no topic or tie claim falls from 97 to 301. The last row loses 4 picks. Two are web-only picks that the evidence cut removes. The other two are seed picks lost to the 100-hit seed cap. So evidence must order, not cut.

What I could not simulate:

- New lane calls: work titles as OpenAlex topic claims, a place lookup for seed people, more pages.
- Changes to resolve beyond replaying it.
- Whether staff judge the new top 20 better. The gold set cannot tell with 13 reachable picks.
- In e4caaf4e, the recommended top 20 holds 7 seed-list people with health, care or AI claims and no known place, 12 OpenAlex authors (2 in Boston, 10 with unknown place) and 1 web hit. Today it holds 9 people placed in Belgium. Whether that is better is a judgement for the owner, not a measurement.

### 5. A model rerank step

The idea: one haiku call reads about 60 compact cards and the question, and returns topic, place and tie grades with supporting claim ids.

- Value. It would catch topic fit that word matching misses (synonyms, "6G" and "wireless"), and it could read a web quote that says "Antwerp-born". But 68% of today's top-20 cards hold no topic claim at all, mostly OpenAlex people, so the model would have nothing to cite for them. Not measured: no labelled set exists to show a gain.
- Cost. Extract calls on the same CLI take a median 10.9 s (p90 21.4 s) with a median 4,383 input tokens (`step_calls`, 19 calls). 60 cards of about 80 tokens each give a similar call (token count estimated, not measured). e4caaf4e took 4 min 17 s, of which the web lane took 3 min 50 s and rank 0.4 s. One rerank call adds about 4 to 8% to a search.
- Testing. `FixtureLLM` replays answers by prompt hash (`src/fn/llm.py:145-176`). A `grade` task with fixtures under `tests/fixtures/llm/` runs in replay mode in CI. The offline evaluator from section 4 can replay recorded grades over stored searches.
- Keeping reasons checked. Each card lists its claim ids. The step drops any cited id not in that card's list, and a grade with no valid id counts as 0. The step stores grades as score parts with claim ids, like belgian_years, so every shown reason is a stored, quoted claim.
- Where it would sit: a step between rank and save that reorders only the first 60 and never adds or removes people.
- Verdict: do not build now. Build the deterministic evidence first. Revisit when OpenAlex stores topic claims and the owner has labelled at least 10 searches' top 20.

## Recommendations

Responsibility table, one owner per row:

| Responsibility | Owner |
|---|---|
| Which chip words to query (stop words, generic words, cap) | `fn/lanes/seeds.py` |
| Store the topic evidence of an OpenAlex author (matching work titles as claims) | `fn/lanes/openalex.py` |
| Group records into entries | `fn/resolve.py` (unchanged) |
| Compute an entry's evidence from every record: topic words and their claim ids, tie kind and Belgian years, place group and distance, source count | new `fn/evidence.py` |
| Order, tiers and cut rules over lane ranks and evidence | `fn/rank.py` |
| Card place and reasons from the same evidence (every record, not hits only) | `fn/present.py` |
| Page size | `fn/present.py` (`RESULTS_STEP`) |
| Offline replay gate over stored searches | new `scripts/gold/rank_eval.py` |

Contracts:

- `evidence.of(entry, claims, facts, chips, area) -> Evidence`. Evidence holds `topic` (matched words and claim ids), `tie` (kind, years and claim ids), `place` (group, km and claim id) and `sources`. It is a pure function, so rank and present call the same code.
- `ScorePart.feature` gains `topic`, `place` and `seed_list`. Each part carries the claim ids that earned it, as belgian_years does.
- `RankOut` candidates gain a `tier` (0 to 2) so the page and the export show the same order.

Cut rules:

- Keep `no_belgian_evidence`.
- Add `weak_openalex`: OpenAlex-only, no topic claim, at most 2 Belgian years or none since 2016, and place not inside. Alone it lowers the median kept list from 510 to 405 and cuts no gold pick.
- Never cut for a missing place or a missing tie on a web hit. Order them lower instead: 5 of the 13 reached gold picks come only from the web lane, and 2 of them have no tie claim.

Default page size: 20 cards with "Show 20 more". The recommended order puts 4 of 13 reachable picks in the top 10 and 4 in the top 20.

Gates that prove an improvement, all run by `scripts/gold/rank_eval.py` on stored payloads with no live calls:

- No reached gold pick is cut. Picks in the top 10 and top 50 never fall below today's replay (2 and 4).
- Median kept people at most today's 510.
- Top-20 census: seed-noise slots 0, weak OpenAlex-only slots 0, known-outside share of located searches at most 10%.
- A labelled set: the owner marks each top-20 card of 10 searches good or noise, and precision at 20 is tracked per change. top5.csv from `fn-gold` has the shape for it.
- One unit test per rule in `rank.py` and `evidence.py`.

## Open decisions

1. Place: should a known place outside the radius order last (recommended, gold +1 at 10), or count for nothing, because gold notes say speakers may travel in? One gold pick falls from 126 to 421 under "order last".
2. Should a seed fellow with a topic claim and no known place outrank an OpenAlex author with a Belgian place for a US event? The recommended order says yes. The owner should judge the e4caaf4e top 20 before this ships.
3. Page size 20, or 10 with the count line? The gold set cannot tell them apart.

## Not measured

- Staff judgement of the new top 20.
- Rank step time with evidence over every record. The whole replay of 25 searches with 4 seed modes took 33 s on this Mac.
- Any effect on searches with a place of kind `anywhere_us`, where `geo.area` locates nothing by design.
