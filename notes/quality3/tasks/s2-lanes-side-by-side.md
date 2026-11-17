# Task S2: lanes side by side

## Goal

The six lanes run one after another, so Washington took 272 s, of which web 79 s and scout 166 s (speed research note). Only web_topic needs earlier lanes, through the first-heading count. This task builds S2 to S5. The research estimates Washington at about 186 s, not measured.

## What to build

### `src/fn/store.py`, `src/fn/steps.py`

- `start_step(run, input_json) -> StepRun`: inside its `self.tx()` it reads `self.next_step_seq(run.search_id)` (store.py:178), inserts the row with that seq and returns `run.model_copy(update={"seq": seq})`. `BEGIN IMMEDIATE` holds the write lock, so two threads never read the same maximum.
- `run_step`, `skip_step` (steps.py:211, :254) pass `seq=0`, use the returned run.

### `src/fn/geo.py`

- `_lock = threading.Lock()`; `cities(http)` (geo.py:67) checks and fills `_loaded` while holding it.

### `src/fn/config.py`, `src/fn/llm.py`

- `Settings.llm_procs: int = Field(10, ge=1)`, from `FN_LLM_PROCS`.
- `proc_slots(limit: int) -> threading.BoundedSemaphore` under `@functools.cache`, shared in the process. `ClaudeCli.__init__` sets `self.slots = proc_slots(settings.llm_procs)`. `structured` holds it from right before `recorder, started = ...` (llm.py:99) to the end, so duration and timeout leave out the wait.

### `src/fn/contracts.py`

- `class CitiesIn(Model): pass` and `class CitiesOut(Model): names: int`, next to `PlacesIn`.
- The step-order comment (contracts.py:757) becomes: parse, cities, lanes side by side with a publish as each ends but the last, resolve, rank, save.

### `src/fn/search.py`

- `cities(ctx, _: CitiesIn) -> CitiesOut`: `names=len(geo.cities(ctx.http))`; an `HttpError` logs a warning and gives 0.
- `in_lane_order(outs: list[LaneOut]) -> list[LaneOut]`: stable sort by index in `LANES`, a `LaneName` missing from `LANES` last. The one owner of lane order.
- `publish(outs: list[LaneOut], done: LaneOut)`: reads `done.hits` where it read `outs[-1].hits` (search.py:41).
- `run_lane(ctx, lane, given: LaneIn) -> tuple[LaneOut, bool]`: the openalex skip (search.py:119-123) or `run_step(ctx, f"lane:{lane.name}", lane.run, given)`, with `False`; any `Exception` gives an empty `LaneOut` and `True`; `finally: ctx.store.close()`.
- `run`:
  1. Parse as today.
  2. When `ctx.http` is not None, `run_step(ctx, "cities", cities, CitiesIn())`; an exception keeps its error row and the search goes on.
  3. `WAITS = "web_topic"`: that lane is submitted once every lane before it in `LANES` has ended and been published, with `first_heading(ctx)`. The others are submitted at once.
  4. One `ThreadPoolExecutor(max_workers=len(LANES), thread_name_prefix="fn-lane")`; each submit runs `copy_context().run(run_lane, ...)` as `fan_out` does (steps.py:133-135).
  5. `outs` has one slot per lane in `LANES` order. Loop on `wait(pending, return_when=FIRST_COMPLETED)`, handling ended futures in `LANES` order: fill the slot, count a failure, run `publish(filled, out)` with `PublishIn(lanes=[o.lane for o in filled], chips=chips)` (`filled`: the filled slots). Publishes run on the search thread, one at a time. The last lane to end gets none, as today: `finish` saves next.
  6. All lanes failed raises as today; `finish` gets `in_lane_order(outs)`. The `run` docstring says lanes run side by side after cities.
- `refinish`: passes `in_lane_order(outs)` to resolve. Every earlier `LANES` (git log of `lanes/__init__.py`) is an ordered subsequence of today's, so stored searches keep their order.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which steps run, what runs side by side, publish order, web_topic's wait | `search.run` |
| Lane output order given to resolve | `search.in_lane_order` |
| A step's row and number | `store.start_step` |
| Building the city index once | `geo.cities` |
| When a search builds it | `search.run` (step `cities`) |
| Model processes at once | `llm.ClaudeCli` (input `Settings.llm_procs`) |
| Closing a lane thread's connection | `search.run_lane` |

## Inputs a real run will meet

web_topic first in `LANES` or absent; 12 model calls at once; `FN_LLM_PROCS` of `0` or `x`; no GeoNames dump in the replay cache; no HTTP client; stored lane steps out of order, of a removed lane, or two of one lane; many steps starting at once.

