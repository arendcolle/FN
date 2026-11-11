# UI patterns for seven interface problems

This note collects how public design systems and well-known products handle seven interface problems. It was written from pages fetched in November 2026. A claim marked "unverified" came from a search snippet, a secondary source, or a page that failed to load, and was not confirmed on the primary page. Several searched sources gave nothing on a topic. Those gaps are listed per section, not filled from memory.

Coverage by source:

| Source | Status |
| --- | --- |
| GOV.UK Design System (error summary, check answers, notification banner) | Read |
| Nielsen Norman Group (progress indicators, skeleton screens) | Read |
| IBM Carbon (filtering pattern v10, loading pattern, data table usage) | Read, data table page truncated |
| Smashing Magazine (dangerous actions), A List Apart (undo) | Read |
| Baymard Institute (split view) | Read |
| HubSpot, Attio, Google Contacts, Shopify help pages | Read |
| Shopify Polaris | Not verified. The component URL redirected to a page that was not fetched |
| Atlassian Design System flag | Not verified. The page returned no content. Only a search snippet exists |
| Salesforce duplicate management | Not verified. The help page returned a loading error |
| folk | Not found. The search returned only Attio material |
| Material Design snackbar | Not verified. The page returned only its title |

## 1. Importing a CSV of people with fixed column names

Flow to cover: upload, validation, preview, row errors, confirm.

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Fixed header names, then upload and one confirm button | Shopify product import: https://help.shopify.com/manual/products/import-export/import-products | Simple to build. Header mismatches fail the whole import, and the user gets cryptic messages. |
| Headers must map to existing properties, with a unique key to update instead of create | HubSpot import file rules: https://knowledge.hubspot.com/import-and-export/set-up-your-import-file | Prevents duplicates when a key such as email is present. Without a key, the import creates duplicates. |
| Review step before commit, with change links back to each answer | GOV.UK check answers pattern: https://design-system.service.gov.uk/patterns/check-answers/ | Catches mistakes before they are saved. Adds one page to the flow. |
| Error summary at the top plus a message at each failing item | GOV.UK error summary: https://design-system.service.gov.uk/components/error-summary/ | Users see every problem at once and can jump to it. Needs identical wording in both places. |

### What the sources say

- Shopify tells users to back up data first, because an import cannot be cancelled once it starts. The help page shows no import history in the admin. It does not describe a validation stage or what the review screen shows (unverified for the review screen).
- Shopify column headers are case-sensitive. A mismatch can produce an unrelated error such as a JSON parse failure. Files over 15 MB should be split.
- Shopify with "overwrite" on turns blank non-required cells into blanks. With overwrite off, rows that match an existing handle are ignored.
- HubSpot ignores blank cells and does not clear existing values. Values that fail validation "will not be imported". The page describes no preview and no row-error report (unverified beyond that).
- HubSpot accepts any column order, requires a header row, and caps rows per file and imports per day.
- The GOV.UK check answers page says the submit button must name its action and that the page must make clear nothing is done until the user confirms. It shows skipped optional answers as "Not provided".
- GOV.UK says to show an error summary even when there is one error, with the heading "There is a problem", and to link each entry to its field.

### Pitfalls the sources warn about

- Cryptic errors for header or encoding problems (Shopify).
- No way to cancel or review after the import starts (Shopify).
- Overwrite semantics that differ between blank and omitted columns (Shopify).
- Missing unique key creates duplicate records (HubSpot).
- A vague page title or generic submit label hides the confirm step (GOV.UK).
- Sending users through the whole flow again after one fix (GOV.UK).
- A notification banner and an error summary on the same page (GOV.UK).

Gap: Polaris has no verified import pattern. No source showed a per-row error table with a downloadable error file.

## 2. Detecting and resolving duplicate people

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Scheduled detection, a queue of pairs, side-by-side review, merge or reject | HubSpot: https://knowledge.hubspot.com/records/manage-duplicate-records | Strong control and an audit log. The user must work through a queue. Pair limits and plan limits apply. |
| Suggestions list with merge one or merge all | Google Contacts: https://support.google.com/contacts/answer/7078226 | Fast for obvious pairs. The page shows no dismiss and no field-level choice. |
| Merge started from a record page, one side wins on conflicts, with a preview of counts | Attio: https://attio.com/help/reference/managing-your-data/records/merge-and-delete-records | Clear rule for the winner. One pair at a time. The page describes no undo. |
| Alert or block at save time, plus batch jobs for old data | Salesforce (unverified, secondary sources only): https://www.salesforceben.com/practical-fixes-for-failing-salesforce-deduplication-rules/ | Stops new duplicates early. Fuzzy matches blocked by mistake frustrate users. |

### What the sources say

