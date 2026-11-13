# Task Q-7a: two one-page seed lists of business people

## Goal

FN's open lists reach researchers, and the business people an organizer invites sit in small named lists. The BelCham board page and the embassy's advisors page hold about 42 people with a role, an employer and a state (`research/people-sources.md`). This task adds two seed scripts and their loader specs. The lead runs the scripts; the builder writes them against saved sample pages with made-up names and never calls out. Decision W4 in `design.md` and the lead's ruling that the two one-page lists come first. The nonprofit officers from the Form 990 filings are Q-7b, which comes last; this task merges without it. Owner: `scripts/seeds/` and `seedload.py`. Needs nothing; Q-3 grades these lists medium already (`tasks/q-3-evidence.md`, `STRONG_LISTS`).

## Before the builder starts (the lead)

Save these files with every person's name, company, phone number and email address replaced by made-up ones (Ann Example, Example Labs, +1 555 010 0000, ann@example.org), keeping the markup:

- `tests/fixtures/seeds/belcham-about.html` from `https://www.belcham.org/about-us` (a copy from 2026-11-12 is in the research scratch folder as `people-sources/web/belcham_about.html`): the `head` with its title, three staff list items, five board list items with different role-line shapes, and the footer with the copyright year.
- `tests/fixtures/seeds/advisors.html` from `https://unitedstates.diplomatie.belgium.be/en/belgian-network-us/advisors-economic-diplomacy` (scratch copy `people-sources/web/advisors.html`): the title, the California, New York and Texas sections with two entries in California (one wrapped in nested spans, as the page has), every Tel, Email and LinkedIn line, an empty `h3`, the "Popular Services" heading, and the "Last updated on" element with its `datetime`.

## What to build

Each script copies the shape of `scripts/seeds/chambers.py`: a parser, `check_page` raising `StructureError`, `build_rows(...) -> list[dict]` with the row fields `common.REQUIRED` lists (`scripts/seeds/common.py:15`), `main()` that writes through `common.write_rows`. Rows of a person named twice keep the first. The delegation's own side (`chambers.STAFF`) is left out.

### `scripts/seeds/belcham.py`, list `belcham`

- `URL = "https://www.belcham.org/about-us"`, chamber name "The Belgian American Chamber of Commerce in the United States". `main` checks robots.txt with `chambers.check_robots`, fetches with `common.fetch`, saves with `common.save_raw`.
- `ListParser(HTMLParser)`: each `h2` with class `list-item-content__title` is a name; the lines of the next `list-item-content__description` (split at `br` and `p`, empty ones dropped) are its role lines; plus the title and the copyright year (`chambers.COPYRIGHT_RE`).
- A role line holding " - " gives job (before the first " - ") and company (between the first and second " - "). A line before it without " - " is a board office and the role becomes `f"{office}, {job}"`. An entry with no " - " line is chamber staff: role is its first line, no company. Institutions: the company as employer unless it is the chamber, then the chamber as `member_of`. `place` is None, `source_date` the copyright year, `date_method` "page text", `quote` the name and its role lines joined by spaces, as the text layer holds it.

### `scripts/seeds/advisors.py`, list `advisors`

- `URL` as above. Each `h3` whose text is a US state (a `STATES` tuple of the 50 names in the script) opens a section; a `ul` in it is one entry. Its lines: the first is the name. A line whose label before ":" is tel, phone, mobile, cell, fax, email, e-mail, linkedin, website or web, or that holds "@" or matches `\+?\d[\d ().-]{6,}\d`, is dropped before anything else reads it. Of the rest, the first is the role and the second the employer; a role with ", " and no employer line is split at its last ", ".
- Row: `place` the state, `jurisdiction` `[state]`, institutions the employer, `source_date` the first 10 characters of the `datetime` after "Last updated on", `date_method` "page text", `quote` `f"{name}, {role}, {employer}"`.
- The text layer holds the title, the state headings, the quotes and the date line only. `save_raw(LIST, "advisors.html", text.encode(), text)`: the page's own bytes are never saved, so no phone number or email address is written anywhere.

### `src/fn/seedload.py`

`SPECS` (line 42) gains `"belcham": ListSpec(None, job=True)` and `"advisors": ListSpec(None, job=True, place=True)`.

## Inputs a real run will meet

A staff entry without " - "; a board office line; a company equal to the chamber; three " - " parts; an advisor entry wrapped in nested spans; a phone written "+1 (555) 010-0000"; an email inside a link; an empty `h3`; a section after the last state ("Popular Services"); a page with no "Last updated on"; the same person named twice.

## Tests (each must fail without the change)

- New `tests/test_seed_belcham.py`: rows from the fixture with role, employer, chamber membership and the year; staff rows have no employer; `check_page` refuses a page with no list items.
- New `tests/test_seed_advisors.py`: rows with name, role, employer, state and page date; no row field and no text-layer line holds "@" or a phone pattern; then the rows and text layer go to a temp folder and `seedload.load(store, seeds=folder)`, and no stored source text, claim value or claim quote holds "@" or a phone pattern.

## Existing tests that change

None. Stop and report a failure.

## Hand check

`uv run python -m unittest` all green. The lead runs `uv run scripts/seeds/belcham.py` and `uv run scripts/seeds/advisors.py`, then `uv run fn-seed`; counts rows per list against the research's 30 and 12; greps `data/seeds/advisors.jsonl` for "@" and digits of a phone pattern; opens two loaded people's pages.

## Not doing

The Form 990 officers (Q-7b). The wider Wikidata query, Wikipedia categories, SEC filings, FARA. A person's place from the organization's address.
