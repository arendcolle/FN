# Plan: the pages of the second quality round

This section covers decisions U1 to U9 and the page side of R4 in [design.md](design.md). Six tasks: one design-system change, then five site tasks. Each ends in something that runs and merges on its own with the whole suite green.

## Tasks in order

| Task | What it does | Needs |
| --- | --- | --- |
| [UI-0](tasks/ui-0-design-system.md) | The design system: BackLink and SummaryList parts, the why block, the one-line Claim with its proof, the readable source page, the card's two lines, results headings, count markers as buttons, and the strings. Built at version 11; its `bundle.css` has sha256 `4f1a844883605813c3dd6c1e0faf0b156f2618607965ac516bf6094b5c41da81` | nothing |
| [UI-1](tasks/ui-1-way-back.md) | Copies the bundle and strings into the site, the only task that does. Every link and redirect keeps where the page was opened from; back links on every opened page; Previous and Next; the header tab; the list's scroll restore | UI-0 and the ranking track's Q-1 |
| [UI-2](tasks/ui-2-person-page.md) | The person page: summary, sections of one-line facts with the proof in place, the card's combined records, "Remove from network" and "Not correct" | UI-1 |
| [UI-3](tasks/ui-3-source-page.md) | The readable source page | UI-1 |
| [UI-5](tasks/ui-5-headings.md) | Tier headings in the results list | UI-1 and the ranking track's Q-4 |
| [UI-4](tasks/ui-4-card-and-map.md) | The card's reason line and second line, the why block, the map's opening view, clustering and keyboard markers | UI-2 and the ranking track's Q-4 |

The order of every task in both tracks, with what may run at the same time, is in [plan-quality.md](plan-quality.md), "Order across both tracks". In short: Q-1 merges before UI-1, since every pages task edits `present.py`; UI-2 and UI-3 follow UI-1; UI-5 and UI-4 wait for Q-4. UI-2, UI-3 and UI-5 change different functions; they share `present.py`, `parts.py`, `staff.py` and `contracts.py`, so expect conflicts only in import lists and new contract classes, resolved by keeping both. UI-4's map half (`map.js` only) could start after UI-1, but it ships with the card half to keep one task per decision.

## File map

| File | UI-1 | UI-2 | UI-3 | UI-4 | UI-5 |
| --- | --- | --- | --- | --- | --- |
| `src/fn/web/static/fn.css`, `notes/e2e/design-system/` | copy (only here) | | | | |
| `src/fn/contracts.py` | BackLink, ListPlace | SummaryRow; ProfileView, ClaimView fields | | ReasonView, WhyView; CardView, PersonView, ProfileView fields | ResultsHeading; ResultsView field |
| `src/fn/present.py` | `walk` | `employer_of`, `what_of`, `place_of`, `source_name`, `debris`, `proof_quote`, `group_of`, `fact_lines`, `tie_claim`, `card_records`, `profile` | `source_sentence`, `passage` | `reason_of`, `place_words`, `person_views`, `card_view`, `card`, `results` (passes fit and tie ids; conflicts with UI-5, merge UI-5 first); `why_of` goes | `HEADINGS`, `heading_of`, `results` |
| `src/fn/web/parts.py` | links, `back_line`, `profile_head`, `network_row`, claim anchors | `claim_line`, `summary_list`, `fact_groups`, `profile_state`, `found_as_block` | | `person_card`, `why_block` | |
| `src/fn/web/staff.py` | `back_link`, `person_here`, `person_page`, `card_action`, `network_block`, `geo_features`, `source_page` back, `reject` | `person_page`, `card_action` (accepts a person page as `next`) | `source_page`, `show_source` | `card_action`, `person_page`, `geo_features` (`place_fit`) | `person_cards` |
| `src/fn/web/static/` | `results.js`, `map.js` popup links | | | `map.js` | |
| New test file | `test_way_back.py` | `test_profile_page.py` | `test_source_page.py` | `test_card_lines.py` | `test_results_headings.py` |

## Interfaces

Between the page tasks:

- UI-1 gives `BackLink(label, href)`, `ListPlace(position, total, previous, next)`, `parts.person_href`, `parts.with_back`, `parts.back_line`, `staff.back_link`, `person_here` keeping `search`, `shown`, `card`, `back` and `all`, fact ids `claim-{id}` with redirects to them, and a `profile` link per listed person in the results geo answer.
- UI-2 gives `present.source_name`, `present.tie_claim(claims, facts, ids)`, `present.card_records(store, search_id, person_id, key)`, `ClaimView.source` and `.url`, `ProfileView.summary` and `.records`, and the page order UI-4 inserts the why block into.
- UI-3 gives `present.source_sentence` and `present.passage`.
- UI-4 gives `ReasonView`, `WhyView`, `CardView.reason` and `.fit`, `PersonView.tie` and `.tie_claim_id`.
- UI-5 gives `ResultsHeading(title, count, first_key)` and `ResultsView.headings`.