## Tests (each must fail without the change)

In `tests/test_search.py` unless named:

- Lanes sleeping 0.5, 1.0, 1.5 s: the search ends under 2.5 s.
- Lanes seeds (sleeps 0.3 s), web (at once) and linkedin (sleeps 0.6 s), one made-up person each: publish inputs `["web"]`, then `["seeds", "web"]`, counts 1 and 2; none after linkedin; resolve gets seeds, web, linkedin.
- Seeds at once, web sleeping 0.3 s, then web_topic, `rank.tier` patched to 2: web_topic gets `first_heading` 2. With web_topic first and seeds sleeping 0.5 s, web_topic starts while seeds runs.
- `fn.search.LANES` patched to seeds, web; `refinish` over steps stored as `lane:web`, `lane:linkedin`, `lane:seeds`, `lane:web`: resolve gets seeds, web, web, linkedin.
- `("cities", "ok")` follows parse with `names` above 0, and no lane step holds the GET of `geo.CITIES_URL`; a GET raising `HttpError` gives `names` 0, step ok; a worker without HTTP client writes no cities step.
- `Store.close` runs once per lane thread.
- `tests/test_steps.py`: 8 threads behind a `threading.Barrier`, `new_id` a uuid4, half `run_step`, half `skip_step`, get seqs 1 to 8.
- `tests/test_geo.py`: two threads, a slow GET: one GET.
- `tests/test_llm.py`: `llm_procs=2`, a fake `Popen` blocking until released, 4 calls through `fan_out` with `workers=4` in one step: at most 2 at once, all 4 answer. `FN_LLM_PROCS=3` gives 3; `0` and `x` raise.

## Existing tests that change, approved by the lead

- `test_search.py:86`: old, the exact list. New: parse, cities first; resolve, rank, save, fit last; the middle counts one `lane:seeds`, one `lane:web`, one publish.
- `test_search.py:142`, renamed `test_the_lane_input_carries_the_question_and_scout_runs_on_or_off`: old, five steps in order. New: parse, cities first; the middle counts the three lanes once and two publishes.
- `test_search.py:165`: `assertEqual` becomes `assertCountEqual`; two failing lanes end in either order.
- `test_search.py:204`: as `:86`, tail resolve, rank, save, fit, rank, save.
- `test_web.py:524`: old, the full list. New: parse skipped, cities ok first; resolve, rank, save, fit last; the middle counts six lanes and five publishes, all ok.
- `test_seeds_lane.py:268`: old, `[:2]` is parse, `lane:seeds`, payload of `steps[1]`. New: `[:2]` is parse skipped, cities ok; the step named `lane:seeds` is ok and its input holds the chips.

No other existing test may change; stop and report any other failure.

## Recorded answers and replay (S6)

No prompt changes, so every recorded answer keeps its key and nothing is re-recorded. A replay changes only its step order, and the GeoNames GET moves into the cities step. Two fresh-search changes come from timing: with scout off and linkedin on, an early linkedin output can push `first_heading` past `GATE` and skip a web_topic search; and seeds can match claims that openalex or web wrote moments earlier in the same search.

## Hand check

From the q3-s2 worktree:

```
uv run python -m unittest
BASE=$(mktemp -d); A=$(mktemp -d); B=$(mktemp -d)
git worktree add "$BASE/wt" "$(git merge-base HEAD main)"
for D in "$A" "$B"; do sqlite3 -readonly /Users/arend/Developer/FN/var/fn.sqlite3 ".backup $D/fn.sqlite3"; ln -s /Users/arend/Developer/FN/var/cache "$D/cache"; done
R="FN_HTTP=replay FN_LLM=replay FN_FIXTURES=/Users/arend/Developer/FN/var/llm"
(cd "$BASE/wt" && env $R FN_VAR="$A" uv run fn-rerank --all)
env $R FN_VAR="$B" uv run fn-rerank --all
Q="select search_id, section, rank, person_id, tier, cut_reason from candidates order by 1, 2, 3"
diff <(sqlite3 -readonly "$A/fn.sqlite3" "$Q") <(sqlite3 -readonly "$B/fn.sqlite3" "$Q")
time env $R FN_VAR="$B" uv run python -m fn.search "Belgian scientists in the Washington D.C. area"
git worktree remove "$BASE/wt"
```

The diff prints nothing. The replay search ends done, seqs unique, in 4.6 s or less.

## Not doing

A lookup step, a time budget, any change inside a lane, two searches at once, a new `failed_lanes` order.
