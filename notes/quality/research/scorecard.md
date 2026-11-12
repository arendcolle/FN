# Scorecard research

## TL;DR

FN has no command that scores a result list. The existing tools each answer one narrow question. `fn-gold` runs the 28 gold questions as new searches and reports where each pick was lost. `cut_gate.py` checks the OpenAlex cut over stored searches. `/debug/stats` shows step times. Nothing counts doubles, card completeness or noise, and nothing compares two code versions. I proved that all three levels of re-run work on a copy of the database: re-score stored candidates (2.4 s for 29 searches), re-run resolve and rank from stored lane outputs (12 s), and replay whole searches with `FN_HTTP=replay FN_LLM=replay` (39 s for 28 searches, two replays identical). Replay of the newest live search does not work, because live mode stores no LLM answers. I wrote a working prototype that computes 20 metrics from the stored database, read-only, and gives a baseline. The baseline says the list is the problem, not the doubles. Gold recall at 20 is 3 of 99 picks, the top 20 is 68% OpenAlex-only, only 1.6% of top-20 cards are fully filled in, and a search keeps a median of 510 people. Doubles in the top 20 are 0. The proposal is one module, `src/fn/score.py`, with the command `fn-score`.

## Findings

### 1. What each existing tool measures

| Tool | Measures | How it runs |
| --- | --- | --- |
| `src/fn/gold.py` (`fn-gold`) | For each of 28 gold questions: starts a real search, then labels each pick found (top 10 of its section), event page, no lane in slice or missed, with the step where it was lost. Writes `report.md` and `top5.csv` to `var/gold/<time>/`. | `uv run fn-gold [GS-02 ...]`. It builds a Worker on `settings.db_path`, so it writes new searches into whatever `FN_VAR` points at (`gold.py:356`). Modes come from `FN_LLM` and `FN_HTTP`. `var/gold` does not exist in the main var dir, so no report from the main checkout. |
| `scripts/gold/cut_gate.py` | Over a database: total vs kept per search, picks that reach the ranker, picks in the first 50 and 100. Exits 1 under three limits. Today: 12 picks reach the ranker, 4 in the first 50, 6 in the first 100, median drop 55.8%, PASS. | `uv run python scripts/gold/cut_gate.py DB`. Opens the database read-only. It has its own copies of `name_key` and `group_key` (`cut_gate.py:16-21`, `contracts.py:68-74`), so the two can drift. |
| `scripts/gold/probe_openalex.py` | One-off. Records OpenAlex responses for two cases and writes `reach.json`. | Needs a live key and calls. |
| `src/fn/stats.py` and `/debug/stats`, `/debug/feedback` | Per step: runs, errors, median and slowest seconds, median cost and calls, over the newest 20 searches. Per search: seconds, cost, people, seconds to first person. Feedback: kept, cut, added, skipped per search and the lanes that found added people. | Web pages. The `events` table has 0 rows, so feedback shows nothing today. |
| `net.py` | Not a measure. `FN_HTTP=live` calls out and writes `var/cache/<sha256(key)>.json`. `replay` serves that cache and raises `CacheMiss` on a miss (`net.py:119-130`). | The key is the URL for GET and `POST url + sorted body` for POST. |
| `llm.py` | Not a measure. `live` calls the CLI and stores nothing but token counts and cost. `record` calls and writes `tests/fixtures/llm/<task>-<sha16>.json`. `replay` reads fixtures and raises `FixtureMissing`. `prefer` reads, else calls. | Fixture dir is `settings.root/tests/fixtures/llm` (`llm.py:186`). |
| `worker.py` | Stamps each search with git sha, dirty flag, LLM mode and redacted settings. Runs `search.run` on one thread. | Used by the app, `fn-gold` and `fn.search`. |

Facts about the stored data:
- `var/cache` has 569 files, 144 MB. `step_calls.response_path` is an absolute path to one of these files. 524 of 980 calls point into another worktree's cache (`fn-scope-new`), 20 into main, and all 545 HTTP paths exist today. Replay recomputes the path from the request, so `response_path` is a debug link, not a replay input.
- All 412 LLM rows in `step_calls` have no `response_sha` and no `response_path`. A live search keeps no LLM answers.
- The 29 stored searches: 28 ran on 2026-11-05 with `FN_LLM=replay` and cached HTTP, on an earlier commit (`36e3d7e`). Only the newest, `e4caaf4e`, ran live on current code. Step seconds are real only for that one: 257 s in total, web lane 230.6 s, OpenAlex lane 18.1 s, parse 6.9 s, rank 0.38 s.
- The 354 `extract-*.json` fixtures are gitignored (`.gitignore`). They exist only in the `fn-scope-new` worktree. A fresh worktree has 30 parse fixtures and no extract fixtures. The same holds for `tests/fixtures/http/openalex/`.
- Test suite: 411 tests, 21 s.

