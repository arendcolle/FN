# What FN users need to do, and which steps are built

2026-11-12 · third version: what is built after the work in [notes/e2e/](../e2e/plan.md), measured against `main`

**TL;DR.** This map lists seven things staff want to do in FN, each as steps in order, and marks every step built, partial or missing. On 2026-11-10 searching and reopening a search worked: 5 of the 30 steps were built, 7 partial and 18 missing. Now 29 are built and one is partial: a search lists the right people, but their order still ignores the place of the question. The network starts empty and fills through import and Add. The four decisions at the end are the owner's, and the design that follows from them is in [the system design](../e2e/design.md).

## How to read the map

Each flow below is one goal a staff member has, written as the steps they take. Each step says what FN does today and gets one of three statuses:

- built: works as the step needs
- partial: some of it works, and the "Today" column says what is missing
- missing: nothing in FN does it yet

A missing or partial step is a to-do. The to-do list points here instead of copying them.

## Flow 1: Import a CSV file and see the people on the map

A staff member has a spreadsheet of people, saves it as CSV, and wants the people in FN and on the map. Excel files come later (D4).

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Upload a CSV file in the browser | `/imports/new`, reached from Import on the Network page. Files up to 5 MB | built |
| 2 | Read on the upload page which column names FN expects, and rename the file's columns to match (D3) | The upload page lists the ten columns. Headers match in any order and any case; commas and semicolons both work | built |
| 3 | Check a preview: rows read, rows skipped and why, columns FN ignored, possible duplicates | `/imports/{id}` shows the counts in words, each skipped row with its reason, the ignored columns and a box per name match | built |
| 4 | Confirm, and the people join the network | "Import 12 people" writes everything in one go; a second press changes nothing | built |
| 5 | FN turns each person's city, state and country into coordinates | `geo.locate_city` reads the three columns. A city FN cannot find is named in the preview, and that person has no dot | built |
| 6 | Open the network map and see the imported people | The Network page says "12 people imported from contacts.csv. Show them" and lists exactly those people beside the map | built |

## Flow 2: Run a search and see who FN found

A staff member types a question and wants people from the network first, then new people the lanes found.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Type a question | The home page has the search box | built |
| 2 | Wait, and see that FN is working | People appear after each lane, without a page reload, under "Searching… 12 people so far". A lane that fails no longer stops the search; the page then says some sources could not be read | built |
| 3 | See the people already in the network | "In your network" lists them first, with no buttons | built |
| 4 | See new people, ranked, each with the reason | 20 people at a time, each with the words of the question it matches. A fact from a database record reads "Affiliated with KU Leuven, 2008–2013"; only prose sources show a quote. The ranker cuts people only OpenAlex found who have no Belgian evidence, which takes the median search from 1,098 to 518 people. The order still ignores the place of the question | partial |
| 5 | See the results on a map | List and map side by side; a dot opens a popup | built |
| 6 | Change the question and search again | The question stays editable at the top of the results | built |

The order of the kept people is the open part. A test of three ways to use the question's place in the ranker found none that helps without losing a gold pick, because the only located places are the last institutions OpenAlex knows. The numbers are in [place-ranking.md](../e2e/research/place-ranking.md).

## Flow 3: Add or merge new people from a search

A staff member looks at the new people in a search and puts the right ones in the network.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Press Add on a card | Add puts the person in the network and the card says "Added to your network" | built |
| 2 | FN says whether this person is already in the network, by shared identifier or similar name | A shared identifier puts the person under "In your network". A same name shows "Same name as … in your network" on the card | built |
| 3 | Choose to add as new, merge into the existing person, or keep them apart | "Same person" merges, "Add as new" adds and remembers they are different. Records Add leaves apart show as "1 possible match" and are decided on the profile | built |
| 4 | Skip a person so FN stops suggesting them | Skip hides the person here and in later searches, behind "3 skipped people hidden · Show" | built |
| 5 | Undo an Add or a Skip | Undo on the card, as long as it is the person's latest decision | built |

## Flow 4: A search finds new facts about someone in the network

A search finds a person staff already know, with something new about them, such as a new job or a talk.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | FN recognizes the person by an identifier it already holds, such as an OpenAlex id or a LinkedIn URL | The lane adds its claims to that person, and they count as new | built |
| 2 | FN finds someone with the same name and no shared identifier | The record stays apart and shows under "Possible matches" on the profile, with "Same person" and "Different person" | built |
| 3 | Staff see the new facts marked "new since you last looked" on the profile (D2) | The Network row says "2 new facts", the count line links "3 with new facts", and the profile marks each fact "New" until it is opened | built |
| 4 | Staff remove a fact that is wrong | Remove on the fact, with Undo. The fact stays removed when a lane finds it again | built |

## Flow 5: Browse the network on the map and open a profile

A staff member looks at an area on the map, clicks a few people and reads their details.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Open a map of the whole network | The Network page and the home page show the network as rows beside the map | built |
| 2 | Zoom to an area and see who is there | People at one point share a dot with a count. The filter box narrows rows and dots by name, place or organization | built |
| 3 | Click a person and see a short summary | A dot opens a popup with name, role, employer and place at every width; a click on a row opens the same popup | built |
| 4 | Open the full profile with every claim, source and date | `/people/{id}`: contact details, every fact once with its newest source, what is new, the records the person was found as | built |

## Flow 6: Reopen an old search

A staff member goes back to a search from last week.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Find the search on the home page | The three newest searches, and "All searches" for the rest | built |
| 2 | Open it and see its results | FN renders the stored results, 20 at a time | built |
| 3 | See who was added or skipped since | Cards show today's state: "Added to your network", or hidden when skipped | built |

## Flow 7: Export the network to CSV

A staff member wants everyone in the network in a spreadsheet.

| # | Step | Today | Status |
| --- | --- | --- | --- |
| 1 | Choose what to export: the whole network, a filtered list or one search's results | Export on the count line of the Network page, of a filtered list ("Export these 9") and of a search | built |
| 2 | Download a CSV with one row per person: name, role, organization, place, Belgian ties and a source link | The import's columns first, then Belgian organizations, the date added and the profile address. The file imports again | built |

## Flows the first map missed

These came up while writing the first map. Five are covered now:

- Browse the network as a list and filter it: the Network page, with one box for name, place and organization
- Look up one person by name: the same filter box
- Remove someone from the network: Remove on the profile, with Undo
- Find and merge duplicates inside the network: "Possible matches" on the profile
- Import a newer version of the same file: rows with a LinkedIn URL, ORCID or email update their person, and the other rows are name matches that one box merges

Two are not built:

- Edit a person by hand. Staff edit the email and phone and remove facts; they cannot type a new job or place
- Several staff using FN, with login and a record of who added whom. Every decision is already stored as an event with an empty user

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

## What is left

- The order of results. The place of a question does not move people up or down yet.
- Excel files, and a mapping step that guesses columns.
- An undo for a whole import. People can be removed one by one.
- A place for people FN finds on LinkedIn. That lane is off by default and writes no location.
