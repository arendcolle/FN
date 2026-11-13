# Task UI-4: the card's two lines, the why block and the map

## Goal

A card has a median of 41.5 words, 30 of them a quote, on 19 of 20 cards; some quotes are debris, "Matches: ai, health, care" echoes the question, and 48 of 143 cards say "date unknown" ([research/ux-patterns.md](../research/ux-patterns.md), walk-new). The map opens on the whole world for a Boston question, only 2 of 9 count markers can be clicked, and Tab skips them (walk-check, flow 5). Decisions U7 and U9, and the why block of U3, in [design.md](../design.md). Text budget: 25 words a card, 90 on a person page's first screen.

## Before you start

UI-2 is merged (`source_name`, `tie_claim`, `card_records`, the page layout), and UI-1 has copied the bundle; do not copy it again. The ranking track's tier task Q-4 is merged: `Candidate.fit` below exists and fresh searches store it. Read the design system's `PersonCard`, `Profile` (why block) and `MapMarker` part files and `ds/preview/page-results-v11.html` and `page-person-v11.html`, and copy their markup. If you need a class or a string the design system does not have, stop and report it.

## Markup, from the design system

- Card, in this order: `h3.fn-card__name text-name` with the name link; `p.fn-card__role text-body`; `<p class="fn-card__reason text-body">Founder and CEO, Fictional Robotics · <a class="fn-card__source" href="…">fictionalrobotics.com</a></p>`; `<p class="fn-card__fit text-small">Studied at KU Leuven · elsewhere in the US</p>`; `<p class="fn-card__combined text-small"><a href="…#sources">Combined from 2 records</a></p>`; `div.fn-card__acts`.
- Why block: `<section class="fn-why"><h2 class="fn-section text-label">Why for this search</h2><ul class="fn-why__lines text-body"><li>…</li></ul></section>`. Up to three lines: the reason's text without its source name, the tie words or "No known tie to Flanders", and the place words with a capital first letter ("In New York", "Elsewhere in the US", "Place unknown"). A line with nothing to say is left out.
- Count marker: `<button type="button" class="fn-marker fn-marker--count text-label" aria-label="4 people near Boston">4</button>`. Its popup starts with `fn-popup__count text-label` reading the same words, then lists everyone with their name links, and no "Open profile".

## What you read from the ranking track

`Candidate.fit: CardFit | None` (Q-4), None on rows stored before this round and on a candidate without evidence, with `class CardFit(Model): tie_grade: TieGrade = "none"; tie_claim_ids: list[str] = []; place: PlaceFit = "none"; role: RoleFit = "unknown"`, where `TieGrade = Literal["strong", "medium", "weak", "none"]`, `PlaceFit = Literal["inside", "outside", "abroad", "unknown", "none"]` and `RoleFit = Literal["met", "fails", "unknown"]`, all in `contracts.py`. `tie_claim_ids` is strongest first. `place` (`rank.place_fit`) is `inside` within the asked metro area, or within the asked country when the question names no metro area; `outside` placed but not inside the area; `abroad` placed only outside the country; `unknown` with no place; `none` when the question has no place. A page never works these out itself: it makes no outside call. And `Search.chips.place` (`text`, `kind`). If a field has another name or type when you start, stop and report it.

## What to build

