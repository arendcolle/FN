## D5. What Add, merge, keep-apart and Skip do

Rounds: 3 · consensus: False

D5, final round. All three reviewers agree on rules 1 and 3 to 8. Rule 2 (Add when hits conflict) has no unanimous vote. Each reviewer chose a different option, so I took the pairwise majority. The user and engineer reviewers keep conflicting hits on one card, against the skeptic's split. The user and skeptic reviewers would store the same result, merging the non-conflicting hits into the first hit and keeping the conflicting hit separate, against the engineer's top-hit-only rule. Option (b) therefore wins.

1. Cards. A card shows and scores only its hit records, mapped to canonical ids (merged_into). Today rank.py:108 and app.py:215,232 still read person_ids. Candidate stores hit_person_ids, backfilled from the stored ResolveOut for the existing searches, and contracts_version goes up.
2. Add. One click, no question first. Add merges every hit that holds no conflicting value in seed, openalex, orcid or profile_url into the first hit (merged_into, depth one), sets list_status='in_list' and writes one event. A conflicting hit stays a separate record. The card then reads "Added · 1 possible match" and links to that profile's Possible matches. A one-record card follows the same rule with nothing to merge.
3. resolve splits a card into separate entries when a not_same row exists between two of its records, or when they hold distinct ORCIDs. This is a pure read rule in resolve.py with no stored state. Conflicts in seed and openalex do not split a card.
4. Network name match. A network person with the same name key and no shared identifier replaces Add with "Same person" / "Add as new". Nothing is preselected. "Same person" merges the hits into the network record and attaches the new facts, marked new. "Add as new" adds the hits and writes not_same.
5. Skip. Skip sets list_status='skipped' on the hit records and lasts across searches. A later search cuts an entry when all of its hits are skipped. A new same-name record still shows. The result list ends with "N skipped hidden · Show", and the cards it shows carry their Undo.
6. Undo. Every action writes one event row with detail_json, and Undo reverses that event with no time limit. FN refuses the Undo with a message when a later event touched the same records. Cut: toasts and undo windows.
7. Repair happens on the profile, in two sections. "Found as" lists the records, each with "Not this person", which unmerges the record and writes not_same. "Possible matches" lists same-key records and conflicting hits, each with Same / Different.
8. Ownership. network.py owns the rules and the conflict-scheme constant, store.py owns the SQL, and store.resolve_person does not change.

Cut from scope: the duplicate queue, field-level merge, inline questions on multi-hit cards and a skipped-list page.

**Rules**

- The card shows and scores only hit_person_ids, mapped to canonical ids. Candidate stores hit_person_ids (backfilled), and contracts_version goes up.
- resolve splits an entry on not_same or on distinct ORCIDs. Seed and openalex conflicts do not split a card.
- Add is one click. It merges the hits with no conflicting seed, openalex, orcid or profile_url value into the first hit and sets them in_list. A conflicting hit stays separate, and the card reads 'Added · 1 possible match'.
- A same-name network person with no shared identifier gets 'Same person' / 'Add as new' with nothing preselected. 'Add as new' writes not_same.
- Skip sets skipped on the hits across searches. An entry whose hits are all skipped is cut. A new same-name record still shows. The list ends with 'N skipped hidden · Show'.
- Each action writes one event row. Undo reverses it with no time limit and is refused when a later event touched the same records.
- The profile has 'Found as' (with 'Not this person', which unmerges and writes not_same) and 'Possible matches' (Same / Different).
- network.py owns the rules and the scheme constant. store.py owns the SQL. store.resolve_person does not change.

**Dissent**

The engineer reviewer still wants Add to add only the top hit when any scheme conflicts. Merging a mention-only hit C into seed record A decides that C is A and not B, and the data does not show that. The skeptic reviewer still wants resolve to split a card on a conflict in any non-mention scheme. The card pools the claims of all its hits (resolve.py:29), so any Add that leaves a hit out stores less than the user saw. Splitting would add about 4 cards per search (114 cards over the stored searches). Neither reviewer disputes rules 1 or 3 to 8.

**Evidence**

