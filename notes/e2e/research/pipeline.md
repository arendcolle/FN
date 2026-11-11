# How one search runs, and what FN logs about it

Read at commit e1250ca. All references are repo-relative `file:line`. This note describes today's behaviour only.

## Summary

`POST /searches` stores a `queued` row on the uvicorn event-loop thread, then hands the id to a one-thread pool (`worker.py:47`). That worker thread runs `search.run`: parse, four lanes in a fixed order, resolve, rank, save. Each is a `run_step`, which writes a `step_runs` row, a `step_payloads` row and one `step_calls` row per outbound HTTP or LLM call. Every step, and every lane, runs one after another on that thread. Queued searches wait in a FIFO. A restart marks unfinished searches `interrupted` and never resumes them. The net client caches responses on disk and can replay them. The LLM client runs `claude -p` on the subscription and can replay fixtures. Logs go to `var/log/fn.log` and into the step row.

## 1. Call tree from POST to done

| Hop | Where | Thread |
|---|---|---|
| Process start: `serve()` loads settings, calls `setup_logging`, builds the app, runs uvicorn | `web/app.py:839-845` | main thread |
| `create_app` builds `Store`, `Worker` (new `boot_id`, git sha, one-thread pool) | `web/app.py:797-800`, `worker.py:45-47` | main thread |
| Lifespan start: `store.migrate()`, then `worker.sweep()` | `web/app.py:803-806` | uvicorn event-loop thread |
| `POST /searches` handler `create` validates the question (1000 characters max) | `web/app.py:674-683` | event-loop thread |
| `worker.create_search` builds a `Search` with `status="queued"`, code sha, dirty flag, `llm_mode`, `boot_id`, redacted settings JSON, and inserts it | `worker.py:49-61`, `store.py:89-100` | event-loop thread, its own SQLite connection |
| `worker.submit` puts `execute` on the pool and adds a done callback | `worker.py:63-67`, `web/app.py:686` | event-loop thread |
| Handler returns 303 to `/searches/{id}` | `web/app.py:687` | event-loop thread |
| `Worker.execute` loads the row, sets `running`, builds a `StepContext` | `worker.py:75-88` | `fn-worker_0` thread |
| `search.run(ctx, found)` | `worker.py:90`, `search.py:24-36` | `fn-worker_0` |
| Step `parse` (LLM), or `skip_step` when the search already has chips | `search.py:27-31` | `fn-worker_0` |
| `set_search_chips(..., "parsed")` after a real parse | `search.py:31` | `fn-worker_0` |
| Steps `lane:seeds`, `lane:openalex`, `lane:web`, `lane:linkedin`, in `LANES` order | `search.py:32-33`, `lanes/__init__.py:15` | `fn-worker_0` |
| Step `resolve`, then `rank` | `search.py:34-35` | `fn-worker_0` |
| Step `save`: `store.save_candidates` replaces candidates and match flags in one transaction | `search.py:20-21,36`, `store.py:374-392` | `fn-worker_0` |
| `execute` sets status `done` and `finished_at` | `worker.py:95-96` | `fn-worker_0` |

Other facts about the path:

- A rerun (`POST /searches/{id}/rerun`) follows the same tree. It creates a search with edited chips and `rerun_of`, so `parse` is recorded as `skipped` (`web/app.py:737-748`, `search.py:27-28`).
- The browser polls. A page for a `queued` or `running` search carries `refresh=2`, a 2-second page reload (`web/app.py:438`).
- The same `Worker.execute` also runs the CLI search `python -m fn.search` (`search.py:39-57`), `fn-gold` (`gold.py:217,353`) and `fn-orgs` (`orgjob.py:22-24`). Those call `execute` directly on the calling thread, with no pool and no sweep.
- Only `Exception` is caught in `execute` (`worker.py:91`). The failure path stores the redacted traceback in `searches.error` and logs it as `fn.worker` at ERROR (`worker.py:92-94`).
- `submit` adds a done callback for anything that escapes `execute`, for example a database error while writing the status. It logs `search <id> crashed outside its guard` (`worker.py:63-73`).

## 2. Steps, `run_step` and `StepContext`

