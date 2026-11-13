# Task UI-5: headings in the results list

## Goal

Today every new person stands under one heading, "New" (`src/fn/web/staff.py:76`, `:166`). Position 9 can have a tie to Flanders and position 10 none, with nothing on the page to say so ([research/tiers.md](../research/tiers.md), section 5). Decision R4 in [design.md](../design.md): people are ordered topic first and shown under headings that name which wishes they meet, each with its count. The lead's rulings add a fourth heading, "Other people found", and fix seven tiers, with tier 7 always under "Other people found", also when the tie is a must. This task is the page side; the ranking track stores the tier and the fit and orders by them.

## Before you start

The ranking track's tier task Q-4 is merged: `Candidate.tier`, `Candidate.fit` and `rank.heading` exist. UI-1 has copied the bundle; do not copy it again. Read the design system's `SectionHeading` part and copy its markup. If you need a class or a string the design system does not have, stop and report it.

## What you read from the ranking track

- `Candidate.tier: int | None`: 1 to 7 on candidates ranked in this round, None on rows stored before it (a NULL column).
- `Candidate.fit: CardFit | None` with `tie_grade: TieGrade` (`"strong"`, `"medium"`, `"weak"` or `"none"`); None on old rows and on a candidate without evidence.
- `rank.heading(tier: int, tie_grade: TieGrade) -> int`, 1 to 4: tiers 1 and 2 give 1, tiers 3 and 4 give 2, tier 5 gives 3, tier 6 gives 3 with a strong or medium tie and 4 without, tier 7 gives 4. Call it with `c.fit.tie_grade if c.fit else "none"`. It is the one owner of tier to heading; the page never maps tiers itself and never reads whether the tie is a must (the ranker has already cut people without a tie when it is).
- The order: the ranker sorts the new section by tier, then heading, so the people of one heading stand together. The page never reorders.

If a field has another name or type when you start, stop and report it.

## What to build

1. `src/fn/present.py`: `HEADINGS = {1: "Topic and a tie to Flanders", 2: "Topic, no known tie", 3: "Tie, topic not confirmed", 4: "Other people found"}` and `heading_of(candidate: Candidate) -> str`: `HEADINGS[rank.heading(candidate.tier, grade)]`. `present.py` already imports `rank` (`present.py:6`).
2. `contracts.py`: `class ResultsHeading(Model): title: str; count: int; first_key: str`. `ResultsView` gains `headings: list[ResultsHeading] = []`. `results()` (`present.py:339`) fills it when every kept new-section candidate has a tier, else leaves it empty. `count` is the number of kept new-section people who are not skipped under that heading, over the whole list and not only the shown cards. `first_key` is the card key of the first shown card under it, skipped-here cards included; a heading whose people all fall past the shown cards gets no entry.
3. `src/fn/web/staff.py` `person_cards` (`staff.py:154`): the network section keeps "In your network" and its count, as today. For the new section, when `found.headings` is empty, the "New" heading as today. Otherwise each new-section card is preceded by the `h2.fn-section text-label` of the heading whose `first_key` is its key: "`{title}` " then `<span>{count}</span>`, the markup "New" uses today. Show more, the skipped line and the count line do not change.

## Inputs a real run will meet

A search stored before this round (no tiers: "New", as today); a search where some candidates have a tier and some do not (treat as no tiers); a list where every person is in one tier (one heading); a must-tie question with tier 5, 6 and 7 people, all with a tie (two headings: "Tie, topic not confirmed" and "Other people found"); a not-must question with all four headings; tier 6 people with and without a tie (two headings, tie people first); a tier with `fit` None (grade "none"); a heading whose first person is the 21st (it shows only with `?shown=40`, and then once); a skipped-here card as the first card of a heading; a running search whose candidates change between polls (the fragment route `/searches/{id}/cards` renders the same list, so it shows the same headings); `?skipped=1`; a search with only network people (no new headings); a version-1 search reranked (tiers set, no tie cut: all four headings can show).

## Tests

In a new file `tests/test_results_headings.py`, with made-up names, building candidates as `tests/test_results_page.py:58` does with a `tier` and a `fit` set. Each must fail without the change.

- Tiers 1, 3, 5, 6 with a medium tie, 6 with none, and 7 show four headings in order with their counts: 1, 1, 2, 2.
- Under a must tie: tiers 1, 5, 6 and 7, each with a strong tie, show three headings, with tier 6 under "Tie, topic not confirmed" and tier 7 under "Other people found".
- A legacy search (tier None everywhere) shows "New" and no tier heading; one candidate without a tier also gives "New".
- 25 tier-1 people then 5 tier-3 people: the first page shows one heading with count 25; `?shown=40` shows both, each once, and the second sits before card 26.
- The count leaves out a person skipped on another search and counts the whole list.
- While a search runs, a heading's count is the number of people under it in the whole list so far, not the number of shown cards (lead's ruling; the count line above the list counts the same way).
- The `/searches/{id}/cards` fragment shows the same headings as the page.
- No staff page shows a tier number or a grade: with made-up names and a question that lack the words, "tier" is nowhere in the page, attributes included, and the page's text with tags removed holds neither "strong" nor "medium" (class names such as `text-strong` hold the word).

## Existing tests

No existing test may change: every existing results test builds candidates without a tier, which must keep the "New" heading. If one fails, stop and report it. Run `uv run python -m unittest`.

## Hand check

Throwaway var folder (`mkvar.sh ui5`), `FN_LLM=replay`, `uv run fn-rerank --all`, `uv run fn-serve` on your port. Stored searches are version 1, so their tie is not a must. Headless Playwright at 1280 px and 390 px: one search with all four headings and one with a single heading (find them with `SELECT id, chips_json FROM searches` and the candidates' tiers), first screen and after Show 20 more. Log each heading's text and count, and the card index before which it stands. Give the paths and say what you see, without names.

## Not doing

- Ordering; the tier rules; hiding people without a tie; tier to heading (the ranking track).
- A tier mark on a card; the wishes line; "Best matches".
- Headings in the network section or on the Network page.
