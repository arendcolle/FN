# Results page: the best 20 first, complete cards, a map that follows

**TL;DR.** The page size is one constant, `RESULTS_STEP = 50` (`src/fn/present.py:45`), used for the first page and for every "Show 50 more". Changing it to 20 is a one-line code change plus a wording change in the design system and one test. It will not make the results better: in the gold set, 3 of the 12 picks that reach the ranker sit in the first 20 and the median pick sits at position 104, so most good people will be behind "Show more" whatever the size. The cards have bigger gaps than the page size. In the newest live search 55% of the first 20 cards say "location not found", no card says why the person matches the question, and 43% of the cards with a place show an employer next to a place that belongs to another institution. The map draws all 510 people while the list shows 50, so most dots have no card. I propose 8 small changes. Four of them need the design system to change first, and none needs a new part, only a new element, state or wording.

## Method

- Read the code in the `quality` worktree (same as main): `present.py`, `web/staff.py`, `web/parts.py`, `static/results.js`, `static/map.js`, the lanes, `rank.py`.
- Read the design system artifact's READMEs for PersonCard, ShowMore, SectionHeading, MapMarker, Claim, ResultsLayout, StatusLine, Quote (published version `1794445194-d68f`). The site's STRINGS.md and DESIGN-NOTES.md match them.
- Measured on a backup copy of the owner's database (read-only backup, then the copy opened). Newest search `e4caaf4e` is the only one run with live calls on the current code. Scripts: `scratchpad/quality/results-page/q*.py`. Each takes a database path and a search id.

## Findings

### 1. Where the 50 is set and what it does

| Fact | Evidence |
|---|---|
| One constant sets the first page and the step | `present.py:45` `RESULTS_STEP = 50`. `results()` default `shown=RESULTS_STEP` (`present.py:276`). |
| A bad or missing `?shown=` falls back to 50 | `staff.py:337-341` `results_query`. A 1 to 6 digit number is accepted, so `?shown=999999` shows everyone. |
| "Show 50 more" is a plain GET link to `?shown=<shown+50>#card-<first new id>` | `staff.py:171`, `parts.py:270-281`. It reloads the page, so the map restarts and fits the bounds again (`map.js:34-39`, `fitted` is per page load). |
| Same constant in the URL builders | `parts.py:138-143` and `staff.py:196` drop `shown` from the URL when it equals 50. |
| Tests that fix the number | `tests/test_card_actions.py:161-176` (50 cards, "Show 50 more", bad values give 50). |
| Docs that fix the number | `notes/e2e/design-system/STRINGS.md:42`, `DESIGN-NOTES.md:28`, design-system ShowMore and ResultsLayout READMEs, `notes/e2e/design.md:112,174`, `notes/design/story-map.md:39,86`, `notes/mvp0/architecture.md:48`. |

How the pieces relate:

- **Cards.** `present.results()` (`present.py:276-304`) builds views for all kept candidates on every request, then makes cards for the first `shown` that are not skipped. Network candidates sort first (`store.py:553`), so they take places before "New" people.
- **Count line.** "510 people · 181 not on the map · Export" counts all kept people, not the shown ones (`present.py:301-304`). It is left out while the search runs (`staff.py:169`).
- **Sections.** Headings count all people of the section, not the shown ones (`staff.py:166`). "Show more" says "50 of 510 shown" under the last card.
- **Map.** `geo_features()` calls `results(..., shown=0)` and maps `network + new`, which is every kept person (`staff.py:229-232`). The design system says the same: "The map and the count line always cover the whole set" (ResultsLayout README). Measured: the list shows 17 people with a place in the first 50, the map draws 329 people on 127 points, and one point holds 58 people.
- **Live update.** `results.js:28-67` polls `/status` every 2 s and swaps `.fn-results__list` when the version changes. The swap URL is `data-cards`, built with the page's own `?shown=` (`staff.py:196-199`). The page size does not change during a run, the list re-sorts when a lane publishes, and the swap waits while the pointer or focus is on a card. In the newest search the lanes published at +7 s (seeds), +26 s (OpenAlex) and +4 min 17 s (web) after the start (`step_runs`), so the first 20 are stable for about 3 min 50 s and then reshuffle. "Show 50 more" stays visible during a run.
- **Cost.** `results()` costs the same for `shown=0`, 20 and 50: 0.145 s for 510 kept people and 0.43 s for 1,130 (best of 3, warm copy). The cost follows the number of kept people, not the page size. The full page also asks for the geo route, which does the same work again, and the poll repeats it every 2 s during a run. A smaller page saves nothing on the server; it saves reading time.