A step is a function `fn(ctx, inp) -> out` where `inp` and `out` are frozen Pydantic models (`steps.py:137`). `search.py` names six kinds: `parse`, `lane:<name>` (one per lane), `resolve`, `rank`, `save`.

`StepContext` is a frozen dataclass: `search_id`, `store`, `llm`, `http`, `now`, `new_id`, `log`, `settings` (`steps.py:26-35`). One is built per search (`worker.py:85-88`) and passed to every step. It holds shared objects, not copies.

`run_step` does this (`steps.py:137-182`):

1. Builds a `StepRun` with status `running`, a new id, `seq = MAX(seq)+1` for the search (`store.py:132-134`), the step name, `started_at` and the input model's class name.
2. `store.start_step` inserts the `step_runs` row and the `step_payloads` row with `input_json` (redacted) in one transaction (`store.py:136-145`). The row exists before `fn` starts.
3. Creates a `CallRecorder`, sets it in a `ContextVar`, and attaches a `_LogCapture` handler to the root logger (`steps.py:150-153`).
4. Calls `fn(ctx, inp)`, then dumps the output to redacted JSON (`steps.py:157-158`).
5. In `finally`, removes the handler, resets the ContextVar and calls `store.finish_step` with status, `ended_at`, `output_model`, errors, totals and the log text (`steps.py:165-182`).

On any `BaseException` the step stores `error_type`, `error_message` and a redacted `traceback` and re-raises (`steps.py:161-164`). `skip_step` writes one `skipped` row with input and output payloads and no calls (`steps.py:185-195`).

### What is stored, and where

| Data | Table and column | Source | Notes |
|---|---|---|---|
| Step start and end time | `step_runs.started_at`, `ended_at` | `ctx.now()` | ISO text, UTC. No duration column. The debug page computes `ended_at - started_at` and shows `%.2f s` (`web/app.py:104-107`) |
| Step status | `step_runs.status` | `running`, `ok`, `error`, `skipped`, `interrupted` | `contracts.py:29` |
| Step cost | `step_runs.cost_usd` | sum of the step's call `cost_usd` | `steps.py:176` |
| Step tokens | `step_runs.tokens_in`, `tokens_out` | sum over calls | `steps.py:177-178` |
| Model and prompt hash | `step_runs.model`, `prompt_sha` | last call that passed them | `steps.py:74-75`. A step with several LLM calls keeps only the last |
| Step input | `step_payloads.input_json` | `inp.model_dump_json()`, redacted | `steps.py:149` |
| Step output | `step_payloads.output_json` | `out.model_dump_json()`, redacted | `steps.py:158`. Null on error |
| Models used | `step_runs.input_model`, `output_model` | class names | `steps.py:146,172` |
| Log lines | `step_runs.log` | `_LogCapture`, joined with newlines | Format `%(asctime)s %(levelname)s %(name)s %(message)s` (`steps.py:20`). Includes any log record reaching the root logger while the step runs |
| Traceback | `step_runs.traceback`, `error_type`, `error_message` | `traceback.format_exc()`, redacted | `steps.py:162-163` |
| Contracts version | `step_runs.contracts_version` | constant `"2"` | `contracts.py:13,395` |
| One call | `step_calls` row, key `(step_run_id, seq)` | `CallRecorder.record` | `steps.py:56-76` |

A `step_calls` row holds `kind` (`http` or `llm`), `request`, `status`, `duration_ms`, `response_sha`, `response_path`, `tokens_in`, `tokens_out`, `cost_usd` and `error` (`migrations/001_init.sql:51-65`). The `request` is the redacted text:

- HTTP: `GET <url>` or `POST <url> <compact JSON body>`, prefixed `cache ` or `replay ` when served from disk (`net.py:124,182,195`).
- LLM: `<task> <sha12>: <full user turn>` (`llm.py:103,137`). The full page text sent to the model is stored here.

The response body is not stored in the database. The row keeps the SHA-256 and the cache file path (`net.py:124,160-161`). LLM answers are not stored per call. They exist in the step's `output_json` after parsing, and in a fixture file only in `record` mode.

### Other places a search is stamped

