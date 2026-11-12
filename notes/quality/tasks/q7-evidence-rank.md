# Task Q7: evidence, and an order that reads the question

## Goal

The ranker sums lane positions and Belgian years and never reads the question. 42% of the first 20 people sit outside the place asked for, only a third have a claim that names the topic, and a search keeps a median of 518 people. This task adds one module that says what a person's records show for a question, and makes the ranker order and cut by it. Decision D12 in [panel-records.md](../panel-records.md) and the rulings in [plan.md](../plan.md) are the rule set. [research/ranking.md](../research/ranking.md) has the measurements and the replay that these rules come from.

## What to build

### 1. `src/fn/evidence.py`, pure functions

`evidence.places(claims, orgs, today) -> list[Place]`: the places of a person.

- A stated place: a location claim with coordinates, of any date, except a birthplace.
- The employer's city: for a `works_at` or `affiliated_with` claim dated within five years before `today` (its `valid_to`, else its `claim_date`), the city and coordinates of its organization when `orgs` holds them.
- Each place has its coordinates, its text, its country, its basis (`stated` or `employer`), its claim id and its year.
- "Recent" has this one definition. `today` is the search's creation time, so a replay gives the same answer every day.

`evidence.of(card, claims, orgs, ask, today) -> Evidence`: what the records on a card show for a question. `card` gives each record with its identifier schemes. `ask` holds the chips, the area of the place (or none) and the question's country (or none).

| Field | Meaning |
| --- | --- |
| `topic.match` | every content word (`parse.content_words`) of at least one topic chip stands, at a word start, in the value or the quote of one claim. A final "s" of the chip word is dropped first, so "designers" finds "designer". This matcher lives in `parse.py`, beside `content_words`, and the scorecard's topic metric uses it too |
| `topic.words`, `topic.claim_ids` | the content words found in any claim, and the claims that hold them, best first |
| `institution` | a claim at the organization of an institution chip, with its claim ids |
| `tie` | its kind and claim ids: a seed-list record, a claim at a Belgian organization, a text or place in Belgium, or an institution match. `tie.years`: the Belgian years as the ranker counts them today, and the last one |
| `place` | `inside` when any place lies within the area's radius, `outside` when the person has places and none does, `unknown` when there is none or the question has no area. The nearest distance, the claim id, and the set of countries |
| `sources` | the number of distinct sources |
| `only_openalex` | every record on the card has no identifier besides `openalex` and `orcid` |

### 2. `src/fn/geo.py`

`geo.country_at(names, lat, lon) -> str | None`: the country code of the nearest city in the cities file, within 100 km. And the question's country: the country of the area's city; `US` for a place of kind `anywhere_us`; none for a question without a place and for a place of kind `abroad`.

### 3. `src/fn/rank.py`

