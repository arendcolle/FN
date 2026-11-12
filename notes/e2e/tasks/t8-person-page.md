# Task T8: the Person page

Branch `feat/person-page`. After this task `/people/{id}` shows one person with every fact and its source, lets staff edit the contact details, remove a wrong fact, separate a wrong record, decide a possible match, and add or remove the person, each with Undo.

Read first: [design.md](../design.md) "What staff decisions do", "Claims" and "Events"; [panel-records.md](../panel-records.md) records D5 and D7; the plan's ["T8 provides"](../plan.md#t8-provides); the design system parts Profile, Claim, Field, Banner, ShowMore and Button; the mockups `page-person.html` and `page-person-candidate.html`; the Person strings in `notes/e2e/design-system/STRINGS.md`; and `src/fn/network.py`, `src/fn/present.py`, `src/fn/web/staff.py` and `src/fn/web/parts.py` as they are now.

## What changes

### 1. `present.profile(store, person_id, today) -> ProfileView | None`

A frozen `ProfileView` in `contracts.py`, built from the person's canonical record:

- `person: PersonView`.
- `contact`: one entry for email and one for phone, each with its newest value as a `ClaimView` or nothing ("Not provided").
- `facts`: groups in this order, each a title and its `ClaimView`s, an empty group left out: "Ties to Belgium" (claims at an organization with `country_code = BE`), "Work" (every other affiliation, role and topic claim) and "Places" (location claims).
  - A fact the person holds from several sources shows once: claims with the same kind, relation and organization or value are one line, with the years of all of them, the citation of the newest, and `is_new` when any of them is new.
  - Within a group, new facts first, then newest first.
  - A group shows its first 10 facts and "Show 23 more", which reloads the page with every fact of every group.
- `found_as`: one entry per source the person was found in (label, link to the Source page, number of facts) with the id of the record it belongs to. A person with one record has no "Found as".
- `possible`: the `PersonView`s of `network.possible_matches`.
- `name_match`: for a person who is not in the network, the first of `network.name_matches`, else nothing.
- `last`: the person's latest event when it can still be undone, with the words the page shows for it (see below).

### 2. Routes in `web/staff.py`

- `GET /people/{id}`. An unknown id is a 404. The id of a merged record redirects (303) to its person. The page renders the "New" marks and then calls `network.mark_seen` for a person in the network, so the marks are gone on the next visit. `?from=card`, `row`, `popup` or `import` goes into `request.state.facts` as `from`, for the request log. `?edit=email` or `?edit=phone` opens that field. `?all=1` shows every fact.
- `POST /people/{id}/add`, `/skip`, `/remove`, `/contact` (fields `kind`, `value`, `replaces`), `/merge` (field `other`: the other person joins this one), `/not-same` (field `other`), `POST /claims/{id}/reject` and `POST /events/{id}/undo`. Each calls the matching `network` function, then redirects (303) to the path in the hidden field `next` when it is a path on this site, else to the person's page. Pressing a button twice changes nothing the second time.
- A value `network.set_contact` refuses re-renders the page with the field open, the message under it, and status 400.
- An undo `network.undo` refuses redirects back with a Banner: "This could not be undone, because <name> changed since." The Banner text travels as a short code in the query string, never as free text.

### 3. The page

Follow the mockups and the Profile part.

- Head: the name, the role line, the place. In the network: "In your network since 3 November 2026" with Remove. Not in the network: Add and Skip, or "Same name as <name> in your network" with Same person, Add as new and Skip when there is a name match. A back link "Back to the results for “…”" when the page was reached from a search (`?search=<id>`).
- Contact: Email and Phone, each with its value and where it came from, or "Not provided", and Edit. Edit shows the Field with Save and Cancel.
- Facts: each as the Claim part, with its quote in full when the source is prose, the "New" mark, and Remove.
- "Found as" and "Possible matches" as the Profile part shows them.
- After a decision the page shows what happened where it happened, with Undo, as long as that decision is the person's latest: "Added to your network · Undo", "<fact> · Removed · Undo", "Saved · Undo", "<source> · Separated · Undo", "Merged into this profile · Undo", "Marked as a different person · Undo". After Remove, a Banner on the page the user returns to: "<name> removed from your network." with Undo.
- Every form is a plain POST form that works without JavaScript.

### 4. Links to the page



- The name on a result card and on a network row links to `/people/<id>` (with `?search=<id>` from a card).
- The Source page shows an import or staff source by its label and file name, with no outside link, through `present.label_of`.

## Tests

New `tests/test_person_page.py`, with made-up people:

1. The page of a network person shows the head, the contact block, the three fact groups in order, and no "Found as" for a single record.
2. A fact held from two sources shows once with the newer citation.
3. A new fact is marked "New" on the first visit and not on the second, and the person's `seen_at` moved. A candidate's page moves nothing.
4. Unknown id: 404. A merged record's id: 303 to its person.
5. Each POST route: add, skip, remove, contact, merge, not-same, reject, undo. After each, the page shows the done line with Undo, and Undo restores the earlier page.
6. Contact: an email without `@`, an empty value, 300 characters and an email another person holds each give 400 with the sentence under the field. A valid one is saved and shown with "Entered in FN".
7. An undo after a later decision redirects with the refusal Banner.
8. `next` with another site's URL (`//evil.example`, `https://evil.example`) is ignored.
9. A person with 40 facts in a group shows 10 and "Show 30 more"; `?all=1` shows all.
10. A person with two records shows "Found as"; "Not this person" separates the record and both pages exist afterwards.
11. A candidate with a same-name network person shows the three buttons; "Same person" merges it and the network person's page shows the merged facts as new.
12. A result card's name and a network row's name link to the page.

Each new test must fail without the change. An existing test that asserts a plain-text name on a card changes on purpose: list it.

## Hand check

On a throwaway copy of the owner's database with 20 people added from a stored search: with the Playwright browser tools at 1280 px and 390 px, open one person from `/people`, edit the email, remove a fact and undo it, open a person with several records and separate one, then undo. Report what each step showed, any console error, and the time `/people/<id>` took for the person with the most facts (it must stay under 1 s). Save a screenshot of the page at both widths in your temp folder and give the paths.

## Working beside another task

The import and export pages are being built at the same time in another worktree. That task owns the count line, the Network heading and the empty-network Notice in `web/parts.py`, and adds its own routes to `web/staff.py`. Do not change those parts; add your functions next to the existing ones without reordering the file.

## Not in this task

Add and Skip on result cards, import and export, the cut, live results. Editing any fact other than the contact details.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- `web/staff.py` changes membership only through `network.py`. `present.py` returns view models and builds no HTML. `web/parts.py` builds HTML from view models and reads nothing from the store. Only `store.py` runs SQL.
- No new dependency. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
