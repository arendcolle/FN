# Task T6: one view model for a person, and one format for a claim

Branch `feat/person-views`. After this task a result card is built from a `PersonView`, and a claim reads the same way wherever it shows. The Network page, the Person page, the map popup and the export will use the same view model in later tasks.

Read first: [design.md](../design.md) ("Design rules" 3, "Candidates and the cut", "Modules and who owns what"), the plan's ["T6 provides"](../plan.md#t6-provides), `research/web.md` section 3 (how a card is built today) and the design system's PersonCard, Claim and Quote parts (the prompt says where its files are).

## Why

- A card for an OpenAlex or LinkedIn person quotes a raw record line, such as `affiliations.19.institution.display_name: …` with fifteen years listed. The to-do list asks for one fixed display format for claims, defined in the contracts.
- A card pools the claims of every same-name record, also records no lane found (`src/fn/web/staff.py` `person_cards`). The design says a card shows its hit records only.
- The rules for how a person reads sit in functions that take raw claims (`src/fn/present.py`). The card, the row, the profile, the popup and the export need the same answers.
- `web/parts.py` `notice` reads the store. Parts turn view models into HTML and read nothing.

## What changes

### 1. View models in `contracts.py`

Frozen models, as in the plan:

- `QuoteView(text, label, href, date)`: the quote cut for a card or in full, the citation label, the link to the Source page and the date in words.
- `ClaimView(claim_id, kind, what, years, quote: QuoteView | None, label, href, date, is_new)`.
- `TieView(org, years)`.
- `PersonView(person_id, name, role, employer, place, lat, lon, ties: list[TieView], more_ties, evidence: ClaimView | None, status, added, new_facts, email, phone)`.
- `ResultsView(network: list[PersonView], new: list[PersonView])`.

### 2. `present.py`: the one place that words a claim

`claim_view(claim, source, org, seen_at=None, cut_quote=True) -> ClaimView`:

- `what` is the fact in plain words:

| Claim | `what` |
| --- | --- |
| relation `studied_at` | Studied at KU Leuven |
| relation `works_at` | Works at Columbia University |
| relation `worked_at` | Worked at imec |
| relation `affiliated_with` | Affiliated with KU Leuven |
| relation `hosted_by` | Hosted by MIT |
| relation `member_of` | Member of KVAB |
| relation `fellow_of` | Fellow of the Belgian American Educational Foundation |
| relation `consul_for` | Honorary consul for Belgium |
| kind `role` | the claim's value as it is |
| kind `topic` | Field: the value |
| kind `location`, relation `born_in` | Born in Leuven |
| kind `location`, any other | Based in Boston |
| kind `email`, `phone` | Email: the value; Phone: the value |
| kind `availability` | the value as it is |

  The organization is the `orgs` row's name when the claim has an `org_id` with a stored row, else the claim's value. A role claim keeps its value, because seed rows already hold a readable role.
- `years` is the years the claim covers as runs with an en dash: "2008–2013", "2001, 2008", or empty. Use `rank.units`, and leave out "undated".
- `quote` is set only when the source is prose: kind `page`, `seed_page` or `vendor_page`. A `record`, `vendor_record`, `import` or `staff` source gives no quote, because its text is a line of a data record. The quote text follows the rules `parts.quote_block` has today (quote marks, inner quotes, cut at 240 characters when `cut_quote`).
- `label`, `href` and `date` are the citation: the label is "OpenAlex record" for kind `record`, "LinkedIn profile" for `vendor_record`, the file name and row for `import` ("contacts.csv, row 14"), "Typed by staff" for `staff`, and for prose sources the title, else the host. `href` is the Source page link with the claim marked. `date` is `date_words`.
- `is_new` is true when `seen_at` is given and the claim's `first_seen_at` is later.

`person_views(store, groups: list[list[str]], today) -> list[PersonView]`: one view per group of person ids, read with one `claims_of` call for all groups.