- Recounted read-only: across the step_payloads ResolveOut entries there are 447 distinct multi-hit cards. 114 of them hold two values in one scheme: openalex 64, seed 50, orcid 16 (a card can count under more than one scheme), profile_url 0. Script: scratchpad/d5mod.py
- person_identifiers by scheme: openalex 19509, orcid 15355, seed 4940, mention 1418, profile_url 25. No (scheme, value) pair belongs to more than one person (query returned 0).
- resolve.py:32-37: Entry has hit_person_ids and person_ids, where person_ids adds the stored same-key records. resolve.py:29 pools the hits' claim_ids into one card. resolve.py has no not_same split yet.
- rank.py:72 and :121 score on hit_person_ids, but rank.py:108 picks the network section from person_ids, and web/app.py:215,232-235 render person_ids.
- contracts.py:16 ListStatus = candidate | in_list | skipped. contracts.py:358-359 hit_person_ids. The persons table has list_status and merged_into columns.

## D6. What the ranker cuts

Rounds: 3 · consensus: True

D6, what the ranker cuts. All three panelists agree on every point.

Rule. rank.py decides whether each candidate is kept or cut. A candidate in the "new" section gets cut_reason = 'no_belgian_evidence' when it has no belgian_years score part and openalex is its only lane. Every other candidate is kept: any network person, anyone with belgian_years, and anyone found by seeds, web or LinkedIn. The rule has no year threshold and no score floor. RRF scores cannot be compared across searches (rank.py:86-92). fuse numbers rank among kept people only. Cut rows get rank NULL, or a separate number that only the debug page shows. Without this, the gate and gold.py (TOP_N) would count positions no user ever sees.

Storage. candidates gets one nullable cut_reason column with CHECK (cut_reason IN ('no_belgian_evidence')). NULL means kept. contracts.py adds a Literal with that single value. There is no `kept` column, because two columns can disagree. The migration fills cut_reason for the stored searches by replaying the rule over lane_ranks_json and score_parts_json. It makes no lane calls. Every row stays in the table.

Skipped people. persons.list_status owns skipped (contracts.py:16). rank never stores skipped as a cut. list_candidates(kept_only=True) (store.py:394) joins persons and leaves out a candidate when any of its person_ids is skipped. An Undo (D5) shows the person again on the next page load, with no re-rank.

Page. web/ shows 50 rows. "Show more" (`?shown=`) adds 50 at a time, the Carbon "load more" pattern. There is no hard cap. Staff pages have no hidden count, no reveal control and no scores.

Where cut people stay visible. The debug page lists them with their reason. The rank trace row logs kept and cut counts per reason. A cut gold pick writes a "dropped" trace row with reason no_belgian_evidence, so gold.lost_at (gold.py:93-95) reports it with no new code path.

Gate before merge. Replay the old sha and the new sha over the same stored rows and the gold set. Reject the change if any of these holds:
(a) the median kept count falls less than 40% below the no-cut baseline;
(b) any of the 12 reachable gold picks is cut;
(c) fewer than 4 picks rank in the first 50, or fewer than 6 in the first 100.
Today the rule passes (a): the median falls from 1,098 to 518, which is 53%.

Tests. rank gets 3 unit cases: a web-only person with 0 Belgian years is kept, an OpenAlex-only person with 0 years is cut, and a network person with 0 years is kept. store gets 1 test: a skipped person is missing from list_candidates(kept_only=True) and comes back after the status returns to candidate, with no re-rank.

Not in scope. D6 does not improve result quality. Ordering needs its own decision, judged by how many picks land in the first 50.

**Rules**

- rank.py sets cut_reason='no_belgian_evidence' on a new-section candidate that has no belgian_years part and no lane other than openalex
- Never cut a network-section candidate; no year threshold, no score floor
- fuse numbers rank among kept candidates only; cut rows get rank NULL or a number shown only on the debug page
- Schema: one nullable candidates.cut_reason with CHECK (cut_reason IN ('no_belgian_evidence')); NULL means kept; no kept column
- Migration backfills cut_reason by replaying the rule over lane_ranks_json and score_parts_json, with no lane calls; every row stays
- list_candidates(kept_only=True) joins persons and hides a candidate with any skipped person_id; rank never stores skipped
- web/ shows 50 rows and adds 50 per 'Show more' (?shown=); no hard cap, no hidden count, no reveal control, no scores
- The debug page lists cut people with their reason; the rank trace logs kept and cut counts per reason; a cut pick writes a 'dropped' trace row so gold.lost_at reports it
- Gate: replay old and new sha; reject if the median kept count drops less than 40% from the no-cut baseline, any of the 12 reachable picks is cut, or picks in the first 50 or 100 fall below 4 or 6
- Tests: 3 rank cases (web-only 0 years kept, openalex-only 0 years cut, network 0 years kept) and 1 store test (skipped hidden, Undo restores it without a re-rank)

