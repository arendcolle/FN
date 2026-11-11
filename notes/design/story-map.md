# What FN users need to do, and which steps are missing

2026-11-10 · second draft with the four decisions settled, measured against `main` at `e1250ca`

**TL;DR.** This map lists seven things staff want to do in FN, each as steps in order, and marks every step built, partial or missing. Searching and reopening a search work today. Importing, the network map, profiles, adding and merging, updates and export are missing, because nobody is in the network yet. All 25,845 people in the database are candidates. Four decisions, settled and listed at the end, shape those flows: the network starts empty, new facts are marked rather than queued, and the import reads a CSV with fixed column names. The first slice is import, then the network list, map and profile, because every other flow needs a network to work on.

## How to read the map

Each flow below is one goal a staff member has, written as the steps they take. Each step says what FN does today and gets one of three statuses:

- built: works as the step needs
- partial: some of it works, and the "Today" column says what is missing
- missing: nothing in FN does it yet

A missing or partial step is a to-do. The [to-do list](../../TODO.md) points here instead of copying them.

## Flow 1: Import a CSV file and see the people on the map

A staff member has a spreadsheet of people, saves it as CSV, and wants the people in FN and on the map. Excel files come later (D4).

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Upload a CSV file in the browser | No upload page. Seed lists load from JSONL files through the `fn-seed` command | missing |
| 2 | Read on the upload page which column names FN expects, and rename the file's columns to match (D3) | Nothing | missing |
| 3 | Check a preview: rows read, rows skipped and why, columns FN ignored, possible duplicates | Nothing | missing |
| 4 | Confirm, and the people join the network | `persons.list_status` has the value `in_list`, but no code sets it | missing |
| 5 | FN turns each person's city, state and country into coordinates | `geo.py` locates the place in a question, never a person's city. It keeps one city per name, the most populous, so it cannot tell Portland, Maine from Portland, Oregon. The map reads location claims only | missing |
| 6 | Open the network map and see the imported people | A map exists only on a search's results page | missing |

Excel on a Belgian locale saves CSV with semicolons, because the comma is the decimal separator there, so the reader has to accept both. The standard library's `csv.Sniffer` detects the delimiter.

## Flow 2: Run a search and see who FN found

A staff member types a question and wants people from the network first, then new people the lanes found.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Type a question | The home page has the search box | built |
| 2 | Wait, and see that FN is working | The page refreshes every 2 s and says the search is running. People appear only when every lane is done. Live, the web lane alone took 190 s on one gold case and LinkedIn 178 s | partial |
| 3 | See the people already in the network | The results page has an "In your network" section, which stays empty because nobody is in the network | partial |
| 4 | See new people, ranked, each with the reason | Cards show a reason and a quote. Stored searches return up to 2,132 people, and 17 of the 28 return more than 700. OpenAlex cards quote raw record lines | partial |
| 5 | See the results on a map | List and map sit side by side | built |
| 6 | Change the question and search again | The question stays editable at the top of the results | built |

Step 1 is marked built, but `geo.py` resolves some places in a question to the wrong city. It keeps the most populous city of each name and ignores the state and country. Two stored searches have the place "Bay Area", which resolves to Bay in the Philippines. The LinkedIn lane then searches the location "Bay", and the OpenAlex lane sorts every Bay Area author outside the radius.

## Flow 3: Add or merge new people from a search

A staff member looks at the new people in a search and puts the right ones in the network.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Press Add on a card | Designed in [the design decisions](decisions.md), not built | missing |
| 2 | FN says whether this person is already in the network, by shared identifier or similar name | Within one result, FN puts records with the same name on one card and flags them. It never checks against the network | missing |
| 3 | Choose to add as new, merge into the existing person, or keep them apart | Nothing | missing |
| 4 | Skip a person so FN stops suggesting them | Designed, not built | missing |
| 5 | Undo an Add or a Skip | Designed, not built | missing |

## Flow 4: A search finds new facts about someone in the network

A search finds a person staff already know, with something new about them, such as a new job or a talk.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | FN recognizes the person by an identifier it already holds, such as an OpenAlex id or a LinkedIn URL | The lane adds its claims to that person and tells nobody | partial |
| 2 | FN finds someone with the same name and no shared identifier | FN keeps a separate record and shows both on one card, marked "same name in N records, not merged". A seed person that OpenAlex finds always gets a second record this way, because seed rows have no OpenAlex id | partial |
| 3 | Staff see the new facts marked "new since you last looked" on the profile (D2) | Nothing | missing |
| 4 | Staff remove a fact that is wrong | Nothing | missing |

