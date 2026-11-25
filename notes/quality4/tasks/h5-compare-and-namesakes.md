# Task H5: two records side by side, and namesake questions only on network pages

## Goal

To answer "same person?" staff open pages and scroll, and 605 of 6,703 shown result cards lead to a page listing possible matches (research note `same-person.md`). This task shows both records in one Compare table (design system version 14) wherever FN asks, and lists possible matches on network people's pages only. `present.py` builds the view, `web/parts.py` renders it (brief H5).

## What to build

### `src/fn/contracts.py`

After `ReasonView`: `CompareValue(text: str, href: str | None = None)`, `CompareRow(field: str, left: list[CompareValue] = [], right: list[CompareValue] = [], left_more: int = 0, right_more: int = 0, differs: bool = False)`, `CompareView(caption: str, titles: tuple[str, str], left_none: str, rows: list[CompareRow])`.

`ProfileView` (line 668) gains `compares: list[CompareView] = []`, one per `possible`, and `name_compare: CompareView | None = None`. `ImportRow` (line 1107) gains `lat` and `lon`, both `float | None = None`.

### `src/fn/importer.py`

`rows_of` (line 251) stores the `locate` area's `lat` and `lon` on the row.

### `src/fn/present.py`

```python
COMPARE_FIELDS = ("Name", "Job", "Employer", "Place", "Studied", "Belgian tie", "Email", "Phone", "LinkedIn", "ORCID", "Found in")
FILE_FIELDS = ("Name", "Job", "Employer", "Place", "Email", "Phone", "LinkedIn", "ORCID")
DIFFERS = ("Employer", "Place", "Email", "Phone", "LinkedIn", "ORCID")
COMPARE_SHOWN = 3
SAME_SPOT_KM = 10.0  # an employer-based place sits on the org's coordinates, not the city centre

@dataclass(frozen=True)
class Value:
    text: str
    key: str
    href: str | None = None
    org: str | None = None
    spot: tuple[float, float] | None = None

Side = dict[str, list[Value]]
```

- `keyed(field, text, href=None, org=None, spot=None) -> Value`. Key: digits for Phone, the identifier value for LinkedIn and ORCID, else folded text with single spaces.
- `same(field, a, b) -> bool`. Employer: `org` when both have one, else key. Place: `geo.distance_km <= SAME_SPOT_KM` when both have a spot, else key. Else key.
- `compare_view(left, right, fields, titles, caption, left_none) -> CompareView`. Fields in order, a field empty on both sides left out. A side drops repeated keys, shows `COMPARE_SHOWN` values and counts the rest. `differs`: field in `DIFFERS`, both sides filled, `same` false for every pair. The left Name never links: only the other person's name does (Compare part).
- `person_sides(store, groups, today) -> list[Side]`, batched like `person_views` (line 573). Name: `display_name`, href `/people/{id}`. Job, Employer: `work_lines(job_claims(...))` (lines 476, 503), head first; Employer where `shown.relation in JOINING`, with its org id. Place: `located` (line 174), then `location` claims not `born_in` or `origin`, newest first, with spots. Studied: `studied_at` claims, "{org}, {span_words(own_years)}". Belgian tie: `what_of` of `tie_claim(claims, facts, evidence_tie(...))` (lines 1036, 1048). Email, Phone: claims newest first, plus Email identifiers; hrefs `mailto:`, `tel:`. LinkedIn: identifiers, shown without `https://www.`. ORCID: the bare id. Found in: per record, its source with most claims (as `found_as`, line 1109), "{record_label}, {date}", an import without ", row n"; date from `source_date` ("3 November 2026", "May 2024", "2024"), else `day_words(fetched_at)`.
- `row_side(row) -> Side`: the cells; Employer `org=orgs.org_id(text)`; Place `importer.place_of(row.cells)` with the row's spot. LinkedIn and ORCID come from `importer.identifiers(row.cells)` (line 125), linked and keyed by the identifier; a cell it does not use shows as plain text with its own folded key.
- `import_compares(store, preview, today) -> dict[int, CompareView]` for each `name_match` row: one `person_sides` call, `FILE_FIELDS`, titles "In the file" and "In your network", caption "Row {n} of {filename} and {name} in your network", `left_none` "Not in the file".
- `profile` (lines 1262 to 1277): `matches = network.possible_matches(store, canonical) if member else []`; `found_as` gets `matches if member else persons[1:]`, so Not this person stays on a card page. One `person_sides` call. `name_compare`: "This person" and "In your network", caption "This person and {name} in your network". `compares`: "This person" and "Possible match", caption "This person and possible match {n} of {count}", or "This person and the possible match" for one. `left_none` "Not known".

### `src/fn/web/parts.py`

- `compare_table(view, back=None) -> Safe`: the Compare part's markup exactly: "Differs" in `span.fn-compare__differs.text-label` after the field; an empty side `td.fn-compare__none` ("Not known" on the right); several values `ul.fn-compare__list`, last `li` "and {n} more". The Name href takes `with_back(href, back)`.
- `name_match` (line 793) takes the row's `CompareView`; the table replaces the two `fn-check__detail` lines. `name_matches` takes `compares: dict[int, CompareView]`.
- `possible_line` (line 668) gets the compare: `div.fn-line.fn-line--compare`, the table in `fn-line__main` with back `{here}#matches`, then the buttons as today.
- `profile_state` (line 438): `div.fn-lines > div.fn-line > div.fn-line__main` with `view.name_compare` (back `here`) between the line and the buttons.
- `match_facts(match) -> Safe | None`: `p.fn-card__match.text-body` "In your network: " plus `facts_line(role_line(match), f"added {match.added}" if match.added else None)`, after each `match_line` in `result_card` (lines 237, 248).

