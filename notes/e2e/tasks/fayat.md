# Task: add the Fayat scholars as a seed list

Branch `feat/seed-fayat`. First find out whether a public list exists. Build the scraper only if it does.

## Why

The to-do list asks for the Fayat scholars as a sixth seed list, "a scraper in `scripts/seeds/` like the other five". Fayat scholarships are grants of the Flemish government for top students at universities abroad. Earlier research (`notes/research/mvp-tech-reference.md:22`, `:160`) found no list online: the Chancellery page named one laureate.

## Step 1. Find the public pages that name Fayat scholars

Search the web again. Look at the Flemish government's pages on the Fayat scholarships (vlaanderen.be, fdfa.be, flandersinusa or similar), press releases per year, and news pages of the Flemish universities. Use generic search terms only, and send no project or personal details to outside services.

Write what you found to the report: each page URL, how many scholars it names, for which years, and whether the page is stable enough to scrape (a list or table, not a single news story).

Decide:

- **A list exists** (one or a few pages that together name at least 10 scholars): go to step 2.
- **No list exists**: stop. Report the pages, the count of names reachable, and say that the seed list cannot be built from public pages. Change no file.

## Step 2. Build the scraper like the other five

Read `scripts/seeds/consuls.py` and `scripts/seeds/common.py` first, and the section "How a seed list is produced" in `notes/e2e/research/tests-tooling.md`.

- `scripts/seeds/fayat.py`: a PEP 723 script that fetches with `common.fetch`, saves raw pages with `common.save_raw`, builds rows and calls `common.write_rows("fayat", rows)`. It raises a clear error when the page shape changed.
- `src/fn/seedload.py`: add `fayat` to `LISTS` with the relation `fellow_of` and the organization the grant belongs to. If that organization has no row in `data/org_aliases.csv`, say so in the report instead of inventing an id.
- `scripts/seeds/check.py`: add the expected count.
- The JSONL and the raw pages stay local: `data/seeds/` is gitignored because the repository is public. Never put a scholar's name in a committed file, a test or a note.
- Tests: `tests/test_seedload.py` holds the total row count in three places. A sixth list changes that total on purpose, so update the number and say so in the report. Add a test for the scraper's parser on a made-up page with made-up names.

Hand check: run the scraper, run `uv run python scripts/seeds/check.py`, load into a throwaway database (`FN_VAR=<a temp dir> uv run fn-seed`) and report the row count and how many scholars got an institution claim.

## Rules for this task

- Run `uv run python -m unittest` before you start (267 tests pass) and when you finish. Every test must pass.
- No new project dependency. The scraper may declare its own in its PEP 723 header, like `kvab.py`.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
- Fetch at most once a second per host, as `common.fetch` does.
