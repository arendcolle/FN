# Task T9a: the import core, with no pages

Branch `feat/importer-core`. After this task FN can take the bytes of a CSV file, say what it would do with every row, and on confirm put the people in the network. The upload page and the preview page come in a later task and call the three functions this one provides.

Read first: [design.md](../design.md) "Imports", "Claims" and "Events"; the plan's ["T9 provides"](../plan.md#t9-provides) and its table of inputs a real user will send; `research/store.md`; `src/fn/network.py`; `src/fn/orgjob.py` for how a job with steps runs; and the import strings in `notes/e2e/design-system/STRINGS.md`.

## What the import does

The expected columns are `name` (required), `email`, `phone`, `organization`, `role`, `city`, `state`, `country`, `linkedin_url` and `orcid`. They live in `contracts.IMPORT_COLUMNS`.

### Reading a file

- Decode as UTF-8 with or without a byte-order mark, else as Windows-1252. A UTF-16 file (it starts with `FF FE` or `FE FF`) is refused.
- The delimiter is a comma or a semicolon, whichever the header row has more of. A tab-separated file is refused. Quoted cells may hold commas, semicolons and line breaks (use the `csv` module).
- Headers are matched by name after trimming, lower-casing and turning spaces into underscores, in any order. Other columns are ignored and named in the preview. A file without a `name` column, an empty file, a file with a header and no rows, a file over 5 MB and a file that is not text (an `.xlsx` starts with `PK`) are refused.
- A refusal raises `ImportRefused` with one sentence for staff, word for word from STRINGS.md where it has one.

### What happens to a row

| Row | Outcome | What confirm does |
| --- | --- | --- |
| Every cell empty | not counted | nothing |
| No name | `skipped`, "Row 14 has no name, so FN skips it." | nothing |
| The same cells as an earlier row | `skipped`, says which row | nothing |
| Its LinkedIn URL, ORCID and email belong to two different people | `skipped`, with a sentence | nothing |
| An identifier belongs to one person | `update` | adds what is new to that person and adds them to the network if they are not in it |
| No identifier match, and its name has the group key of someone in the network | `name_match`, with that person's id | a new person; merged into the match only when the row's number is in `merge_rows` |
| Anything else | `new` | a new person in the network |

- Identifiers: the LinkedIn URL in the form the LinkedIn lane stores (move `canonical` out of `lanes/linkedin.py` into `contracts.py` as `profile_url`, and let the lane import it; a module does not call a lane's internals), the ORCID as `https://orcid.org/0000-0000-0000-0000` (accept the bare id and the URL), and the email trimmed and lower-cased under the scheme `email`. Every row's person also gets `import:<import id>:<row number>`, so a row with no identifier is a person of its own. A name is never an identifier.
- The row's source is a record source of kind `import` (extend `contracts.record_source`) with one `column: value` line per filled cell, the URL `fn:import/<import id>#row-<n>`, the title "<file name>, row <n>", and the import's day as source date. Its id must differ per import and row.
- Claims, each quoting its own line, dated the import's day with date method `sheet_date`: `organization` is an affiliation with relation `works_at` and the org id `orgs.org_id` finds; `role` is a claim of kind `role`; `email` and `phone` are claims of those kinds; `city`, `state` and `country` give one location claim with relation `lives_in`, the value the filled parts joined by ", ", and the coordinates `geo.locate_city` finds. A row with no city gets no location claim. A place FN cannot find gives a claim without coordinates, and the row's message says the person will not be on the map.
- For a person who already exists, a cell whose value they already hold (same kind, same value after trimming and case-folding) writes nothing. A blank cell clears nothing.
- People join the network through `network.add(..., via="import", import_id=...)`, ticked name matches through `network.merge`, and the import writes one event through `network.record_import` with the counts. `importer.py` never sets `list_status` itself.

### The three entry points

- `importer.upload(worker, filename: str, raw: bytes, now) -> str`: checks the file, stores an `imports` row with status `preview` and the decoded text, computes the preview and stores it in the row's summary. Returns the import id.
- `importer.get(store, import_id) -> ImportPreview | None`: the stored preview with the import's status and file name.
- `importer.confirm(worker, import_id: str, merge_rows: set[int], now) -> ImportPreview`: writes everything in one transaction, sets the status to `confirmed` and stores the final preview. A second confirm of a confirmed import changes nothing and returns the stored preview. A name match whose person left the network since the preview is imported as a new person, and its message says so.
- `importer.discard(store, import_id) -> None`: sets the status to `discarded`. It is not an event.

The preview and the confirm each run as a step of a job (a `searches` row of kind `job`, as `orgjob.refresh` does), executed in the calling thread, so the place lookup can use the step's HTTP client and the calls, the duration and any error show on the debug pages. Do not start a second worker thread per import: check how `Worker.execute` can run a job in the calling thread with the app's existing worker.

`contracts.py` gets `ImportRow(n, name, outcome, person_id, message, cells)`, `ImportPreview(import_id, filename, status, rows, ignored_columns, counts)` and the step models. `store.py` gets the readers and writers for `imports`.

## Tests

New `tests/test_importer.py`, with made-up people. One case per row of the plan's input table that names T9, and these:

1. A comma file and a semicolon file with the same content give the same preview. A byte-order mark and Windows-1252 accents read correctly.
2. Headers in capitals and with spaces match. Extra columns are listed as ignored.
3. Each refusal: no `name` column, empty, header only, `.xlsx` bytes, UTF-16, tabs, over 5 MB.
4. Each row outcome of the table above.
5. Confirm puts new people in the network with their claims, each claim quoting its line in the row's source; the location has coordinates for "Cambridge, MA, USA" (use the geo fixture) and none for an unknown city.
6. A second import of the same file: rows with an identifier are `update` and write no new claim; rows without one are `name_match`; with every such row in `merge_rows`, confirm leaves the same number of people in the network.
7. A LinkedIn URL without `www`, with a trailing slash and with a query string finds the person a canonical URL created. An ORCID as a bare id finds the person the URL form created. An email in capitals finds the person.
8. Confirm twice changes nothing the second time. Confirm after discard raises.
9. The import event holds counts and no contact value.
10. A cell starting with `=` is stored as the text it is.

Each test must fail without the change.

## Hand check

Write a CSV of twelve made-up people into your temp folder, with semicolons, one row without a name, one duplicate row, two rows with a LinkedIn URL and cities in three US states and Belgium. On a throwaway copy of the owner's database, run `upload`, print the preview's counts and each row's outcome and message, run `confirm`, and print how many people are in the network, how many have coordinates and the job's steps with their durations. Run the same file a second time and print the outcomes.

## Not in this task

Pages, routes and the multipart upload (`web/`), the export, view models. Another task is rewriting `present.py`, `web/staff.py` and `web/parts.py`: do not touch them.

## Rules for this task

- Run `uv run python -m unittest` before you start (300 tests pass) and when you finish.
- No new dependency. Only `store.py` runs SQL. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
