# Task Q8b: a seed list from the Belgian-American chambers' board pages

## Goal

The delegation asks about business people in a US region with a Belgian tie. The Belgian-American chambers of commerce name such people on their board pages, with role, company and often a city. FN reads none of them. This task adds the board and leadership pages of two chambers as one seed list. Background: [research/sources.md](../research/sources.md), decision D13 in [panel-records.md](../panel-records.md).

## What to build

### 1. The scraper (`scripts/seeds/chambers.py`)

Follow the other scrapers (`scripts/seeds/fayat.py` is the shortest, `wikidata.py` the newest): `common.fetch` with its generic User-Agent and its pause per host, `common.save_raw`, `common.write_rows`, the fields of `common.REQUIRED`, a `StructureError` and exit 1 when a page's shape changed. Obey each site's robots.txt: read it once and stop with a clear message when it forbids the page.

Pages, board and leadership only:

- the Southeast chamber's about page (a static list of board members with role and company)
- the West Coast chamber's board page

Find the two URLs in [research/sources.md](../research/sources.md), section 2, and check them with one fetch each. If a third chamber has a board page in the same form, add it and say so; do not read event pages.

A row:

| Field | Value |
| --- | --- |
| `list` | `chambers` |
| `row_key` | `common.row_key("chambers", name, None, <a short word for the chamber>)` |
| `name`, `name_on_page` | the person as the page writes them |
| `year` | none |
| `role` | the person's job title at their company when the page gives it, else their board role |
| `institutions` | the company as `employer`; the chamber as `member_of` |
| `field` | none, or the sector when the page gives it |
| `place` | the person's city when the page gives it, else the chamber's home city, as "City, State" |
| `jurisdiction` | none |
| `profile_url` | the person's link on the page, if any |
| `source_url`, `source_title`, `source_date`, `date_method` | the page, its title, and its date when the page states one, else none with the method the loader maps to "no date" |
| `quote`, `raw_path` | the person's entry on the page, in the page's text layer |

### 2. The list in the loader (`src/fn/seedload.py`)

One line in the spec table: `chambers`, no list claim of its own (the `member_of` institution is the membership), `role` is a job title, `place` is a current place stored as a location claim without a relation. The chambers need org ids to count as a tie only if they are Belgian organizations; they are US organizations with a Belgian purpose, so add nothing to the alias file. The tie of a chamber board member is the membership text itself.

## Inputs a real run will meet

A page that answers 403 or moved; an entry with a name and nothing else; honorary members and staff listed beside the board (keep both, the role says which); the same person on two chambers' boards (two rows); a name with a title or a suffix.

## Tests

With a made-up page and made-up names, in `tests/test_seed_chambers.py` and the loader tests:

- the parser turns each chamber's page shape into rows with role, company and place
- an entry without a company still gives a row; an entry without a name is left out
- a changed page shape raises `StructureError`
- loading a `chambers` row gives a job role on the person's view, a `works_at` claim, a `member_of` claim for the chamber and a location claim

Each new test must be seen failing without the change it covers. No existing test may change.

## Hand check

Run the scraper for real, then `uv run python scripts/seeds/check.py`, then load into a throwaway var folder (`mkvar.sh q8b`, `uv run fn-seed`) and paste: rows per chamber, rows with a place and how many got coordinates, persons and claims added. Count, with no names in your report, how many gold picks in `data/gold/gold-set.json` have the same folded name as a row.

The data file and the raw pages stay local: git ignores them. Leave them in the worktree and say where they are.

## Not doing

- Event pages, member directories, newsletters.
- The New York chamber's event highlights.
- Guessing a person's Belgian background. The membership is the only tie this list states.
