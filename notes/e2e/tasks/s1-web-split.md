# Task: split `web/app.py` by job, with no change in behaviour

Branch `refactor/web-split`. A structural change only. Every page FN serves must be byte-identical before and after.

## Why

`src/fn/web/app.py` is 845 lines and holds five jobs: the app factory and middleware, the staff pages, the debug pages, the rules for how a person reads on a card, and the HTML of each design-system part. The next slices add a Network page, a Person page, import, export, Add and Skip. Each job needs one file before that work starts, so two slices do not edit the same 2,000-line file.

## Target layout

Move code. Do not rewrite it, rename it or improve it.

| File | Holds |
| --- | --- |
| `src/fn/present.py` (new) | How a person reads, with no HTML and no HTTP: `EMPLOYED`, `newest_places`, `employer_of`, `belgian_orgs`, `evidence`, `date_words`, `cut`, `plural`, `days_ago`, `sources_read` |
| `src/fn/web/parts.py` (new) | The HTML of each design-system part, one function per part: `search_box`, `recent_meta`, `orgs_line`, `quote_block`, `notice`, `error_page`, and the person card (lift the inner `card` function out of `person_cards` as `person_card`) |
| `src/fn/web/staff.py` (new) | The staff router and its pages: `/`, `POST /searches`, `/searches/{id}`, `/searches/{id}/map`, `/api/searches/{id}/geo`, `/sources/{id}`, with `home_page`, `person_cards`, `search_page`, `geo_features`, `source_page`, `recent`, `get_search`, `get_source` |
| `src/fn/web/debug.py` (new) | The debug router and its pages: every `/debug/...` route and `POST /searches/{id}/rerun`, with the debug card, chips form, trace, calls and source pages, `chips_from_form`, `lane_matches`, `duration` |
| `src/fn/web/requests.py` (new) | Request helpers both routers use: `store_of`, `worker_of`, `form_of`, `first` |
| `src/fn/web/app.py` | `create_app`, the guard middleware, `refusal`, the security headers, the exception handler and `serve`. It includes both routers |
| `src/fn/web/html.py` | Unchanged |

`tests/test_web.py` and `tests/test_map.py` import only `create_app` and `serve` from `fn.web.app`. Keep both there.

If a function is used by both the staff and the debug pages, put it where its job is (`present.py` for a rule about a person, `parts.py` for HTML) and import it from both. Report each case.

## Proof that nothing changed

Write a throwaway script outside the repo (in your temp folder) that builds the app with `create_app` on a throwaway copy of the owner's database (the task prompt says how to get one), and uses `fastapi.testclient.TestClient` to fetch these and write each response body to a file:

- `/`, `/debug`, `/debug/errors`
- for the three newest searches with status done: `/searches/{id}`, `/searches/{id}/map`, `/api/searches/{id}/geo`, `/debug/searches/{id}`
- for the first claim on each of those searches' first card: its `/sources/{id}?claim=...` page and `/debug/sources/{id}?claim=...`
- one `/debug/steps/{id}/calls` and one `/debug/searches/{id}/trace?name=...`

Run it once on the untouched code (`git stash` is not allowed: run it before you edit anything and keep the output folder), once after the split, and `diff -r` the two folders. The diff must be empty. Paste the file list and the diff result in your report.

## Rules for this task

- Run `uv run python -m unittest` before you start (267 tests pass) and when you finish. Every test must pass with no edit to any test file.
- No behaviour change, no renames beyond `card` to `person_card`, no new abstraction, no new dependency.
- Each new file starts with a one-line module docstring that says its job. Update the module docstring of `app.py`.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
