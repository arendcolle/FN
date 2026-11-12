# Why each new part and page looks the way it does

Each part and page below gets three lines: the staff task it serves, the principle or pattern it follows with the file that names it, and what it leaves out. The principles come from `notes/e2e/research/ui-principles.md` (principles) and the patterns from `notes/e2e/research/ui-patterns.md` (patterns). The last two sections list the points where I depart from a written decision or think a decision is wrong for staff.

## New parts

FilterBar
- Task: narrow a network of a few hundred people to the ones near an event or from one file (story map, the flow "browse the network as a list and filter it").
- Follows: Carbon filtering in patterns (one category gets one box, applied filters stay visible with a clear for each and one global clear), Baymard in patterns (a horizontal bar above list and map), and "A list of people with filters" in principles (count and active filters next to the list, a zero result names its filter). Filter is a quiet button, because Search is the one dark button on Home (Von Restorff).
- Left out: selects for place and organization, sort, a "more filters" panel and live filtering, as D8 decided. Tokens come from where the user already is (a dot, an import).

Field
- Task: upload a file, fix a contact detail, tick a name match.
- Follows: GOV.UK error pattern in patterns (message at the field, worded as the fix) and "Every state answered" in principles. Checkboxes use `ink`, because green means Add.
- Left out: the GOV.UK error summary (patterns, rule 1). Every FN form has one field, so a summary repeats the message one line above it. Focus moves to the field instead.

DataTable
- Task: read which columns FN expects, and check the rows of a file before importing.
- Follows: Carbon data table in patterns (no table as a spreadsheet, rows between lines) and decisions.md ("wide tables use the full width"). The wrapper is a focusable region so keyboard users can scroll it.
- Left out: sorting, column controls, row selection and "Not provided" in blank cells. The preview is a check of the file, so blank stays blank.

Banner
- Task: see the result of an action that sent you to another page (import, discard, remove), or why an Undo was refused.
- Follows: GOV.UK notification banner in patterns (at most one per page, above the content, never for validation errors, gone on the next page).
- Left out: toasts, timers and a close button. Results shown in place (Add, Skip, Remove a fact, Save) keep their in-place confirmation and Undo ("Every action says what just happened and offers undo in the same place" in principles).

ShowMore
- Task: get past the first 50 people of a long search without losing your place.
- Follows: Carbon "load more" in patterns, chosen by D6, and goal gradient in principles ("50 of 518 shown"). The link is a plain GET with an anchor, so Back works and the page opens at the first new card.
- Left out: page numbers, infinite scroll and any count of people the ranker cut.

Profile
- Task: read everything FN knows about one person, fix contact details, and repair a wrong merge (flows 4 and 5).
- Follows: "A detail page of one person" in principles (most useful facts first, chunked into labelled groups, missing values marked "Not provided", main actions near the name, every fact with its source) and D5 rule 7 (Found as, Possible matches).
- Left out: a map of the one place, a ties line in the head (the "Ties to Belgium" group right under it says it in full), contact details for people not in the network, "Not this person" when only one record exists, and empty groups.

ImportSummary
- Task: know what an import will do before it does it, and decide the name matches FN cannot decide.
- Follows: GOV.UK check answers in patterns (button named after its action, "nothing is done until you confirm"), "An upload-and-import form with a preview" in principles (commit button carries the count, say what happens and how to undo before the click), HubSpot in patterns (blank cells clear nothing) and D7 (unticked boxes with a header box).
- Left out: a column mapping step (D3), a progress bar (files of a few hundred rows finish in one request), and Undo of the whole import, which no decision defines.

## Changed parts

- PersonCard: the database statement replaces raw record lines that today show as quotes (design.md, "What works today"). Same person and Add as new are both quiet, because D5 says nothing is preselected. The match line stays after the choice, so the card keeps its height.
- NetworkRow: the "new facts" mark is an outlined word, not a dot, because a dot that never clears teaches users to ignore it and colour alone fails (patterns, section 6). Rows align their text with the filter box's text.
- SectionHeading: action links on the right. The Network heading carries Import only. It drops its count, because the count line one line below gives the filtered count.
- Count line Export: Export ends the count line on Results and Network ("214 people · 12 not on the map · Export"), so it is one pattern next to the number it writes ("Use the same export pattern wherever an export is offered" in principles). The manager accepted this in place of D8's heading link. With a filter on, the link reads "Export these 9", the shortest wording that says the file holds the filtered people and not the whole network. Without a filter, "Export" next to the full count is enough.
- MapMarker: a popup at every width (D8). A shared dot lists names as links and leaves out "Open profile" per person, so five people do not get five identical links.
- Notice: the empty network names both ways in and offers Import ("An empty state" in principles: say why it is empty, one action forward).
- RecentSearches: capped at three with "All searches" under the list, where the eye ends after scanning.
- StatusLine: the two D9 notes sit where the status line was, in `failed`, with a quiet retry. They name no source, because staff never see lanes.
- Claim: Remove as a muted link per fact, and the removed state shrinks in place with Undo, the same pattern as Skip ("One pattern per repeated situation" in principles).
- ResultsLayout: Home scrolls as one page with a sticky map (`fn-results--page`), because recent searches sit above the network. Results and Network keep the full-window layout.
- ViewSwitch: links with `aria-current="page"`, as the site already builds them. I removed `overflow: hidden` from the switch so the focus ring on its links is not clipped.