`searches` holds `created_at`, `finished_at`, `status`, `error`, `code_sha`, `dirty`, `llm_mode`, `settings_json` (secrets replaced by `***`), `boot_id`, `rerun_of`, `chips_json`, `chips_origin`, `kind` and `contracts_version` (`migrations/001_init.sql:1-19`, `002_orgs.sql:1`). There is no total cost or duration column on `searches`. The debug page sums steps.

### `request_errors`

The HTTP middleware `guard` catches an unhandled exception from a route, stores `(id, route, traceback, at)` in `request_errors`, logs it as `fn.web` at ERROR, and returns a 500 page with the traceback (`web/app.py:821-838`, `store.py:187-195`). The list is at `GET /debug/errors` (`web/app.py:790-794`). It is separate from step errors: a search failing inside the worker never reaches this table.

### Redaction

`redact` replaces each secret value by `***` by plain string replacement (`steps.py:38-42`). `Settings.secrets()` lists every non-empty `SecretStr` field (`config.py:34-37`). It is applied to payloads, calls, errors, tracebacks, step logs, the settings JSON and the log file filter.

## 3. Lanes: serial, and what would break in parallel

Lanes run serially, in list order `seeds, openalex, web, linkedin`, in a list comprehension on the worker thread (`search.py:33`, `lanes/__init__.py:15`). Each lane is one `run_step`, so each has its own `step_runs` row and its own `seq`. The pool has `max_workers=1` (`worker.py:47`), so two searches never run at once either.

A lane that raises fails the whole search. The exception passes through `run_step` and `search.run` and reaches `execute`, so later lanes, `resolve`, `rank` and `save` never run (`steps.py:161-164`, `worker.py:91-94`). Lanes that expect trouble, for example a missing key or a cache miss, return a `LaneOut` with a `considered` note instead of raising (`lanes/linkedin.py:254-258`, `lanes/web.py:126-129`).

What would break if two steps ran at the same time (inference from the code, not tested):

| Shared thing | Why it breaks | Reference |
|---|---|---|
| `ContextVar` recorder | A new thread starts with an empty context, so `current_recorder()` raises `RuntimeError` there. Asyncio tasks would copy it, and each task's `reset(token)` must match its own `set` | `steps.py:79-87,152,167` |
| Root logger handler | `_LogCapture` is added to the root logger and filters by `_recorder.get() is self.recorder`. Each concurrent thread would see only its own records, but records from a thread without the variable go to the log tagged `- -` | `steps.py:125-134`, `steps.py:100` |
| `CallRecorder.calls` and `seq` | `seq = len(self.calls) + 1` and `calls.append` are not atomic. Two calls in one step from two threads can get the same `seq`, which is the primary key part | `steps.py:66-75`, `001_init.sql:64` |
| Step `seq` | `MAX(seq)+1` read, then insert in a later transaction. Two steps of one search could both get the same value and violate `UNIQUE (search_id, seq)` | `store.py:132-145`, `001_init.sql:42` |
| SQLite connection | `Store.conn` is thread-local, so a second thread gets its own connection (`check_same_thread=True` forbids sharing one). Write transactions use `BEGIN IMMEDIATE`, so writers wait up to `busy_timeout=5000` ms, then fail | `store.py:57-70,76-87`, `db.py:12-17` |
| Transactions held across slow work | `web.py` lane opens `ctx.store.tx()` at `:96` and `:146`; `tx()` joins an open transaction on the same connection | `store.py:76-80`, `lanes/web.py:96,146` |
| `httpx.Client` in `net.Client` | One client, shared. httpx clients allow threads, but the per-call `recorder` is looked up from the ContextVar | `net.py:69-70,118` |
| `geo._loaded` | A module-level dict keyed by HTTP client, filled on first use with no lock | `geo.py:52-56` |
| `ClaudeCli` | Starts a process per call. No shared state. Subscription rate limits are not handled in the code | `llm.py:109-121` |
| Cache files | Written to a temp file then `os.replace`d, so two writers of the same key do not corrupt a file | `net.py:156-159` |

## 4. Queue, pickup, interrupt, rerun, process start

**Queue.** `ThreadPoolExecutor(max_workers=1, thread_name_prefix="fn-worker")` holds the queue in memory (`worker.py:47`). A search is a `queued` row in `searches` plus a pending future. The queue has no limit and no priority.

**Pickup.** The pool thread calls `execute`, which sets `running` (`worker.py:84`). There is no timestamp for "started running" on the search row. The first step's `started_at` is the closest.