### 2. What can be re-run with no outside call

I copied the database with `sqlite3.backup` (540 MB, 0.8 s) and worked only on copies. `Settings` had no keys, so no outbound call was possible.

| Level | What it re-runs | Result | Time |
| --- | --- | --- | --- |
| Re-score | Nothing. Reads stored candidates. | Deterministic: two runs give a byte-identical JSON. | 2.4 s for 29 searches |
| Re-rank | `resolve.run` and `rank.run` from the stored `resolve` and `rank` step inputs. | The newest search reproduces exactly (1154 entries, same candidates). The other 24 with candidates do not equal their stored output (see below). | 12 s for 29 searches; resolve 0.03-0.09 s, rank 0.03-0.5 s per search |
| Replay | A whole search with `Settings(llm_mode="replay", http_mode="replay")` on a clone. | 28 of 28 gold searches end `done`. Kept lists identical to stored for 8 (the 4 empty ones plus 4 others), same top-20 order for 12, top-20 overlap 464 of 480 people. Two replays from two fresh clones are identical in every candidate, section, rank, score and cut reason. | 39 s for 28 searches, 1.3 s median, 3.9 s max |
| Replay of the live search | Same. | Fails at parse (`FixtureMissing`) because live mode stored no fixture. With the stored chips passed in, it ends `done` with 1102 candidates vs 1154 stored. The 19 extract fixtures are missing, so the web lane returns 12 people instead of 65. It logs a warning and stays `ok`. | 3.0 s |

Why re-rank and replay differ from stored output on the older searches:
- The stored `rank` inputs come from older code. They have `hit_person_ids = []`, which the current ranker reads as "first person is the hit". All 576 candidates of one search differ in that field.
- `resolve` reads the whole persons table. Later searches added same-name records, so entries grew from 1 to 2 or 5 records (14 of 576 entries in one search, 17 of 417 in another).
- So "equals the stored result" is the wrong test. The right test is base code against head code on one frozen snapshot. Two replays of the same code on the same snapshot are identical, which I measured.

Two traps found:
- A missing LLM fixture degrades a lane silently. The scorecard run must fail when any step log holds `FixtureMissing` or any call has error "not in the response cache".
- `fn-gold` and `fn.search` write into the database at `FN_VAR`. Run them in replay mode only against a clone.

### 3. The scorecard

Inputs are the searches in a frozen snapshot and the 28 gold cases. A search with a gold question gets gold metrics. Others get the rest.

| Metric | Definition | Reuses | Baseline (stored, 25 searches with results) |
| --- | --- | --- | --- |
| gold_recall_at_10 / 20 / 50 | Gold picks whose card sits at position K or better in the list staff see (network first, then new, skipped people removed), over all 99 picks. | `gold.load_cases`, `gold.match` | 0.0303 / 0.0303 / 0.0404 (3 / 3 / 4 of 99) |
| gold_picks_found_anywhere | Picks present in the kept list at any position. | same | 12 |
| doubles_top20 / top50 (certain, likely, possible) | Pairs of cards in the top K. Certain: a shared ORCID, OpenAlex, Wikidata, LinkedIn or email identifier. Likely: same name (spaces ignored, middle initials dropped, first-name initial allowed) and a shared org id. Possible: same name only. | `contracts.group_key`, `store.identifiers_of` | top 20: 0 / 0 / 0. top 50: 0 / 1 / 1 |
| has_place, has_role, has_employer, has_tie, has_sources2, complete_all5 (top 20) | Share of cards with the field. Tie is evidence or a Belgian org. Sources2 is two or more distinct source ids across the card's records. | `present.person_views` | place 0.576, role 0.032, employer 0.988, tie 1.0, sources2 0.594, all five 0.016 (8 of 500 cards) |
| topic_evidence (top 20) | Share of cards where a topic chip word appears in a claim value or quote of the card. | chips, claims | 0.333 |
| in_place (top 20) | Of cards scored, share whose place coordinates are inside the metro radius of the question's place. Scored only when the place is a metro that GeoNames finds. | `geo.locate`, `geo.distance_km` | 0.193, on 19 searches |
| lane mix (top 20) | Share of cards found by one lane only (OpenAlex, seeds, web) and by two or more lanes. | candidate `lane_ranks` | OpenAlex only 0.682, seeds only 0.158, web only 0.016, multi-lane 0.134 |
| people shown | Kept count per search. The page shows 50 first (`present.RESULTS_STEP`). | store | median 510, max 1130 |
| seconds per step (live searches) | `ended_at - started_at` per step. Reported only for searches with `llm_mode = live`. | `step_runs` | one search, see section 1 |

