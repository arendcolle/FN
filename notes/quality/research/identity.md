# Identity: one card per human

Research note. No product code changed. Measured on a read-only snapshot of `var/fn.sqlite3` taken 2026-11-12 (26,791 person records, 293,612 live claims, 25 finished searches with candidates, 13,868 shown candidates). Scratch scripts: `$SCRATCH/quality/identity/{load,match,q2,q3,q3b,q4}.py`.

## TL;DR

Doubles are rarer than they feel: across 25 searches, looser name matchers find 0 likely-double pairs in any top 20 and 2 in all top 50s (90 overall, 47 with a shared organization). The few seed-vs-OpenAlex doubles come from four gaps in `group_key`: it keeps full middle names, keeps a first-name initial, treats a stray trailing letter as the surname, and cannot read "Surname-initial First" order. The bigger problem is that a card shows only the facts of the records a lane hit, and seed records hold no place at all: 79 of 79 seed-only cards in the top 20s have no place. Better linking fixes only 11 of the 212 top-20 cards with no place, because for 232 of 269 seed-only top-50 cards no OpenAlex record of that person exists in the store. So identity needs three things: one module that owns "who is one person" with evidence levels, cards that show facts from every linked record, and an enrichment lookup that fetches the missing OpenAlex record for seed people. Two rules are wrong today. Add refuses to merge two seed rows of one human because the seed identifier is per row. And the ORCID veto in resolve splits real people: in 18 of 49 same-name pairs with different ORCIDs, I judged both records to be one human.

## Findings

### 1. How a card is built today

| Step | What it decides | Evidence |
|---|---|---|
| Lanes | Each lane hit is a record found through `store.resolve_person` by identifier. Seed rows use `seed:<row_key>`, and the row key includes the year, so one fellow listed in two years is two records. OpenAlex uses the author id plus the ORCID. The web lane uses `mention:<url>#<name>`, one record per page mention. | `seedload.py:95`, `lanes/openalex.py:242-243`, `store.py:316-345`, identifier counts in `person_identifiers` |
| `resolve.group` | Hits share an entry when their `group_key` is equal. `group_key` folds case, accents and hyphens (`contracts.py:68-71`) and drops only one-letter middle tokens (`contracts.py:74-77`). Two records stay apart only for a `not_same` row or for ORCID sets with no overlap (`resolve.py:41-42`). Stored records with the same key that no lane hit join `person_ids` but not `hit_person_ids` (`resolve.py:63-69`). | `resolve.py:27-79` |
| `rank.fuse` | Lane parts come from `lane_ranks`. `belgian_years` counts claims of `hit_person_ids` only (`rank.py:72`, claims fetched for hits only at `rank.py:135`). `candidate.person_id` is the first record. | `rank.py:62-127` |
| `store.save_candidates` | Stores both id lists. | `store.py:519-530` |
| `present` | Name, role, employer, place, map point, Belgian orgs, evidence and contact all come from `hits_of(candidate)` (`present.py:220-222`, used at `present.py:271` and `present.py:280`). The non-hit same-name records in `person_ids` feed nothing on the card. The map uses the same views (`present.py:296`, `geo`). | `present.py:199-300` |
| Add (`network.add`) | Merges later hits into the first unless a STRONG scheme (`seed`, `openalex`, `orcid`, `profile_url`) holds different values on both sides (`network.py:20`, `network.py:65-66`, `network.py:91-93`). | `web/staff.py:392-405` passes hits only |

Consequences:

- Two seed rows of one human always conflict on the `seed` scheme, so Add leaves them apart. I ran `network.add` on a scratch copy for a card with two seed hits: 0 merged, 1 left apart. 27 of the 1,250 top-50 cards hold two or more seed hits. Two OpenAlex ids of one human conflict the same way (8 top-50 cards hold two or more OpenAlex hits).
- Resolve and Add use different veto rules: resolve vetoes on ORCID only, Add on four schemes. "Who is one person" lives in five places: `contracts.group_key`, `resolve.group`, `network.add`/`_conflicts`, `network.name_matches`/`possible_matches`, and `store.resolve_person`.
- Nobody has merged or split anything yet: `persons.merged_into` is NULL on all 26,791 records and `not_same` has 0 rows.

### 2. Doubles in stored results

Matchers run on the hit names of every pair of shown cards in one search, after the exact `group_key` (which never repeats among shown cards: 0 repeats, measured). Corroboration means the two cards' records share an affiliation `org_id`. No two records can share an identifier value, because `person_identifiers` has `UNIQUE (scheme, value)`.