- HubSpot compares name, email, phone, zip code, IP country and company name by default, once a day. The pair table shows a similarity score and can be filtered.
- HubSpot "Reject" removes a pair from the tool. A rejected pair can come back if one record is later merged into another. A rejection can be rolled back within 14 days from View history.
- HubSpot says merged records cannot be reverted. Its audit log and exportable merge history exist.
- HubSpot warns when a custom rule matches more than 10% of records, because search results can become incomplete.
- Attio merges create a new record with a new ID. Lists, notes, tasks and comments from both records are combined. The right-hand record wins on conflicting values and the user can swap sides.
- Attio prompts a merge when it detects a duplicate by email for people. Deleting a record is permanent.
- Google Contacts merges only inside one Google account. Merge all and merge one are both offered.

### Pitfalls the sources warn about

- Treating merge as undoable when it is not (HubSpot, Attio).
- A rejected pair that returns later (HubSpot).
- A rule that matches too many records (HubSpot).
- Cross-account duplicates are invisible to the tool (Google Contacts).
- Merge all with no review hides wrong merges (Google Contacts offers it; the page gives no warning, so this is an inference).

Gap: no verified page for "add as new" at import time. HubSpot's unique-key rule in section 1 is the closest verified behaviour.

## 3. A list of people next to a map

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Split view with list and map side by side | Baymard on travel sites: https://baymard.com/blog/accommodations-split-view | Users see where results are without switching views. Needs width. |
| List follows the map area | Baymard (same page) describes users watching the list update as they zoomed. Airbnb help: https://www.airbnb.com/help/article/421/search-by-neighborhood (unverified for list behaviour) | Reassures users about scope. Moving the map can hide results users expected. |
| Cluster markers, click to zoom, spread out at maximum zoom | Leaflet.markercluster: https://github.com/Leaflet/Leaflet.markercluster and Google MarkerClusterer: https://developers.google.com/maps/documentation/javascript/marker-clustering | Handles thousands of markers. A cluster of exact same coordinates needs the spread-out step or users cannot reach each marker. |

### What the sources say

- Baymard found users go to the map first to judge location, and that zooming is an effective way to narrow results.
- Baymard saw trouble when the split view opened as an overlay: users mistook it for the full results page and missed sorting. Narrow vertical filter columns crowded the page; a horizontal filter bar worked better.
- Leaflet.markercluster clusters within 80 px by default. Clicking a cluster zooms to its bounds. At maximum zoom, or when markers stay together, it spreads them out, and a second click or Escape folds them back. The README does not discuss identical coordinates directly.
- The Google MarkerClusterer clicks to fit the cluster bounds, with a default 60 px radius. Its page does not cover identical positions.
- A secondary source says a Google cluster with identical positions shows only the top marker unless a spiderfier is added (unverified): https://github.com/csillag/oms
- Leaflet.markercluster has `chunkedLoading` so the page stays responsive while many markers are added.

### Pitfalls the sources warn about

- Overlay map that hides the real results page (Baymard).
- Filters in a narrow column beside list and map (Baymard).
- Identical coordinates that cluster and never separate (Leaflet and Google pages, plus the unverified secondary source).

Gap: no primary source describes hover on a list row highlighting its marker. Baymard's page does not mention it. A search snippet claimed Airbnb highlights the pin on hover, but only from a vendor source (unverified).

## 4. Filtering and searching a list of a few hundred to a few thousand people

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Search and filters in a table toolbar | Carbon data table: https://v10.carbondesignsystem.com/components/data-table/usage/ | Familiar. The page was truncated, so details on search behaviour are unverified. |
| Filters grouped by category, instant or batch apply | Carbon filtering pattern: https://v10.carbondesignsystem.com/patterns/filtering | Instant is quick for one category. Batch fits several categories or slow data. |
| Filters and saved views as tabs in an index list | Shopify Polaris IndexFilters (unverified, page not fetched): https://shopify.dev/docs/api/polaris | Not verified. |

### What the sources say

- Carbon: use instant updates for one category or a single selection. Use batch with an "Apply filters" button for several categories or slow loads.
- Carbon: "Multiple categories should never be put within a menu or dropdown". Place them on the left or at the top.
- Carbon: if filters sit in a closed container, the closed control must show that filters are active. At minimum show the count and allow clearing without reopening.
- Carbon: give each category a clear-all and a global clear-all. Start all selected when users usually exclude a few, all unselected when they want a few.
- Carbon data table: do not use a table as a replacement for a spreadsheet, and do not place it in a small container. Toolbar height must match row height.
- Baymard (section 3) found a horizontal filter and sort bar worked better than a narrow vertical column.
- Secondary sources, unverified as NN/g claims: show applied filters in a separate summary, show result counts per option, use OR within a facet and AND across facets: https://uxplanet.org/9-filtering-design-best-practices-to-improve-e-commerce-ux-edac50560f94

