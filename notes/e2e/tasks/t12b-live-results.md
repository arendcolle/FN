# Task T12b: the results page updates while a search runs

Branch `feat/live-results`. After this task a running search shows people as each lane reports, without reloading the page, and a search that lost a source or stopped says so above the people it found.

Read first: [design.md](../design.md) "While a search runs"; [panel-records.md](../panel-records.md) record D9; the design system parts StatusLine, Notice and PersonCard; the mockup `page-results-running.html`; the Results strings in `notes/e2e/design-system/STRINGS.md`; and `src/fn/search.py`, `src/fn/store.py` (`search_progress`, `failed_lanes`), `src/fn/web/staff.py`, `src/fn/web/parts.py` and `src/fn/web/static/results.js` and `map.js` as they are now.

## What changes

1. **Status route.** `GET /searches/{id}/status` returns `{"status", "people", "version"}` from `store.search_progress`. Unknown search: 404.
2. **List fragment.** `GET /searches/{id}/cards` returns the HTML of the results list alone: the status line or note, the count line, the sections with their cards, "Show more" and the skipped line. It takes the same `shown` and `skipped` query as the page. The page builds its list through the same function.
3. **The poll, in `results.js`.** While the page's search is queued or running, the script asks the status route every 2 s. When the version or the status changed, it fetches the fragment and swaps the list in place, keeps the scroll position, and tells the map to reload its points (the event the script already sends after an Add or a Skip). It does not swap while the pointer or the keyboard focus is on a card; it swaps when the pointer leaves or the focus moves out. When the search is no longer running, it does one last swap and stops. The script is plain JavaScript in a static file; the CSP allows no inline script.
4. **Without JavaScript** the page still reloads every 2 s while a search runs: move the meta refresh into a `<noscript>` element.
5. **The status line** reads "Searching…" before the first people and "Searching… 12 people so far" after, with "1 person so far" for one.
6. **A search that ended with a problem:**
   - Done with a failed lane (`store.failed_lanes` is not empty): the StatusLine note "Some sources could not be read, so this list may be incomplete." with the button "Search again", above the people.
   - Failed or interrupted with people published: the note "This search stopped before it finished." with "Run again", above the people it had found. Today the page hides them.
   - Failed or interrupted with nobody: the Notice "This search stopped", as STRINGS.md words it, with "Try again".
   - Each button posts the question to `POST /searches` again.
7. **Request log.** The status route puts `version` and `people` in `request.state.facts`.

## Tests

In `tests/test_web.py` or a new `tests/test_live_results.py`:

1. The status route returns the progress of a queued, a running and a done search, and 404 for an unknown one.
2. The fragment holds the same cards as the page, and no `<html>` or header.
3. A running search's page has the status line with the people count, the script tag for `results.js`, and the meta refresh only inside `<noscript>`.
4. A done search with a failed lane shows the note and "Search again" above its cards.
5. A failed search with published people shows them under "This search stopped before it finished."; one with nobody shows the Notice and no map.
6. With a fake lane that blocks (as `tests/test_search.py` does): while it blocks, the status route says running with version 1 and the fragment holds the first lane's card; after release it says done.

Each new test must fail without the change. An existing test that asserts the old stopped-search page (people hidden) or the meta refresh in the head changes on purpose: list it with the old and the new expectation.

## Hand check

With the Playwright browser tools at 1280 px on a throwaway copy of the owner's database, with `FN_HTTP=replay FN_LLM=replay`: open the debug page of search `f10ee197-4c35-48f1-80f6-07cdbceae261` and press "Run again with these chips", which reruns it from stored chips and replays the recorded calls. Watch the results page of the new search: report when the first cards appear, whether the list changes without a page reload (the network log shows no document reload), whether a card you hover stays in place during an update, and what the page says at the end (a lane may fail on a replay miss, which is the note this task adds). Save a screenshot while it runs and one at the end in your temp folder and give the paths.

## Not in this task

Running lanes at the same time, server-sent events, a time estimate, lane names on a staff page.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- `present.py` returns view models and builds no HTML. `web/parts.py` builds HTML from view models and reads nothing from the store. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
