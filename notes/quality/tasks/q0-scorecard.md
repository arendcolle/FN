# Task Q0: one command that scores search results

## Goal

`fn-score` scores the searches of a frozen snapshot with the code of the checkout it runs from. Two runs, one from main and one from a branch, are compared before the branch merges. Research and a working prototype: [research/scorecard.md](../research/scorecard.md) and the prototype named at its end (`scorecard.py`, `rerank.py`, `replay_all.py`). Start from the prototype.

## What to build

One module `src/fn/score.py` with the entry `fn-score = "fn.score:main"` in `pyproject.toml`, next to `fn-gold`. It owns the metric definitions, the JSON, the comparison and the verdict. It calls other modules for everything else and rebuilds none of their logic:

| Need | Call |
| --- | --- |
| The steps after the lanes | a new `search.finish(ctx, outs, chips)` (see below) |
| A whole search | `Worker.create_search` and `Worker.execute` |
| Card fields | `present.person_views` |
| Gold cases and matching | `gold.load_cases`, `gold.match` |
| Place of a question | `geo.locate`, `geo.distance_km` |
| Name keys | `contracts.name_key`, `contracts.group_key` |

### Commands

- `fn-score snapshot DIR [--llm EXTRA_DIR ...]` writes `DIR/fn.sqlite3` (SQLite backup API from the settings database, source opened read-only), `DIR/cache/` (a copy of `var_dir/cache`) and `DIR/llm/` (every `*.json` of `settings.fixtures_dir`, of `var_dir/llm` and of each `--llm` directory). It refuses a `DIR` that exists and is not empty.
- `fn-score run DIR --mode rescore|rerank|replay --out OUT_DIR` copies `DIR/fn.sqlite3` to a temporary folder, runs there, writes `OUT_DIR/scorecard.json` and `OUT_DIR/scorecard.md`, and deletes the temporary folder. It never writes into `DIR`.
  - `rescore` scores the stored candidates as they are.
  - `rerank` runs `search.finish` for each finished search from the stored outputs of its lane steps (`step_payloads.output_json` where `step_runs.step` starts with `lane:`), with the stored chips. Scores the result.
  - `replay` starts a new search for each finished search with the stored question and the stored chips, with `llm_mode="replay"`, `http_mode="replay"`, `var_dir` the temporary folder (its `cache` is a copy or link of `DIR/cache`), `fixtures_dir=DIR/llm` and no API keys. Scores the new searches.
  - A replay or rerank is `degraded` when a step failed, a step log holds `FixtureMissing`, or a call has an error that names the response cache. The JSON lists the degraded searches under `meta`, their metrics are left out of the aggregate, and the command exits 2 unless `--allow-degraded` is given.
- `fn-score compare A.json B.json` prints every aggregate metric that changed with both values and the delta, then the gold picks that moved (by pick id, old and new position). Exit 1 when a gate fails, else 0.

### `search.finish`

Move the three steps after the lane loop of `search.run` (resolve, rank, save) into `finish(ctx, outs, chips)` in `src/fn/search.py`, and call it from `run` and from `publish` where the code is the same. No behaviour change. Later tasks add steps there, and the scorecard follows without edits.

### Settings

- `Settings.fixtures_dir: Path`, env `FN_FIXTURES`, default `root/tests/fixtures/llm`. `llm.from_settings` reads it instead of building the path.
- Live mode keeps its answers: `from_settings` returns `FixtureLLM(settings.var_dir / "llm", "record", ClaudeCli(settings))` for `llm_mode == "live"`. A live search can then be replayed later. If an existing test asserts that live mode returns a bare `ClaudeCli`, change that assertion: this is an intended change.

### Metrics

Per search, over the kept candidates in the order staff see them (`store.list_candidates(search_id, kept_only=True)`). "Top 20" is the first 20. Names never enter the output.