Findings from the baseline:
- **The list is flooded.** A search keeps a median of 510 people. Two thirds of the top 20 come from OpenAlex alone, and a third have a topic word anywhere in their claims. The OpenAlex lane of the live search returned 1002 authors, 354 with a Belgian affiliation (its own log line).
- **Gold recall is near zero.** 12 of 99 picks are in any kept list, and 4 are in the first 50. This matches `cut_gate.py` (12 reach the ranker, 4 in the first 50).
- **Doubles by name are rare in the top 50.** There are 0 in the top 20 and 1 likely pair in the top 50 across 25 searches. In the full kept lists there are 40 likely pairs, 37 of them two OpenAlex records of one person and 3 a seed record against an OpenAlex record. My rules cannot see a double whose names differ (nickname, spelling, transliteration). A probe for same surname, same first three letters and a shared org found 1 more pair in the top 100. I could not reproduce the owner's seed-plus-OpenAlex doubles in stored data. They may come from a run that is not stored, or from name forms I do not catch.
- **Records are split.** 287 of the 1250 top-50 entries (23%) hold two or more same-name records that resolve flags as "not merged". Of the 500 top-20 cards, 77 have such unused records. But merging them would fix little. Of 212 top-20 cards without a place, 6 would get a place from the other records. Of the 73 cards with unused records and no role, 0 would get one. Missing place and role mostly mean the data is in no record yet.
- **Cards are thin.** The tie is always there, the employer almost always (OpenAlex affiliations), and the role almost never (3.2%).

Limits of these numbers:
- Cards read today's claims, not the claims at search time. A snapshot fixes this for comparisons, not for history.
- The gold set is small. One pick is 0.0101 of recall. Report picks gained and lost by id, not only the rate. `reach.json` labels 9 of 99 picks, 5 of them unreachable.
- The topic proxy is a word match. It reads zero for OpenAlex cards because the OpenAlex claims record only affiliations. The match "works on 'X'" lives in `LaneHit.matched_on`, which is never stored as a claim.
- The `events` table is empty, so no staff labels exist yet for doubles or good picks.

#### Output format

`scorecard.json` has `schema`, `aggregate` (flat metric to number), `searches` (keyed by the first 8 characters of the search id, holding the question hash, the gold case id and every metric) and `live_step_seconds`. Keys are sorted and numbers rounded to 4 places, so two runs diff line by line. No names and no timestamps sit in `aggregate` or `searches`. `scorecard.md` is the aggregate as a table. `compare BEFORE AFTER` prints only the metrics that changed, with the delta.

#### Before and after from two worktrees

```
export FN_VAR=var/score        # frozen, outside git
uv run fn-score snapshot                                  # once: db backup, cache, fixtures
git worktree add ../score-base <main sha>
git worktree add ../score-head <branch sha>
(cd ../score-base && uv run fn-score run --mode replay --out /tmp/base.json)
(cd ../score-head && uv run fn-score run --mode replay --out /tmp/head.json)
uv run fn-score compare /tmp/base.json /tmp/head.json   # exit 1 on a regression
```

- Each run clones the snapshot database (an APFS clone, `cp -c`) into a temp file, runs, and deletes it. The cache is shared and read-only.
- Both runs record `git rev-parse HEAD` and `dirty` in a `meta` block outside `aggregate`, so a dirty tree is visible.
- Pick the mode by what the change touches. `rescore` for a metric change. `rerank` (12 s) for `resolve`, `rank` or `present`. `replay` (about 40 s) for lanes, parse or extract. Under a minute either way.

### 4. Where it lives and how it is tested

