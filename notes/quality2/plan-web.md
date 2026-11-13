# Plan: how FN searches the web, reads pages and grows its lists

This section covers decisions W1 to W4 and R9 of [design.md](design.md), with the lead's rulings on them and the ruling after the live check of 2026-11-12, which drops the DuckDuckGo adapter from this round. Five tasks follow the five of [plan-quality.md](plan-quality.md). Q-6 was too large for one task that merges alone, so it is split: Q-6a puts the backends and the query check behind `websearch.find`, Q-6b reads pages locally. Q-7 is split the same way, so the two one-page lists merge without the nonprofit officers: Q-7a adds the BelCham board and the embassy's advisors, Q-7b the Form 990 officers, last. Q-8 adds the web lookup of thin records.

## Changes to earlier tasks

Applied on 2026-11-13 to `tasks/q-1-prompts-and-contracts.md` and `tasks/q-5-lanes.md`. W2 makes the parse call write the web queries, which is a prompt change. It went into Q-1, so the parse prompt and its schema change once and recorded answers miss once.

- Q-1: `Chips.queries: list[WebQuery] = []` with `WebQuery(text, lang)`; the `queries` bullet in the parse prompt after `related`; `run` keeps `queries` as the model wrote them; `chips_from_form` gives edited chips `queries=[]`; the inputs and tests for queries; "queries (Q-6a)" under Not doing.
- Q-5, so the rule that writes queries has one owner (`websearch`, per the design's table): `rule_queries(chips: Chips) -> list[str]` lives in `src/fn/websearch.py`, both lanes and `web.request` call `websearch.rule_queries`, its test reads `websearch.rule_queries`, and Not doing names "the backends and the query check (Q-6a)". Q-6a later swaps both lane calls for `websearch.queries`.

Not applied here, because the pages track owns those files: `tasks/ui-2-person-page.md` line 17 and `tasks/ui-3-source-page.md` line 17, "for `page`, `seed_page` and `vendor_page`" becomes "for a kind in `present.PROSE`", so Q-8's `lookup_page` reads as a page.

## Tasks, in order

| Task | One line | Needs |
| --- | --- | --- |
| [Q-6a](tasks/q-6a-web-search.md) | Three backends behind `websearch.find` (Parallel, SearXNG, the Claude web search), one setting, the fallback, the checked query list | Q-1, Q-5 |
| [Q-6b](tasks/q-6b-page-reading.md) | `pageread.py`: robots.txt, the HTML and PDF reader, the failure rule; Extract only for failed pages; kind `page` | Q-6a |
| [Q-7a](tasks/q-7a-one-page-lists.md) | BelCham board and embassy advisors as seed lists | none (the lead's fixtures first) |
| [Q-7b](tasks/q-7b-nonprofit-officers.md) | Form 990 officers as a seed list, last among the lists | Q-7a merged (the lead's fixtures first) |
| [Q-8](tasks/q-8-thin-lookup.md) | `fn-enrich --kind web_person` over thin records, anchored facts under `lookup_page` | Q-6b |

Q-7a and Q-7b touch only `scripts/seeds/`, `data/seeds/irs990-orgs.csv` (Q-7b), lines of `seedload.SPECS` and new test files, so they can run at any time; Q-7b merges after Q-7a. Q-6a and Q-6b both change `net.py`, `contracts.py` and `websearch.py` and run one after the other. No task in this plan adds a migration.

## File map

| File | Q-6a | Q-6b | Q-7a | Q-7b | Q-8 |
| --- | --- | --- | --- | --- | --- |
| `src/fn/contracts.py` | `SearchBackend`, `WebResult(s)`, `HttpClient.get` | `page_source` kind and plain, `HttpClient.get` redirects | | | `LookupKind`, `SourceKind` |
| `src/fn/config.py` | `search_backend`, `searxng_url` | `page_reader` | | | |
| `src/fn/net.py` | `keep` on `get` | `HttpError.status`, `Redirect`, `redirects` | | | |
| `src/fn/llm.py`, `prompts/websearch.md` | tools per task, new prompt | | | | |
| `src/fn/store.py` | | | | | `thin_persons`, `lookups_since` |
| `src/fn/websearch.py` | adapters, chain, `queries` | reading, `source_of` | | | |
| `src/fn/pageread.py` | | new | | | |
| `src/fn/lanes/web.py`, `web_topic.py` | queries, backend | `collect` uses `source_of` | | | |
| `src/fn/enrich.py` | | | | | `web_person` |
| `src/fn/present.py`, `src/fn/gold.py` | | | | | `PROSE`, `EVENT_KINDS` |
| `scripts/seeds/`, `seedload.py` | | | two scripts, two `SPECS` | one script, one `SPECS` | |
| `tests/helpers.py` | `StubHttp.get` takes options | | | | |

## Interfaces

| Name | Type | Made by | Read by |
| --- | --- | --- | --- |
| `Chips.queries` | `list[WebQuery(text: str, lang: Literal["en", "nl"])]` | Q-1 | `websearch.queries` |
| `websearch.rule_queries(chips) -> list[str]` | Q-5's rule | Q-5 | `websearch.queries`, `web.request` |
| `SearchBackend` | `Literal["parallel", "searxng", "claude"]` | Q-6a | config, websearch, lanes |
| `Settings.search_backend` | `SearchBackend \| None`, None: Parallel with a key, else the Claude web search | Q-6a | `websearch.backend_of` |
| `Settings.searxng_url`, `page_reader` | `str \| None`; `Literal["local", "parallel"]` "local" | Q-6a, Q-6b | websearch |
| `websearch.find(ctx, objective, queries, *, backend=None, limit=None) -> Found` | `Found` gains `backend`, `queries` | Q-5, Q-6a | `web`, `web_topic`, `enrich` |
| `websearch.queries(chips, *, tie: bool, backend) -> list[str]` | at most 5; version 1 gives `rule_queries` unchanged | Q-6a | `web`, `web_topic` |
| `Page.local`, `Page.failed` | `bool`, `str \| None` | Q-6b | `websearch.source_of` |
| `websearch.source_of(page, fetched_at, kind=None) -> tuple[str, Source] \| None` | label and source | Q-6b | `web.collect`, `enrich` |
| `pageread.read_all(ctx, urls) -> list[Read]` | `Read(url, title, text, failed, truncated)` | Q-6b | websearch only |
| `Client.get(url, params, *, keep, redirects)` | as `post` for `keep` | Q-6a, Q-6b | websearch, pageread |
| `LookupKind` `web_person`, `SourceKind` `lookup_page` | new values | Q-8 | enrich, present, gold |

Owners, as in the design's table: `websearch.py` finds pages, picks the backend, falls back and checks the queries; `pageread.py` fetches and reads a page and checks robots.txt; the lanes store pages and read people; `enrich.py` owns the lookup. The lane without a tie and the lookup batch pass `backend=websearch.secondary_backend(ctx.settings)` (Q-6a; `search_backend or "claude"`), so the Parallel calls per search stay as they are.

## Inputs a real run will meet

| Input | Test in |
| --- | --- |
| No Parallel key and no LLM; no key with an LLM; a key and SearXNG failing | Q-6a |
| SearXNG without an address; SearXNG answering HTML | Q-6a |
| Every backend failing; a missing key | Q-6a |
| Version-1 chips (same bodies as before); model lists of 7, empty, English only, two `site:` queries, no country word | Q-6a |
| A short `main`; JavaScript-only page; 403; 999; redirect chains; robots.txt disallow, 404, 403, timeout | Q-6b |
| PDF with and without `pdftotext`; cp1252 page; 30,000 characters | Q-6b |
| Replay mode with every fetch cached | Q-6b |
| Staff rows, board offices, phones and emails, nested spans | Q-7a |
| Names in capitals, a 990-N only EIN, two tax periods | Q-7b |
| Not thin, namesake pages, page-title roles, daily cap of 50, rerun | Q-8 |

## Before the builders start (the lead)

- Q-7a: the fixtures listed at the top of [tasks/q-7a-one-page-lists.md](tasks/q-7a-one-page-lists.md).
- Q-7b: the fixtures listed at the top of [tasks/q-7b-nonprofit-officers.md](tasks/q-7b-nonprofit-officers.md).

## Done check

- Every task merged with `uv run python -m unittest` green and no existing test changed beyond the ones its task names.
- Q-6a: `fn-score run <snapshot> --mode replay --allow-degraded` sends the same Parallel Search bodies for stored searches. A live run with `FN_SEARCH=claude` on two dev questions shows the query rows and the `websearch` calls with their cost.
- Q-6b: on the same live run, at least 6 of 10 pages read by FN, and Extract called only for the rest.
- Q-7a: rows per list near 30 and 12; no "@" or phone pattern in `data/seeds/advisors.jsonl`.
- Q-7b: rows near 100 to 150; GS-23#2 and GS-32#4 present as seed records.
- Q-8: the lead's audit of 20 records finds no namesake fact, then the full queue at 50 a day; the benchmark of [research/benchmark.md](research/benchmark.md) on the ten development questions before and after the lookup.
- The benchmark compares `web_topic` on the Claude web search with the same lane on Parallel, and the owner chooses the backend with those numbers.
