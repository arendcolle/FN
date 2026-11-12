# Does the place in a question improve the ranking?

No variant passes the bar in task T15, so the ranker stays as it is and no code changed. The place cut (A) and the place cut with a place list (C) cut people hard: the median kept count in searches with a located place falls from 511.5 to 183, a 68% drop. Both also cut one gold pick (GS-29 pick 1), whose only stored place is the Belgian institution of its OpenAlex record. The place list alone (B) cuts nobody, but it leaves the median kept count, the picks in the first 10 (3) and the median pick position (104) where they are today.

## How the numbers were made

A throwaway script replayed `rank.run` from the stored `RankIn` of each search's latest ok rank step, on a migrated copy of the owner's database with `FN_HTTP=replay`. It located each question's place chip with `geo.area`. For each candidate it took `present.place_of` over the claims of the candidate's hit persons and called the place inside when that claim has coordinates within the 100 km radius, outside when it has coordinates beyond it, and unknown otherwise.

The variants were applied on top of today's replayed candidates:

- A cuts a new-section candidate whose place is outside
- B adds a part worth 1 / (60 + 1) to every candidate inside, then reorders
- C does both

Positions count kept people only, network first, as the results page and `scripts/gold/cut_gate.py` count them. Gold picks are matched to candidates with `cut_gate.pick_candidate`.

The replay of today's code does not reproduce every stored row, because claims and list statuses changed after the searches ran. Its totals match the gate on the stored rows (median kept 518, 12 picks reached, 4 in the first 50, 6 in the first 100). Single positions move by a few places, for example GS-02 pick 3 is 99 in the stored rows and 97 in the replay.

## Decision against the bar

| Check | Today | A | B | C |
|---|---|---|---|---|
| Picks that reach the ranker and are cut | 0 | 1 | 0 | 1 |
| Picks in the first 10 | 3 | 3 | 3 | 3 |
| Picks in the first 50 (need 4) | 4 | 4 | 4 | 4 |
| Picks in the first 100 (need 6) | 6 | 7 | 6 | 7 |
| Median pick position | 104 | 65 | 104 | 65 |
| Median kept, all 24 searches | 518 | 191.5 | 518 | 191.5 |
| Median kept, 18 searches with a located place | 511.5 | 183 | 511.5 | 183 |
| Median of the first 50 inside / outside / unknown, located searches | 1 / 19 / 29 | 1 / 0 / 49 | 1 / 19 / 29 | 1 / 0 / 49 |
| Verdict | | fails, cuts a pick | fails, improves nothing | fails, cuts a pick |

For A and C the median pick position counts only the 11 picks they keep.

B moves the Boston picks up (GS-10 picks 1 to 4) and moves GS-10 pick 5, whose place is unknown, down from 202 to 292. The sixth and seventh picks by position stay at 97 and 111, so the median stays at 104.

## Why the place data does not support a cut

The place of most candidates comes from the location claim of their OpenAlex record, which is the location of their last known institution. Searches select people with Belgian evidence, so most known places are in Belgium. In the 18 searches with a located place, a median of 1 of the first 50 people is inside the radius and 29 have no known place.

Every OpenAlex location claim carries the date it was fetched as its claim date, not the date the person was there. "The newest dated location" therefore says where an institution is, not where the person lives now. GS-29 pick 1 is an example: its only location is a Belgian city, 8,833 km from San Francisco.

## Searches without a located place

Six of the 24 stored searches with candidates have no place `geo.area` locates. Five have kind `anywhere_us`, which `geo.area` does not locate by design, and one ("Georgia", no kind) names no city in the GeoNames file. Every variant leaves these searches as they are.

| Search | Case | Place | Kind | Kept |
|---|---|---|---|---|
| f7485ff0 | GS-03 | Georgia | none | 356 |
| d621c1a6 | GS-05 | US West Coast | anywhere_us | 330 |
| 7da28ba1 | GS-09 | US-based | anywhere_us | 585 |
| 588f8ca0 | GS-15 | North Carolina | anywhere_us | 826 |
| 4b74df73 | GS-18 | US | anywhere_us | 492 |
| 32944796 | GS-23 | US | anywhere_us | 1130 |

## Searches with a located place

Each cell gives the kept count, then the first 50 kept people as inside / outside / unknown.

