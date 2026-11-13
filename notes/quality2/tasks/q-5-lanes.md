# Task Q-5: the lanes read the kind of person, and a web search without Belgium

## Goal

Every lane asks for Belgian people, so only 1 stored person has the topic and the place without a tie (`research/tiers.md`), and the second and fourth headings stay empty. The OpenAlex lane runs for every question, though 10 of 28 gold questions ask for business people and its people fill 44% of first-20 cards. The web lane never names the kind of person, and a question of only a role and a place ("Flemish founders in New York") runs no web search at all (`src/fn/lanes/web.py:118`). This task skips the OpenAlex lane when no research is asked, puts role chips in the web queries, moves page finding behind `websearch.find`, and adds the `web_topic` lane. Decisions R6, R7 (skip) and the lead's rulings on `web_topic` and on one web search function. Needs Q-1 and Q-4.

## What to build

### `src/fn/websearch.py` (new; owner of "finding pages for a web query")

- Move from `lanes/web.py`: `SEARCH_URL`, `EXTRACT_URL`, `MAX_CHARS`, `FETCH_TIMEOUT_S`, `EXTRACT_TIMEOUT_S`, `PRICES`, `usage_cost`, `extract_body`. Logger `fn.websearch`.
- `search_body(objective: str, queries: list[str]) -> dict`: `{"objective": objective, "search_queries": queries[:MAX_QUERIES], "mode": "fast"}`, `MAX_QUERIES = 5`.
- `rule_queries(chips: Chips) -> list[str]`: one per topic with the place text, one per role chip with the place text, then one per institution; at most 5. It lives here so the rule that writes queries has one owner. Q-6a later swaps both lane calls for its checked `websearch.queries`.
- `@dataclass(frozen=True) class Page`: `rank: int`, `url: str`, `title: str | None`, `texts: list[tuple[str, str]]` (label and markdown, in today's order "Extract full content", "Extract excerpts", "Search excerpts"), `published: str | None`, `raw: dict`, `unread: str | None` (Extract's error type).
- `@dataclass(frozen=True) class Found`: `pages: list[Page]`, `considered: list[Considered]` (the repeated-URL rows, as `web.py:136-138`), `note: str | None`.
- `find(ctx: StepContext, objective: str, queries: list[str]) -> Found`: today's Search post, URL dedup and Extract post (`web.py:125-144`). No results gives `note="Parallel Search returned no results; Extract not called"` and no Extract call. `MissingKey` and `HttpError` propagate. The route (Parallel today) changes here only; the R9 lookup batch calls this function too.

### `src/fn/lanes/web.py`

- `objective(chips: Chips, tie: bool = True) -> str`: starts "People with a connection to Belgium" when `tie`, else "People". Then, when there are role chips, "who are " plus their texts joined by ", "; then topics with "who work on" (or "and work on" after roles); institutions with "who have a link to" (or "and have a link to" after roles or topics); then "in {place}". Without role chips the sentence is today's word for word.
- `request(chips)` returns `websearch.search_body(objective(chips), websearch.rule_queries(chips))`, unchanged for chips without roles.
- `NO_QUERY = "no topic, role or institution chip"`; the lane runs when any of the three exists.
- `collect(ctx: StepContext, objective: str, queries: list[str], lane: LaneName) -> LaneOut`: the rest of today's `run`: the MissingKey note, `websearch.find`, storing each page with the first text that has plain text, the considered rows, and `people`. `people` gains `lane: LaneName` and sets it on each hit. `run` checks chips and the client, then calls `collect(ctx, objective(chips), websearch.rule_queries(chips), name)`.

### `src/fn/lanes/web_topic.py` (new; owner of "people with the topic and no tie asked")

