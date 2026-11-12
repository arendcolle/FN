# Task Q3: one owner for who is one person

## Goal

Five places in the code decide whether two records are one person, with two different veto rules. Cards bundle unrelated OpenAlex records under one initial, Add cannot merge two rows of one seed list, and a card shows only the facts of the records a lane hit. This task gives the question one owner, `src/fn/identity.py`, and makes every other place ask it. Decision D11 in [panel-records.md](../panel-records.md) is the rule set; [plan.md](../plan.md) has the rulings that close the review's findings; [research/identity.md](../research/identity.md) has the measurements with file and line.

## The rules

**Name key.** `identity.key(name)` is the key two names must share to be compared at all. It replaces `contracts.group_key`, which moves out of `contracts.py`. It starts from `contracts.name_key` and then:

- drops a last token of one letter when the name has three or more tokens (OpenAlex display names sometimes end in a stray letter)
- reads the surname as everything from the first particle after the first token to the end (van, von, de, den, der, des, du, la, le, ten, ter, te, di, da, del, dos, el, al), joined without spaces, else the last token alone. So "Van de Wiele" and "Vandewiele" give one surname, and "de Groot-Smit" gives "degrootsmit", not "smit"
- keeps the first given name and drops the other given names and initials

Two names with one key can still be two people. That is decided per pair. Known gaps, accepted: `name_key` splits a name at hyphens and apostrophes, so "Jean-Luc" keys as "jean" (the middle-name veto still keeps Jean-Luc and Jean-Marie apart), and "O'Neil" keys as the initial "o", so such a person is only ever a possible match. A hyphenated surname without a particle keys as its last part.

**Levels.** `identity.same_person(store, a, b) -> tuple[Level, str]`, with `Level = Literal["sure", "likely", "possible", "no"]` and a reason word.

| Level | When | Reason |
| --- | --- | --- |
| sure | both records belong to one person already (a staff merge, or one record) | `merged` |
| no | a veto, checked before anything else below | the veto's word |
| no | the names have different keys | `name` |
| possible | either first name is one letter | `initial` |
| likely | a shared organization among the two records' claims, held by fewer than 300 person records | `shared_org` |
| likely | both are rows of one seed list whose row keys differ only in the year, and the years are at most 10 apart | `same_seed_row` |
| likely | a shared organization of any size, and the name key is held by at most 3 person records, not counting records whose only identifier is a mention on a web page | `rare_name_org` |
| likely | one of the two records is only a mention on a web page (its identifiers are all of the `mention` scheme), and the name key is held by at most 3 person records, not counting such mention records | `rare_name_mention` |
| possible | everything else with one key | `name_only` |

**A rare name alone is not enough.** The first build linked records by a rare name without anything else. On the labelled pairs that rule linked 82 pairs, of which 4 could be shown to be one person and 1 was two people, while a shared small organization linked 59 with 35 shown the same and none different. So rarity only counts together with a shared organization. Two rows of one seed list 34 years apart were also two people, hence the 10 years.

**A web mention is the exception.** A record that is only a name on a web page has no organization to share, so the rule above split an OpenAlex author from the page that mentions them: 16 first-20 cards lost a record, which shows staff the same person twice. For such a record a rare name is enough. A seed row and an OpenAlex record with a rare name and no shared organization stay two cards.

**The network is never joined by likely.** A record that belongs to a person in the network is linked only by sure. A hit that is likely the same as a network person stays its own card, and the network person stays in `person_ids`, so the existing "Same name as ... in your network" line and the Same person choice decide it. Add never merges a network person into another record on its own. The network is the owner's curated list, and nothing joins it without a decision.

**Vetoes.** A not-same decision between the two (`not_same`). Different ORCIDs (`orcid`). Different profile links (`profile_url`). Middle names that contradict: both names have middle tokens and the initials of one are not a subsequence of the other's (`middle`). Two OpenAlex ids, or two seed rows, are no veto: `STRONG` in `network.py` goes away.

## What to build

1. `src/fn/identity.py` with `key`, `same_person`, and `on_card(store, candidate) -> list[str]`: the records a card reads now. For a candidate with `card_person_ids` it is those, minus any record with a not-same decision against the first. For an older stored row without them it is the hit records, else the first person id, as today.
   - Deciding many pairs must not run a query per pair. Load what the rules need once per call of resolve: identifiers, the org ids of claims, the counts per name key and per organization, the not-same pairs, the canonical ids.
2. `Entry` and `Candidate` gain `card_person_ids: list[str] = []`. Migration `009_card_records.sql` adds `card_person_ids_json TEXT NOT NULL DEFAULT '[]'` to `candidates`. `store.save_candidates` and `list_candidates` write and read it. `person_ids` keeps its meaning.
3. `resolve.py` asks `identity`. Within one name key, a record joins the first card where it is sure or likely with a member and has a veto against none. A card's `card_person_ids` are its hit records plus the stored records that are sure or likely with one of them. A stored record that is only possible stays in `person_ids` with a flag, as today. Hits that are only possible with each other become separate entries, so initial-only records are never bundled.
4. `network.py`: `add` merges each later record into the first when `same_person` says sure or likely, and leaves the others apart. `name_matches` and `possible_matches` use `identity.key` and drop pairs with a veto. `STRONG`, `_strong` and `_conflicts` go.
5. Every other caller of `contracts.group_key` moves to `identity.key`: `store.person_ids_by_group_key`, `store.network_by_group_key`, `importer.py`, `web/debug.py`, and the lookup of stored records by name in `gold.stored_text`. `contracts.group_key` then goes away. The frozen matcher `gold.pick_key` and `gold.match` are not touched. In `score.py` only the function that names a card's records changes: `card_ids(store, candidate)` returns `identity.on_card(store, candidate)`. `rank.fuse` passes `card_person_ids` from the entry to the candidate and changes nothing else.
6. `present.py` reads `identity.on_card` wherever it reads a card's records today (`hits_of`): the facts, the place, the evidence, the skipped state, the name match.
7. `web/staff.py`, `card_decision` only: Add, Skip and the same-person choice act on `identity.on_card(store, candidate)`.
8. The labelled pair file `data/gold/identity-pairs.jsonl` in your worktree (git ignores the folder), in the format of [tasks/q6-scorecard-two.md](q6-scorecard-two.md) section 5. At least 120 pairs of record ids from the frozen snapshot's database (`var/score/2026-11-12/fn.sqlite3`, read only), with these parts: the identity researcher's sampled pairs (`q2_sample.json` and the pairs behind `q4.py` in the scratch folder `quality/identity/`), the D11 panel's samples (scratch folders `quality/panel/D11-*`), at least 15 pairs per likely reason, at least 10 pairs per veto, and at least 15 pairs of two different people with one common name.
   - Label a pair `same` only when two facts that do not depend on each other agree, for example a specific shared organization and the same field, or the same city and the same co-author. Label it `different` when the facts contradict: different ORCIDs with different fields, or careers that cannot be one person's. Otherwise `unclear`.
   - The note says which facts decided, without any name.