1. `src/fn/present.py`: `reason_of(view: ClaimView, href: str) -> ReasonView | None`. Text: `view.what`, cut at a word with "…" so that its words, the words of ", `{years}`" (when there are years) and the words of `view.source` are at most 15 together; then ", `{years}`". `class ReasonView(Model): text: str; source: str; href: str` in `contracts.py`. None when the card has no evidence claim.
2. `place_words(search: Search, fit: CardFit | None) -> str | None`: None when there is no place chip, its kind is `abroad`, `fit` is None, or `fit.place` is `none`. `inside`: "in `{place chip text}`", or "in the US" for kind `anywhere_us`; `outside`: "elsewhere in the US"; `abroad`: "outside the US"; `unknown`: "place unknown".
3. Tie words: `what_of` of `tie_claim(claims, facts, ids)`, where `ids` is `fit_tie(fit)` when the candidate has `fit`, else `evidence_tie(store, persons, claims, facts, today)` (an old search); both come from the person page content task and give no ids unless the tie is strong or medium. With no tie words, the second line and the why block say "No known tie to Flanders" (PersonCard part). `person_views(..., ties: list[list[str]] | None = None)` passes the ids per group; `PersonView` gains `tie: str | None = None` and `tie_claim_id: str | None = None`.
4. `CardView` loses `why` and gains `reason: ReasonView | None = None` and `fit: str | None = None`: the tie words, or "No known tie to Flanders" when there are none, and the place words, joined by " · ". The tie part is left out when `tie_claim_id` is the reason's claim, because the reason already names the tie. `why_of` (`present.py:306`) goes. `card(store, candidate, today)` becomes `card(store, search, candidate, today)`; `card_action` passes the search.
5. The why block: `class WhyView(Model): reason: ReasonView | None = None; tie: str; place: str | None = None`, `ProfileView.why: WhyView | None = None`, built in `person_page` only when `card_records` found the candidate; `person_page` reads that candidate's `fit` and reason by its key (`candidate_of(store, search_id, key)`). `tie` is the tie words or "No known tie to Flanders".
6. `src/fn/web/parts.py`: `person_card` shows the card markup above, in its order. The reason's source links to `view.href` with `back` set to the results url and `#card-{key}`. No orgs line, no quote, no statement, no "Matches:" line. `quote` and `statement` go if nothing calls them. `why_block(why)` renders the why block markup after the head on the person page, before the summary; its first line is `why.reason.text` only.
7. `src/fn/web/staff.py` `geo_features` (`staff.py:229`): each `listed` entry gains `"place_fit"`, the `fit.place` of the kept candidate whose card key it is (`store.list_candidates(search.id, kept_only=True)` by `person_id`), or None. `src/fn/web/static/map.js` copies it onto the person as it copies `shown` (`map.js:140`).
8. `src/fn/web/static/map.js`: fit the opening view to the spots with at least one shown person (`shown !== false`) whose `place_fit` is `inside` (lead's ruling); when there is none, to the spots with at least one shown person; else all spots, keeping 64 px padding and `maxZoom: 11` (`map.js:36`). Put every spot in the `people` source, shared spots too (today they are separate HTML markers, `map.js:157-181`), each with a `count` property (its people). Give the source `cluster: true`, `clusterRadius: 40`, `clusterMaxZoom: 10` and `clusterProperties: {people: ["+", ["get", "count"]]}`, since `point_count` counts spots, not people. Draw an unclustered spot of one person as today, and every cluster and every spot with `count` > 1 as the count marker button above, labelled with its people (`people` for a cluster, `count` for a spot), with `aria-label` "`{n}` people near `{city}`" (the first person's place up to its first comma), or "`{n}` people here" when nobody has a place. A cluster's people are the people of the spots `getClusterLeaves` returns. Enter, Space and a click open the popup; Esc closes it and moves focus back to its marker. Rebuild the buttons on `moveend`.

## Templates, with examples (made-up people)

Reason: `{what}[, {years}] · {source}`. Second line: `{tie words} · {place words}`, either part left out when empty.

