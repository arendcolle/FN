# Keep every OpenAlex author and let the ranker order them

2026-11-05 · build plan for one change to the OpenAlex lane, after the owner's rule that lanes only provide input and the ranker owns ranking and cutting

**TL;DR.** The OpenAlex lane drops every author whose record has no Belgian affiliation with years (`in_scope`) before the ranker sees them. After this change the lane keeps every author it fetches among the first 2,000 seen (`MAX_AUTHORS`), stores their claims and returns them all as hits. rank.py does not change: an author without a Belgian claim gets no belgian_years part, so reciprocal rank fusion (RRF) already places them below Belgian authors with a similar lane rank. The lane still orders by place group first, so in a case with a located metro area a non-Belgian author inside the radius, or with no known place, ranks in the lane list above a Belgian author outside it. In the last gold run GS-10 dropped no author, so the dev measure should stay at 3 of 4. The other 23 cases with an OpenAlex query dropped 12,319 authors, who now join section `new`. The gold comparison runs both shas on the same recorded vendor answers and the same Haiku answers, so a pick that moves moved because of this change.

## What changes

The lane stops filtering. Everything else in it stays as built.

`lanes/openalex.py`:

- `in_scope` goes. The kept authors are every author among the first 2,000 seen that OpenAlex returned a record for.
- The order stays place group, then the order seen. The lane does not order by Belgian evidence, because belgian_years in rank.py does that.
- Each hit's `claim_ids` keep today's rule, the Belgian affiliation claims plus the location claim. An author with no Belgian affiliation has the location claim or nothing.
- A kept author's `considered` row says `Belgian affiliations none` when there are none. Two drop reasons stay, "not fetched: beyond the first 2000 authors seen" and "no author record returned". The reason "no Belgian affiliation in the OpenAlex record" goes.
- The log line keeps the count of authors with a Belgian affiliation next to the hit count.
- The module and `run` docstrings say the lane keeps every fetched author.

`rank.py` does not change. `belgian_list` already leaves out entries with a count of 0, and `fuse` sums the parts an entry has. No cut is added.

Docs: `architecture.md` goes to 3.2. The TL;DR, Ranking, the Lanes intro, the OpenAlex lane bullet and the responsibility table say the lane keeps every fetched author, and the Not doing line about `in_scope` goes. `progress.md` gets one line, and this plan gets the comparison result.

## What the last gold run predicts

The 2026-11-04 branch run (`fn-branch-gold`, sha dfb4361) stored every lane's `considered` rows, so the effect can be counted before building.

| Cases | OpenAlex hits | Dropped for no Belgian affiliation | Not fetched |
| --- | --- | --- | --- |
| GS-10 | 359 | 0 | 0 |
| GS-02 | 327 | 666 | 0 |
| GS-24 | 340 | 1,660 | 419 |
| all 24 cases with a query | 10,892 | 12,319 | 419 |

GS-10's query is the MIT author list with `affiliations.institution.country_code:BE`, so every author it sees already has a Belgian affiliation, and all 359 have years. Its OpenAlex list should not change.

Topic cases change. A non-Belgian author first in the lane's list scores 1/61 = 0.0164. A Belgian author at OpenAlex #100 and belgian_years #50 scores 1/160 + 1/110 = 0.0153. So the first non-Belgian authors seen can rank above Belgian ones in a topic case's top 10, and Belgian authors' OpenAlex ranks grow as non-Belgian authors fill the places between them. Place group comes before the order seen, which widens this. In GS-02, 272 of the 327 Belgian hits sit outside the New York radius, and at least 104 of the 666 dropped authors sit inside it or have no known place, so those 104 rank above the 272 in the lane list. 17 of the 23 cases that change have a located metro area. That follows the owner's rule, and the comparison measures it as the number of top-10 cards with belgian_years 0 per case.

## Test updates that need the owner's OK

One existing test asserts the cut this change removes.

| Test | Today | After |
| --- | --- | --- |
| `tests/test_openalex.py:143-158`, `test_author_without_a_belgian_affiliation_is_dropped_with_that_reason` | Klein's record has no Belgian affiliation. His `considered` row is stage `record`, not kept, "no Belgian affiliation in the OpenAlex record"; `out.hits` is empty; no person is stored | renamed `..._is_kept_as_a_hit`: his row is stage `rank`, kept, and names `Belgian affiliations none`; he is the one hit; one person is stored with his affiliation claims |

The owner approved this rewrite on 2026-11-05. The build runs the whole suite after the lane change. Any other assertion that fails goes into this table and waits for the OK too.

## New test

One test in `test_openalex.py` runs a whole search with three authors on one work, seen in this order:

1. one with only an MIT affiliation;
2. one with KU Leuven 2020;
3. one with a KU Leuven affiliation without years and no last known institution.

It asserts that the lane ranks all three in the order seen (1, 2, 3), that all three are candidates, that the second ranks first among the candidates, and that only the second has a belgian_years part. The third has no claims and `place unknown`. The test fails today, because the lane drops the first and the third. It is run against the old lane before the change to see it fail.

