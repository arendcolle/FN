# Task K3: a search is done after the fit check; the second lookup pass runs after it

## Goal

In the last three live searches staff waited 25 to 55 s for the second lookup pass, which moved 0, 0 and 9 of the first ten; the fit check moved 4 to 9. The search now becomes `done` after the fit check, and the second pass runs after that on the same thread. Brief K3.

## What to build

### `src/fn/search.py`

`finish` (line 115) returns `Callable[[], None]`: link, resolve, `rank_and_save`, fit (an error gives `FitOut()`, no `return`), `rank_and_save` with any verdicts, then `return partial(second_pass, ctx, resolved, chips, first, hit if linking else None)`. New after it:

```python
def second_pass(ctx: StepContext, resolved: ResolveOut, chips: Chips, first: DeepenOut, linked: list[str] | None) -> None:
    """Look up the people the first pass left out, picked from the list saved after the fit check; when that added
    claims, link the employers of linked again (when given) and rank and save with the stored fit verdicts."""
    deepened = look_up(ctx, DeepenIn(chips=chips, skip=first.picked, used=first.gaps))
    if deepened.claim_ids:
        if linked is not None:
            link(ctx, linked)
        rank_and_save(ctx, resolved, chips, stored_fit(ctx))
```

`run` returns `finish(...)` (line 251).

### `src/fn/worker.py`

`execute` (76): `then = search.run(ctx, found)` when `workflow is None`, else `workflow(ctx, found)` and `then = None`, so a given workflow's return value is never called. After the `done` write, `then()` runs in a `try`; an exception logs `"search %s: the lookups after done failed\n%s"` redacted and the search stays `done`.

### `src/fn/store.py`

`sweep` (283), same transaction, after the loop:

```python
conn.execute("UPDATE step_runs SET status = 'interrupted', ended_at = ? WHERE status = 'running' AND search_id IN "
             "(SELECT id FROM searches WHERE status = 'done' AND boot_id != ?)", (_iso(now), boot_id))
```

### `src/fn/present.py`

`looking` (1326):

```python
    if search.status not in ("running", "done") or search.chips is None or search.chips.version < 2:
        return False
    return any(s.status == "running" and (s.step == deepen.STEP or search.status == "done")
               for s in store.list_steps(search.id))
```

After done, `link`, `rank` and `save` belong to the pass too; `deepen` alone would end the poll during link.

### `src/fn/web/staff.py`

`results_list` (231): `busy = looking(store, search)` first; `progress = ... if active or busy else None`; `if progress: top = None` becomes `if active:`; line 256 goes; the status element is `h.div(count, status_line(progress.people, busy) if progress else None, role="status")`. `search_page` line 274: `active = search.status in ("queued", "running") or looking(store, search)`.

### `src/fn/web/static/results.js`

Line 73 adds `|| progress.looking` to the keep-polling condition.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Step order before and after done | `search.finish`, `search.second_pass` |
| Search status; running the pass after done | `Worker.execute` |
| Who the pass picks | `deepen.picks` |
| Interrupting a pass left running | `Store.sweep` |
| Whether a search is looking up | `present.looking` |
| Status element, poll attributes, refresh | `staff.results_list`, `staff.search_page` |
| Polling and the swap | `results.js` |

## Recorded answers, replay and stored searches (S6)

No prompt text changes. A replayed second pass picks from the list after fit, so a pick may lack a recording ("no recorded lookup"), and fit prompts lack second-pass facts. `refinish` runs no lookup; version-1 chips get no rerank; stored orders stay.

## Inputs a real run will meet

Pass picks nobody (1); pass or its rank raises (3); fit raises (B); every lane failed (existing); a search queued behind (4); a person added mid-pass (5); page during and after, version-1 chips, `fn-rerank` steps (6, 7); server stopped mid-pass (8).

## Tests (each must fail without the change)

`tests/test_search.py`, `SearchStepsTest`, made-up "Ann Smith" and "Pat Lee":

