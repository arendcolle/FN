# Task o2: researchers by place and topic, without a tie (D5)

## Goal

A live run of "Political scientists in New York City specializing in federal politics" gives 4 people in the match tiers and 81 set aside as outside the US, among them every person of the OpenAlex lane: the lane only searches works with a Belgian institution. This task adds one query per topic chip: works on the topic from the last six years with an author at an institution inside the area, keeping only the authors listed there. Owner: `lanes/openalex.py`. The ranker does not change.

## OpenAlex facts relied on (read 17 November 2026)

- `authorships.institutions.ror` (alias `institutions.ror`) filters works by the ROR id of an author's institution. https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/filter-works.md (the current page, https://help.openalex.org/api-entities/works/filter-works, lists only `institutions.id`). The lane already sends full ROR URLs in `last_known_institutions.ror` (openalex.py:90).
- `publication_year:>2020` is the inequality form for a number. https://help.openalex.org/how-to-use-the-api/get-lists-of-entities/filter-entity-lists
- `|` combines up to 100 values inside one filter. OR does not work across filters, and commas between filters mean AND. Same page.
- `per_page` runs from 1 to 100. https://help.openalex.org/how-to-use-the-api/get-lists-of-entities/paging
- Each `authorships[].institutions[]` holds `ror`. https://help.openalex.org/api-entities/works/work-object/authorship-object
- A search call costs 10 of 10,000 daily credits: 10 more per topic chip.

## What to build

### `src/fn/store.py`

`orgs_near(lat: float, lon: float, km: float) -> list[str]`, placed beside `persons_near` (line 488) and built with the same box: the ids of the orgs whose `lat` and `lon` fall in the box, ordered by id.

### `src/fn/lanes/openalex.py`

- Constants: `AREA_YEARS = 6` and `AREA_INSTITUTIONS = 100`.
- Structural first commit: move `see` out of `seen_authors` (line 78) to module level as `see(seen: dict[str, Seen], author: dict, how: str) -> Seen`. Move the body of the work loop (lines 107 to 112) into `see_work(seen, work: dict, how: str, keep: Callable[[dict], bool] = lambda _: True) -> None`. `keep` is called with each authorship. Behaviour stays byte for byte the same.
- `inside_rors(ctx, area: GeoArea) -> list[str]`: `ctx.store.orgs_near(area.lat, area.lon, area.radius_km)`, then `get_orgs` (store.py:454). Keep the `ror:` ids with `geo.distance_km` ≤ `area.radius_km`. Order them by `org_sizes` (store.py:815), largest first, with id breaking ties. Take the first `AREA_INSTITUTIONS` and return them as `https://ror.org/<id>`.
- `area_works(ctx, chips: Chips, area: GeoArea | None, seen, considered) -> tuple[list[str], list[str]]`: returns the query lines and the short ids of the authors it kept, in the order kept. Notes: "required place has no area; no works query by place" without an area, "no stored institution inside {area.city}; no works query by place" without institutions. Else, once per distinct topic text (casefolded), it sends `GET {API}/works` with `search=<topic>`, `filter=authorships.institutions.ror:<a>|<b>…,publication_year:>{as_of(ctx).year - AREA_YEARS}` (steps.py:39), `per_page=100` and `select=WORK_SELECT`. Each work goes to `see_work` with `how = f"works on {topic!r} in {area.city}"`, keeping an authorship only when one of its institutions has a `ror` in the set. An `HttpError` (net.py:45, which covers a replay miss) adds the note "works on {topic!r} in {area.city} failed: {exc}", and the lane goes on.
- `run` (line 299): after `place_area` (line 312), when `parse.place_must(chips)`, `parse.wants_research(chips)`, `not parse.tie_must(chips)` and `chips.topics` all hold, call `area_works` and add its lines to `queries`. This runs after every Belgian query, so authors already seen keep their order. Version-1 chips fail `place_must` (parse.py:95).
- `run`, fetch cap (line 314): one Belgian topic page with a consortium paper can fill `MAX_AUTHORS` alone, and area authors are seen last. Area authors get the fetch slots first, as the institution lists do (line 84): `fetched = list(dict.fromkeys([*area_ids, *ids]))[:MAX_AUTHORS]`, passed to `fetch`. Hits keep `seen` order. The "not fetched" reason (line 337) tests `author not in fetched_set` instead of `found.order >= MAX_AUTHORS`. Without an area query `area_ids` is empty, so both are unchanged.