| Matcher | All pairs | With shared org | In a top 50 |
|---|---|---|---|
| First initial vs full first name | 40 | 32 | 1 |
| Token order ("Surname, F.") | 33 | 3 | 0 |
| Double surname or trailing stray letter | 5 | 3 | 0 |
| Kept middle name | 4 | 3 | 0 |
| Particle or hyphen joined ("Van X" vs "Vanx") | 4 | 4 | 1 |
| Prefix first name | 3 | 2 | 0 |
| Nickname | 1 | 0 | 0 |
| Total | 90 | 47 | 2 (0 in any top 20) |

Lane mix of the 47 corroborated pairs: OpenAlex with OpenAlex 41, OpenAlex with seeds 4, OpenAlex with web 2. 25 of the 33 token-order pairs involve a web record, and 15 are web with web (12 of those in one marine search). Those web records carry almost no org ids, so a shared org cannot back them.

I read the claims of 30 random corroborated pairs. 21 are one human, 8 are two humans, 1 is unclear. Six of the 8 false pairs have an ORCID clash. The other false pairs are common names in large physics collaborations, where one paper puts hundreds of authors on the same institutions. No true pair had an ORCID clash.

The seed-vs-OpenAlex doubles (6 pairs, 5 distinct people) and why resolve kept each apart:

- Kept middle name, 2 cases. The seed has "First Surname" and OpenAlex has "First Middle Surname". `group_key` keeps a middle token longer than one letter.
- Trailing stray letter, 1 case. The OpenAlex display name ends in a lone capital letter. `group_key` reads that letter as the surname.
- First-name initial, 1 case. OpenAlex has "M. Second Surname" and the seed has the full first name. `group_key` drops one-letter middles but never a one-letter first token.
- Name order, 1 case in 2 searches. The OpenAlex display name is "Surname-initial Firstname". No rule reads that order.

None of these involve the ORCID veto, because seed records carry no ORCID (0 seed records hold one).

The opposite fault also exists: 52 shown cards bundle two or more OpenAlex records under one key without ORCIDs. 8 of them hold 3 to 9 records, all with initial-only names such as "J. Surname", and they mix different humans' affiliations on one card.

### 3. Facts that exist but are not shown

Card facts are computed with the real `present.person_views`, on hits only (today), on all `person_ids`, and on all `person_ids` plus likely records (loose matcher, shared org, no ORCID clash).

| Top 20 (500 cards) | Missing today | Fixed by same-name records | Fixed by likely records |
|---|---|---|---|
| Place | 212 (42%) | 6 | 5 |
| Map point | 213 | 6 | 5 |
| Role | 484 (97%) | 0 | 0 |
| Employer | 6 | 0 | 0 |

| Top 50 (1,250 cards) | Missing today | Fixed by same-name records | Fixed by likely records |
|---|---|---|---|
| Place | 612 (49%) | 20 | 20 |
| Role | 1,155 (92%) | 0 | 1 |
| Employer | 60 | 2 | 0 |

Why linking helps so little:

- Seed records never hold a location claim (0 of the location claims sit on seed records). 79 of 79 seed-only top-20 cards and 269 of 269 seed-only top-50 cards have no place.
- The extra records on a card are mostly other seed rows: 159 of 207 extra records in top-50 cards are seed rows, and 181 of 207 have no location.
- Only 37 of the 269 seed-only top-50 cards have any OpenAlex record with a place in the store, matched by name. For the other 232, the record that would supply the place has never been fetched.
- OpenAlex-only cards miss a place too: 119 of 341 in the top 20s. OpenAlex records hold no role claims, and seed roles are list roles that `is_job` hides (`present.py:117-119`). Role is a completeness problem, not an identity problem.

In the newest search, 11 of the top 20 and 33 of the top 50 have no place.

### 4. How safe linking rules are

Ground truth is weaker than hoped. Two records can never share an ORCID, because `resolve_person` folds a second OpenAlex author id with a known ORCID into the existing record (43 records hold 2+ OpenAlex ids). So "same ORCID" pairs never exist as two records, and every pair below has different ORCIDs.

| Rule, both records with an ORCID | Pairs | Same ORCID | One human, my reading |
|---|---|---|---|
| Same group key, share an org | 41 | 0 | not split out |
| Same group key, share no org | 8 | 0 | not split out |
| Same group key, total | 49 | 0 | 18 of 49 |
| First initial vs full first name, share an org | 37 | 0 | about 4 of 37 |
| First initial vs full first name, share no org | 26 | 0 | not read |
| Other loose matchers, share an org | 17 | 0 | not read |

