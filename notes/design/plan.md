# How to build the FN design system

This plan turns [the decisions](decisions.md) into the files of the FN design system artifact at https://claude.ai/artifact/WGaDjfBwi5z6y2HWds2Ayz. It lists every token, every part with a preview, who owns what between the design system and the site, what is out of scope, and the checks that prove it is done. Values come from the approved mockup, `scratchpad/mockups/results.html` in the session that wrote this plan. A fresh Opus review found 3 blockers and 12 smaller issues in the first version, and this version fixes all of them.

## Changes from the mockup

These differences are deliberate.

- Input and quiet-button borders use `field` #948c80 instead of #cfc8bc, because #cfc8bc is 1.7:1 on white and control borders need 3:1.
- Paddings snap to 4px steps, as the decisions require: buttons go from 9px 16px to 8px 16px, the input from 10px 14px to 12px 16px, and recent-search rows from 14px to 16px. No change is larger than 2px a side.
- The person name and the notice title are 20px instead of 19.5px.
- The focus ring is a 2px solid `ink` ring with a 2px offset, because an accent ring disappears on the accent Add button and on a picked card.
- The Source page highlight uses `rule` with an underline, so the accent stays limited to Add and its confirmation, the picked card and the map markers.
- IBM Plex Mono sets years only. Counts and dates written as words ("March 2024") stay in Plex Sans, as in the mockup.
- Source Serif 4 uses static 400 and 600 files at one optical size. The mockup loaded the variable font with an optical-size axis. The difference at 15px to 22px is small, and the variable files would be a new download for the owner to approve.

## Files the system gets

All paths sit under `project/` in the artifact, in the shape the Design System type's `format.md` describes.

- `design-system.json`, the index, written last. The artifact has no index yet, so it is new: `{"v":3, "layout":"files", "createdOnFiles":{"v":1,"at":"<now>"}, "title":"FN", "namespace":"FN", "libraries":[], "sections":{}, "groups":[], "assetGroups":{}, "blobs":{}, "docs":{"readme":"project/README.md","sections":[]}, "lastChange":{...}}`.
- `tokens.json`, with one theme `[{"id":"light","name":"Light"}]`, the family keys `serif`, `sans` and `mono`, one `type.groups` list, and one `type.fonts` entry (family, file, weight, style) for each latin woff2.
- `README.md`, with usage rules that name the tokens.
- `components/bundle.css`, one stylesheet with every part's classes, all prefixed `fn-`.
- `components/<Part>/README.md` and `components/<Part>/preview.html`, for each part below.
- `components/Cover/preview.html`, the cover.
- `fonts/`, the 10 woff2 files: 5 latin files listed in `tokens.json` and 5 latin-ext files the site loads with `unicode-range`.
- `assets/Fonts/`, the 3 OFL licence files and a `README.md`, because `fonts/` holds font binaries only.

There is no `bundle.js`, because the site is server-rendered HTML and the previews are static markup.

## Tokens

Contrast ratios are WCAG 2 ratios, computed with a script against `ground` and `raised`.

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `ground` | #faf8f4 | Page background | |
| `raised` | #ffffff | Cards, inputs | |
| `ink` | #1f1d1a | Text, dark button fill, focus ring | 15.9 on ground |
| `on-ink` | {ground} | Text on a dark button | 15.9 |
| `muted` | #6b665e | Secondary text, citations | 5.4 on ground |
| `rule` | #e4dfd6 | Card borders, dividers, the Source page highlight | decorative |
| `rule-strong` | #bfb6a8 | Hovered card border | decorative |
| `field` | #948c80 | Borders of inputs, quiet buttons and the List/Map switch | 3.1 on ground, 3.3 on raised |
| `accent` | #2d5a47 | Add, "Added to your network", the picked card, map markers | 7.4 on ground |
| `on-accent` | #ffffff | Text on accent | 7.9 |
| `running` | #2a5d9f | "Searching" text and bar | 6.3 on ground |
| `running-track` | #dfe6f0 | Track behind the searching bar | |
| `failed` | #b3401a | "Failed" and "This search stopped" | 5.4 on ground |
| `map-ground` | #e9e6df | Map area before tiles load | |