### 2. What a page of 20 holds (newest search, 510 kept, all in "New"; the network is empty in the owner's database)

| Measure | First 20 | First 50 | All 510 |
|---|---|---|---|
| Card says "location not found" | 55% | 66% | 35% |
| Card has no role (role line is the employer alone) | 85% | 92% | 96% |
| Card has no Belgian tie line | 0% | 2% | 7% |
| Evidence is a quote (prose source) | 45% | 48% | 31% |
| People with a map dot | 9 on 6 points | 17 on 8 points | 329 on 127 points |
| Found by lane | 10 OpenAlex, 7 seeds, 2 web, 1 both | 25, 17, 7, 1 | 349, 96, 64, 1 |

- The top of the list is less complete than the rest: seed-list and web people rank high and have no place. Of the 181 people without a place, 96 come from seed lists, 61 from web pages and 24 from OpenAlex institutions without coordinates (`q13.py`). 149 of the 181 have a Belgian organization on their card.
- Seed rows hold no place in three of the six lists (`data/seeds`: 0 of 3,577, 453 and 545 rows), 101 of 331 in a fourth, and all rows in two small lists (95 and 30 of 34). So the place cannot come from the seed row.
- Scores are flat: the kept scores run from 0.024 at rank 1 to 0.016 at rank 60 and 0.004 at the end (`q5.py`). Reciprocal rank fusion with K = 60 gives little spread, so the label "best" needs the ranker to earn it.
- Gold picks (`scripts/gold/cut_gate.py`, 12 picks reach the ranker): positions 2, 9, 10, 38, 94, 99, 111, 126, 129, 202, 235, 383. That is 3 in the first 20, 4 in the first 50, 6 in the first 100. The median is 104. A first page of 20 puts 9 of 12 picks behind at least one click, and 5 clicks of 20 reach the median pick.

### 3. What a card tells today, and what it does not

- Card content: name, `role · employer · place`, up to three Belgian organizations with years, one evidence item (a quote for prose sources, otherwise a statement with its citation) (`parts.py:119-135`).
- **Topic.** No card shows why the person matches the question. The OpenAlex lane knows it ("works on 'AI in health care'; last known <institution>, Boston, 0 km from Boston, US (inside the radius)", `lanes/openalex.py:255`, seen in the step payload), but it only lives in `LaneHit.matched_on` and the step payload. The candidate stores `reason_claim_ids`, which are institution and location claims. Only 94 of 510 people have a topic claim at all, all from seed pages, and the card never shows it because the evidence picks a Belgian-organization claim first (`present.py:62-67`).
- **Place is the institution's place.** OpenAlex gives 17,739 location claims, one kind only: the geo of the last known institution, dated the day it was read (`lanes/openalex.py:160-177`). `place_of` takes the newest dated location (`present.py:108-115`), and `employer_of` takes the newest job by a different rule (`present.py:48-51`). Result: for 329 people with a place, 186 show an employer whose name matches the place's institution, and 142 do not (one more has no employer). Example shapes: a hospital employer next to the city of a university; an association next to a university hospital's city. The card reads as if the employer sits in that city.
- **Several sources.** 1 of 510 people has claims from two source kinds, so the merge across lanes hardly happens in this search. A card names one source in its citation. The README bans record counts on cards, so no card shows "found in 2 places". `found_as` exists only on the Person page (`present.py:384-396`).
- **Missing place.** The string sits in three places: `parts.py:130, 209, 325`, plus tests `tests/test_web.py:237,275`, `tests/test_network_page.py:60`, STRINGS.md line 12, the PersonCard README and `plan.md:102`.

## Responsibility table

One owner per row. Rows marked "new" have no owner today.

