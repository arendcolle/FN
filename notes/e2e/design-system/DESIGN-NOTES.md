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
- Task: get past the first 20 people of a long search without losing your place.
- Follows: Carbon "load more" in patterns, chosen by D6, and goal gradient in principles ("20 of 518 shown"). The link is a plain GET with an anchor, so Back works and the page opens at the first new card.
- Left out: page numbers, infinite scroll and any count of people the ranker cut.

Profile
- Task: read everything FN knows about one person, fix contact details, and repair a wrong merge (flows 4 and 5).
- Follows: "A detail page of one person" in principles (most useful facts first, chunked into labelled groups, missing values marked "Not provided", main actions near the name, every fact with its source) and D5 rule 7 (Found as, Possible matches).
- Left out: a map of the one place, a ties line in the head (the "Ties to Belgium" group right under it says it in full), contact details for people not in the network, "Not this person" when only one record exists, and empty groups other than Places, which reads "Not provided".

ImportSummary
- Task: know what an import will do before it does it, and decide the name matches FN cannot decide.
- Follows: GOV.UK check answers in patterns (button named after its action, "nothing is done until you confirm"), "An upload-and-import form with a preview" in principles (commit button carries the count, say what happens and how to undo before the click), HubSpot in patterns (blank cells clear nothing) and D7 (unticked boxes with a header box).
- Left out: a column mapping step (D3), a progress bar (files of a few hundred rows finish in one request), and Undo of the whole import, which no decision defines.

BackLink
- Task: return from a person, a source or a match to exactly where you were, and walk a list one person at a time (U1, U2).
- Follows: GOV.UK Back link (return to the previous page in the state last seen) and the A1 and A3 options in `notes/quality2/research/ux-patterns.md`, with Greenhouse's Previous and Next on a profile opened from search. The walk line counts the whole list ("4 of 143"), as the lead ruled.
- Left out: breadcrumbs, a side panel, keyboard shortcuts and a back link when the origin is unknown.

SummaryList
- Task: read who a person is at a glance before reading the facts (U3).
- Follows: GOV.UK summary list (a `dl` of key and value) and B1 in ux-patterns.md (summary first, sections second, two levels of disclosure). Rows reuse the contact rows' `rule` lines and key column, and stack under 900px.
- Left out: "Works at" and "Based in" (the head already shows them), source links (each row repeats a sourced fact below) and actions.

## Changed parts

Round 11 (UI-0, the quality2 round):

