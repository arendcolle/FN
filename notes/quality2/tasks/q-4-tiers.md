# Task Q-4: tiers in the ranker

## Goal

The ranker puts a tie before the topic (`rank.group` and `rank.band`, `src/fn/rank.py:140-153`), so a strict top group is empty in 17 of 27 stored searches, and a topic expert without a tie sits below everyone with a tie. 44% of first-20 cards come from OpenAlex alone with no gold pick among them (`research/gold-reality.md`). This task orders people topic first in seven tiers under four headings, hides people without a tie when the tie is a must, moves people who clearly fail the role asked for to the last tier, caps OpenAlex-only people in the first 20, lets at most 20 topic experts back in from the `no_belgian_evidence` cut for new searches only, and stores each candidate's tier and fit for the pages. Decisions R3 (demotion), R4, R7 (cap) and the lead's rulings on legacy chips, the fourth heading, seven tiers, the stored fit, related words, the cap, stored searches gaining nobody, the order inside a tier and tier 6. Owner: `rank.py`. Needs Q-1 and Q-3.

## The tier table

"Topic" is `ev.topic.match` (own words or a related word), true by default when no topic chip has content words (as `rank.group` today). "Word" is at least one entry in `ev.topic.words`. "Tie" is `ev.belgian.grade` strong or medium; weak counts as none (R5). "Place fits" is `place_fit` inside, unknown or none; an unknown place fits, so nobody moves down for it (D12 of the last round).

| Tier | Rule (design ruling "Seven tiers") | Heading |
| --- | --- | --- |
| 1 | topic, tie, place fits | 1 Topic and a tie to Flanders |
| 2 | topic, tie, place outside or abroad (abroad last) | 1 |
| 3 | topic, no tie, place fits | 2 Topic, no known tie |
| 4 | topic, no tie, place outside or abroad | 2 |
| 5 | no topic, tie, a word | 3 Tie, topic not confirmed |
| 6 | no topic, tie, no word; or no topic, no tie, a word | 3 with a tie, 4 without |
| 7 | no topic, no tie, no word; and anyone whose `ev.role.fit` is `fails` | 4 Other people found |

Tier 7 is always under heading 4, also when the tie is a must. The heading words belong to `present.py` (UI-5); this task gives the number.

## What to build

### `src/fn/contracts.py`

- `PlaceFit = Literal["inside", "outside", "abroad", "unknown", "none"]`.
- `class CardFit(Model): tie_grade: TieGrade = "none"; tie_claim_ids: list[str] = []; place: PlaceFit = "none"; role: RoleFit = "unknown"`. `TieGrade` and `RoleFit` come from Q-3.
- `Candidate` (`src/fn/contracts.py:395`) gains `tier: int | None = None` and `fit: CardFit | None = None`; None means stored before this round. `CutReason` (line 52) gains `"no_tie"`.

### `src/fn/rank.py`

