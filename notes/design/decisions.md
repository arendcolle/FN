# What the FN design system and restyle must follow

The owner settles these in a question-and-answer review before anyone writes the design system. FN's pages are for delegation staff and get a calm, dossier-like look with its own identity. Before anything is styled, a later session removes what exists only for debugging. The page set is still open.

## Who it is for and how it looks

These decisions hold for every page and every token.

- **Users.** The future staff of 5 to 20 people at the delegation, not only the owner.
- **Identity.** FN's own. No government or FIT branding, because the owner has no official affiliation.
- **Name.** The two letters "FN". No tagline and no logo.
- **Theme.** Light only.
- **Feel.** A dossier. Person names and quotes are set in a serif, the interface in a sans, and years in a monospace. Thin rules replace boxes and shadows, on a warm off-white ground.
- **Clarity.** Less is more. Text is big enough to read, and whitespace is placed on purpose. No stacks of cards and no extra information that helps nobody. Every line, card, button and toggle has to earn its place.
- **Size.** Body text 15px, picked on the mockup. Tables and metadata 13px, spacing in 4px steps.
- **Cards.** Allowed where they help, never the default wrapper for everything. Each person in the results is a card.
- **Width.** Reading pages sit in a column of about 80 characters per line. The map and wide tables use the full width.
- **Colour.** Status always shows as a word, with colour as a second signal. Blue means running and orange-red means failed, with no green and red pair.
- **Fonts.** Open-licensed families, such as those on Google Fonts. Their woff2 files are committed to `src/fn/web/static/fonts/` and copied into the design system. No page requests a font CDN. Source Serif 4 sets the FN name, person names and quotes. IBM Plex Sans sets the interface, and IBM Plex Mono sets years. Counts and dates written as words stay in Plex Sans, as in the approved mockup.
- **Accent.** Deep green `#2d5a47`, used only for Add, the picked card and the map markers.
- **Quotes.** Upright serif with plain quote marks, no italic and no hanging mark.
- **Map markers.** Dots in the accent colour. The dot of the hovered or picked person is larger.

## Pages and what staff see

Staff type a question into one box and see people. Everything about how FN got there stays out of their view.

- **Staff pages.** Ask `/`, Results `/searches/{id}`, Person `/people/{id}`, Source `/sources/{id}` and Network `/people`. Person and Network are designed now and built later.
- **No chips.** The question box is the only input. Chips, scores, lanes, traces, the per-record breakdown, the org-facts notes and step statuses move to `/debug`.
- **Debug pages.** They stay at `/debug` for the owner only, with no link from a staff page, and get only the base styles.
- **One person in the results.** A card with name, role and employer, place, one line of Belgian ties, one quote as the reason with its source, and Add and Skip. Everything else is on the Person page. People already in the network show no buttons.
- **Results layout.** The list of cards and the map sit side by side, as in the map views of Funda and Booking. The list's top lines up with the map's top. The layout works at every screen width, and on narrow screens a List and Map switch replaces the side by side. Wide screens have no list-only view, because a search returns tens of people.
- **Search box on results.** The question stays in an editable box at the top of the results page.
- **Duplicates and merges.** Not shown in the results. Finding duplicates and merging are steps of the Add flow, designed later.
- **Components for later features.** The system has generic parts that Add, Skip, Merge, Network, export and a progress state can use. It does not design those features in detail, because their behaviour is not decided.

## Screens and states

Every screen says what happened and what to do next.

- **Ask.** The search box sits where it sits on the results page. Recent searches follow as plain rows with the people count and the date, "Searching…" in blue and "Failed" in orange-red.
- **Searching.** People appear as FN finds them. A line above the list says "Searching… 3 people so far" next to a moving blue bar.
- **No results.** The page says how many sources FN read and suggests a broader topic or a wider area. The map is hidden.
- **Failed.** "This search stopped", one plain sentence and a Try again button. Staff see no technical details, and nothing found before the stop is shown.
- **Add and Skip.** Add turns its buttons into "Added to your network" with Undo. Skip shrinks the card to one line with Undo and removes the person's dot. The design system holds these states; the logic is built later.
- **Person and Network pages.** The system holds their parts, a claim with its quote, source and date and a list row, not full page designs.

## What the design system holds

The design system is a claude.ai artifact with four parts:

- `tokens.json` with colours, type styles, spacing and radii
- a README with usage rules that name the tokens
- static HTML previews of the parts of the site
- a cover with the name "FN"

It has no React components, because the site is server-rendered HTML.

## How the site gets restyled

A fresh session restyles the site in two steps:

1. Strip everything that exists only for debugging and everything that breaks the clarity rule.
2. Style what stays, using the design system.

## Still open

Nothing. The owner confirmed the summary on 2026-11-03.