Type uses three families. Source Serif 4 sets the FN name, names, quotes and titles, IBM Plex Sans sets the interface, and IBM Plex Mono sets years. Each style is a class `text-<name>` in the generated `tokens.css`, and component classes start with `fn-`, so they never collide.

| Style | Family | Size / line height | Weight | Use |
| --- | --- | --- | --- | --- |
| `text-logo` | serif | 22px / 22px, letter spacing 0.02em | 600 | FN in the header |
| `text-name` | serif | 20px / 25px | 600 | Person name on a card |
| `text-title` | serif | 20px / 26px | 600 | Notice titles, the Source page title |
| `text-quote` | serif | 16px / 1.5 | 400 | Quotes |
| `text-popup` | serif | 15px / 1.3 | 600 | Name in a map popup |
| `text-body` | sans | 15px / 1.5 | 400 | Body text |
| `text-strong` | sans | 15px / 1.5 | 500 | Status line, "Added to your network" |
| `text-control` | sans | 15px / 1 | 500 | Buttons |
| `text-switch` | sans | 14px / 1 | 500 | The List/Map switch |
| `text-meta` | sans | 14px / 1.4 | 400 | Recent-search meta |
| `text-meta-strong` | sans | 14px / 1.4 | 500 | "Searching…" and "Failed" in recent searches |
| `text-small` | sans | 13px / 1.4 | 400 | Citations, table cells, popup role |
| `text-label` | sans | 13px / 20px | 500 | Section headings |
| `text-year` | mono | 14px / 1.5 | 400 | Years |

Spacing is in 4px steps: `space-1` 4px, `space-2` 8px, `space-3` 12px, `space-4` 16px, `space-5` 20px, `space-6` 24px, `space-7` 28px, `space-8` 32px and `space-12` 48px. Radius has three steps: `radius-sm` 2px for the searching bar, `radius-md` 6px for buttons, inputs and the switch, and `radius-lg` 8px for cards and the map. The `layout` family records widths: `list-width` `clamp(400px, 34vw, 520px)`, `search-width` 880px, `notice-width` 560px, `narrow-list-width` 760px and `measure` 72ch for the Source page text. The 900px breakpoint is written into `bundle.css` as 900px and 899px, because custom properties do not work in media queries, and the README says so.

## Parts with a preview

Each part has a README that says when to use it and what the page provides, and a preview that renders its states. A part's markup puts the `text-*` class on each text element, and `bundle.css` never sets font size, line height, weight or family. The one exception is the base rules for bare elements the site cannot give a class (`body`, `th`, `td`, `pre`), and each of those names the style it copies.

| Group | Part | States in the preview |
| --- | --- | --- |
| Layout | Header | FN and the Search and Network links, the current link underlined with `aria-current="page"` |
| Layout | SearchBox | Empty with placeholder, a long question wrapping to 3 lines, the error "Type a question", the 1,000-character error |
| Layout | ResultsLayout | List and map side by side, `width=960` |
| Layout | ViewSwitch | List state and Map state of the narrow layout, `width=375` |
| Actions | Button | Add, dark, quiet, link, each with its focus ring |
| Results | SectionHeading | "In your network 2", "New 3" |
| Results | PersonCard | Network person, new person with Add and Skip, hovered, picked (`aria-current="true"`), added, skipped, a long name, more than three ties |
| Results | MapMarker | Default dot, larger dot, a shared dot with a count, the narrow-screen popup |
| Status | StatusLine | "Searching…" with no count, "Searching… 1 person so far", "Searching… 3 people so far", the static bar under reduced motion |
| Status | Notice | No results, failed |
| Ask | RecentSearches | Done with a count, searching, failed, zero people |
| Evidence | Quote | A quote with source and date, a cut quote with "…", a quote with no date |
| Evidence | Claim | One claim for the Person page: relation, organization, years, quote, source |
| Evidence | SourceText | A Source page title and text with the quote highlighted and underlined |
| Network | NetworkRow | One person in the network list |
| Debug | Table | The base table the debug pages use |

## Inputs a real page will send

The previews and README rules cover these cases, which the mockup does not show.

