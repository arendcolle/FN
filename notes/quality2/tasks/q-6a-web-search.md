# Task Q-6a: find pages through switchable backends and checked queries

## Goal

Every web search goes to Parallel, whose limits will not grow, and without a key FN finds no web page at all (`src/fn/lanes/web.py:126-128`). Query wording changed results more than the route did: a Dutch query gave the two best on-target pages of the test, and dropping "Belgian" lost the tie on every route (`research/local-search.md`). The Claude web search took 12 to 22 s a query and about 1 in 10 of its links was dead (same note). This task puts three backends behind `websearch.find`, picks one with a setting, falls back when the chosen one raises or is off, and checks the web queries the parse step writes. Decisions W1 and W2 in `design.md`, with the ruling after the live check of 2026-11-12: the DuckDuckGo adapter is not built in this round, so there is no DuckDuckGo spacing, daily counter or migration 013. Owner: `websearch.py`. Needs Q-1 (it adds `Chips.queries`) and Q-5 (it adds `websearch.py` and `websearch.rule_queries`). Q-6b reads pages locally after this.

## What to build

### `src/fn/contracts.py` and `src/fn/config.py`

- `SearchBackend = Literal["parallel", "searxng", "claude"]` next to `LLMMode` (line 46).
- `class WebResult(Model): url: str; title: str = ""` and `class WebResults(Model): results: list[WebResult] = []`.
- `HttpClient.get` (line 87) gains `*, keep: Callable[[bytes], bool] | None = None`.
- `Settings` (`src/fn/config.py:14`) gains `search_backend: SearchBackend | None = None` and `searxng_url: str | None = None`; `from_env` reads `FN_SEARCH` and `FN_SEARXNG_URL`.

### `src/fn/net.py`

- `get(url, params=None, *, keep=None)`: `keep` as `post` has it. A body for which `keep` is false is returned and not cached.

### `src/fn/llm.py` and `src/fn/prompts/websearch.md`

- `TOOLS = {"websearch": "WebSearch"}`, `TIMEOUTS["websearch"] = 90`. `ClaudeCli.argv(system, schema_text, tools: str = "")` writes `f"--tools={tools}"` in place of `"--tools="` (line 85); `structured` passes `TOOLS.get(task, "")`. Every other task's argv is unchanged.
- The prompt, word for word: `You find web pages for one search query. Run the web search tool once with the query in <query> exactly as it is written. Return the results it gives, in their order, each with its url and its title, at most 10. Never invent a URL and never return a page the search did not give.`
- Recording rides on what exists: `FixtureLLM` records each answer in `var/llm` in live mode and replays it by prompt hash (`src/fn/llm.py:158-178`), and the call lands in the step's `step_calls` with its cost. Builders test this adapter with a stub LLM only.

### `src/fn/websearch.py` (Q-5 made it; owner of finding pages)

- `LABELS = {"parallel": "Parallel Search", "searxng": "SearXNG", "claude": "Claude web search"}`, `SITE_BACKENDS = ("parallel", "searxng")`, `MAX_QUERY_CHARS = 200`, `COUNTRY_WORDS`: the `name_key` of belgian, belgians, belgium, flemish, flanders, belgische, belgisch, belgie, belgië, vlaamse, vlaams, vlaanderen, vlaming, vlamingen, belge, belges, belgique, flamand, flamande, flamands.
- `class Stopped(RuntimeError)` (a backend that is off or cannot run) and `class LayoutChanged(RuntimeError)`.
- `@dataclass(frozen=True) class Hit`: `url: str`, `title: str | None`, `snippet: str`, `published: str | None`, `raw: dict`.
- `backend_of(settings: Settings) -> SearchBackend`: `settings.search_backend`, else "parallel" when `parallel_api_key` is set, else "claude".
- `secondary_backend(settings: Settings) -> SearchBackend`: `settings.search_backend or "claude"`. The lane without a tie and the lookup batch (Q-8) call it, so this rule has one owner.
- Adapters, each `(ctx, objective, queries) -> list[Hit]`, collected in `ADAPTERS: dict[SearchBackend, Callable]`:
  - `search_parallel`: today's Search post (`search_body`, `usage_cost`); the snippet is its excerpts joined by a blank line.
  - `search_searxng`: without `searxng_url`, `Stopped("SearXNG is off: searxng_url is not set")`. Else one `ctx.http.get(f"{url}/search", {"q": q, "format": "json"}, keep=answered)` per query; `results[].url`, `title`, `content`, `publishedDate`. A body that is not JSON with a `results` list raises `LayoutChanged`, and `answered(body)` is false for it, so it is not cached.
  - `search_claude`: without `ctx.llm`, `Stopped("no LLM for the Claude web search")`. One `ctx.llm.structured("websearch", {"query": q}, WebResults)` per query through `fan_out` with `ctx.settings.llm_workers`; non-http urls are dropped; the snippet is empty; every call failing raises the first error.
