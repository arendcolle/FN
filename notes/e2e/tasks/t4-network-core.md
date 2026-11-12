# Task T4: the network core, with no pages

Branch `feat/network-core`. This task builds the data model and the rules for who is in the network. No page changes. The later tasks build pages on the functions this one provides, so their names and types are fixed in [the plan](../plan.md#t4-provides).

Read first: [design.md](../design.md) sections "The model" and "What staff decisions do", then `research/store.md` and `research/lanes-rank.md` for how the code works today.

## What changes

### 1. Migration `src/fn/migrations/006_network.sql`

Plain SQL, like the other migrations. No CHECK constraints: vocabularies are Literals in `contracts.py`.

- `persons`: add `seen_at TEXT` and `merged_at TEXT`; indexes on `list_status` and on `merged_into`.
- `claims`: add `first_seen_at TEXT` and `rejected_at TEXT`. Old rows keep both empty.
- `candidates`: add `hit_person_ids_json TEXT NOT NULL DEFAULT '[]'` and `cut_reason TEXT`.
- New table `not_same (person_id, other_person_id, at)`, primary key on the pair. Store each pair once, smaller id first.
- New table `events`: `id` primary key, `at`, `kind`, `person_id`, `other_person_id`, `search_id`, `rank`, `section`, `import_id`, `claim_id`, `undoes`, `detail_json NOT NULL DEFAULT '{}'`, `user_id`. Indexes on `(person_id, at)` and on `search_id`.
- New table `imports`: `id` primary key, `filename`, `uploaded_at`, `status`, `text`, `summary_json NOT NULL DEFAULT '{}'`, `confirmed_at`. T9 uses it; this task only creates it.
- Fill `candidates.hit_person_ids_json` for stored searches from the stored resolve output: each entry in the `ResolveOut` payload of a search's `resolve` step has `person_ids` and `hit_person_ids`, and a candidate's `person_id` is the entry's first person id. Do it in SQL with `json_each`, through a temporary table with an index, not a correlated scan per candidate. A candidate with no match keeps `'[]'`.

Time the migration on a copy of the owner's database (509 MB) and report the seconds. It must finish in under a minute.

### 2. `contracts.py`

As listed under "T4 provides" in the plan. Keep `CONTRACTS_VERSION` at 2: every new field has a default. `Person.merged_into` becomes `str | None`. `Source` accepts a URL with the `fn:` scheme when `kind` is `import` or `staff`, and still refuses it for every other kind.

### 3. `store.py`

- `canonical_ids(person_ids) -> dict[str, str]`: each id to its canonical id (itself when not merged). Ids that do not exist are left out.
- `records_of(person_id) -> list[Person]`: the canonical record of that id first, then the records merged into it, by id.
- `claims_of(person_ids, include_hidden=False) -> list[Claim]`: for each id, the claims of its whole person (the canonical record and every record merged into it), each returned with `person_id` set to the canonical id, in the order it has today. A person asked for twice, through two of its records, gives its claims once. A claim of a merged record is returned with `first_seen_at` set to the later of its own and the record's `merged_at`, so facts that arrive through a merge count as new. Without `include_hidden` it leaves out every claim with `rejected_at` set, and every claim of the same person with the same kind and the same value (trimmed, case-folded) as a rejected one, unless a claim of that value from a `staff` source has a `first_seen_at` later than the rejection.
- `match_claims` leaves out rejected claims and the kinds `email` and `phone`.
- `upsert_claim(draft, at: datetime | None = None)` sets `first_seen_at` to `at` when it inserts a claim, and leaves it alone on a conflict. Without `at` it uses the current UTC time. Every lane call passes `ctx.now()` (`lanes/openalex.py`, `lanes/linkedin.py`, `lanes/web.py` through `extract`, wherever a lane upserts a claim), and `network.py` passes its `now`. The new-fact rule, the merge rule and the "staff claim newer than the rejection" rule compare these times, so they must come from the caller's clock, as aware UTC datetimes, and the tests pass fixed times.
- `get_persons` returns `merged_into`, `merged_at` and `seen_at`.
- `save_candidates` and `list_candidates` write and read `hit_person_ids` and `cut_reason`.
- One-statement writers: `set_list_status(person_id, status)`, `set_merged_into(person_id, into_id | None, at | None)` (it also sets `merged_at`), `set_seen(person_id, at)`, `set_claim_rejected(claim_id, at | None)`, `add_not_same(a, b, at)`, `remove_not_same(a, b)`, `add_event(event)`.
- Readers: `get_event(event_id) -> Event | None`, `events_of(person_id) -> list[Event]` (newest first, where the person is `person_id` or `other_person_id`), `not_same_pairs(person_ids) -> set[frozenset[str]]`, `network_by_group_key() -> dict[str, list[str]]` (canonical ids of people with `list_status = in_list`, by the group key of their name), `identifiers_of(person_ids) -> dict[str, list[Identifier]]`.
- `add_identifier(person_id, identifier) -> bool`, false when another person holds that identifier, and `remove_identifier(person_id, identifier)`.

`store.resolve_person` does not change. It returns the record that holds the identifier, also when that record is merged into another.

### 4. `network.py` (new)

Every function takes `store` first and `now: datetime` by keyword, runs in one `store.tx()`, and writes exactly one event unless it says otherwise. Person ids it receives may be any record's id; it works on canonical ids. `Event.person_id` is the canonical id the decision is about.

- `add(store, hit_person_ids, *, via, now, search_id=None, rank=None, section=None, import_id=None, not_same_as=()) -> Event`. Takes the hits in order. The first hit's person is the target. Each later hit is merged into the target unless it conflicts: a hit conflicts when it holds an identifier in one of the schemes `seed`, `openalex`, `orcid` or `profile_url` and the target's person, with what was merged so far, already holds a different value in that scheme. A conflicting hit is left as it is. The target becomes `in_list` and its `seen_at` is set to `now`, so only facts that arrive later count as new. Each id in `not_same_as` is stored as a not-same pair with the target. The event's `detail` holds `via`, `prior_status`, `merged` (record ids merged by this call), `left_apart` and `not_same`. When the target is already `in_list` and the call would merge nothing, it writes nothing and returns that person's latest `add` event.
- `skip(store, hit_person_ids, *, now, search_id=None, rank=None, section=None) -> Event`. Sets the person of every hit to `skipped`, merging nothing. `detail` holds each person's `prior_status`. A person already in the network is not skipped: raise `ValueError`.
- `remove(store, person_id, *, now) -> Event`. An `in_list` person goes back to `candidate`.
- `merge(store, person_ids, into_id, *, now, search_id=None, rank=None, section=None) -> Event`. Merges each person in `person_ids` into the person of `into_id`, re-pointing records already merged into them, so depth stays one. Removes a not-same pair between them. `detail.merged` lists every record whose `merged_into` changed, with its old value. Merging a person into itself raises `ValueError`. When exactly one of the two is `in_list`, the merged person is `in_list`.
- `not_same(store, person_id, other_id, *, now) -> Event`. Stores the pair. When one is a record merged into the other's person, it is separated first (`merged_into` cleared) and `detail` says so.
- `reject_claim(store, claim_id, *, now) -> Event` sets `rejected_at`.
- `set_contact(store, person_id, kind, value, *, now, replaces=None) -> Event`. `kind` is `email` or `phone`. Writes one claim of that kind on the canonical record, quoting a source of kind `staff` built like a record source with the one line `<kind>: <value>`, URL `fn:staff/<event id>`, date method `staff_edit`, claim date today. When `replaces` holds a claim id, that claim gets `rejected_at` in the same transaction. The event kind is `edit_contact`, and `detail` holds claim ids only, never the value. A typed email also becomes the person's `email` identifier (the address trimmed and lower-cased), so a later import of that address finds the person; undo removes an identifier this call added. An empty value, an email without `@`, a value over 200 characters or an email another person holds raises `ValueError` with a sentence a page can show.
- `undo(store, event_id, *, now) -> Event`. Reverses the event and writes an event of kind `undo` with `undoes` set. It restores exactly what `detail` recorded: statuses, `merged_into` values, not-same pairs, `rejected_at`. For `edit_contact` it rejects the new claim and restores the replaced one. Raises `UndoRefused(message)` when a later event names one of the event's persons in `person_id` or `other_person_id`, when the event is itself an `undo`, or when its kind is `import` or `export`. The message is one plain sentence for staff.
- `record_import(store, import_id, *, now, detail) -> Event` and `record_export(store, *, now, detail) -> Event`. They only write the event. `network.py` is the one writer of events.
- `mark_seen(store, person_id, *, now) -> None`. Sets `seen_at` on the canonical record. No event.
- `name_matches(store, hit_person_ids) -> list[str]`. Canonical ids of network people whose name has the same group key as one of the hits, who are not the person of a hit, and who have no not-same pair with a hit.
- `possible_matches(store, person_id) -> list[str]`. Canonical ids of other persons with the same group key as this person's name, minus not-same pairs.

### 5. `resolve.py` and `rank.py`

- `resolve.run` passes `resolve.group` three more things read from the store, each for the hit persons and for every same-name record `person_ids_by_group_key` returns: the canonical ids, the not-same pairs and the ORCID identifiers.
- `resolve.group` maps each hit to its canonical id before it groups, so two hit records of one person are one person with both lanes' ranks. Within one group key it puts two persons in separate entries when a not-same pair exists between them or when they hold different ORCIDs. A person goes into the first entry of its key that holds nobody it must stay apart from. Stored same-name records that no lane hit are mapped to canonical ids too, and one that is already in the entry is dropped, so a merged record never shows as "not merged". The rest are still added to the first entry of their key, as today, and still flagged.
- Several entries can now share a `name_key`. `rank.py` keys its per-entry lookups on the entry's first person id, not on `name_key`.
- `rank.fuse` takes the section from the hit ids: `network` when one of the entry's hit persons is `in_list`. A same-name record that no lane hit no longer makes a card a network card. An entry stored without hit ids counts its first person as the hit. It fills `Candidate.hit_person_ids`.

### 6. `lanes/seeds.py`

The seed lane's `EXCLUDED` list stays. Reword its comment to say what the list is: the source kinds that searches write. Import and staff sources are not in it, so imported people are found by their organization and role.

## Tests

New file `tests/test_network.py`, plus cases in `tests/test_resolve.py`, `tests/test_rank.py`, `tests/test_db.py` and `tests/test_seeds_lane.py`. Follow the style in `research/tests-tooling.md`: `unittest` classes, `make_db`, made-up names, docstrings that state the invariant in three to five lines.

1. Add one hit: the person is `in_list` with one `add` event. A second Add writes nothing.
2. Add two hits with no conflict: the second is merged, and `claims_of` gives both records' claims under the canonical id, once, also when both ids are passed. Undo separates them and restores the status.
17. Merging a record into a network person after `seen_at` returns that record's claims with a `first_seen_at` later than `seen_at`.
3. Add two hits with different `openalex` ids: the second stays apart and is listed in `left_apart`.
4. `merge` then `undo` restores every `merged_into`, including a record that was already merged into the moved person.
5. `not_same` on a merged record separates it, and `possible_matches` and `name_matches` leave the pair out.
6. Skip, then Add: the person is `in_list`. Skip of a network person raises.
7. Undo after a later event on the same person raises `UndoRefused`. Undo of an undo raises.
8. `reject_claim` hides the claim and a same-value claim from another source in `claims_of` and `match_claims`; `include_hidden=True` returns them; undo brings them back.
9. `set_contact` adds an email, a second call with `replaces` hides the old one, and undo swaps them back. A bad email raises, and so does an email another person holds. `resolve_person` with that email identifier returns the person. `match_claims` never returns an email claim.
10. `resolve.group`: two hit records of one merged person give one entry with one hit id and both lane ranks; a not-same pair gives two entries; different ORCIDs give two entries.
11. `rank`: a hit whose person is `in_list` gives section `network`; an `in_list` same-name record that no lane hit does not.
12. The seed lane finds a person through an affiliation claim that quotes an `import` source.
13. `resolve_person` with the identifier of a merged record returns that record, a claim written on it shows under the canonical id, and its `first_seen_at` is set.
14. `mark_seen` sets `seen_at` and writes no event.
15. A `Source` with an `fn:` URL is valid for kind `import` and `staff` and invalid for `page`.
16. `migrate()` twice is a no-op, and migration 006 fills `hit_person_ids_json` from a stored resolve payload (build the rows in the test).

Each test must fail without the change. Show the failing and the passing run for three of them of your choice, and the full suite result.

## Hand check

On a throwaway copy of the owner's database (the prompt says how to get one): run the migration and report its time; pick the newest search with results; print for its first three candidates the `hit_person_ids` the migration filled; add the first candidate with `network.add`, print the person's status, the event and `network_by_group_key` size; undo it and print the status again. Paste the output.

## Not in this task

Pages, routes, view models, the import, the export, the cut rule (the column exists, nothing sets it), publish steps. Do not change how any page looks. The existing web pages must keep working: run the full suite.

## Rules for this task

- Run `uv run python -m unittest` before you start (272 tests pass) and when you finish. Never edit an existing test to make a change pass. One existing test changes on purpose: `tests/test_rank.py::test_sections_number_apart` builds its network entry without hit ids. Give that entry `hit_person_ids=["p2", "p4"]`, keep its expectation, and add a case in which an `in_list` record that no lane hit leaves the card in section `new`. For any other existing test that fails, stop and report the old and the new expectation instead of editing it. The manager approved four more edits that follow from the new schema: `tests/test_db.py` names the columns of its `persons` insert; `tests/test_web.py` `ContractsV1Test` inserts its person with the v1 columns instead of calling `resolve_person` on a database migrated only to 003, expects `migrate()` to return `[4, 5, 6]`, and lists the two new `candidates` columns.
- No new dependency. Match the style of the file you edit: short functions, docstrings of one to five lines, single-line comments only.
- Only `store.py` runs SQL. `network.py` holds the rules and calls the store.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