- A long name, such as "Marie-Christine Van den Bossche-Vandewalle", wraps inside the card and never pushes the buttons out.
- A person without a place shows "location not found" and has no map dot.
- When nobody in a result has a place, the map is hidden and the list takes the reading width.
- People at the same point share one dot with their count. Hovering any of their cards enlarges that dot, and clicking it outlines all their cards and scrolls to the first.
- A quote over 240 characters is cut at a word with "…". The server adds the quote marks and the ellipsis, and turns double quotes inside a quote into single ones. The Person page shows the quote in full.
- More than three ties show the first three and "+2 more".
- A claim without a date shows "date unknown" in its citation.
- The search box is a text area that grows to 3 lines and then scrolls, so a question up to the app's 1,000-character limit stays readable.
- A name with extended Latin letters, such as "Łukasz Şahin", renders in Source Serif 4, because the site loads the latin-ext files as well.
- A search with 100 people scrolls inside the list column while the map stays in place.
- A user who prefers reduced motion sees a static searching bar.

## Who owns what

One owner per responsibility. The restyle session is the fresh Claude Code session that moves debug-only content and restyles the site after the system is published.

| Responsibility | Owner |
| --- | --- |
| Token values and their usage notes | Design system, `tokens.json` |
| Usage rules for each screen and state | Design system, `README.md` and the part READMEs |
| How each part looks | Design system, `components/bundle.css` and the previews |
| Which font files to use, with their pinned Fontsource versions and sha256 hashes | Design system, `README.md` |
| What staff pages never show: scores, lanes, chips, traces, record breakdowns, org-facts notes, step statuses | Design system, `README.md` |
| Moving debug-only content from staff pages to `/debug` pages, each still reachable there | Restyle session |
| The site's `tokens.css` (custom properties, `text-*` classes, `@font-face` with `unicode-range`), generated from the system's `tokens.json` | Restyle session |
| The site stylesheet `fn.css`, built from `bundle.css` | Restyle session |
| Copying the fonts into `src/fn/web/static/fonts/` and checking their hashes against the README | Restyle session |
| HTML structure and class names in `html.py` and `app.py` | Restyle session |
| `map.js`: marker paint from `accent`, card and dot linking, shared dots, the List/Map switch and the popup, plus a person id in the geo API | Restyle session |
| Tests in `tests/test_web.py` that change with the move | Restyle session |
| Live updates without a full page reload, and people appearing as FN finds them | A later session |
| Logic for Add, Skip, Undo, and the Person and Network pages | Later sessions |

A change to a value starts in the design system and then goes to the site, so the two do not drift.

## Not doing

- No React components and no `bundle.js`
- No full Person or Network page designs, only their parts
- No logic for Add, Skip, Undo, merging or duplicate checks
- No live updates or streaming; StatusLine has a state without a count until then
- No dark theme, no logo and no tagline
- No changes to the FN repository's code in this session; the restyle session makes them
- No `tokens.css`, `manifest.json` or `api/` cards in the system, unless the check after publishing shows the previews get no tokens without one

## The cover

The type requires colour blocks and one pattern next to the name. The cover shows "FN" in Source Serif 4 with no tagline. Its blocks are `accent` as the large block, then `ink` and `rule`, crossed by four hairlines in `rule-strong`, which is the editorial pattern in `cover.md`. The height is 288px. The owner hears that the blocks are decoration on the system page and not a logo.

## Checks that prove it is done

1. A script computes the contrast of every text and control pair the README names and fails below 4.5:1 for text or 3:1 for borders, rings and markers.
2. A local harness renders every preview with the tokens, `bundle.css` and the fonts, and runs axe-core from cdnjs on it in the browser pane. Any violation fails the check.
3. In the same harness, a script compares the computed font size, line height, weight, colour and padding of 10 named elements against the mockup at 1440px and 375px. Only the changes listed under "Changes from the mockup" may differ.
4. In every harness preview, `document.fonts` reports Source Serif 4, IBM Plex Sans and IBM Plex Mono as loaded.
5. After publishing, the artifact lists every file above, `project/tokens.css` is read to see whether the page generated it, and the Colors, Typography and Spacing views show the same number of tokens as `tokens.json`.
6. In the browser pane, the artifact shows the cover, the brand book and every preview with no blank or broken frame.