**Interrupt.** There is no cancel and no stop button. A step runs until it ends, fails or hits a call timeout (30 s default read timeout for HTTP, 60 s or 120 s for the LLM, see sections 5 and 6). Shutdown calls `pool.shutdown(wait=True)`, so stopping the server waits for the running search and every queued one (`worker.py:103-106`, `web/app.py:806-808`). If the process dies instead, rows stay `running` and `queued` until the next start.

**Process start.** `Worker.__init__` makes a new `boot_id` (uuid4) and reads `git rev-parse HEAD` and `git status --porcelain` once (`worker.py:45-46,29-36`). Every search created in this boot stores that `boot_id` (`worker.py:57`). In the lifespan, after `migrate()`, `worker.sweep()` runs `Store.sweep(boot_id, now)` (`web/app.py:803-806`, `store.py:197-216`). In one transaction it:

- finds searches with status `queued` or `running` and `boot_id != current`,
- sets them to `interrupted` with `finished_at`,
- sets their steps with status `running` to `interrupted` with `ended_at`.

Only the server sweeps. `fn.search`, `fn-gold` and `fn-orgs` do not. Interrupted searches are not requeued. The page tells the user "FN was restarted while this search ran" and offers `Try again`, a form that POSTs the question to `/searches` as a new search that parses again (`web/app.py:394-408`). The debug page offers a rerun with edited chips, which skips parse (`web/app.py:737-748`).

**Search kinds.** `kind` is `search` or `job`. `list_searches` leaves jobs out (`store.py:113-116`). `fn-orgs` is a job that goes through `execute` with its own steps (`orgjob.py:22-24`).

## 5. HTTP client (`net.py`)

One class, `net.Client`, for all outbound HTTP. It exposes `get` and `post`. Every call goes through `_send` and needs a running step, otherwise `current_recorder()` raises `RuntimeError("an outbound call was made outside a step")` (`net.py:114-118`, `steps.py:82-87`).

| Topic | Behaviour | Reference |
|---|---|---|
| Schemes | Only http and https. Others raise `HttpError` before any request | `net.py:76-77` |
| Timeouts | 30 s total, 10 s connect. `post(timeout_s=)` replaces the 30 s, not the 10 s connect | `net.py:17,74` |
| Redirects | Not followed | `net.py:69` |
| Size cap | 5 MB, checked while streaming. Over it raises `HttpError` | `net.py:18,93-103` |
| User agent | `FN/0.1 (https://github.com/arendcolle/FN) httpx/<version>` | `net.py:23` |
| Keys | Per host from `KEYS`: OpenAlex `Authorization: Bearer` (optional), Parallel `x-api-key` (required), Apify `Authorization: Bearer` (required). Added only over https. A missing required key raises `MissingKey` before any request | `net.py:34-38,80-91` |
| Where keys come from | `config.from_env`: the env var named like the field (`OPENALEX_API_KEY`, `PARALLEL_API_KEY`, `APIFY_TOKEN`), else a Keychain lookup with `security find-generic-password -a $USER -s NAME -w` (10 s timeout) | `config.py:40-51,58-59,68-70` |
| Retries | A GET retries a 429 or 503 once. A POST retries a 429 only. Needs a numeric `Retry-After` of at most 30 s, then waits with `time.sleep`. A second failure or a longer wait raises `HttpError` that names the wait | `net.py:19,135,163-173` |
| Other errors | A 5xx without `Retry-After` or a timeout is not retried. Error text holds the first 300 characters of the body, redacted | `net.py:20,141-144,167-171` |
| Rate limits | None in the client. No throttle, no request spacing, no concurrency cap. Calls are serial because the worker is | `net.py` (no code) |
| Cache file | `var/cache/<sha256 of key>.json`. GET key is the full URL with query. POST key is `POST <url>\n<body JSON with sorted keys>`. Written to a temp file and renamed | `net.py:117,156-159,196` |
| Cache expiry | None. Files live until deleted | `net.py` (no code) |

### Cache modes

`FN_HTTP` gives the global mode (`live` or `replay`). `cache` on `post` gives the per-call mode (`net.py:119-129`).