- `find(ctx, objective, queries, *, backend: SearchBackend | None = None, limit: int | None = None) -> Found`. The chain is the chosen backend (`backend or backend_of(ctx.settings)`), then "parallel" when the chosen one is `searxng` and a Parallel key is set, then "claude" unless chosen. `MissingKey` propagates at once. `Stopped`, `LayoutChanged`, `HttpError` or any error of the claude adapter adds a row `stage="query"`, `kept=False`, reason `f"{LABELS[b]} failed: {type(exc).__name__}: {exc}"`, then the next backend runs. When all fail, the first error is raised. Hits keep their order, a repeated url gives today's dropped row, and `limit` keeps the first `limit` unique urls. No hit gives `note=f"{LABELS[b]} returned no results; Extract not called"`.
- Reading stays as Q-5 built it: with a Parallel key, one Extract call over the kept urls; without one, each page's texts are its snippet as "Search excerpts". `Found` gains `backend: SearchBackend` (the one that answered) and `queries: list[str]` (the list sent).
- `queries(chips: Chips, *, tie: bool, backend: SearchBackend) -> list[str]`, owner of the final list. Version-1 chips give `rule_queries(chips)` unchanged (lead's ruling "Version-1 chips keep today's web queries"), so stored searches send the same Search body and replay from the cache. Version 2, in order: (1) `chips.queries` with white space collapsed, empty, over 200 characters and casefold repeats dropped; (2) a query holding `site:` stays only when `tie` and `backend in SITE_BACKENDS`, at most one; each dropped one is noted for step 5; (3) with `tie`, a query without a country word gets "Belgian " (lang en) or "Belgische " (lang nl) in front; without `tie`, country words are removed word by word; (4) with a place, a query whose folded text lacks the folded place text gets " {place.text}"; (5) no Dutch query, and each dropped site query, adds a rule Dutch query, `"Belgische " if tie else ""` plus the next of the role, topic and institution texts in that order, plus the place; (6) an empty list becomes `rule_queries(chips)` with step 3 and 4 applied, plus one rule Dutch query; (7) at most 5, with the first Dutch query moved to place 5 when it stands later.

### The lanes

- `lanes/web.py` `run`: `websearch.queries(chips, tie=True, backend=websearch.backend_of(ctx.settings))`. `collect` sets `LaneOut.query` to `"; ".join(found.queries)` and adds a row `stage="query"`, `kept=True`, reason `f"{LABELS[found.backend]}: {' | '.join(found.queries)}"`. `collect` notes a `websearch.Stopped` as it notes a `MissingKey`: one row with the message, no people, step ok.
- `lanes/web_topic.py`: `backend = websearch.secondary_backend(ctx.settings)`, with `websearch.queries(chips, tie=False, backend=backend)` and `find(..., backend=backend)`. The lane without a tie uses the Claude web search by default, so the Parallel calls per search stay as they are (ruling of 2026-11-12).

### `src/fn/score.py`

`run` (line 325) builds its replay `Settings` with `search_backend=os.environ.get("FN_SEARCH") or "parallel"`. Its settings hold no Parallel key, so without this `backend_of` picks "claude", the websearch call misses the fixtures and every replayed web lane is degraded. Stored searches recorded Parallel calls.

## Inputs a real run will meet

No Parallel key and no LLM; no Parallel key with an LLM (the Claude web search answers); the Claude web search failing on every query; SearXNG without an address; a SearXNG answer in HTML; SearXNG failing with and without a Parallel key; every backend failing; version-1 chips; a model list of 7, of empty strings, all in English, with two `site:` queries, with no country word, or with the country word in the no-tie lane; a place of two words; a Dutch query on place 6; a `site:` query sent to the Claude web search (dropped).

## Tests (each must fail without the change)

Fixture `tests/fixtures/http/websearch/searxng.json`, written by the builder with made-up names.

- New `tests/test_websearch.py`, over `net.Client` with `httpx.MockTransport` and a stub LLM: SearXNG off without an address, parsed from `searxng.json`, and its HTML answer raises `LayoutChanged` and is not cached; SearXNG failing with a key falls to Parallel with a failed row; without a key it falls to a stub LLM's `WebResults`; the Claude web search drops a non-http url; all failing raises the first error; `MissingKey` calls nothing else; `backend_of` for each setting; `queries` on each input of the list above, one row per case, version-1 chips among them.
- `tests/test_llm.py`: the websearch argv holds `--tools=WebSearch`; the parse argv still holds `--tools=`.
- `tests/test_net.py`: `keep` false leaves a GET uncached.
- `tests/test_web_topic.py`: with `search_backend=None` the lane asks the Claude web search, never Parallel.
- `tests/test_score.py`: a replayed version-1 search whose Search body is in the cache is not degraded.

## Existing tests that change

- `tests/helpers.py` `StubHttp.get(self, url, params=None, **options)`, so it takes `keep`. `make_settings` (line 28) sets `search_backend="parallel"`, so every existing test keeps today's route; a test of the Claude default passes `search_backend=None` explicitly.
- No other existing test may change; stop and report a failure.

## Hand check

`uv run python -m unittest` all green. `fn-score run <snapshot> --mode replay --allow-degraded --out <scratch>`: version-1 chips send the same Parallel bodies, so no new Search call misses the cache. The lead, live and paid: `FN_VAR=<copy> FN_SEARCH=claude FN_LLM=prefer FN_HTTP=prefer fn-gold <two dev case ids>`; read the `lane:web` and `lane:web_topic` query rows and the `websearch` calls with their cost in `/debug/stats`.

## Not doing

The DuckDuckGo adapter, its spacing, its daily counter and migration 013 (ruling of 2026-11-12). Local page reading (Q-6b). Docker or a SearXNG container. Choosing SearXNG engines. Merging two backends' results. Brave, Mojeek or any keyed backend. Translating chips by rule. A fallback on a short result list.