**Dissent**

None.

**Evidence**

- Replay over var/fn.sqlite3 (read-only): 24 stored searches have candidates; with no cut, the median is 1,098 per search (range 363 to 2,132); under the rule, the median is 518 (range 205 to 1,130); the drop is 52.8%
- Lanes seen in lane_ranks_json: openalex, web, seeds, linkedin
- rank.py:108 sets the network section from list_status == 'in_list'; rank.py:112 numbers rank per section over every entry; rank.py:120 loads statuses at rank time
- rank.py:86-87: each lane part is worth 1/(K+rank), so scores are not comparable across searches
- contracts.py:16: ListStatus = Literal['candidate','in_list','skipped']
- store.py:374 save_candidates, store.py:394 list_candidates
- gold.py:91 reports a pick ranked below TOP_N; gold.py:93-95 returns the first 'dropped' trace row as lost_at
- The candidates schema today has no cut_reason column; rank is INTEGER NOT NULL, so the migration must make it nullable if cut rows get rank NULL
- The figures 12 reachable picks and 71 of 83 picks never reaching rank come from the panelists' earlier gold replay; this round did not re-run that replay

## D7. Where email, phone and hand-typed facts live

Rounds: 3 · consensus: False

D7, decided by majority. Contact details and hand-typed or imported facts are claims, option (a).

Shared base, which all three agree on. ClaimKind gets two new kinds, email and phone. An imported row is a source of kind "import" with URL fn:import/<import id>#row-<n> and DateMethod sheet_date. A hand-typed fact is a source of a new kind "staff" with URL fn:staff/<event id> and DateMethod staff_edit. Source._http_only allows the fn: scheme for import and staff sources only. present.py owns the mapping from an fn: URL to a link on the page. Contact kinds stay out of match_claims and out of the seed lane's full-text search, so a contact value never makes a person a search hit. A blank cell in an import clears nothing. The export writes the newest non-rejected value per kind, one value per cell. Logs and events hold claim ids, never contact values.

1. Ownership (unanimous). store.claims_of owns value-level hiding and newness, because rank.py, gold.py and app.py all call it directly. By default it drops a claim when its key (canonical person, kind, lower(trim(value))) matches a claim with rejected_at set. include_hidden=True returns the removed values for the profile's removed list and for undo. A value's first_seen_at is the earliest over the same key. No schema change is needed beyond rejected_at and first_seen_at, which design.md already plans. A value typed back after a reject would stay hidden under the value rule. To close that gap, a value is hidden only when its newest reject is later than its newest staff claim. Only the skeptic raised this gap and nobody opposed the fix.

2. Hand edit (majority: user and engineer). One call, network.set_contact(person, kind, value, replaces=None). In one transaction under one edit_contact event, it writes the staff claim and, when replaces holds a claim id, sets rejected_at on that value. With replaces=None the same call adds a value. detail_json holds claim ids only. Undo restores the old value and rejects the new one. The UI shows one Replace action with undo and no confirm dialog.

3. Build order (majority: user and engineer). The contact form ships with the profile, right after the import. The import ships after flows 1, 5 and 7. The TextInput component goes into the design system before the form is built.

4. Name-only rows (majority: engineer and skeptic). A row with no strong identifier (LinkedIn, ORCID, email) always becomes a new person keyed import:<import id>:<row>. A name key is never stored as an identifier, so resolve_person cannot merge on a name. When the row's name key matches a network person, the preview shows "Same as <person>? Merge" with the checkbox unchecked. A header checkbox selects all rows. A ticked box calls network.merge, which sets merged_into and can be undone. On a second import of an updated file, a row is recognised by its strong identifiers. Emails that staff added and exported then let later imports match on the email scheme.