## Flow 5: Browse the network on the map and open a profile

A staff member looks at an area on the map, clicks a few people and reads their details.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Open a map of the whole network | The map exists only per search | missing |
| 2 | Zoom to an area and see who is there | Works on a search's map, and people at the same point share one dot with a count | partial |
| 3 | Click a person and see a short summary | On narrow screens a popup shows name and role. On wide screens the click highlights the person's card in the list | partial |
| 4 | Open the full profile with every claim, source and date | The Person page `/people/{id}` is designed, not built. Each source has a page at `/sources/{id}` | missing |

## Flow 6: Reopen an old search

A staff member goes back to a search from last week.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Find the search on the home page | Recent searches show the question, the people count and the date | built |
| 2 | Open it and see its results | FN renders the stored results | built |
| 3 | See who was added or skipped since | Depends on flow 3 | missing |

## Flow 7: Export the network to CSV

A staff member wants everyone in the network in a spreadsheet.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Choose what to export: the whole network, a filtered list or one search's results | Nothing | missing |
| 2 | Download a CSV with one row per person: name, role, organization, place, Belgian ties and a source link | Nothing | missing |

## Flows this map may be missing

These came up while writing the map. Each could become a flow of its own:

- Browse the network as a list and filter it on a few fields, such as organization, place or seed list
- Look up one person by name to see whether they are already in the network
- Edit a person by hand to fix a wrong fact or add a note. The claim model already has a `staff_edit` date method
- Remove someone from the network
- Find and merge duplicates inside the network, for example right after an import
- Import a newer version of the same file, which raises the question of whether rows update people or add them
- Several staff using FN, with login and a record of who added whom. The design decisions name 5 to 20 staff, and login is out of scope for now

## Decisions

These four decisions were settled on 2026-11-10. Each one changes how a flow is designed.

**D1. Who is in the network at the start? Nobody.** The network starts empty and fills through import and Add. The 4,940 seed people stay candidates, and searches reach them through the seed lane.

**D2. What happens when a search finds new facts about a network person? FN adds them and marks them.** The profile marks each new fact "new since you last looked". Every claim keeps its source, quote and date, so staff remove a wrong fact instead of approving every right one. A same-name match with no shared identifier stays a possible match that staff merge in flow 3.

**D3. How does the import know which column is which? By fixed column names.** The upload page lists the names FN expects, and staff rename their columns to match. FN ignores other columns and says which ones in the preview. A mapping step that guesses columns from their headers can come later.

The expected columns follow what a person can hold in `contracts.py` today:

| Column | Required | Becomes |
| --- | --- | --- |
| `name` | yes | The person's name |
| `email` | no | A contact detail, which needs a new field |
| `phone` | no | A contact detail, which needs a new field |
| `organization` | no | An affiliation claim |
| `role` | no | A role claim |
| `city` | no | A location claim, which step 5 of flow 1 turns into coordinates |
| `state` | no | Part of the location claim. The US state, or the province or region elsewhere |
| `country` | no | Part of the location claim |
| `linkedin_url` | no | A `profile_url` identifier, the one the LinkedIn lane sets |
| `orcid` | no | An `orcid` identifier, the one the OpenAlex lane sets |

The `state` column exists because 307 of the 2,947 US city names in the GeoNames city list FN uses occur in more than one state. FN has no place for email or phone today, so the import needs the contact field from the to-do list first. The two identifier columns let a later search recognize an imported person, as long as the import stores the URL in the same form as the lanes.

**D4. CSV or Excel first? CSV.** The standard library reads CSV. Excel needs openpyxl, a new dependency, and comes after the CSV flow works.

## Suggested build order

Each slice below gives staff a complete flow, and each later slice needs the one before it.

1. Import CSV, then the network list, the network map and the Person page. These cover flows 1 and 5, and every other flow needs people in the network.
2. Export CSV, flow 7. It is one page with the standard library.
3. Add, Skip and merge from search results, and the "In your network" section in search, flows 3 and 2.
4. New facts on network people, flow 4.

The stricter ranker cut and the card claim format on the to-do list fit into slice 3, because staff add from the cards they see.
