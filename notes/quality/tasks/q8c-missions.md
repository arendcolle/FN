# Task Q8c: a seed list from the 2022 economic mission program

## Goal

The program of the 2022 Belgian economic mission to the US names every session with its speakers, their titles and their employers. It is the cleanest public record of whom Flanders put on a stage: 26 of the 99 gold picks are in it. FN reads none of it. This task adds its speakers as a seed list. Background: [research/sources.md](../research/sources.md), decision D13 in [panel-records.md](../panel-records.md).

## What to build

### 1. The scraper (`scripts/seeds/missions.py`)

Follow the other scrapers: `common.fetch`, `common.save_raw`, `common.write_rows`, the fields of `common.REQUIRED`, a `StructureError`, exit 1 when the shape changed. `scripts/seeds/kvab.py` shows how a scraper reads a PDF: it declares its PDF reader as an inline script dependency, so the app gets no new dependency. Do the same. The `pdftotext` program on this Mac may serve as a cross-check, not as the reader.

The source: the program PDF "Belgian Economic Mission USA, Program", updated 3 June 2022, on a partner site that answers 403 to a generic client. Fetch the Wayback Machine's copy through its raw form (`https://web.archive.org/web/<stamp>id_/<origin url>`). Find the origin URL in the sources researcher's scratch file `quality/sources/goldurls.txt` (first line) and a copy of the PDF in `quality/sources/pdf/` for comparison. Pin the Wayback timestamp in the script.

One row per speaker, not per session:

| Field | Value |
| --- | --- |
| `list` | `missions` |
| `row_key` | `common.row_key("missions", name, 2022)` |
| `name`, `name_on_page` | as the program writes the person, without titles such as Mr, Ms, Dr, H.E. |
| `year` | 2022 |
| `role` | the person's job title as the program gives it |
| `institutions` | the employer as `employer` |
| `field` | the title of the session, or of the sessions joined by "; " |
| `place`, `jurisdiction` | none: the session's city says where the event was, not where the person lives |
| `profile_url` | none |
| `source_url` | the Wayback raw URL with its timestamp |
| `source_title` | the document's title and the origin URL |
| `source_date`, `date_method` | 2022-06-03, from the document's own "updated on" line |
| `page` | the PDF page of the quote |
| `quote`, `raw_path` | the line or block that names the person with title and employer, in the PDF's text layer |

Left out, each counted in the printed summary:

- staff of the delegation's own side, who are FN's users: people whose employer is Flanders Investment & Trade, the Delegation of Flanders, AWEX, hub.brussels, the Belgian Foreign Trade Agency, or a Belgian embassy or consulate
- members of the royal family and ministers
- a name without a title or an employer on any line
- a line the parser cannot split with confidence. Do not guess: a wrong employer on a person's card is worse than a missing person.

### 2. The list in the loader (`src/fn/seedload.py`)

One line in the spec table: `missions`, no list claim, `role` is a job title, no place.

## Inputs a real run will meet

A speaker in three sessions (one row, the field joins the sessions); a name split over two lines by the PDF's columns; two speakers on one line; a moderator; a company name with a comma; a page of logistics with no speakers; the Wayback copy unavailable (stop with a clear message).

## Tests

With a made-up program text and made-up names, in `tests/test_seed_missions.py` and the loader tests:

- the parser finds a speaker with title and employer, joins a speaker's sessions, and leaves out staff of the delegation's side, a minister and a name without an employer
- two speakers on one line give two rows; a name split over two lines gives one
- a changed document shape raises `StructureError`
- loading a `missions` row gives a job role on the person's view dated 2022, a `works_at` claim dated 2022, a topic claim with the session, and no list claim and no location

Each new test must be seen failing without the change it covers. No existing test may change.

## Hand check

Run the scraper for real, then `uv run python scripts/seeds/check.py`. Then check 30 rows drawn at random against the PDF's text by hand: the name, the title and the employer must be what the program says for that person. Report how many of the 30 are fully right. If fewer than 27 are right, tighten the parser so it leaves more out, and check 30 again. Then load into a throwaway var folder (`mkvar.sh q8c`, `uv run fn-seed`) and paste: rows written, rows left out per reason, persons and claims added. Count, with no names in your report, how many gold picks in `data/gold/gold-set.json` have the same folded name as a row.

The data file and the raw PDF stay local: git ignores them. Leave them in the worktree and say where they are.

## Not doing

- The trade agency's participants brochures, other years' programs, event pages.
- A place for a speaker.
- Reading the PDF with a model.