- Evidence and Belgian years are computed over the records on the card (`card_person_ids`; for an entry without them, the hit records). A record that is only a possible match never counts. `tests/test_rank.py`'s test that a record joined only by name never scores stays green unchanged.
- Score parts, each worth 1 / (60 + its rank on its own list) and each carrying the claim ids that earned it: the lanes and `belgian_years` as today; `topic`, ranked by the number of content words found, with the found words in its `detail`, comma separated, so the page can print them; `place`, for people inside, ranked by distance, with the place's basis (`stated` or `employer`) and its text in its `detail`; `seed_list`, a fixed 1 / 61 for a card with a seed-list record.
- Two groups. Group 0: a topic match and a tie. Group 1: everyone else. A question without a topic chip puts everyone with a tie in group 0.
- Order inside a section: group 0 not outside the area, group 0 outside the area, group 1 not outside, group 1 outside, then people with a place only outside the question's country and no institution match. Inside each of these, by score. Nobody moves down for an unknown place.
- Cuts, only in the new section and only for `only_openalex` people. `rank.cut_reason` reads `Evidence` and no longer tests which lanes found the person.
  - `no_belgian_evidence`: no Belgian years (today's rule)
  - `weak_openalex`: no topic word in any claim, at most 2 Belgian years or none since 2016, not inside, and no institution match. All three new cuts spare a match on an institution chip: a question about one university is answered by people of that university
  - `no_claim`: no topic word in any claim, no institution match, and not inside
  - `outside_country`: the question has a country, the person has at least one country, none of them is the question's, and there is no institution match
- `Candidate` gains `group: int`. `CutReason` gains the three new values. Migration `010_candidate_group.sql` adds the column. Tests that pin the list of applied migrations gain 10; the lookup task, built at the same time, adds 11 to the same lists and the manager joins the two at merge.

### 4. `fn-rerank` (`src/fn/search.py`)

`fn-rerank SEARCH_ID...` or `fn-rerank --all` runs `search.refinish` on stored searches in the settings' database and prints, per search, the people kept before and after. It is the only way stored results change.

### 5. The scorecard (`src/fn/score.py`)

`place_inside`, `place_outside` and `place_unknown` come from `evidence.of`, so the employer's city counts. New: `cut_seed_top20`, the first-20 cards of the base run that the head run cut although they hold a seed-list record (computed in `compare`), and `group0_top20`, the share of first-20 cards in group 0.

## Inputs a real run will meet

A question with no topic chip; with no place; with a place of kind `anywhere_us`, of kind `abroad`, a state, a city the cities file does not know; a person in the network section (never cut, ordered as today); a person with a Belgian and a US place; a person whose only place comes from an employer fact six years old (no place); an organization without a city; a card with a seed record and an OpenAlex record (never `only_openalex`); a person found only on a web page (never cut); a search where every lane returned nothing; a topic chip of only generic words (no content words: no topic match is possible, treat it as no topic chip).

## Tests

With made-up names, in `tests/test_evidence.py` and the rank tests:

- `places`: a stated place; an employer's city from a recent fact; none from a fact six years old; none for a birthplace
- topic: all words in one claim is a match; the words spread over two claims is not; a word start is needed ("care" does not match "scared")
- tie: each kind; `only_openalex` is false for a card with a seed record or a web mention
- place: inside, outside, unknown; the countries of a person with two places
- order: the five bands in order; an unknown place does not move anyone down; groups are monotone (no group 1 person above a group 0 person in the same band class)
- each cut with one case that is cut and its nearest case that is kept, among them: an `anywhere_us` question, a person with a Belgian and a US place, a person with no place, an institution match, a person in the network section, a person on a seed list
- `fn-rerank` changes a stored search's candidates and leaves another search alone
- the scorecard's place metrics count an employer's city

Each new test must be seen failing without the change it covers.

## Changes to existing tests, approved

Tests that pin the exact order or the exact score parts of ranked candidates follow the new order and parts. Tests that pin the list of cut reasons or the columns of `candidates` follow the new values. Say which tests changed and how. The test that a record joined only by name never scores, and the tests of today's `no_belgian_evidence` cut for an OpenAlex-only person without Belgian years, must stay green unchanged. If another test fails, stop and report it.

## Hand check and gates

From this worktree and from the main checkout (read only): `fn-score run var/score/2026-11-12 --mode replay --out <scratch> --allow-degraded`, then `fn-score compare main.json branch.json` and `fn-score diff main.json branch.json --names var/score/2026-11-12` for three searches. Paste the aggregates and say in plain words what the diff shows for those three searches, without names. The gates, branch against main:

- no gold pick that reaches the ranker on main is cut, and `gold_free_at_10`, `_20` and `_50` do not fall
- `seed_noise_top20` falls and `cut_seed_top20` is 0. The count cannot reach 0: the text index stems words and the scorecard counts exact word starts
- `place_outside` is at most 0.15
- the median of people kept is at most 250. The panel's replay gave 156 before OpenAlex people carried topic claims. They do now, so fewer of them are cut for having no claim, and the first run of this task measured 228 and 246
- the `complete` gate of `fn-score compare` may fail on the second snapshot: the new order puts seed people first, who have no place until the lookup batch and the page task fill it. The final check has its own pass lines for place and role
- `pairs_wrong` is 0

If a gate fails, do not tune a rule to pass it. Report the numbers and which rule moves them.

## Not doing

- The seed lane's place search, the why line on the card, the page size. Other tasks.
- Synonyms, such as "AI" for "artificial intelligence".
- A label or divider for group 0.
- A cut for anyone who is not `only_openalex`.