## Changes to existing tests, approved

- `tests/test_network.py`, `test_a_hit_with_another_openalex_id_stays_apart`: two OpenAlex ids no longer keep two records apart. Rewrite it to the new rule: two records with one name and different ORCIDs stay apart. Add its mirror as a new test: two OpenAlex ids, a rare name, merged.
- `tests/test_resolve.py`, `test_two_seed_rows_with_one_name_stay_two_persons_in_one_flagged_entry`: the two rows of one seed list with one name are likely one person. They stay two persons in the store, both are on the card, and the flag text for a card that combines records may change. Keep what the test proves: nothing merges in the store at search time.
- `tests/test_card_actions.py`, `test_add_merges_the_hits_and_leaves_a_conflicting_hit_apart`: two seed ids no longer keep two records apart. Give the second record a different ORCID, so the test still proves that a record left apart shows "1 possible match".
- `tests/test_score.py`, `test_pair_metrics_are_left_out_without_a_pair_file_and_counted_with_one`: it reads the real `data/gold` path, so it fails once the pair file exists there. Point it at a temporary path instead, for both of its cases.
- Tests that pin the list of applied migrations gain 9. Tests that pin the exact columns of `candidates` gain the new column.
- `tests/test_contracts.py`, `test_group_key_drops_middle_initials_only`: the function moves, so this test moves to `tests/test_identity.py` as a test of `identity.key`, with the keys the new rules give.
- `tests/test_gold.py`, `test_pick_key_gives_what_group_key_of_name_key_gives_today`: it compares the frozen matcher with `contracts.group_key`, which goes away. Replace the comparison with the ten literal keys `gold.pick_key` gives today, so the test still guards the freeze. `gold.py` itself does not change.
- Other tests that import `group_key` from `contracts` import `identity.key`.

`tests/test_rank.py`, the test that a record joined only by name never scores, and `tests/test_flows.py` must stay green unchanged: the flow where a search hits a second record of a network person keeps its "Same name as" line because of the network rule above. No other existing test may change. If one fails, stop and report it.

## Inputs a real run will meet

One-token names; names with particles, hyphens and accents; "Surname, First" (the key differs; that pair stays apart, and it is a known gap); two seed rows of one person in two years; a seed person and an OpenAlex author with one name at one small institute (likely) and at one university with thousands of records (possible unless the name is rare); a common name at a large university (possible); three records where A fits B and B fits C but A has a veto against C; a record merged into another; a not-same decision made after the search was stored; an old stored candidate without card records.

## Tests

`tests/test_identity.py`, with made-up names and organizations:

- `key`: the trailing letter, the joined particles, a dropped middle name, a one-token name
- one case per level and reason in the table, and one per veto
- a common name sharing only a large organization is possible; a rare name sharing nothing is possible for two records that are not web mentions, and likely when one of them is only a web mention; a common name with a web mention is possible; a rare name sharing a large organization is likely; a web mention does not count toward rarity; two seed rows 11 years apart are possible
- resolve: two initial-only hits give two entries; a stored likely record joins the card and a stored possible record does not; A, B, C with a veto between A and C gives two cards
- `add` merges two seed rows of one list and two OpenAlex ids that share an organization and a rare name, and leaves a record with another ORCID apart; undo restores every row
- `on_card` drops a record after a not-same decision, and gives the hit records for an old row
- a card's view shows a place that only its likely record holds

Each new test must be seen failing without the change it covers.

## Hand check and gates

From this worktree and from the main checkout (read only), run `fn-score run var/score/2026-11-12 --mode replay --out <scratch> --allow-degraded`, then `fn-score compare main.json branch.json` and `fn-score diff main.json branch.json`. Copy your pair file to `data/gold/` of both checkouts' worktree copies before the runs, never into the snapshot. Paste the output. The gates:

- `pairs_wrong` is 0 on the branch
- `doubles_top20` is 0
- the diff shows at most 2 first-20 cards across all searches that changed because a card lost a record
- no kept card holds two hit records whose first names are both one letter: count them with SQL on your throwaway copy, before and after (8 before)
- `place` does not fall

Also report, per likely reason, how many labelled pairs the rule links and how many of those are labelled `same`.

## Not doing

- Matching an initial against a full first name, or "Surname, First" order. Those pairs stay possible.
- Any change to the order or the cuts. The ranker still scores hit records only.
- The card line that says a card combines records. The page task adds it.
- Merging anything in the store at search time.