| Setting | Behaviour |
|---|---|
| `http_mode=replay` (any call) | Serves the cache file. A miss records an error call and raises `CacheMiss`. Nothing goes out and no key is checked |
| `cache="refresh"` (default; always for GET) | Calls out, writes the cache file |
| `cache="prefer"` (POST) | Serves the file if present, else calls out and writes it |
| `cache="only"` (POST) | Serves the file if present, else raises `CacheMiss`. Never calls out |

A GET always uses `refresh` (`net.py:183`). In live mode a GET therefore always calls out, and the cache it writes only helps a later replay run.

`keep(body)` returning False leaves a live answer uncached (Apify with no profiles) (`net.py:149,155`, `lanes/linkedin.py:250`).

### Recording and cost

| Call outcome | `step_calls` fields | Reference |
|---|---|---|
| Served from cache or replay | `request` prefixed `cache ` or `replay `, `duration_ms=0`, `status=200`, `cost_usd=0.0`, sha and path | `net.py:122-126` |
| Cache miss | `duration_ms=0`, `error="not in the response cache"` | `net.py:128` |
| Live 2xx | measured `duration_ms` (monotonic clock), `status`, sha, path (if kept), `cost_usd` | `net.py:138-161` |
| Live non-2xx | `status`, `error` with the body start | `net.py:164-169` |
| Transport error or over 5 MB | `error="<ExceptionType>: <message>"`, no status | `net.py:141-144` |
| Missing key | `duration_ms=0`, `error` | `net.py:130-134` |
| `cost` or `keep` raised on a 2xx | the call is recorded with status, sha and the error, nothing cached, exception re-raised | `net.py:151-154` |

Cost for a live answer: the `cost(body)` callback if given, else OpenAlex's `meta.cost_usd` from the JSON body, else None (`net.py:106-112,150`). The callbacks:

- Parallel: `usage_cost` applies `PRICES = {"sku_search": 0.001, "sku_extract_excerpts": 0.001}` to the response `usage` (`lanes/web.py:30,67`).
- Apify: `estimate` is `PAGE_USD + PROFILE_USD * profiles` because the actor reports no cost (`lanes/linkedin.py:32,124-126`).

## 6. LLM client (`llm.py`)

`StructuredLLM` is a protocol with one method, `structured(task, data, schema) -> LLMResult[T]` (`llm.py:27-28`). Callers are `parse.run` (task `parse`) and `extract.mentions` (task `extract`, one call per chunk) (`parse.py:73`, `extract.py:136`). `data` values go to the model as `<name>...</name>` blocks. A value holding its own closing tag raises `TagError` (`llm.py:53-62`). The system prompt is the file `src/fn/prompts/<task>.md` (`llm.py:49-50`).

### Modes (`FN_LLM`, default `live`)

| Mode | Class built by `from_settings` | Behaviour | Reference |
|---|---|---|---|
| `live` | `ClaudeCli` | Calls the CLI, no fixtures read or written | `llm.py:183-184` |
| `record` | `FixtureLLM` over a `ClaudeCli` | Always calls the CLI, writes the fixture, returns the result | `llm.py:163-168` |
| `replay` | `FixtureLLM`, no CLI | Serves the fixture. A miss raises `FixtureMissing` with the key and the start of the prompt | `llm.py:169-178` |
| `prefer` | `FixtureLLM` over a `ClaudeCli` | Serves the fixture if present, else calls the CLI. Never writes | `llm.py:170-171` |

`FixtureLLM` requires a CLI for `record` and `prefer` (`llm.py:152-156`). `ClaudeCli` refuses to start when `FN_ENV=test` (`llm.py:77-79`).

### Fixtures

Directory `tests/fixtures/llm/` under the repo root (`llm.py:186`). File name `<task>-<first 16 hex of prompt sha>.json`, content `{key, task, prompt, result}` (`llm.py:161,166`). The prompt sha is SHA-256 over system prompt, user turn, schema JSON and model name joined by NUL bytes (`llm.py:65-67`). Changing a prompt file, the schema or the model changes every key, so old fixtures stop matching.

### The CLI call