### Pitfalls the sources warn about

- Hiding applied filters (Carbon).
- No clear-all (Carbon).
- A start state that does not match what users usually want (Carbon).
- Instant updates on slow data (Carbon).

Gap: no verified source gave a number for when to add pagination. The truncated Carbon page only says pagination exists for "too much to show at once".

## 5. Progress for a one to five minute search that delivers results in parts

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Percent-done or step count ("3 of 50") | NN/g progress indicators: https://www.nngroup.com/articles/progress-indicators/ | Best for waits over 10 s. Needs a good estimate, and a stalled bar hurts. |
| Placeholders replaced progressively by real content | NN/g skeleton screens: https://www.nngroup.com/articles/skeleton-screens/ and Carbon loading pattern: https://carbondesignsystem.com/patterns/loading-pattern | Good for the first seconds of a page load. Wrong for long processes. |
| Let the user leave, then notify | Carbon loading pattern (same URL), and Nielsen on think time (unverified as a primary page): https://www.uxtigers.com/post/think-time-ux | Frees the user. Needs a place to find the result later. |

### What the sources say

- NN/g: use an indicator for anything over about 1 s. Looped animation fits roughly 2 to 10 s. Use percent-done at 10 s or more, and show remaining time when the wait is over about 10 s.
- NN/g: show step counts when possible. Give a general estimate with margin. Offer a way to stop. For highly variable delays, switch to percent-done sooner.
- NN/g: do not use skeleton screens for uploads, downloads or conversions. Use a progress bar or step-by-step wizard instead.
- Carbon: skeleton states should last only a few seconds. If a process takes more than a few minutes, consider a notification. Tell screen reader users when content is loading, stalled or failed.
- Carbon progressive loading: first batch shows structure, later batches fill in data. "Load more" extends long lists in batches.
- Leaflet.markercluster exposes `chunkProgress` for adding many markers in chunks (https://github.com/Leaflet/Leaflet.markercluster), relevant when results arrive in parts and are added to a map.

### Pitfalls the sources warn about

- A stalled or uneven bar (NN/g).
- Overly precise time estimates that prove wrong (NN/g).
- A spinner for a long process (Carbon).
- A "don't click again" warning instead of showing the first click was accepted (NN/g).
- Skeletons that stay on screen too long (Carbon).

Gap: NN/g's progress page says nothing about showing partial results during a wait. No primary page found describes streaming results into a list while a progress indicator runs.

## 6. Marking what is new since the reader last looked

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Dot badge on the item | Proximus design system notification dot: https://designsystem.proximus.com/pagesDS/15__Basic_Elements/Notification_dot/ and Maersk badge: https://designsystem.maersk.com/components/badge/ | Cheap, no count needed. Users can learn to ignore it if it never clears. |
| Visually distinct unread row (bold, tint) | Proximus (same page) | Scannable in a list. Needs a clear rule for when it resets. |
| Banner that tells the user something changed elsewhere | GOV.UK notification banner: https://design-system.service.gov.uk/components/notification-banner/ | Visible at the top of the page. People often miss banners, and it must not hold validation errors. |

### What the sources say

- GOV.UK: use banners sparingly, because "There's evidence that people often miss them". Show at most one per page, and put it directly above the `h1`. Success banners go away when the user moves to a new page.
- GOV.UK: if the information is central to the page task, put it in the main content with inset or warning text.
- Secondary sources, unverified as standards: reset the "new" signal when the panel is opened, cap or expire new-feature badges, and do not mix dot and count badges in one navigation: https://www.saasui.design/blog/saas-notification-center-ux-patterns and https://www.braze.com/resources/articles/beware-red-dot-badging
- A Discourse thread proposes a dot meaning "never opened" instead of "has new posts": https://meta.discourse.org/t/tone-down-the-new-indicator-and-change-it-to-mean-never-opened/31393 (user feedback, not a design system).

### Pitfalls the sources warn about

- A badge that is always lit teaches users to stop looking (secondary source).
- Colour alone as the signal. GOV.UK pairs colour with a text heading.
- Assistive technology users can skip a banner placed before the `h1` (GOV.UK).

Gap: no primary design system page defined "changed since last visit" for a single detail page. Field-level change markers were not found in any source.

## 7. Add and skip on suggestions with undo, and a home page with collection and search

### Patterns that recur

| Pattern | Named example | Trade-off |
| --- | --- | --- |
| Undo toast right after the action | Smashing Magazine: https://www.smashingmagazine.com/2024/09/how-manage-dangerous-actions-user-interfaces/ and A List Apart: https://alistapart.com/article/neveruseawarning | No interruption. A small toast in a corner may go unseen. |
| Time-boxed undo (hold the action briefly) | Gmail undo send, 5 to 30 s: https://blog.google/products-and-platforms/products/gmail/how-to-unsend-email-gmail/ | Works for actions that can wait. It holds the action, it does not reverse it. |
| Auto-dismissing flag with an action | Atlassian flag (unverified, page returned nothing): https://atlassian.design/components/flag/auto-dismiss-flag | A search snippet says 8 seconds. Not verified. |
| Soft delete behind the undo | Smashing Magazine (same URL) | Allows manual restore. Not wanted where law requires full erasure. |

### What the sources say

- Smashing: undo suits reversible actions such as moving to trash, changing status or applying filters. It does not suit purchases, legal submissions or most third-party API requests, where it creates "false safety".
- Smashing: overusing confirmation dialogs causes fatigue. Name the item and the action on the button, for example "Pay $97".
- A List Apart: "Never use a warning when you mean undo". Undo must be visible right after the action. Gmail's delete with undo plus a trash folder is the model. Shared data makes undo hard.
- Smashing on toasts: they are non-modal but must be noticeable.
- GOV.UK notification banner: avoid banners in linear flows. Use a confirmation page at the end.

### Home page with the collection and a search box

I found no primary design system page on a home page that shows a user's own collection beside a search box. Sources for this half of the problem are unverified. The nearest verified material is the Carbon filtering pattern (section 4) for narrowing a collection and the GOV.UK notification banner (section 6) for pointing at new items elsewhere in a service.

### Pitfalls the sources warn about

- Undo offered for something that cannot be undone (Smashing).
- Toast too small or low contrast (Smashing).
- Auto-dismiss that gives some users too little time to react. This is from older Atlassian AUI docs seen in a search snippet: https://aui.atlassian.com/aui/9.9/docs/flag.html (unverified).
- Keeping deleted data for undo conflicts with privacy expectations and adds storage (A List Apart comments).

Gap: no source covered an "add" or "skip" pair on a suggestion list. Searches for "people you may know" dismiss behaviour returned nothing usable.

## Rules worth copying

1. Always show an error summary at the top of the page, even for one error, and link each entry to its field. https://design-system.service.gov.uk/components/error-summary/
2. Word the summary entry exactly like the inline error. https://design-system.service.gov.uk/components/error-summary/
3. Add a review page before the final submit, with a change link per item that returns to the review. https://design-system.service.gov.uk/patterns/check-answers/
4. Name the submit button after its action and say that nothing is done until the user confirms. https://design-system.service.gov.uk/patterns/check-answers/
5. Show skipped optional values as "Not provided", not as a gap. https://design-system.service.gov.uk/patterns/check-answers/
6. Tell users before an import starts that it cannot be cancelled, and recommend a backup. https://help.shopify.com/manual/products/import-export/import-products
7. Match import columns by header name, not position, and state whether blank cells clear existing values. https://knowledge.hubspot.com/import-and-export/set-up-your-import-file
8. Offer a unique key so an import updates instead of duplicating. https://knowledge.hubspot.com/import-and-export/set-up-your-import-file
9. Give a rejected duplicate pair a way back and say plainly that merges cannot be reverted. https://knowledge.hubspot.com/records/manage-duplicate-records
10. In a merge, make the winning side explicit and let the user swap it. https://attio.com/help/reference/managing-your-data/records/merge-and-delete-records
11. Show a preview of what a merge will keep before it runs. https://attio.com/help/reference/managing-your-data/records/merge-and-delete-records
12. Show list and map side by side, not as an overlay, and put filters in a horizontal bar. https://baymard.com/blog/accommodations-split-view
13. Make a cluster of markers at one spot spread out at maximum zoom so each marker can be reached. https://github.com/Leaflet/Leaflet.markercluster
14. Use batch apply for filters across several categories or slow data, and instant apply for one category. https://v10.carbondesignsystem.com/patterns/filtering
15. When filters are collapsed, show the active count and a clear control without reopening. https://v10.carbondesignsystem.com/patterns/filtering
16. Use a percent-done or "n of N" indicator for waits over 10 s, and offer a way to stop. https://www.nngroup.com/articles/progress-indicators/
17. Do not use skeleton screens for long processes, and keep them to a few seconds. https://www.nngroup.com/articles/skeleton-screens/
18. For waits of a few minutes, let the user leave and tell them when it finishes. https://carbondesignsystem.com/patterns/loading-pattern
19. Use a banner for "something changed" sparingly, at most one per page, and never for validation errors. https://design-system.service.gov.uk/components/notification-banner/
20. Prefer undo to a confirmation dialog for reversible actions, and never offer undo for an action you cannot reverse. https://www.smashingmagazine.com/2024/09/how-manage-dangerous-actions-user-interfaces/
