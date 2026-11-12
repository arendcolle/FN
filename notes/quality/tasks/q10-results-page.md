# Task Q10: the results page

## Goal

The page shows 50 cards at a time, says "location not found" on more than half of the first 20, never says why a person is listed, and draws 329 dots for 50 cards. This task makes the page match the new order: 20 people at a time, a why line, the fact that matched as evidence, the place the evidence module picks, and a quieter dot for people not in the list yet. The design system changed first (version 10), and this task follows it. Decision D15 in [design.md](../design.md); measurements in [research/results-page.md](../research/results-page.md).

## The design system leads

- Copy the design system's `project/components/bundle.css` over `src/fn/web/static/fn.css`, byte for byte. It has three new rules: `fn-card__why`, `fn-card__combined` and `fn-marker--quiet`. Add no CSS anywhere else.
- Read these part files before you write markup: `components/PersonCard/README.md` and `preview.html`, `ShowMore`, `MapMarker`, `ResultsLayout`, `NetworkRow`, `Profile`, `Claim`. Copy their markup and class names.
- Bring `notes/e2e/design-system/STRINGS.md` and `DESIGN-NOTES.md` in line with the new texts below. They are the site's copy of the design system's words.

## What to build

1. **20 at a time.** `present.RESULTS_STEP` is 20. The line reads "20 of 518 shown" and the link "Show 20 more", then "Show 18 more" for a last batch. The link opens at the first new card.
2. **No words for a missing place.** A card, a network row and the profile's headline end after the employer when there is no place. The three copies of that line in `web/parts.py` become one function. The profile's Places section reads "Not provided" when it is empty.
3. **The place the evidence module picks.** `PersonView.place` and its coordinates come from `evidence.places`: the newest stated place, else the employer's city from a recent employer fact. `PersonView.place_basis` is `stated` or `employer`. When two employer facts share the newest date, the card shows the employer whose city is the shown place, else the choice of today.
4. **The why line**, `fn-card__why`, built only from the candidate's stored score parts: "Matches: " and the words of the `topic` part's detail, comma separated. " · Place from the employer" follows when the place's basis is `employer`. A person listed for their place alone reads "Based in " and the city. No line when none applies. A candidate stored before this work has no such parts and gets no line.
5. **The evidence that matched.** When the candidate has a `topic` part, the card's evidence is the first claim of that part. Otherwise it is today's choice. A topic claim whose source is an OpenAlex work reads "Paper: " and the title with the year, and its citation reads "OpenAlex work, 2023".
6. **The combined line**, `fn-card__combined`: when `identity.on_card` gives more than one record that are not merged into one person, the card says "Combined from 2 records", a link to Possible matches on the first record's profile.
7. **The map.** The geo answer of a results page gains, per person, whether they are among the shown cards and the link that shows them (`?shown=<the next multiple of 20 that includes them>#card-<id>`). `map.js` draws a person who is not shown with radius 5 and the `rule-strong` colour, a shared dot in `accent` when at least one of its people is shown, and ends an unshown person's popup with "Show in list" instead of "Open profile". The network map is unchanged. If this item cannot be finished cleanly, leave it out, say so, and finish the rest: it can merge on its own.

## Changes to existing tests, approved

Tests that pin 50 cards a page or "Show 50 more", the words "location not found", the exact markup of a card or a row where these two change, and the byte copy of the stylesheet follow the new behaviour. `tests/test_web.py`, `test_a_card_shows_employer_place_belgian_orgs_and_one_quote`: its search has a topic chip, so the card's evidence is now the claim that matched the topic; its quote assertions follow that claim. Say which tests changed and how. No other existing test may change.

## Inputs a real run will meet

A search stored before this work (no topic part, no card records, no group): it renders, without a why line; a list of 3 people; a list of exactly 20 and of 21; a card with no place, no role and no employer; a very long paper title (cut like a quote is cut on a card, whole on the profile); a card that combines 4 records; a person with a stated place and an employer in another city; every person without a place (no map dots, the count line says so); a narrow window (390 px).

## Tests

With made-up names, in the page tests:

- a list of 21 shows 20 cards and "Show 1 more"; `?shown=40` shows all
- a card without a place has no place text, and the string "location not found" is nowhere in `src/`
- the why line shows the topic part's words, adds "Place from the employer" for an employer basis, and is absent for an old candidate
- the evidence is the topic part's claim when there is one, worded as a paper for a work source
- the combined line shows for two unmerged records and not for one
- the geo answer marks unshown people and carries their link
- the stylesheet equals the design system's bundle

Each new test must be seen failing without the change it covers.

## Hand check

Start a server on your port on a throwaway var folder (`mkvar.sh q10`), run `fn-rerank --all` there first so stored searches have the new parts, and open a stored search. Take four screenshots with a headless browser (Playwright): the results page at 1280 px wide and at 390 px wide, the same page after "Show 20 more", and a person's profile reached from the combined line. Save them in your scratch folder and give their full paths. Look at each one before you report: the first card, the last card before the Show more line, and the map. Say what you see, without names.

## Not doing

- A label or divider for the first group, and the words "Best matches".
- Any change to the order.
- New parts in the design system. If the page needs a class or a string that is not there, stop and report it.