Command: `claude -p --model <model> --output-format json --json-schema=<schema> --tools= --setting-sources= --strict-mcp-config --no-session-persistence --system-prompt=<text>`. The user turn goes on stdin (`llm.py:82-87,116`). The child gets only `PATH, HOME, USER, LANG, TMPDIR`, and its own process group (`llm.py:20,107-112`). Timeout 60 s, or 120 s for `extract` (`llm.py:21-22,98`). On timeout the whole group gets SIGKILL (`llm.py:117-121`).

Failures raise `LLMCallError` for: no start, timeout, non-JSON output, `is_error` or non-zero exit, and no `structured_output`. Each is recorded as an `llm` call with the error before it raises (`llm.py:100-131`). A schema break raises Pydantic `ValidationError` after the successful call was recorded (`llm.py:139`).

### Model ids and cost

- One model id appears in code: `MODEL = "haiku"` (`llm.py:23`). It is the alias passed to `--model`. The recorded model is the first key of the result's `modelUsage`, else the alias (`llm.py:134`). The real id string therefore comes from the CLI output.
- `tokens_in` is `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. `tokens_out` is `output_tokens` (`llm.py:132-133`).
- `cost_usd` is the CLI's `total_cost_usd`. The result says `billing="subscription"` (`llm.py:135,141`). The subscription is not charged per call, so this is the list-price equivalent.
- A replayed fixture records `duration_ms=0`, `status=0`, and the original `cost_usd`, tokens and model from the fixture file, not zero (`llm.py:174-177`). A replay run therefore shows the cost of the recording run in its steps.

## 7. Settings: every `FN_*` variable

`config.from_env` reads these (`config.py:54-73`). Unset means the `Settings` default applies.

| Variable | Field | Default | Effect | Reference |
|---|---|---|---|---|
| `FN_VAR` | `var_dir` | `<repo>/var` | Root of the database (`fn.sqlite3`), `cache/`, `log/`, `gold/` | `config.py:18,31-32` |
| `FN_HOST` | `host` | `127.0.0.1` | Bind address. `serve()` exits unless it is `127.0.0.1` or `::1` | `config.py:20`, `web/app.py:841-843` |
| `FN_PORT` | `port` | `8765` | Bind port | `config.py:21` |
| `FN_ENV` | `env` | `dev` | `dev` or `test`. `test` makes `ClaudeCli` refuse to start | `config.py:22`, `llm.py:78` |
| `FN_LLM` | `llm_mode` | `live` | `live`, `record`, `replay`, `prefer` (section 6) | `config.py:23` |
| `FN_HTTP` | `http_mode` | `live` | `live` or `replay` (section 5) | `config.py:24` |
| `FN_LINKEDIN` | `linkedin_live` | `False` | Only the exact value `1` turns it on. On: LinkedIn POST uses `cache="prefer"` (cache, else a paid Apify run). Off: `cache="only"`, and a miss gives a note "off" | `config.py:71`, `lanes/linkedin.py:247-257` |

Other settings fields are not FN_* variables:

- `OPENALEX_API_KEY`, `PARALLEL_API_KEY`, `APIFY_TOKEN`: env var or Keychain (`config.py:68-70`).
- `root` (repo root) and `mode` (`local` only) have no env var (`config.py:17,19`).
- `FN_ENV=dev` allows live mode with the real services. Nothing else in `src` reads `os.environ`, except `ClaudeCli` copying five names into the child env (`llm.py:107`).

## 8. Logging to files under `var/log`

`setup_logging` runs only from `serve()` (`web/app.py:844`). It does not run for `fn.search`, `fn-gold` or `fn-orgs`, whose log lines reach only the step rows.

| Item | Detail | Reference |
|---|---|---|
| File | `var/log/fn.log` | `steps.py:113-115` |
| Rotation | `RotatingFileHandler`, 2,000,000 bytes, 5 backups (`fn.log.1` to `.5`) | `steps.py:115` |
| Second sink | A `StreamHandler` to stderr with the same format | `steps.py:116` |
| Format | `%(asctime)s %(levelname)s %(name)s [%(search_id)s %(step)s] %(message)s`. Example: `... INFO fn.step [<search id> parse] calling with ***` | `steps.py:118-119`, `tests/test_steps.py:127` |
| Tag | `search_id` and `step` come from the running step's recorder, else `-` and `-` | `steps.py:98-100` |
| Redaction | A filter formats the message, redacts it, and turns exception info into redacted `exc_text` | `steps.py:90-107` |
| Level | Root at INFO, `httpx` at WARNING. `fn` logger is set to INFO at import | `steps.py:23,121-122` |
| Directory mode | `var` and `var/log` created with mode 0700 | `steps.py:112-114` |
| uvicorn | `log_config=None`, so uvicorn's loggers propagate to the root handlers | `web/app.py:845` |

What reaches the file, by logger name: `fn.worker` ERROR for a failed or crashed search (`worker.py:73,93`), `fn.web` ERROR for a request error (`web/app.py:834`), `fn.step`, `fn.parse` (span moves), `fn.lanes.web` and lane INFO lines, `fn.step` warnings from lanes (`parse.py:50`, `lanes/linkedin.py:256`, `lanes/web.py:127`). There is no per-call or per-step timing line in the file. Timings and costs live in SQLite only (`step_runs`, `step_calls`).

Files under `var/` that other code writes:

| Path | Writer | Reference |
|---|---|---|
| `var/fn.sqlite3` (+ WAL files) | `Store` | `config.py:31-32`, `db.py:12-17` |
| `var/cache/<sha>.json` | `net.Client` | `net.py:67,156-159` |
| `var/log/fn.log*` | `setup_logging` | above |
| `var/gold/<timestamp>/report.md`, `top5.csv` | `fn-gold` | `gold.py:335,361` |

## 9. How long each step takes in practice

The code and tests state limits, not measured times. Measured times appear only in the notes.

| Step | Stated in code or tests | Measured, where stated |
|---|---|---|
| any HTTP call | 30 s read timeout, 10 s connect (`net.py:17`) | none in code |
| `lane:openalex` | up to 4 author pages of 200 per institution, 1 works page of 100 per topic, then batches of 100 ids (`lanes/openalex.py:28-32,85,97,109`) | one probe: singleton author lookups 0.21 to 0.45 s each (`notes/research/mvp-tech-reference.md:557`) |
| `lane:web` | Parallel Extract call timeout 90 s; one Haiku `extract` call per 6,000-character chunk, 120 s timeout each (`lanes/web.py:27`, `llm.py:22`) | median 186 s per search, at most 462 s, 88 minutes over 28 gold cases (`notes/mvp0/progress.md:30`). GS-02 took 190 s for 14 Haiku calls over 10 pages (`notes/mvp0/architecture.md:241`) |
| `lane:linkedin` | Apify run timeout 240 s, call timeout 290 s, $0.25 charge cap (`lanes/linkedin.py:28-30`) | none stated |
| `parse` (one Haiku call) | 60 s timeout (`llm.py:21`) | one test call took 3 s (`notes/mvp0/architecture.md:273`) |
| `seeds`, `resolve`, `rank`, `save` | none | none stated |

The tests (`tests/test_worker.py`, `test_steps.py`, `test_net.py`, `test_llm.py`) use stubs, a mock transport and a fake `sleep`. They assert no durations beyond the timeouts above (`tests/test_llm.py:197-209`, `tests/test_net.py:78,380`). To get timings for a real search today: the debug page `GET /debug/searches/{id}` lists duration, cost and model per step (`web/app.py:488`), and `GET /debug/steps/{id}/calls` lists each call with its `duration_ms` (`web/app.py:528`).

## Tests that pin this behaviour

| File | Pins |
|---|---|
| `tests/test_worker.py` | sweep marks only earlier-boot queued and running searches and their running steps; failures outside a step fail the search; redaction in log and error; unknown id raises `LookupError`; `submit` runs to `done`; settings stored redacted |
| `tests/test_steps.py` | step row is `running` while `fn` runs; error steps store traceback; totals of cost, tokens, model and prompt sha; secrets absent from payloads, calls, errors, log text and `fn.log`; log line tags |
| `tests/test_net.py` | Retry-After rules, replay, cache file naming, key per host over https, `MissingKey`, `cache` modes, `keep`, `cost`, atomic cache write, 300-character error bodies, per-call timeout |
| `tests/test_llm.py` | replay miss, record then replay, stdin not argv, error results, process-group kill, `prefer`, per-task timeouts, refusal under `FN_ENV=test` |
