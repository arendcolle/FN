# Task G3: two tests build their own seed rows with made-up names

## Goal

The repository is public and the seed lists stay local (`.gitignore`: `data/seeds/*.jsonl`). Two tests look up a real person's row in the local seed lists and so carry that person's name: the KVAB membership test in `tests/test_rank.py` (line 190, the test before `BOSTON`) and `test_two_seed_rows_with_one_name_stay_two_persons_in_one_flagged_entry` in `tests/test_resolve.py`. Each test now builds the rows it needs itself, with made-up names, and proves the same invariant.

## What to build

Only the two test files change. No code under `src/` changes.

### `tests/test_resolve.py`

`test_two_seed_rows_with_one_name_stay_two_persons_in_one_flagged_entry` keeps its name and its assertions. Its setup changes: a fresh database (`make_db`), then two seed rows of one list with one made-up name ("Ada Example") and two years, written to a temporary seeds folder and loaded with the loader's entry point `seedload.load(store, seeds=folder)` (`src/fn/seedload.py:125`). Read `seedload.load` and a row of `tests/test_seedload.py` to see the row shape; use the list `baef` so the row keys keep their form (`baef|ada-example|2019|`, `baef|ada-example|2018|`). The docstring names no person: "Two seed rows with one name stay separate persons; a hit on one gives one entry holding both, flagged."

### `tests/test_rank.py`

The test becomes `test_a_kvab_membership_puts_a_seed_record_on_the_list`, with the docstring "A seed hit on a KVAB member's record gets a belgian_years part from the KVAB member_of claim." It keeps every assertion: the part's claims are the person's `member_of` claims at `wikidata:Q1301699`, and the part is `(1, "1 year at Belgian organizations; 1 / (60 + 1)")`. Its setup changes: one made-up KVAB row ("Ada Example", year 2011) loaded with `seedload.load(store, seeds=folder)` into a database that holds the recorded organization facts the claim needs. Find the smallest setup that gives the same result: `make_db` plus `save_recorded_orgs` from `tests/helpers.py`, or `make_seeded_db` plus the made-up row when the organization facts need the seed rows. Look at a real KVAB row in the worktree's `data/seeds/kvab.jsonl` for the row shape, and copy no value of a real person from it.

If a shared helper for "a seeds folder with these rows" already exists in `tests/`, use it. If not, keep the few lines inside each test or add one small helper in `tests/helpers.py`; do not add both.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Loading seed rows from a folder | `seedload.load` (unchanged) |
| The rows each test needs | the test itself |

## Proof that each rewritten test still guards its invariant

A rewritten test proves nothing until it has failed. For each of the two tests, break the code it guards with one small temporary edit, run the test, see it fail, and restore the code (`git diff src/` must be empty at the end):

- resolve: make `resolve` stop flagging two records with one name (for example return no flag for `SAME_NAME`).
- rank: make the `belgian_years` part ignore `member_of` claims.

Paste both failing runs and the passing runs in the report.

## Existing tests that change, approved by the lead

Exactly the two tests above, as described. No other test changes.

## Hand check

```
uv run python -m unittest tests.test_rank tests.test_resolve
uv run python -m unittest
```

Then search both test files for the two surnames the lead names in the prompt (they are not written here). The search finds nothing.

## Not doing

Other files that name people from the seed lists (the lead's scan found more in other tests, two scripts and older notes); they are reported to the owner as their own follow-up. Any change to `make_seeded_db`. Any change under `src/`.
