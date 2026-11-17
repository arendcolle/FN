# Task d3: link employers during the search

## Goal

In the Washington search, 19 of 23 tier-1 people without a known place had only unlinked employer claims (`diag-rank.md`, section 3). In a live New York run, all 8 web research people stood under "place unknown" because their employers stay unlinked until `fn-orgs --match` runs. This task runs `orgs.match` for the people the lanes hit, before the first resolve, so the first ranking knows their place (D6).

## What to build

### `src/fn/contracts.py`

`OrgMatchIn` (line 893) gains two fields after `pace_s`:

- `person_ids: list[str] | None = None`: None takes every unlinked claim in the store, a list takes the claims of those persons only.
- `most: int | None = None`: the most names asked; None asks every new name.

`OrgMatchOut` gains `left: int = 0`, the new names not asked because of `most`.

### `src/fn/orgs.py`

- `SEARCH_PACE_S = 0.0`. ROR documents 2,000 calls per 5 minutes per IP (d1 task file). Serial calls took 0.22 to 0.24 s each (three live calls, 17 November 2026), so 40 calls cost about 9.5 s; at the batch pace of 0.2 s, about 17 s. Without a `Client-Id` header the documented limit is 50 per 5 minutes, not enforced yet (d1, line 12).
- `match` (line 275), smallest edit:
  - With `inp.person_ids` None, the rows are `ctx.store.unlinked_affiliations(MATCH_RELATIONS)` as today. With a list, the rows are `ctx.store.claims_of(inp.person_ids, include_hidden=True)` (`store.py:564`), kept when `org_id is None` and `relation in MATCH_RELATIONS`. `include_hidden` keeps rejected claims, as `unlinked_affiliations` does.
  - Each group's position is the smallest index in `inp.person_ids` of a person holding the name, mapped through `ctx.store.canonical_ids` (`store.py:663`) since `claims_of` returns canonical ids. In batch mode it is 0.
  - Groups run in the order `(key not in answers, position, key)`: stored answers first, so a failing call cannot block them.
  - Before a call, when `inp.most` is set and `asked >= inp.most`, add 1 to `left` and go on. A name `askable` (line 233) refuses never counts.

### `src/fn/search.py`

Import `orgs` and `OrgMatchIn`. `LINK_MOST = 40`. In `finish` (line 86), before `resolved = run_step(ctx, "resolve", ...)` at line 92:

```python
if ctx.http is not None and chips.version >= 2:
    by_rank = sorted((h for out in outs for h in out.hits), key=lambda h: h.rank)
    hit = list(dict.fromkeys(h.person_id for h in by_rank))
    try:
        run_step(ctx, "link", orgs.match, OrgMatchIn(person_ids=hit, most=LINK_MOST, pace_s=orgs.SEARCH_PACE_S))
    except Exception:  # noqa: BLE001 the error is kept on the step row and the people keep an unknown place
        pass
```

`outs` comes in lane order (`search.py:205`), so 300 seeds hits would precede every web hit. The stable sort by `LaneHit.rank` (`contracts.py:384`) puts each lane's first people first, so the cap reaches the web research hits.

Merge note for e1: this block sits above the `resolve` line; e1's `deepen` block sits below the first `rank_and_save` (line 93), so the edits share no line. `refinish` and `publish` are unchanged.

`orgjob.py:58` is unchanged. In batch mode stored answers now link before any call, so a failing call leaves more claims linked than today.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which names are asked, their order, applying a given limit and pace | `orgs.match` |
| Stored answers, claim links, a person's claims in SQL | `store.py`, unchanged |
| That the step runs, where, for whom; choosing 40 and the search pace | `search.finish` |
| What a linked org means for place | `evidence.py`, unchanged |

## Inputs a real run will meet

- No hits: `person_ids` is empty, no call.
- 300 seeds hits plus the other lanes: more than 40 new names; names are asked by hit rank across lanes, so each lane's first people come first.
- One person hit by two lanes; one name in two spellings on two persons: one call.
- A one-letter or 300-character employer: no call, not counted.
- A name answered before, with an org or "no match": no call.
- A hit on a record merged into another person: the whole person's claims.
- A same-name claim of a person not hit: not linked now; the batch job links it from the stored answer.
- ROR answers 429, 503 or no network, or a replay miss: the step fails, the search ends done.
- Version-1 chips, no HTTP client, a rerank: no step.

