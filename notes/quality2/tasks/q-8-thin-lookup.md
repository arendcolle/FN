# Task Q-8: look thin records up on the web, anchored on a school or employer

## Goal

A business record holds a median of 2 claims and a place in 19% of cases; a researcher record holds 7 claims and always a place (`research/held-not-returned.md`). So even a correct founder pick rarely looks invitable on a card, and three gold picks (GS-18#4, 22#1, 28#4) have records too thin to match any query. This task adds the lookup kind `web_person` to `fn-enrich`. It searches the web for a thin person's name with a school or employer FN already holds, reads the pages, and stores a fact only when its quote names the anchor next to the person, under the new source kind `lookup_page`. Twenty records are checked by hand before the full run. Decision R9 in `design.md`. Owner: `enrich.py`. Needs Q-6b, and Q-1 for the page reader's answer.

## What "thin" means

A thin record is a person not merged away, with at least one identifier and none of the schemes `openalex`, `orcid` or `profile_url`, with at most `THIN_CLAIMS = 4` claims not rejected, and with at least one anchor. The cut sits between the business records' median of 2 to 3 claims and the researchers' 7 (same note). In `var/fn.sqlite3` of 2026-11-12 this gives 2,256 records, 170 of them on a kept first-20 card of the 31 stored searches (read-only count with the query below).

An anchor is an affiliation claim, not rejected, with an `org_id` and a relation in `ANCHOR_RELATIONS = ("works_at", "affiliated_with", "worked_at", "studied_at")`; list relations such as `fellow_of` never are.

## What to build

### `src/fn/contracts.py`

- `EnrichIn` (line 749) gains `persons: list[str] = []`, the records to look up first.
- `LookupKind` (line 55) gains `"web_person"`. `SourceKind` (line 35) gains `"lookup_page"`. `page_source`'s `kind` (Q-6b) gains `"lookup_page"`.

### Every place that lists source kinds

- `present.PROSE` (`src/fn/present.py:40`) gains `lookup_page`, so a fact shows its quote. UI-2's `source_name` and UI-3's `source_sentence` read `present.PROSE` (see `plan-web.md`).
- `gold.EVENT_KINDS` (`src/fn/gold.py:38`) gains `lookup_page`: a lookup page at a case's event page is the same leak as a web page there.
- No change: the local search leaves out only `record` after Q-2, so lookup facts are searchable; `score.py:129` reads `seed_page` only; identity reads identifier schemes, and a lookup adds no identifier.

### `src/fn/store.py`

- `thin_persons(max_claims: int) -> list[str]`: the definition above, in `rowid` order.
- `lookups_since(kind: str, since: datetime) -> int`: lookups of the kind with verdict not `error` and `at >= since`.

### `src/fn/enrich.py`

- `KINDS` gains `"web_person"`; `DEFAULT_KINDS = ("openalex_author", "orcid_employment")` is what runs without `--kind`. `THIN_CLAIMS = 4`, `MAX_ANCHORS = 2`, `MAX_PAGES = 5`, `DAILY = 50`.
- `queue` (line 35): `web_person` takes `store.thin_persons(THIN_CLAIMS)`, then sorts by `kept_card_ranks` as today, so people on first-20 cards of stored searches come first. `queue(store, kind, persons=())` puts the ids of `inp.persons` that are in the list before all others, in their given order. `run` takes at most `DAILY - store.lookups_since("web_person", start of today UTC)` of them and logs `fn-enrich: daily cap of 50 web lookups reached` at 0.
- `anchors_of(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[str, str]]`: org id and name (the org's stored name, else the claim value), one per org, in `ANCHOR_RELATIONS` order and newest claim first, at most `MAX_ANCHORS`.
- `anchored(quote: str, name: str, anchors: list[tuple[str, str]]) -> bool`: the quote holds the last word of the name (`extract.words`) and `extract.names_org(anchor_name, quote)` holds for an anchor.
- `web_people(ctx, people: list[str]) -> list[Lookup]`, one person at a time, each in its own `try` as `employments` does (line 160): queries `f'"{display_name}" "{anchor_name}"'` per anchor; `websearch.find(ctx, f"Pages that name {display_name} with {', '.join(anchor names)}", queries, backend=websearch.secondary_backend(ctx.settings), limit=MAX_PAGES)` (the lookup batch uses the Claude web search by default, ruling of 2026-11-12 in `design.md`); each page through `websearch.source_of(page, now, kind="lookup_page")`; `extract.read_all(ctx, sources)`. A mention counts when `identity.key(located.name) == identity.key(display_name)`. Of its `extract.drafts(person_id, source, located, ctx)`, a draft is kept when `anchored(draft.quote, ...)`, and a role draft only when `located.role` is set (else its value is the page title). In one transaction: upsert the sources with a kept draft, then the drafts, then `save_lookup`.
- Verdicts and details, word for word: `matched` with `{n} claims from {urls}` when a draft is kept; `ambiguous` with `name on {n} pages, never next to {anchor names}` when a mention counts and no draft is kept; `no_match` with `{n} pages read, no mention of the name` otherwise; `error` as `failed` gives it. No anchor never reaches the queue.
- `run` dispatches through `{"openalex_author": authors, "orcid_employment": employments, "web_person": web_people}`; `web_people` raises `RuntimeError("the web lookup needs an LLM")` without `ctx.llm`.
- `refresh(store, settings, http, inp, llm=None)` passes `llm` to the `Worker` (line 196). `main` builds `llm.from_settings(settings)` when `web_person` is asked, takes `--person ID` (repeatable; passed as `EnrichIn.persons`), and prints under each `web_person` line every stored claim: `  {kind} {relation or ''} {value!r} | {quote[:200]!r} | {url}`. That printout is the hand-check list.

## The count behind the numbers

The read-only count, for the lead to repeat on the snapshot: persons with `merged_into IS NULL`, an identifier, no `openalex`, `orcid` or `profile_url` identifier, at most 4 claims with `rejected_at IS NULL`, and an anchor claim; joined to `kept_card_ranks` with rank 20 or better for the 170.

## Inputs a real run will meet

A record with only `fellow_of` claims (not thin, never queued); two anchors at one org; a name with a particle ("Ann van Example"); a namesake page that names the anchor elsewhere on the page; a page naming the person and the anchor in one sentence; a role taken from the page title; a page FN cannot read and Extract fills; no results; the Claude web search failing for one person (verdict `error`, retried on a rerun); the daily cap reached; a rerun (done records skipped, errors retried); a record merged away since the queue was read.

## Tests (each must fail without the change)

New `tests/test_web_lookup.py`, with made-up names, `websearch.find` patched to return recorded `Found` pages and a stub LLM giving the page reader's answer:

- `thin_persons`: a seed record with 2 claims and a `studied_at` anchor is thin; one with 5 claims, one with an `openalex` identifier, one with only `fellow_of` are not.
- The queue puts a record on a kept card of rank 3 before one of rank 40 and one on no card. A thin record passed through `refresh` in `EnrichIn.persons` goes before all three; a record in `persons` that is not thin is not queued.
- One page says "Ann Example, CEO of Example Labs, studied at KU Leuven" with anchor KU Leuven: a role and two affiliation claims stored under a `lookup_page` source, verdict `matched`.
- A page naming "Ann Example" without the anchor near her: nothing stored, verdict `ambiguous`. A page naming "Bo Example": `no_match`.
- A role draft whose value is the page title is not stored.
- With 50 `web_person` lookups saved today, the run looks nobody up.
- With `search_backend=None` (the test helper sets "parallel" since Q-6a), `find` is called with `backend="claude"`.
- `present` shows a `lookup_page` fact with its quote.

## Existing tests that change

None. `tests/test_enrich.py:104` calls `refresh` without `llm` and keeps working. Stop and report a failure.

## Hand check

`uv run python -m unittest` all green. The lead, live and paid: `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-enrich --kind web_person --limit 20 --person <record of GS-03#1> --person <record of GS-28#4>`. The lead checks all 20 printouts for namesakes before any longer run; a namesake stops the batch until the rule changes. Then the full queue at 50 a day, and the benchmark before and after.

## Not doing

A lookup during a search. Records without an anchor (GS-18#4). New people found on the pages. An undo command (facts go with "Not correct"). LinkedIn or its snippets.
