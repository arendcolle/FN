# How FN gets from search-only to the seven staff flows

2026-11-12 · version 2, measured against `main` at `e1250ca` · decisions D5 to D10 settled

**TL;DR.** FN can search and reopen a search today. This design adds what the other flows in the [story map](../design/story-map.md) need: a network that people join through import and Add, merge and skip decisions, a profile per person, a network list and map, CSV export, a ranker that cuts, and a log of every staff decision. It keeps the rules of [the architecture document](../mvp0/architecture.md) and adds six modules, each with one job. Six review panels of three reviewers settled the open decisions. Their records are in [panel-records.md](panel-records.md), and the build order is in [plan.md](plan.md).

## What the owner asked for

The owner wants to walk each of the seven flows end to end on the local server. Everything on the to-do list serves that goal. The request sets these limits:

- The deployment stays as it is: one local server on 127.0.0.1 and one SQLite file.
- No subscription changes. Tests replay recorded calls. A live search runs only when a flow cannot be checked another way.
- The [FN design system](https://claude.ai/artifact/WGaDjfBwi5z6y2HWds2Ayz) is the one source for how pages look. A part the site needs and the design system lacks goes into the design system first.
- Logging has to make later work on speed and on result quality possible.
- Modules have one owner per responsibility, and contracts between them.

## What works today and what does not

The research notes in [research/](research/) hold the detail with file and line. The facts this design rests on:

| Fact | Where |
| --- | --- |
| Nothing ever sets `persons.list_status` to `in_list`, so the network is empty and the "In your network" section never shows | `src/fn/store.py:240`, `src/fn/rank.py:108` |
| `persons.merged_into` exists in the schema and nothing writes it | `src/fn/migrations/001_init.sql` |
| A search runs its four lanes one after another on one worker thread, and people are saved only after the last lane | `src/fn/search.py:33`, `src/fn/worker.py:47` |
| The results page reloads fully every 2 s while a search runs | `src/fn/web/html.py:103` |
| The ranker orders and never cuts. The 24 stored searches with results hold a median of 1,098 people | `src/fn/rank.py`, local database |
| Only the OpenAlex lane writes coordinates, so only its people have a dot on the map | `src/fn/lanes/openalex.py:162` |
| `geo.py` keeps one city per name worldwide. "Bay Area" resolves to a town in the Philippines | `src/fn/geo.py:44` |
| A card shows raw record lines as its quote when the source is an OpenAlex or LinkedIn record | `src/fn/web/app.py:346` |
| A card pools the claims of every same-name record, also the ones no lane found | `src/fn/web/app.py:370` |
| `fn.css` is the design system's `bundle.css` plus 11 site-only lines, and nothing keeps the two in step | `src/fn/web/static/fn.css:155` |
| A step row records start, end, cost, tokens, calls, log and traceback. No table records what staff do with a result | `src/fn/steps.py` |
| A failing lane fails the whole search | `src/fn/worker.py:89` |

## Design rules

The architecture rules stay: contracts at every module boundary, SQL only in `store.py`, one identity function, quotes checked at their offsets, and no automatic merge on a name. Staff pages keep hiding the pipeline. This design adds four rules:

1. **A staff decision is data.** Every Add, Skip, merge, removal, import and export writes one row to an append-only events table. Undo writes a second row that names the first.
2. **A merge is a pointer.** Merging sets `merged_into` on one person record. No claim or identifier moves, so a merge can always be undone.
3. **One module decides how a person reads.** The card, the network row, the profile, the map popup and the export row all come from the same view model.
4. **The design system leads.** A new part gets its README, preview and CSS in the design system first. The site's `fn.css` is a byte copy of the design system's `bundle.css`.

## The model

### People, records and the network

A **record** is one row in `persons`: one seed row, one OpenAlex author, one LinkedIn profile, one name on one web page, or one imported row. A **person** is a record plus every record merged into it. The record the others point at is the **canonical record**.

- `persons.merged_into` holds the canonical record's id and `merged_at` the time of the merge. Depth is always one: merging a person that already has merged records re-points those too.
- `store.resolve_person` keeps its contract. It returns the record that holds the identifier, so a lane that finds a merged record adds its claims to that record.
- Readers see a merged person as one in two places. `resolve.group` maps every hit to its canonical id before it groups. `store.claims_of` returns the claims of each id's whole person, once, with `person_id` set to the canonical id.
- The network is the set of canonical records with `list_status = in_list`. The date a person joined and how (`search`, `import` or `profile`) come from the add event, not from columns.
- `persons.seen_at` holds the last time staff looked at the person: the moment they were added, then each time the profile opens. `network.add` and `network.mark_seen` are its only writers.
- A pair of records that staff declared different people is one row in a new table `not_same`.

### Claims

Claims stay immutable evidence. Three additions:

- `first_seen_at`: when FN first stored the claim. Old rows keep it empty and count as old. A claim is **new** when `first_seen_at` is later than the person's `seen_at` and the person is in the network. A fact that arrives through a merge counts from the time of the merge. The profile shows the marks and then moves `seen_at`.
- `rejected_at`: staff removed the fact. `store.claims_of` and `store.match_claims` leave out a rejected claim and every other claim of that person with the same kind and the same value, so a lane that finds the fact again does not bring it back. A value staff typed after the removal shows again.
- Two new claim kinds, `email` and `phone`. They quote their source like every claim, and they never make a person a search hit: `match_claims` leaves these kinds out.

Imported and hand-typed facts need a source:

- An imported row is a source of kind `import` with one `column: value` line per filled cell, so each claim quotes its own cell. Its URL is `fn:import/<import id>#row-<n>` and its date method is `sheet_date`.
- A fact typed on the profile is a source of a new kind `staff` with URL `fn:staff/<event id>` and date method `staff_edit`.
- `Source` accepts the `fn:` scheme for these two kinds only. `present.py` turns an `fn:` URL into the label and link a page shows.

The seed lane matches seed, import and staff claims, because staff entered those on purpose. It still leaves out the source kinds that searches write (`record`, `vendor_record`, `vendor_page`).

### Places

- `geo.locate(text)` reads qualifiers and aliases: "Cambridge, Massachusetts" and "Bay Area" resolve to the right city. A bare name keeps the rule it had, the most populous city of that name. The alias file is `data/place_aliases.csv`.
- `geo.locate_city(city, state, country)` serves the import.
- A web-page "lives in" claim gets coordinates when it is written. A "born in" claim never does, because the map shows where a person is.
- A person's place is their newest dated location claim with coordinates, else an undated one.

### Events

One append-only table, `events`, records what staff decided:

| Column | Holds |
| --- | --- |
| `id`, `at`, `user_id` | When, and who once login exists (empty now) |
| `kind` | `add`, `skip`, `merge`, `not_same`, `reject_claim`, `edit_contact`, `remove`, `import`, `export` or `undo` |
| `person_id`, `other_person_id` | The canonical record, and the other record of a merge or a not-same decision |
| `search_id`, `rank`, `section` | Where on which search the decision was made |
| `import_id`, `claim_id` | The import or the claim it concerns |
| `undoes` | For an `undo` row, the id of the event it reverses |
| `detail_json` | What undo needs, such as the records an Add merged. It holds ids, never contact values |

`network.py` is the only writer, also of the `import` and `export` rows. Undo is allowed while the decision is the latest event of every person it touched. A later event on the same person makes FN refuse the undo with a plain sentence. Opening a profile writes no event, because it is not a decision.

### Imports

One table, `imports`: id, file name, upload time, status (`preview`, `confirmed` or `discarded`), the file text and a summary of row outcomes. The preview and the confirm both compute rows from the stored text, so they cannot disagree.

- The expected columns are those of the [story map](../design/story-map.md) (D3): `name` required, then `email`, `phone`, `organization`, `role`, `city`, `state`, `country`, `linkedin_url` and `orcid`. The reader matches headers by name, accepts commas and semicolons, and ignores other columns. A blank cell clears nothing.
- A row finds its person through `store.resolve_person` with its strong identifiers: the LinkedIn URL, the ORCID and the email. A row with none becomes a new person with the identifier `import:<import id>:<row>`. A name is never an identifier. An email typed on the profile becomes an identifier too.
- When a row's name matches a network person and no identifier ties them, the preview shows "Same as this person?" with an unticked box. A ticked box merges on confirm. A header box ticks them all, which is the way to import a newer version of the same file.
- The export writes the same columns first, so an exported file imports again. A cell that starts with `=`, `+`, `-` or `@` gets a leading apostrophe, so a spreadsheet does not run it as a formula.

### Candidates and the cut

- `Candidate` gains `hit_person_ids`, the canonical ids of the records a lane found, and `cut_reason`. A card shows and scores only its hit records.
- `rank.py` sets `cut_reason = no_belgian_evidence` on a candidate in section `new` whose only lane is OpenAlex and that has no `belgian_years` part. Everyone else is kept. On the stored searches this takes the median from 1,098 people to 518 and cuts none of the 12 gold picks that reach the ranker.
- Rank numbers count kept people only. Cut rows stay in the table and show on the debug page with their reason.
- A skipped person is not a cut. `store.list_candidates` leaves out a candidate whose hit records are all skipped, so Undo brings the card back without a new rank run.
- The results page shows 50 people and adds 50 per "Show more".

## What staff decisions do

**Add.** One click, no question first. Add merges the card's hit records that hold no conflicting identifier (two different values in `seed`, `openalex`, `orcid` or `profile_url`) into the first hit, sets that person `in_list` and writes one event. A hit with a conflicting identifier stays a separate record, and the card then reads "Added to your network · 1 possible match" with a link to the profile.

**Same person or new.** When a network person has the same name as a card and no shared identifier, the card shows "Same person" and "Add as new" where Add would be, with a link to the network person and nothing preselected. "Same person" merges the hits into the network person, and the new facts show as new on the profile. "Add as new" adds the hits and stores a `not_same` row.

**Skip.** Skip sets the hit records to `skipped`, across searches. The card shrinks to one line with Undo. A later search leaves the person out, and its list ends with "3 skipped people hidden · Show". A new record with the same name still shows.

**Undo.** Every decision has an Undo that reverses its event: the Add with its merges, the Skip, the merge, the removal of a fact, the contact edit.

**Repair on the profile.** "Found as" lists the records of a person, each with "Not this person", which separates the record and stores `not_same`. "Possible matches" lists same-name records and conflicting hits, each with "Same person" and "Different person".

**Cards split.** `resolve.py` puts two records on separate cards when a `not_same` row exists between them or when they hold different ORCIDs.

## While a search runs

- Lanes stay one after another. After each lane except the last, a step named `publish` resolves, ranks and saves what the lanes found so far, so people appear after the first lane and move as later lanes report.
- The page asks `GET /searches/{id}/status` every 2 s. It returns the status, the people count and a version that goes up with each publish. A script of about 30 lines swaps the list when the version changes, keeps the scroll position and updates the map in place. It waits while the pointer or the focus is on a card. Without JavaScript the page falls back to the reload.
- A failing lane keeps its error row and the search goes on. The page then says "Some sources could not be read, so this list may be incomplete." A search that stopped shows the people it had published.
- Running lanes at the same time waits for numbers. `/debug/stats` shows each lane's time and the time to the first person. Before lanes can run together, three things change: `next_step_seq` moves inside the insert transaction, the busy timeout goes up, and every lane write stays a short transaction.

## Modules and who owns what

New modules are marked. Each row has one owner.

| Responsibility | Owner |
| --- | --- |
| Every model and Literal that crosses a boundary, including view models and the CSV column list | `contracts.py` |
| Every SQL statement, the claims of a whole person, hiding rejected values | `store.py` |
| Who is in the network: add, skip, undo, remove, merge, not-same, reject a fact, set a contact detail, mark seen, name matches, and the event for each | `network.py` (new) |
| CSV text to rows, row checks, the preview and the confirm | `importer.py` (new) |
| Network to CSV | `exporter.py` (new) |
| How a person reads: role line, place, ties, evidence, contact, claim wording, what counts as new, the network view | `present.py` (new) |
| Place text to coordinates and the alias file | `geo.py` |
| Order of the fused list, the cut and its reason | `rank.py` |
| Order of steps in a search, publishing people while lanes still run, going on after a failed lane | `search.py` |
| Mapping hits to canonical ids, grouping same-name records into one card, splitting on not-same pairs and different ORCIDs | `resolve.py` |
| Searching known people: seed, import and staff claims | `lanes/seeds.py` |
| Read models for the owner: timings, costs, feedback | `stats.py` (new) |
| App factory, middleware, request log, error pages | `web/app.py` |
| Staff routes and pages | `web/staff.py` (split from `app.py`) |
| Debug routes and pages | `web/debug.py` (split from `app.py`) |
| HTML of each design-system part, one function per part | `web/parts.py` (split from `app.py`) |
| Token values, part looks, part rules | the design system |
| Site CSS | `web/static/fn.css`, a byte copy of the design system's `bundle.css` |

Boundaries:

- `web/` calls `network.py`, `importer.py`, `exporter.py`, `present.py` and `stats.py`. It never writes membership through `store.py` directly.
- `importer.py` creates people through `store.resolve_person` and adds them through `network.add`. It does not set `list_status`.
- `present.py` reads through `store.py` and returns view models. It writes nothing and builds no HTML.
- `web/parts.py` turns view models into HTML and reads nothing from the store.
- `store.py` stays one file. It is split by aggregate behind the one `Store` class when it passes about 800 lines.

## Pages

| Page | Route | What it shows |
| --- | --- | --- |
| Home | `/` | The search box, the three newest searches with an "All searches" link, then the network as on the Network page. An empty network shows a notice that points to Import and to adding people from a search |
| All searches | `/searches` | Every search, newest first |
| Results | `/searches/{id}` | People for one question as cards beside the map, with Add and Skip, 50 at a time, and Export |
| Network | `/people` | Everyone in the network as rows beside the map, newest added first. One text box filters on name, place and organization, with a Filter button. Two links narrow the list further: "From import contacts.csv" after an import, and "New facts only" when someone has new facts. The count line reads "214 people · 12 not on the map". 200 rows, then "Show more". Import and Export sit on the heading |
| Person | `/people/{id}` | One person: contact details, every fact with its source, what is new, "Found as" and "Possible matches" |
| Import | `/imports/new`, `/imports/{id}` | Upload with the expected columns listed, then the preview with Confirm |
| Export | `/people/export.csv`, `/searches/{id}/export.csv` | The filtered network, or one search's kept people, as CSV |
| Source | `/sources/{id}` | Unchanged |

The header has two links, Search and Network. A dot on the map opens a popup at every screen width, with the name as a link, role and employer, place and "Open profile". Clicking a row pans to its dot and opens the same popup. Results and Network share the layout, the map, the popup, the row-to-dot link and the count line, so the product reads as one.

## Logging for later work

**Speed.** Step rows already hold duration, cost and calls. This design adds one log line per request with the route, the duration and, on list pages, the filter and the rows rendered. `/debug/stats` shows per step the median and slowest duration, the cost and the call count over the last searches, and the time to the first person.

**Result quality.** The events table is the feedback data. `/debug/feedback` shows per search how many people were kept, cut, added and skipped, at which ranks the added people stood and which lanes found them. The gold runner reports a pick the cut removed as lost at the rank step with the cut's reason, and reports lane errors on searches that still ended done.

**Data quality.** The import stores each row's outcome. `geo` logs every place it could not resolve.

## Decisions

The panels' full records, with the evidence and the dissent, are in [panel-records.md](panel-records.md).

| Decision | Outcome | Agreement |
| --- | --- | --- |
| D5. What Add, merge, keep-apart and Skip do | The rules under "What staff decisions do" | Majority. One reviewer wanted Add to add only the top hit when identifiers conflict, and one wanted such cards split |
| D6. What the ranker cuts | OpenAlex-only people without Belgian evidence, 50 per page | All three |
| D7. Where email, phone and hand-typed facts live | Claims with an `import` or `staff` source. Name-only import rows are new people with an unticked merge box | Majority. One reviewer wanted two separate actions for a contact edit, and one wanted name matches flagged without a merge box |
| D8. Home, header, Network page and person detail | The pages above | All three |
| D9. How people appear while a search runs | Publish after each lane, poll a status endpoint, lanes one after another | All three |
| D10. Module map and data model | The model and the ownership table above | All three |

The manager changed three points of the panel records:

- `CONTRACTS_VERSION` stays 2. The new `Candidate` fields have defaults, which the architecture document says needs no new version, and a new version would hide every stored search from the trace page.
- The `cut_reason` column has no SQL CHECK. The architecture rule is that vocabularies are Literals with no CHECK constraints.
- No backfill of `hit_person_ids` by replaying payloads in Python. One SQL statement in the migration fills it from the stored resolve output, and a candidate without it falls back to its first record.

## Not doing

- Login and several users. `user_id` stays empty.
- Excel import and a mapping step that guesses columns.
- Fuzzy or nickname name matching, and a model that judges duplicates.
- Editing any fact by hand. Staff edit contact details and remove facts.
- A model that reorders the top results, and any change to the order of the list. The cut only removes people.
- Running lanes at the same time, server-sent events and time estimates.
- A location claim in the LinkedIn lane. The lane is off by default, and the change breaks eight of its tests.
- Sort controls, map clustering, filtering by the map's bounds, place and organization selects, and statistics on the home page.
- A mirror of the design system in the repository.
- Any change to how FN is deployed, and any new dependency.
