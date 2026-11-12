# How do FN's search results get good, and how do we know?

2026-11-12 · version 3 · decisions D11 to D13 settled by panels and the lead's rulings; the plan review's findings are worked in

**TL;DR.** A search today lists a median of 510 people, puts 3 of 99 gold picks in the first 20, and shows cards without a role (97%) and often without a place (42%). Seven research notes measured why. Three causes carry most of it. First, the people staff pick are mostly not in FN's sources: 70 of 83 gold picks never reach the ranker. Second, the ranker never reads the question: it ignores topic and place, so 42% of the first 20 people sit outside the place asked for. Third, cards drop data FN already holds, such as the employer's city. People shown twice are rare (0 pairs in any first 20), but five places in the code decide who is one person, with two different rules. This design adds a scorecard that gates every change, one owner for identity, one for evidence, an enrich step for the first people, new seed lists, and a results page of 20. The web lane reads its pages at the same time, which takes a search from 257 s to about 70 s.

## What is wrong today, in numbers

Each row is measured on the owner's database (25 finished searches with results, 500 first-20 cards). The notes are in [research/](research/).

| Problem | Number today | Note |
| --- | --- | --- |
| People staff picked that reach the ranker | 13 of 83 gold picks | ranking |
| Gold picks in the first 20 | 3 of 99 | scorecard |
| People kept per search | median 510 | scorecard |
| First-20 people only OpenAlex found | 69% | ranking |
| First-20 people with a known place outside the place asked for | 42% (19 searches with a place) | ranking |
| First-20 cards where a claim names a topic word | 32% | ranking |
| Seed hits that matched only a stop word or a generic word | 488 of 1,664 | ranking |
| First-20 cards with no place | 42% (all 79 seed-only cards) | completeness |
| First-20 cards with no role | 97% | completeness |
| Empty places that the employer's known city would fill | 178 of 212 | completeness |
| Shown employers that rest on a fact older than five years | 18% | completeness |
| Likely pairs of one person on two cards | 0 in a first 20, 2 in all first 50s, 90 in all lists | identity |
| Cards that bundle 3 to 9 different OpenAlex records under one initial | 8 | identity |
| Places in the code that decide who is one person | 5, with 2 veto rules | identity |
| Gold picks named in public records FN does not read | 56 of 99 | sources |
| Seconds for a search with live calls | 257, of which 228 in 19 model calls in a row | speed |

Two things the owner saw need a note. People shown twice, once from OpenAlex and once from a seed list, exist: 6 pairs in all stored lists, caused by four gaps in how names are compared. And "location not found" is not solved by joining the records FN holds: that fills 11 of 212 empty places. The place has to come from the employer's city (178) and from a lookup of the person's missing record.

## What a search does after this work

1. `parse` reads the question into chips: topics, institutions, place. Unchanged.
2. The lanes find records. The seed lane drops stop words and also searches the place. The web lane reads its pages at the same time. The OpenAlex lane stores the titles of the matching works as topic claims.
3. `resolve` asks `identity` which records are one person, and builds one entry per person.
4. `rank` asks `evidence` what each entry shows for this question (topic, tie, place, sources) and orders: people with a topic match and a tie first, people known to be outside the place last within their group. It cuts weak people only OpenAlex found.
5. `save` stores the candidates.
6. The results page shows 20 people, then 20 more on request. A card shows the role, the employer and its city, the Belgian tie, and why the person is listed.

Steps 3 to 5 are one function, `search.finish`, so the scorecard, the publish steps and a rerun of stored searches use the same code.

Outside a search, `fn-enrich` looks up the facts seed people and ORCID holders miss, and `fn-seed` loads the seed lists, three of them new.

## Who owns what

One owner per row. A module calls another's entry point, never its internals.

| Responsibility | Owner |
| --- | --- |
| The words and the place of a question, and which words carry meaning (`content_words`) | `parse.py` |
| The seed search: its query, its cap, its place search | `lanes/seeds.py` |
| OpenAlex people and their topic evidence | `lanes/openalex.py` |
| People named on web pages | `lanes/web.py` with `extract.py` |
| Running calls of one step at the same time | `steps.fan_out` |
| Who is one person: name rules, evidence levels, vetoes | `identity.py` (new). `resolve`, `network` and the importer call it |
| Finding a record by an identifier | `store.resolve_person` |
| What an entry shows for a question: topic, tie, place, sources, over every linked record | `evidence.py` (new) |
| The places of a person, with the employer's city when the employer fact is recent (`evidence.places`) | `evidence.py` |
| Running the steps after the lanes again on a stored search | `search.py` (`refinish`, `fn-rerank`) |
| Order, groups and cut rules | `rank.py` |
| Looking up missing facts for seed people and ORCID holders | `enrich.py` (new, `fn-enrich`) |
| The city and coordinates of an organization | `orgs.py` |
| Seed rows into claims, with place and job title | `seedload.py` |
| Which steps run in which order | `search.py` |
| How a person reads: headline choice, wording, page size | `present.py`, printed by `web/parts.py` |
| Every part, state and string of the pages | the design system, then its copy in the site |
| Scoring results and gating changes | `score.py` (`fn-score`) |