## Pages

- Home: search first, unfinished work next (a running search stays in the three), then the network (principles, "A home page": the main action distinct, unfinished work first, chunked by whitespace). Left out: stats, as D8 decided.
- Home, empty network: the Notice in place of the list, with the map hidden. Left out: FilterBar and the count line, which have nothing to act on.
- Results: count line ending in Export on top, mixed card states, Show more, then the skipped line. Left out: the count line while the search runs, because the list is not final.
- Results, running: the status line, then people so far with their actions working (D9). Left out: time estimates and progress per source (D9 cut them).
- Network: Import on the heading, FilterBar, count line with Export, rows beside the map with one picked row and its popup. Left out: sort and clustering (D8).
- Network, filtered to nobody: "0 people", Clear all and a Notice that names both active filters ("A filter that matches zero people names the filter that caused it" in principles).
- Person: head, contact, grouped facts with two New marks, Found as, Possible matches.
- Person, candidate: back link to the results, Add and Skip in the head, no contact section, no empty groups.
- Import: the upload field first, then the column table. A returning user wants the field; a first-time user reads the table, and the "no name column" error points at it.
- Import preview: the summary in a reading column, the rows table at full width under it.
- All searches: the recent-searches list without the cap.

## Where I depart from a written decision

1. **Count arithmetic in the import summary.** The brief's example ("12 new people", "3 already", "2 same name", "1 row skipped", "Import 15 people") does not add up whichever way the same-name rows count. I used 10 + 3 + 2 = 15 imported and 1 skipped from 16 rows, and the button counts new, already-in and same-name rows.
2. **"Edit", not "Replace", for a contact detail.** D7 says the UI shows one Replace action. "Replace" reads wrong on an empty value ("Not provided · Replace"), and Edit opens the same one-call form that D7 describes.
3. **No count on the network heading.** The SectionHeading rule says headings carry a count. On the Network page the count line right under it repeats the number, so I dropped it there.
4. **"organization", not "organisation".** The filter placeholder uses the US spelling to match the CSV column name and the rest of the UI.
5. **README's "What staff never see".** It banned "the per-record breakdown of a person". D5's "Found as" lists a person's records with a fact count. I reworded the rule so Found as is the one allowed place, and kept the ban on per-record scores and "same name in N records".
6. **The site's popup markup changes.** `bundle.css` no longer has `.fn-popup__role + .fn-popup__name`. The new popup wraps each person in `fn-popup__person`, so `map.js` must emit that wrapper when `fn.css` becomes a byte copy, or a shared dot's names run together.

## Decisions I think are wrong for staff

1. **"Open profile" next to a linked name in the popup (D8).** The name already opens the profile. I kept both for the one-person popup because a visible verb is clearer on touch, but one of the two is redundant.
2. **Export sat in two places.** D8 put Export on the Network heading, while Results had it on the count line. Resolved: the manager accepted moving Export to the count line on both pages. Import stays on the Network heading.
3. **No Undo for a whole import.** Every other staff decision has an Undo. The design defines no inverse for an import event, so the summary can only say "You can remove anyone later from their profile", which for 15 people is 15 clicks. An "Undo this import" on the post-import Banner would close the gap.
4. **"Added to your network · 1 possible match" wraps.** At list widths under about 440px the line plus Undo takes two lines, so this one state makes the card one line taller and moves the cards below by 30px. D5's original shorter wording, "Added · 1 possible match", fits on one line.
5. **The row click does nothing under 900px.** D8 only says a row click pans the map. On a phone the map sits behind the switch, and jumping to the map view on a tap would surprise staff, so I left it out. If staff want it, the Map link is one tap away.
