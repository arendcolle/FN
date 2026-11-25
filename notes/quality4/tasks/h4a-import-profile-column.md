# Task H4a: an import recognizes a person by the `profile` column of an FN export

## Goal

The one import stored on the owner's database is FN's own network export, imported again: 14 rows, 6 tied by ORCID and 8 asked "Same as <name>?". In all 8 the ignored `profile` cell is the address of the person asked about. Confirmed unticked, the file makes 8 new people (measured on a copy). This task reads the cell: a row whose `profile` is the address of a stored person with the row's name belongs to that person without a question. Identifiers still decide first. Owner: `importer.py` (brief H4a, panel decision D2 option b).

## What to build

### `src/fn/contracts.py`

After `IMPORT_COLUMNS` (line 1078): `PROFILE_COLUMN = "profile"`, with the one-line comment "The FN export's last column, the address of the person's page; the import reads it to recognize the person." `IMPORT_COLUMNS` stays the claim columns and the rows table's columns.

### `src/fn/exporter.py`

Line 6 imports `PROFILE_COLUMN`; line 10 and the dict key on line 61 use it in place of the literal `"profile"`. The file's bytes do not change.

### `src/fn/importer.py`

Constants next to `LABELS` (line 40). `LABELS` gains `PROFILE_COLUMN: "profile address"`.

```python
PROFILE_PATH = re.compile(r"/people/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?\Z", re.IGNORECASE)
NOT_PROFILE = "Its profile is not the address of a person page in FN, so FN does not use it to recognize the person."
NO_PROFILE = "Its profile is the address of a person FN does not hold, so FN does not use it to recognize the person."
OTHER_NAME = ("Its profile is the address of {name}, whose name is not the row's name, so FN does not use it to "
              "recognize the person.")
```

All 38,211 stored person ids are lowercase uuid4 (`store.py:352` is the only insert).

`table` (line 97): `if key in (*IMPORT_COLUMNS, PROFILE_COLUMN) and key not in columns:`. `profile` then leaves `ignored`.

New, after `identifiers` (line 118), with `from urllib.parse import urlsplit`:

```python
def profile_id(cell: str) -> str | None:
    """The person id in an FN profile address: http or https, a path ending in /people/<id>; else None.

    The host, port, query and fragment do not count, so an export from another host reads the same.
    """
    try:
        parts = urlsplit(cell.strip())
    except ValueError:
        return None
    match = PROFILE_PATH.search(parts.path) if parts.scheme.lower() in ("http", "https") else None
    return match.group(1).lower() if match else None
```

`rows_of` (line 157):

- After `holders`: `profiles = {n: profile_id(cells[PROFILE_COLUMN]) for n, cells in filled if PROFILE_COLUMN in cells}`, `canonical = store.canonical_ids([p for p in profiles.values() if p])`, and `people = store.get_persons(list({*holders.values(), *canonical.values()}))`. Add `file_profiles: dict[str, int] = {}`.
- After `seen[key] = n`: `cells.pop(PROFILE_COLUMN, None)`, so the duplicate check sees the cell and nothing after it does. Move `gkey = identity.key(name)` up to here.
- After the `owners` loop (line 185), before the clash check:

```python
        tied = None
        if n in profiles:
            tied = canonical.get(profiles[n] or "")
            if profiles[n] is None:
                notes.append(NOT_PROFILE)
            elif tied is None:
                notes.append(NO_PROFILE)
            elif identity.key(clean_name(people[tied].display_name)) != gkey:
                notes.append(OTHER_NAME.format(name=people[tied].display_name))
                tied = None
            else:
                owners.setdefault(tied, PROFILE_COLUMN)
```

The existing clash message then names an identifier's person and the profile's person ("Row 5's ORCID belongs to A and its profile address to B, so FN skips it.").
- The outcome chain gets a first branch. It also covers a profile that agrees with the row's identifier, since a search export writes both (brief ruling 5):

```python
        if person_id and (owners[person_id] == PROFILE_COLUMN or person_id == tied):
            outcome = "update" if person_id in file_profiles or people[person_id].list_status == "in_list" else "new"
            if person_id in file_profiles:
                notes.insert(0, f"Row {file_profiles[person_id]} has the same profile address, so FN adds it to the "
                                "same person.")
            file_profiles.setdefault(person_id, n)
        elif person_id:
            outcome = "update"
```

`_write` (line 273):

- Lines 288 to 290: `idents = [*found, Identifier(scheme="import", ...)]`. When `row.outcome in ("new", "update") and row.person_id`, call `store.add_identifier(row.person_id, i)` (store.py:853) for each and take `person = store.get_persons([row.person_id])[row.person_id]`; else `store.resolve_person(idents, row.name)` as today. Identifier rows take this branch too; their `person_id` is the canonical holder.
- Lines 291 and 292: also count the names of the held claims' organizations as held, with the comment "An FN export writes an employer as its organization's name, which the claim may word otherwise.":

```python
        claims = store.claims_of([person.id, *([into.id] if merging else [])], include_hidden=True)
        held = {(c.kind, fold(c.value)) for c in claims} | {
            ("affiliation", fold(o.name)) for o in store.get_orgs([c.org_id for c in claims if c.org_id]).values()}
```

Without this, the unchanged re-import adds 2 affiliation claims (measured).

### `src/fn/web/parts.py`

`IMPORT_NOTES` (line 700) gains `"profile": "The address of the person's page in FN, as an FN export writes it. FN recognizes the person by it."`.

### `src/fn/web/staff.py`

