# Task T9b: the import pages and the CSV export

Branch `feat/import-export-pages`. After this task staff upload a CSV file, check what FN will do with it, confirm, land on the Network page with the new people, and download the network as a CSV file that imports again.

Read first: [design.md](../design.md) "Imports" and "Pages"; the plan's ["T9 provides"](../plan.md#t9-provides) and its table of inputs; the design system parts Field, DataTable, ImportSummary, Banner and FilterBar; the mockups `page-import.html` and `page-import-preview.html`; the Import strings in `notes/e2e/design-system/STRINGS.md`; and `src/fn/importer.py`, `src/fn/present.py`, `src/fn/web/staff.py` and `src/fn/web/parts.py` as they are now.

## What changes

### 1. Import pages

- `GET /imports/new`: the upload page: the file Field with its hint, Upload, and the table of the columns FN reads, built from `contracts.IMPORT_COLUMNS` with the descriptions in STRINGS.md.
- `POST /imports`: reads the upload and calls `importer.upload`. The body is `multipart/form-data` and FN has no multipart library: read it from `request.stream()`, stop past 5 MB, and parse it with `email.parser.BytesParser(policy=email.policy.HTTP)` on the Content-Type header plus the body. No file chosen, a file over the cap and every `ImportRefused` re-render the upload page with the sentence under the field and status 400. On success it redirects (303) to the preview.
- `GET /imports/{id}`: the preview from `importer.get`: the title "Check <file>", the lead, the counts in words with a count of 0 left out, the notes on skipped rows and ignored columns, the name matches with their unticked boxes and the header box, the button "Import 15 people" and Discard, then the rows table with what happens to each row. The table shows the first 200 rows and says how many more there are. An import that is confirmed or discarded shows what happened and no buttons. Unknown id: 404.
- `POST /imports/{id}/confirm`: the ticked rows arrive as `merge` fields. Calls `importer.confirm` and redirects (303) to `/people` with a Banner: "15 people imported from contacts.csv." and the link "Show them", which is `/people?import=<id>`. A second confirm changes nothing and redirects the same way.
- `POST /imports/{id}/discard`: calls `importer.discard` and redirects to `/people` with the Banner "contacts.csv discarded. Nothing was imported."
- The header box "All of these are the same person" works without JavaScript: it is a second submit choice or a field the confirm route reads as "every name match". Do not add a script for it.
- The Network heading gets the Import link, and the empty-network Notice gets its Import button.

### 2. Export

- `exporter.py` (new): `csv_text(store, people: list[PersonView]) -> str`. One row per person. The columns are `contracts.IMPORT_COLUMNS` in their order, so the file imports again, then `belgian_organizations` (each with its years, joined by "; "), `added` and `profile` (the address of the Person page). `organization` is the employer. `city`, `state` and `country` come from the person's place text split on commas, with the later parts sorted into state or country through `geo`'s alias table; a place of one part is the city. `linkedin_url` and `orcid` come from the person's identifiers. The text starts with a byte-order mark so a spreadsheet reads the accents, uses commas and the `csv` module's quoting, and a cell that starts with `=`, `+`, `-` or `@` gets a leading apostrophe.
- `GET /people/export.csv`: the same query as `/people` without the limit, as a download named `fn-network-<date>.csv`. Register it before `/people/{id}`, or that route answers it. It writes the export event through `network.record_export` with the count and whether a filter was on.
- The count line on the Network page and on Home ends with the Export link: "Export" without a filter, "Export these 9" with one, nothing at 0 people.

### 3. Request log

Each of these routes puts its counts in `request.state.facts`: rows read, outcome counts, people exported.

## Tests

New `tests/test_import_pages.py` and `tests/test_exporter.py`, with made-up people:

1. The upload page lists every column of `IMPORT_COLUMNS`.
2. A posted CSV (build the multipart body by hand in the test) redirects to a preview that shows the counts, the name matches and the rows.
3. No file, an `.xlsx`, a file with no `name` column and a body over 5 MB each give 400 with the sentence under the field. The oversized body is not read past the cap.
4. Confirm adds the people, redirects with the Banner, and `/people?import=<id>` lists them. Confirm twice adds nobody twice. Discard changes nothing and shows its Banner.
5. A ticked name match merges; an unticked one becomes a new person; the header choice merges all.
6. The preview of a confirmed import has no buttons. Unknown id: 404.
7. Export: the header row starts with the import columns; a person's row has the right cells; a filter narrows the rows; the count line's number equals the number of rows for the same query.
8. Export then import: the exported file uploads without a refusal, and confirming it with every name match ticked leaves the same number of people in the network.
9. A cell starting with `=` is exported with a leading apostrophe. Accents survive. A name with a comma and a quote survives.
10. `/people/export.csv` is not answered by the profile route.

Each new test must fail without the change.

## Hand check

With the Playwright browser tools at 1280 px on a throwaway copy of the owner's database: write a CSV of twelve made-up people (semicolons, one row without a name, cities in three US states and Belgium), upload it through the page, read the preview, confirm, open "Show them", check the people have dots on the map, press Export, and open the downloaded file. Report each step and paste the first three lines of the exported file. Then upload the exported file and report the preview's counts. Save screenshots of the upload page and the preview at 1280 px and 390 px in your temp folder and give the paths.

## Not in this task

Excel files, a mapping step, an undo of an import, the export of a search (it comes with the result card actions).

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- `web/` calls `importer.py`, `exporter.py`, `network.py` and `present.py` and writes nothing to the store itself. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