| Person | Stored claims | Reason line | Second line |
| --- | --- | --- | --- |
| Seed person on a Belgian fellows list, topic matched on a web page | `fellow_of` the fellows' foundation (BE); `topic` "AI in health care" quoted on example.org; location Cambridge, MA; fit strong tie (a BAEF row), inside, place chip "Boston" | Field: AI in health care · example.org | Fellow of Belgian American Educational Foundation · in Boston |
| OpenAlex person | topic claim from an OpenAlex work, 2023, titled "Deep learning for early warning of sepsis in intensive care units across three Boston hospitals"; `studied_at` KU Leuven 2012–2017; location Seattle, WA; fit strong tie, outside | Paper: Deep learning for early warning of sepsis in intensive care units…, 2023 · OpenAlex work | Studied at KU Leuven · elsewhere in the US |
| Web person | role "Founder and CEO, Fictional Robotics" on fictionalrobotics.com; `origin` "Belgian"; no place; fit strong tie with the origin claim first, unknown | Founder and CEO, Fictional Robotics · fictionalrobotics.com | Origin: Belgian · place unknown |
| Old search, no fit | `worked_at` ULB 2013–2018 | Worked at ULB, 2013–2018 · example.org | (no second line: the reason names the tie) |
| Web person, no tie | role "Director of robotics, Example Health" on examplehealth.org; location Boston, MA; fit tie none, inside, place chip "Boston" | Director of robotics, Example Health · examplehealth.org | No known tie to Flanders · in Boston |

## Inputs a real run will meet

A search stored before this round (no fit, no headings); a card with no evidence claim (role line only); a card whose evidence claim is its tie claim; a 40-word role value; a 300-character paper title; a source with no title and an `fn:` url; a question with no place chip, a place of kind `abroad`, `anywhere_us`; a weak tie only; 120 people on one city; 9 count markers over Belgium at world zoom; nobody shown with a place.

## Tests

In a new file `tests/test_card_lines.py`, with made-up names. Each must fail without the change.

- The five rows of the table above give exactly those two lines, in `p.fn-card__reason` with `a.fn-card__source` and `p.fn-card__fit`.
- A reason never passes 15 words; a 40-word role is cut with "…"; no card shows "date unknown", "Matches:" or a `blockquote`.
- `place_words` for each `fit.place` value and each place-chip kind, and None without fit.
- The text budget: a fixture search of 20 made-up people with 30-word quotes, roles, ties and places. Count the words of each `article.fn-card` with its forms removed: the median is at most 25 and no card passes 30. Five person pages opened from that search: at most 90 words in `main` before the first section heading, with `<form>` elements and the content of closed `details` left out.
- The results geo answer gives each listed person its `place_fit`, and None for a search stored before this round.
- The why block shows on a page opened with `search` and `card`, between the head and the summary, with "No known tie to Flanders" for a person without a tie, the place line capitalised ("In Boston"), and no source name in its first line; it does not show without `search`.

## Existing tests that change, approved

- `tests/test_results_page.py`: `test_the_why_line_names_the_topic_words_and_an_employer_place` is removed, because the why line is gone; `test_the_evidence_is_the_topic_claim_and_a_work_reads_as_a_paper`, its card assertions become the reason line.
- `tests/test_web.py`: `test_a_card_shows_employer_place_belgian_orgs_and_one_quote`, the orgs-line and quote assertions become the reason line; `test_a_card_from_a_record_states_the_fact_and_never_quotes_the_record`, the `fn-fact` and `fn-cite` assertions become the reason line.

No other existing test may change. Run `uv run python -m unittest`.

## Hand check

Throwaway var folder (`mkvar.sh ui4`), `FN_LLM=replay`, `uv run fn-rerank --all`, `uv run fn-serve` on your port. Headless Playwright at 1280 px and 390 px on a Boston search: screenshot the first screen; log the map's zoom and whether every shown dot whose `place_fit` is `inside` is inside the view; for each count marker log whether `document.elementFromPoint` at its centre is that marker and whether its number equals the people its popup lists; at world zoom log that no two markers overlap; Tab to the first marker, press Enter, screenshot, press Esc and log `document.activeElement`. Pass: every marker clickable, focus back on the marker. Give the paths and say what you see, without names.

## Not doing

- Tier headings (UI-5); the wishes line of met and unmet wishes (the headings replace it).
- Focusable single-person dots; a custom spiderfy; the popup's place at 390 px.
- Any change to the order or to what the ranker stores.
