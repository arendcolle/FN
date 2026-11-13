# Task UI-1: the way back

## Goal

At 1280 px the list returns to card 1 after every visit to a person or a source, and the "Back to the results" link also drops "Show 20 more" (blockers in both walkthroughs). A source page, a possible-match page, a person opened from the map or from the Network list, and the page after Remove, Undo or Same person have no way back. The cause is one: links and redirects drop where the page was opened from. `profile_head` links to the bare `/searches/{id}` (`src/fn/web/parts.py:386`), the card link has no shown count or card (`parts.py:128`, `:132`), the combined link has no search (`parts.py:129`), a network row links with `from=row` only (`parts.py:212`), the popup links to `/people/{id}` (`present.py:393`), and `person_here` keeps only `search` and `all` (`src/fn/web/staff.py:475`). Decisions U1 and U2 in [design.md](../design.md).

## Before you start

The design system is built at version 11 (UI-0 is done), and Q-1 of the ranking track is merged in the repository (it edits `present.py`; see `plan-quality.md`, "Order across both tracks"). This task is the only one that copies the bundle. Copy its `ds/project/components/bundle.css` byte for byte over `src/fn/web/static/fn.css`, and its `ds/STRINGS.md` and `ds/DESIGN-NOTES.md` over `notes/e2e/design-system/`. Set `BUNDLE_SHA` in `tests/test_results_page.py:25` to `4f1a844883605813c3dd6c1e0faf0b156f2618607965ac516bf6094b5c41da81`, the sha256 of the version 11 bundle, and its comment says version 11. If the copied file hashes to anything else, stop and report it. Read `ds/project/components/BackLink/README.md` and `preview.html` and copy their markup. If the page needs a class or a string the design system does not have, stop and report it.

## Markup, from the BackLink part

- Back link, the first line of the page's column: `<p class="fn-back text-meta"><a href="…">{label}</a></p>`. A page never shows two.
- Walk line, right under it, only on a person page opened from a search: `<p class="fn-walk text-meta"><span>4 of 143</span> · <a href="…" rel="prev">Previous</a> · <a href="…" rel="next">Next</a></p>`. The first person has no Previous and the last no Next, each with its " · " left out.
- The results label cuts the question at 60 characters, at a word, with "…" inside the quote marks: "Back to the results for “Flemish experts in telecom and 6G research in the…”".

## The address of a page opened from another page

| Opened from | Link | Back link |
| --- | --- | --- |
| A card's name or its combined line | `/people/{pid}?search={sid}&shown={n}&card={key}&from=card` | "Back to the results for “`{question cut at 60}`”" to `/searches/{sid}?shown={n}#card-{key}` |
| A results map popup | same, `from=popup` | same |
| A network row on Network or Home | `/people/{pid}?from=row&back={list url}#person-{n}` url-encoded | "Back to your network" |
| A network map popup | `/people/{pid}?from=popup&back={page path and query}` | "Back to your network" |
| A possible match, the same-name link, a Sources row on a person page | target with `back={that person page's path and query}` | "Back to `{person name}`" |
| A card's same-name link, its "1 possible match" note, its quote or cite source link | target with `back={results url}#card-{key}` | the results label |
| A fact's source link on a person page | target with `back={that person page's path and query}#claim-{claim_id}` | "Back to `{person name}`", to that fact's line |

`shown` is left out when it is 20, as `results_href` does (`parts.py:143`). The search origin uses `search`, `shown`, `card`; every other origin uses `back`. No origin known: no back link.

## What to build

1. `src/fn/contracts.py`: `class BackLink(Model): label: str; href: str` and `class ListPlace(Model): position: int; total: int; previous: str | None = None; next: str | None = None` (hrefs).
2. `src/fn/present.py`: `walk(store, search, key) -> tuple[int, int, tuple[str, str] | None, tuple[str, str] | None] | None`: the card's 1-based position among the kept people who are not skipped, the total of that whole list (not the shown count; it equals `results(...).total`, so the line reads "4 of 143" beside "20 of 143 shown", lead's ruling), and the (person id, card key) before and after. It must agree with `results(...).order` (`present.py:368`) without building person views: `store.list_candidates(search.id, kept_only=True)`, `is_skipped`, and the canonical id of `identity.on_card(...)[0]`. None when the key is not in that list.
3. `src/fn/web/parts.py`: `person_href(person_id, search_id, shown, key, origin) -> str`; `with_back(href, back) -> str` (adds `back=` before any `#`); `back_line(back: BackLink | None, place: ListPlace | None) -> list[Safe]` with the BackLink part's two lines in the markup above. `person_card(..., shown: int = RESULTS_STEP)` and `result_card(card, search_id, here, shown)` pass the shown count; the combined line links to `person_href(...)` plus `#matches` (UI-2 changes the anchor). `profile_head(view, back, place, here)` replaces the `search` argument. `network_row(view, n, back)` takes the list url. Links to a possible match (`possible_line`), to the same-name person (`profile_state`), and to sources on the person page (`claim_line`, `contact_block`, `found_as_block`) go through `with_back(..., here)`; a fact's source link in `claim_line` uses `here` plus `#claim-{claim_id}` as its `back`. On a card, `result_card` passes `here` plus `#card-{key}` as `back` to the same-name link (`match_line`, `parts.py:152`), the note link (`note_href`, `present.py:295`) and the quote and cite links (`quote`, `statement`, `parts.py:70`, `:78`). `profile_state`'s Same person posts with `next` set to the merged-into person's path plus this page's query. `claim_line` gives each fact `id="claim-{claim_id}"`, and its reject and Undo forms post `next={here}#claim-{claim_id}`.
4. `src/fn/web/staff.py` owns the origin. `back_link(store, value) -> BackLink | None`: a value that `local_path` refuses, longer than 2,000 characters, or not one of `/`, `/people`, `/people/{id}`, `/searches/{id}`, `/searches/{id}/map` (each with any query and anchor) gives None; an unknown person or search gives None. `/` and `/people` read "Back to your network", a person reads "Back to `{display name}`", a search the results label. `person_here` keeps `search`, `shown`, `card`, `back` and `all`. `person_page` builds the back link (search first, else `back`), the `ListPlace` when the address has `search` and `card` (Next raises `shown` to the next multiple of 20 that holds the next card), and `current="search"` when the address carries a search or a `back` to a search, else `"network"`. `card_action` reads the shown count from `next` for its fetch answer. `network_block` passes each row its list url. `geo_features` adds `"profile"` to each listed person: `person_href(..., origin="popup")`. `source_page(source, claim, back)` shows `back_line` above the title, and `show_source` reads `back`; the header marks Search when `back` leads to a search. `reject` falls back to `/people/{canonical}#claim-{claim_id}` when the form has no `next`.
5. `src/fn/web/static/map.js`: copy `listed.profile` onto the person next to `shown` and `list` (`map.js:140`). The popup's name and "Open profile" use `p.profile` when present; else `p.href` plus `?from=popup&back=` and the url-encoded `location.pathname + location.search`.
6. `src/fn/web/static/results.js`: on `pagehide` save `.fn-results__list` `scrollTop` in `sessionStorage` under `fn-scroll:` plus path and query; on `pageshow`, when `event.persisted` or the navigation type is `back_forward`, set it back. Wrap storage in `try`. Otherwise the `#card-` anchor places the list. One single-line comment says why.

