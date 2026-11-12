# Build plan for the seven staff flows

2026-11-12 · follows [design.md](design.md) version 2 · progress in [progress.md](progress.md)

**Goal.** The owner can walk each of the seven flows in the [story map](../design/story-map.md) end to end on the local server, and FN logs what later work on speed and result quality needs.

**Approach.** Fourteen tasks. Each ends in something to run by hand, gets its own branch and pull request, and merges before the next task that touches the same files starts. One builder agent does a task from its task file in [tasks/](tasks/), an Opus reviewer checks the diff against that file, and the manager reads the diff, runs the tests and the hand check, then merges.

## Order and what each task ends in

| # | Task | Ends in | Needs |
| --- | --- | --- | --- |
| T1 | Split `web/app.py` by job, move only (merged, PR #6) | Every page byte-identical to `main` | |
| T2 | A place text resolves to the right city (merged, PR #7) | "Bay Area" gives San Francisco | |
| T3 | Fayat scholars as a seed list (merged, PR #5) | 95 people load from the public page | |
| T4 | Network core, no pages | A test adds, merges, skips and undoes on a real database copy | T1 |
| T5 | New parts in the design system, then `fn.css` | The design system shows every part the pages below use | |
| T6 | View models and the claim format on cards | A results card shows "Works at … 2019–2024" and no raw record line | T4 |
| T7 | Network page, home, header, all searches, map popup | `/people` lists the network beside the map | T5, T6 |
| T8 | Person page | `/people/{id}` shows a person, edits a contact detail, removes a fact | T7 |
| T9 | Import and export | Upload a CSV, confirm, see the people on `/people`, download them again | T2, T8 |
| T10 | Add, Skip, Same person and Undo on result cards | A card's Add puts the person on `/people` | T8, T9 |
| T11 | The ranker cut and "Show more" | A stored search shows 50 of about 500 kept people | T10 |
| T12 | People appear while a search runs | A replayed search shows people after its first lane | T11 |
| T13 | Request log, `/debug/stats`, `/debug/feedback` | The owner sees lane times and which ranks got added | T12 |
| T14 | Flow tests, browser walk, documents | Seven flows pass in `tests/test_flows.py` and in a browser | all |

T2, T3 and T5 touch no file the others touch and run beside them.

## File map

| File | Responsible for | Tasks |
| --- | --- | --- |
| `src/fn/migrations/006_network.sql` | Columns on `persons`, `claims` and `candidates`; tables `events`, `not_same`, `imports` | T4 |
| `src/fn/contracts.py` | New Literals, `Event`, view models, the CSV column list | T4, T6, T7, T8, T9 |
| `src/fn/store.py` | SQL for all of it | T4, T7, T9, T11, T13 |
| `src/fn/network.py` (new) | Membership rules and the events | T4 |
| `src/fn/resolve.py`, `src/fn/rank.py`, `src/fn/gold.py` | Canonical ids, card splits, section from hits; the cut; a cut pick reported as lost at rank | T4, T11 |
| `src/fn/present.py` (new in T1) | View models | T6, T7, T8 |
| `src/fn/importer.py`, `src/fn/exporter.py` (new) | CSV in and out | T9 |
| `src/fn/search.py`, `src/fn/worker.py` | Publish steps, going on after a failed lane | T12 |
| `src/fn/stats.py` (new) | Timings and feedback read models | T13 |
| `src/fn/geo.py`, `data/place_aliases.csv` | Place lookup | T2 |
| `src/fn/web/staff.py`, `web/parts.py`, `web/debug.py`, `web/app.py`, `web/html.py` | Routes and HTML; the header links are in `html.py` | T1, T6 to T13 |
| `src/fn/web/static/fn.css`, `tokens.css` | Byte copies of the design system's files | T5 |
| `src/fn/web/static/map.js`, `results.js` (new) | Map popup and row link; the poll and in-place card updates | T7, T10, T12 |
| `tests/test_network.py`, `test_present.py`, `test_importer.py`, `test_exporter.py`, `test_stats.py`, `test_flows.py` (new) | One per new module, and the flows | T4 to T14 |

## Change to the search steps

```
search.run
  parse
  lane:seeds
+ publish            resolve + rank + save over the lanes so far
  lane:openalex
+ publish
  lane:web
+ publish
  lane:linkedin
  resolve            - a lane error no longer stops here
  rank               + sets cut_reason
  save
```

## Interfaces between tasks

Names and types are fixed here so a later task can rely on them. A builder who has to change one stops and reports it.

### T4 provides

`contracts.py`:

- `ClaimKind` gains `email` and `phone`. `SourceKind` gains `staff`. `IdentifierScheme` gains `email` and `import`.
- `EventKind = Literal["add", "skip", "merge", "not_same", "reject_claim", "edit_contact", "remove", "import", "export", "undo"]`, `CutReason = Literal["no_belgian_evidence"]`, `AddedVia = Literal["search", "import", "profile"]`.
- `Person.merged_into: str | None`, `Person.merged_at: datetime | None`, `Person.seen_at: datetime | None`.
- `Claim.first_seen_at: datetime | None`, `Claim.rejected_at: datetime | None`.
- `Candidate.hit_person_ids: list[str] = []`, `Candidate.cut_reason: CutReason | None = None`.
- `Event`: `id`, `at`, `kind`, `person_id`, `other_person_id`, `search_id`, `rank`, `section`, `import_id`, `claim_id`, `undoes`, `detail: dict`, `user_id: None`.
- `Source` accepts an `fn:` URL for the kinds `import` and `staff`.

`store.py`:

- `canonical_ids(person_ids: list[str]) -> dict[str, str]`: record id to canonical id.
- `records_of(person_id: str) -> list[Person]`: the canonical record first, then the merged ones.
- `claims_of(person_ids: list[str], include_hidden: bool = False) -> list[Claim]`: the claims of each id's whole person, once, with `person_id` set to the canonical id, also when the list names two records of one person. A claim of a merged record gets as `first_seen_at` the later of its own and the record's `merged_at`, so facts that arrive through a merge count as new. Without `include_hidden` it leaves out rejected claims and claims with the same person, kind and folded value as a rejected one, unless a `staff` claim of that value is newer than the rejection.
- `match_claims` leaves out rejected claims and the kinds `email` and `phone`.
- `upsert_claim(draft, at: datetime | None = None)` sets `first_seen_at` to `at` when it inserts. Lanes pass `ctx.now()` and `network.py` passes its `now`, so every time the new-fact rules compare comes from the caller's clock, in aware UTC. Without `at` it uses the current UTC time.
- `save_candidates` and `list_candidates` write and read `hit_person_ids` and `cut_reason`.
- `identifiers_of(person_ids: list[str]) -> dict[str, list[Identifier]]`, `add_identifier(person_id, identifier) -> bool` (false when another person holds it) and `remove_identifier(person_id, identifier)`.
- Small writers, each one statement: `set_list_status`, `set_merged_into`, `set_seen`, `set_claim_rejected`, `add_not_same`, `remove_not_same`, `add_event`. Readers: `get_event`, `events_of(person_id)`, `not_same_pairs(person_ids)`, `network_by_group_key() -> dict[str, list[str]]`.

`network.py`, every function takes `store` first and `now: datetime` by keyword, and writes one event:

- Every function accepts any record's id and works on the canonical id, because a stored search keeps ids that a later merge made non-canonical.
- `add(store, hit_person_ids, *, via: AddedVia, now, search_id=None, rank=None, section=None, import_id=None, not_same_as: list[str] = ()) -> Event`. Merges the hits without a conflicting identifier into the first hit, sets the person `in_list` and sets `seen_at` to now, so only later facts count as new. `not_same_as` stores pairs for "Add as new". `Event.detail` lists `merged` and `left_apart`.
- `skip(store, hit_person_ids, *, now, search_id=None, rank=None, section=None) -> Event`
- `remove(store, person_id, *, now) -> Event`: back to `candidate`.
- `merge(store, person_ids: list[str], into_id, *, now, search_id=None, rank=None, section=None) -> Event`, which serves "Same person" on a card and on the profile and stamps `merged_at`, and `not_same(store, person_id, other_id, *, now) -> Event`, which also separates a merged record.
- `reject_claim(store, claim_id, *, now) -> Event`
- `set_contact(store, person_id, kind, value, *, now, replaces: str | None = None) -> Event`. A typed email also becomes the person's `email` identifier, so a later import of that address finds the person. It is refused with a sentence when another person holds the address.
- `record_import(store, import_id, *, now, detail) -> Event` and `record_export(store, *, now, detail) -> Event`, so `network.py` stays the only writer of events.
- `undo(store, event_id, *, now) -> Event`; raises `UndoRefused` when a later event touched one of its persons.
- `mark_seen(store, person_id, *, now) -> None`: no event.
- `name_matches(store, hit_person_ids) -> list[str]`: network persons with the same group key, no shared person and no `not_same` row.
- `possible_matches(store, person_id) -> list[str]`: same-key records that are not merged and not declared different.

`resolve.run` reads the canonical ids, the not-same pairs and the ORCIDs for the hit persons and for every same-name record `person_ids_by_group_key` returns. `resolve.group` maps hits and the stored same-name records to canonical ids, drops a same-name record that is already in the entry, and splits on `not_same` pairs and different ORCIDs. `rank.fuse` takes the section from the hit ids and fills `Candidate.hit_person_ids`. An entry stored without hit ids counts its first person as the hit. `tests/test_rank.py::test_sections_number_apart` changes on purpose: its network entry gets `hit_person_ids`, and a new case shows that an `in_list` record no lane hit does not make a card a network card.

### T6 provides

`contracts.py` view models, all frozen:

- `QuoteView(text, label, href, date)`
- `ClaimView(claim_id, kind, what, years, quote: QuoteView | None, label, href, date, is_new)`. `what` reads "Studied at KU Leuven". `quote` is set only when the source is prose (`page`, `seed_page`, `vendor_page`); a record, import or staff source gives the citation without a quote.
- `OrgView(org, years)`
- `PersonView(person_id, name, role, employer, place, lat, lon, orgs: list[OrgView], more_orgs, evidence: ClaimView | None, status: ListStatus, added: str | None, new_facts, email, phone)`

`present.py`:

- `person_views(store, groups: list[list[str]], today: date) -> list[PersonView]`: one view per group of person ids.
- `claim_view(claim, source, org, seen_at) -> ClaimView`: the one place that words a claim.

`web/parts.py`: `person_card(view, actions)`, `quote(view)`, `claim(view)`.

### T7 provides

- `NetworkFilter(text: str = "", import_id: str | None = None, new_only: bool = False)`. The text box is the only filter staff type. `import_id` and `new_only` are tokens set by links: "From import contacts.csv" after an import, and "New facts only" when someone has new facts.
- `store.list_network(flt: NetworkFilter, limit: int | None) -> tuple[list[str], int]`: person ids newest added first, and the total.
- `present.network_view(store, flt, limit, today) -> NetworkView(people: list[PersonView], total, not_on_map)`
- `present.geo(people: list[PersonView]) -> dict`: GeoJSON for `map.js`.
- Routes `/people`, `/api/people/geo`, `/searches`. `map.js` links any element with `data-person` to its dot and opens the popup at every width.
- `parts.network_row(view)`, `parts.filter_bar(flt, total, not_on_map)`.

### T8 provides

- `present.profile(store, person_id, today) -> ProfileView(person: PersonView, contact: list[ClaimView], facts: list[tuple[str, list[ClaimView]]], removed: list[ClaimView], found_as: list[RecordView], possible: list[PersonView])`
- The Source page shows an import or staff source by its label, with no outside link, through the same `present.py` mapping.
- Routes: `GET /people/{id}` (a merged record's id redirects to its person), `POST /people/{id}/add`, `/remove`, `/contact`, `/merge`, `/not-same`, `POST /claims/{id}/reject`, `POST /events/{id}/undo`. Each POST redirects back to the page it came from.

### T9 provides

- `contracts.IMPORT_COLUMNS: tuple[str, ...]`, `ImportRow(n, name, outcome: Literal["new", "update", "name_match", "skipped"], person_id: str | None, message: str)`, `ImportPreview(import_id, filename, rows, ignored_columns, counts: dict[str, int])`.
- `importer.create(store, filename: str, raw: bytes, now) -> str`, `importer.preview(store, http, import_id) -> ImportPreview`, `importer.confirm(store, http, import_id, merge_rows: set[int], now) -> ImportPreview`.
- `exporter.csv_text(views: list[PersonView]) -> str`
- Routes `/imports/new`, `POST /imports`, `/imports/{id}`, `POST /imports/{id}/confirm`, `/people/export.csv`. The export route is registered before `/people/{id}`, or the profile route would answer it.
- The upload is `multipart/form-data` and FN has no multipart library. `POST /imports` reads the body from `request.stream()`, stops past 5 MB, and parses it with `email.parser.BytesParser(policy=email.policy.HTTP)` on the Content-Type header plus the body.

### T10 to T13 provide

- T10: `POST /searches/{id}/people/{person_id}/add`, `/skip` and `/same`, `/searches/{id}/export.csv`, and `results.js`, which sends those forms with `fetch` and swaps the returned card in place. `store.list_candidates(search_id, include_skipped=False)` leaves out a candidate whose hit persons are all `skipped`, except the ones skipped on this search, which show as the one-line card. `present.results(store, search, shown, show_skipped, today) -> ResultsView`.
- T11: `store.list_candidates(search_id, include_skipped=False, kept_only=True)`, `?shown=` on the results page, `gold.py` reports a cut pick as lost at rank.
- T12: step `publish` with `PublishOut(count)`, `GET /searches/{id}/status -> {status, people, version}`, `GET /searches/{id}/cards` for the list fragment.
- T13: `stats.steps(store, last: int) -> list[StepStat]`, `stats.feedback(store, last: int) -> list[SearchFeedback]`, the request log line.

## Inputs a real user will send

Each has a test in the task that owns the code.

| Input | Expected | Task |
| --- | --- | --- |
| A CSV with semicolons, a byte-order mark, Windows-1252 text, headers in capitals or with spaces | Read correctly | T9 |
| A file with no `name` column, an empty file, a header only, an `.xlsx` file | Refused with a sentence that lists the expected columns | T9 |
| Blank rows, a row with no name, the same row twice in one file | Skipped rows are counted with the reason; an identical row is skipped; two rows with one name and different details become two people, and the preview says so | T9 |
| A row whose LinkedIn URL and ORCID belong to two different people | Skipped, with a sentence naming both | T9 |
| Confirm pressed twice, or again after Back | The second Confirm changes nothing | T9 |
| A tab-separated or UTF-16 file from a spreadsheet's "Unicode text" export | Refused with the expected-format sentence | T9 |
| A cell starting with `=`, a cell with a line break, a 10 MB file, 5,000 rows | Text stays text; files over 5 MB are refused; 5,000 rows import | T9 |
| A LinkedIn URL without `www`, with a trailing slash or a query string; an ORCID as a bare id; an email with capitals | The same person as the canonical form | T9 |
| A city FN cannot find, a state as a name or a code | The person imports without a dot and the preview says so | T9 |
| Add pressed twice, or in two tabs | One person, one event | T4, T10 |
| Undo after a later decision on the same person | Refused with a sentence | T4, T8 |
| Skip, then Add from another search | Added; the skip is gone | T4 |
| Filter text with a quote, `%`, `_`, 500 characters, only spaces | Treated as text; spaces mean no filter | T7 |
| `/people/{id}` for an unknown id, for a merged record, for a person with 2,000 facts | 404; a redirect; the page groups facts and stays usable | T8 |
| An email without `@`, an empty value, 300 characters, an email another person holds | Refused with a sentence under the field | T4, T8 |
| `?shown=` and `?limit=` that are negative, huge or not a number | The default | T7, T11 |
| The status of an unknown search | 404 | T12 |

## Risks

- **The migration is a one-way door for the owner's database.** The manager copies `var/fn.sqlite3` with `sqlite3 .backup` before the first start on the new code. T4 times the migration on a copy of the 509 MB file.
- **The cut hides people.** T11 is rejected when it cuts one of the 12 gold picks that reach the ranker, when fewer than 4 picks stand in the first 50 or fewer than 6 in the first 100, or when the median kept count falls by less than 40%.
- **A one-click Add can merge two different people.** Hits with conflicting identifiers stay apart, the profile shows "Found as" with "Not this person", and every merge is a pointer that Undo reverses.
- **Imports change what the seed lane finds.** The gold runner pins its database copy.

## Proof that the whole change is done

1. `uv run python -m unittest` passes with every failure named.
2. `tests/test_flows.py` walks the seven flows through the app on a seeded database.
3. A browser walk on a copy of the owner's database, with a screenshot per flow: import a CSV and see the people on the map; search (replayed) and see network people first; add, merge and skip from a result; see a new fact marked on a profile and remove it; open a profile from the map; reopen an old search and see who was added; export and re-import the file.
4. Against `main`: `/people`, `/people/{id}`, `/imports/new` and `/people/export.csv` return 404 there and pages here.

## Not doing

The list is in [design.md](design.md#not-doing).