Line 827: `import_columns((*IMPORT_COLUMNS, PROFILE_COLUMN))`. Line 861 keeps `IMPORT_COLUMNS`, so the rows table gains no column. No CSS change.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Writing the profile address | `exporter.csv_text` |
| The column's name | `contracts.PROFILE_COLUMN` |
| Reading an id from the cell | `importer.profile_id` |
| Deciding which person a row belongs to | `importer.rows_of` |
| Writing a row's facts to its person | `importer._write` |
| The column's line on the upload page | `parts.IMPORT_NOTES` |

## Recorded answers, replay and stored searches (S6)

No prompt, model call or HTTP call changes. Every recorded answer and replay test stays valid. The import adds stored candidates to the network as Add does and leaves chips and the stored rank unchanged, so a search stored with version-1 chips keeps its order exactly.

## Inputs a real run will meet

Another host or port, `http`, an upper-case id, a trailing slash, a query and a fragment all read. A `/searches/<id>` address, a bare id, `ftp://`, `http://[::1` (ValueError), and an apostrophe before `https` give `NOT_PROFILE`. An unknown uuid gives `NO_PROFILE`, and an empty cell gives no note. A merged id counts as its person, checked against that person's name. A case or middle-initial difference still matches. Two rows with one address tie to one person, counted once as new. A 5 MB file of 60,000 addresses previews in 1.4 s on the scratch copy.

## Tests (each must fail without the change)

In `tests/test_importer.py`, a new class `ProfileTest(ImporterTest)` with header `name,orcid,email,organization,profile`, "Ann Fictive", "Bo Madeup", "Cy Invented":

1. `test_a_profile_address_ties_the_row_on_any_host`: the read forms above give `update` with that person, no question; confirm adds no person or claim.
2. `test_a_profile_outside_the_network_adds_that_person_as_new`: row 2 is `new` with Bo's id, row 3 with the same address is `update` with the same-profile note; after confirm Bo is `in_list` and the person count is unchanged. Subtest: Bo, given an ORCID in setup, with his ORCID and his own address is `new`, and a second such row is `update`.
3. `test_a_merged_record_counts_as_its_person`.
4. `test_a_cell_that_is_no_profile_address_is_said_and_ignored`: each unread form gives its sentence and the name rules; `ignored_columns == []`. One subtest: a file with `profile` and no `name` raises `NO_NAME` (this one also passes today).
5. `test_a_changed_name_does_not_use_the_profile`: "Ann Other" is `new` with `OTHER_NAME` naming Ann; "ann fictive q." is `update`.
6. `test_an_identifier_decides_first_and_a_clash_skips_the_row`: Cy's ORCID with Cy's address is `update` without a note; Cy's ORCID or email with Ann's address is skipped with the exact clash sentence.
7. `test_an_employer_written_as_its_organizations_name_adds_no_claim`: a claim "Example Labs Inc" linked to org "Example Labs" (`store.upsert_org`); a profile row with organization "Example Labs" adds no claim.
8. `test_a_five_megabyte_file_of_profile_addresses_previews_in_under_five_seconds`: its first row is `update`.

In `tests/test_exporter.py`: `test_an_unchanged_export_imports_again_without_a_question_or_a_change` (no `name_match`; persons, merges and claims unchanged) and `test_an_email_typed_into_an_export_row_goes_to_that_person`.

In `tests/test_import_pages.py`: `test_the_upload_page_explains_the_profile_column`, with the exact sentence.

## Existing tests that change, approved by the lead

- `test_import_pages.py` `test_the_upload_page_lists_every_import_column`: old, the table rows equal `IMPORT_COLUMNS` with name "Yes"; new, they equal `(*IMPORT_COLUMNS, "profile")`, `profile` "No".

With the change applied in a scratch copy, the other 1,126 tests pass unchanged. No other existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. Then `V=$(mkvar.sh h4a)` twice (one copy per side) and save as `$S/hand.py` outside the repo:

```python
from datetime import UTC, datetime
from fn import config, importer
from fn.store import Store
from fn.worker import Worker
settings = config.from_env(); store = Store(settings.db_path); store.migrate()
worker = Worker(store, settings, llm=None, http=None)
COUNT = ("SELECT (SELECT count(*) FROM persons), (SELECT count(*) FROM persons WHERE merged_into IS NOT NULL), "
         "(SELECT count(*) FROM claims), (SELECT count(*) FROM persons WHERE list_status = 'in_list' AND merged_into IS NULL)")
tally = lambda: tuple(store.conn.execute(COUNT).fetchone())
(text,) = store.conn.execute("SELECT text FROM imports ORDER BY uploaded_at LIMIT 1").fetchone()
lines = text.split("\n")
at = lines[0].lstrip("﻿").strip().split(",").index("email")
cells = lines[1].split(","); cells[at] = "made.up@example.org"
for label, body in (("again", text), ("email", "\n".join([lines[0], ",".join(cells), *lines[2:]]))):
    before, now = tally(), datetime.now(UTC)
    iid = importer.upload(worker, f"{label}.csv", body.encode(), now)
    print(label, importer.get(store, iid).counts)
    importer.confirm(worker, iid, set(), now)
    print(label, "persons, merged, claims, network:", before, "->", tally())
worker.shutdown()
```

Run `FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run python $S/hand.py`, once from a worktree pinned to main and once from this one, each on its own copy. Measured by the planner:

- Main: `update` 6, `name_match` 8; persons +8, network 14 to 22.
- Branch, "again": `update` 14, nothing else; persons, merges, claims and network unchanged.
- Branch, "email": `update` 14; claims +1, the typed email.

## Not doing

Matching on name plus details. Storing a "different person" answer. More than one namesake per row. Any change to the question's layout (H4b). An undo for a whole import. Reading an apostrophe before an address. Making an identifier holder outside the network count as new when the row has no profile. A note when `add_identifier` returns False because an earlier row's new person holds the identifier (follow-up).
