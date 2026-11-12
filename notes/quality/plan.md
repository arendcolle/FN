# Plan: better search results, task by task

2026-11-12 · version 2, after the first plan review · the design is in [design.md](design.md), the measurements in [research/](research/), the panel decisions in [panel-records.md](panel-records.md)

**Goal.** The first 20 people of a search are the right people, each card is complete and true, the list is a third of today's, a search takes about a minute, and one command shows whether a change made results better.

**Approach.** Build the scorecard first and gate every later task on it. Then fix the data FN drops, give identity and evidence one owner each, change the order and the cuts, add three seed lists and a lookup batch, and change the results page last. Each task runs in its own worktree with one builder and an Opus reviewer, and merges as its own pull request, one at a time, rebased on main with the whole suite green.

## Tasks

Each task has a file under [tasks/](tasks/) with its interfaces, the inputs a real run meets, its tests and its hand check. A task file is written when the tasks it needs have merged, so it names the real code.

| Task | What | Needs | Files it owns | Proof |
| --- | --- | --- | --- | --- |
| Q0 | `fn-score`: snapshot, rescore, rerank, replay, compare. `search.finish`. Live model answers are kept | merged (PR 25) | `score.py`, `search.py`, `config.py`, `llm.py`, `net.py`, `geo.py` | baseline on the frozen snapshot |
| Q1 | The web lane reads its pages at the same time (`steps.fan_out`) | merged (PR 27) | `steps.py`, `extract.py`, `lanes/web.py`, `config.py` | same scorecard as main in replay |
| Q2 | Seed job titles, consul cities, organization cities | merged (PR 26) | `seedload.py`, `orgs.py`, `orgjob.py`, `contracts.py` (org facts, seed step), `store.py` (org writer), migration 008, `lanes/openalex.py` (org facts) | counts on a copy of the owner's database |
| Q6 | Scorecard round two. One owner for the words of a question that carry meaning (`parse.content_words`). One owner for running the steps after the lanes on a stored search (`search.refinish`). A frozen name matcher for gold picks. Gold picks split by "named by a seed list built from the same record". A labelled pair file and its two metrics. Seed-noise slots. A per-search first-20 diff | Q0 | `score.py`, `parse.py`, `search.py`, `gold.py` | tests per metric; rescore, rerank and replay on the snapshot give the same gold counts as before this task |
| Q5 | OpenAlex stores the titles of matching works as topic claims; its batch calls run at the same time | Q1, Q2 | `lanes/openalex.py` | lane tests; replay: the share of first-20 cards with a topic claim rises, no gate fails |
| Q8 | Three seed lists: Wikidata, chamber boards, the 2022 mission program | Q2 | `scripts/seeds/wikidata.py`, `chambers.py`, `missions.py` (new), one line each in `seedload.LISTS` | `scripts/seeds/check.py` on the rows; tests with made-up rows; the data files stay local |
| Q3 | `identity.py`: one owner for who is one person. Cards read the records identity puts on the card. Add merges sure and likely records | Q6 | `identity.py` (new), `resolve.py`, `network.py`, `importer.py` (its name match), `web/debug.py` (its name lookups), `present.py` (which records a card reads), `web/staff.py` (`card_decision` only), `contracts.py` (`card_person_ids`; `group_key` moves out), `store.py` (the candidate column and the two lookups by name key, `person_ids_by_group_key` and `network_by_group_key`), migration 009. It does not touch `score.py` or `gold.py`: their name matcher is frozen in Q6 | `tests/test_identity.py`; the labelled pair file; replay gates: 0 labelled-different pairs on one card, at most 2 first-20 cards lose a hit against main, 0 same-key pairs in a first 20, 0 bundles of initial-only records |
| Q4 | The seed lane uses `parse.content_words`, keeps 300 hits | Q6 | `lanes/seeds.py` | lane tests; replay: seed-noise slots in the first 20 go to 0, no gold pick lost |
| Q7 | `evidence.py` and the new order: two groups, score parts for topic, place and seed list, four cuts, the question's country. `fn-rerank`. The scorecard's place metrics call `evidence` | Q3, Q4, Q5 | `evidence.py` (new), `rank.py`, `geo.py` (country of a point and of a place chip), `contracts.py` (score parts, cut reasons, group, the ask), `search.py` (`fn-rerank`), `score.py` (place and cut metrics) | rank and evidence tests; the gates below, in replay mode |
| Q9 | `fn-enrich`: the lookup batch for seed people (OpenAlex author by name) and ORCID holders (employments) | Q1, Q3 | `enrich.py` (new), migration 011 for `lookups`, `store.py` (lookup rows), `lanes/openalex.py` (one entry point that stores an author) | tests with recorded answers; on a copy of the database, the share of seed-only first-20 cards with a place, and of first-20 cards with a role |
| Q12 | The seed lane searches the place of a question | Q7 | `lanes/seeds.py`, `store.py` (people near a point) | lane tests; replay: no gate fails, place-only hits stay below topic hits |
| Q10 | The results page: 20 people, the why line, the city next to its employer, no "location not found", the combined-records line, muted dots for people not yet listed. Design system first | Q3, Q7 | the design system, `present.py`, `web/parts.py`, `web/staff.py`, `static/map.js`, `static/fn.css` (copy) | page tests; screenshots at two widths |
| Q11 | Put it on the owner's server: back up, migrate, load seeds, backfill cities, run the batch, freeze a second snapshot, rerank stored searches, two live searches, the final check. Notes, architecture document and to-do list | all | notes only | the final check below |