Tests: the ranker's and the gold runner's input omits a rejected value. Reject, then re-add, and the value shows. Undo of a Replace brings back the old value and rejects the new one. A re-import of the same file marks nothing new. An unchecked name match creates a separate person. A checked one creates a merge pointer, and unmerge splits the two again.

Cut: pre-checked name matches, a separate rejection table, phone normalization, multi-value export cells, search by contact, and contact details on result cards.

**Rules**

- Email and phone are new ClaimKind values. Every contact fact is a claim with a quoted source. No plain contact columns.
- An imported row's source has kind import, URL fn:import/<import id>#row-<n> and DateMethod sheet_date. A hand-typed fact's source has kind staff, URL fn:staff/<event id> and DateMethod staff_edit.
- Source._http_only accepts fn: only for import and staff sources. present.py maps fn: URLs to links.
- store.claims_of hides a claim when its key (canonical person, kind, lower(trim(value))) has a reject newer than its newest staff claim. include_hidden=True also returns hidden claims. first_seen_at is the earliest over the key.
- network.set_contact(person, kind, value, replaces=None) writes the staff claim and rejects the replaced value in one transaction under one edit_contact event. detail_json holds claim ids only. Undo restores the old value and rejects the new one.
- Contact kinds stay out of match_claims and the seed lane's full-text query.
- A blank import cell clears nothing. The export writes the newest non-rejected value per kind, one per cell.
- A row without LinkedIn, ORCID or email becomes a new person keyed import:<import id>:<row>. A name key is never stored as an identifier.
- When a name key matches a network person, the preview shows an unchecked merge checkbox and a header select-all. A ticked box calls network.merge, which can be undone.
- The contact form ships with the profile, right after the import. The TextInput component goes into the design system first.
- Logs and events never hold contact values.

**Dissent**

Skeptic, on the hand edit: wants two actions with two events, Add (add_contact) and the existing reject_claim. The skeptic thinks a combined edit_contact needs its own undo logic and saves only one click. The majority answers that design.md rule 1 asks for one event per decision and an undo that reads it, and that edit_contact is already listed in design.md. Skeptic, on build order: wants the form built with flow 5's profile, before the import, because the export does not depend on it. User, on name-only rows: wants a flag only, shown as one grouped preview line, with merging left to flow 3. The user reads D2 (story-map.md:118) as keeping these rows possible matches, and a merge prompt in the import as overriding that by default. The majority answers that an unchecked box keeps the match possible, and that a merge is an undoable pointer.

**Evidence**

- store.claims_of is at src/fn/store.py:354. Its callers are rank.py:121, gold.py:129, gold.py:147, gold.py:198 and web/app.py:260, :360 and :452, so a rule kept in present.py would miss the ranker and the gold runner.
- grep finds neither rejected_at nor first_seen_at in src/fn/store.py, so both columns are new. design.md:58-61 plans them and says a rejected claim is 'ignored by the ranker'.
- ClaimKind at contracts.py:18 has five kinds and no email or phone. SourceKind at contracts.py:28 already includes 'import'. DateMethod at contracts.py:23-25 includes sheet_date and staff_edit.
- design.md:40 says every staff decision writes one event that its undo reads. design.md:41 says a merge is a merged_into pointer. design.md:83 lists edit_contact among the event kinds.
- merged_into exists in migrations/001_init.sql:72 and contracts.py:264, but no merge function exists in src/fn yet. network.merge is planned in design.md.
- story-map.md:118 (D2): a same-name match with no shared identifier stays a possible match that staff merge.
- TODO.md (the email and phone item): add email and phone as contact details. A person today has no place for them.
- resolve_person is at store.py:218. It must never receive a name key as an identifier.

## D8. Home page, header, Network page and person detail

Rounds: 3 · consensus: True

All three panelists agree on every point. Home, Network and Results are one view built from existing design-system parts.

(1) Home (/): SearchBox first. Then RecentSearches, capped at 3, with an "All searches" link. Then the network block, which is the same list-beside-map view as /people. `/` and `/people` render the block through one function, `present.network_view`. An empty network shows a Notice that points to Import and to adding people from results, and it hides the map with `fn-results--no-map`. Home has no stats.

