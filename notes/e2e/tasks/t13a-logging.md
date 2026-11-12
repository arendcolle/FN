# Task T13a: a request log, lane timings and decision feedback for the owner

Branch `feat/owner-logging`. After this task the owner can see where a search spends its time and what staff did with its results, and every request leaves one log line.

Read first: [design.md](../design.md) "Logging for later work", `research/pipeline.md` (what a step row holds) and `research/web.md` section on the debug pages.

## Why

The owner wants to improve speed and result quality later. Step rows hold duration, cost and calls, and the new `events` table holds every staff decision with the search and the rank it was made at, but no page sums them up, and no log says how long a page took.

## What changes

1. **Request log.** The guard middleware in `web/app.py` logs one INFO line per request on the logger `fn.request`: method, path, status and duration in milliseconds, then any facts the handler put in `request.state.facts` (a dict) as `key=value` pairs. A request over 1,000 ms logs at WARNING. Static files are not logged. No query string and no form value goes into the line, because they can hold personal data.
2. **The staff error page shows no traceback.** The design system says staff never see tracebacks. A 500 on a staff page says "Something went wrong" and "FN could not show this page. Nothing was changed." The traceback is stored as today and shows on `/debug/errors`. A 500 on a `/debug` page keeps the traceback. `tests/test_web.py` asserts the traceback on the 500 page (around line 376): that test changes on purpose; say so in your report.
3. **`stats.py`** (new), read models with no HTML, each a frozen model in `contracts.py`:
   - `steps(store, last: int = 20) -> list[StepStat]`: over the newest `last` searches of kind `search`, per step name: runs, errors, median and slowest duration in seconds, median cost and median call count.
   - `searches(store, last: int = 20) -> list[SearchStat]`: per search: the question cut at 80 characters, status, total seconds, cost, people saved, and the seconds from the search's creation to the end of its first `publish` or `save` step whose output has a count above 0 (empty when there is none).
   - `feedback(store, last: int = 50) -> list[SearchFeedback]`: per search with at least one event: candidates kept and cut, people added and skipped (events not undone), the ranks at which the added people stood, and how many added people each lane had found (from the candidate's lane ranks).
   Add the SQL these need to `store.py`.
4. **Two debug pages** in `web/debug.py`: `/debug/stats` (the step table, then the search table) and `/debug/feedback` (one row per search, then the ranks of all added people as counts per band: 1 to 10, 11 to 50, 51 to 100, over 100). Link both from the debug nav in `web/html.py`. Debug pages use the base table styles only.

## Tests

- New `tests/test_stats.py`: medians and slowest over built step rows; a search with no publish step has an empty time to first person; feedback counts an add, leaves out an add that was undone, and reads the lanes from the candidate.
- `tests/test_web.py`: a request writes one `fn.request` line with the status and no query string (use `assertLogs`); a failing staff route returns 500 without the traceback text and `/debug/errors` shows it; `/debug/stats` and `/debug/feedback` return 200 on an empty and on a filled database.

Each new test must fail without the change.

## Hand check

On a throwaway copy of the owner's database, start the server on a port from your range, open `/debug/stats` and `/debug/feedback`, and paste the step table as text. Paste three lines of the request log.

## Not in this task

Staff pages other than the error page (`web/staff.py`, `present.py`): another task is rewriting them. Client-side logging. Any change to what a step records.

## Rules for this task

- Run `uv run python -m unittest` before you start (300 tests pass) and when you finish.
- No new dependency. Only `store.py` runs SQL. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