What this shows:

- A different ORCID is not proof of a different human in OpenAlex data. 18 of 49 same-key pairs look like one person with two ORCIDs (identical full name, same city, 2 or more specific shared orgs). Resolve splits all 49.
- Conflicting middle initials ("A. B. Surname" vs "A. C. Surname") marked a different human in every case I read (4 of 4). `group_key` throws that signal away.
- An initial match with a shared org is unsafe among ORCID holders (about 4 of 37 true). Most of these are common East Asian names in big consortia.
- Name frequency settles it. In the 30-pair sample, "no ORCID clash and at most 3 stored records with that initial plus surname" keeps all 21 true pairs and lets in 2 false ones (21 of 24, 88%).

Base rate of common names: 92 of 15,961 ORCID holders (0.6%) share their group key with another ORCID holder. 1,014 (6.4%) share first initial plus surname.

## Recommendations

1. **One owner for "who is one person": a new `fn/identity.py`.** Its entry point is `link(record_ids) -> list[Link]`, where a link is `(a, b, level, reasons)`. `resolve.group`, `network.add`, `network.name_matches` and `network.possible_matches` call it. They stop reading `group_key` and STRONG schemes themselves. `store.resolve_person` keeps exact identifier lookup only.
2. **Evidence levels and their tests.**
   - *sure*: same value of a person-level identifier (orcid, openalex author id, profile_url, email), or a staff merge.
   - *likely*: names compatible by one of the tested matchers (equal group key, token order, joined particles or hyphens, middle-name subset, first initial vs full name, trailing stray letter, double surname subset). The pair also passes every veto and has corroboration: a shared org held by fewer than 300 records, or the same seed person on two seed rows. And the name is rare: at most 3 stored records share initial plus surname.
   - *possible*: compatible names without corroboration, or same full name with an ORCID clash.
   - *Vetoes*: a `not_same` row, conflicting middle initials, conflicting full first names, an ORCID clash (unless staff merged).
3. **Sure and likely records share one card at search time. Possible records only show "possible match" on the card.** `resolve` stops adding bare same-name records to the card. Today it adds them to `person_ids` and they show nothing anyway.
4. **The card shows facts from every sure and likely record, not just the hits.** `present.card` and `results` read `linked_person_ids` instead of `hits_of`. `rank.belgian_list` counts the same records, so the score and the card agree.
5. **No merge is written at search time.** The grouping stays in `candidates` until staff press Add. Add then merges the sure and likely records. A person-level conflict uses only orcid, openalex and profile_url; the per-row `seed` scheme is removed from STRONG (`network.py:20`). Staff undo a wrong link with "Not the same person" on the card. It writes `not_same` (`network.not_same` exists), resolve already honors it, and the undo log reverses it.
6. **Fetch the missing record for seed people.** For a seed hit with no linked OpenAlex record, the OpenAlex lane looks up authors by name and the seed's institution. That is a free API, and the lane already calls it. Identity then links the result. This is the only path to a place for 232 of 269 seed-only top-50 cards.
7. **Contract changes.**
   - `Entry` and `Candidate` gain `links: list[Link]`.
   - `person_ids` means the records on the card (sure plus likely).
   - `possible_ids` holds the rest.
   - `hit_person_ids` keeps lane provenance only.
   - Bump `contracts_version`, and backfill old candidates by mapping the old `person_ids` to `possible_ids`.
8. **Tests and metrics.**
   - `tests/test_identity.py`: one fixture pair per matcher and per veto, with invented names.
   - A local labelled pair file holding ids only, never names: the 30 sample pairs plus the 49 ORCID pairs. A script scores precision and recall per level, so a rule change shows its effect.
   - Scorecard metrics per search: likely-double pairs in the top 50 (target 0, today 2 across 25 searches), share of top-20 cards with a place (today 288 of 500, 58%), share of seed-only top-50 cards with a linked OpenAlex record (today at most 37 of 269), and cards that bundle 3+ initial-only OpenAlex records (today 8).

## Open decisions

- **The ORCID clash.** Should it stay a hard veto? It is safe against false merges, but it splits about 37% of same-name ORCID pairs that look like one human. My pick: veto at *likely*, show as *possible*.
- **The rarity and org-size thresholds.** I picked "at most 3 records" and "fewer than 300 records" from one 30-pair sample. They need a larger labelled set before they are fixed.
- **Ownership of the seed lookup.** Should the OpenAlex lane run it during the search, or a separate enrichment step after it? The cost per search is not measured.