(2) The header has two links, Search and Network, as the Header README already says.

(3) The Network page uses ResultsLayout: a list beside a map, with the List/Map switch under 900px. The list uses NetworkRow rows between rules. Cards stay reserved for people in results. Rows are sorted newest added first, with no sort control. The filter is a GET form with one text box (name, place, organisation) and a visible Filter button. It submits on Enter or on the button, never on blur or change (WCAG 3.2.2). Tokens are links and need no form: a place token comes from clicking a shared dot, and `?import=<id>` gives "From import x.csv". Each token has its own Clear, and a Clear sits beside the count line. "New facts only" appears in slice 4, and only when its count is above 0. The map shows the whole filtered set. The count line reads "N people · M not on the map". The list shows the first 200 rows, then "Show more", which raises `?limit` (400, 600 and so on). There is no offset, so the page keeps one URL and Back works. `store.list_network(NetworkFilter, limit)` is the contract. Export and `/api/people/geo` ignore the limit.

(4) Person detail uses the existing MapMarker popup, with no panel. Clicking a dot opens the popup on every screen width. Clicking a row (outside the name) for a person with a place pans to the dot and opens the same popup. A row with no place opens nothing extra: the row is already the summary, and its name links to /people/{id}. The popup shows the linked name, role · employer, place, "N new facts" (from slice 4) and "Open profile". A dot shared by several people lists them all, with a scroll cap. Only the profile page sets `seen_at`. Opening a popup never does.

(5) Import and "Export these N people" are action links on the Network SectionHeading. Results also gets Export (story-map flow 7, step 1).

(6) Results and Network share ResultsLayout, MapMarker and its popup, the row-to-dot and dot-to-row link, the List/Map switch and the count line. Results uses PersonCard and Network uses NetworkRow. The design system gets these first: FilterBar (box, Filter button, tokens, count, Clear), the network popup variant of MapMarker with the row-click rule, a "New facts" mark on NetworkRow in text-meta-strong, action links on SectionHeading, the empty-network Notice and the RecentSearches cap.

Logging: each request records the filter text, tokens, limit, rows rendered, marker count and render time, plus popup opens (row or dot) and profile opens by source. A panel or clustering waits until these numbers show a need.

Tests: the export row count equals the count line for the same query string, the filter survives a round trip through the URL, and an empty network renders the Notice.

Cut: the PersonSummary panel, offset, submit on blur, live typing, place and organisation selects, sort controls, clustering, map-bounds filtering and stats on home.

**Rules**

- Home shows SearchBox, then RecentSearches capped at 3 with an 'All searches' link, then the network block rendered by present.network_view, the same function /people uses.
- An empty network shows a Notice and hides the map (fn-results--no-map). Home has no stats.
- The header has two links, Search and Network.
- Network uses ResultsLayout (list beside the map, List/Map switch under 900px) and NetworkRow rows between rules. No cards.
- Rows are sorted newest added first. There is no sort control.
- The filter is a GET form with one text box and a visible Filter button. It submits on Enter or the button, never on blur or change.
- Tokens (place from a shared dot, ?import=<id>, New facts only from slice 4 when its count is above 0) are links, each with its own Clear.
- store.list_network(NetworkFilter, limit) is the contract. The list shows 200 rows, and 'Show more' raises ?limit by 200. There is no offset.
- The map and the count line ('N people · M not on the map') cover the whole filtered set. Export and /api/people/geo ignore the limit.
- Clicking a dot opens the MapMarker popup at every width. Clicking a row with a place pans to its dot and opens the same popup. A row with no place opens nothing extra.
- The popup shows the linked name, role · employer, place, N new facts (slice 4) and Open profile. A shared dot lists everyone at it, with a scroll cap.
- Only the profile page sets seen_at.
- Import and Export sit as action links on the Network SectionHeading. Results also gets Export.
- Code changes: map.js selects [data-person], not .fn-card[data-person]; choose() opens the popup on wide screens too; the person name becomes a link.
- The design system gets these before code: FilterBar, the network MapMarker popup and row-click rule, the New facts mark on NetworkRow, action links on SectionHeading, the empty-network Notice and the RecentSearches cap.
- Log per request: filter text, tokens, limit, rows rendered, markers and render time. Also log popup opens (row or dot) and profile opens by source.
- Tests: export row count equals the count line for the same query; the filter survives a URL round trip; an empty network renders the Notice.
- Cut: PersonSummary panel, offset, submit on blur, live typing, selects, sort controls, clustering, map-bounds filtering, stats on home.

