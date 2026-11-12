# Task Q1: the web lane reads its pages at the same time

## Goal

A search with live calls spent 228 of its 257 s in 19 model calls that ran one after another in the web lane. Run them at the same time, six at once by default, so the lane takes about 45 s. The design, with file and line for every claim, is in [research/speed.md](../research/speed.md), findings 2 and 3. Build exactly that design; this file lists what must hold.

Measured since the research: four calls at the same time take as long as one call alone (16 to 22 s each), so calls do not slow each other down.

## What to build

1. `steps.fan_out(fn, items, workers) -> list` in `src/fn/steps.py`. It runs `fn(item)` for each item on a thread pool. Each task runs in a copy of the caller's context with a buffer in place of the step's call recorder. The buffer keeps the task's calls in memory and never touches the store. When all tasks have ended, the step thread writes every buffered call into the step's recorder in item order, also when a task raised. The result list has one entry per item, in item order: the return value or the exception.
2. Log lines written inside a task stay on the step: `_LogCapture.emit` keeps a record whose recorder is the step's recorder or a buffer of it.
3. `extract.read_all(ctx, sources)` in `src/fn/extract.py` collects every chunk of every page, calls `fan_out` with the model call, and then checks each answer on the step thread, page by page and chunk by chunk, as `mentions` does today. The four error types `mentions` catches today become the same `chunk` rows and warnings. Any other exception is raised after the buffered calls are written. `mentions(ctx, source)` stays as the one-page form of the same code, so there is one implementation.
4. `web.people` in `src/fn/lanes/web.py` calls `read_all` once for all stored pages, then writes each page in its own short transaction as today. Store writes and `geo.coordinates` stay on the step thread.
5. `Settings.llm_workers: int`, env `FN_LLM_WORKERS`, default 6. The step context gives `read_all` the value; find how `ctx` reaches settings today and follow it, or pass the number where the lane is built. With 1 worker the calls run in order on the pool, with the same results.
`llm.py` does not change. The fake models in the tests keep working because they ask `current_recorder()`, which returns the buffer inside a task.

## What must hold

- `step_calls.seq` runs 1..N with no gap, and the requests follow page rank, then chunk index, on every run of the same input, whatever order the calls finish in.
- Every write to the store comes from the step thread.
- One failed chunk gives one `chunk` row and does not lose the other chunks or pages.
- The step's `tokens_in`, `tokens_out` and `cost_usd` are the sums over all calls.
- A replayed search gives the same people, claims and candidates as before this change. Run two searches from the throwaway var folder in replay mode on main and on your branch and compare the kept candidates.

## Inputs a real run will meet

No stored page at all (no pool is started); one page with one chunk; a page whose text is empty; more chunks than workers; a model call that times out (an `LLMCallError`, one `chunk` row); a model call that raises an unexpected exception (the lane step fails, and the calls that finished are still logged).

## Tests

In `tests/test_fan_out.py` or the existing web lane tests, with made-up names:

- a fake model that sleeps, with later chunks sleeping less so they finish first: 10 pages of 2 chunks with 8 workers finish in under a quarter of the serial time, and the logged requests are in page then chunk order on two runs
- a wrapper around `store.add_call` and `store.upsert_claim` records `threading.get_ident()`: one thread only
- one chunk raises `LLMCallError`: the people of the other chunks are returned and one `chunk` row names the failure
- the step's token and cost totals equal the sums of the fake's answers
- a log line written inside a task appears in the step's log

Each new test must be seen failing without the change it covers.

## Hand check

Replay one stored search with web pages on a throwaway var folder (`mkvar.sh q1`, `FN_HTTP=replay FN_LLM=replay`, extract fixtures from `.claude/worktrees/fn-scope-new/tests/fixtures/llm` copied into the worktree's `tests/fixtures/llm`, which git ignores) and paste the web lane's step row and its call order.

## Changes to existing tests, approved

- `tests/test_extract.py`, the test of a 13,000-character page: it reads the chunks in the order the calls reached the fake model. Calls now start at the same time, so that order is no longer a property of the code. Sort the fake's pages by their position in the text (`sorted(self.llm.pages, key=text.index)`) before the assertions. Change nothing else in that test. No other existing test may change.

## Not doing

- Joining a short last chunk to the one before. It saves one call on 7 of 225 pages and changes what an existing test pins.

- OpenAlex batch calls at the same time. That is a later task, after the task that changes the same file.
- Lanes side by side.
- One chunk for LinkedIn profile pages.
- Any change to the model, the effort level or the prompt. Measured: low effort finds the same people and saves no time; the older small model without thinking is 2 to 4 times faster and lost 4 of 35 people.