## Contracts that change

- `identity.same_person(store, a, b) -> (level, reason)` with the levels `sure`, `likely`, `possible` and `no`, and `identity.on_card(store, candidate)`, the records a card reads now. `Entry` and `Candidate` gain `card_person_ids`, the sure and likely records. `person_ids` keeps today's meaning, and `hit_person_ids` keeps what the lanes hit. An old stored row has no card records, so its card reads the hit records as today, until `fn-rerank` runs.
- `evidence.places(claims, orgs, today)` and `evidence.of(card, claims, orgs, ask, today) -> Evidence`: `topic` (matched words and claim ids), `tie` (kind, Belgian years, claim ids), `place` (group inside, outside or unknown, the distance, the claim id, the countries), `sources` and `only_openalex`. `card` gives each record with its identifier schemes. `ask` holds the chips, the area and the question's country. Pure functions. The ranker, the seed lane's place search and the scorecard call them, so they agree. "Recent" means within five years before `today`, the search's creation time.
- `ScorePart.feature` gains `topic`, `place` and `seed_list`, each with the claim ids that earned it. `Candidate` gains `group`.
- `CutReason` gains `weak_openalex`, `no_claim` and `outside_country`.
- `OrgFacts` and the `orgs` table gain `city`, `lat`, `lon`.
- A `lookups` table: one row per person and lookup kind with the verdict (matched, ambiguous, no match), so the batch goes on where it stopped and never asks twice.
- `PersonView` gains `place_basis` (stated, employer) and `why`, the words of the why line, built from the claim ids stored in the candidate's score parts.

## Decisions

Settled by measurement:

- **D17. The model and its effort level stay.** Low effort found the same 35 people on four pages and saved no time. The older small model without thinking was 2 to 4 times faster and lost 4 of the 35. The current small model cannot run without thinking through the command line.
- **D16. No model rerank step now.** 68% of first-20 cards hold no topic claim a model could cite, and no labelled set exists to show a gain.
- **D15. The results page.** 20 people, then "Show 20 more". A card without a place says nothing about it; the count line already gives the number. The city stands next to its employer. People beyond the shown cards are small muted dots on the map. The heading says "Best matches" only if the scorecard shows a better order.

Settled by a panel each (records and dissent in [panel-records.md](panel-records.md)). No panel reached full agreement, so each is the majority decision, with the lead's ruling where two panels disagreed.