From the ranking track, which the page tasks only read:

- `Candidate.tier: int | None`, 1 to 7, None on rows stored before this round (UI-5).
- `Candidate.fit: CardFit | None` (Q-4, column `fit_json` in migration 012), None before this round and without evidence: `tie_grade: TieGrade = "none"` (`strong`, `medium`, `weak`, `none`), `tie_claim_ids: list[str] = []` (strongest first), `place: PlaceFit = "none"` (`inside`, `outside`, `abroad`, `unknown`, or `none` when the question has no place) and `role: RoleFit = "unknown"` (`met`, `fails`, `unknown`). UI-4 reads the grade, the tie claims and the place, and passes the place to the map through the geo answer; UI-5 reads the grade.
- `rank.heading(tier: int, tie_grade: TieGrade) -> int`, 1 to 4, tier 7 always 4 (UI-5). The pages never read `Chips.tie`, `Chips.version` or `parse.tie_must`: the ranker has already cut and ordered.
- Relation `origin` (Q-1), which `present.what_of` reads as "Origin: `{value}`" and `place_of` leaves out, both done in Q-1; UI-2 and UI-4 keep that wording.

## New responsibilities and their owners

| Responsibility | Owner |
| --- | --- |
| The origin of a page, its back link and label, and the redirects that keep it | `web/staff.py` (existing row) |
| The list order Previous and Next walk | `present.walk` |
| Whether a quote is debris, and the 25-word proof window | `present.debris`, `present.proof_quote` |
| The short source name on a fact line and a card | `present.source_name` |
| The tie a page names in words | `present.tie_claim` |
| The records a person page shows for a search | `present.card_records` |
| The source page's sentence and passage | `present.source_sentence`, `present.passage` |
| The card's reason line, second line and the why block | `present.reason_of`, `present.place_words` |
| The heading number of a tier | `rank.heading` (ranking track) |
| The words of a heading | `present.heading_of` |
| The list panel's scroll on Back | `static/results.js` |
| The map's opening view, clustering and keyboard markers | `static/map.js`, from the geo answer's `shown` and `place_fit` |

## Walkthrough findings each task closes

Every blocker and should in the two findings tables, from [research/ux-walk-walk-new.md](research/ux-walk-walk-new.md) (new) and [research/ux-walk-walk-check.md](research/ux-walk-walk-check.md) (check).