Order: Q6, Q5 and Q8 run next, side by side. Then Q3 and Q4. Then Q7 and Q9. Then Q12 and Q10. Then Q11. Two tasks that run side by side never own the same file, except `contracts.py` and `store.py`, where each task owns the named parts and merges one at a time.

## Rulings that close the review's findings

- **Stored searches (R3, R7).** `Candidate.person_ids` keeps today's meaning: the hit records and the stored records with the same name. Q3 adds `Candidate.card_person_ids`, the records identity puts on the card. An old row has none, and its card reads the hit records as today. Stored results change only when someone runs `fn-rerank`, never as a side effect. Q11 runs it once on the owner's database after a backup, so old searches get the new order. The owner has made no decision on any stored result yet (the events table is empty). `fn-rerank` uses the stored lane outputs: an old search keeps its old seed hits and gets no topic claims for OpenAlex people.
- **Splitting a wrong link (R2).** Q3 owns `card_decision`, so Add passes every record on the card. The split control already exists: the profile's "Possible matches" block has "Different person", which writes a not-same decision. `identity.on_card(store, candidate)` drops a record with a not-same decision at render, so a split shows at once. Q10 only adds the card line that links there.
- **The cut outside the country (R4).** The question's country is the country of the area's city, or US for a place of kind `anywhere_us`, or none for a question without a place or with a place of kind `abroad`. A person's countries are the country of every stated location claim that has coordinates, of any date, plus the country of the employer's organization when that employer fact is recent. The cut applies to a person in the new section whose records all come from OpenAlex, who has at least one country, none of them the question's country, and no match on an institution chip. Tests: an `anywhere_us` question, a person with a Belgian and a US place (kept), a person with no place (kept), an institution match (kept), a person in the network section (kept).
- **A person's place (R5).** `evidence.places(claims, orgs, today)` is the one function. It returns stated places and the employer's city, each with its basis, its claim and its date. One rule for "recent": dated within five years before `today`, which is the search's `created_at`. The ranker, the seed lane's place search, the scorecard's place metrics and the card's headline all call it.
- **Stop words (R6).** `parse.content_words(text)` is the one list: English, Dutch and French function words, and the generic words the ranking note lists. The seed lane, `evidence` and the scorecard call it.
- **Gates run in replay mode (R8)**, because rerank mode reuses stored lane outputs and cannot see a lane change.
- **`evidence.of` (R10).** `evidence.of(card, claims, orgs, ask, today) -> Evidence`. `card` gives each record on the card with its identifier schemes, so `only_openalex` is decided from the records. `ask` holds the chips, the area and the question's country.
- **What the lookup batch accepts (R11).** The batch stores a looked-up OpenAlex author only when its name has the seed person's name key and the two share an organization, of any size. Whether they then count as one person is `identity.same_person`'s answer, as for any two records: sure or likely puts them on one card, possible leaves the author as a possible match. A rare name without a shared organization never stores anything. Nothing is copied onto the seed person.
- **The measuring name matcher stays frozen (R12, R16).** Q6 gives `gold.py` its own copy of today's name key, `gold.pick_key`, marked frozen. `gold.match` and the scorecard's doubles metric both use it, so the gold counts and the doubles count move only when results move, not when identity changes how it compares names.
- **The why line (R15)** is built from the claim ids stored in the candidate's score parts, not from evidence computed again at render.