**Dissent**

None.

**Evidence**

- src/fn/web/static/map.js:25 builds `cards` from `.fn-card[data-person]` only, so NetworkRow rows would not link to dots until it selects [data-person].
- map.js popup() (about lines 65-79) already builds a popup with name and employer · place for every person at a dot.
- map.js choose() (about line 81) runs `narrow.matches ? popup(index) : pick(index)`, so on a wide screen today a dot click only picks the card and opens no popup.
- src/fn/store.py:113 has `list_searches(self, limit)`; nothing in the store lists network people or takes a limit for them yet.
- src/fn/web/app.py:374 renders the card name as a plain h3 with no link to the person page.
- sqlite3 -readonly var/fn.sqlite3: 25,845 persons; 16,973 have at least one claim with lat set (about 66%); the searches table holds 29 rows.
- TODO.md lines 7-9: ideate the homepage to show the current network with one consistent view; map view, list view and basic filtering; person detail as a pop-up from the list or the map.
- The design system has Header, NetworkRow, PersonCard, MapMarker, ResultsLayout, ViewSwitch, SearchBox, RecentSearches, SectionHeading and Notice. It has no FilterBar.

## D9. How people appear while a search runs

Rounds: 3 · consensus: True

D9, decided unanimously in round 3. Lanes keep running one after another on the one worker thread. Partial people appear through a `publish` step, and the page polls a small status endpoint instead of reloading.

1. Partial results. search.run calls run_step(ctx, "publish", ...) after each lane except the last. The step runs resolve, rank and save_candidates on the lane outputs so far and returns PublishOut{count}. The final resolve, rank and save steps stay as they are. With 4 lanes (seeds, openalex, web, linkedin), a search records 3 publish steps and 1 save step, so version rises at most 4 times. The user sees cards appear and re-rank after each lane. A partial card can be opened and acted on. Add and Skip are keyed on (search_id, person_id) and never stored on candidate rows, because save_candidates deletes and re-inserts those rows. This rule binds D5.

2. Refresh. GET /searches/{id}/status returns {status, people, version}. version is one COUNT over step_runs WHERE step IN ('publish','save') AND status='ok', with no schema change. A script of about 30 lines polls every 2 s. When status or version changes, it swaps the list fragment, keeps the scroll position and calls setData on the existing map without rebuilding it. The swap waits while a `.fn-card` has focus (:focus-within) or the pointer, and runs on pointerleave or focusout. The status line keeps updating during a hold. When status leaves running, the poller renders the final fragment with its Notice and stops. The meta refresh moves into `<noscript>` as the fallback.

3. Concurrency. Lanes stay serial this week. design.md records a gate: revisit once /debug/stats shows live lane times. The gate also names what has to change first: next_step_seq reads MAX(seq)+1 outside a transaction, the call recorder uses a context variable, and Store keeps one connection per thread with a 5 s busy timeout. SSE, htmx, skeletons, time estimates, a progress table, lane names or a source count in the UI, and a tab-title count are all left out.

4. Failure. A lane exception keeps its error row, and the search goes on and ends done. Errors in parse, resolve, rank or save stay fatal, and so does a search in which every lane failed. gold.py reports lane errors on done searches.

5. Wording and return visits. The status line reads "Searching…", then "Searching… N people so far", as in the StatusLine README. A done search with a lane error shows "Some sources could not be read, so this list may be incomplete." with Search again. A failed or interrupted search shows the people published so far with "This search stopped before it finished." and Run again. That needs a change at app.py:422, which hides them today. Both sentences go into the design system before any code. A user who leaves and comes back sees the same state, because it lives in SQLite.

6. Logging. /debug/stats shows time to first person, measured to the first publish with count > 0.

