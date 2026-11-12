# Speed of one search

## TL;DR

Search e4caaf4e took 257 s, and 228 s of that is 19 Haiku calls in the web lane, run one after another. Two levers together bring the search near 50 s. First, the web lane can run its chunk calls at the same time. With 8 at once, today's 19 calls finish in 43 s instead of 228 s (a schedule computed from the logged durations). The design keeps every call logged in a stable order, keeps all store writes on the step thread and keeps replay deterministic. Second, about 80% of every Haiku call's output tokens never reach the answer, and call time grows 3.4 ms per output token (r² 0.98). This points at hidden thinking in the `claude -p` call, which one recorded experiment can confirm. If it is thinking and it can be turned off, each call gets 3 to 5 times shorter. OpenAlex can fetch its author and institution batches at the same time, which saves about 7 s. Lanes running side by side saves another 7 to 18 s but carries the most risk. Reading fewer pages or fewer chunks would lose gold picks, so the page count stays at 10.

## Findings

### 1. Where the 257 s go (question 1)

Source: tables `step_runs` and `step_calls` for search e4caaf4e, script `scratchpad/quality/speed/q1.py` and `q1b.py`.

| Step | Wall time | Calls | Call time |
| --- | --- | --- | --- |
| parse | 6.9 s | 1 Haiku | 6.9 s, 2,217 tokens in, 854 out |
| lane:seeds | 0.6 s | 0 | |
| lane:openalex | 18.0 s | 18 HTTP | 14.2 s |
| lane:web | 230.6 s | 2 HTTP, 19 Haiku | 2.2 s HTTP, 228.2 s Haiku |
| lane:linkedin | 0.0 s | 1 cache miss (off) | |
| 3 publish, resolve, rank, save | 1.3 s | 0 | |

The numbers in the task hold. What they leave out:

- **Haiku call time.** Mean 12.0 s, median 10.9 s, min 3.0 s, max 25.4 s. Tokens in average 3,947 a call (75,002 in all) and tokens out 2,568 (48,801 in all). Cost $0.044 for the lane.
- **Call time follows output tokens.** A least-squares fit over the 19 calls gives `duration_ms = 3,271 + 3.40 × tokens_out`, r² = 0.982. So each call has about 3.3 s of fixed cost (process start, CLI startup, round trip), and the rest is output generation.
- **Most output tokens are not the answer.** Today's answers were not stored, so I measured the 354 recorded extract fixtures in another worktree (`.claude/worktrees/fn-scope-new/tests/fixtures/llm`, same `extract.md` prompt, same model). The JSON answer averages 2,135 characters while `tokens_out` averages 3,326. That is 0.49 characters per output token (median), where JSON text runs about 3.5 characters a token. So about 16% of output tokens are the answer (median). The 30 parse fixtures in this worktree show the same: 330 characters of JSON against 1,468 output tokens (median). Today's call 20 read a 1,815-character page and spent 6,234 output tokens. Which hidden output it is (thinking, or retries inside the CLI's structured output) is not measured.
- **Why 10 pages need 19 calls.** `extract.chunks` cuts each page into parts of at most `CHUNK_CHARS = 6_000` (`src/fn/extract.py:26`), and Extract returns up to `MAX_CHARS = 12_000` a page (`src/fn/lanes/web.py:25`). Today 8 pages gave 2 chunks, 2 pages gave 1, and page 1 gave 3, because its third chunk is a 48-character tail that the packing could not join (`extract.py:64`). That tail call cost 3.0 s and returned 123 tokens. Across all stored web pages: 109 pages had 1 chunk, 109 had 2, 7 had 3.
- **Per-call fixed cost is real money in time.** 19 calls × 3.3 s = 62 s of today's 228 s is fixed cost. 68 of the 354 fixture calls (19%) found no person and still cost about 3.7 s each (median 130 output tokens).
- **OpenAlex.** 1 works call (1.8 s), 1 GeoNames zip download (1.3 s, once per process, `src/fn/geo.py:61`), 11 author batches (9.1 s) and 5 institution batches (2.0 s), all one after another. The other 3.8 s of the step are store writes for 1,002 hits. In the 29 replayed searches of 2026-11-05 the same calls averaged about 150 ms each, against 790 ms today. Why OpenAlex was slower today is not measured.

### 2. What stops calls inside one step from running at the same time (question 2)

1. **Call order.** `CallRecorder.record` sets `seq = len(self.calls) + 1` and then appends (`src/fn/steps.py:67` and `:73`). Two threads can read the same length, and the second insert then breaks `PRIMARY KEY (step_run_id, seq)` with an IntegrityError. Even without a clash, seq would follow finish order, so two runs of the same search would log calls in a different order.
2. **The recorder is a ContextVar.** `_recorder` (`steps.py:79`) is set on the step thread. A plain `ThreadPoolExecutor` thread does not inherit it, so `current_recorder()` raises "an outbound call was made outside a step" (`steps.py:86`) inside `ClaudeCli.structured` (`llm.py:97`) and `Client._send` (`net.py:118`). `_LogCapture.emit` keeps a line only when `_recorder.get() is self.recorder` (`steps.py:133`), so log lines from other threads would be lost.
3. **Which thread may use SQLite.** `Store.conn` opens one connection per thread through `threading.local` (`store.py:100-107`, `db.py:11` with `check_same_thread=True`). A worker thread would not crash. It would silently open a second connection and write `step_calls` rows from there (`store.add_call`, `store.py:219`, autocommit). If the step thread then holds `BEGIN IMMEDIATE` (`store.py:126`), for example in `web.people` (`web.py:96`), the worker's insert waits up to `busy_timeout=5000` and then fails with "database is locked". Connections opened by pool threads are never closed.
4. **Replay.** `FixtureLLM` finds an answer by the sha of system prompt, user turn, schema and model (`llm.py:160`), and `net.Client` finds a cached response by sha of the URL or POST body (`net.py:117`). Neither depends on call order, so replay itself stays deterministic. Only the logged order (point 1) would drift.
5. **Tokens and cost.** `run_step` sums `recorder.calls` when the step ends (`steps.py:176-178`). That works with any order, as long as every call reaches `recorder.calls` before the step finishes.
6. **Errors.** `extract.mentions` catches `TagError`, `LLMCallError`, `ValidationError` and `FixtureMissing` per chunk and goes on (`extract.py:137`). Any other exception fails the lane step. A pool must hand each chunk's exception back to this same handler, or one bad chunk could fail the lane or vanish.
7. **One more trap.** `extract.drafts` calls `geo.coordinates`, which can download the 1.3 s GeoNames zip, inside the page's write transaction (`web.py:96-100`, `extract.py:176`). Today that only slows the step. With concurrent writers it would hold the write lock during a network call.

The design note already lists the lane-level blockers: `next_step_seq` outside the insert transaction, the busy timeout and long transactions (`notes/e2e/design.md:133`). The architecture note puts "calling Parallel or Haiku concurrently" out of scope (`notes/mvp0/architecture.md:495`).

### 3. Reading pages at the same time in the web lane (question 3)

Smallest safe change: a fan-out helper in `steps.py` that runs tasks on threads with a buffered child recorder, and flushes the buffered calls into the step's recorder in task order on the step thread.

- `steps.fan_out(fn, items, workers) -> list[result | Exception]`. For each item it makes a `CallRecorder`-like buffer that copies `search_id`, `step` and `secrets` and points to the parent, and runs `fn(item)` inside `contextvars.copy_context()` with `_recorder` set to that buffer. The buffer stores calls in memory and never touches the store. After all tasks end, the step thread replays each buffer into the parent `record()` in item order, inside a `finally` so a crash still logs the calls that finished. It returns results and exceptions in item order.
- `CallRecorder.record` stays as it is. Only the step thread calls it, so seq stays `len + 1` and stable: page rank, then chunk index.
- `_LogCapture.emit` accepts a record whose recorder is the capture's recorder or a buffer whose parent it is. Then lines from worker threads are kept.
- `extract.mentions` splits into two parts. A new `extract.read_all(ctx, sources)` collects every (source, start, end) chunk of all pages, calls `fan_out` with `ctx.llm.structured`, and then runs `check` on each answer in order on the step thread. Exceptions from the four caught types become the same `chunk` rows as today, and any other exception is raised after the flush, as today.
- `web.people` calls `read_all` once for all stored pages, then writes each page in its own short transaction as now. Store writes stay on the step thread, and so does `geo.coordinates`.
- `llm.py` needs no change, and neither do `StubLLM` (`tests/helpers.py:89`) or the extract fake (`tests/test_extract.py:52`), because they call `current_recorder()`, which returns the buffer.
- Worker count: a setting `llm_workers`, default 6. The timeout per call stays at 120 s (`llm.py:22`).

Expected time, from today's 19 durations with tasks started in chunk order (`scratchpad/quality/speed/sim.py`): 1 worker 228 s, 4 workers 73 s, 6 workers 47 s, 8 workers 43 s, 10 workers 37 s, 19 workers 25 s. Running whole pages instead of chunks gives 67 s at 4 and 37 s at 10, so chunks are the better unit. This assumes calls do not slow down when several run together, which is not measured. 45 s for 10 pages needs 8 workers today, or 4 workers once the hidden output is gone (see finding 5).

The proving test, in `tests/test_web_lane.py` or a new `tests/test_fan_out.py`:

- A fake LLM that sleeps 0.5 s and records through `current_recorder()`, with later chunks sleeping less so they finish first. 10 pages of 2 chunks and 8 workers finish in under 2 s (serial is 10 s).
- `step_calls` seq runs 1..20 and the requests follow page rank, then chunk index, on two runs of the same input.
- A wrapper around `store.add_call` and `store.upsert_claim` records `threading.get_ident()`. Every write comes from the step thread.
- One chunk raises `LLMCallError`. The lane returns the people of the other pages and one `chunk` row for the failure.
- The step's `tokens_in`, `tokens_out` and `cost_usd` equal the sums of the fake's answers.

### 4. OpenAlex and lanes side by side (question 4)

**OpenAlex batches.** `openalex.fetch` (`src/fn/lanes/openalex.py:106`) loops over batches of 100 ids. The batches do not depend on each other, so `fetch` can call `steps.fan_out` with the same buffered recorder and merge the bodies in batch order. `seen_authors` keeps the institution pages serial (each page decides whether to read the next) and the topic works calls can fan out too. The GeoNames download in `place_area` could start alongside the author fetch, but it happens once per process and is not worth the extra code. From today's durations with 4 workers: author batches take 3.1 s instead of 9.1 s and institution batches 0.7 s instead of 2.0 s, which saves about 7 s. `httpx.Client` handles requests from several threads with one connection pool. The geo cache dict `_loaded` (`geo.py:63`) can race and download twice, which costs time but gives the same result.

OpenAlex limits (help.openalex.org, rate limits page, read 2026-11-12): 10 requests per second without a key, 30 with a free key, and the owner's settings show a key is set. Filters with more than 5 OR operators are limited to 5 per second with a free key, and each id batch is a 100-way OR. So 4 workers stays under that cap as long as calls take at least 0.8 s. Calls in the replays averaged 150 ms, so the fan-out also needs a rate limit: at most 5 batch requests in any second, or 3 workers. A per-second 429 costs nothing, and `net.Client` already retries a 429 once after `Retry-After` (`net.py:135-173`).

**Lanes side by side.** Today `search.run` runs the lanes one after another (`src/fn/search.py:50`). Running OpenAlex and web together saves the shorter of the two, which is 7 s after the OpenAlex fan-out, or 18 s if done alone. Changes needed: `next_step_seq` inside the insert transaction (`store.py:176`), lane write transactions kept short (the OpenAlex lane writes 1,002 hits in one transaction, `openalex.py:239`), no network call inside a transaction (finding 2.7), a higher busy timeout, and a new rule for `publish`, which now runs after each lane in a fixed order. Each lane thread opens its own connection, so two lanes write at the same time on two connections, unlike the fan-out above.

**Limits on this laptop.** `sysctl` reports 11 CPU cores and 18 GiB of memory. Running interactive `claude` processes use 140 to 500 MB each (`ps`). A headless `claude -p` call was not measured. Six at once should use at most about 1.5 GB if a headless process stays under 250 MB, which is an estimate. The subscription's limit on parallel requests is not measured. A 429 or "overloaded" answer from the CLI would come back as `LLMCallError` and become a `chunk` row, so a too-high worker count loses people without failing the lane. Default 6 and watch `chunk` rows on the first live runs.

**Ranking by seconds saved against risk.**

| Change | Seconds saved on e4caaf4e | Risk | Owner |
| --- | --- | --- | --- |
| Web chunk calls fan out, 6 to 8 workers | 181 to 185 | Low: one new helper, store and seq stay on one thread | `extract.py` (with `steps.fan_out`) |
| OpenAlex batches fan out, 3 to 4 workers | about 7 | Low: same helper, plus a 5 per second cap | `lanes/openalex.py` |
| Lanes side by side | 7 to 18 | High: two writers, seq race, new publish order | `search.py` |

Projected search after the first two: 7 (parse) + 0.6 + 11 (OpenAlex) + 2.2 + 43 to 47 (web) + 1.3 = 65 to 69 s. After all three: 54 to 58 s.

### 5. Fewer pages, smaller pages or less text (question 5)

Script `scratchpad/quality/speed/q5b.py` and `q5c.py` over the 25 searches with web hits.

- **Every page rank yields people.** Hits per rank 1 to 10: 150, 114, 190, 125, 118, 81, 93, 203, 262, 190. Gold picks found by the web lane came from ranks 2, 2, 2, 4, 8 and 9 (5 distinct gold candidates in 4 searches). Reading 5 pages instead of 10 would lose 1 of those 5 and halve the lane's people. The sample is small.
- **Later chunks yield people.** Of 1,526 web hits, 1,290 came from chunk 1, 235 from chunk 2 and 1 from chunk 3. One gold pick came only from chunk 2. Dropping later chunks saves about 9 calls a search and loses 15% of web people, including that pick.
- **LinkedIn profile pages give little after chunk 1.** Of 79 hits on `linkedin.com/in/` pages, 64 came from chunk 1 and 15 from later chunks. Today 4 of 10 pages were such profiles and used 8 of 19 calls. Their later chunks returned 123, 128 and 172 output tokens on three of the four, meaning few or no people. A rule "one chunk for a profile page" saves about 4 calls a search. Whether those 15 later hits are useful people or noise is not measured.
- **The 48-character tail.** Letting a final piece under about 500 characters join the chunk before it (a chunk of up to 6,500 characters) removes calls like today's 3.0 s tail call. It affects 7 of 225 pages.
- **Less text per page does not buy much.** Call time depends on output tokens (finding 1), not input. Sending less text trims few seconds and risks people.
- **Less hidden output buys the most.** If about 84% of output tokens are hidden, the fit predicts a mean call of 3.3 + 3.4 × 0.2 × 2,568 / 1,000 = 5.0 s instead of 12.0 s. Today's 19 calls would take 95 s in a row, 28 s with 4 workers and 18 s with 6 (`sim.py`). The parse call would drop by a similar share. Not measured: whether the CLI is thinking, and whether answers stay as good without it.

## Recommendations

1. **Fan out the web lane's chunk calls** with `steps.fan_out` and a buffered child recorder, 6 workers by default. Owner: `extract.py` for the change, `steps.py` for the helper. The test is in finding 3.
2. **Measure hidden output in the `claude -p` call.** Keep the full CLI JSON of 3 extract calls (the `result`, `usage` and any thinking fields), then rerun the same 3 chunks with thinking off, through whatever switch the CLI offers. Compare call time and the people found. Owner: `llm.py`. Only the owner may run the CLI.
3. **Fan out OpenAlex batch fetches** with the same helper, 3 workers, at most 5 requests a second. Owner: `lanes/openalex.py`.
4. **One chunk for LinkedIn profile pages, and join a short tail chunk.** Owner: `extract.py`. Check first that the 15 later-chunk profile hits are noise.
5. **Log time to first person and the web lane's wall time per search** on `/debug/stats`, and add a speed row to the gold runner so each change has a before and after. Owner: the gold runner script.
6. **Lanes side by side last**, after 1 to 3 have numbers. Owner: `search.py`.

## Open decisions

- Worker count for `claude -p`: 6 is a guess that fits memory. The subscription's parallel limit decides it, and only a live run shows it.
- Whether to turn thinking off for extract and parse, if recommendation 2 shows it is thinking. That trades answer quality for speed and needs a gold run to decide.
- Whether to keep reading later chunks of LinkedIn profile pages.
- Whether lanes side by side is worth its risk once the web lane takes under 50 s. The saving then is 7 to 11 s.
- Aside, outside speed: `net.USER_AGENT` (`src/fn/net.py:23`) sends the repository URL, which names the owner, to every host the app calls.