### `src/fn/web/staff.py`

`import_summary` (line 851) passes `import_compares(...)` to `name_matches`.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| A row's coordinates | `importer.rows_of` |
| Rows, values, words, links, Differs | `present.compare_view`, `person_sides`, `row_side` |
| Which pages list possible matches | `present.profile` |
| Compare markup | `parts.compare_table` |
| Pairs, merge, not-same | `network.py`, unchanged |
| Style sheet | the lead |

## Recorded answers, replay and stored searches (S6)

No prompt, model or HTTP call changes, so recorded answers and replay tests stay valid. Ranking reads no possible match: version-1 searches keep their order.

## Inputs a real run will meet

No fact on a side (4), twelve employers (2), 200 characters (5), email on one side (4), one employer two ways (1), a city with and without its state (1, 3), two namesakes at one employer (1), a name-only row (4), two network namesakes (4), a match decided a moment ago (7), ten matches (7), a network person opened from a search (8), 390 px (hand check), a duplicate value (2), a `javascript:` LinkedIn cell and an ORCID "n/a" (5), 300 name matches (6), a preview stored earlier (3).

## Tests (each must fail without the change)

1. `test_present.py` `test_a_row_differs_only_when_no_value_on_one_side_equals_one_on_the_other`: one org id, one spot, an employer-based place 5 km from its city's row, case, digits, LinkedIn hosts and ORCID forms agree; Job, Name and a one-sided row never differ.
2. `test_present.py` `test_rows_keep_order_and_a_side_shows_three_then_and_n_more`: twelve employers give three and 9; a duplicate shows once.
3. `test_importer.py` `test_a_located_row_keeps_its_coordinates`: "Cambridge, MA" has them, Gotham has none, an old summary validates.
4. `test_import_pages.py` `test_each_name_match_shows_both_records_and_differs_where_they_disagree`: of two rows, Differs on exactly Employer and Place of the second; a one-sided email reads "Not known"; a name-only row reads "Not in the file"; two network namesakes show the first.
5. `test_import_pages.py` `test_long_values_and_bad_links_render_whole_and_as_text`: 200 characters whole; `javascript:` and "n/a" as text.
6. `test_import_pages.py` `test_three_hundred_name_matches_read_the_claims_once`: `claims_of` wrapped; exactly 2 calls on the page (views plus compares) and 300 tables.
7. `test_profile_page.py` `test_possible_matches_are_compare_tables_with_both_buttons`: captions for one and for ten; the left Name cell is plain text, the right one a link; after Different person nine tables and the done line.
8. `test_profile_page.py` `test_a_page_outside_the_network_runs_no_possible_match_query`: `possible_matches` patched to raise, page 200 without the section; the person added and opened from the card has it.
9. `test_profile_page.py` `test_a_result_with_a_network_namesake_shows_line_table_and_three_buttons`.
10. `test_card_actions.py` `test_a_same_name_card_shows_the_network_persons_facts_after_each_choice`.

## Existing tests that change, approved by the lead

- `test_import_pages.py` `test_a_posted_csv_redirects_to_a_preview_with_counts_matches_and_rows`. Old: "In the file: Lecturer, Other Labs · Cambridge, MA, USA · cy@example.org". New: `<caption>Row 4 of contacts.csv and Cy Samename in your network</caption>` and `<tr><th scope="row">Employer</th><td>Other Labs</td><td class="fn-compare__none">Not known</td></tr>`.
- `test_profile_page.py` `test_a_card_of_two_records_shows_both_and_not_this_person_separates_the_second`, line 234. Old: "Same person" under Possible matches. New: `assertIsNone(self.section(alone, "Possible matches"))`, and the docstring says so.

No other existing test may change; stop and report. On a scratch copy the `profile` gate failed only the second. Main has 1,145 tests; the wall-clock bound at `test_openalex.py` line 363 failed once under load.

## Hand check

1. `uv run python -m unittest` all green.
2. On a copy (`V=$(mkvar.sh h5)`), a script outside the repo counts kept new-section candidates whose `present.profile(s, c.person_id, today, identity.on_card(s, c))` has `possible`, and sums `possible` over network people. Run it with `FN_VAR=$V FN_HTTP=replay FN_LLM=replay` from main and from here. Planner, read-only, with only the `profile` gate applied: 6,703 cards, 2 with matches, both network people added from a search; network 4 people, 5 pairs. This plan reads the brief's target of 0 as 0 cards of people outside the network. The 2 are network people, who keep the section (decision 4). Main: 605 cards per the research note (the planner's main run did not finish in 13 minutes); the network counts must match.
3. On a second copy, `FN_VAR=$V FN_PORT=8792 FN_HTTP=replay FN_LLM=replay uv run fn-serve`. Upload two rows named like one network person, the first with its role, employer and place, the second with another employer and place. Screenshot with headless Playwright at 1280 and 390 px the import question, a possible match and a namesake page; check the last row and right edge.

## Not doing

Deciding pairs by rule or model, "None of these", an answer for an unticked row, every namesake of a row, debug flags, new routes, style sheet edits. A phone with and without its country code reads as Differs.
