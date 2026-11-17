# Task F2: inside a tier, a known job and a recent fact come first

## Goal

Three judges scored the first 20 cards of 20 questions (run c7). Of the 200 first-ten cards, 97 scored under 2 on "could the organizer invite on what the card shows", and 80 had the topic and were still not invitable. Two patterns stand out in their reasons. On a Houston energy question, eight people known only from one paper, with no role, stood at ranks 3 to 10, ahead of a port operations chief and a hydrogen organization's CEO at ranks 11 and 12. On the Washington question, people whose newest fact is from 2001 or 2004 stood at ranks 3 to 5 inside the first heading. The rubric asks for a current role and employer and a fact from the last five years. This task makes the order inside a tier prefer what the card can show: a known job, then something recent. It is an experiment and stays only if the benchmark agrees.

## What to build

### `src/fn/evidence.py`

- `Age` gains `stale: bool = False`: true when the person has at least one dated claim and the newest year over all of them lies more than `STALE_YEARS = 10` years before today. Every dated claim counts, whatever its date method: a page FN read this year shows the person exists now, so a claim dated by the read date counts here (unlike in `recent`). The newest year of a claim is the newest of its `years`, `valid_to` and `claim_date`. A person without any dated claim is not stale.

### `src/fn/rank.py`

- `order_key`, version-2 questions only: right after the element that holds the role fit and the verdict come two new elements, in this order: the job (`known` 0, `employer` 1, `none` 2, from `found.job`), then `found.age.stale` (False before True). Everything after them keeps its order. The key for a person without evidence (the version-2 form of `BLANK`) grows by the same two elements, with the last values (2 and True), so keys still compare.
- Version-1 keys do not change.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a person's newest fact is old | `evidence.age` |
| What a known job and an old newest fact do to the order | `rank.order_key` |

## Inputs a real run will meet

A person with a role and an employer beside one with an employer only and one with neither, same tier and role fit; a person whose only dated claims are from 2004; a person whose only date is the day FN read a page this year; a person with no dated claim; a met role with no job beside an unknown role with a known job (the role fit still comes first); version-1 chips.

## Tests (each must fail without the change)

- `tests/test_evidence.py`: `stale` is true for newest year 2004, false for a claim dated by this year's read date, false without dated claims, false for a valid_to of last year.
- `tests/test_rank.py`: on a version-2 question, inside one tier and with the same role fit and verdict, known job sorts before employer only before none; among equals a person who is not stale sorts before a stale one; a met role without a job still sorts before an unknown role with a known job; the same people on a version-1 question keep today's order.

## Existing tests that change, approved by the lead

A test that pins the full version-2 order key tuple, or the version-2 key of a person without evidence, takes the two new elements. A test that pins the order of two people who differ only in job or in staleness takes the new order. Name each in the report. No other existing test may change; stop and report.

## Hand check

`uv run python -m unittest` all green. On a throwaway copy of the owner's data, `FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` from the worktree's base and from the worktree: candidate rows of searches with version-1 chips are identical.

## Not doing

Any change to tiers, to who is set aside, to the caps, or to the pages.