1. `test_the_second_pass_starts_after_the_search_is_done_and_the_fit_check_ended`: inside the second pass the search is `done` and fit `ok`; steps end `fit, rank, save, deepen`, which starts after `finished_at`; nobody picked adds no `save`.
2. `test_a_second_pass_that_adds_a_claim_reranks_and_keeps_every_fit_verdict`: fit `{ann: "no", pat: "yes"}`, pass returns a claim id. Steps end `fit, rank, save, deepen, link, rank, save`; the last rank gets the fit's verdicts; Ann keeps `aside == "unfit"`; version +1.
3. `test_a_pass_that_raises_after_done_keeps_the_list_and_the_search_done`: a raising deepen keeps its error row and the list; a raising rank after a claim logs ERROR on `fn.worker`; the search stays done.
4. `test_a_search_queued_behind_waits_for_the_second_pass`: while A's pass blocks, A is `done` and looking, B is `queued`; B's first step starts after A's deepen ended.
5. `test_a_person_added_during_the_pass_is_in_the_network_section_after_it`: `network.add` Pat while A (`done`) blocks; after a claim, Pat's section is `network`.

`tests/test_results_headings.py`, `SetAsideGroupsTest`:

6. `test_a_done_search_still_looking_up_shows_the_count_line_then_the_status_line_and_polls`: done v2 with running `deepen`: `role="status"` holds `fn-count` with Export, then "Looking up missing facts…"; `data-progress` ends " looking"; noscript refresh; JSON `"looking": true`. After it and a `save` end ok: count line alone, no `data-status`, refresh or `looking`, version +1.
7. `test_a_done_search_looks_up_only_with_version_2_chips_and_a_running_step`: done v2 with running `rank` is true; done v1 with running `deepen`, done v2 with nothing running, failed v2 with running `deepen` are false.

`tests/test_worker.py`:

8. `test_sweep_interrupts_a_running_step_of_a_done_search_from_an_earlier_boot`: the step is `interrupted` with `ended_at`; the search stays `done`, unreturned; this boot's is untouched.

## Existing tests that change, approved by the lead

- A. `test_search.py` `test_the_fit_step_runs_once_after_the_first_save_and_the_search_ranks_again_with_its_verdicts`: ends `deepen, fit, rank, save` → `fit, rank, save, deepen`.
- B. `test_a_fit_step_that_raises_leaves_the_search_done_with_the_first_ranking`: `deepen ok, fit error` → `fit error, deepen ok`.
- C. `test_a_lookup_that_added_claims_ranks_and_saves_again_before_the_fit_step`, renamed `..._after_the_fit_step`: ends `fit, rank, save, deepen, link, rank, save`.
- D. `test_a_deepen_step_that_raises_keeps_the_first_ranking_and_the_fit_step_runs`: ends `fit, rank, save` ok, `deepen` error.
- E. `test_the_first_lane_s_people_are_saved_before_the_next_lane_returns`: `deepen, fit` → `fit, deepen`.
- F. `test_web.py` `test_rerun_with_edited_chips_skips_parse_and_links_back`: after `wait_ended`, `client.app.state.worker.pool.submit(int).result(timeout=10)`; ends `fit ok, deepen ok`.
- G. `test_flows.py` `FlowTest.wait`: once the returned status is past running, it first drains the worker the same way.

No other existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. `V=$(mkvar.sh k3)`, from this worktree:

```sh
FN_VAR=$V FN_FIXTURES=<data folder>/llm FN_LLM=replay FN_HTTP=replay uv run python -m fn.search "Flemish students in Boston in healthcare"
```

Planner's run: main ends `deepen ok, fit ok`, this branch `fit ok, deepen ok` (0.1 ms after `finished_at`); no model call.

Then `FN_VAR=$V FN_PORT=8791 FN_LLM=replay FN_HTTP=replay uv run fn-serve`, and set that search's last `deepen` row to `running` with `ended_at` NULL in `$V/fn.sqlite3`. Headless Playwright screenshots of `/searches/<id>` at 1280 and 390 px: the count line with Export, under it "Looking up missing facts…" with its bar. Set the row to `ok`: within 4 s the line goes without a reload, no `/status` request follows, and a hovered card holds the swap until `pointerout`.

## Not doing

A new status, a second thread, a second fit check, a lock for the sub-millisecond gaps between the done write and the pass's rows, changes to the first pass, `deepen.picks`, `refinish`, Export or `fn.css`, browser tests of `results.js`.