| Search | Case | Place | Located as | Today | A | B | C |
|---|---|---|---|---|---|---|---|
| 4061fbe5 | GS-01 | Atlanta | Atlanta, US | 205 (0/29/21) | 37 (0/0/37) | 205 (0/29/21) | 37 (0/0/37) |
| 09bb8098 | GS-02 | New York and New Jersey area | New York City, US | 544 (3/18/29) | 280 (3/0/47) | 544 (3/18/29) | 280 (3/0/47) |
| de0821b3 | GS-04 | Atlanta | Atlanta, US | 261 (0/21/29) | 63 (0/0/50) | 261 (0/21/29) | 63 (0/0/50) |
| cd693a39 | GS-07 | Bay Area | San Francisco, US | 323 (0/23/27) | 194 (0/0/50) | 323 (0/23/27) | 194 (0/0/50) |
| e8bfab16 | GS-10 | Boston | Boston, US | 417 (31/6/13) | 291 (35/0/15) | 417 (50/0/0) | 291 (50/0/0) |
| 00f573b8 | GS-11 | New York | New York City, US | 546 (1/18/31) | 215 (1/0/49) | 546 (1/18/31) | 215 (1/0/49) |
| 8ea718e3 | GS-12 | New York | New York City, US | 287 (0/18/32) | 140 (0/0/50) | 287 (0/18/32) | 140 (0/0/50) |
| 4835b920 | GS-13 | New York | New York City, US | 591 (2/19/29) | 166 (2/0/48) | 591 (2/19/29) | 166 (2/0/48) |
| 640fc679 | GS-14 | New York | New York City, US | 675 (3/25/22) | 141 (5/0/45) | 675 (5/23/22) | 141 (5/0/45) |
| ee2a9b42 | GS-21 | New York | New York City, US | 544 (1/16/33) | 236 (1/0/49) | 544 (1/16/33) | 236 (1/0/49) |
| d0c10112 | GS-24 | New York | New York City, US | 479 (1/19/30) | 187 (1/0/49) | 479 (1/19/30) | 187 (1/0/49) |
| 1e9d81a5 | GS-27 | San Diego | San Diego, US | 454 (0/21/29) | 156 (0/0/50) | 454 (0/21/29) | 156 (0/0/50) |
| 997fe1a6 | GS-28 | New York | New York City, US | 611 (3/19/28) | 189 (3/0/47) | 611 (3/19/28) | 189 (3/0/47) |
| be5cab9d | GS-29 | Bay Area | San Francisco, US | 1103 (0/29/21) | 149 (0/0/50) | 1103 (1/29/20) | 149 (1/0/49) |
| 3e5bf1e9 | GS-30 | London | London, GB | 452 (3/22/25) | 97 (3/0/47) | 452 (3/22/25) | 97 (3/0/47) |
| 08bbccbb | GS-31 | Los Angeles | Los Angeles, US | 471 (0/18/32) | 186 (0/0/50) | 471 (0/18/32) | 186 (0/0/50) |
| f10ee197 | GS-32 | Los Angeles | Los Angeles, US | 800 (0/15/35) | 194 (0/0/50) | 800 (0/15/35) | 194 (0/0/50) |
| 9631ca7c | GS-33 | Atlanta | Atlanta, US | 877 (3/14/33) | 180 (3/0/47) | 877 (3/14/33) | 180 (3/0/47) |

## Gold picks that reach the ranker

Each cell is the pick's position among kept people, or "cut".

| Case | Pick | Search | Place | Today | A | B | C |
|---|---|---|---|---|---|---|---|
| GS-02 | 3 | 09bb8098 | unknown | 97 | 65 | 97 | 65 |
| GS-10 | 1 | e8bfab16 | inside | 2 | 1 | 1 | 1 |
| GS-10 | 2 | e8bfab16 | inside | 235 | 206 | 130 | 129 |
| GS-10 | 3 | e8bfab16 | inside | 9 | 7 | 7 | 7 |
| GS-10 | 4 | e8bfab16 | inside | 10 | 8 | 8 | 8 |
| GS-10 | 5 | e8bfab16 | unknown | 202 | 175 | 292 | 265 |
| GS-15 | 3 | 588f8ca0 | no located place | 111 | 111 | 111 | 111 |
| GS-21 | 2 | ee2a9b42 | unknown | 129 | 89 | 129 | 89 |
| GS-21 | 5 | ee2a9b42 | unknown | 383 | 217 | 383 | 217 |
| GS-28 | 1 | 997fe1a6 | unknown | 94 | 60 | 94 | 60 |
| GS-28 | 2 | 997fe1a6 | unknown | 38 | 23 | 38 | 23 |
| GS-29 | 1 | be5cab9d | outside | 126 | cut | 127 | cut |
