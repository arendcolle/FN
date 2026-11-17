# Task U2a: the reading line and the set-aside groups

## Goal

Slice r1 sets aside people known to fail a required wish (75 of 104 under the Washington search's first heading were elsewhere), but the page shows each reason as one more heading, hides how FN read the question, and walks from a match into a set-aside person. This task builds design system version 13 for that: the reading line (N7), closed "Set aside" groups (N2, N3, N6, N8), their card line, the live count line, the no-full-match line, and a walk inside one list.

## What to build

### Copies

`src/fn/web/static/fn.css` becomes a byte copy of version 13's `bundle.css` (sha256 `80a0f648e6ceb9db380a7c3702104bb8fbe0779f6762e3bff578b340f90b7e94`); `notes/e2e/design-system/STRINGS.md` and `DESIGN-NOTES.md` become copies of version 13's.

### `src/fn/contracts.py`

`AsideGroup(Model)`: `key: str; title: str; count: int; cards: list[CardView] = []; shown: int = 0; next_key: str | None = None`. `CardView` gains `aside_line: ReasonView | None = None`; `ResultsView` gains `groups: list[AsideGroup] = []` and `no_match: str | None = None`.

### `src/fn/present.py` (adds `from fn.geo import regions_of` and `from fn import parse`; `present.geo` at line 803 keeps its name, staff.py uses it)

- Delete `ASIDE_HEADINGS`, `UNFIT_LINE` (lines 68, 69). Add `GROUP_KEYS = ("other", "outside", "abroad", "unfit")`, `GROUP_TITLES = {"other": "Other people found", "abroad": "Outside the US", "unfit": "Other roles or topics"}`, `SET_ASIDE = "Set aside"`, `CLOSEST = "The closest people are below."`, `TIE_BELOW = "The people below have a known tie, but FN could not confirm their topic."`.
- `area_words(place: Place) -> str`, checked in this order: kind `anywhere_us` with a text that names the US itself (`name_key` in `US_NAMES = ("us", "usa", "us based", "united states")`) gives "in the US"; any other `anywhere_us` text gives `f"in {text}"` when `regions_of(name_key(text), free_text=True)` finds it ("in North Carolina"), else `f"in the {text}"` ("in the US West Coast"); kind `abroad` gives `f"in {text}"`; kind `metro` or None gives, a leading "the " dropped, `f"in the {text} area"`, adding no "area" to a text ending in " area" ("in the New York area", although "New York" is also a state).
- `reading(chips: Chips | None) -> tuple[str | None, str | None] | None`: None without chips, on version 1, or with no part. Parts: roles, topics, institutions, tie, then `area_words(place)`, each to Required (need "must") or Wished; a leading word in `SOFTENERS = ("ideally", "preferably", "if possible")` and a trailing "if possible" dropped from each text, then the text cut to 60 characters with `cut` (line 119); empty texts skipped, repeats by `name_key` kept once. Returns `"Required: " + ", ".join(...)` and `"Wished: " + ", ".join(...)`, None when empty.
- `group_key(candidate, chips) -> str | None`: None when `is_open` (line 584), else `candidate.aside or "other"`; `outside` under chips without a place is `other`. `group_title(key, chips)`: `"Outside " + area_words(chips.place).removeprefix("in ")` for `outside`, else `GROUP_TITLES[key]`.
- `heading_of` (line 576) drops its aside branch; `results_headings` (line 592) takes `chips` and lists open people only.
- `aside_line(store, candidate, today) -> ReasonView | None` replaces `place_reason` (line 682): a stated place in its claim's words ("Based in Houston, TX"), an employer place as `f"Works at {org.name}, {place.text}"`, with the claim's source and no years.
- `card_view` (line 695): reason and second line are always `reason_of` and `fit_words`. For `outside` and `abroad` it sets `aside_line` and gives the card the view with `place=None` (role line ends after the employer); `fit_words` reads the original view.
- `results(..., group_shown: dict[str, int] | None = None)` (line 736): the shown and skipped loop (lines 749 to 760) becomes a helper, run on the open list with `shown` and per group with `group_shown.get(key, RESULTS_STEP)`. `cards` are open cards; `skipped_hidden` sums all lists; a group with no cards and a count of 0 is left out; one holding only skipped cards stays. `no_match`, only on a `done` version-2 search with someone kept and nobody open under heading 1: `f"FN found no {what}{place} with a known tie to Flanders or Belgium. "` plus `TIE_BELOW` under `parse.tie_must`, else `CLOSEST`; `what` is the role texts, else topic texts, joined "a, b or c", else "people"; `place` is `" " + area_words(...)` under `parse.place_must` only.
- `walk` (line 775) walks only the people whose `group_key` equals the key's.

### `src/fn/web/parts.py`

- `search_box(question, message=None, read=None)` (line 45) adds after the button `<p class="fn-search__read text-small"><span>{required}</span><span> · {wished}</span></p>`, no dot without a Required span.
- `person_card` (line 137) renders `aside_line` right after the role line: `<p class="fn-card__fit text-small">{text} · <a class="fn-card__source">{source}</a></p>`; `result_card` (line 182) passes it.
- `results_href` (line 169) gains `group=None, group_shown=RESULTS_STEP`, written as `group=` and, when not 20, `group_shown=`.
- `aside_group(group, cards, more, opened) -> Safe`: SetAside's markup with `data-group="{key}"`, `open` when opened.

### `src/fn/web/staff.py`

- `results_query` (line 401) also returns `group` (in `GROUP_KEYS`, else None) and `group_shown` (`shown_of`); callers and the poll URL pass them on; `geo_features` passes 0 per group.
- `person_cards` (line 177) returns the count line apart; puts `no_match` in `<p class="fn-note text-body">` above the headings; Show more counts `found.matched`; then `section_heading(SET_ASIDE, total)` and the groups in one `div`, cards linking with their group's `here` and shown count, `show_more(..., RESULTS_STEP, f"card-{next_key}")`, the query's group opened. Set-aside people alone give "0 people" and the groups, not the notice.
- `results_list` (line 203): one `<div role="status">` holds the status line while running and the count line when done; while running with a reading, `<template data-read>` holds the reading line.
- `search_page` passes `reading(search.chips)`; `person_page` (line 594) gives `search_back` (line 568) the card's `group_key`, which links with `shown=RESULTS_STEP`, `group` and `group_shown=shown`.
- `card_action` (line 471): for a fetch request it reads `group` and `group_shown` from the next URL as `results_query` does and passes the group's shown count to `result_card` when `group` is set.

### `src/fn/web/static/results.js`

`swap` keeps the old `[role=status]` element and gives it the fresh one's children; opens each fresh `details.fn-aside` exactly when its `data-group` was open; appends the fresh `template[data-read]` content to `.fn-search` when the form has no `.fn-search__read`.

## Strings used, from STRINGS.md

"Required: `{…}`", " · Wished: `{…}`", "in the Washington D.C. area", "in Maryland", "Set aside", "Other people found", "Outside `{place}`", "Outside the US", "Other roles or topics", "Based in `{place}` · `{source}`", "Works at `{organization}`, `{place}` · `{source}`", "`{shown}` of `{count}` shown", "Show 20 more", "Show `{n}` more", "`{count}` people · `{n}` not on the map · Export", the three "FN found no …" forms, "`{position}` of `{total}`".

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Who is set aside and why | `rank.aside`, unchanged |
| A person's list, group titles and counts | `present.group_key`, `present.results` |
| Words of the reading, no-match and set-aside lines | `present.reading`, `present.results`, `present.aside_line` |
| Markup | `parts.py` |
| Query, paging per group, back link | `staff.py` |
| Open groups, live element, reading line across a refresh | `results.js` |

## Inputs a real run will meet

Chips None while parse runs; version 1; "New York" (metro); "North Carolina" and "US West Coast" (`anywhere_us`); a tie chip with "ideally"; only wishes; a repeated or empty chip; a 300-character chip; "Maryland", "the Bay Area", `anywhere_us`; a group emptied by skips; 61 in a group; `group=died`, `group_shown=9999999`; `outside` without a place; everyone set aside; a skip inside a group; a running search.

## Tests (each must fail without the change)

- `tests/test_present.py`: `reading` and `area_words` on each input above, with "New York" (metro) giving "in the New York area", "North Carolina" (`anywhere_us`) "in North Carolina", "US West Coast" (`anywhere_us`) "in the US West Coast", "US" "in the US"; the nice tie "ideally someone connected to Flanders" giving "Wished: someone connected to Flanders"; a 300-character chip cut to 60 characters; with "Required: scientists, Belgian, in the Washington D.C. area" and "Required: founders, in the Boston area" plus "Wished: Flemish"; `group_key` without a place.
- `tests/test_results_headings.py`: the reading line after the button, none on Home or version 1, `template data-read` while running; groups in `GROUP_KEYS` order under "Set aside" and its total, empty ones out; an outside card's role line has no place and its set-aside line precedes the reason; "Works at Example Lab, Houston"; no extra line on an unfit card; 61 give 20 cards, "20 of 61 shown", `group=outside&group_shown=40`; everyone set aside gives "0 people"; the status div; each no-match form, none while running or with a heading-1 person; bad query values give the default page with every group closed and holding 20 cards; a group whose only person is skipped on this search stays, with the skipped card and no number.
- `tests/test_way_back.py`: an open card walks the open list; a group card walks its group and returns to it opened; a fetch Add on card 25 of a group returns a name link with `group_shown=40`.

## Existing tests that change, approved by the lead

- `tests/test_results_page.py` `BUNDLE_SHA` becomes version 13's hash.
- `tests/test_results_headings.py`: `AsideHeadingsTest.listing` gives the chips a must metro place "Boston". `test_the_aside_groups_follow_the_open_headings`: was three aside `h2` headings, now "Set aside 3" with "Outside the Boston area", "Outside the US", "Other roles or topics". `test_an_unfit_card_shows_the_fit_check_line`: was `UNFIT_LINE` in the card, now no line beyond the tie line. The import drops both deleted names.

No other existing test may change; stop and report.

## Recorded model answers and replay (S6)

No prompt or model call changes, so no recording or replay test changes.

## Hand check

`uv run python -m unittest` all green. On a copy of the owner's data with `FN_HTTP=replay FN_LLM=replay`, set the Washington place to must and `search.refinish` as in r1, run `FN_PORT=8791 uv run fn-serve`, screenshot the search at 1280 and 390 px beside `page-results-v13-*.png`. Each version-1 search's `/cards` fragment equals main's, the status div aside.

## Not doing

The died group, old-record line, lookup words, contact section and summary row, Look up more. Network people in a group (`rank.aside` keeps them open). `search.first_heading`, `score.py`, the export and the searches list still count set-aside people. The List and Map links keep dropping `group`, so switching view closes an opened group.
