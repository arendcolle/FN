# Panel 3 brief: how should the pages read and how does the user get back?

## What the owner asked

The results page is well designed and stays, with less text in the quoted paragraphs. The person page is the problem: it looks raw, shows too much source text, and its sections (work, education, places) are not clear. A fact should read short, such as "Studied at Ghent University", with a small source link for the reader who wants proof. After a click there must always be a clear way back, the way other applications do it.

## What the research found

Read these notes in `notes/quality2/research/` before you vote.

- `ux-walk-walk-new.md` and `ux-walk-walk-check.md`: two browser walkthroughs with screenshots, as a first-time organizer and as a careful reviewer. Both found the same things. On a wide screen the list returns to card 1 after every visit to a person or a source, because the list scrolls inside its own panel. The "Back to the results" link also drops "Show 20 more". A source page, a possible-match page, a person opened from the map and a person opened from the Network list have no way back. All 54 cards that say "Combined from N records" open a page that shows one record and lists the others as unconfirmed possible matches. One page has two "Remove" links with different meanings. Many quotes are raw page text and prove nothing. At world zoom only 2 of 9 map count markers can be clicked.
- `ux-patterns.md`: how other products solve it, with options A1 to A3 (list to person and back), B1 to B3 (person page), C1 to C3 (a source per fact) and D1 to D3 (card evidence), a text budget and a proposed section list. Today a card has a median of 41.5 words and quotes are 60% to 79% of a person page's words.
- `tiers.md`, section 5: the results list may get up to three headings that name which wishes a person meets.

The pages today: `src/fn/web/staff.py` (routes), `src/fn/web/parts.py` (markup of each part), `src/fn/present.py` (view models), `src/fn/web/static/results.js` and `map.js`. The design system leads: a page may only use parts it defines (PersonCard, Profile, Claim, Quote, SourceText, NetworkRow, MapMarker, ShowMore, ResultsLayout and others), so each choice below that needs something new means a design-system change first.

Limits that hold for every option: server-rendered HTML with small plain JavaScript files, pages that work without JavaScript where they do today, a phone layout at 390 px, a map next to the list on a wide screen, 20 cards at a time.

## The decisions

The options under each decision are listed in the panel's prompt.

- **U1** Where a person opens and how the user returns to the list.
- **U2** Which pages get a way back, and what the header marks as the current tab.
- **U3** How the person page is laid out.
- **U4** What the person page shows for a card that combines records.
- **U5** How a fact shows its source.
- **U6** What a source link opens.
- **U7** What a result card shows as evidence.
- **U8** How the two kinds of Remove are worded and confirmed.
- **U9** How the map starts and how its markers behave.
