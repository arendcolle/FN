# Task T7: the Network page, the home page and the map popup

Branch `feat/network-page`. After this task `/people` lists the network beside a map, the home page shows the network under the search box, every search has a page in "All searches", and a dot on any map opens a popup.

Read first: [design.md](../design.md) "Pages"; [panel-records.md](../panel-records.md) record D8; the plan's ["T7 provides"](../plan.md#t7-provides); the design system parts ResultsLayout, NetworkRow, FilterBar, SectionHeading, MapMarker, Notice, RecentSearches, ShowMore and Header; the mockups `page-home.html`, `page-home-empty.html`, `page-network.html`, `page-network-filtered-empty.html` and `page-searches.html`; and `src/fn/present.py`, `src/fn/web/staff.py`, `src/fn/web/parts.py` and `src/fn/web/static/map.js` as they are now.

## What changes

### 1. Store and view model

- `contracts.NetworkFilter(text: str = "", import_id: str | None = None, new_only: bool = False)` and `contracts.NetworkView(people: list[PersonView], total: int, not_on_map: int, shown: int)`.
- `store.list_network(flt: NetworkFilter, limit: int | None) -> tuple[list[str], int]`: the canonical ids of the people with `list_status = in_list`, newest added first (by the time of the person's latest `add` event), and the total before the limit. `text` matches, without regard to case, anywhere in the person's name or in the value of an affiliation, role, location or topic claim of the person or a record merged into them. `%`, `_` and quotes in the text are plain characters. Text of only spaces is no filter. `import_id` keeps the people an import added or merged. `new_only` keeps people with at least one new fact.
- `present.network_view(store, flt, limit, today) -> NetworkView`: the people as `PersonView`s for the rows shown, the total, and how many of the whole filtered set have no place on the map.
- `present.geo(people: list[PersonView]) -> dict`: the GeoJSON `map.js` reads, one point per person with a place, with the properties `id`, `name`, `role`, `employer`, `place`, `new_facts` and `href` (the Person page, `/people/<id>`). The results geo route uses the same function, so both maps get the same shape.

Measure on a throwaway copy of the owner's database with 1,000 people added to the network (add the first 1,000 candidates of a stored search with `network.add`): `/people` must answer in under 1 s and `/api/people/geo` in under 2 s. Report both times. If the place of every filtered person cannot be read that fast through `person_views`, add one store reader for places and say so.

### 2. Routes and pages

- `GET /people`: the Network page. Query: `q` (the filter text), `import` (an import id), `new=1`, `limit` (default 200, then steps of 200; anything else is the default) and `view=map` for the narrow layout's map view, as the results page does it.
  - The layout is ResultsLayout with NetworkRow rows: name, role and employer, place, the ties line, the date added, and the "2 new facts" mark. Each row carries `data-person` and, when the person has a place, `data-place`.
  - Above the rows: the heading "In your network", the FilterBar (a GET form with one text box and a Filter button), the tokens for `import` and `new` with their Clear links, and the count line "214 people · 12 not on the map". Leave a part out when it is 0.
  - Under the rows: "200 of 214 shown" and "Show 14 more" when there are more.
  - No people at all: the empty-network Notice. A filter that matches nobody: "0 people", Clear all and the "Nobody matches" Notice. Both hide the map.
  - The Import and Export links are added by the import and export task, with their routes. Leave them out.
- `GET /api/people/geo`: the same query as `/people`, without the limit, through `present.geo`.
- `GET /`: the search box, then the three newest searches with the link "All searches" when there are more than three, then the network block: the same heading, filter, count line, rows and map as `/people`, built by the same function, with the filter form's action `/people`. Home scrolls as one page while its map sticks (`fn-results--page`).
- `GET /searches`: every search of kind `search`, newest first, as RecentSearches rows under "All searches 29".
- The header has two links, Search and Network, on every staff page. Network is current on `/people`.
- Each list page puts `rows`, `total` and whether a filter is on in `request.state.facts` (a dict) for the request log.

### 3. `map.js`

- It links any element with `data-person` to its dot: cards on the results page, rows on the Network page and Home.
- A click on a dot opens the popup at every width, and from 900px up also picks the card or row. The popup for one person shows the name as a link to `href`, role and employer, the place, "2 new facts" when above 0, and "Open profile". A dot shared by several people starts with "4 people here" and lists them, names as links, with no "Open profile". Use the markup and classes of the MapMarker preview.
- A click on a network row outside a link pans to its dot and opens the same popup, from 900px up. A row without `data-place` does nothing.
- The map fits its dots with 64px padding and a maximum zoom of 11, as the MapMarker part says.
- The page's script stays one file without a build step.

## Tests

In `tests/test_web.py` or a new `tests/test_network_page.py`, on a database with made-up people:

1. `/people` lists network people newest added first, and a candidate is not listed.
2. The filter finds a person by a part of their name, of their organization and of their place, in any case; `%` and `_` are plain characters; spaces only is no filter.
3. `import=<id>` lists the people of that import; `new=1` lists people with a new fact.
4. `limit`: 200 by default, `limit=400` shows more, `limit=abc`, `-5` and `999999999` fall back to the default. The count line and "Show more" follow.
5. An empty network shows the empty Notice and no map. A filter with no match shows "0 people" and "Nobody matches".
6. `/api/people/geo` returns one point per person with a place, and its count equals the total minus "not on the map" for the same query.
7. Home shows at most three searches, "All searches" only when there are more, and the network rows. `/searches` lists every search.
8. The header shows Search and Network, with `aria-current="page"` on the right one.
9. The results geo route returns the same property names as the network one.

Each new test must fail without the change. An existing test that asserts the old home page (recent searches without a cap) or the old geo properties changes on purpose: list it with the old and the new expectation.

## Hand check

Start the server on a port from your range on a throwaway copy of the owner's database with 30 people added to the network from a stored search. With the Playwright browser tools (ToolSearch "playwright"), at 1280 px and at 390 px: open `/people`, filter on a place, click a dot and read the popup, click a row and check the popup opens, open Home and `/searches`. Report what each step showed and any console error. Take a screenshot of `/people` at both widths into your temp folder and give the paths.

## Not in this task

The Person page (links to `/people/<id>` 404 until the next task), Add and Skip, import and export, the cut, the live update of a running search.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- `present.py` returns view models and builds no HTML. `web/parts.py` builds HTML from view models and reads nothing from the store. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