- `place_fit(found: Evidence, question: Question | None) -> PlaceFit`: `none` when `question` is None or has no place chip; `abroad` when `abroad(found, question)`; `inside` when `found.place.fit` is inside, or when `question.area` is None and `question.country` is in `found.place.countries` (an `anywhere_us` question); `outside` when `found.place.fit` is outside; else `unknown`.
- `tier(found: Evidence | None, question: Question | None) -> int` per the table; 7 for no evidence. `heading(tier: int, tie_grade: TieGrade) -> int`: 1, 1, 2, 2, 3, then 3 for tier 6 with grade strong or medium and 4 without, then 4. The pages call it with `Candidate.fit.tie_grade` ("none" when `fit` is None).
- `fit_of(found: Evidence | None, question: Question | None) -> CardFit | None`: `CardFit(tie_grade=found.belgian.grade, tie_claim_ids=list(found.belgian.claim_ids), place=place_fit(found, question), role=found.role.fit)`; None without evidence.
- Remove `group` and `band`. `Candidate.group` stays for the scorecard: 0 for tiers 1 and 2, else 1.
- New-section order key: `(tier, heading, abroad, role, related, grade, place, -len(words), -score, person_id)` (lead's ruling "Order inside a tier": role met first, then own words before related words, then grade, place, topic words, score). `abroad` is 1 when `place_fit == "abroad"`, else 0, so people abroad stand last in tier 2 whatever their role or grade (ruling "Seven tiers"). Role met 0, unknown 1, fails 2; `related` 1 when `ev.topic.related` else 0; grade strong 0, medium 1, else 2; place 0 when it fits, 1 outside, 2 abroad. `heading` keeps tier 6's two headings apart: tier 6 with a tie stands under heading 3, after tier 5; tier 6 without one stands under heading 4, before tier 7 (lead's ruling "Tier 6 holds two kinds of people"). The network section keeps its order by score and is never cut.
- `no_tie(section, found, question) -> CutReason | None`: `"no_tie"` for a new-section person with evidence and grade weak or none when `parse.tie_must(question.chips)`. It runs after `cut_reason` and the exemption, on people no other cut took.
- The exemption: only for version-2 chips (lead's ruling "Stored searches gain nobody either"), and when the tie is not a must, a person whose cut is `no_belgian_evidence`, with `topic.match` and not abroad, is kept. Only the first `EXEMPT_CAP = 20` such people in the order above; the rest keep the cut.
- The cap: when `parse.asks_researchers(question.chips)` is false, at most `OPENALEX_CAP = 5` of the first `TOP = 20` kept new-section people are OpenAlex-only, read as `found.only_openalex` (every record on the card holds only `openalex` or `orcid` schemes, `src/fn/evidence.py:161`), the same test as the role `fails` rule. Do not read `lane_ranks`: on a question without a role chip Q-2 lets the seeds lane return stored OpenAlex records too, so their lanes are `{seeds, openalex}`. Walk the kept list from the top; a sixth or later such person inside the first 20 moves to just after the last person of its own heading (`heading(tier, grade)`), never under another heading. Each person moves once. When a heading ends inside the first 20 the cap can stay unmet; report it, do not break the headings.
- `fuse` sets `tier`, `fit` and `group` on every `Candidate`.

### Store and migration

- `src/fn/migrations/012_candidate_tier.sql`: `ALTER TABLE candidates ADD COLUMN tier INTEGER;` and `ALTER TABLE candidates ADD COLUMN fit_json TEXT;`. Old rows stay NULL until `fn-rerank`. This task owns 012.
- `store.save_candidates` (`src/fn/store.py:566`) writes `tier` and `fit_json` (`c.fit.model_dump_json()`, or NULL); `list_candidates` (line 588) reads them back, None for NULL.

### `src/fn/score.py`

In `card_metrics`, over the kept new-section people: `tier_1` to `tier_7` (counts) and `first_heading_under_5` (1 when tiers 1 and 2 hold fewer than 5, else 0), added to `SUMS`. `lane_openalex_only` already gives the OpenAlex-only share of the first 20. Rows of searches without kept people stay as they are.

## Legacy chips

Version-1 chips (lead's rulings): `parse.tie_must` is false, so nobody is cut `no_tie`; the exemption does not apply, so nobody comes back from `no_belgian_evidence`; `parse.asks_researchers` is true, so the OpenAlex cap does not apply; there are no role chips, so nobody is demoted; there are no related words. `fn-rerank` of a stored search keeps exactly the people main keeps, neither cutting nor adding anyone for lacking or having a tie. Only the order and the headings change.

## Worked examples, as tests in `tests/test_rank.py` (made-up names)

- `ASK` with v2 chips and no tie chip: the eight cases of the table (tier 6 twice) come out in tiers 1 to 7, each with its tier, group and `heading`, tier 6 with a tie before tier 6 without.
- The same people with v2 chips and a tie chip of need "must": weak and none are cut `no_tie`; the network person with no tie is kept.
- The same people with v1 chips: nobody is cut `no_tie`.
- Tier 1, three pairs: role met before unknown, although the met person matches only on a related word; then, with the same role fit, an own-word match before a related-word match although its score is worse; then strong before medium.
- Tier 2: outside before abroad, also when the abroad person has role met and a strong tie and the outside person has role unknown and a medium tie.
- Role fails with topic and strong tie: tier 7, heading 4, and kept under a must tie.
- `place_fit` for each value, including an `anywhere_us` question (no area) and a person in the US: inside.
- `fit` on a saved candidate: grade, tie claims in Q-3's order, place and role.
- 25 OpenAlex-only people with `no_belgian_evidence`, topic match, not abroad, v2 chips, tie nice: 20 kept, 5 keep the cut; under a must tie all 25 are cut; with v1 chips all 25 keep the cut.
- V2 chips with no role chip (the only case where the cap and the OpenAlex lane both apply), heading 1 of 30 people of whom 8 OpenAlex-only by `only_openalex` in the first 20, some with lanes `{seeds, openalex}`: 5 stay, 3 move to the end of heading 1. Heading 1 of 10 people, 8 OpenAlex-only: the order stays, and the test says so.
- `tier(None, None)` is 7; `heading(6, "medium")` is 3 and `heading(6, "weak")` is 4.
- `tests/test_db.py`: 012 adds nullable `tier` and `fit_json`; a candidate saved with tier 3 and a fit lists with both; an old row lists with None for both.
- `tests/test_score.py`: a search with kept people in tiers 1, 3 and 7 gives `tier_1` 1, `tier_3` 1, `tier_7` 1 and `first_heading_under_5` 1.

## Inputs a real run will meet

A question with no topic chip (topic true by default); no place (`place` "none"); `question` None in direct `fuse` calls (no exemption, as for version 1); no evidence for an entry (tier 7, fit None); every person OpenAlex-only; a must tie with nobody tied (empty kept list); stored candidates from before 012; a network person who would be cut.

## Existing tests that change

- `tests/test_rank.py` helper `found()` gains `grade` (default "strong" when `kinds`, else "none"), `role` (default "unknown") and `related` (default False). No assertion in other tests changes.
- `OrderTest.test_the_five_bands_come_in_order_whatever_the_lane_score` becomes the tier order: expected `[("g0in", 0, 1), ("g0out", 0, 2), ("abroad", 0, 3), ("g1", 1, 4), ("g1out", 1, 5)]` as (person, group, rank), since the abroad person has a topic and a tie (tier 2, abroad last) and the two without a full match have a tie and the word "wind" (tier 5). Its name and docstring say tiers.
- The applied-migration lists gain 12: `tests/test_db.py` lines 77 and 103, `tests/test_orgs.py:319`, `tests/test_web.py:654`.
- Every other test must stay green unchanged, among them `test_an_unknown_place_moves_nobody_down`, `test_without_a_topic_chip_a_tie_alone_is_group_0`, the `CutTest` cases and `CardRecordsTest`. If one fails, stop and report.

## Hand check and gates

`uv run python -m unittest` all green. Then on main and the branch: `fn-score run <snapshot> --mode rerank --out <scratch>`, `fn-score compare`, and `fn-score diff --names` for three searches, described without names.

- Gold picks in the first 20: `research/tiers.md` measured 5 under its ladder against 5 today, none lost. No gold pick main keeps may be cut: stored chips are version 1, so `no_tie` cuts nobody there.
- The kept people per search are the same as on main: version 1 lets nobody back in from the cut.
- `first_heading_under_5` and the tier sizes per search, against `research/tiers.md` (13 of 27 searches under 5 in tiers 1 and 2). After the live-preferring run below, report how many people the exemption let back in per search.
- `pairs_wrong` stays 0.
- Live-preferring (lead, paid, after Q-1 to Q-3): `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-gold <dev case ids>`, `fn-score snapshot`, `fn-score run --mode rescore`: the OpenAlex-only share of the first 20 for business questions against 44%, as `lane_openalex_only` and beside it the share by `only_openalex`, and GS-10, 15 and 29 keep their researcher picks.

If a gate fails, do not tune a rule to pass it. Report the numbers and the rule that moves them.

## Not doing

Headings on the page and their words (UI-5). The card's lines from the fit (UI-4). A cut or tier from `place.need` or `topic.need`: stored, not read this round. The `web_topic` lane (Q-5). Raising the exemption cap before a benchmark run shows those people help.