| Responsibility | Owner |
|---|---|
| First page size and step (one value) | `present.py` constant, read by `parts.py` and `staff.py` |
| Which people count toward a page (new people only, or all) | `present.results` |
| Order of people | `rank.py` (not this note) |
| Why a lane listed a person, as data (topic text, institution) | each lane writes `LaneHit.matched`, `resolve` carries it, `rank` stores it on `Candidate` (new field) |
| City of an organization (name, coordinates) | `orgs.py`, from the ROR record it already fetches (`orgs.py:110-130` reads the city name and drops it) |
| Which place a person gets, and where it came from | `present.place_of` (new rule: the place of the employer's institution first) |
| Words of the card, the heading and the shown line | `present.py` view model, rendered by `parts.py` |
| Which dots the map draws and how they look | `present.geo` for the data, `map.js` for drawing |
| Every part, state and string | the design system artifact first, then STRINGS.md as its copy |

## Recommendations

Each item says: the change, the part it uses, whether the design system changes first, the strings, and the principle (all from `notes/e2e/research/ui-principles.md` and `ui-patterns.md`, plus the design notes that cite them).

1. **First page 20, step 20.** Set `RESULTS_STEP = 20`; keep one constant for both. Part: ShowMore. Design system first: edit the ShowMore and ResultsLayout READMEs from "50" to "20". No new part. Strings: "Show 20 more", "20 of 510 shown", and the last step "Show 10 more". Principle: Hick's law ("Start with the recommended or highest-ranked rows and mark them. Do not present the whole list as equal") and goal gradient ("50 of 518 shown", DESIGN-NOTES ShowMore). Carbon "load more" (patterns, section 5) stays the pattern. A step of 20 keeps one unit for the user; the cost is flat, so it is a reading decision only. Tests to change in the same change: `test_the_page_shows_fifty_kept_people_at_a_time`.
2. **Label the first block.** When "New" has more people than one page, the heading reads "Best matches" with the count of the cards shown (20, then 40). With one page or less it stays "New". "In your network" is unchanged. Part: SectionHeading. Design system first: the README says the count is "the number shown so far" only while a search runs; extend it to a long list, and add the words rule. No new part. Strings: "Best matches 20", "New 7". Principle: Hick's law (mark the highest-ranked rows) and chunking (Miller). Dependency: the word "best" is a promise. If the ranker owner cannot show a better order than today's flat scores, use "New" plus the shown line only.
3. **Do not let network people use up the first 20.** Count only new people toward the page; network cards keep their own block above. Owner: `present.results`. Design system: no change, the section order stays. Not measured: the owner's network is empty, so no search has a network section (0 of 1,154 candidates). Decide before staff import a network (open decision 1). Principle: the first-20 promise of recommendation 1 (Hick's law).
4. **A "why" line on the card.** One line under the ties line: the topic or institution the person was listed for. Part: PersonCard. Design system first: a new element `fn-card__why` in `text-small`, `muted`, between the ties line and the evidence, and a rule that it shows only when the lane gave a topic. Needs the structured `matched` field (table above). Strings, one per lane: "Works on {topic}" (OpenAlex works), "Listed for {field}" (seed list field), "Named on a page about {topic}" (web). An institution match needs no line, because the ties line already shows the tie. Principle: "Show where each fact came from" and "Start with the recommended rows and mark them"; the card's own README purpose, "just enough evidence to decide Add or Skip".
5. **Read the place as the employer's place, and label only the exception.** Pick the place from the same institution as the employer (`place_of`), and write the job line as `{role}, {employer}, {city}` so the city sits next to its employer. A stated residence ("lives_in", 3 placed claims in the whole database) reads "Lives in {city}". For people whose only place is a Belgian organization's city, give `orgs` the city and coordinates from the ROR record (149 of the 181 unplaced people have a Belgian organization), and read it the same way. Part: PersonCard and Claim. Design system first: one rule in the PersonCard README ("the place is the employer's city; a different basis is named"), no new part. Strings: "Lives in {city}"; no new label for the employer case, which is the default, so a label there would sit on nearly every card. Principle: conservation of complexity (the system carries the inference), Gestalt proximity, and "Show where each fact came from" (the full basis is one click away on the Person page, "Places").
6. **Better wording than "location not found".** On a card, leave the place out. The count line already says "181 not on the map" (state-coverage: "Show how many people lack a place and so are not on the map"). On the Person page, "Places" shows "Not provided" for an empty place, as the GOV.UK rule in patterns (rule 5, "Not provided") and the Person page do for contact details. Today 55% of the first 20 cards carry the phrase; repeating a gap on a third of the cards is noise. Part: PersonCard and NetworkRow. Design system first: change the line "Write 'location not found' when there is no place" in the PersonCard README, and the line in STRINGS.md. Strings: card, none; Person page, "Place: Not provided". Tests to change: `test_web.py:237,275`, `test_network_page.py:60`. Principle: "Mark missing fields as missing" (detail page) for the profile; one fact fewer on a card that already carries four. If the owner wants a visible word on the card, the only plain candidate is "Place unknown".
7. **Merged sources on a card.** When the person's facts come from more than one source label, the citation line names up to two, "OpenAlex record, 2025 · KVAB list, 2023", with no counts. The "possible match" state keeps its existing wording ("1 possible match", link to the profile). Part: PersonCard citation (`fn-cite`). Design system first: a one-line README change; the ban on record counts stays. Strings: none new. Principle: "One pattern per repeated situation" and "Show where each fact came from"; the README's rule "cards never show record counts" is kept. This only shows once the resolve step merges more records (1 of 510 today), so build it last.
8. **The map beyond the first 20.** Keep every placed person on the map, but draw the people on the shown cards as today's accent dots and everyone else as small muted dots. A click on a muted dot opens the popup with the name, role and employer and a link "Show in list" (`?shown=<n>#card-<id>`). Part: MapMarker. Design system first: a new state "not in the list yet" (radius 5, `rule-strong` fill, no hover link to a card). Data: add `listed: true|false` to the geo properties (`present.geo`), and have the geo route know `shown`. Strings: "Show in list". Principle: Gestalt connection ("selecting a row highlights its marker and the reverse"; a dot with no card breaks it), "Show how many people lack a place" (count line unchanged), and Baymard (patterns, section 3: users go to the map first to judge location, so keep the overview). Measured effect: the accent dots drop from 329 on 127 points to 9 on 6 points on page 1; the largest stack drops from 58 to 3. The cheaper alternative is to draw only the listed people (one argument change in `geo_features`), but then the map no longer covers the whole set and the README line must change.

