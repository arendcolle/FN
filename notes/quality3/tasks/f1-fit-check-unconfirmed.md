# Task F1: the fit check also reads the people whose topic is not confirmed

## Goal

On a live search for political scientists in New York, 50 people stand under "Tie, topic not confirmed". Among them is an artist, whom nobody would invite for this question, and there may be people who do fit and whose record uses other words than the question. The fit check reads only the match tiers today, so it had 17 people to read and 103 places unused. This task lets it read the unconfirmed people too. A "no" sets such a person aside, as it does for anyone. A "yes" confirms a person whose card shows where they work. It is tried against the benchmark before it stays.

## What to build

### `src/fn/fitcheck.py`

- `candidates(ranked)`: first the people it takes today (tiers 1 to 4), then the kept new-section people under heading 3 (`rank.heading(c.tier, c.fit.tie_grade if c.fit else "none") == 3`), each group in rank order, together at most `MAX_PEOPLE`. As today, nobody the web researcher found and nobody set aside. The docstring says so.

### `src/fn/rank.py`

- `tier`: on a version-2 question, a verdict of "yes" counts as a match when `found.job != "none"`, whatever the word match says. The rest of the verdict logic stays: "no" takes the match away, "partly" too unless the role is met, and once the fit check ran a person without a verdict is no match.
- `order_key`: below tier 4 the verdict order becomes yes, partly, no verdict, no (today: partly, no verdict, no). Keep the key's length and the place of the element.

Nothing changes for a search with version-1 chips or for a rerank without stored verdicts.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which people the model is asked about | `fitcheck.candidates` |
| What a verdict does to a tier and to the order | `rank.tier`, `rank.order_key` |

## Inputs a real run will meet

130 people in the match tiers (nobody from heading 3 is sent); 10 in the match tiers and 200 under heading 3 (110 of them sent); a heading-3 person with "yes" and a known job (tier 1 or 2 by place), with "yes" and no job (stays), with "no" (set aside as unfit, as today), with "partly" (stays, sorted after "yes"); a heading-4 person (never sent); version-1 chips.

## Tests (each must fail without the change)

- `tests/test_fitcheck.py`: heading-3 people follow the match tiers in what is sent; the cap holds across both groups; a heading-4 person, a web research person and a set-aside person are not sent.
- `tests/test_rank.py`: on a version-2 question a person with a tie, a known job, no topic word and verdict "yes" is tier 1 inside the area and tier 2 with an unknown place under a required place; the same person without a job stays in tier 5 or 6; under heading 3 "yes" sorts before "partly", before no verdict, before nothing else changes; on version 1 a verdict changes nothing.

## Existing tests that change, approved by the lead

A test that pins the verdict order below tier 4 ("partly" first) takes the new order. A test that pins what `candidates` sends when heading-3 people exist takes the new list. Name each in the report. No other existing test may change; stop and report.

## Hand check

`uv run python -m unittest` all green. On a throwaway copy of the owner's data, `FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` from main and from the branch: every stored search keeps its candidate rows, since their verdicts are stored and the new people have none.

## Not doing

Reading the people under "Other people found", changing the prompt, changing the cap of 120, any page change.