| Metric | Definition |
| --- | --- |
| `kept` | number of kept candidates |
| `gold_at_10`, `gold_at_20`, `gold_at_50`, `gold_found` | gold picks of the search's gold case at position 10, 20, 50 or better, and anywhere in the kept list. `gold_picks` lists each pick as `{"id": "GS-02#1", "position": 37}` or position null |
| `doubles_top20`, `doubles_top50` | pairs of cards in the top 20 or 50 that are likely one person: equal `group_key`, or equal after dropping every middle token, or surname equal and first names compatible by initial, each with at least one shared `org_id` among their claims |
| `place`, `role`, `employer`, `tie`, `sources2`, `complete` | share of top-20 cards whose view has a place, a role, an employer, a Belgian organization or evidence, two or more distinct sources, and all five |
| `fresh` | share of top-20 cards whose employer fact has `valid_to` or `claim_date` in the last five years, counted from the search's `created_at` |
| `topic` | share of top-20 cards where a topic chip word (stop words dropped, case-insensitive, at a word start) stands in a claim value or quote of the card's records |
| `place_inside`, `place_outside`, `place_unknown` | for a search whose place chip `geo.locate` finds: share of top-20 cards with a located claim inside `geo.METRO_RADIUS_KM`, with located claims and none inside, and with none |
| `lane_openalex_only`, `lane_seeds_only`, `lane_web_only`, `lane_multi` | share of top-20 cards by the lanes in `lane_ranks` |
| `seconds` | per step name, for searches with `llm_mode == "live"` only, under `live_step_seconds` |

The aggregate is the mean of each share over the searches that have it, the sum of the gold counts and the double counts, and the median of `kept`.

### Output

`scorecard.json` holds `schema` (1), `meta` (git sha, dirty flag, mode, snapshot path, degraded searches), `aggregate` (flat, metric to number) and `searches` (keyed by the first 8 characters of the stored search id, with a sha256 of the question, the gold case id and every metric). Keys sorted, numbers rounded to 4 places, no timestamps outside `meta`, no names anywhere. `scorecard.md` is the aggregate as a table.

### Gates in `compare`

A gate fails when, from A to B: `doubles_top20` rises, `gold_at_20` falls, `gold_found` falls, or `complete` falls by more than 0.02. Everything else is reported only.

## Inputs a real run will meet

Each needs a test or a stated behaviour: a search with no candidates (scored with `kept` 0, shares left out); a search with no gold case; a search whose place chip is a country or `anywhere_us` (place metrics left out); a search with fewer than 20 kept; a snapshot folder with a missing `llm` folder (replay degrades, it does not crash); a failed search in the snapshot (skipped, listed in `meta`).

## Tests

`tests/test_score.py`, built with `tests/helpers.make_db` and made-up names:

- each metric on a hand-built database with two searches, including a pick at position 20 (counts at 20, not at 10) and a card missing each field
- a likely pair in the top 20 raises `doubles_top20`: this is the test that must fail when the pairing logic breaks. Show it failing with the pairing disabled, then passing
- scoring the same snapshot twice gives byte-identical JSON
- `run` leaves the snapshot folder's files unchanged (compare hashes)
- `compare` exits 1 when `doubles_top20` rises or `gold_at_20` falls, and 0 when only an ungated metric moves
- a replay with a missing fixture is reported as degraded and exits 2
- `search.run` still writes the same steps in the same order (the existing search tests cover this; they must pass unchanged)

## Hand check

Make a snapshot from the throwaway var folder (`mkvar.sh q0` prints it; set `FN_VAR` to it), add the extract fixtures with `--llm .claude/worktrees/fn-scope-new/tests/fixtures/llm`, then run all three modes and paste the three aggregates. Expected from the research: `rescore` near gold 3 / 3 / 4 at 10 / 20 / 50, place 0.58, role 0.03, median kept 510, `doubles_top20` 0; `replay` finishes 28 searches in under 2 minutes with the newest live search listed as degraded.

## Not doing

- No web page for the scorecard.
- `scripts/gold/cut_gate.py` stays. Retiring it is a follow-up.
- No labelled set of good and bad cards.
- No change to `fn-gold`.