## Tests (each must fail without the change)

In `tests/test_orgs.py` `MatchTest`, made-up people only (names such as "Ada Moss", "Bo Rink"), the INBO and agriculture fixtures, `pace_s=0`. A helper `routed()` sends `orgs.ROR_API` to `net.Client` over `httpx.MockTransport(self.handler)` and every other call to `StubHttp`.

- Scoped match: `OrgMatchIn(person_ids=[ada])` links Ada's INBO claim and leaves Bo's INBO claim unlinked; the answer is stored; `person_ids=[]` makes no call.
- Limit and order: Ada (first) holds "Zeta Works", Bo holds "Alpha Lab 01" to "Alpha Lab 40"; `most=40` asks "Zeta Works" and 39 Alpha names, `left == 1`, the last Alpha name is not stored. A one-letter name beside 40 names leaves `left == 0`.
- Duplicates: Ada hit twice and Bo holding INBO in upper case give one call and two links.
- Merged record: a hit on a record merged into Ada (`set_merged_into`) links Ada's claim.
- Search, V2 chips with place "the US" (`anywhere_us`, as `test_orgs.py:538`), a fake seeds lane hitting Ada with a 2025 INBO claim, http `routed()`: a `link` step stands right before `resolve`; its output is `OrgMatchOut(asked=1, chosen=1, linked=1, failed=0)`; the first `rank` step's candidate has place `abroad`. Then a new claim "Example Lab" and `search.refinish`: `self.asked` is unchanged and no second `link` row exists.
- Rank across lanes: a fake seeds lane hits Bo, who holds "Alpha Lab 01" to "Alpha Lab 40", and a fake scout lane hits Ada with INBO: INBO is asked and Ada's place is `abroad` in the first `rank` step.
- Stored answer: `save_org_answer` for INBO before the search; the search links Ada with no call.
- Failure: INBO answers 503 and a stored answer exists for "Zeta Works" on Ada: the `link` step is an error, the search is done, Zeta is linked, rank and save follow.
- Skips, in subtests: V2 with `routed()` has a `link` row (fails without the change); V2 with `http=None` and V1 chips with `routed()` have none and make no call.

## Existing tests that change, approved by the lead

`tests/test_search.py:225`: `sorted(names[2:-6])` was `["lane:seeds", "lane:web", "publish"]`, becomes `["lane:seeds", "lane:web", "link", "publish"]` (V2 chips, `StubHttp`). No other existing test may change; stop and report a failure. `test_orgs.py:528` keeps passing: `StubHttp`'s answer has no `items`, so its search stores nothing.

## Recorded model answers and replay tests (S6)

No prompt changes; unit tests and `fn-rerank` are unchanged. A replayed fresh search now links employers from stored answers, and `fitcheck.line_of` shows the ROR name, so its recorded fit answers miss and must be recorded again, as after d1. A new name in replay is a replay miss: the `link` step fails and the search goes on.

`fn-score` replay (`score.py:317`) marks a search degraded when the `link` step errors or a call logs "not in the response cache" (`score.py:290`, `net.py:168`), so catching the miss in `match` would not help. Before the next replay scorecard the lead runs `fn-orgs --match` live on the owner's database, then freezes a new snapshot (`fn-score snapshot` copies stored answers and the response cache) and scores base and head on it. Names counted as failed stay unanswered; the lead reports those degraded searches.

## Hand check

1. `uv run python -m unittest` all green.
2. On a copy (`mkvar.sh d3`), `FN_VAR=<copy> FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` from a worktree pinned to main and from the branch, saving `SELECT search_id, section, rank, person_id FROM candidates ORDER BY 1, 2, 3` each time: identical.

The live run is the lead's.

## Not doing

Linking during a publish; linking the card records resolve adds beside the hits; calls side by side; a time budget; any change to `chosen`, `named` or `askable`; a `Client-Id` header.