7. Tests. Update the expected step list at test_web.py:431-433 on purpose. Add a slow fake-lane test that asserts candidates exist and version is 1 before the second lane returns. Add a raising-lane test that asserts the search still ends done.

**Rules**

- Lanes run one after another this week; design.md records the gate for running them at the same time later.
- search.run records a step named `publish` (PublishOut{count}) after each lane except the last; final resolve, rank, save unchanged.
- Add and Skip state is keyed on (search_id, person_id) and never stored on candidate rows.
- GET /searches/{id}/status returns {status, people, version}; version = COUNT of ok steps named publish or save.
- A ~30-line script polls every 2 s; on a status or version change it swaps the list fragment, keeps scroll, calls map setData.
- The swap waits while a .fn-card has focus or the pointer; it runs on pointerleave or focusout.
- Meta refresh moves into <noscript>.
- A lane exception keeps its error row and the search ends done; parse/resolve/rank/save errors and all-lanes-failed stay fatal.
- gold.py reports lane errors on done searches.
- Status line: 'Searching…' then 'Searching… N people so far'.
- Done with a lane error: 'Some sources could not be read, so this list may be incomplete.' plus Search again; add it to the design system first.
- Failed or interrupted searches show published people with 'This search stopped before it finished.' plus Run again; change app.py:422.
- /debug/stats time to first person = time to first publish with count > 0.
- Tests: update test_web.py:431-433 on purpose; add a slow fake-lane test (candidates exist, version 1 before lane 2 returns) and a raising-lane test (ends done).
- Cut: concurrent lanes, SSE, htmx, skeletons, time estimates, progress table, lane or source names in UI, tab-title count.

**Dissent**

None.

**Evidence**

- src/fn/search.py:33 runs lanes in order via run_step(ctx, f"lane:{lane.name}", ...); :34-36 run resolve, rank, save once at the end
- src/fn/lanes/__init__.py:15 LANES = [seeds, openalex, web, linkedin], so 3 publishes + 1 save at most
- src/fn/store.py:374-392 save_candidates DELETEs and re-INSERTs candidates and match_flags in one transaction
- src/fn/store.py:132-134 next_step_seq reads COALESCE(MAX(seq),0)+1 outside a transaction; src/fn/steps.py:146 allocates seq per step
- src/fn/worker.py:89-96 any exception from search.run sets the search to failed; done is set after run returns
- src/fn/web/app.py:64 TRACED holds only LaneOut, ResolveOut, RankOut; :552 trace_rows uses TRACED.get, so PublishOut stays out of the trace
- src/fn/web/app.py:422 hides people for failed or interrupted searches (the panel cited :421, where `stopped` is set)
- src/fn/web/app.py:438 refresh=2 while active; src/fn/web/html.py:103 renders it as a meta refresh
- src/fn/gold.py:99 selects lanes with startswith("lane:"), so the name `publish` does not collide
- tests/test_web.py:431-433 asserts the exact step list parse, 4 lanes, resolve, rank, save

## D10. Is the module map and data model right

Rounds: 3 · consensus: True

All three panelists accept the joint rule set from earlier rounds on questions 1 to 8. They also agree on the two points that were still in dispute.

Joint rule set:
(1) A merge is a pointer. persons.merged_into holds the canonical id, at depth one. store.resolve_person keeps its current contract (store.py:218-236) and returns the record that holds the identifier. resolve.group is the only canonicalizer that rank, the web cards, gold and the seeds lane read through. design.md:52 is corrected to match.
(2) One append-only events table records staff decisions (design.md:40). Undo writes the inverse event and is allowed only while the decision is the person's latest event. added_at and added_via are derived from the add event and are no longer columns. The event kinds open_person, unmerge and restore_claim are removed from design.md:83.
(3) app.py is split into staff, debug and parts as a move-only structural commit, done first.
(4) store.py stays one file (421 lines today) and is split by aggregate behind one Store class when it reaches about 800 lines.
(5) No design-system mirror folder goes into the repository.
(6) The owner fixes and (7) the logging list stand as agreed.
(8) Postponed: /debug/stats, /debug/feedback, the unmerge UI, restore_claim, open_person and the D9 swap script. Added to the plan as risks: back up the 509 MB database before migrating, backfill first_seen_at and the duplicate name keys, and guard the CSV export against formula injection.

