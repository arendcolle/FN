# Task Q2: use the data FN already holds

## Goal

Cards miss facts that FN has on disk and drops. A seed row's job title is filed as a list role, which the card hides. A consul row's city is never loaded. And FN reads the city of an organization from ROR and OpenAlex but has no column to keep it. This task stores those three. A later task shows the employer's city on the card and uses it for the order; this task only makes the data available. Measured background: [research/completeness.md](../research/completeness.md).

## What to build

### 1. Job titles from seed lists (`src/fn/seedload.py`)

The climate list (453 rows) and the consul list (34 rows) carry a real job title in `role`, such as "Senior researcher" or "Honorary Consul of Belgium". `LISTS` files it under `member_of` or `consul_for`, and `present.is_job` hides every list role.

- For these two lists, store the title as a role claim without a list relation, next to the list claim. The list claim stays, because it is the tie.
- Find out how `store.upsert_claim` tells two claims apart before you choose the shape, so both claims survive a load and a second load still writes nothing.
- The other four lists keep one role claim: their `role` is a fellowship type or an academy class, not a job.

### 2. The city of a consul (`src/fn/seedload.py`, `fn-seed`)

Consul rows carry `place` (a city, 30 of 34 rows) and `jurisdiction` (a list of states). Store the place as a location claim of the row, dated like the row's other claims, with coordinates from `fn.geo`.

- `seedload.load(store, seeds, locate=None)`: `locate(city, states) -> (lat, lon) | None`. Without `locate` the claim has no coordinates. The tests that call `load` without it keep passing.
- `fn-seed` passes a `locate` built on `fn.geo`. `fn.geo` reads a cities file it may have to download, and an outside call is only allowed inside a step. Follow how `fn-orgs` makes its outside calls (`src/fn/orgjob.py`).
- Try the city with each state of `jurisdiction` until one is found, then the city alone.
- Leave the `place` of the Francqui and Fayat lists alone: a host city from a fellowship year is history, and Fayat places are countries.

### 3. The city of an organization (`src/fn/orgs.py`, `src/fn/contracts.py`, `src/fn/store.py`, a migration, `src/fn/lanes/openalex.py`)

- Migration `008_org_places.sql`: `orgs` gains `city TEXT`, `lat REAL`, `lon REAL`.
- `OrgFacts` and `Org` gain `city`, `lat`, `lon`, all optional.
- `orgs.ror_record` fills them from the first location's `geonames_details` (`name`, `lat`, `lng`) and lists those fields in its record source.
- The OpenAlex lane fills them from the institution record's `geo` (`city`, `latitude`, `longitude`) wherever it builds org facts today.
- `store.upsert_org(org, replace=False)` keeps a stored row as today, except that it fills `city`, `lat` and `lon` when the stored row has none. A stored city is never overwritten by this path.
- A backfill with no outside call: `orgs.backfill_places(store) -> int` reads the stored OpenAlex institution record sources (their text holds one `path: value` line per field, among them `ror`, `geo.city`, `geo.latitude`, `geo.longitude`) and fills org rows that have no city. It returns the number of rows filled, and a second run fills none. `fn-orgs --places` runs it and prints the count.

## Inputs a real run will meet

A consul row without a place; a city `fn.geo` does not know (claim without coordinates); a jurisdiction with several states; a ROR record without a location; an OpenAlex institution without `geo`; an institution source whose org id is not in `orgs` (skip); an org with a city from ROR and another from OpenAlex (the stored one stays); a database at schema version 7 with data (the migration applies and old rows read back with empty places).

## Tests

With made-up names and places:

- a climate row gives a job title on the person's view (`present.person_views(...)[0].role`), and the list tie still shows
- a BAEF row still gives no role on the view
- a consul row with a place gives a location claim with the coordinates `locate` returned, and none without `locate`
- loading the same seeds twice writes nothing the second time
- `ror_record` returns the city and coordinates of a ROR record, and the record source lists them
- the OpenAlex lane stores an institution's city on its org
- `upsert_org(replace=False)` fills an empty city and keeps a set one
- `backfill_places` fills an org from a stored institution source, skips an org that has a city, and fills nothing on a second run
- the migration test or the store tests read an old org row back with empty places

Each new test must be seen failing without the change it covers.

## Changes to existing tests, approved

- The four tests that pin the list of applied migrations (`tests/test_db.py` for 006 and 007, and the two `ContractsV1Test` tests in `tests/test_web.py`) gain migration 8 in that list.
- `test_seed_fields_map_to_relations_orgs_and_dates` in `tests/test_seedload.py`: the consul row's role claims gain the job title claim, `(None, 'page_date')`.
- A test that pins the exact column list of `orgs`, or builds an `Org` by position, may follow the new columns.

No other existing test may change.

## Hand check

On a throwaway var folder (`mkvar.sh q2`): run the migration, `fn-seed`, then `fn-orgs --places`, and paste the counts. Then count with SQL how many orgs have a city (the research expects about 3,900), how many consul persons have a location claim with coordinates (about 29), and how many climate persons have a role claim without a relation (about 449).

## Not doing

- Showing the employer's city on a card or using it in the order. That is a later task.
- Host cities of fellowships, Fayat countries, profile links of seed rows.
- Re-dating OpenAlex location claims.
- Fetching ROR records again for orgs already stored. `fn-orgs` does that when the owner runs it.
