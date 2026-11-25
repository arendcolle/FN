# Task K5: fn-enrich stops when the day's OpenAlex budget is nearly used

## Goal

`fn-enrich` never reads OpenAlex's credits, so after the budget is gone each queued person gets a 429 and an `error` row (`enrich.py:42`, `:186-188`). On 12 November one run of 1,500 gave 679 answers and 823 errors and left that day's searches without OpenAlex. `fn-index` already stops under `RESERVE = 3000` and on a 429 (`usindex.py:19-27`, `:87-105`). This task moves the credits reading and the reserve to the OpenAlex module and stops the author searches of `fn-enrich` at the first answer under the reserve or the first 429. A person not reached, or refused, gets no row and stays queued. Brief K5, design D4.

## What to build

### `src/fn/lanes/openalex.py`

Add `import httpx`. After `NO_QUERY` (line 43):

```python
# Credits of the day's 10,000 that fn-index and fn-enrich leave for searches (design D4).
RESERVE = 3000
```

After `short` (line 55), `remaining` moved unchanged from `usindex.py:22-27`.

### `src/fn/usindex.py`

Delete `RESERVE`, `remaining` and `import httpx`. Line 100 calls `openalex.remaining(response)`; lines 103 and 104 read `openalex.RESERVE`; the docstring at line 54 says `openalex.RESERVE`. Output and log text do not change.

### `src/fn/contracts.py`

`EnrichOut` (line 1012) gains `stopped: str = ""` (why the author searches stopped, empty when they did not) and `waiting: int = 0` (people still in the author queue after a stop). Old payloads still parse.

### `src/fn/enrich.py`

Add `import threading` and `from fn.net import HttpError`. Next to `KINDS`:

```python
REFUSED = "an OpenAlex 429 (the day's credits are used up)"


def refused(answer: object) -> bool:
    """Whether answer is OpenAlex's 429: the day's budget, not a fact about the person."""
    return isinstance(answer, HttpError) and answer.status == 429
```

`authors` (line 62) returns `tuple[list[Lookup], str]`; its docstring adds "No search starts after an answer under openalex.RESERVE credits or a 429; a person not searched or refused gets no lookup. Also returns why the searches stopped, or ''." Lines 72-74 become:

```python
    stop = threading.Event()

    def search(p: str) -> tuple[dict, float | None] | None:
        if stop.is_set():
            return None
        try:
            response = ctx.http.get(f"{openalex.API}/authors", {
                "search": persons[p].display_name, "per_page": str(AUTHORS_PER_LOOKUP), "select": openalex.AUTHOR_SELECT})
        except HttpError as exc:
            if exc.status == 429:
                stop.set()
            raise
        left = openalex.remaining(response)
        if left is not None and left < openalex.RESERVE:
            stop.set()
        return response.json(), left

    answers = fan_out(search, people, WORKERS)
    asked = [(p, a if isinstance(a, Exception) else a[0]) for p, a in zip(people, answers) if a is not None and not refused(a)]
    low = [a[1] for a in answers if isinstance(a, tuple) and a[1] is not None and a[1] < openalex.RESERVE]
```

`kept` (line 75) and the loop (line 85) iterate over `asked` in place of `zip(people, bodies)`. First line in the loop: `if kept.get(person_id) and refused(missing): continue`. Before `return`:

```python
    why = (REFUSED if any(refused(a) for a in answers) or refused(missing)
           else f"the OpenAlex reserve ({min(low):,.0f} credits left today)" if low else "")
    return found, why
```

`low` filters before `min`, so a `nan` header never hides a stop. `employments` does not change.

`run` (line 173): `stopped = ""` before the loop; line 185 becomes `found, stopped = authors(ctx, people)` for `openalex_author`, else `found = employments(ctx, people)`. It returns `EnrichOut(lookups=done, stopped=stopped, waiting=len(queue(ctx.store, "openalex_author")) if stopped else 0)`. Unreached people are not in `done`, so ORCID gets the rest of `--limit`.

`main` (line 228): the last line gains `+ (f"; stopped at {out.stopped}, {out.waiting:,} people still wait" if out.stopped else "")`. Exit code stays 0.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Credits left on an OpenAlex answer, and the reserve | `openalex.remaining`, `openalex.RESERVE` |
| When `fn-index` stops | `usindex.run` (rule unchanged) |
| Whether an answer is OpenAlex's 429 | `enrich.refused` |
| Starting no author search after a stop, and who gets no row | `enrich.authors` |
| The stop reason and the people still waiting | `enrich.run` with `enrich.queue` |
| The command's last line | `enrich.main` |

## Recorded answers, replay and stored searches (S6)

No prompt or model call changes; every recorded answer replays. Replayed HTTP answers carry no `x-ratelimit-*` header (`net.py:199-200`), so a replay never stops. The lane is untouched and `fn-enrich` is no part of a search, so searches stored with version-1 chips keep their order exactly.

## Inputs a real run will meet

No header (test 4). A header `abc`, empty, `nan` or `-5` (4). A 429 first (2). A 429 on the institution filter call (5). The filter call's 1 credit stops nothing: `authors` makes it after every name search of the batch (4). A 500 on one person (1). `--limit 0` and an empty queue (7). A queue shorter than `WORKERS` (8). 60 people (1). ORCID alone and after a stop (6). A rerun asks only the people without a row, none twice (2). A 429 with Retry-After up to 30 s is retried once by `net.Client`; a second refusal stops the run.

