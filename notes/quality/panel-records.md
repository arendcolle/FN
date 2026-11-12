# Panel records for the result quality decisions

2026-11-12. Three panels of three reviewers (a staff user, the maintaining engineer, a pragmatist) took up to three rounds each, with a moderator. No panel reached full agreement, so each record is the majority decision with the dissent. The lead's rulings on the points where panels disagree are in [design.md](design.md).

## D11: Who is one person, and what a card may show before staff confirm it

Three rounds, majority decision.

### Decision

Scope: build a single identity owner now, src/fn/identity.py with same_person(a, b) -> (level, reason). Resolve (resolve.py), network.add, network.name_matches, the importer's identity step (importer.py:196) and the D13 enrich link all call it. Cut the contract version bump, the backfill, a possible_ids column in the store, and Likely B (cross-form matches) for now. All three reviewers agree on this.

Levels. Sure: a staff merge (merged_into). A shared identifier already folds at write time through UNIQUE(scheme, value) (migrations/001_init.sql:80, store.resolve_person at store.py:316). Likely: the same group_key after the four name-comparison gaps are fixed, both first names at least 2 letters, no veto, and one of three backers. (1) A shared org held by fewer than 300 records. (2) The same seed list and slug. (3) A group_key held by at most 3 records, with the 1,471 mention-only web records left out of that count. Two reviewers (engineer, skeptic) reject a fourth route, "two or more shared orgs of any size". Possible: every other name match, including cross-form matches (initial plus surname) and initial-only names. Initial-only records never reach likely, and records of that kind are never bundled into one card.

Vetoes, owned only by identity.py: not_same pairs (honoured today at resolve.py:41), conflicting middle initials, incompatible first names, different ORCIDs, different profile_urls. ORCID and profile_url are hard vetoes, and only a staff merge overrides them. Delete STRONG at network.py:20. seed and openalex stop vetoing: OpenAlex splits one author across ids (20,310 openalex identifiers on 20,260 persons), and seed values are per-row slugs.

Card before confirmation: sure and likely records pool their facts on one card. Each fact names its source record. The card shows "combined from N records" with the link reason. Each extra record has a "Not the same person" control that writes not_same. A possible record shows as one line and contributes no facts.

Add: card_decision (web/staff.py:390-392) passes every person_id on the card. Add calls same_person again and merges sure and likely records only, so two rows of one seed list can merge. Undo restores every row. The MR must name two spec changes: tests/test_network.py:99 (a different openalex id no longer keeps two hits apart) and the flag text of tests/test_resolve.py:30.

Proof. tests/test_identity.py uses invented names, one case each: every likely backer; a rare name sharing only a big org links; a common name sharing only a big org is possible; a seed record with no org plus a common name is possible; each veto, profile_url included; an initial-only name stays possible; two seed rows merge on Add. data/gold/identity-pairs.jsonl holds ids and labels only: every panel sample, the researcher's 30 pairs, the 49 ORCID pairs, the common-name pairs and the split cards.

Scorecard gates, run on a frozen snapshot and again after every import:
- 0 labelled-different pairs at sure or likely (all three agree).
- Precision per likely backer is reported, with its pair count and its count of unclear pairs.
- First-20 cards that lose a hit against main: at most 2 (user and skeptic; 1 measured today).
- First-20 doubles that share a group_key: 0.
- Initial-only bundles: 0.
- Share of cards with a place: reported, not gated.