| Finding | Severity | Task |
| --- | --- | --- |
| Combined card opens a page with one record (new flow 3, check flow 9) | blocker | UI-2, with UI-1's links carrying the search |
| Back from a person at 1280 px returns to card 1 (new flows 1, 4, 8; check flows 1, 8) | blocker | UI-1 |
| Back from a source at 1280 px returns to card 1 (check flows 2, 8) | blocker | UI-1 |
| Card 27, Back, panel at card 1 (check flows 4, 8) | blocker | UI-1 |
| "Back to the results" lands on card 1 and drops shown (check flows 1, 4) | should | UI-1 |
| Source page: no back link, no person or fact, lands mid-text (new flows 2, 3; check flow 2) | should | UI-1 back link (the card's quote link until UI-4 replaces it with the reason's source link), UI-3 page |
| Possible-match page has no way back (both) | should | UI-1 |
| Person from a map popup has no way back (both) | should | UI-1 |
| Person from the Network list has no way back (check flow 7) | should | UI-1 |
| Back to the map: list at card 1 (check flows 5, 8) | should | UI-1 (the list's scroll; the popup is left out) |
| Only 2 of 9 count markers can be clicked (both) | should | UI-4 |
| Count markers have no tabindex (check flow 5) | should | UI-4 |
| Two "Remove" with different meanings (both) | should | UI-2 |
| After Remove of a fact, nothing confirms it on screen (check flow 6) | should | UI-1 anchor, UI-2 line kept in place |
| Headline names a past employer after a fact is removed (new flow 6) | should | UI-2 |
| Raw scraper quotes that prove nothing (new flows 1, 2) | should | UI-2 proof rules, UI-4 no quote on cards |

Nits closed on the way: the header marks Network on a person from a search (UI-1); the removed fact moves to the end (UI-2); "Matches: ai, health, care", the same organization twice on a card, "date unknown" on 48 cards (UI-4); the map opens on the world (UI-4).

Left out, all nits: history entries added by each post (no task replaces history); the popup closed after Back; menus as text on the source page (the passage keeps most of them off the first screen); the red "Some sources could not be read"; a blank square in the headless map; the popup cut at 390 px; Network filters `new` and `import` not on screen; one sentence quoted under three facts (now behind the proof); 13 ties and 58 work facts on a match page (three per section now).

## Done check

1. The whole suite is green: `uv run python -m unittest`.
2. The two walkthroughs run again with their flows and widths, on a throwaway copy with `fn-rerank --all` run first. Neither reports a blocker or a should.
3. Word counts on 20 cards of a stored search and 5 person pages, measured as the research did (`innerText`, forms and the content of closed `details` left out): median card at most 25 words, every person page's first screen at most 90.
4. The test files of UI-2 and UI-4 hold the same budgets on fixtures, so a later change that breaks them fails a test.

## Open questions for the lead

1. **"elsewhere in the US" and "outside the US"** assume the question's country is the US, as in every benchmark question. A question about another country would read wrong. Proposal: accept for this round.
2. **The card drops its line of Belgian organizations with years.** The 25-word budget cannot hold it next to the reason and the second line, which names the tie. Confirm, since the owner likes the results page.

Settled by the lead's rulings in [design.md](design.md), and written into the tasks: the ranker stores `Candidate.fit` next to the tier in migration 012 (UI-4); tier 7 is always "Other people found" (UI-5); the walk line counts the whole list, "4 of 143" (UI-1); a past job never names the current employer (UI-2); "Studied" is the newest study claim (UI-2); the map opens on the shown people inside the asked area when there is one (UI-4); the text budget is a median of at most 25 words a card, none over 30, and at most 90 words on a person page's first screen (UI-2, UI-4).

## The design system as built, version 11

The tasks copy the built parts and the mockups `ds/preview/page-person-v11.html`, `page-source-v11.html` and `page-results-v11.html`. What changed against the first drafts of the tasks:

- UI-1 pins `BUNDLE_SHA` to the sha256 above. The results label cuts the question at 60 characters at a word; the walk line drops " · " with a missing Previous or Next; a fact's source link returns to `#claim-{id}`.
- UI-2: section headings are `h2.fn-section text-title` inside `section.fn-profile__section`. In a claim, the what span and the proof `details` sit inline in `fn-claim__line` with a space between them, and "Not correct" is its own form, a direct child of `fn-claim__head`. A record's proof has no quote, and only an `fn:` url drops "Original page". A date that is not known is left out. Show more is `p.fn-more > a.fn-link` to `?all={anchor}#{anchor}`, without a "3 of 5 shown" line. Sources is left out with one record.
- UI-2, two Profile rules the lead added after the mockup: each fact stands in one section only (a Belgian job under Work, a Belgian degree under Education, and "Ties to Flanders and Belgium" holds a birthplace, an origin, a fellowship, a membership, a consul's post or a list entry), and Places is left out when its only fact is the place the head shows.
- UI-3: the source page sits in `main.fn-source`, with `p.fn-source__url` and the stored record's `summary.text-meta`.
- UI-4: the card's second line says "No known tie to Flanders" when there are no tie words. The why block's first line leaves out the source name, and its place line starts with a capital.
- Every word budget leaves out forms and the content of closed `details`.

## Where the design does not fit the code

- Tier 4 in [research/tiers.md](research/tiers.md) held "a tie and abroad" under "Topic, no known tie". The seven tiers of the lead's ruling put those people in tier 2, abroad last, and `rank.heading` splits tier 6 by its tie.
- The map already fits its dots with maximum zoom 11 (`src/fn/web/static/map.js:36`, `:199`). It opens on the world because the bounds hold every person, Belgians included. Fitting to the shown people helps only when the first 20 are local; Belgian people among them still widen the view.
- U3's "Studied: the highest degree" cannot be built: no claim stores a degree level. The lead ruled the newest `studied_at`; UI-2 shows it.
- An `origin` location claim would make "Belgian" a person's place. Q-1 skips it in `evidence.places`, `store.unlocated_places` and `present.place_of`, and merges before every pages task.
- The site's copy of the strings (`notes/e2e/design-system/`) is newer than the design system's working copy; UI-0 starts from the site's copy.
- `fn.css` is pinned by hash (`tests/test_results_page.py:25`), so only UI-1 copies the bundle. A later page task that needs a new class must stop and ask for a design-system change.
- The debris rule leaves out a correct but short quote, such as a name and an organization only; the title and links remain.
