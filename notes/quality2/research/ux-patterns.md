# How should FN move between list, person and source, and show proof without walls of text?

## TL;DR

Keep the person page a full page, and make its Back link return to the exact card, with the shown count in the URL. Add Previous and Next so Paul can walk the list without going back. Open the person page with a short summary list (works at, based in, studied, tie to Flanders, contact). Write each fact as one line with a small source name after it, and let the source name expand the quote in place. Cards drop the quote and show one reason line plus a line of met and unmet wishes. Today quotes fill 60% to 79% of a person page and a card quote runs 30 words at the median (measured below). The proposed budget is at most 25 words per card and at most 90 words on the first screen of a person page.

## What FN does today

These numbers come from GET requests to the running app on 2026-11-12, for the search "Who could speak about AI in health care in Boston..." (20 cards) and the first three people on it. Forms and buttons are left out of the counts.

| Measure | Value |
|---|---|
| Words per card, median of 20 | 41.5 (range 24 to 80) |
| Cards with a quote | 19 of 20 |
| Quote words per card, median of 19 | 30 (range 8 to 59) |
| Person page words (3 pages) | 172, 281, 300 |
| Of which quote words | 104, 181, 236 (60%, 64%, 79%) |

What the code does, read in the source:

- The card name links to `/people/{id}?search=...&from=card` in the same tab.
- The person page's "Back to the results for ..." link goes to `/searches/{id}`. It drops the `shown` count, so a card past the first 20 is gone after Back. It also has no `#card-...` anchor, although every card already has `id="card-<key>"`.
- On a wide screen with the map, the list scrolls inside its own box (`overflow-y: auto` on the results list). Browser scroll restoration covers the page scroll. Whether it restores that inner box after a full reload is not checked.
- The results page sends no `Cache-Control: no-store`. Whether Chrome and Safari keep it in the back/forward cache with the map running is not checked.
- A "source" link opens the stored record as raw `field.path: value` lines, with the matching lines highlighted and no way back (see the current screenshot of the source page).
- One card quote reads as page debris: an author name followed by "1, 2 Author Orcid Image". A quote copied from a page shows what the page contains, not why the person fits.

The owner's knowledge base has no page on list views, detail pages or progressive disclosure. Three of its pages apply. Its Miller's law page says to chunk content, not count items. Its Hick's law page says fewer choices shorten decisions. Its Jakob's law page says to reuse patterns users know from other products.

## (a) From the list to one person and back

Pick by one dimension: where the person opens. The options are a full page, a panel beside the list, or a full page you can step through.

