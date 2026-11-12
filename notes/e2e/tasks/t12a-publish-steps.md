# Task T12a: a search publishes people after each lane, and one failed lane does not stop it

Branch `feat/publish-steps`. After this task the people a search has found so far are saved after every lane, a failing lane no longer fails the search, and the store can say how far a search is. The page that shows this live comes in a later task.

Read first: [design.md](../design.md) "While a search runs", [panel-records.md](../panel-records.md) record D9, and `research/pipeline.md`.

## Why

A search saves people only after its last lane (`src/fn/search.py`), so the page shows nobody for minutes: the web lane's median is 186 s. One lane exception fails the whole search and hides what the other lanes found (`src/fn/worker.py`).

## What changes

1. **Publish step.** `contracts.py` gets `PublishIn(outs: list[LaneOut], chips: Chips)` and `PublishOut(count: int)`. After each lane except the last, `search.run` runs a step named `publish` that resolves, ranks and saves the lane outputs so far through the same functions the final steps use (`resolve.run`, `rank.run`, `store.save_candidates`), and returns the count saved. The final `resolve`, `rank` and `save` steps stay as they are. The step order becomes:

   ```
   parse, lane:seeds, publish, lane:openalex, publish, lane:web, publish, lane:linkedin, resolve, rank, save
   ```

2. **A failing lane.** When a lane raises, its step row keeps the error and traceback as today, and `search.run` goes on with an empty output for that lane. The search ends `done`. An error in parse, publish, resolve, rank or save still fails the search, and so does a search in which every lane failed. `store.failed_lanes(search_id) -> list[str]` returns the names of the lane steps that ended in error, for the page and the gold runner.
3. **Progress.** `contracts.SearchProgress(status: SearchStatus, people: int, version: int)` and `store.search_progress(search_id) -> SearchProgress | None`. `people` is the number of saved candidates with no `cut_reason`. `version` is the number of steps named `publish` or `save` with status `ok`, so it goes up each time the saved people change.
4. **Gold runner.** A done search with a failed lane is reported with the lane's name in the case's line, so a run that lost a lane is not read as a clean run.
5. **The trace page** does not trace publish steps (`TRACED` in `web/debug.py` lists the models it reads; leave `PublishOut` out).

## Tests

- `tests/test_worker.py` or a new `tests/test_search.py`: with a first fake lane that returns a hit and a second fake lane that blocks on an event, the candidates of the first lane are saved and `search_progress` says version 1 before the second lane returns; then the search ends done with version raised.
- A lane that raises: the search ends `done`, the other lanes' people are saved, the lane's step has status `error`, and `failed_lanes` names it.
- Every lane raises: the search ends `failed`. A parse error still ends `failed`.
- The step list of a search: `tests/test_web.py` asserts the exact list (around line 431). It changes on purpose to the order above. Change that assertion and say so in your report.
- `tests/test_gold.py`: a done case with a failed lane names the lane.

Each new test must fail without the change. Any other existing test that fails: stop and report the old and new expectation.

## Hand check

On a throwaway copy of the owner's database with `FN_HTTP=replay FN_LLM=replay`: create a rerun of the stored search `f10ee197-4c35-48f1-80f6-07cdbceae261` with its stored chips through `Worker.create_search(question, chips, "edited", rerun_of=...)` and `Worker.execute`, and print each step with its status and duration, `search_progress` and `failed_lanes`. A lane may fail on a replay cache miss: that is the case this task handles, so report what happened.

## Not in this task

The status route, the poll script, any page (`web/staff.py`, `web/parts.py`, `present.py`): another task is rewriting them. Running lanes at the same time.

## Rules for this task

- Run `uv run python -m unittest` before you start (300 tests pass) and when you finish.
- No new dependency. Only `store.py` runs SQL. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
