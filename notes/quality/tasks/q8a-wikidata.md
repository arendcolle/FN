# Task Q8a: a seed list from Wikidata, and a loader that takes more kinds of list

## Goal

70 of 83 gold picks never reach the ranker, because the people staff pick are not in FN's sources. Wikidata holds about 950 living people with a Belgian tie and a job or a home in the US, with a current employer and often a city. This task adds them as a seed list, so a search can find them with a filled card. Background: [research/sources.md](../research/sources.md), decision D13 in [panel-records.md](../panel-records.md).

## What to build

### 1. A list spec in the loader (`src/fn/seedload.py`)

Today `LISTS` maps a list to the relation and the organization of its list claim, and two more constants say which lists carry a job title and which a place. Make it one spec per list, so a new list is one line:

- the relation and organization of the list claim, or none when being on the list is not a membership
- whether `role` is a job title (today: climate and consuls)
- whether `place` is a current place, and the relation of that location claim (today: consuls, `lives_in`)

The six lists behave as before. No existing test may change.

### 2. The scraper (`scripts/seeds/wikidata.py`)

Follow the other scrapers (`scripts/seeds/fayat.py` is the shortest): `common.fetch`, `common.save_raw`, `common.write_rows`, the row fields of `common.REQUIRED`, a `StructureError`, exit 1 on a changed shape. The row contract does not change: no new field.

Who is in:

- a living human (no date of death)
- with a Belgian organization: educated at (P69) or employed by (P108) an organization whose country (P17) is Belgium. Citizenship or birthplace alone is not enough, because the loader has no claim for them.
- and in the US now: an employer (P108) in the US whose statement has a start date and no end date, or a residence (P551) in the US

Where from: the Wikidata query service, or its public mirror when the service limits requests. Use `common.USER_AGENT`. One query, or a few by page. No per-person crawl beyond what the row needs. Save each person's part of the answer as that person's raw file, so each person's facts cite their own Wikidata item.

A row:

| Field | Value |
| --- | --- |
| `list` | `wikidata` |
| `row_key` | `common.row_key("wikidata", name, None, qid)` |
| `name`, `name_on_page` | the English label, else the Dutch, else the French |
| `year` | none |
| `role` | the first occupation (P106) label, or none |
| `institutions` | each current US employer as `employer`; each Belgian school as `student`; each Belgian employer as `home` |
| `field` | the field of work (P101) labels, else the English description |
| `place` | the US residence city, else the city of the current US employer's headquarters (P159), as "City, State" when the state is known |
| `jurisdiction` | none |
| `profile_url` | the item URL |
| `source_url`, `source_title` | the item URL, "Wikidata item <label>" |
| `source_date`, `date_method` | the item's last change date, with a date method the loader maps to a record date |
| `quote`, `raw_path` | the person's text layer: label, description and one line per statement used, with its dates |

Left out, each counted in the scraper's printed summary: no label in the three languages; a label that is only the item id; an employer statement with an end date or without a start date (the row has one date for all its claims, so a past job cannot be dated); a person left with neither a current US employer nor a US residence.

### 3. The list in the loader

`wikidata` in the spec table: no list claim, `role` is a job title, `place` is a current place stored as a location claim without a relation. Add the date method mapping the scraper uses.

## Inputs a real run will meet

The query service answers 429 or times out (try the mirror, then stop with a clear message); a person with three employers; an employer without a country; a label with a comma or a title; two people with the same label (two rows, two keys); a person already on another seed list (a separate row; identity decides later); a city `geo` does not know (the loader stores the place without coordinates).

## Tests

With a made-up query answer and made-up names, in a new `tests/test_seed_wikidata.py` and in the loader tests:

- the parser turns an answer into rows: an open-ended US employer is `employer`, an ended one is left out, a Belgian school is `student`
- the place is the residence when there is one, else the employer's city
- a person without a label, and one without a current US tie, are left out and counted
- a changed answer shape raises `StructureError`
- loading a `wikidata` row gives a job role on the person's view, a `works_at` and a `studied_at` claim, a location claim, and no list claim
- loading the six old lists gives the same claims as before (the existing tests)

Each new test must be seen failing without the change it covers.

## Hand check

Run the scraper for real, then `uv run python scripts/seeds/check.py`, then load into a throwaway var folder (`mkvar.sh q8a`, `uv run fn-seed` with `FN_VAR` set to it) and paste: rows written, rows left out per reason, persons and claims added, how many rows have a place and how many of those got coordinates. Count, with no names in your report, how many gold picks in `data/gold/gold-set.json` have the same folded name as a row.

The data file `data/seeds/wikidata.jsonl` and the raw folder stay local: git ignores them. Leave them in the worktree and say where they are.

## Not doing

- Reading ORCIDs or other identifiers onto the seed person. The lookup task reads them from the item.
- Citizenship-only and birthplace-only people.
- Past jobs.
- The chamber and mission lists. They are separate tasks that add one line to the spec table.