- **D11. Who is one person.** One owner, `identity.same_person(a, b) -> (level, reason)`. Sure: a staff merge. A shared identifier already makes one record when it is stored. Likely: the same name key after fixes to how names are compared, both first names at least two letters, no veto, and one backer: a shared organization held by fewer than 300 records; a shared organization of any size together with a name key held by at most 3 records (records that are only a mention on a web page do not count); two rows of one seed list at most 10 years apart; or a rare name alone when one of the two records is only a mention on a web page, which has no organization to share. The panel had also let a rare name alone count. The labelled pairs showed that rule linking two different people and proving only 4 of 82 pairs the same, so the lead tightened it. A record of a person in the network is linked only by sure, so nothing joins the network without a staff decision. Possible: every other name match, including an initial against a full first name. Vetoes: a not-same decision, different middle initials, first names that do not fit, different ORCIDs, different profile links. Sure and likely records share a card and the card shows the facts of all of them, each with its source. The card says how many records it combines, and the profile lets staff split one off. Nothing merges in the store until staff press Add. Add merges sure and likely records, so two rows of one seed list can merge. Two OpenAlex ids or two seed rows no longer block a merge.
- **D12. Order and cut.** `evidence` owns each fact and the ranker reads it. A topic match means every content word of one topic chip stands in a claim of a record on the card. A tie means a seed list, a Belgian organization, Belgian years, Belgian text or place, or a match on an institution chip. Two groups order before the score: people with a topic match and a tie, then everyone else. Inside a group the score decides: lane positions, Belgian years, topic, place and seed list. A place is the stated place, or the employer's city when the employer fact is recent: within five years before the search. A known place outside the area asked for goes last in its group. Nobody is cut or moved down for a missing place. Cuts, all for people whose records all come from OpenAlex: no Belgian evidence (today's rule), weak evidence (no topic claim, at most 2 Belgian years or none since 2016, not inside the place), no claim (no topic claim, no institution match, no place inside the area), and outside the country.
- **The lead's ruling on the last cut.** The two panels disagreed. The sources panel wanted every OpenAlex-only person outside the country of the question cut, also when the place is unknown: median 149 people kept, one gold pick lost. The ranking panel's majority wanted no cut by place: median 238. The ruling is the cut the ranking panel measured as its strictest variant: an OpenAlex-only person with a known place outside the country of the question and no match on an institution chip is cut. A person with an unknown place is not cut by this rule, a person on a seed list is never OpenAlex-only, a person in the network section is never cut, and a question without a place has no place cut. The exact test, with the question's country and a person's countries, is in [plan.md](plan.md). Measured on the 25 stored searches: median 156 people kept instead of 510, all 13 reachable gold picks kept, the same first 20 as the looser variants. Reason: the owner asked for far fewer people and as little noise as possible, four of six reviewers accepted a cut by country, and it costs no gold pick.
- **D13. Sources and lookups.** Three new seed lists, in this order: Wikidata people with a Belgian tie and a US employer or residence (about 949 people), the board pages of the Belgian-American chambers, and the 2022 mission program read from its archived copy. The delegation's event pages and the mission brochures wait. The seed lane also searches the place of a question when the place is a city area: it matches current places within 100 km, returns at most 20 people and ranks them below topic hits. OpenAlex stays a lane, unchanged inside. Missing facts are looked up by one offline batch that can stop and go on: an OpenAlex author by name for each seed person, and ORCID employments for each ORCID FN holds. The batch stores a looked-up author only when the name key matches and the two share an organization. `identity` alone decides whether they are one person, as for any two records. A lookup inside every search waits until the batch shows what is still missing.
- **D15 additions from the ranking panel.** The heading stays "New", with no "Best matches" and no divider. Each card gets a why line built from the claims that put it where it is: the matching words, the tie and the place with its basis.

Settled by the lead during the build, each from a measurement in [progress.md](progress.md):

- **A rare name.** A name is rare when at most 3 records hold it, not counting list rows and web mentions, because one person has many of those. A rare name backs a link only together with a shared organization and when one of the two records is a list row or a mention, or when one record is only a web mention.
- **Two rows of one seed list** are one person only when their keys differ in the year alone and the years are at most 10 apart.
- **A stated place decides where a person is.** An employer's city only counts when no place is stated.
- **Inside a band, more topic words come first**, then the score.
- **The seed lane searches the place only for a question that names a place and nothing else.** Beside a topic it lifted people who match only the city above topic matches.
- **A full topic match outside the place stays above a partial match inside it.** The other order gave the same gold picks and more people of unknown place.
- **A different ORCID iD keeps two records apart**, also when they share many organizations.

## How we measure

`fn-score` runs on a frozen snapshot: the database, the HTTP cache and the recorded model answers. It has three modes. `rescore` reads stored results. `rerank` runs `search.finish` on stored lane outputs (12 s). `replay` runs whole searches from the cache (about 40 s). A branch is compared with main on the same snapshot before it merges.

Gates: likely pairs in the first 20 do not rise, gold picks in the first 20 and in the kept list do not fall, and the share of complete cards does not fall by more than 0.02. The other metrics are reported: people kept, the share of the first 20 with a topic match, inside and outside the place, with a place, a role and a recent employer, and the lane mix.

Two limits. The gold set is small: one pick is one hundredth of recall, so the report names each pick that moved. And three of the new seed lists are the records the gold set was built from, so gold recall rises partly by construction. The report splits gold picks into those a seed list names and the rest.

## Not doing

- A model rerank step (D16).
- A lookup of missing facts inside every search. The offline batch comes first.
- The delegation's event pages, mission brochures and chamber event pages as seed lists.
- Lanes side by side: 7 to 18 s for the most risk, after the page reads are fast.
- Reading LinkedIn. Robots rules forbid it, and the paid lane stays off.
- A mapping step, Excel import and the other open items of the first build.
- Labelling cards good or bad by a batch of agents. That needs rules agreed with the owner first.

## Risks

- A wrong link shows another person's facts on a card. The levels are set from a sample of 30 pairs, so the thresholds start strict, the scorecard counts pairs, and "Not the same person" undoes a link.
- Order by evidence pushes people without a known place up, so more first-20 cards miss a place (43% to 78% in the replay) until the enrich step and the employer's city fill them.
- The enrich step and the new lane behaviour cannot be replayed from stored calls. They are checked with fixtures and with a few live searches.