## Inputs the spec does not mention

| Input | Behaviour | Test |
| --- | --- | --- |
| An author with only non-Belgian affiliations | kept, with those affiliation claims; no belgian_years part | the Klein test, the new test |
| A Belgian affiliation without years | kept; no claim, because claims need years; `Belgian affiliations none` | the new test |
| No affiliations and no last known institution | kept with no claims, `place unknown`, empty `claim_ids` | the new test |
| More than 2,000 authors seen (GS-24 sees 2,419) | the first 2,000 with a record are hits; the rest are dropped "not fetched" as today | unchanged code, no new test |
| An author record OpenAlex does not return | dropped "no author record returned" as today | the Janjevic test |
| A non-Belgian author with the group key of a seed or web person | one card with a flag; belgian_years counts hit records only, as today | the resolve and rank tests |
| A search with 2,000 OpenAlex hits | about 30 MB of results HTML, the architecture's estimate; paging stays out of scope | the gold run reports candidate counts |

## Responsibility table

Only one row's wording changes, and no owner moves.

| Responsibility | Owner |
| --- | --- |
| Which of the people a lane finds it keeps (the seed top 100, the first 2,000 OpenAlex authors with a record, everyone for web and LinkedIn) | each lane, under Lanes |
| The order of a lane's own hits (bm25 for seeds, place group then order seen for OpenAlex, page order for web, actor order for LinkedIn) | each lane, under Lanes |
| Turning claims into ranked lists, fusing the lanes' lists, sections, ordering entries and any cut of the fused list (none yet) | `rank.py` |

## Gold comparison

The comparison holds every input fixed except the code. OpenAlex and Parallel answers come from one response cache, and Haiku's extract answers from one set of fixtures, on both sides.

1. **Worktrees.** `fn-scope-base` is detached at 31c0750, the branch tip this change starts from. `fn-scope-new` is detached at the final sha. Each gets `uv sync`, copies of `data/gold/`, `data/seeds/*.jsonl`, `data/seeds/raw/` and `tests/fixtures/http/openalex/`, and a fresh `var/` whose `cache` is copied from `fn-branch-gold`. That cache holds the 2026-11-04 run's OpenAlex, Parallel, ROR, Wikidata and GeoNames answers and GS-02's Apify run. Then `fn-seed` runs, and `fn-orgs` with `FN_HTTP=replay`.
2. **Harness.** `gold_harness.py` sits in the scratchpad and runs `fn.gold.main` unchanged. It changes inputs only, and both sides use the same file:
   - every HTTP call in cache mode `refresh`, which is every GET and the Parallel POSTs, reads the response cache first (`prefer`). A call neither run made before goes out live and is cached. The LinkedIn lane's `only` stays, so it serves GS-02's recorded run and never calls Apify;
   - with `FN_LLM=prefer`, an LLM answer with no fixture is fetched live and written as a fixture. Extract fixtures are already gitignored. Parse answers come from the 28 tracked fixtures on both sides.
3. **Runs.** Base runs first, all 28 cases: `FN_LLM=prefer uv run python gold_harness.py`. Its Haiku answers become extract fixtures. The new side then gets copies of base's `var/cache` and extract fixtures, so its web lane reads the same pages and names the same people. It runs with `FN_LLM=replay`, so an extract call that failed on base fails the same way with `FixtureMissing`, which extract.py records per chunk.
4. **Report.** A scratchpad script reads both reports and databases and prints per case: each pick's verdict, section, rank and lanes; seed, web and OpenAlex hits; candidates; top-10 cards with belgian_years 0; vendor and LLM cost; HTTP calls not served from the cache. For every pick whose rank or verdict changed it prints the score parts on both sides and how many candidates share its exact score, because equal scores fall back to the order of person ids, which are random uuids.

Inputs the harness cannot hold fixed: the new side's institution batches list different ids, so they miss the cache and are fetched live (base made 46 such calls). An institution record that changed in OpenAlex since 2026-11-04 can move an author between place groups. ORCID identity can join two OpenAlex ids into one person, and with more authors stored that depends on which case ran first; the review found two such pairs, neither in GS-10.