## Inputs a real run will meet

No search in the address; a search id that does not exist; a card key not in the search, or a skipped card (back link, no walk line); a list of one ("1 of 1", neither link); the 20th card (Next goes to `shown=40`); `shown` of `abc`, `0`, `-1` or seven digits (20); a `back` of `//evil.example`, `https://evil.example`, `/\evil.example`, `javascript:alert(1)` or 3,000 characters (no back link); a `back` to a person merged since (its canonical name); a running search; a search stored before card records existed; a network person on a search; a hostile question in the back label (escaped).

## Tests

In a new file `tests/test_way_back.py`, with made-up names. Each must fail without the change.

- With `?shown=40`, card 27's name links with `search`, `shown=40`, `card` and `from=card`; its page's back link goes to `/searches/s1?shown=40#card-{key}`.
- The walk line: first, middle and last of three people; a skipped person is passed over; Next from card 20 carries `shown=40`; `walk` agrees with `results(...).order` on a search of 25, and card 4's line reads "4 of 25" while 20 cards are shown.
- A network row with filter `q=gent` links with its `back`, and that page reads "Back to your network" to `/people?q=gent#person-1`.
- A possible match and a source link from Ada's page carry `back`; their pages read "Back to Ada Example", and the source page's back link ends in `#claim-{id}`; each refused `back` above gives no back link.
- A 90-character question gives a results label cut at a word within 60 characters, with "…" inside the quote marks; the first person's walk line has no "Previous" and does not start with " · ".
- The copied `fn.css` hashes to the `BUNDLE_SHA` above.
- The header marks Search on a person and a source page opened from a search, and Network on a person page without one.
- After Add, Not same, Same person and a reject posted from a page with `search`, `shown` and `card`, the redirect keeps all three; a reject lands on `#claim-{id}`.
- The results geo answer gives each listed person a `profile` link with the search.
- On a card, the same-name link, the "1 possible match" note and the quote link carry `back` to the results url with `#card-{key}`.

## Existing tests that change, approved

- `tests/test_results_page.py`: `BUNDLE_SHA`; `test_the_combined_line_shows_for_two_records_not_merged_into_one`, its href only.
- `tests/test_person_page.py`: `test_card_and_network_row_names_link_to_the_person_page`, its two hrefs only.
- `tests/test_web.py`: `test_a_card_shows_employer_place_belgian_orgs_and_one_quote`, the name link's href only.
- `tests/test_card_actions.py`: the "1 possible match" note's href (`:108`) only.
- `tests/test_person_page.py`: `test_a_same_name_candidate_can_join_the_network_person`, the same-name link's href only.

No other existing test may change. Run the whole suite: `uv run python -m unittest`.

## Hand check

On a throwaway var folder (`mkvar.sh ui1`), `FN_VAR` set to it, `FN_LLM=replay`, your own `FN_PORT`, `uv run fn-serve`. With a headless Playwright script at 1280 px and 390 px, on a stored search: scroll to card 9, open it, take the back link, screenshot; open card 9 again, press the browser Back, screenshot; Show 20 more, card 27, back link, screenshot; a map popup, Open profile, back link; a network row, back link; a source page, back link. Log the list panel's `scrollTop` and the first visible card before and after each step. Pass: every return shows the card you left. Give the screenshot paths and say what each shows, without names.

## Not doing

- History replacement after Not correct or Undo (a walkthrough nit).
- Restoring an open map popup after Back.
- Scroll restore on the Network list.
- The person page's sections, combined facts and labels (UI-2), the source page body (UI-3).
- The import preview's "Same as" link: the design system has no back label for an import, so it stays without one.
