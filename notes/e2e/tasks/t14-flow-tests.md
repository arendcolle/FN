# Task T14: one test per staff flow, end to end

Branch `test/staff-flows`. After this task `tests/test_flows.py` walks each of the seven flows of the [story map](../../design/story-map.md) through the app the way a staff member would: one request after another, reading each page for the next link or form.

Read first: the story map; [design.md](../design.md) "Pages" and "What staff decisions do"; `tests/helpers.py` and `tests/test_search.py` for how tests build a store, fake lanes and a client; `tests/test_import_pages.py` for how a test posts a file; and the routes in `src/fn/web/staff.py` as they are now.

## Why

Every piece has its own tests. Nothing checks that the pieces connect: that the page after an import links to the people, that a person added from a search stands on the Network page, that an exported file imports again. The to-do list asks for the flows to be tested end to end.

## What to write

One test class per flow in `tests/test_flows.py`, with made-up people. Each test uses `TestClient` only: it follows the links and posts the forms it finds in the returned HTML (find a form's action and hidden fields in the page instead of hard-coding the route), so a broken link or a renamed field fails the test. A small helper that pulls a form's action and fields, or a link by its text, out of the HTML keeps the tests short; use the standard library's `html.parser`.

1. **Import a CSV file and see the people on the map.** Open Home on an empty network and follow Import. Post a semicolon CSV of five people with cities in two US states and Belgium, one row without a name. Read the preview's counts, confirm, follow "Show them", and check the five rows, the count line, and that the geo route gives a point for each person whose city exists.
2. **Run a search and see who FN found.** With two fake lanes (as `tests/test_search.py` builds them) and one person already in the network: post a question, read the status route while the second lane blocks, release it, and check the page shows the network person under "In your network" and the new person with Add and Skip.
3. **Add or merge new people from a search.** On a stored search: Add a person and find them on the Network page; press "Same person" on a card whose name matches a network person and check one person holds both records; Skip a person and check the card and the hidden-skipped line on another search; Undo the skip.
4. **A search finds new facts about someone in the network.** A person is in the network. A later search's lane writes a new claim for that person's identifier. The Network row then says "1 new fact", the profile marks the fact "New", a second visit does not, and Remove with Undo hides and restores the fact.
5. **Browse the network on the map and open a profile.** Network page, filter by a place, the geo route narrows with it, a point's `href` opens the profile, and the profile shows the facts with their sources and a working link to each Source page.
6. **Reopen an old search.** A search is stored, then two of its people are added and one skipped from another search. Opening the first search from "All searches" shows those states.
7. **Export the network to CSV.** Export from the Network page, check the header and a row, export with a filter and check the row count equals the count line, then import the exported file with every name match ticked and check the network holds the same people.

Add one more test for what staff must never see: fetch every staff page the flows visit and assert none holds a score, a lane name ("openalex", "seeds", "linkedin", "lane:"), the word "Traceback" or a link to `/debug`.

## Rules for this task

- These tests must pass on the code as it is. If a flow cannot be walked because a link, a form or a page is missing or wrong, do not work around it in the test: stop, and report the flow, the step, what the page returned and what the story map expects. That report is the result of this task.
- Change no file under `src/`. If a test needs a fake lane or a helper, put it in the test file or in `tests/helpers.py`.
- Run `uv run python -m unittest` before you start and when you finish.
- No new dependency. Single-line comments only; test docstrings of three to five lines that state what the flow guarantees.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