Dispute A, decided: persons.seen_at stays a column. network.mark_seen is its only writer. The profile route calls it after it renders the "new" marks. Opening a profile writes no event, for two reasons. It is navigation, not a decision. And an open event would become the person's latest event and block Undo of an Add. A claim is new when claim.first_seen_at > persons.seen_at and the person is in the network (design.md:60). Profile opens are recorded only in the request and step log, keyed by request id. design.md:53 is updated to say this.

Dispute B, decided: seeds.EXCLUDED stays ("record", "vendor_record", "vendor_page") (seeds.py:19). Import and staff claims stay matchable. The exclusion exists because matching other lanes' sources would make seed ranks depend on past searches (seeds.py:42). Staff entered import and staff claims on purpose, and no search produced them. If they were excluded, an institution chip would never find an imported person who has no OpenAlex or LinkedIn presence. The comment at seeds.py:42 and the design are reworded to say that EXCLUDED lists the source kinds that searches write. The ownership table calls the seeds lane "known people" and states that it matches seed, import and staff claims.

Required with B: once rejected_at exists, both match_claims (store.py:305-317) and claims_of must filter c.rejected_at IS NULL. Otherwise a fact that staff removed still ranks the person. The panel treats this as a should-fix in the intended case. Today the claims table has no rejected_at column, so the column, both filters and the tests arrive in the same task. The gold run pins its database snapshot, because imports change seeds results by design.

**Rules**

- Merge sets persons.merged_into to the canonical id, depth one; no claim or identifier moves.
- store.resolve_person keeps its contract; resolve.group is the single canonicalizer for rank, web cards, gold and seeds.
- One append-only events table for staff decisions only; undo writes the inverse event and is allowed only when the decision is the person's latest event.
- Drop persons.added_at and added_via; derive them from the add event.
- Remove open_person, unmerge and restore_claim from the event kinds.
- Keep persons.seen_at as a column; network.mark_seen is its only writer, called by the profile route after rendering new marks; no event on profile open.
- A claim is new when first_seen_at > persons.seen_at and the person is in the network.
- Profile opens are logged only in the request/step log by request id.
- seeds.EXCLUDED stays (record, vendor_record, vendor_page); import and staff claims are matchable; reword the seeds.py:42 comment and the design to say EXCLUDED lists kinds that searches write.
- Add claims.rejected_at with the filter c.rejected_at IS NULL in both match_claims and claims_of, plus tests: an imported affiliation matches an institution chip, and a rejected claim does not match.
- Gold runs pin a database snapshot.
- First commit: move-only split of web/app.py into staff, debug and parts.
- store.py stays one file; split by aggregate behind one Store class at about 800 lines.
- No design-system mirror folder in the repository.
- Postpone /debug/stats, /debug/feedback, unmerge UI, restore_claim, open_person and the D9 swap script.
- Before migrating: back up the database, backfill first_seen_at and duplicate name keys; guard CSV export against formula injection.

**Dissent**

None.

**Evidence**

- seeds.py:19 EXCLUDED = ("record", "vendor_record", "vendor_page"); the stated reason is the comment at seeds.py:42 (panelists cited :43)
- contracts.py:28 SourceKind = page, record, seed_page, import, vendor_record, vendor_page
- store.py:218-236 resolve_person returns the person that holds any identifier, else a new candidate
- store.py:305-317 match_claims filters only on s.kind NOT IN exclude; no rejected filter
- claims table today has no rejected_at column (PRAGMA table_info(claims)), so the panelists' claim that claims_of already filters rejected claims is not true yet; both filters come with the new column
- sqlite3 -readonly claims JOIN sources GROUP BY kind: record 263096, seed_page 11840, vendor_page 2744, vendor_record 331
- store.py is 421 lines (wc -l)
- var/fn.sqlite3 is 509091840 bytes (about 509 MB)
- design.md:40 rule 1, a staff decision is data; design.md:52 merge text; design.md:53 added_at/added_via/seen_at columns; design.md:60 definition of a new claim; design.md:83 event kinds including open_person, unmerge, restore_claim