- Profile. Task: decide on one person in seconds, then check the facts (U3, U4). Follows: B1 in ux-patterns.md and NN/g progressive disclosure: head, a quiet why block, the summary, then sections. Section headings are `text-title` over a `rule-strong` line, `space-12` apart, because the owner found today's `text-label` headings did not read as headings. "Found as" becomes "Sources" with "Not this person" on every record but the page's own. Leaves out: "Not provided" for Places, sections whose facts all stand in the summary, tabs and a side panel.
- Claim. Task: read a fact in one line and check its proof without leaving the page (U5, U8). Follows: C1 in ux-patterns.md (Wikidata's collapsed references, GOV.UK details): the source name after the fact is the `summary` of an inline `details`, so the proof opens under the line and the line and "Not correct" stay put. Leaves out: footnote numbers, hover previews, a marker triangle, "date unknown", and the quote shown by default.
- Quote. Task: see the words that prove a fact, not the page around them (U5). Follows: Wikipedia's reference preview (one reference, short). At most 25 words around the matched words. Leaves out: quotes on cards, quotes over 25 words, and page debris.
- PersonCard. Task: decide Add or Skip from the list (U7). Follows: D1 in ux-patterns.md (one reason with its source next to it, NN/g explainable AI) and the lead's ruling on the second line (tie and place fit in words, since the headings say topic and tie). Leaves out: the quote, the ties line, the "Matches:" line and any tier or grade.
- SectionHeading. Task: see at once how well each group of people fits (R4). Follows: the existing heading with a count, repeated per tier. Leaves out: a new class and tier numbers.
- SourceText. Task: check a source in words, not raw record lines (U6). Follows: the source-page fix in ux-patterns.md (back link, one sentence, original link, raw record behind a disclosure). Leaves out: the raw record shown by default.
- MapMarker. Task: reach the people at one place with the keyboard, and open the map on the people shown (U9). Follows: MapLibre's own clustering and native buttons. Leaves out: focusable single dots (their cards are in the list).
- Header. Task: know which part of FN you are in from a person or source page. Search is current whenever the address carries a search. Leaves out: a third link.

Round 12 (UI-6a, after the second walkthrough, V1 to V21):

- Claim. Task: read a fact in the same words every time, with years that belong to it (V2, V3, V4, V17, V20). Follows: one relation list with an example line each, as GOV.UK writes one pattern once. A stated role joins its organization, a list entry reads as its relation, and a gap in the years shows in the proof. Leaves out: "Affiliated with", "Based in", "Field:", a page's title as a line, a record's place for an institution, and a changed-or-read day as a year. Not correct on a joined line hides role and organization together.
- Profile. Task: open on the current job and keep ties to ties (V1, V5, V8, V11, V12, V14, V15, V16, V18). Follows: the order a recruiter reads a CV, current job first, then stated roles, Belgian organizations and the rest, with one-year affiliations folded into one line. Sources has one row per record; actions return to the section they came from. Leaves out: a head line that is not a job, folding Belgian one-year affiliations, and forms in the 90-word budget.
- SummaryList. Task: show the one strongest tie once (V6, V13, V21). Follows: GOV.UK summary list; the key says Flanders or Belgium by where the organization is. Leaves out: a Studied row that repeats the tie, and weak ties.
- Quote. Task: keep evidence that is a sentence (V7, V9, V19). Follows: Wikipedia's reference preview, where only page furniture is dropped. Leaves out: field labels after a list mark, author-list tokens, markup entities, fragments under four words, and any quote from a LinkedIn profile.
- SourceText. Task: say which source the sentence comes from (V3, V9, V10). Follows: the cite line already in Claim. Long words wrap, so an address never widens the page at 390 px. Leaves out: a passage for a LinkedIn record, and the page's title as a sentence.

- PersonCard: the database statement replaces raw record lines that today show as quotes (design.md, "What works today"). Same person and Add as new are both quiet, because D5 says nothing is preselected. The match line stays after the choice, so the card keeps its height. A card without a place says nothing about it, because the count line already gives the number (D15). The why line names the matching words and the evidence is the fact that holds them, so staff see why a person is listed ("Show where each fact came from" in principles). "Combined from 2 records" is the one record count a card shows, a link to where staff split a record off.
- NetworkRow: the "new facts" mark is an outlined word, not a dot, because a dot that never clears teaches users to ignore it and colour alone fails (patterns, section 6). Rows align their text with the filter box's text.
- SectionHeading: action links on the right. The Network heading carries Import only. It drops its count, because the count line one line below gives the filtered count.
- Count line Export: Export ends the count line on Results and Network ("214 people · 12 not on the map · Export"), so it is one pattern next to the number it writes ("Use the same export pattern wherever an export is offered" in principles). The manager accepted this in place of D8's heading link. With a filter on, the link reads "Export these 9", the shortest wording that says the file holds the filtered people and not the whole network. Without a filter, "Export" next to the full count is enough.
- MapMarker: a popup at every width (D8). A shared dot lists names as links and leaves out "Open profile" per person, so five people do not get five identical links. On results, people beyond the shown cards get a smaller `rule-strong` dot and "Show in list", so every accent dot has a card next to it (D15).
- Notice: the empty network names both ways in and offers Import ("An empty state" in principles: say why it is empty, one action forward).
- RecentSearches: capped at three with "All searches" under the list, where the eye ends after scanning.
- StatusLine: the two D9 notes sit where the status line was, in `failed`, with a quiet retry. They name no source, because staff never see lanes.
- Claim: Remove as a muted link per fact, and the removed state shrinks in place with Undo, the same pattern as Skip ("One pattern per repeated situation" in principles).
- ResultsLayout: Home scrolls as one page with a sticky map (`fn-results--page`), because recent searches sit above the network. Results and Network keep the full-window layout.
- ViewSwitch: links with `aria-current="page"`, as the site already builds them. I removed `overflow: hidden` from the switch so the focus ring on its links is not clipped.

Round 13 (quality3, rulings N1 to N9, A1 to A3, E1 to E4, U1). Each entry names the pattern taken from a product that solves the same thing.

- SearchBox, the reading line (N7). Task: see at once whether FN understood the question, before reading any card. Follows Google's "Showing results for" line: one plain line under the box, read-only, and the user changes it by asking again. Also Google's "Missing:" note, which names in plain words what a result lacks, so "Required" and "Wished" are the question's own words, not codes. Left out: LinkedIn-style editable chip boxes, which turn a reading into a form to fill in and would add a second input to search pages; related words; and any "required" marker on the cards. Cost measured: one line at 1280 px, two at 390 px, and the first card still starts on the first screen at both widths (`q3/design/page-results-v13-*-first.png`).
- SetAside, a new part (N2, N3, N6, N8, A1). Task: keep the people FN found but does not count within reach, without letting them crowd out the matches. Follows the GOV.UK details component (closed by default, opened in place, the title says what is inside) and Google's closing note on omitted results, which puts the extra results at the end behind one line instead of mixing them in. Five groups in a row read well as rows between `rule` lines, the pattern every repeated item outside cards already has, under one "Set aside" heading that carries the total. One heading over all five tells staff the list of matches has ended; five more headings with the same weight as the match headings would read as five more tiers. Left out: a single closed "More people" block with sub-groups inside (two clicks to reach anyone), a marker triangle, colour, and map dots for set-aside people.
- SetAside, group words. "Outside `{place}`" and "Outside the US" name the reason in the question's own place words. "Other roles or topics" is used for the fit check's "no", because "Not scientists" only works for some questions and FN's "no" is a judgement, not a sourced fact. "People who have died" is the ruling's own wording. "Other people found" keeps its round-12 name.
- PersonCard, set-aside line (N2, N3, A1). Task: see why a person is set aside and check it. Follows the card's reason line: one fact with its source name. For the place groups the place moves from the role line to this line, so the card never says the place twice. Departure from A1: the ruling says the card shows the source quote; cards carry no quote in this system, so the card shows "Died 1966" and the source link opens the Source page with the quote marked. People who have died get no Add or Skip, because nobody invites them.
- PersonCard, old record (A2, A3). Task: know before writing that a person may not be active. "First record 1958, nothing recent" sits on its own line after the tie, because on the tie line it broke in the middle at 380 px. It states what FN knows and leaves the conclusion to staff. Left out: a line for A3, whose order alone does the work, and the word "retired".
- PersonCard and headings, place unknown (N4). Checked in the mockup: under the first heading the people inside the area come first, then cards whose second line ends "place unknown". The heading words stay the same and the card states the one difference, so no new line or sub-heading is needed.
- SectionHeading, no full match. Task: understand an empty top tier without reading every card. Follows Google's "Missing:" note again: name what is missing in plain words, once, above the list. Uses `fn-note`, no new class. Left out: the line when there are a few full matches, because the heading's count already says so.
- StatusLine, lookup (E1, S2). Task: know the list is still settling. "Looking up missing facts…" replaces the count while FN looks up facts for the first people. Left out: "for the first people", which made the bar 30 px wide at 390 px and adds nothing staff can act on; lane names; and counts of calls. Lanes side by side change no words.
- Profile, Look up more (E1, E2, E3). Task: get more facts for a promising person, and know how fresh they are. Follows HubSpot's enrichment, which records on the record when it was enriched and which properties it filled, and the Banner rule of saying what happened in the past tense. One line under the summary holds the date and what was added, next to a quiet button, reusing the ShowMore line. While looking it shows the StatusLine, and a stop shows the StatusLine note. "Not sure it is the same person" is said plainly, because E3 makes it a normal outcome. Left out: a time estimate, a list of sources tried, and a disabled button within 90 days.
- Profile, contact found by FN (E4). Task: email the person. The Contact section now also shows for people outside the network when FN holds a value, each with its source name like every fact (the Claim proof), because a found address needs its page to be trusted. The summary's Contact row keeps the values for the first screen; the section holds the sources. Left out: Edit for people outside the network, and "Not provided" rows for them.
- SourceText, stored record (U1). The disclosure is a debugging aid and is off unless `stored_record` is on.
- Review fixes, round 13. Reading line: a nationality or tie stands under Required when the question requires it and under Wished when the question only wishes for it (lead ruling); " · " sits in the Wished span so no line ends on a dot; no `aria-describedby`, because the line describes the last question, not an edited one. Count line: the open list, network people included, and never the set-aside groups (lead ruling); it becomes the `role="status"` element when a search ends, so the done state is heard when script updates the page in place. No-full-match line: drops "No full match:", and says nobody has a known tie only when the tie is a wish; with a required tie it names what the people below lack. Died cards: "Died 1966" takes the role line's place, because a present-tense role read as a current job. Network people in a group: same rules, no buttons, "In your network" on the card. Open group: the title takes the `text-strong` weight (one CSS rule), following GOV.UK details, whose summary changes with the state. Person page: no Contact row in the summary for people outside the network, so every value shows once with its source. Look up more: one `role="status"` container at `#lookup` that script updates in place and that takes focus only on the answer to the user's own press, a form post that works without JavaScript, and "Look up again" after a lookup, so a second press visibly means a new run.
- CSS: 11 rules added to `bundle.css` (two for the reading line, eight for SetAside, one that keeps a `text-year` year at the size of a card's small line) and `flex-wrap: wrap` on `fn-search`. Everything else reuses `fn-card__fit`, `fn-card__source`, `fn-note`, `fn-more`, `fn-status` and `fn-status-note`.

## Pages

- Home: search first, unfinished work next (a running search stays in the three), then the network (principles, "A home page": the main action distinct, unfinished work first, chunked by whitespace). Left out: stats, as D8 decided.
- Home, empty network: the Notice in place of the list, with the map hidden. Left out: FilterBar and the count line, which have nothing to act on.
- Results: count line ending in Export on top, mixed card states, Show more, then the skipped line. Left out: the count line while the search runs, because the list is not final.
- Results, running: the status line, then people so far with their actions working (D9). Left out: time estimates and progress per source (D9 cut them).
- Network: Import on the heading, FilterBar, count line with Export, rows beside the map with one picked row and its popup. Left out: sort and clustering (D8).
- Network, filtered to nobody: "0 people", Clear all and a Notice that names both active filters ("A filter that matches zero people names the filter that caused it" in principles).
- Person: head, contact, grouped facts with two New marks, Found as, Possible matches.
- Person, candidate: back link to the results, Add and Skip in the head, no contact section, no empty groups other than Places.
- Import: the upload field first, then the column table. A returning user wants the field; a first-time user reads the table, and the "no name column" error points at it.
- Import preview: the summary in a reading column, the rows table at full width under it.
- All searches: the recent-searches list without the cap.

## Pages, round 11

- Person, v11 (`preview/page-person-v11.html`): a person opened from a search, combined from 2 records, with one proof open and one removed fact.
- Source, v11 (`preview/page-source-v11.html`): the readable page for a web page source, stored record closed.
- Results, v11 (`preview/page-results-v11.html`): the results mockup with the new cards under two of the tier headings.

## Pages, round 12

- Person, v12 (`preview/page-person-v12.html`): Elke Voorbeeld, a researcher whose Work opens on her current professorship, with Show more closed and open, and the folded "Also named at" line.
- Source, v12 (`preview/page-source-v12.html`): Jonas Testman's page, "The page names Jonas Testman.", the cite line and a passage with a long email address that wraps at 390 px.

## Where I depart from a written decision

1. **Count arithmetic in the import summary.** The brief's example ("12 new people", "3 already", "2 same name", "1 row skipped", "Import 15 people") does not add up whichever way the same-name rows count. I used 10 + 3 + 2 = 15 imported and 1 skipped from 16 rows, and the button counts new, already-in and same-name rows.
2. **"Edit", not "Replace", for a contact detail.** D7 says the UI shows one Replace action. "Replace" reads wrong on an empty value ("Not provided · Replace"), and Edit opens the same one-call form that D7 describes.
3. **No count on the network heading.** The SectionHeading rule says headings carry a count. On the Network page the count line right under it repeats the number, so I dropped it there.
4. **"organization", not "organisation".** The filter placeholder uses the US spelling to match the CSV column name and the rest of the UI.
5. **README's "What staff never see".** It banned "the per-record breakdown of a person". D5's "Found as" lists a person's records with a fact count. I reworded the rule so Found as is the one allowed place, and kept the ban on per-record scores and "same name in N records".
6. **The site's popup markup changes.** `bundle.css` no longer has `.fn-popup__role + .fn-popup__name`. The new popup wraps each person in `fn-popup__person`, so `map.js` must emit that wrapper when `fn.css` becomes a byte copy, or a shared dot's names run together.
7. **Person page section headings are `text-title`, not `text-label`.** The task keeps `h2.fn-section` markup; the owner said the person page's sections are not clear and its headings do not read as headings. A 13px label over one-line facts did not separate them in the screenshots; `text-title` over a `rule-strong` line does. The results headings and the why block keep `text-label`.
8. **The why block's first line drops the source name.** The card's reason line ends with its source; on the person page the same fact stands with its source in a section below, so the why block keeps the words only.
9. **A record's proof keeps "Original page" unless its url starts with `fn:`.** The task's sentence can be read as "every record has no Original page". An OpenAlex or LinkedIn record has a real url, so I kept the link there and dropped it only for `fn:` urls.
10. **Claim rows are tighter.** `fn-claim` padding goes from `space-4` to `space-3`, because a claim is now one line. The site's quote-style claims get the same padding until UI-4.

## Decisions I think are wrong for staff

1. **"Open profile" next to a linked name in the popup (D8).** The name already opens the profile. I kept both for the one-person popup because a visible verb is clearer on touch, but one of the two is redundant.
2. **Export sat in two places.** D8 put Export on the Network heading, while Results had it on the count line. Resolved: the manager accepted moving Export to the count line on both pages. Import stays on the Network heading.
3. **No Undo for a whole import.** Every other staff decision has an Undo. The design defines no inverse for an import event, so the summary can only say "You can remove anyone later from their profile", which for 15 people is 15 clicks. An "Undo this import" on the post-import Banner would close the gap.
4. **"Added to your network · 1 possible match" wraps.** At list widths under about 440px the line plus Undo takes two lines, so this one state makes the card one line taller and moves the cards below by 30px. D5's original shorter wording, "Added · 1 possible match", fits on one line.
5. **The row click does nothing under 900px.** D8 only says a row click pans the map. On a phone the map sits behind the switch, and jumping to the map view on a tap would surprise staff, so I left it out. If staff want it, the Map link is one tap away.

## Pages, round 13

- Results, v13 (`project/components/page-results-v13.html`): a done search with a required place and a required tie, the reading line with no Wished part, the first heading with three people inside the area and then two with "place unknown", the old record last in that heading, "Tie, topic not confirmed", and "Set aside" with "Outside the Washington D.C. area" open. No "Topic, no known tie", because the tie is required. 8 people in the count line (2 in the network and 6 under the match headings) and 124 set aside.
- Results running, v13 (`project/components/page-results-running-v13.html`): "Looking up missing facts…", the cards found so far with one added, and three groups filling.
- Results few, v13 (`project/components/page-results-few-v13.html`): a required tie and no full match, the line that says the people below have a tie but no confirmed topic, "Tie, topic not confirmed" with 2 people, "2 people" in the count line and three groups.
- Person, v13 (`project/components/page-person-v13.html`): Ines Goossens after a lookup: the lookup line with "Look up again", the place in the head, and the Contact section with a source on each value and New on the added email and on the added place, which stays in Places until the page is opened again so the lookup line points at a line with a source. The walk line reads "5 of 8": the open list, network people included, never the set-aside groups. No Contact row in the summary, because she is not in the network.

## Where I depart from a written decision, round 13

1. **A1 says the card shows the source quote.** Cards carry no quote in this system. The card shows "Died 1966" with its source link, and the quote is one click away on the Source page.
2. **The Contact section shows for people outside the network.** Round 11 kept it for network people only; E4 gives FN found values for anyone, and they need a place with their source.

## Lead rulings after round 13

- **Reading line.** A tie stands under Required when the question requires it and under Wished when the question only wishes for it. When the question requires a tie, FN leaves out every person without a known tie, so "Topic, no known tie" never prints and the mockup reads "Required: scientists, Belgian, in the Washington D.C. area".
- **Count line.** The count counts the open list: "In your network" plus the three match headings, never the set-aside groups. The mockup reads "8 people" (2 and 6) and the walk line "5 of 8".
- **Old record.** A person whose card says "First record 1958, nothing recent" sorts after everyone else under the same heading.


## Review fixes, round 13

- **Walk line total.** The walk covers the open list ("5 of 8": 2 in the network and the 6 under the match headings), because that is the list the user scrolls past to open the card. A person opened from a set-aside group walks only that group ("3 of 59"), so Next never jumps between the open list and a closed group.
- **Live regions update in place.** The done count line and the lookup result are announced only because script replaces the text of a `role="status"` element that already exists. A reload announces nothing, so the READMEs say so instead of claiming it. Focus moves to `#lookup` only on the answer to the user's own press.