## How the ranker treats such a person today (rank.py, unchanged)

An OpenAlex-only person without Belgian years gets the cut `no_belgian_evidence` from `cut_reason` (line 281).

- No tie chip, or a wished tie: `exempt` (line 309) brings back the first 20 (`EXEMPT_CAP`) in order that match the topic and are not abroad. A recent affiliation makes `job` `employer`, so `confirmed` (line 165) holds on a research question: tier 3 inside the area, tier 4 with an unknown place, both under "Topic, no known tie". Outside the area: kept with `aside` `outside` (line 258). `capped` skips research questions; `over_cap` caps headings 3 and 4 only.
- Yield: `search` matches title, abstract and full text, but `topic.match` reads stored titles only. Authors of area works without a topic word in the title are stored and then cut with `no_belgian_evidence`, so each 10-credit call gives fewer kept people than authors. The lead's live run measures it.
- Required tie: `exempt` returns nothing, so the cut stays. The lane sends no area query in that case.
- The card shows the name, a role line with the last known institution and its city, and the work title with its year from OpenAlex as the reason line. The second line has no tie words (`fit_words`, present.py:673), plus "place unknown" when no place is known.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| When the area query runs, what it sends, which authors it keeps | `lanes/openalex.py` |
| Which stored orgs lie in a box | `store.orgs_near` |
| Whether a chip is required | `parse.place_must`, `parse.tie_must`, `parse.wants_research` |
| Cuts, the exemption, tiers, aside | `rank.py` |

## Inputs a real run will meet

No stored org inside (test 1); 300 inside, 100 sent (4); `wikidata:` or `openalex:` orgs and an org beyond the radius (4); two equal topic chips (4); a state place with no area (1); only an institution chip (1); an empty works page and an authorship without institutions (2); an inside author whose last known institution is elsewhere, later set aside by the ranker (2); a replay miss or a 429 (5); Belgian pages that fill `MAX_AUTHORS` alone (6); required, wished or no tie and version-1 chips (1).

## Tests (each must fail without the change)

In `tests/test_openalex.py`, through the `search` helper, with made-up authors, an MIT org stored with Cambridge coordinates, and version-2 chips with topic "wind" and a required Boston place:

1. The area query is sent with the inside ROR, `publication_year:>` and `per_page=100`. It is not sent with a required tie, a wished place, no place chip, version-1 chips, no topic chip, or no inside org (the note is checked).
2. An author listed at the inside institution is a hit. A co-author listed elsewhere on the same work is not seen.
3. An inside author without any Belgian affiliation, on a work titled with the topic, is a kept candidate (`cut_reason` None, tier 3) on a question without a tie chip. The same author on a work whose title lacks the topic word is cut with `no_belgian_evidence`, which pins the dependence on `topic.match`.
4. 105 inside orgs give 100 RORs, the largest first. A `wikidata:` org and an org beyond the radius are left out. Two equal topic chips give one call.
5. A 404 or a replay miss on the area query leaves the Belgian hits and adds the note.
6. With `MAX_AUTHORS` patched to 3 and a Belgian page of 4 authors, an inside author from the area query is still fetched and is a hit; the fourth Belgian author gets "not fetched".
7. `store.orgs_near` returns an org in the box and leaves out one without coordinates (`tests/test_db.py`).

## Existing tests that change, approved by the lead

None. Existing lane tests use version-1 chips, and no recorded parse answer holds a required place. No existing test may change. If one fails, stop and report it.

## Recorded answers and replay (S6)

No prompt or model call changes, so no recorded model answer changes. A replay of a search recorded before this change misses the new HTTP call; the lane keeps its old hits and adds one note.

## Hand check

1. Run `uv run python -m unittest`. Every test must pass.
2. On a copy (`mkvar.sh o2`) of `var-bench-c1live-b`, run `FN_VAR=<copy> FN_HTTP=replay FN_LLM=replay uv run python -c '…'`. The script runs `openalex.run` on the stored chips of the federal politics search and compares its hits with the stored `lane:openalex` output. The hits must be the same, and there must be one more note: "failed", or "no stored institution inside" when the copy holds no org inside the area.
3. The live run is the lead's.

## Not doing

- A change to `exempt`, its cap or any rank rule.
- A second page of works.
- A query by role alone.
- Querying `openalex:` or `wikidata:` orgs.
- The `authorships.institutions.geo.city` filter: it ignores the radius, and D5 decides on stored orgs.
- Any model call.