Smallest first cut, in order: 1, 6, 5 (place choice only), 2, then 4, 8, 3, 7.

## What this does not fix

- The order. Three of 12 gold picks sit in the first 20. Cards that are complete and a page that is short make a weak order easier to read; they do not move a pick up. The rank researcher's findings decide whether recommendation 2 can use "Best".
- Duplicates across lanes. Recommendation 7 only displays what `resolve` merges.
- The server cost. It grows with kept people, not with the page. If a faster page is a goal, `results()` should build views for the shown cards and a light geo query for the map, and the geo route should not repeat the page's work. Not measured: browser render time for 20 vs 50 cards.

## Not measured

- A non-empty network (no search in the database has a network section), so recommendation 3 has no data.
- The page in a browser at 375 px and 1440 px, and the size of the HTML for 20 vs 50 cards.
- How many of the 142 mismatched employer and place pairs are spelling differences of the same institution. The sample I read were different institutions.
- Search `e4caaf4e` is one live search; the 25 older searches ran on older code, so I used them only for kept counts (205 to 1,130 kept people).

## Open decisions

1. **Do network people count toward the first 20?** Recommended: no, new people only; the owner decides before the first import.
2. **First block word.** "Best matches" if the ranker improves; "New" if not. Recommended: decide after the rank note.
3. **Map for people beyond the page.** Recommended: muted dots with "Show in list". Alternative: only listed people.
4. **A word for a missing place on the card.** Recommended: none. Alternative: "Place unknown".
5. **Step size.** Recommended: 20 for the first page and every step. Alternatives are a growing step (20, then 40) or one click for 50; the cost is the same.
6. **Show more while a search runs.** Today it shows during a run and reloads the page. Recommended: keep it; staff can act on cards during a run.
