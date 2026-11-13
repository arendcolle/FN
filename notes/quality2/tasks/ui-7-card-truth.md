# Task UI-7: cards and pages that say only what holds

## Goal

The third walkthrough ([research/ux3-walk-new.md](../research/ux3-walk-new.md), [research/ux3-walk-check.md](../research/ux3-walk-check.md), [research/ux3-design-review.md](../research/ux3-design-review.md)) found that navigation, word counts and the page layout now hold, and that some lines mislead. On 67 of 100 first cards the reason line is a fellowship host, a study year or a record's affiliation, and on 43 of 785 cards it is a page's title. 58 of 175 cards say "in the US" or "elsewhere in the US" beside a role line in Bruges or Geneva. The first heading says "tie to Flanders" over people whose tie is in Brussels or Wallonia. A partner's title was joined to a government job of 2006 to 2009. The lead ruled V22 to V28 in `design.md` ("Rulings after the third walkthrough"), and the design system holds them (version 12.2: the PersonCard, SectionHeading, Claim and Profile part READMEs and `STRINGS.md` in the design system folder). This task brings the site in line. It ships no ranking change: V28 belongs to another task.

## What to build

Read the four part READMEs named above and the design system's `STRINGS.md` first, and copy their words. Copy the design system's `STRINGS.md` over the repository's copy (`notes/e2e/design-system/STRINGS.md`) as the person page task did. `src/fn/web/static/fn.css` does not change.

1. **The reason line (V22)**, in `src/fn/present.py` where the card's reason is chosen (`reason_of` and the claim it is given). The reason is the first of: (a) a claim that says what the person does today on the question's subject: a role claim for which `evidence.stated_role` holds, or a topic claim from a page; (b) a topic fact: a work (paper) claim or a topic claim from a record. With neither, the card has no reason line. Never a claim whose relation is `worked_at`, `hosted_by`, `affiliated_with`, `studied_at`, `fellow_of`, `member_of`, `consul_for`, `born_in`, `lives_in` or `origin`, never a role that is not a stated role (a page's title), and never a line whose words repeat the role line: compare the reason's text with the card's role and employer after `name_key`, and drop the reason when the role line holds every word of it. Where the ranker's stored reason claims (`Candidate.reason_claim_ids`) hold a claim of kind (a) or (b), take the first such; else look through the card's claims in the order the person page lists Work. The why block's first line follows the same choice.
2. **The headings (V23)**: `present.HEADINGS[1]` reads "Topic and a tie to Flanders or Belgium". Under the heading "Topic, no known tie" the card's second line leaves out "No known tie to Flanders"; under any other heading a card without a tie still says it. The why block keeps its tie line as today.
3. **One place per card (V24)**: `place_words` gives "place unknown" (card) and "Place unknown" (why block) when the card's role line shows no place, and nothing in every other case. The words "in `{city}`", "in the US", "elsewhere in the US" and "outside the US" go from the card and from the why block. The map's use of `place_fit` is unchanged.
4. **Each fact once in the why block (V25)**: a line whose words, after `name_key`, equal an earlier line's is left out.
5. **Joined roles (V26)**, in `joined_roles` or the function that pairs a stated role with an organization: the organization comes only from a `works_at` claim of the same source, never from `worked_at` or any other relation. A role whose text already holds the organization's name (compare after `name_key`: "Managing Director at BGR Group" holds "bgr group") is not followed by the organization again: the line reads the role alone with its years. The head's role line follows the same rule.
6. **"Consul for" (V27)**: the relation word for `consul_for` is "Consul for", so the line reads "Consul for Belgium".

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which fact is a card's reason, and the words of the second line and the why block | `present.py` |
| What a stated role is | `evidence.stated_role` |
| The words themselves | the design system's part READMEs and `STRINGS.md` |

## Inputs a real run will meet

A card whose stored reason is a fellowship host; one whose only claims are a fellowship and an affiliation (no reason line); a web person whose role claim is the page's title (no reason line from it); a role line "Partner, Example LLP" with the reason "Partner" (dropped as a repeat) and with the reason "Topic: export controls" (kept); a search stored before this round, without stored fit; a card under "Topic, no known tie" with and without a known place; a person with a place in the role line and `place_fit` of inside, outside, abroad and unknown (no place words for any); a source that states a role and both a current and a past job; a role that names its own organization; a consul from the list of honorary consuls and a consul general found on a web page.

## Tests (each must fail without the change)

In the test files that hold the card and person page tests (`tests/test_card_lines.py`, `tests/test_person_content.py`), with made-up names:

- A stored reason that is a `hosted_by`, `studied_at` or `affiliated_with` claim gives no reason line when the card has no role or topic claim, and gives the stated role or the topic claim when it has one.
- A page-title role is never the reason line nor the why block's first line.
- A reason that repeats the role line is dropped; one that adds a topic stays.
- The first heading's text; no "No known tie to Flanders" under "Topic, no known tie"; the words still stand under "Other people found".
- No "in", "elsewhere in the US" or "outside the US" words on a card or in a why block whose head shows a place; "place unknown" when it shows none.
- A why block with two equal lines shows one.
- A stated role joins a `works_at` of its source and never a `worked_at`; a role that names its organization is not followed by it.
- A `consul_for` claim reads "Consul for Belgium".

## Existing tests that change, approved by the lead

Tests that pin the first heading's words, a place-fit phrase on a card or in a why block, "Honorary consul for", a reason line that is a host, a study or an affiliation, or a joined role that repeats its organization. List each with the old and the new expectation in your report. No other existing test may change; stop and report a failure.

## Hand check

`uv run python -m unittest` all green. Then with a throwaway copy of the walkthrough data (`sh <scratchpad>/bin/mkvar3.sh ui7`, where the scratchpad is the folder the lead's instructions name; it holds four new-style searches and the stored ones) and your own server: screenshots at 1280 and 390 px of the first screen of the searches `/searches/85afc8ed-3d38-489d-887b-e4b44b8a7576`, `/searches/d8d370a6-9a67-4b5d-a6cf-b5049589088b` and `/searches/186cbce6-dfec-4d01-ad34-3da43207077c`, and of two person pages opened from them. Count on the first 20 cards of each search: cards with a reason line, cards whose reason is a host, study or affiliation (expect 0), cards with place-fit words beside a shown place (expect 0), and the median words per card. Open each screenshot and give the paths and the counts.

## Not doing

- A list entry named by its program ("Fayat scholar"). "Founded" as a relation word and open year spans. A new fold rule for long Work sections. The map's opening view. The place the ranker reads (V28). Any change to `fn.css`.
