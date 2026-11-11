# Task: a place text resolves to the right city

Branch `fix/geo-places`. Two small changes, each with its own test.

## Why

`geo.py` keeps one city per name worldwide, the most populous, and ignores the state and country (`src/fn/geo.py:31-48`, `:59-76`). Measured on the cached GeoNames file:

- "Bay Area" resolves to Bay in the Philippines. Two stored searches use that place. The LinkedIn lane then searches the location "Bay" (`src/fn/lanes/linkedin.py:91-102`), and the OpenAlex lane sorts every Bay Area author outside the radius (`src/fn/lanes/openalex.py:193-203`).
- "Cambridge, Massachusetts" resolves to Cambridge in the UK, "Portland, Maine" to Portland in Oregon and "Paris, Texas" to Paris in France.
- 307 of the 2,947 US city names in the file occur in more than one state.

Only the OpenAlex lane gives a location claim coordinates, so people from other lanes have no dot on the map.

## G1. `geo.locate` reads qualifiers and aliases

`geo.locate(place, names)` and `geo.area(http, place)` keep their signatures and their callers keep working. `GeoArea.city` keeps the form `"<name>, <country code>"`, because `lanes/linkedin.py` `LOCATIONS` is keyed on it.

Rules:

1. A metro alias wins first. A new hand-kept file `data/place_aliases.csv` (columns `kind,alias,target`) holds metro names (`metro,bay area,"San Francisco, CA, US"`), US state names and codes (`state,massachusetts,MA`) and country names and codes (`country,united kingdom,GB`). Match the longest alias in the folded text. Build the country rows from GeoNames `countryInfo.txt` once and commit the result; add the common short forms (USA, U.S., UK, Holland). GeoNames data is CC BY 4.0: add one attribution line to `README.md`.
2. Text with commas: the part before the first comma names the city, the later parts are qualifiers. A qualifier that is a known state or country filters the cities of that name (GeoNames column 11 is the admin1 code, which is the state code for US cities; column 9 is the country code). A state implies the US. Among the cities left, the most populous wins.
3. A known qualifier that no city of that name matches gives `None`. FN does not guess a city in another state. An unknown qualifier, such as "Flemish Region", is ignored.
4. Text without commas keeps the word scan it has today, and a state or country name found among the other words filters the matched cities the same way ("Portland Maine", "New York and New Jersey area").
5. A bare name keeps today's rule: the city's own name beats an alternate name, then the larger population wins. "Cambridge" stays Cambridge in the UK.
6. A text that names only a state or country and no city gives `None`.

New function `geo.locate_city(city: str, state: str | None, country: str | None, names) -> GeoArea | None` for the CSV import: the same rules with the qualifiers given apart. `state` and `country` each accept a name or a code.

Expected results, which the test asserts against fixture rows (extend `tests/fixtures/geo/cities15000-extract.txt` with the real GeoNames rows these need):

| Input | City | Near |
| --- | --- | --- |
| Bay Area | San Francisco, US | 37.77, -122.42 |
| San Francisco Bay Area | San Francisco, US | |
| Silicon Valley | San Jose, US | 37.34, -121.89 |
| Greater Boston | Boston, US | |
| Boston area | Boston, US | |
| Cambridge, Massachusetts | Cambridge, US | 42.37, -71.11 |
| Cambridge, MA | Cambridge, US | |
| Cambridge, Massachusetts, United States | Cambridge, US | |
| Cambridge | Cambridge, GB | |
| Cambridge, UK | Cambridge, GB | |
| Cambridge, Texas | none | |
| Portland, Maine | Portland, US | 43.66, -70.26 |
| Portland Maine | Portland, US | 43.66, -70.26 |
| Portland | Portland, US | 45.52, -122.68 |
| Paris, Texas | Paris, US | 33.66, -95.56 |
| Paris | Paris, FR | |
| Springfield, Massachusetts | Springfield, US | 42.10, -72.59 |
| Columbus, Georgia | Columbus, US | 32.46, -84.99 |
| Atlanta, GA | Atlanta, US | |
| Washington, DC | Washington, US | |
| New York and New Jersey area | New York City, US | |
| Brussels, Brussels Region, Belgium | Brussels, BE | |
| Leuven, Flemish Region, Belgium | Leuven, BE | |
| London | London, GB | |
| Georgia | none | |
| anywhere in the US | none | |
| (empty) | none | |

`locate_city`: `("Cambridge", "MA", None)`, `("Cambridge", "Massachusetts", "USA")` and `("Cambridge", None, "United States")` give Cambridge, US. `("Cambridge", None, "UK")` gives Cambridge, GB. `("Cambridge", None, None)` gives Cambridge, GB. `("Leuven", None, "Belgium")` gives Leuven, BE. `("Nowhere", "MA", None)` gives none.

Hand check: resolve every distinct place of the stored searches (Atlanta, New York and New Jersey area, Georgia, Bay Area, New York, Boston, Boston area, San Francisco, San Diego, London, Los Angeles) against the cached GeoNames zip at `var/cache/9192eaa5e750fe72224a27bb5d7c41457120f33967952597477a186d1575cef6.json` (it is the raw zip) and print the result. Bay Area must give San Francisco. The others must not change, apart from that fix.

## G2. A web-page "lives in" claim gets coordinates

`extract.py` writes a location claim for `born_in` and `lives_in` (`src/fn/extract.py:159-176`) with no coordinates. Give a `lives_in` claim the coordinates `geo` finds for its text, at the place where the claim is built. A `born_in` claim stays without coordinates, because the map shows where a person is, not where they were born. A place `geo` cannot resolve leaves the claim without coordinates and adds one log line naming the text.

## Not doing: a location claim in the LinkedIn lane

The first version of this task also had the LinkedIn lane write a location claim from the profile's location text. It is left out. The change breaks 8 existing LinkedIn tests, because they assert exact claim sets and call counts, and the lane is off unless `FN_LINKEDIN=1`, so it would help nobody today. It stays on the to-do list.

## Rules for this task

- Run `uv run python -m unittest` before you start (267 tests pass) and when you finish. Every test must pass. Never edit an existing test to make a change pass; if a test encodes behaviour this task changes on purpose, stop and report it.
- Each of G1 and G2 gets a test that fails without the change. Show the failing run and the passing run in your report.
- No new dependency. Match the style of the file you edit. One-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
- No real people's names in tests or fixtures: use made-up names.