- `name: LaneName = "web_topic"`, `GATE = 20`.
- `run(ctx, inp) -> LaneOut`, in order: no topic, role or institution chip gives `web.NO_QUERY`; `inp.chips.version == 1` gives a note `chips stored before this round, so no search without a tie` (lead's ruling on legacy chips: a stored search replays without new calls; `parse.tie_must` is false for version 1, so this gate comes first); `parse.tie_must(inp.chips)` gives a note `the tie is a must, so no search without it`; `inp.first_heading` of `GATE` or more gives `{n} people under the first heading, so no search without a tie`; else `web.collect(ctx, web.objective(inp.chips, tie=False), websearch.rule_queries(inp.chips), name)` and a log line `web_topic lane: {n} people under the first heading, searched without a tie`. A note makes no call.
- Its calls, seconds and cost land on its own step row `lane:web_topic` and its `step_calls`, which `/debug/stats` shows per step.

### Contracts and registry

- `LaneName` (`src/fn/contracts.py:39`) gains `"web_topic"`. `LaneIn` (line 662) gains `first_heading: int | None = None`.
- `LANES` (`src/fn/lanes/__init__.py:15`) becomes `[seeds, openalex, web, web_topic, linkedin]`.

### `src/fn/search.py`

- `first_heading(ctx: StepContext) -> int`: kept new-section candidates of the search with tier 1 or 2, from `ctx.store.list_candidates(ctx.search_id, kept_only=True)`.
- In `run` (line 76): for the lane named `openalex`, when `parse.wants_research(chips)` is false, `skip_step(ctx, "lane:openalex", lane_in, LaneOut(lane="openalex", query="", total_seen=0, considered=[Considered(person_key="-", name="", stage="query", kept=False, reason="no research asked")]))`. For the lane named `web_topic`, pass `lane_in.model_copy(update={"first_heading": first_heading(ctx)})`; the publish after the web lane has saved its tiers by then. A skipped lane does not count as failed.
- `refinish` already reads a skipped lane step as an empty output (line 55).

## Inputs a real run will meet

No role chip (queries as today); roles and a place only; more than 5 queries; a MissingKey in `web_topic` (note, step ok); Parallel returns nothing; `first_heading` None (counts as 0); a must tie; 20 or more under the first heading; an earlier lane that raised; the same page found by both web lanes (one source, one person, two lanes on the entry); version-1 chips (OpenAlex runs, since research counts as asked; `web_topic` gives the version-1 note and calls nothing).

## Tests (each must fail without the change)

- `tests/test_web_lane.py`: `web.objective` and `websearch.rule_queries` with roles "founders" and "business leaders", topic "nanotech", place "New York": "People with a connection to Belgium who are founders, business leaders and work on nanotech in New York", queries `["nanotech New York", "founders New York", "business leaders New York"]`; `objective(..., tie=False)` starts "People who are"; a role and a place alone post one Search.
- New `tests/test_web_topic.py`: each gate note with no call, the version-1 note among them (v1 chips with a topic and no tie chip); under the gate it posts one Search whose objective has no "Belgium" and its hits carry lane `web_topic`.
- `tests/test_search.py`: v2 chips with only non-research roles give a skipped `lane:openalex` step and no OpenAlex call; v1 chips run it; `web_topic` gets the count of tier 1 and 2 people saved by the publish before it.

## Existing tests that change

- `tests/test_web_lane.py` may change only the module of moved names: `web.extract_body`, `web.usage_cost` and `web.PRICES` become `websearch.*`, and `assertLogs("fn.lanes.web", ...)` around `usage_cost` becomes `"fn.websearch"`. That touches `test_request_and_extract_body_name_only_fields_the_v1_schemas_define`, `test_extract_body_asks_for_12000_characters_of_full_content_and_a_20s_fetch`, `test_the_lane_posts_one_search_then_one_extract_for_each_unique_url_and_stores_one_source_each`, `test_the_cost_function_prices_the_search_usage_and_an_unknown_sku_gives_none_and_a_warning`, `test_a_priced_sku_costs_its_price_times_its_count_and_no_usage_has_no_cost`.
- `tests/test_gold.py` `test_gs10_picks_are_found_by_pin_and_the_rest_are_labelled_with_a_step_and_reason` and `test_an_unreachable_pick_no_lane_found_keeps_the_trace_step_and_reason_and_reach_evidence_follows`: the expected lost step becomes `"lane:seeds, lane:openalex, lane:web, lane:web_topic, lane:linkedin"`.
- `tests/test_web.py` `test_rerun_with_edited_chips_skips_parse_and_links_back`: the step list gains `("lane:web_topic", "ok"), ("publish", "ok")` after the web lane's publish.
- No other existing test may change; stop and report a failure.

## Hand check and measure

- `uv run python -m unittest` all green.
- Replay with stored v1 chips: `fn-score run <snapshot> --mode replay --allow-degraded`: OpenAlex runs, `web_topic` gives the version-1 note and calls nothing, so nothing but the step list changes.
- Live-preferring (lead, paid): `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-gold <dev case ids>`; read `/debug/stats` for `lane:web_topic` runs, median seconds and cost against the 2 Parallel calls and 12 to 21 page reads `research/tiers.md` estimates; count searches where it ran (expected about three quarters of those with a nice tie). Then `fn-score snapshot` and `--mode rescore` for tier sizes.

## Not doing

The R9 lookup batch (Q-8; it calls `websearch.find`). The backends and the query check (Q-6a). An OpenAlex works search by the question's country. Changing the LinkedIn lane. A second objective inside the first web lane.
