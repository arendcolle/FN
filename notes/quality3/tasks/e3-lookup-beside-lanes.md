# Task e3: the lookup starts while the lanes run

## Goal

Measured live on two questions with the lookup after the lanes: the lanes took about 75 s, the step 127 s and 81 s (30 and 20 calls of 10 to 24 s, then 37 page readings of up to 35 s), the searches 228 s and 196 s. This task runs a first pass on the seeds publish's people beside the other lanes, and a second pass after them within one total of 20 (S8). Judgement: a search then takes the longer of lanes and first pass, plus a short second pass; the first pass's calls share `llm_procs` (llm.py:92) with the lanes, so the lanes can slow down.

## What to build

### `src/fn/contracts.py`

- `DeepenIn` (line 982) gains `skip: list[str] = []` and `used: int = 0`.
- `DeepenOut` (line 986) gains `picked: list[str] = []` and `gaps: int = 0`.

### `src/fn/deepen.py`

- `picks(ctx, chips, skip: frozenset[str] = frozenset(), most: int = MAX_LOOKUPS)` (line 70): line 83 becomes `(since | skip) & set(records)`. Lines 85-91 become `gap = [...]` (the list at line 85), `missing = gap if missed < most else []`, `missed += bool(missing)`, and `contact = at < CONTACT_TOP and (missing or not gap) and not any(...)`: past the cap, a person with a gap gets no contact-only pick. With `most=20` e1's picks stay the same.
- `run` (line 149): `picks(ctx, inp.chips, frozenset(inp.skip), MAX_LOOKUPS - inp.used)`. The returns at lines 166 and 192 set `picked` (each pick's `candidate.person_id`) and `gaps` (picks with `missing`). A `FixtureMissing` pick counts, so a replay never looks a person up twice.

### `src/fn/search.py`

- `look_up(ctx, inp: DeepenIn) -> DeepenOut`: lines 114-117 as a function; an exception gives `DeepenOut()` and stays on its row.
- `first_pass(ctx, chips) -> DeepenOut`: `look_up(ctx, DeepenIn(chips=chips))`, `finally: ctx.store.close()` as `run_lane` (line 178).
- `run` (line 182): `max_workers=len(LANES) + 1`. Right after the publish that follows the `FIRST` lane (lines 228-230), submit `copy_context().run(first_pass, ctx, chips)` to the pool. When `FIRST` is absent or the only lane, no publish follows it and no first pass starts. After the `with` block, `first = started.result() if started else DeepenOut()`; `finish(ctx, in_lane_order(outs), chips, first)`.
- `finish(ctx, outs, chips, first: DeepenOut)` (line 99, called only by `run`): the second pass is `look_up(ctx, DeepenIn(chips=chips, skip=first.picked, used=first.gaps))`. `refinish` is unchanged.
- The docstrings of `run` (line 183) and `finish` (line 100) say the first pass starts after the seeds publish and the second runs after the first save.

### Threads, publishes and the ranking

The first pass runs on a lane-pool thread, which opens its own connection; `first_pass` closes it. The second pass runs on the search thread, closed by the worker as today. Each pass has a `deepen` row; the first gets its number at start (S3).

`deepen.store` (line 195) commits one person's claims and lookup row in one transaction, and `rank.run` reads claims from the store (rank.py:446). A publish during the first pass therefore ranks each person with all of their lookup's claims or none. `finish` collects the first pass before its link step, and the pass-1 people are seeds hits, so link, resolve, rank and save after the lanes use those claims and link their employers. No extra rank is needed.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| When each pass runs and on which thread | `search.run`, `search.finish` |
| Closing the first pass's connection | `search.first_pass` |
| Who qualifies, the 20 and what is left, no person twice | `deepen.picks`, `deepen.run` |
| One transaction per looked-up person | `deepen.store` |
| The 90 days | `store.lookups_since` |

## Inputs a real run will meet

(1) Seeds finds nobody or raises; (2) seeds is the only lane; (3) the first pass outlasts every lane; (4) it takes all 20; (5) a pass-1 lookup failed; (6) no recording in replay; (7) a pass-1 person on another card after the lanes; (8) 300 people; (9) version-1 chips; (10) every lane fails; (11) the first pass raises; (12) a stored input without `skip` or `used`.

## Tests (each must fail without the change)

"a" in `tests/test_search.py`, "b" in `tests/test_deepen.py`, whose `deepen` helper gains `skip` and `used` arguments.

- a1: seeds at once, web sleeps 1.0 s, a patched `fn.deepen.run` sleeps 1.0 s on its first call only (a call counter) and returns at once on the second: the first `deepen` row starts before `lane:web` ends; the search ends under 1.8 s.
- a2 (3): V2, web sleeps 0.2 s; the first patched call sleeps 0.6 s, then writes a `works_at` claim for the seeds person and returns `picked=[id], gaps=1`. A wrapper on `fn.rank.run` records that person's claim ids: absent at the seeds publish, present at the first rank after the lanes. The second call gets `skip=[id], used=1`.
- a3 (1): seeds without hits, web 0.3 s: the first pass notes "nobody to look up", the second gets `used=0`.
- a4 (2): seeds alone: one `deepen` row.
- a5 (11): the first call raises: search done, rows `("deepen", "error")` then `("deepen", "ok")`.
- a6 (10): seeds and web raise: search failed after the first pass ended; `Store.close` ran on its thread.
- b1 (4, 8): 300 qualifying, `used=20`: only top-10 people with no gap and no contact are picked, and a top-10 person with a gap and no contact gets no call; `used=15`: 5 gap lookups.
- b2 (5, 7): a person in `skip` with a failed row, and a card whose second record is in `skip`: no call.
- b3 (6): all `FixtureMissing`: note, `picked` holds the picks, `gaps` counts them.
- b4 (9): V1 chips: `picked` empty, no call.
- b5 (12): `DeepenIn` from JSON with chips only: `skip=[]`, `used=0`.

## Existing tests that change, approved by the lead

- `test_search.py` `test_the_first_lane_s_people_are_saved_before_the_next_lane_returns`: sorted middle, old `lane:seeds, lane:web, publish`, new with `deepen` first.
- `test_search.py` `test_the_fit_step_runs_once_after_the_first_save_and_the_search_ranks_again_with_its_verdicts`: sorted middle, old `lane:seeds, lane:web, link, publish`, new with `deepen` first. `self.llm.calls` stays 3: the first pass looks up the seeds person, the second leaves them out.
- `test_web.py` `test_rerun_with_edited_chips_skips_parse_and_links_back`: the sorted middle gains `("deepen", "ok")`.

No other existing test may change; stop and report any other failure.

## Recorded answers and replay (S6)

No prompt changes. A lookup's key holds the person block, which the first pass builds from claims at seeds time. A person whose claims grew during the lanes of a recorded run misses in replay: no row, and the second pass skips them. Fresh live runs record under the new keys. Reranks are unchanged. In replay a fast lane can add claims to a seeds person before the first pass reads its block; the rare `FixtureMissing` this gives is accepted.

## Hand check

With `BASE`, `A`, `B`, `R` and `Q` set up as in s2's hand check:

```
uv run python -m unittest
(cd "$BASE/wt" && env $R FN_VAR="$A" uv run fn-rerank --all); env $R FN_VAR="$B" uv run fn-rerank --all
diff <(sqlite3 -readonly "$A/fn.sqlite3" "$Q") <(sqlite3 -readonly "$B/fn.sqlite3" "$Q")
env $R FN_VAR="$B" uv run python -m fn.search "Belgian scientists in the Washington D.C. area"
```

The diff prints nothing. The search lists two `deepen` rows, the first right after the seeds publish; their `gaps` add up to 20 or less and their `picked` lists share no id. In a live run of the two measured questions, the search's elapsed time is printed and compared with 228 s and 196 s.

## Not doing

Changes to who qualifies or what a lookup stores; a publish after the first pass; a page-read pace shared with the lanes; a time budget.