**A1. Full page that returns to the card.** GOV.UK's Back link component says the link must take users "to the previous page they were on, in the state they last saw it" ([GOV.UK Back link](https://design-system.service.gov.uk/components/back-link/)). NN/g calls the open-item-then-Back habit pogo sticking and says listing pages must support it. It names BMW's US site as a failure, where Back went to the top of the list ([NN/g infinite scrolling](https://www.nngroup.com/articles/infinite-scrolling-tips/), [NN/g alternatives to pagination](https://www.nngroup.com/articles/alternatives-pagination-listing-pages/)). NN/g's scroll position article praises Muji for keeping the place and Ravelry for returning to page 8, not page 1 ([NN/g saving scroll position](https://www.nngroup.com/articles/saving-scroll-position/)).

- Click: the card name opens `/people/{id}?search={sid}&shown={n}&card={key}`.
- The page's Back link goes to `/searches/{sid}?shown={n}#card-{key}`. The anchor scrolls the card into view, inside the list box or the page.
- Browser Back: the browser restores the page from its back/forward cache when it can, with scroll and script state kept ([web.dev bfcache](https://web.dev/articles/bfcache)). Otherwise it reloads, and `history.scrollRestoration` is `auto`, which restores the page scroll ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/History/scrollRestoration)).
- Trade-offs for FN: no new design-system part, no new JavaScript, works at 390 px. The map zoom is not kept by the Back link (not checked whether bfcache keeps it).

**A2. Side panel next to the list.** Notion opens a database item in a side peek on the right, and the list on the left stays "visible and interactive" ([Notion release notes, 2022-07-20](https://www.notion.com/releases/2022-07-20)). Linear previews the focused list item when you press Space, and J/K or the arrow keys move the focus ([Linear changelog, peek moved to Space](https://linear.app/changelog/2019-09-23-improved-peek); the current docs page returned 404 to this research, so the J/K detail comes from search summaries, not checked). Greenhouse's redesigned candidate profile has a right panel that opens and closes ([Greenhouse redesign](https://www.greenhouse.com/uk/blog/why-we-redesigned-the-candidate-profile-in-greenhouse)). NN/g recommends a nonmodal side panel to show one record while the table stays visible ([NN/g data tables](https://www.nngroup.com/articles/data-tables/)). It also warns that Back skips past an overlay unless the page makes Back close it ([NN/g overuse of overlays](https://www.nngroup.com/articles/overuse-of-overlays/)).

- Click: the card name opens the person in the map column. The script calls `history.pushState` with `?person={id}`, so Back closes the panel and the URL can be shared.
- Trade-offs for FN: the map is hidden while the panel is open. It needs a new PersonPanel part and more JavaScript. At 390 px it has to fall back to A1. Notion's mobile app opens most pages full screen, not as a side peek (third-party claim from [MakeUseOf](https://www.makeuseof.com/change-notion-side-peek-setting/), not checked).

**A3. Full page with Previous and Next.** Greenhouse lets the arrow keys move between candidates on a profile, but only when it was opened from the search results ([Greenhouse application review](https://support.greenhouse.io/hc/en-us/articles/4401963991707-Application-review-stage)). Ashby's candidate review uses the left and right arrow keys, and Esc leaves the review ([Ashby candidate reviews](https://docs.ashbyhq.com/candidate-reviews)).

- The person page shows "4 of 40 · Previous · Next" under the Back link. Each is a plain link to the neighbour's page with the same `search`, `shown` and `card` parameters.
- Trade-offs for FN: the server must know the order of the cards for that search, which the results page already computes. It works without JavaScript and at 390 px.

**Recommendation: A1 now, plus A3.** A1 fixes the lost place with a change to two links. A3 lets Paul review the list one person at a time without going back at all. Build A2 only if Paul reviews long lists on a wide screen and asks for it, because it costs a new part and a phone fallback.

## (b) A person page that reads at a glance

Pick by one dimension: how the first screen is organized. The options are a summary block over detail sections, all sections expanded with "see more" cuts, or tabs.

**B1. Summary list, then sections.** GOV.UK's summary list is a `<dl>` of key, value and an optional action such as "Change" ([GOV.UK summary list](https://design-system.service.gov.uk/components/summary-list/)). Attio opens a record with a highlights area of up to six attribute widgets above its tabs ([Attio record pages](https://attio.com/help/reference/managing-your-data/records/configure-record-pages)). Crunchbase opens a profile with About and Highlights sections and keeps deeper detail in tabs ([Crunchbase profile design](https://about.crunchbase.com/blog/new-crunchbase-profile-design)).

**B2. All sections expanded, each cut with "see more".** LinkedIn orders a profile as header, About, Featured, Activity, Experience, Education. Third-party guides put the About cut at 200 to 300 characters and disagree on the exact number ([Coursera guide](https://www.coursera.org/articles/linkedin-profile), not checked against LinkedIn).

**B3. Tabs.** Attio and Crunchbase put activity, news and detail behind tabs. Greenhouse moved away from heavy tabs because they made the hierarchy unclear ([Greenhouse redesign](https://www.greenhouse.com/uk/blog/why-we-redesigned-the-candidate-profile-in-greenhouse)).

Trade-offs for FN: B1 fits the existing Profile and Claim parts and the 390 px layout, since a `<dl>` stacks. B2 is what FN does now, and the quotes make it long. B3 hides facts Paul needs for every person and adds navigation to a page of 3 to 5 facts (the three measured pages had 3, 4 and 5 facts).

**Recommendation: B1.** NN/g says to show the few things users need first, keep the rest one step away, and stop at two levels ([NN/g progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/)). The summary is level one, the sections and the expanded proof are level two.

### Proposed section list and field order

1. Back link: "Back to results" (A1), then "4 of 40 · Previous · Next" (A3).
2. Head: name; headline as "Role, Organization"; place as "City, State"; Add and Skip, or the network state.
3. Why for this search: one reason line per wish, with a mark for met, partly met or unknown. Order: topic, tie to Flanders, place. This is where the better-or-worse tiers show.
4. At a glance, a summary list with these rows in this order:
   - Works at: current role and organization
   - Based in: city and state
   - Studied: the highest degree, school and years
   - Tie to Flanders: the strongest tie in one line
   - Contact: email and phone, or "Not found"
5. Work: current first, then past, three shown, ShowMore for the rest.
6. Education: degree, school, years, newest first.
7. Ties to Flanders and Belgium: every tie, strongest first.
8. Places: only when there is more than the place in the head.
9. Contact: the edit form, for network members only.
10. Sources: each record FN combined, with its fact count and "Not this person" (today's "Found as").
11. Possible matches: unchanged.

Every fact row uses one field order: what, organization, years, then the source name. A row with an unknown field leaves it out. It does not print "date unknown". An empty section is left out, except Contact, which says "Not found" so Paul knows FN looked.

## (c) A source for every fact, without walls of text

Pick by one dimension: where the proof opens. The options are in place under the fact, in a hover card with a list at the end, or in a separate sources panel.

**C1. Source name after the fact, proof expands in place.** Wikidata shows each statement with its references collapsed under an "n references" toggle. On mobile they were always expanded ([Phabricator T177970](https://phabricator.wikimedia.org/T177970), [T85364](https://phabricator.wikimedia.org/T85364)). GOV.UK's details component reveals extra text below a short summary link. It warns not to hide what most users need ([GOV.UK details](https://design-system.service.gov.uk/components/details/)).

- Click the source name: a `<details>` element opens under the fact. It shows the quote (at most 25 words, with the matching words marked), the page title, the date, a link to the original page, and a link to the stored record.
- Trade-offs for FN: no JavaScript, works by tap at 390 px. It needs a small extension to the Claim part.

**C2. Footnote numbers, hover preview, list at the end.** Wikipedia's Reference Previews open the footnote in a pop-up on hover. A click on the number still jumps to the reference list, and a long reference scrolls inside the pop-up ([MediaWiki Reference Previews](https://www.mediawiki.org/wiki/Help:Reference_Previews)). The older tooltip gadget notes that hover may not work on touch screens ([MediaWiki Reference Tooltips](https://www.mediawiki.org/wiki/Reference_Tooltips)). Perplexity puts numbered markers on claims and shows title, domain, date and an excerpt on hover, per third-party guides ([Perplexity teardown](https://ai-design-patterns.pages.dev/gallery/perplexity-citations), not checked in the product).

- Trade-offs for FN: hover needs JavaScript and fails on a phone. A number tells Paul nothing until he opens it.

**C3. Source chips with a count and a sources panel.** Perplexity shows domain chips with "+N", a source sidebar and a Links tab. Copilot shows chips and a "See all" button ([NN/g explainable AI](https://www.nngroup.com/articles/explainable-ai/)).

- Trade-offs for FN: a panel competes with the map for the same column, and it needs a new part.

NN/g's guidance holds for all three options. Put the source next to the claim it supports. Label it with the publication name, not "Source". Link to the part of the page that supports the claim ([NN/g explainable AI](https://www.nngroup.com/articles/explainable-ai/)).

**Recommendation: C1.** Fix the source page too. It should open with a Back link to the person, then one sentence ("This OpenAlex record lists the National Institute for Health and Care Research, 2016 to 2021"), then the original link. The raw record goes behind a "Show the stored record" disclosure.

### Three ways to word a fact with its source

1. Trailing name: "Studied at Ghent University, 2010 to 2014 · Wikidata". The source name is a small link that expands the proof (C1).
2. Footnote number: "Studied at Ghent University, 2010 to 2014 [1]", with "1. Wikidata, retrieved 2026-11-12" at the end of the section (C2).
3. Chip with a count: "Studied at Ghent University, 2010 to 2014 [Wikidata +1]", where "+1" means a second source agrees (C3).

Use wording 1. Add "+1" from wording 3 only when two sources agree, because agreement is useful for linking records of one person.

## (d) Cards with one short reason

Pick by one dimension: what the card shows as evidence. The options are a written reason, a line of met wishes, or a shortened quote.

**D1. One reason line with its source.** NN/g found that users struggle to tell which claims a source supports. It advises putting the source next to the claim ([NN/g AI search](https://www.nngroup.com/articles/ai-search-infoseeking/), [NN/g explainable AI](https://www.nngroup.com/articles/explainable-ai/)). Example: "Moderated a Harvard panel on AI in health care · Harvard Chan School". At most 15 words, written from stored facts, with no new claims.

**D2. A line of met and unmet wishes.** This extends today's "Matches: ai, health, care" line to the three wishes: "Topic ✓ · Flanders tie ✓ · Boston ✗". It shows the tier at a glance. A partial match reads as a fair result, not a miss.

**D3. The quote cut to the matching phrase.** It keeps the source's own words but still shows page debris, such as the "Author Orcid Image" quote measured above.

**Recommendation: D1 plus D2.** The quote moves to the person page behind C1. D1 needs a sentence per card. Write it from facts FN already stores, so it costs no extra model call per card.

## Text budget

| Place | Today (measured) | Proposed default | Measured from |
|---|---|---|---|
| Card | 41.5 words median | at most 25 words: name, headline, place, D2 line, D1 line | LinkedIn About cut of 200 to 300 characters, about 35 to 50 words (third-party, conflicting); Attio's 6 highlight widgets |
| Person page, first screen | not measured separately | at most 90 words: head, why, summary list of 5 rows | Attio up to 6 highlights; GOV.UK summary list; NN/g two levels |
| Person page, whole default | 172 to 300 words | at most 180 words, no quotes open | Wikidata references collapsed by default |
| One fact row | quote of 8 to 59 words under it | at most 12 words plus source name | proposed wording 1 |
| Opened proof | whole stored record | quote of at most 25 words, then links | Wikipedia preview pop-up holds one reference |

The 25, 90 and 180 word figures are a judgement from these products, not a measured optimum. Test them by counting words on 20 cards and 5 person pages after the change.

## Design-system changes this needs

- Claim: add the trailing source name and the `<details>` proof (C1). Remove the quote shown by default.
- Profile: add the summary list, the "why" block and Previous and Next.
- PersonCard: replace the quote with the D1 and D2 lines.
- ResultsLayout: none for A1 and A3. A2 would need a new PersonPanel part.
- Source page: a Back link, one plain sentence, and the raw record behind a disclosure.

## Not checked

- Whether Chrome and Safari keep the results page with the live map in the back/forward cache.
- Whether Back restores the list box's own scroll after a full reload.
- Linear, Perplexity, LinkedIn, Apollo and Clay behaviour seen in the products themselves. This note relies on their documentation or third-party guides, as marked.
- Exact LinkedIn cut lengths. Sources disagree.
