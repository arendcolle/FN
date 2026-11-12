# Task Q12: the seed lane searches the place of a question

## Goal

The seed lane searches topic and institution words only. A consul in Atlanta, a chamber board member in San Francisco or a Wikidata person at a Boston hospital never shows up for a question about that city unless their record also names the topic. The consul list reached the shown results 3 times in 29 searches. This task lets the lane also find people by the place of the question. Decision D13 in [panel-records.md](../panel-records.md), point 4; the place function is `evidence.places` from the ranking task.

## What to build

### `src/fn/lanes/seeds.py`

- The place search runs only for a question that names a place and nothing else: no topic word that carries meaning and no institution chip. And only when `geo.area` returns an area for that place: a city area. A country, a state, `anywhere_us` and a place the cities file does not know get no place search.
- Why only then: the first build ran it for every question with a city. On the second snapshot it added 341 people who match the city and not the topic, and the ranker lifted them above topic matches (96 first-20 cards without a topic word, against 5). For a question with a topic, the ranker already uses the place of the people the other searches find.
- It finds people whose records from seed lists, imports and staff edits (the same source kinds the lane's text search reads) have a current place inside the area's radius. "Current place" is what `evidence.places` returns for those records' claims: a stated place, or the employer's city from a recent employer fact. A host institution of an old fellowship never counts, because `evidence.places` does not return it.
- At most 20 people, nearest first.
- The hit's `matched_on` reads "based in " and the place's text, and its `claim_ids` hold the place's claim.
- The lane's log line says how many place hits it added.

### `src/fn/store.py`

One read for the lane: the people who may be near a point. It returns the person ids that have a located claim, or a claim at an organization with a located city, inside a box around the point, from the given source kinds. The lane then asks `evidence.places` for the exact answer. No SQL in the lane.

## Inputs a real run will meet

A place of every kind; an area with no seed person near it; more than 20 people in the area; a person with a stated place inside and an employer outside (inside counts); a person whose only place is an employer fact older than five years (no hit); a consul whose city has no coordinates (no hit); a person in the network section.

## Tests

With made-up seed rows and places, in the seed lane tests:

- for a question with only a place, a consul in that city is a hit with "based in" and the place claim
- a person 300 km away is no hit; a person with an old employer fact in the city is no hit
- 25 people in the area give 20 hits, nearest first
- a country place, an `anywhere_us` place and an unknown city give no place search
- a question with a topic word and a city gets no place hits; so does a question with an institution chip and a city

Each new test must be seen failing without the change it covers. No existing test may change.

## Hand check and gate

Load the seed lists into a throwaway var folder first (`mkvar.sh q12`, `uv run fn-seed`), so consul places exist. Then, from this worktree and from the main checkout (read only): `fn-score run var/score/2026-11-12 --mode replay --out <scratch> --allow-degraded`, `fn-score compare main.json branch.json` and `fn-score diff main.json branch.json`. The frozen snapshot holds no consul places, so expect few place hits there; say how many. Gates: compare exits 0 on both snapshots and nothing moves, because every stored question has a topic or an institution. Then run one made-up question that is only a US city on your throwaway copy (create the search with chips that hold only the place, so no model call is needed) and report how many place hits the lane added and who is in the first 20, by list and without names.

## Not doing

- Place search for states, regions and countries.
- Any change to the ranker or the page.
