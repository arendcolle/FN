# Task Q-10: a topic match counts only for a person with a known job

## Goal

Ask for a speaker on US export controls and the first heading, "Topic and a tie to Flanders", fills with fellows whose 2003 fellowship field holds the word "trade": no role, no employer, no place. Judges scored such cards 0 on "could the organizer invite this person", and of 1,162 stored cards that do show a role and an employer only 2 were invitable (`design.md`, "What the first after-measurement showed"). The scout lane (Q-9b) now finds people who hold the asked job today, but a wished tie puts them under the second heading, after every such fellow. This task makes the ranker treat a topic match as confirmed only when the card shows what the person does: a stated role and an employer. A person with a tie and topic words but no known job stands under "Tie, topic not confirmed". Inside a tier, a person placed inside the asked area stands before a person whose place is unknown. Owner of what a card shows: `evidence.py`. Owner of tiers and order: `rank.py`.

## What to build

### `src/fn/evidence.py`

- `JobFit = Literal["known", "employer", "none"]` in `contracts.py` next to `RoleFit`, and `Evidence` gains `job: JobFit = "none"`: what the card shows of the person's work today.
- `job(claims: list[Claim], card: dict[str, frozenset[str]]) -> JobFit`: `known` when the card's claims hold a role and an employer, `employer` with an employer alone, else `none`. A role is a claim for which `usable_role(card, claim)` holds and whose `relation` is None (a role with a relation is a list entry such as a fellowship, not a job). An employer is a `works_at` claim of any year, or an `affiliated_with` claim that is undated or whose newest year lies within `RECENT_YEARS` of today (a host institution of a 2005 fellowship is not an employer today). `job` takes `today` for that, and `of` sets `job=job(own, card, today)`.
- If the person page task (UI-6b) has moved the list-role names or `stated_role` into `evidence.py` by the time you start, use what is there and add no second definition.

### `src/fn/rank.py`

- `confirmed(found: Evidence, question: Question | None) -> bool`, the one place that says when a topic match counts. Without a question or with version-1 chips it is `has_topic(found, question)` alone, so stored searches keep today's tiers. With version-2 chips it is `has_topic` and one of: `found.role.fit == "met"` (the person holds the asked role, as a consul without a named employer does on a question about consuls); `found.job == "known"`; or `found.job == "employer"` on a card whose records all come from OpenAlex (`found.only_openalex`) when the question wants research (`parse.wants_research(question.chips)`: researchers asked for, or no role named), because a researcher's record states the employer and the role is the research itself.
- `tier`: `confirmed(found, question)` replaces `has_topic(found, question)` in the first branch. A person who matched the topic without a known job then falls to the tie branch: tier 5 with a tie (their topic words stand), tier 6 without. Nothing else in `tier` changes, and nobody is cut by this task.
- `order_key`: for a question with version-2 chips the place element becomes inside or no place asked (0), unknown (1), outside (2), abroad (3). Without a question or with version-1 chips it stays today's `PLACES.get(place, 0)`, so a stored search keeps its order exactly. The separate `place == "abroad"` element stays where it is.
- `heading` is unchanged: tier 5 and tier 6 with a tie stand under "Tie, topic not confirmed".

## Ruling after the first live run of the scout lane (13 November)

The question "Which Belgian brewers, chocolatiers or food entrepreneurs who built a business in the US could speak at our food export seminar?" parses to three role chips and the topic "food". The scout lane found a brewmaster, a brewer and a brewery founder, each with a tie and a US place. Their role chip is met, but no claim of theirs holds the word "food", so `has_topic` is false and they stood in tier 6, ranks 40 to 50, behind fellows whose field holds "food". A met role is what the organizer asked for. So `confirmed` reads: with version-2 chips, `found.role.fit == "met"`, or `has_topic` and a known job (or the OpenAlex case). The lead applies this at merge with a test: a person with a met role chip, a tie and no topic word is tier 1, not tier 6.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| What a card shows of the person's work today: a role and an employer, an employer alone, or nothing | `evidence.job` |
| When a topic match counts for the tier | `rank.confirmed` |
| Tiers and the order inside a tier | `rank.tier`, `rank.order_key` |

## Inputs a real run will meet

A fellow with a fellowship role (a role with a relation) and a host institution (an employer alone on a seed record: not confirmed); a web person whose only role is the page title (not usable); a researcher from OpenAlex with a current affiliation and no role, on a question that names a business role (not confirmed: tier 5 or 6), on a question that names no role and on a research question (confirmed, as today); a seed person with a role and no employer; a scout person with a role, an employer and no tie on a wished-tie question (tier 3 or 4, now above the fellows); version-1 chips (unchanged); a question without topic chips (`has_topic` is true for everyone: only people with a job stay in tiers 1 to 4); a search stored before this task and reranked; a consul or a board member from a job list with a role and no employer, on a question whose role chip they meet (confirmed) and on one without a role chip (not confirmed); a version-1 search with a place chip, where people inside the area and people with an unknown place keep today's order.

## Tests (each must fail without the change)

- `tests/test_evidence.py`: `job` is `known` for a stated role plus a `works_at`; `employer` for a fellowship role plus a recent affiliation and for a page-title role of a web person plus an employer; `none` for a role without an employer and for a role plus an affiliation whose newest year is older than `RECENT_YEARS`.
- `tests/test_rank.py`: on a version-2 business question, a person with topic words, a strong tie and no job is tier 5, and the same person with a role and an employer is tier 1; a person with the topic, a job and no tie is tier 3 and stands before the tier-5 person; on a version-1 question the person without a job keeps tier 1; an OpenAlex-only person with an employer and no role is tier 1 on a version-2 question without a role chip and tier 5 on one that names a business role, and a seed person with an employer alone is tier 5 on both; a person with a met role chip, a tie and no employer is tier 1; inside tier 1 of a version-2 question a person inside the area stands before one with an unknown place; on a version-1 question with a place chip those two keep their score order.

## Existing tests that change

`tests/test_rank.py` builds its tier cases with a `found()` helper and version-2 chips (`TierTest`, near line 312). Give `found()` a `job` parameter and set `job="known"` on the cases that are meant to stand in tiers 1 to 4, so `test_the_eight_cases`, the must-tie cut test and the tier-1 and tier-2 order tests keep their expected values. The new no-job cases are separate tests. Any other existing test that pins a tier for a version-2 question with people who have no role or employer may change its expected tier: list each with the old and the new value in your report. Stop and report if a version-1 test changes.

## Hand check

`uv run python -m unittest` all green. Then on a throwaway copy of the owner's data (`mkvar.sh`), `FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` before and after the change: every stored search has version-1 chips, so the kept count and the order of each must be identical; print one line per search that differs (expect none).

## Not doing

- Cutting anyone. A change to headings or their words. A lookup of what a thin person does today. A change to the score inside a tier beyond the place order.
- A role for LinkedIn records. They hold a `works_at` with the title only in its quote, so a LinkedIn-only person counts as an employer alone. The LinkedIn lane is off; when it is switched on, its title should become a role claim.
- The heading words for a question without a topic chip: a person with a tie and no known job then stands under "Tie, topic not confirmed" although no topic was asked.

## Effects outside the ranker, known and accepted

Fewer people reach tiers 1 and 2 on version-2 questions, so `search.first_heading` is lower and the `tier_n` and `first_heading_under_5` numbers of `score.py` shift against stored baselines. The `web_topic` lane's gate reads that count; that lane makes no call once the scout lane is on (a separate change), so no paid call is added.
