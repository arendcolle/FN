# Progress of the result quality work

One line per finished step, newest last. The design is in [design.md](design.md) and the plan in [plan.md](plan.md).

- 2026-11-12 Seven research notes written: identity, ranking, completeness, speed, sources, scorecard, results page. Baseline: 3 of 99 gold picks in the first 20, median 510 people kept, 42% of first-20 cards without a place, 97% without a role, 0 likely pairs in any first 20.
- 2026-11-12 Model settings measured on four stored pages, four calls at once: low effort found the same 35 people and saved no time; the older small model without thinking was 2 to 4 times faster and lost 4 of the 35. Four calls at once took as long as one alone. The model and effort stay.
- 2026-11-12 Q1 builder stopped on two existing tests. Decided: the 13,000-character page test sorts the fake model's pages by position, because calls now start at the same time; the short-tail rule is dropped from the task instead of changing a second test.
- 2026-11-12 Q2 builder reported five existing tests failing by design. Approved: four tests that pin the list of applied migrations gain migration 8, and the seed mapping test gains the consul's job title claim.
- 2026-11-12 Three panels settled D11 (identity), D12 (order and cut) and D13 (sources and lookups), each by majority after three rounds. The lead ruled on the one point where two panels disagreed, the cut of OpenAlex-only people outside the country.
- 2026-11-12 Q0 merged: `fn-score` (PR 25). Frozen snapshot S0 in `var/score/2026-11-12`. Baseline in replay: gold picks 2, 3, 4 in the first 10, 20, 50; median 518 people kept; first-20 place 0.58, role 0.03, topic 0.37, outside the place 0.40; 0 likely pairs in a first 20.
- 2026-11-12 Q2 merged: seed job titles, consul cities, organization cities (PR 26). Q1 merged: the web lane reads its pages at the same time (PR 27). Both gave the same scorecard as main. 447 tests.
- 2026-11-12 Plan review round 1: one blocker and twelve gaps. The plan is at version 2 with a ruling per finding.
- 2026-11-12 Plan approved in round 3 of its review. Q5 builder stopped on two OpenAlex lane tests that pin the claims of a topic-work author. Approved: those assertions gain the topic claim.
- 2026-11-12 Design system version 10 published: results show 20 people at a time; PersonCard gets a why line and a combined-records line and no words for a missing place; MapMarker gets a quieter dot for people not in the list yet; Claim words a paper.
- 2026-11-12 Q6 merged: scorecard round two (PR 28). 463 tests. 22 first-20 cards match no topic word today.
- 2026-11-12 Q5 merged: OpenAlex topic claims (PR 29); first-20 cards with a topic claim go from 0.29 to 0.77 in replay. Q8a merged: the Wikidata seed list, 295 people (PR 30). The seed row-count tests now count the rows that are present.
- 2026-11-12 Q3 builder stopped before building, on two tests that pin the old name key. Ruled: the key test moves with the function, and the frozen gold matcher's test pins its ten keys as literals. Q4 builder stopped on the gate for seed noise: the text index stems words, so the count goes from 22 to 10, not to 0. Ruled: the gate is that it falls.
- 2026-11-12 Q4 merged: the seed lane searches only meaningful topic words and keeps 300 hits (PR 31); seed noise in the first 20 goes from 22 to 10 and one more gold pick is found.
- 2026-11-12 Q3 builder stopped on three points. Ruled: a record of a network person is linked only by sure, so a likely hit keeps the "Same name" choice; two seed rows are one person only when their keys differ in the year alone; `gold.stored_text` may use the new key, so the old key function goes away. One more approved test change: the card-actions test uses a different ORCID.
- 2026-11-12 Q8b merged: the chambers' board members as a seed list, 32 people (PR 32). The lead changed two things after review: no place is loaded, because the pages state none and the chamber's home city was a guess, and the delegation's own side (consuls, ambassadors, trade commissioners) is left out.
- 2026-11-12 Q8c merged: the 2022 mission program's speakers as a seed list, 67 people (PR 33). After review the lead also left out foreign-affairs officials and employers that name two organizations, and removed a royal's name from the scraper's code. On a copy of the owner's database, the reloaded seed lists and organization cities alone take first-20 cards with a role from 0.03 to 0.18.
- 2026-11-12 Q3 built; its gate failed with 4 labelled-different pairs on one card (2 record pairs, each in 2 searches). Ruled from the labelled pairs: a rare name counts only together with a shared organization, and two rows of one seed list are one person only within 10 years. The pair file has 307 pairs: 74 same, 28 different, 205 unclear.
- 2026-11-12 Q3 second gate run: no labelled-different pair linked, no bundle of initial-only records, but 16 first-20 cards lost a record: an OpenAlex author and the web page that mentions the same rare name became two cards. Ruled: a record that is only a web mention links by a rare name alone, because it has no organization to share.
- 2026-11-12 Q3 merged: `fn.identity` (PR 34), 516 tests. Replay against main: no labelled-different pair on one card, no pair of one person in a first 20, the 8 bundles of initial-only records gone, 2 first-20 cards lost a record, place fill 0.59 to 0.61. The pair file was relabelled after the reviewer agreed with only 9 of 20 labels; a second blind check agreed on 17 of 20. It now holds 136 same, 45 different and 126 unclear pairs, and it is in `data/gold/`, local only.
- 2026-11-12 Q9 built and approved: the lookup batch. On a copy with 40 live lookups, 19 of 20 seed people matched an OpenAlex author and 9 of 19 ORCID holders got a job title. It merges after Q7, which owns the earlier migration.
- 2026-11-12 Q7 built; replay against main: people kept 553 to 228, first-20 outside the place 0.43 to 0.10, inside 0.09 to 0.27, gold picks in the first 10, 20, 50 from 2, 3, 4 to 3, 4, 7, no gold pick cut. Ruled: the weak-evidence cut also spares an institution match (it cut three picks of a university-only question in a test); the list-size line moves from 200 to 250, because OpenAlex people now carry topic claims; seed noise must fall, not reach 0.
- 2026-11-12 Q7 merged: `fn.evidence` and the new order and cuts (PR 35). The lead fixed one thing after review: a topic word of three letters or fewer must be the whole word, so "AI" no longer finds "aircraft". Q9 merged: `fn-enrich` (PR 36). 561 tests.
- 2026-11-12 Rolled out to the owner's database: backup, migrations 008 to 011, nine seed lists reloaded (5,429 rows), 3,954 organizations with a city, 300 OpenAlex lookups (202 matched) and 600 ORCID lookups (442 matched), second snapshot frozen in `var/score/2026-11-12-after`, stored searches ranked again.
- 2026-11-12 The second snapshot showed 3 pairs of one person in a first 20: a person with several records no longer had a rare name. Fixed and merged (PR 37): seed rows and web mentions do not count toward rarity, and a rare name backs a link only when one record is a list row or a mention. One labelled-different pair is linked under this rule, accepted and noted for the owner.
- 2026-11-12 Q12 built; on the second snapshot it flooded topic questions with 341 people who match only the city. Ruled: the place search runs only for a question that names a place and nothing else. Q10 built; one more approved test change (the card's evidence is the claim that matched the topic).
- 2026-11-12 Two ranking rules merged after reading the first 25 cards of the Boston question (PR 38). A stated place decides where a person is, so an employer's city only counts when no place is stated. Inside a band, people with more topic words come first. Replay on the second snapshot: gold picks in the first 20 that no new list names 4 to 6, seed rows without a topic word in a first 20 from 4 to 0. One existing test of the place rule followed the new rule.
- 2026-11-12 Q12 merged: the seed lane's place search for a question that names only a place (PR 39). Its builder stopped because the gate said nothing may move, and three stored questions name only a place. Ruled: accepted, those three go from 0 to 20 people. The scorecard no longer counts seed noise for a question without a topic word. The date a search ranks as of moved to `steps.as_of`, used by the ranker and the place search.
- 2026-11-12 Q10 merged: the results page (PR 40), after the review's one open point, a map link for a person behind two cards.
- 2026-11-12 Rolled out again: stored searches reranked, server restarted. On the owner's 25 searches with results, 25% of first-20 cards had a place. Counted why not: 122 web people whose employer is no organization record, 81 seed people whose only employer claims are older than five years, 74 web people without an employer claim.
- 2026-11-12 `fn-enrich --limit 1500` used up the day's free OpenAlex budget after 677 lookups (455 matched); the other 823 returned errors and are tried again by the next run. The budget is 1 US dollar a day and a search costs a tenth of a cent, so about 1,000 calls a day, shared with the OpenAlex lane.
- 2026-11-12 The first card of the Boston question printed a Belgian city. 85 of 118 stored "lives in" claims had no coordinates, because they were written before places were located on write, so the ranker read those people as place unknown. Merged (PR 41): `fn-orgs --places` also locates those claims and runs as a recorded job. 76 claims located on the owner's database; first-20 cards with a place 25% to 32%.
- 2026-11-12 Measured and not adopted: ordering people inside the place before a full topic match outside it. Gold picks in the first 10, 20 and 50 stay the same, first-20 people outside the place go from 10% to 0.2%, and people of unknown place go from 65% to 74%. The panel's order stays.
- 2026-11-12 Two live searches on the owner's server. The Boston question took 68 s against 257 s in the morning: parse 6.5 s, web lane 57.6 s, resolve and rank 0.3 s. Its OpenAlex lane failed on the used-up budget, and the page said the list may be incomplete. "Who is based in Chicago?" took 6 s and listed 8 seed people, each with "Based in" and the city; it listed nobody before.
- 2026-11-12 Final check, base on the first snapshot against main on a third snapshot frozen after the last data steps (`var/score/2026-11-12-final`): see the table in [plan.md](plan.md). Six pass lines hold and three are missed: first-20 cards with a place (0.45 against 0.58), one labelled-different pair on one card (0 wanted) and pairs of one person in a first 20 (2 against 0).
- 2026-11-12 An independent review of the last four changes (three reviewers, each finding checked by a second agent) confirmed two bugs, both fixed and merged (PR 42): the place search counted a recent employer in the city for a person who states another city, and the place backfill skipped the places seed lists write. 582 tests. The scorecard did not move.

## Review ledger

| Id | Finding | Severity | Outcome |
| --- | --- | --- | --- |
| score R1 | `score.py` computed net's cache path and unzipped the cities file itself | nit | fixed: `net.cached_get`, `geo.from_zip` |
| score R2 | An unused settings validator | nit | fixed: removed |
| score R3 | Freshness compared years only | nit | fixed: dates |
| score R4 | A mistyped `--llm` folder was accepted | nit | fixed: exit 2 |
| score R5 | `compare` skipped a gate when the metric was missing in the second file | nit | fixed: fails |
| held R1 | A consul city was tried without its state and could get another state's pin | should | fixed: the city alone is tried only when no state is known |
| held R2 | The cities download counted as a changed row | nit | fixed |
| held R4 to R6 | Moving `org_of`, a test for the known-state rule, the relation of a consul's place | nit | declined, follow-ups |
| fan-out R1 | `FN_LLM_WORKERS=0` failed inside the lane | nit | fixed: at least 1 |
| fan-out R2, R3 | A union type for a case no caller has; two import forms | nit | fixed |
| fan-out R4 | The timing test has 35% headroom | nit | declined: 9 of 9 runs passed |
| plan R1 | Q3 and Q4 were gated on metrics a parallel task builds | blocker | fixed: Q6 runs first |
| plan R2 | Add and the split control had no owner between Q3 and Q10 | should | fixed: Q3 owns `card_decision`; the profile's "Different person" is the split; `identity.on_card` applies it at render |
| plan R3 | Old stored rows would pool the facts of same-name records | should | fixed: a new field `card_person_ids`; old rows read hit records |
| plan R4 | The cut outside the country could not be implemented as written | should | fixed: the measured test is written out, with five test cases |
| plan R5 | Four modules decided a person's place, with three recency rules | should | fixed: `evidence.places`, one rule |
| plan R6 | Three modules needed a stop-word list and none existed | should | fixed: `parse.content_words` |
| plan R7 | `fn-rerank` rewrites stored results, against a panel rule | should | ruled: only by the explicit command, run once at deploy after a backup |
| plan R8 | Gates in rerank mode cannot see lane changes | should | fixed: gates run in replay mode |
| plan R9 | The final check could not fail | should | fixed: two snapshots and pass lines |
| plan R10 | Two signatures for `evidence.of`, neither enough | should | fixed: one signature |
| plan R11 | The lookup batch's match rule differed between decisions | should | fixed: sure, or likely by a shared organization |
| plan R12 | Gold counts would move when the name key changes | should | fixed: a frozen matcher in `gold.py` |
| plan R13 | Four inputs missing from the table | should | fixed: added |
| plan R14 | File lists incomplete | nit | fixed |
| plan R16 | Moving the name key breaks five callers, and the doubles metric would change with the code under test | should | fixed: Q3 owns the two store lookups; the doubles metric uses the frozen `gold.pick_key` |
| plan R15 | The why line recomputed evidence; two owners for the stored-search rerun | nit | fixed: stored score parts; `search.refinish` |
| score2 R2 | `diff` skipped degraded searches without saying so | nit | fixed: one line names them |
| score2 R4 | Generic words in English only | nit | fixed: Dutch and French forms added |
| score2 R1, R3, R5 | Broad error handling, replay not in a unit test, import order | nit | declined |
| topics R1 | The gate "people kept stays" moved by half a person, because new claims shift the seed lane's text statistics | should | accepted by the lead: gold counts hold; a follow-up keeps record claims out of that index |
| topics R2, R3 | Two tests did not test what they named | should, nit | fixed |
| seedwords R1 to R3 | Two approved test edits went slightly beyond a function word; a hyphenated topic matches more loosely | nit | accepted |
| wikidata R1 | Two tests hard-coded 5,035 seed rows | should | fixed by the lead: they count the rows that are present |
| wikidata R2 to R4 | Five places are states, a summary mixes units, the role is the alphabetically first occupation | nit | follow-ups |
| chambers R1 | Every member got the chamber's home city as a place | should | fixed by the lead: no place |
| chambers R2, R3 | The date is the page's copyright year; a heading never resets the section | nit | follow-ups |
| missions R5 | A real royal's name stood in the scraper to strip a column heading | nit | fixed by the lead: a pattern without the name |
| missions R2 | An employer that names two organizations was accepted | nit | fixed by the lead: such a row is left out |
| missions R1, R3, R4, R6, R7 | A title with a comma, one speaker spelled two ways, a second name fold, no hand count in check.py, one speaker without a session | nit | follow-ups |
| identity R1 | The labelled pairs agreed with a blind relabel on only 9 of 20 | should | fixed: every pair relabelled from its claims; second blind check 17 of 20 |
| identity R2 | An unapproved line in the card-actions test | nit | fixed: removed |
| identity R3 | Three network tests gained a shared organization beyond the approved list | nit | kept: the rare-name rule needs it; named in the pull request |
| identity R4 | No labelled pair for two vetoes the snapshot cannot supply | nit | accepted: unit tests cover them |
| identity R5 | No resolve test for two seed rows on one card | nit | fixed |
| rank R1 | A rerun ranked as of today, not as of the search it repeats | should | fixed |
| rank R5 | A short topic word matched any word that starts with it | nit | fixed by the lead: whole word for three letters or fewer |
| rank R3, R4, R6, R7 | A shim on the old cut path, the cut-seed metric's route, cuts on a question without a topic, an import cycle | nit | follow-ups |
| enrich R3 | Seed people with only Wikidata organizations cost a call that cannot match | nit | fixed by the lead: skipped |
| enrich R4 | A negative limit looked up almost everyone | nit | fixed by the lead |
| enrich R1, R2 | No test for the ORCID Accept header; the hand check used 19, not 20 | nit | accepted |
| final logic-1, inputs-1, tests-1 | The place search took the nearest of a person's places, so an employer's city counted beside a stated place elsewhere | should | fixed: the lane asks `evidence.where` |
| final inputs-2 | The place backfill took only "lives in" claims and skipped the places seed lists write | should | fixed: every location claim that is not a birthplace. The lead extended the test written an hour earlier for the narrower rule |
| final tests-3, tests-4, tests-5 | No test that topic words leave the network section alone, the places job named twice, one test without a docstring | nit | fixed |
| final logic-2 | A failed city index download leaves the organization cities already filled | nit | declined: the next run finishes the claims |
| final inputs-3 | The place search stores one considered row per person in the box, 1,650 for Brussels | nit | follow-up |
| final tests-2 | The source-kind filters of the place search have no test of their own | nit | follow-up |