## Tests (each must fail without the change)

Made-up names only ("Test Seed 0" and on, at `SMALL`). In `tests/test_enrich.py`: a handler `Budget(Recorded)` that numbers `/authors` answers under a lock and serves `x-ratelimit-remaining` or a plain-text 429 by number, and optionally on `/institutions`; a helper returning the rows and the `EnrichOut` payload.

1. `test_an_answer_under_the_reserve_starts_no_search_after_it`: `enrich.WORKERS` patched to 1 (with 4 the in-flight bound is racy), 8 people, answer 2 a 500, answer 3 `2990`: 3 requests, `error` for person 2, `no_match` for 1 and 3, no row for 5, `stopped == "the OpenAlex reserve (2,990 credits left today)"`, `waiting == 5`. Subtest, 4 workers, 60 people: rows only for people searched, under 60 requests, under 5 s.
2. `test_a_429_stores_no_row_and_the_next_run_asks_those_people_again`: `WORKERS` 1, 5 people, answer 1 a 429: 1 request, no rows, `stopped == enrich.REFUSED`, `waiting == 5`. A second run with plain answers asks each of the 5 once.
3. `test_fn_enrich_prints_why_it_stopped_and_exits_0`: `main` with `fn.enrich.from_env`, `fn.net.Client` and `sys.argv` patched, stdout captured, `WORKERS` 1, 8 people. Three runs, last line matched with the job id by regex: answer 3 carrying `2990` gives `... done: 3 lookups; matched 0, ambiguous 0, no_match 3, error 0; stopped at the OpenAlex reserve (2,990 credits left today), 5 people still wait`; a first answer 429 gives `... done: 0 lookups; matched 0, ambiguous 0, no_match 0, error 0; stopped at an OpenAlex 429 (the day's credits are used up), 5 people still wait`; plain answers give today's line ending `error 0`. Exit 0 each.
4. `test_an_answer_without_a_number_for_credits_does_not_stop`: no header, `abc`, empty, `nan`, `9000`, and `2990` on the institution answer only: every person searched, `stopped == ""`. Subtests: `-5` stops; with `openalex.RESERVE` patched to 9500, `9000` stops.
5. `test_a_429_on_the_institution_call_leaves_the_found_people_without_a_row`: a person with a kept author gets no row, a person without one gets `no_match`, `stopped == enrich.REFUSED`.
6. `test_orcid_lookups_run_after_the_author_searches_stop`: both kinds, `WORKERS` 1, 3 seed people, answer 1 carrying `2990`, 2 ORCID holders: 1 author row, 2 ORCID rows. `--kind orcid_employment` alone with no header anywhere: `stopped == ""`.
7. `test_an_empty_queue_or_a_limit_of_0_asks_nothing_and_reports_no_stop`: no requests, `stopped == ""`, `waiting == 0`.
8. `test_a_queue_shorter_than_the_workers_keeps_every_answer`: 2 people, both answers `2990`: 2 rows, stopped, `waiting == 0`.

In `tests/test_usindex.py`: `test_the_reserve_is_the_one_in_the_openalex_module`: with `openalex.RESERVE` patched to 9500, a page carrying `9000` stops the job after page one.

## Existing tests that change, approved by the lead

None. No existing test reads `usindex.RESERVE` or `usindex.remaining`. No existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. With `SP=<scratch folder>`, `FN_VAR=$(sh $SP/bin/mkvar.sh k5a) FN_HTTP=replay FN_LLM=replay uv run fn-enrich --limit 0` prints today's line with 0 lookups. Save `$SP/r5/k5/hand.py`:

```python
import os, sys
from pathlib import Path
from unittest import mock
import httpx
from fn import enrich, net
from fn.config import Settings
from fn.store import Store

mode, n = sys.argv[1], [0]
def answer(request):
    if mode == "429":
        return httpx.Response(429, text="made-up refusal")
    n[0] += 1
    return httpx.Response(200, json={"meta": {"count": 0}, "results": []},
                          headers={"x-ratelimit-remaining": "2990" if n[0] >= 3 else "9000"})
settings = Settings(var_dir=Path(os.environ["FN_VAR"]), http_mode="live", llm_mode="replay")
client = net.Client(settings, httpx.MockTransport(answer), sleep=lambda _: None)
count = lambda: Store(settings.db_path).conn.execute(
    "SELECT verdict = 'error', count(*) FROM lookups WHERE kind = 'openalex_author' GROUP BY 1").fetchall()
before = count()
with mock.patch.object(enrich, "from_env", return_value=settings), mock.patch.object(net, "Client", return_value=client), \
        mock.patch.object(sys, "argv", ["fn-enrich", "--limit", "50", "--kind", "openalex_author"]):
    print("exit", enrich.main())
print(before, "->", count())
```

Run `FN_VAR=$(sh $SP/bin/mkvar.sh k5b) uv run python $SP/r5/k5/hand.py reserve`, then with `k5c` and `429`. The transport is faked; no call leaves the machine. Expected: `reserve` adds 3 to 6 `no_match` rows and no `error` row, and ends `stopped at the OpenAlex reserve (2,990 credits left today), N people still wait`, N being 1,633 minus the rows added; `429` adds no row and ends `..., 1,633 people still wait`. Exit 0 both.

## Not doing

A per-day counter, a new setting or flag, batched names, any change to what a lookup stores, retry rules for old `error` rows, the OpenAlex lane, `--limit`, the ORCID kind, and reading the header of the institution call.