- `name`: the display name of the group's first person.
- `employer`: as `employer_of` today. `role`: the value of the newest claim of kind `role` that describes a job. A seed list role (relation `fellow_of`, `member_of`, `consul_for`) is not a job. A web-page role whose value equals its source's title or host is not one either: check how `extract.py` fills a role without a mention role, and report how many of the stored web-page role claims are real roles.
- `place`, `lat`, `lon`: the newest dated location claim with coordinates, else an undated one with coordinates, else the text of the newest location claim without a dot. A `born_in` claim is never the place.
- `ties`: the first three Belgian organizations with their years as today's card shows them (first to last year), and `more_ties` for the rest.
- `evidence`: the claim today's `evidence` picks, as a `ClaimView`.
- `status`: the person's `list_status`. `added`: the date of the person's latest `add` event in words ("3 November 2026"), else `None`. `new_facts`: how many claims are new for a person in the network, else 0. `email`, `phone`: the newest value of each kind, else `None`.

`results(store, search, today) -> ResultsView`: the search's candidates as views, split by section, each built from the candidate's `hit_person_ids`, or from its first person when that list is empty. T10 and T11 add paging, skipped and cut handling here.

Keep `sources_read` in `present.py`. Delete the functions in `present.py` that nothing calls after this change.

### 3. `web/parts.py` and `web/staff.py`

- `parts.person_card(view: PersonView)` builds the card from the view and nothing else: name, the role line ("Research scientist, Columbia University · New York, NY", leaving out what is missing, "location not found" when there is no place), the ties line, then the evidence. Evidence with a quote looks as today. Evidence without a quote is one line with `what` and the years in `text-year`, and the citation under it, in the Quote part's citation style.
- `parts.notice` takes what it shows (the search and the count of sources read) and no store.
- `staff.search_page` and the geo JSON read `present.results`. One map point per person. Keep the properties `map.js` reads. The name stays plain text; the link to the Person page comes with that page in T8.
- The debug pages do not change. They keep showing every record of a card.

## Tests

New `tests/test_present.py`:

1. `claim_view` words each row of the table above, with the org name from the `orgs` row when there is one.
2. A claim from a `record` source has no quote and the label "OpenAlex record"; one from a `vendor_page` source has its quote and the page title.
3. `years` shows runs: 2008 to 2013 as "2008–2013", and 2001 with 2008 as "2001, 2008".
4. `person_views`: a person with a dated located claim and a newer undated one keeps the dated place; a person with only an undated located claim gets it; a `born_in` claim is never the place.
5. `person_views`: a seed list role is not the job role, and a web-page role equal to the page title is not one.
6. `results`: a card is built from its hit records only. Build a candidate with a hit record and a same-name record no lane hit, and check that the second one's employer is not on the card.
7. `is_new` and `new_facts` follow `seen_at`.

In `tests/test_web.py`: a results page for a search with an OpenAlex person shows the statement line and "OpenAlex record", and no raw record line (assert that the text `display_name:` is not in the page).

Existing tests that assert the raw record quote on a staff card change on purpose. List each one in your report with the old and the new expectation. Any other failing existing test: stop and report.

## Hand check

On a throwaway copy of the owner's database, fetch the results page of search `f10ee197-4c35-48f1-80f6-07cdbceae261` with `TestClient` before and after the change. Report the first card's text before and after, and the page size in bytes before and after. Then start the server on a port from your range and open that page: paste the first three cards' text as the browser shows it.

## Notes from the network core review

- `store.claims_of` now returns each claim under its canonical person id. A stored search can hold the id of a record that was merged later, so map every candidate person id through `store.canonical_ids` before you group claims, or a merged person's card shows no claims.
- The site's `fn.css` now holds the design system's classes for a statement without a quote: `fn-fact` for the line and `fn-cite` for its citation. Use them as the PersonCard preview does.
- The exact words for every string are in `notes/e2e/design-system/STRINGS.md`.

## Decided while building

- The view model for an organization with its years is `OrgView`, with `orgs` and `more_orgs` on `PersonView`. The done check bans the old label's name in code, so the plan's `TieView` could not be used.
- `tests/test_map.py` changes on purpose: the geo JSON gives one point per card from its hit records, an undated place with coordinates counts when there is no dated one, and the properties are `id`, `name`, `employer`, `place` and `section`. The quote, the claim date and the source link are gone from it, because no page shows them.
- Citation labels follow STRINGS.md: "OpenAlex record", "LinkedIn record", "Import <file>, row <n>" and "Entered in FN".

## Not in this task

Add and Skip buttons, the Person page, links from names, the Network page, paging, the cut. The card's look is the design system's PersonCard as it is; add no CSS.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish. Every test must pass.
- `present.py` returns view models and builds no HTML. `web/parts.py` builds HTML from view models and reads nothing from the store. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit: short functions, docstrings of one to five lines, single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