One module, one owner, `src/fn/score.py`, with the entry `fn-score` in `[project.scripts]` next to `fn-gold`. Responsibilities:

| Responsibility | Owner |
| --- | --- |
| Freeze inputs (database backup, cache, fixtures) | `score.py snapshot` |
| Run the code under test on the snapshot (replay, rerank) | `search.run`, `resolve.run`, `rank.run`. `score.py` only calls them. |
| Card fields (place, role, employer, tie) | `present.person_views`. `score.py` reads, never rebuilds. |
| Gold match and cases | `gold.match`, `gold.load_cases` |
| Place area and distance | `geo.locate`, `geo.distance_km` |
| Metric definitions, JSON, compare, verdict | `score.py` |
| Why a pick was lost | `fn-gold` stays the diagnosis tool. It does not gate. |

Tests, in `tests/test_score.py`, in the style of `test_gold.py` with `tests/helpers.make_db`:
- A hand-built database with two searches checks each metric on known data, including recall at the edge (a pick at position 20 counts for K=20 and not at 21), a certain, a likely and a possible pair, and a card missing each field.
- Scoring twice gives equal JSON.
- Scoring a read-only database leaves the file hash unchanged.
- `compare` exits 1 when a double count rises or recall falls, and 0 when only an unrelated metric moves.
- A replay smoke test on the test fixtures ends `done` and fails when a fixture is missing.
- Break test: add a duplicate card to the fixture and see the doubles count go up. This is the one check that fails when the logic breaks.

Prototype (not product code), in `scratchpad/quality/scorecard/`:
- `scorecard.py` has `run DB OUT [--cache DIR] [--since ISO]` and `compare A B`. It opens the database with `mode=ro` and `PRAGMA query_only`. Run it from a worktree with `uv run python`, so it imports that worktree's `fn`.
- `out1/scorecard.json` and `out1/scorecard.md` are the baseline above. `rerank.py`, `replay_all.py` and `replay_sig.py` are the re-run experiments. The `explore_*.py` files are the probes for doubles and recoverable fields.

## Recommendations

1. Build `src/fn/score.py` as designed above, with `snapshot`, `run --mode rescore|rerank|replay` and `compare`. Start from the prototype. Owner: `score.py`. Effort: about 1 day plus tests.
2. Add `fixtures_dir` to `Settings` (`FN_FIXTURES`), default `root/tests/fixtures/llm`. A worktree pinned to a commit has no extract fixtures today. Owner: `config.py`, read by `llm.from_settings`.
3. Make app searches run with `FN_LLM=record`, writing to the shared fixture dir, so every live search can be replayed later. Today live mode drops the answers. Owner: `llm.py`.
4. Fail a replay run on `FixtureMissing` or `CacheMiss` instead of passing it as a quiet 12-versus-65 drop. Owner: `score.py` checks step logs and call errors. A lane that swallows these in a real replay is the web lane's behaviour to settle.
5. Move the gitignored extract and OpenAlex fixtures out of one worktree into the shared snapshot dir. Deleting that worktree deletes the only copy. Owner: `score.py snapshot`.
6. Once `fn-score` covers it, retire `scripts/gold/cut_gate.py`. It holds its own copy of `name_key` and `group_key`. Owner: `scripts/gold`. Not deleted by me.
7. Store each OpenAlex hit's matched works as a topic claim so a card can show why it matches, and the topic metric stops reading zero for OpenAlex. Owner: `lanes/openalex.py`.
8. Treat the metrics as the target list: fewer people kept (median 510), recall at 20 above 3%, top-20 completeness above 1.6%. The list-size cut belongs to rank. The missing place and role belong to the lanes, not to resolve.

## Open decisions

1. **Gate thresholds.** Proposal for the first version: fail on any rise in certain or likely doubles in the top 20, on a fall of gold picks found at 20, and on a fall of `complete_all5` over 0.02. Everything else reports only. The owner decides if recall may trade against list size.
2. **Where the frozen snapshot lives.** Proposal: `var/score/` in the main checkout, outside git, shared by every worktree through `FN_VAR`. The fixtures hold real names, so it must not enter the public repo.
3. **Labels for doubles.** Staff `same` and `new` clicks write events, but the table is empty. The owner can label 20 or 30 pairs by hand to calibrate the doubles rules, or wait for events.
4. **Gold set reach.** `reach.json` labels 9 of 99 picks. Labelling the rest would show which misses are lane faults and which are out of reach.
