# Task T10: Add, Skip, Same person and Undo on a result card

Branch `feat/card-actions`. After this task a result card has its buttons, a search shows 50 kept people at a time, skipped people are hidden, and reopening an old search shows who was added since.

Read first: [design.md](../design.md) "What staff decisions do" and "Candidates and the cut"; [panel-records.md](../panel-records.md) records D5 and D6; the plan's section "T10 to T13 provide"; the design system parts PersonCard, ShowMore, FilterBar (the count line) and Banner; the mockup `page-results.html`; the Results strings in `notes/e2e/design-system/STRINGS.md`; and `src/fn/network.py`, `src/fn/present.py`, `src/fn/web/staff.py`, `src/fn/web/parts.py` and `src/fn/web/static/map.js` as they are now.

## What changes

### 1. Which candidates a page shows

- `store.list_candidates(search_id, kept_only=False, include_skipped=True)`: with `include_skipped=False` it leaves out a candidate whose hit persons are all `skipped`.
- `present.results(store, search, today, shown=50, show_skipped=False) -> ResultsView`. It reads kept candidates only. `ResultsView` gains, next to its two lists: `total` (kept people, skipped ones not counted), `shown`, `skipped_hidden`, `not_on_map`, and per person a `CardView(person, state, match, undo_event, note)`:

| State | When | The card shows |
| --- | --- | --- |
| `network` | the candidate's section is `network` | no buttons |
| `new` | not in the network, no name match | Add and Skip |
| `name_match` | not in the network, and `network.name_matches` finds someone | "Same name as <name> in your network", then Same person, Add as new and Skip |
| `added` | section `new` and the person is in the network now | "Added to your network", with "· 1 possible match" linking to the profile when the add left a hit apart, "· same person as <name>" after Same person, "· as a new person" after Add as new; Undo while the add is the person's latest event |
| `skipped` | the person is skipped | the one-line card "Skipped <name>" with Undo while the skip is the person's latest event |

- A person skipped on this search shows as the one-line card where it stood. A person skipped on another search is hidden and counted in "3 skipped people hidden · Show". `?skipped=1` shows them as one-line cards, and the line reads "3 skipped people shown · Hide".
- The page shows the first `shown` cards over both sections, network first, then "50 of 518 shown" and "Show 50 more" (`?shown=100`). `shown` that is not a positive number is 50.
- Above the sections: the count line "518 people · 41 not on the map · Export".

### 2. Routes

- `POST /searches/{id}/people/{person_id}/add`, `/skip`, `/same` (field `match`: the network person) and `/new` (field `match`: stored as not the same). `person_id` is the candidate's person id. The route reads the candidate's hit persons and its rank and section from the stored search and passes them to `network.add`, `network.skip` or `network.merge`, so the event records where the decision was made. Unknown search or person: 404.
- Undo is `POST /events/{id}/undo`, which exists.
- A request that carries the header `X-Requested-With: fetch` gets the card's HTML back (200). Any other request is redirected (303) to the results page at the card's anchor, so the buttons work without JavaScript.
- `GET /searches/{id}/export.csv`: the search's kept, not skipped people through `exporter.csv_text`, named `fn-search-<date>.csv`.

### 3. `results.js` (new static file, loaded on the results page)

- It sends a card's form with `fetch` and the header above, and swaps the card's element for the returned HTML, so the list does not jump. On a network error it submits the form the normal way.
- After a swap it tells the map to reload its points (a document event that `map.js` listens to), so a skipped person's dot leaves the map.
- No inline script: the CSP allows this site's script files only.

### 4. Reopening a search

The states come from the people's status now, not from the day of the search, so an old search shows "Added to your network" on the people added since, and network people found again stand in "In your network".

## Tests

New `tests/test_card_actions.py`, with made-up people and a stored search built in the test:

1. A new card has Add and Skip; a network card has none; a card with a same-name network person has the three buttons and that person's link.
2. Add: the person is in the network, the card says "Added to your network" with Undo, and the event holds the search id, the rank and the section. Add twice: one person, one event.
3. Add on a card with two hit records merges them; with conflicting identifiers the card says "· 1 possible match".
4. Same person merges into the network person; Add as new adds and stores the not-same pair; each card says which.
5. Skip: the one-line card with Undo here, hidden on another search and counted in the skipped line; `?skipped=1` shows it. Undo brings the card back.
6. A request with the fetch header gets the card's HTML; one without is redirected to the anchor.
7. `shown`: 50 by default, `?shown=100`, and `abc`, `0`, `-1` fall back to 50; the "of" count is kept people only; a cut candidate never shows.
8. Reopening: a search stored before a person was added shows that person as added.
9. The export of a search has one row per kept, not skipped person.
10. Unknown search or person: 404.

Each new test must fail without the change.

## Hand check

With the Playwright browser tools at 1280 px and 390 px on a throwaway copy of the owner's database, on the stored search `f10ee197-4c35-48f1-80f6-07cdbceae261`: add the first person and check `/people` lists them; undo; skip the second and check its dot left the map; press Show 50 more; open another stored search that holds one of the same people and check the state there. Report each step, the page size in bytes, any console error, and save screenshots of the results page at both widths in your temp folder.

## Not in this task

The live update of a running search, the status route, the Person page's own buttons (they exist), import.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- `web/staff.py` changes membership only through `network.py`. `present.py` returns view models and builds no HTML. `web/parts.py` builds HTML from view models and reads nothing from the store. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