## Interfaces between tasks

- Q6 gives: `parse.content_words(text) -> list[str]`; `search.refinish(ctx, search)`; the pair file `data/gold/identity-pairs.jsonl`, one JSON object per line with `a`, `b` (record ids), `label` (`same`, `different`, `unclear`) and `note`; metrics `pairs_wrong` (labelled-different pairs on one card) and `pairs_split` (labelled-same pairs on two kept cards); `gold_free_at_10|20|50` (without picks a seed list names by construction); `seed_noise_top20`; `fn-score diff`.
- Q5 gives: topic claims on OpenAlex records, `kind="topic"`, the work title as value, the work record as source.
- Q3 gives: `identity.same_person(store, a, b) -> tuple[Level, str]` with `Level = Literal["sure", "likely", "possible", "no"]` and the reason one of `merged`, `shared_org`, `same_seed_row`, `rare_name`, or the veto's name; `identity.key(name)`; `identity.on_card(store, candidate) -> list[str]`; `Entry.card_person_ids`, `Candidate.card_person_ids`.
- Q7 gives: `evidence.places`, `evidence.of` and `Evidence` (`topic`, `tie`, `place`, `sources`, `only_openalex`); `geo.country_at(names, lat, lon)`; `Candidate.group`; score parts `topic`, `place`, `seed_list` with claim ids; `CutReason` values `weak_openalex`, `no_claim`, `outside_country`; the command `fn-rerank`; metrics `place_outside` (with the employer's city), `cut_seed_top20`.
- Q9 gives: the table `lookups (person_id, kind, verdict, at)`; `fn-enrich [--limit N]`.
- Q10 reads: the stored score parts for the why line, `evidence.places` for the headline place and its basis, `identity.on_card` for the records.

## Inputs a real user will send that the tasks must cover

| Input | Task whose test covers it |
| --- | --- |
| A question with no topic, only a place or an institution | Q7 (groups without a topic chip), Q12 |
| A question whose topic is one stop word or one generic word | Q4 |
| A question with no place, with a country, with a state, with `anywhere_us`, with a place of kind `abroad`, with a city `geo` does not know | Q7, Q12 |
| A question that names a Belgian city and a US city, of which parse keeps one | Q7: the cut outside the country spares an institution match; the limit is written down |
| A person in the network section | Q7 (never cut) |
| A person with two seed rows, two OpenAlex ids, an initial for a first name, a name written surname first | Q3 |
| Two different people with one common name at one large university | Q3 |
| A person whose only record is a mention on a web page | Q3 (does not count toward rarity), Q7 (never cut) |
| A search where every lane returns nothing, or one lane fails | Q7 (empty groups), Q0 (scored as empty) |
| An organization without a city; an employer fact older than five years | Q7 (no place from it) |
| A seed page that moved or answers 403; a PDF whose text layer is empty | Q8 |
| A lookup that finds two authors with the same name at the same university | Q9 (the verdict is ambiguous and no link is made) |
| A stored search made before this work, opened before and after `fn-rerank` | Q3 (reads hit records), Q7 (`fn-rerank`), Q10 (renders both) |
| A very long list, a list of 3 people, a list where nobody has a place | Q10 |

## Not doing

- A model rerank step, lanes side by side, a lookup inside every search, LinkedIn.
- The delegation's event pages, mission brochures and chamber event pages as seed lists.
- A label or divider for the first group, and the words "Best matches".
- Host cities of old fellowships as places.
- Two places for one question. A question that names a Belgian and a US city keeps one place.
- Matching an initial against a full first name as one person. Such pairs stay possible matches.
- A batch of agents that labels cards good or bad.
- Retiring `scripts/gold/cut_gate.py`.
- Excel import, a mapping step and the other open items of the first build.

## Risks and how each is held

| Risk | Held by |
| --- | --- |
| A wrong link puts another person's facts on a card | the strict likely rule, the labelled pair file, the gate `pairs_wrong` = 0, "Different person" on the profile |
| The new order puts people without a place first (82% of the first 20 in the replay) | organization cities count as a place (Q2, Q7), the batch fills seed people (Q9), the page ships after both (Q10), and the final check has a pass line for place fill |
| Gold recall rises only because new seed lists name the gold picks | Q6 splits the gold picks and gates on the rest |
| A cut removes a person staff wanted | cut reasons are stored, the debug page shows cut people, `fn-rerank` reverses any rule |
| The pair file is labelled by an agent, not by the owner | labels need two facts that agree, unclear pairs are left out of the gate, and the file is listed for the owner to spot-check |
| The lookup batch spends the owner's OpenAlex allowance | `--limit`, a resumable table, and the batch never runs inside a search |

## Gates for Q7, branch against main in replay mode on the frozen snapshot

- No gold pick that reaches the ranker is cut, and `gold_free_at_10`, `_20` and `_50` do not fall.
- `seed_noise_top20` falls and no first-20 slot is lost to a cut of a person with a seed-list record (`cut_seed_top20` = 0).
- `place_outside`, with the employer's city counted, is at most 0.15.
- The median of people kept is at most 250. The first run measured 228 and 246: OpenAlex people now carry topic claims, so fewer are cut for having no claim.
- `pairs_wrong` is 0.
- The printed first-20 diff is read by the lead for three searches, and what it shows is written into the progress log.

## The final check

Two snapshots. S0 is frozen now, before the data steps. S1 is frozen in Q11 on a copy of the owner's database after migrate, `fn-seed` with the new lists, `fn-orgs --places` and `fn-enrich`. Base is main before this work replayed on S0. Head is main after this work replayed on S1. It passes when all of these hold:

| Metric | Base on S0 | Pass line for head on S1 |
| --- | --- | --- |
| People kept, median | 518 | at most 250 |
| Gold picks in the first 20 that no new seed list names | 3 | at least 3 |
| First-20 people known to be outside the place | 0.40 | at most 0.15 |
| First-20 cards with a topic claim | 0.37 | at least 0.60 |
| First-20 cards with a place | 0.58 | at least 0.58 |
| First-20 cards with a role | 0.03 | at least 0.12 |
| Labelled-different pairs on one card | not measured | 0 |
| Likely pairs in a first 20 | 0 | 0 |

Then two searches with live calls on the owner's server, timed, with screenshots of the first page. The pass line for time is a web lane under 60 s.

### Result of the final check

Head is main at PR 41, replayed on a third snapshot frozen after the last lookups and the place backfill (`var/score/2026-11-12-final`).

| Metric | Base | Pass line | Head | Holds |
| --- | --- | --- | --- | --- |
| People kept, median | 518 | at most 250 | 223 | yes |
| Gold picks in the first 20 that no new seed list names | 3 | at least 3 | 6 | yes |
| First-20 people known to be outside the place | 0.40 | at most 0.15 | 0.10 | yes |
| First-20 cards with a topic claim | 0.37 | at least 0.60 | 1.00 | yes |
| First-20 cards with a place | 0.58 | at least 0.58 | 0.45 | no |
| First-20 cards with a role | 0.03 | at least 0.12 | 0.46 | yes |
| Labelled-different pairs on one card | not measured | 0 | 1 | no |
| Likely pairs in a first 20 | 0 | 0 | 2 | no |
| Web lane, live | 228 s of model calls | under 60 s | 57.6 s | yes |

Gold picks in the first 10, 20 and 50 go from 2, 3, 4 to 10, 13, 14. Seven of the 14 are named by a new seed list. Five picks that stood between rank 38 and 144 now stand between 147 and 473.

The three misses:

- **Place.** The first 20 now hold the people who match the topic, and fewer of them have a place FN can locate. The count on the owner's searches is in [progress.md](progress.md). The largest group is web people whose employer is a name without an organization record.
- **One labelled-different pair on one card.** The rarity rule links it. The profile's Possible matches undoes it.
- **Two pairs of one person in a first 20.** The identity rules keep both apart on purpose: one person has two OpenAlex profiles with different ORCID iDs, and one record has an initial for a first name. Among the labelled pairs with different ORCID iDs and three or more shared organizations, 6 are different people and 11 are the same, so that veto stays.