Measured (reviewers' scripts, 25 searches): this rule splits 1 first-20 card and 4 first-50 cards against today. Counting web mention records gives 2 and 10.

### Rules

- One owner: src/fn/identity.py same_person(a, b) -> (level, reason); resolve, network.add, network.name_matches, importer.py:196 and the enrich link all call it.
- Sure = staff merge (merged_into); shared identifiers already fold through UNIQUE(scheme, value).
- Likely = same group_key after the name-gap fixes, both first names >= 2 letters, no veto, and one of: shared org with < 300 records, same seed list and slug, or group_key held by <= 3 records counting no mention-only web records.
- No 'any shared org', no 'one side has no org', no 'two or more shared orgs' route.
- Possible = every other name match, cross-form and initial-only included; Likely B is not built now.
- Vetoes: not_same, conflicting middle initials, incompatible first names, different ORCID, different profile_url; only a staff merge overrides ORCID and profile_url.
- Delete STRONG at network.py:20; seed and openalex stop vetoing.
- Sure and likely records pool facts on the card; every fact names its source record; the card shows 'combined from N records' with the reason; each extra record has a 'Not the same person' control writing not_same.
- Possible records show one line and contribute no facts; initial-only records are never bundled.
- Add passes all card person_ids, re-asks same_person, merges sure and likely only (two seed rows may merge); undo restores every row.
- MR names spec changes to tests/test_network.py:99 and the flag text in tests/test_resolve.py:30.
- tests/test_identity.py: one invented-name case per backer, per veto, common name plus big org is possible, no-org seed plus common name is possible, initial-only stays possible, two seed rows merge on Add.
- data/gold/identity-pairs.jsonl holds ids and labels only.
- Scorecard gates: 0 labelled-different pairs at sure or likely; first-20 splits vs main <= 2; first-20 same-group_key doubles = 0; initial-only bundles = 0; precision per backer and place share reported; rerun after every import.

### Dissent

The user reviewer wants a fourth likely route, two or more shared orgs of any size. On today's first 50s it adds one pair (47b74e7f/ed2ad237), which reads as one human. The user reviewer also wants Likely B written now, returning possible until at least 20 labelled B pairs reach a precision of 0.9 or more, and a precision gate of at least 0.9 per backer with at least 20 pairs each. The engineer wants a precision gate of at least 0.95 overall and a cap of 1 on first-20 splits against a frozen snapshot, since today's value is 1 and any rise is a regression. The skeptic and the user reviewer chose a cap of 2 to leave room for rarity drift. The majority keeps precision as a reported figure: with 30 to 40 pairs per backer, one wrong pair moves it by about 3 points.

### Evidence

- person_identifiers by scheme (read-only query on var/fn.sqlite3): mention 1471, openalex 20310 rows on 20260 persons, orcid 15961, profile_url 25, seed 5035
- src/fn/network.py:20 STRONG = ("seed", "openalex", "orcid", "profile_url")
- src/fn/resolve.py:41 apart() honours not_same pairs and different held ORCIDs
- src/fn/migrations/001_init.sql:80 UNIQUE (scheme, value) on person_identifiers; store.resolve_person at store.py:316
- tests/test_network.py:99 test_a_hit_with_another_openalex_id_stays_apart encodes the openalex veto that this decision removes
- tests/test_resolve.py:30 test_two_seed_rows_with_one_name_stay_two_persons_in_one_flagged_entry
- src/fn/web/staff.py:390-392 card_decision uses candidate.hit_person_ids or the first person_id
- src/fn/importer.py:196 computes group_key(name_key(name)) for import identity
- Reviewers' replay (panel/D11-user3, D11-engineer-r3, D11-pragmatist/r3.py): the adopted rule splits 1 first-20 and 4 first-50 cards against today; counting web mention records gives 2 and 10
- Of the 4 first-50 splits, c57afebd/ab64a0de holds two different ORCIDs (a correct split) and 4dad09db is three seed rows linked only by a common name

## D12: How the ranker orders and cuts

Three rounds, majority decision.

### Decision

Majority decision for D12 (engineer and skeptic; the user agrees on everything except the extra cut and the divider).

Evidence owns each fact. The ranker reads it and never repeats a lane test.
1. Topic match: every content word of at least one chip appears in a claim, cited by its id, on a sure or likely record. A half-chip match and uncited OpenAlex work titles do not count.
2. Tie: evidence.tie, or an institution chip match.
3. Two groups, sorted before score: group 0 has a topic match and a tie, group 1 has everything else. Inside a group, today's score parts decide the order. No third group.
4. Place: a stated place, or the employer's city when that employer fact is from 2021 or later. A known place outside the area asked for goes last within its group. A known place outside the country with no institution match goes after both groups. Nobody is cut or demoted for a missing place.
5. "OpenAlex-only" means every record on the entry comes from OpenAlex. Evidence decides this from the records, not from which lane found the person. A person with a seed-list record is never OpenAlex-only, and neither is a web-only person. rank.py:101-106 cut_reason must read Evidence instead of `set(entry.lane_ranks) == {"openalex"}`.
6. Cuts, three in all: no_belgian_evidence (today), weak_openalex (today), and the no-claim cut. The no-claim cut removes OpenAlex-only people who have no topic claim, no institution match and no place inside the area. There is no separate rule for "outside the country with no claim", because the no-claim cut already covers every person it would remove. The keep_c2 cut (abroad without an institution match, even with a topic claim) does not ship. Each cut names its basis so the dismissed list can be audited. New cuts are not written back into stored results.
7. Page: RESULTS_STEP (present.py:45) goes from 50 to 20, with "show more". Cards stay under the existing "New" heading (staff.py:76). There is no group label, no divider and no "Best matches". The why line reads "Matches {words} · {tie} · {place (basis, year)}", built from the stored score_parts claim ids.

Expected numbers on the 25-search replay, with seed-list people exempt: 13 of 13 reached gold picks kept, 5/6/10 in the first 10/20/50, median gold position 23, median kept 238 (510 today), minimum kept 31. First 20: 77% topic claim, 14% OpenAlex-only, 9% inside, 1% outside, 82% no place shown, 90% with a stated reason.

Merge gates, run against main on a frozen snapshot:
- No reached gold pick is cut, and the counts at 10, 20 and 50 do not fall.
- The first 20 holds 0 weak-OpenAlex and 0 seed-noise slots.
- No first-20 slot is lost to a cut of a person with a seed-list record.
- Outside share stays at or below 15%, counting the employer city.
- Every group-0 card cites a claim id from a sure or likely record.
- Median kept does not rise.
- The replay recomputes evidence on sure and likely records only, and tests/test_rank.py:147-157 stays green.
- Unit tests check that groups are monotone, that outside comes after inside, and that the no-claim cut matches its definition.
- First-20 place fill after enrich (D13) does not fall.
- A printed per-search first-20 diff, read by a person, names the part that moved each card.
- Add and Skip are logged with rank into `events`. This becomes the evidence for later ranking changes and for revisiting the keep_c2 cut and the group label.

Risks: 8 of the 13 reached picks come from two searches, so the count in the first 10 is a judgement call. 82% of first-20 cards show no place until enrich runs, so this ships behind D13's place-fill gate.

### Rules

- Topic match = every content word of one chip in a cited claim on a sure or likely record.
- Tie = evidence.tie or an institution chip match.
- Two groups (topic match and tie; the rest) sort before score; score parts order within a group.
- Place = stated place, or the employer city when the employer fact is from 2021 or later.
- Known place outside the area goes last within its group; outside the country with no institution match goes after both groups.
- Nobody is cut or demoted for a missing place.
- OpenAlex-only = all records on the entry are from OpenAlex, decided by Evidence; seed-list and web-only people are never OpenAlex-only.
- rank.py cut_reason reads Evidence, not lane_ranks.
- Cuts: no_belgian_evidence, weak_openalex, and the no-claim cut (OpenAlex-only, no topic claim, no institution match, no place inside the area). No separate b3 rule. No keep_c2 cut.
- Each cut names its basis. New cuts are not written back into stored results.
- RESULTS_STEP 50 -> 20 with show more, under the existing New heading; no group label, divider or 'Best matches'.
- Why line: 'Matches {words} · {tie} · {place (basis, year)}' from stored score_parts claim ids.
- Merge gates: no reached pick cut, @10/20/50 not lower, 0 weak-OpenAlex and seed-noise first-20 slots, no seed-list person cut from a first-20 slot, outside <= 15%, cited group-0 claims, median kept not higher, sure-or-likely rerun with test_rank.py green, unit tests for groups, outside order and the no-claim cut, place fill not lower after enrich, a person-read per-search first-20 diff, Add/Skip logged with rank in events.

### Dissent

The user votes to also ship keep_c2. That cut removes OpenAlex-only people placed outside the country with no institution match, even when they have a topic claim. The user's argument is that the owner said "way too many people" and "as little noise as possible", and that an OpenAlex-only researcher in Leuven or Vienna is not a US contact. The cut takes the median kept from 231 to 151 (156 with seed-list people exempt) and costs no gold pick and no first-20 slot. It removes 981 people, 20 of whom sat in a first 50 at positions 22 to 27, which are the first cards "show more" would show. The majority rejects it for three reasons: it is a cut by place, which the panel agreed not to make; ordering already puts these people after both groups; and it changes nothing in the first 20. The majority would revisit it once Add/Skip data exists. The user also wants one divider at the end of group 0 ("Below: no topic match or no Belgian tie found"). The majority leaves it out because the why line already states the topic and the tie, and because the divider would fall at a different place in each search and need pagination handling. The seed-list exemption was measured only by the skeptic. The user and the engineer did not address it, but it corrects the definition of OpenAlex-only rather than adding a rule.

### Evidence

- Replay scratch/panel/D12-pragmatist-r3/r3.py, rerun by the moderator. G4 (b3 plus no-claim cut): 13 picks kept, 5/6/10 in the first 10/20/50, median position 23, median kept 231, minimum 27. First 20: topic claim 78%, OpenAlex-only 14%, inside 9%, outside 1%, no place 82%, stated reason 90%.
- Same run, G3 (keep_c2): identical gold and first-20 figures, median kept 151, minimum 21.
- Same run, 'b no-claim only' gives median kept 231, the same as G4, so the separate b3 rule adds nothing.
- r3b.py, rerun: the no-claim cut moves 11 first-20 slots across 25 searches. 4 of them are seed-list people (7bcdcf1b in two searches, 4133254e, b38115e0) with seed True.
- r3e.py, rerun, seed-list people exempt: (a') median kept 156, minimum 25; (b') median kept 238, minimum 31; (c') median kept 254, minimum 34. All three keep 13 picks at 5/6/10, with first 20 at 77% topic claim, 1% outside and 82% no place.
- evaluate.py:52 in the ranking scratch folder defines oa_only as f['lanes'] == ['openalex'], a test of the finding lane.
- src/fn/rank.py:101-106: cut_reason uses set(entry.lane_ranks) == {'openalex'} and the absence of a belgian_years part.
- src/fn/present.py:45: RESULTS_STEP = 50.
- src/fn/web/staff.py:76: SECTIONS = {'network': 'In your network', 'new': 'New'}.
- src/fn/store.py:553: ORDER BY section = 'new', cut_reason IS NOT NULL, rank, so the stored rank decides the order.
- tests/test_rank.py:147-157: a record joined only by name adds no belgian_years part.

## D13: Which sources to add, what OpenAlex should do, and how missing facts are looked up

Three rounds, majority decision.

### Decision

D13, majority decision (engineer and skeptic on every point; the user reviewer agrees on everything except the place-search gate).

1. Seed lists this round, in order. First, Wikidata people with a Belgian tie and a US employer or residence: about 949 people, 3 to 4 h. It helps topic and place questions with complete, current US records. Second, Belgian-American chamber board and leadership pages: 4 to 7 h. They help place questions in chamber metros. Third, the 2022 mission program, read from the pinned Wayback copy: 8 to 12 h, without the delegation's or the trade office's own moderators. It helps sector questions. Delegation event pages, mission brochures and chamber highlight pages wait for a later round.

2. Belgium-based delegates from mission brochures are left out of this round.

3. The origin URL answers 403, so the scraper fetches the Wayback `id_` URL. That URL goes in `source_url` and the origin URL in `source_title`. Docling reads the PDF, as the existing scraper scripts/seeds/kvab.py:3 already declares it as an inline script dependency. pdftotext is used for cross-checks only. The app gets no new dependency.

4. Place search in the seed lane runs only when `geo.area(place)` returns an area. geo.py:185 already limits it to kinds in `METRO_KINDS = (None, "metro")` (geo.py:22). It matches current location claims within `METRO_RADIUS_KM` (100 km, geo.py:20). Those claims are lives_in, the consul's place, a board member's city, or an employer dated within 5 years. Hits are capped at 20 and rank below topic hits. Each card says "listed because based in <city>". The 5 `anywhere_us` chips get no place query: US twice, US-based, US West Coast and North Carolina. Seedload must keep `place` and `jurisdiction`. State-level place search waits.

5. OpenAlex stays a lane, unchanged inside the lane. After resolve, rank.py drops a person whose records all come from OpenAlex unless their known location is in the question's country, or in the US when the question names no place. An unknown location is cut. Replayed on the 25 stored searches, kept people fall from 13,868 to 3,534 and one gold pick is lost (GS-29, an OpenAlex-only person placed in Belgium, at rank 126).

6. Enrich runs once, offline, as a resumable batch over the seed rows, not per search. It makes one OpenAlex author lookup by name per row and a free ORCID employments lookup when an ORCID is known. A Wikidata row uses its QID as `row_key` and its item URL as `profile_url`. The batch reads P496 from the item. Enrich records resolve by their own key (the OpenAlex author id or the ORCID). Only `identity.link` decides whether an enrich record is the seed person, and it requires the same name group key, a shared ROR id and no veto. No identifier is copied onto the seed person. The seed row contract (REQUIRED, common.py:15-21) is unchanged. A Wikidata URL is stored as a claim and never as a `profile_url` identifier, because importer.py:41 and exporter.py:59 treat that scheme as LinkedIn. One test asserts this.

7. The scorecard computes "by construction" itself, without a hand-filled field. A pick counts as by construction when the site of its seed row's `source_url` matches the site of the case `source` or of any URL in the pick's `sources`. The comparison unwraps Wayback URLs and drops www. score.py prints total recall, recall without the by-construction picks, and the excluded pick ids, and it gates on the second number. Card fill (place, dated role, employer) for the first 20 is printed beside it. One fixture test covers a Wayback URL and a www URL.

Cut this round: a built_from field, a seed identifiers field, a filter inside the OpenAlex lane, per-search enrich, a no-OpenAlex mode, and place search on anywhere_us chips.

### Rules

- Build order: Wikidata (about 949 people, 3-4 h), then chamber board and leadership pages (4-7 h), then the 2022 mission program from the Wayback copy (8-12 h, no delegation or trade-office moderators).
- Event pages, mission brochures, chamber highlight pages and Belgium-based brochure delegates are out this round.
- The Wayback id_ URL goes in source_url and the origin URL in source_title. Docling reads the PDF as kvab.py:3 declares it, and pdftotext is used only for cross-checks. The app gets no new dependency.
- The seed lane runs a place query only when geo.area(place) returns an area (kind in METRO_KINDS and a city located). It matches current location claims within 100 km, caps hits at 20 and ranks them below topic hits, and each card shows 'listed because based in <city>'.
- Seedload keeps place and jurisdiction on consul rows.
- rank.py drops OpenAlex-only people whose known location is outside the question's country (the US when no place is asked). An unknown location is dropped. The OpenAlex lane itself is unchanged.
- Enrich is one resumable offline batch over the seed rows, with OpenAlex author by name and ORCID employments for a known ORCID. There is no per-search enrich.
- identity.link alone accepts a match: same name group key, a shared ROR id and no veto. Enrich records keep their own identifiers, and none is copied onto the seed person.
- The Wikidata row_key is the QID and its profile_url is the item URL. The URL is stored as a claim, never as a profile_url identifier, and a test asserts this.
- score.py flags a pick as by construction when its seed source_url site (Wayback unwrapped, www dropped) matches the site of the case source or of any pick source. It gates on recall without the flagged picks, prints the flagged ids and reports top-20 card fill.

### Dissent

The user reviewer would run place search only when place.kind == "metro". Under the majority's geo.area rule, the "Georgia" chip (kind null) also qualifies when locate finds a city for it. The user reviewer sees that as a flood risk and wants the chip parser fixed instead. The difference covers one of the 25 stored searches. It matters only if locate resolves "Georgia" to a city, which no reviewer and not the moderator has run.

### Evidence

- Stored searches with candidates: 25. Place kinds: metro 19, anywhere_us 5 (US twice, US-based, US West Coast, North Carolina), null 1 (Georgia). Source: query on searches.chips_json in var/fn.sqlite3, read-only.
- geo.py:20 METRO_RADIUS_KM = 100.0; geo.py:22 METRO_KINDS = (None, "metro"); geo.py:180-187: area() returns None unless place.kind is in METRO_KINDS, then calls locate(place.text).
- seedload.py:95 resolves each seed row by Identifier(scheme="seed", value=row_key) only.
- store.py:316-345 resolve_person attaches every passed identifier to the first person that holds any of them.
- importer.py:41 labels profile_url as 'LinkedIn URL'; exporter.py:59 exports it as linkedin_url.
- scripts/seeds/kvab.py:3 declares the inline dependencies ["httpx", "docling"].
- The moderator reran panel/D13-engineer/oa_rule.py. Kept people across the 25 searches fell from 13,868 to 3,534 under the country rule. GS-29, an OpenAlex-only person placed in Belgium at rank 126, is the only gold pick lost.
- The current seed files data/seeds/*.jsonl hold 5,035 lines in all. The enrich cost estimate of about $2.26 was not recounted against this.