Base starts from new Haiku answers, so its web lane can differ from the 2026-11-04 run. The report first compares base with that run (3 of 99 found; GS-10 Goemans #1, Janjevic #9, de Wit #10; dev measure 3 of 4), then the new side with base.

Base takes about as long as the last run's web lane, a median 186 s per case and about 90 minutes in all, on the owner's subscription. The new side reads every Haiku answer from fixtures. Vendor spend should stay under $0.01: the OpenAlex calls the cache lacks.

## Done check

1. `uv run python -m unittest` passes, with every failure named if not.
2. The new test fails on the old lane and passes on the new one.
3. The gold comparison above. The dev measure is 3 or more of 4 on the new side. If it drops below 3, the report says so and proposes the ranker change that would restore it, and nothing is tuned. Every pick that moved is named with its score parts on both sides.
4. `architecture.md` and `progress.md` describe what is built.

## Not doing

- A cut in rank.py. Nothing asks for one yet, and the comparison's top-10 count gives the owner the numbers to decide.
- Ordering OpenAlex hits by Belgian evidence inside the lane. That is ranking, and rank.py owns it through belgian_years.
- Moving place ordering out of the lane. Ordering by place is ranking too, but the lane has owned it since architecture 2.3, and moving it is its own change with its own gold comparison.
- Changing the OpenAlex queries. The works filter `institutions.country_code:BE` and the author-list filter `affiliations.institution.country_code:BE` decide which authors the lane sees, not which it keeps, and reach.json was recorded with them. Each lane narrows its query and keeps what comes back: the web lane's objective asks for a connection to Belgium, and the LinkedIn lane filters on nine Belgian schools. Without the filter the MIT author list would run past the 4 pages of 200 the lane reads, while the picks sit at positions 157 to 190 on page 1 and 47 on page 2 of the filtered list.
- Raising or removing `MAX_AUTHORS`.
- Storing affiliations without years as claims. The Dates rule needs a year or an undated unit, and OpenAlex lists no date for them.
- Changing which claims a hit names as its reason.
- Paging the results page.
- Updating reach.json or the gold set.

## Plan review (2026-11-05)

A fresh Opus review said "build after fixes". It applied the change to a scratch copy, where the suite failed only the Klein test, and ran the new test against both lanes. Taken in: the place-group effect above, the order assertion in the new test, `FN_LLM=replay` on the new side, the exact cache-mode wording, tie sizes and uncached calls in the comparison, the query-filter argument and the hit-order row. Declined:

- Copying `data/org_aliases.csv` to the gold worktrees. `git ls-files data` lists it, so every checkout has it.
- The card text "No Belgian organization found in no source" for a hit without claims. A LinkedIn profile without entries shows it today, so this change does not add it.
- The map plotting non-Belgian authors' last known institutions, and the lane's own Belgian check next to `orgs.belgian_claims`. Both stay as they are; the lane's check now only picks reason claims and feeds a log count.

## Result (2026-11-06)

The suite passes with 264 tests. The new test failed on the old lane, which kept 1 of its 3 authors, and passes on the new one.

Base at 31c0750 reproduces the 2026-11-04 run: 3 of 99 picks found, the same three GS-10 picks at #1, #9 and #10, and the dev measure at 3 of 4. Its fresh Haiku answers moved 8 missed picks by a few places.

The new side at 36e3d7e ran on the same vendor and Haiku answers as base. Web hits and LLM cost are equal in all 28 cases.

- Found: 3 of 99 on both sides, the same picks. The dev measure stays at 3 of 4.
- OpenAlex hits: 10,892 to 23,211, the 12,319 the plan predicted. GS-10 keeps its 359. Candidates: 13,359 to 25,638.
- Top 10: no case has a card without a Belgian claim, on either side. The best non-Belgian OpenAlex-only card in GS-02 ranks #80, at OpenAlex #3.
- Spend: 98 OpenAlex institution batches missed the cache and ran live, for $0.0098. No Parallel, Apify or Haiku call ran.
- The largest results page, GS-24 with 2,132 candidates, grew from 3.6 MB to 13.7 MB and renders in 1.0 s.

Ten picks moved, none into or out of the top 10:

| Case | Pick | Base | New | Why |
| --- | --- | --- | --- | --- |
| GS-10 | Goemans | found #1 (seeds #1) | found #2 (seeds #2) | seed rank, see below |
| GS-10 | de Wit | found #10 (seeds #37) | found #9 (seeds #34) | seed rank |
| GS-10 | Janjevic | found #9 (seeds #72) | found #10 (seeds #71) | seed rank; her score rose too, but de Wit's rose more |
| GS-29 | Luc M. Martens | missed #118 (openalex #90) | missed #143 (openalex #121) | 31 non-Belgian authors now sit above him in the OpenAlex list |
| GS-02 | Vetter | missed #134 | missed #102 | parts unchanged (web #6); Belgian OpenAlex authors above him lost points |
| GS-15 | James Braun | missed #151 | missed #120 | the same, with seeds #37 to #38 |
| GS-21 | Brandon Wen | missed #154 | missed #136 | the same (web #18) |
| GS-21 | Julie Kegels | missed #445 | missed #408 | the same (web #80) |
| GS-28 | Hans Bruyninckx | missed #148 | missed #105 | the same, with seeds #34 to #35 |
| GS-28 | Kevin Reed | missed #68 | missed #41 | the same (web #4) |

For Reed and Vetter this was checked candidate by candidate: the 30 and 35 candidates that fell below them are all Belgian OpenAlex authors whose OpenAlex rank grew.

The GS-10 moves do not come from its own OpenAlex list, which is unchanged. They come from the seed lane. `store.match_claims` scores bm25 over the whole claims index and drops excluded source kinds afterwards, so every stored claim counts toward the term statistics. Both sides hold the same 11,840 seed and page claims. The new side stored 263,096 OpenAlex record claims against base's 139,379, and that alone swaps Goemans and another seed person at seed #1 and #2 for the MIT query.
