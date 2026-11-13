# How does FN return people an organizer can invite, on pages he can read?

**TL;DR.** The first quality round made lists shorter and on topic, and they still read 69% academic. Of 99 real picks, 39 are business people, and none reaches a first 20 on merit. This round changes what a search asks for and how it orders people. The parse step learns the kind of person, the tie wish and which wishes are a must. The local search covers every person FN already holds and uses related words. People are ordered in tiers shown under headings, so a topic expert without a tie still appears, below the people with one. The person page, the source page and the way back are rebuilt from two browser walkthroughs. A benchmark of 14 organizer questions, scored by three judges, says whether each step helped.

## What is wrong today, in numbers

Each number comes from a note in [research/](research/).

| Problem | Number | Note |
| --- | --- | --- |
| Business picks in a first 20 on merit | 0 of 39 | gold-reality |
| First-20 cards that read academic | 69% | gold-reality |
| First-20 cards found only by OpenAlex | 44%, with no gold pick among them | gold-reality |
| Picks never returned that FN already holds | 19 of 79 | held-not-returned |
| Of those, records without any word of the question | 9 | held-not-returned |
| Records the local search can reach | 5,429 of 27,400 | held-not-returned |
| Stored people with the topic and the place and no tie | 1 | tiers |
| Searches with an empty strict top tier | 17 of 27 | tiers |
| Cards that say "Combined" and open a page that shows one record | 54 of 54 | ux-walk-walk-new |
| Words on a card, median | 41.5 | ux-patterns |
| Share of a person page's words that are quotes | 60% to 79% | ux-patterns |

## Decisions

Three panels of three judges each decided: result quality after three rounds, the pages after two, web search and sources after one. All 22 decisions ended unanimous. The votes, reasons and amendments are in [panel-records.md](panel-records.md). The lead's rulings fill what the panels left open and are marked.

### Who comes back and in what order

- **R1. The local search covers seed rows, web mentions from earlier searches and stored profiles from the LinkedIn lane.** OpenAlex and ORCID records join only when the question asks for research expertise. It uses the existing text index.
- **R2. The parse call returns related words per topic and role chip**: synonyms, sector words, job titles, Dutch and French forms. At most 6 per chip after the generic-word filter. They are searched in a second pass whose hits rank below the hits of the question's own words. The word lists are tuned on the ten development questions only.
- **R3. The parse call returns role chips for the kind of person** ("founders", "business leaders"), each marked research or not. A met role orders people inside a tier. A person who clearly fails the role moves to the lowest tier. "Clearly fails" holds only when every role chip is a non-research one, and means an academic research job, or no role at all with only bibliographic sources. A person without a role and with any other source is never moved down.
- **R4. People are ordered topic first and shown under up to three headings**: "Topic and a tie to Flanders", "Topic, no known tie", "Tie, topic not confirmed". When the question makes the tie a must, people without a tie are not shown. At most 20 people per search come back from the old cut of OpenAlex-only people without Belgian years, until a benchmark run shows they help.
- **R5. A tie has a grade.** Strong: a row on a seed list that is Belgian by construction, a degree from a Belgian institution, born in Belgium, a stated Belgian origin, or three or more years at Belgian organizations with one since 2016. Medium: a shorter or older Belgian organization, a stated place in Belgium, and a Wikidata row whose only tie is an employer in Belgium. Weak: Belgian words in a claim only. A weak tie counts as no tie under the headings. A match on the question's institution is no longer a tie.
- **R6. A second web search without Belgium in it** runs only when the tie is not a must and fewer than 20 people stand under the first heading after the other lanes. Its seconds and calls are logged.
- **R7. The OpenAlex lane is skipped when every role chip is a non-research one.** Otherwise it runs, and people only OpenAlex found fill at most 5 of the first 20, unless the question asks for researchers. A question that mixes research and other roles counts as asking for researchers.
- **R8. A topic word inside an organization's name counts as a found word and never as a full topic match.**
- **R9. An offline batch looks thin people up on the web**, anchored on a school or an employer FN already knows. It stores a fact only with a quoted passage that names the anchor next to the person, under its own source kind. Twenty records are checked by hand for namesakes before the full batch runs.

Lead's rulings:

- **Legacy chips.** A search parsed before this round has no tie chip and no role chips. Its chips carry version 1. For version 1 nobody is cut for lacking a tie, research counts as asked, and the lane without a tie does not run, so a stored search keeps its people and replays without new calls. The parse step writes version 2.
- **A stated origin is a claim.** The page reader gains a relation for the country or region a text says a person is from ("Belgian chocolatier"). Without it, exactly the people a must-tie question asks for would count as having no tie.
- **Topics a text gives a person are claims.** The page reader also returns the subjects the text says a person works on. They are the topic evidence for web people, in place of words found anywhere on the page.
- **A fourth heading, "Other people found"**, holds people with neither a full topic match nor a tie, and the people moved down for clearly failing the role. When the tie is a must, people without a tie are cut, so the heading then holds only the people moved down.
- **The lane that searches without a tie is its own lane, `web_topic`.** The search runs it after the first web lane and tells it how many people stand under the first heading.

Rulings on what the planners found against the code:

- **Seven tiers.** 1: full topic match, a tie, place fits. 2: full topic match, a tie, any other place, with people abroad last. 3: full topic match, no tie, place fits. 4: full topic match, no tie, elsewhere. 5: a tie and some topic word. 6: a tie and no topic word, or some topic word and no tie. 7: neither, and the people moved down for the role. An unknown place fits, as decided last round.
- **The ranker stores what the card needs.** Each candidate gets its tier and a fit: the tie's grade, the claims that show the tie with the strongest first, the place fit (inside, outside, abroad, unknown) and the role fit. A page makes no outside call, so it cannot work these out itself.
- **Which lists give a strong tie.** Strong: the BAEF, Francqui and Fayat fellowships, the consul list and the climate list. Medium: the academy list, chamber boards, mission programs, the embassy's advisors, nonprofit officers, and a Wikidata row without a degree, a birthplace or an origin in Belgium.
- **A related word counts as topic evidence.** A claim that holds a related word of a chip is a full match for that chip, marked as found through a related word, and it orders below a match on the question's own words inside a tier. The benchmark decides whether this stays.
- **The cap on OpenAlex-only people** moves the extra ones to the end of their own heading. It never moves a person under another heading, so it can stay unmet when a heading ends inside the first 20.
- **A past job no longer names the current employer** on a card, a row or a person page.
- **"Studied" in the summary is the newest study claim**, because no claim stores a degree level.
- **The map opens on the shown people whose place is inside the asked area** when there is at least one, else on all shown people.
- **The walk line counts the whole list** ("4 of 143").
- **The text budget as a test:** a median of at most 25 words a card and no card over 30; at most 90 words on a person page's first screen.
- **Migration 012** belongs to the tiers task.
- **Stored searches gain nobody either.** For version-1 chips the ranker lets nobody back in from the old cut, so a rerank of a stored search neither cuts nor adds people for lacking or having a tie.
- **Order inside a tier:** people who meet the role first, then a match on the question's own words before a match on a related word, then the tie's grade, the place fit, the number of topic words and the score.
- **Tier 6 holds two kinds of people**, so the heading follows the tie: with a tie under "Tie, topic not confirmed", without one under "Other people found".
- **A stated origin reads "Origin: Belgian"**, in the text's own word.
- **Version-1 chips keep today's web queries**, so a stored search sends the same requests and replays from the cache. Only version 2 gets the written and checked queries.
- **Locally read pages use the source kind `page`**, which exists and is unused. Pages read by the lookup batch use a new kind, `lookup_page`.
- **The lookup batch** runs at most 50 lookups a day, and a record counts as thin with at most 4 claims.
- **Page fetches send a plain client name**, "FN/0.1", on a page and on its robots.txt. The header FN sends to the services it knows holds the repository's address, and a site a search happens to find has no need for it.
- **A heading's count covers the whole list so far**, also while a search runs.
- **The nonprofit officers come last among the lists**, because their filings sit in large bulk files. The two one-page lists come first.

### How FN searches the web and grows its lists

- **W1. One function finds pages for a query, with switchable backends behind one setting.** The panel chose Parallel, DuckDuckGo's HTML endpoint, SearXNG and the Claude web search, with Parallel as the default while its key is set. The SearXNG adapter is off until the owner gives its address and picks its engines, because its best engine reads a page Google's robots.txt disallows. The Claude web search runs when the chosen backend raises or is blocked. The ruling below this list drops the DuckDuckGo adapter.
- **W2. The parse call writes up to 5 web queries**, in English and in Dutch, with the role and the place. They are checked: at most 5, at least one in Dutch, the country word kept. A rule fills what is missing or malformed. The lane without a tie drops the country word by rule. A query limited to Belgian press and university sites goes only to a backend that honours it. The final list is recorded in the step.
- **W3. FN fetches a found page itself and reads it with the standard-library parser**, preferring the main or article element, after a check of the host's robots.txt. A PDF goes through `pdftotext` when it is installed. A read fails on a status other than 2xx, on under 300 characters of text, or on a PDF without `pdftotext`. Parallel Extract reads only failed pages, and only when a key is set. Locally read pages get their own source kind.
- **W4. Three seed lists are added**: the BelCham board, the embassy's advisors on economic diplomacy (name, role, employer, state and page date only, no phone numbers or email addresses), and the officers of about 12 Belgian-American nonprofits from the IRS bulk filings, each with its fiscal year.

Ruling after a live check on 2026-11-12, which overrides part of W1 and the rulings on DuckDuckGo above: **the DuckDuckGo adapter is not built in this round.** The research got 8 answers from its HTML endpoint in the evening. Two hours later the same machine, with an honest client name, got the bot-check page on its first request, by GET and by form post. A route that stops after about 10 queries from one address cannot carry a lane that sends 5 queries a search, and FN does not disguise its client to pass a bot check. So the setting has three backends: Parallel, the Claude web search and SearXNG. Without a Parallel key the default is the Claude web search. The lane without a tie and the lookup batch use the Claude web search by default, so the paid calls per search stay as they are. The benchmark compares that lane on the Claude web search with the same lane on Parallel, and the owner chooses with those numbers. No daily counter and no spacing are needed, so migration 013 is not used.

Ruling of 13 November, after the first after-measurement: **W5. A web researcher finds people, as a lane named scout.** Four model calls with the web search and page fetch tools run side by side, each on its own search angle (the press, lists of people with the tie, biography phrases, the job in the place; other angles when no tie is asked). Each returns people with the pages that state their facts. FN fetches those pages itself (W3's reader, built now as `pageread.py`) and the page reader makes the claims, so no fact rests on the model's own words. The lane never reads or reports linkedin.com. It runs on the owner's Claude subscription with the product's model. The page reader also takes a person's base or office city, and the lane adds the city the researcher reports when the page prints it within 1,000 characters of the person's name. W1's switchable backends and the web lane's use of the local reader wait: the scout lane already finds people without Parallel.

### How the pages read

- **U1. A person opens as a full page.** Its back link and the browser's Back return to the same card with the same number of cards shown. Previous and Next walk the list ("4 of 40") when the page was opened from a search. Every link carries the search, the shown count and the card. The results script saves the list panel's scroll position when the page hides and restores it when the page shows, and falls back to the card's anchor.
- **U2. Every page opened from another page has one back link at the top that names where it returns.** That holds for a source page, a possible-match page, a person opened from the map or from the Network list, and after Remove, Undo and Same person. With no known origin there is no back link. The header marks Search when the address carries a search.
- **U3. The person page is the head, a "why for this search" block, a summary, then sections.** The why block shows only with a search and is built from the same data as the card's lines. The summary is a new SummaryList part with the rows the head does not show: Studied, Tie to Flanders, Contact. An empty row is left out, except Contact, which says "Not found". Sections are Work, Education, Ties to Flanders and Belgium, Places, Contact, Sources and Possible matches. Each shows three facts, then Show more. A section whose only facts already stand in the summary is left out (two judges for, one against).
- **U4. With a search in the address, the person page shows the same combined facts as the card.** It says "Combined from N records" and lists the records under Sources with "Not this person" on each. Records FN only suspects stay under Possible matches. Without a search the page shows the person as today.
- **U5. A fact is one line: what, organization, years, then the source's name as a small link.** The link opens the proof in place: a quote of at most 25 words cut around the matched words, the page title and date, and a link to the original page. A quote that is page debris is left out and the title and link remain. "Not correct" stays on the fact's line, outside the proof.
- **U6. A source link opens a readable source page**: a back link, a heading that names the person, one sentence built from the stored fact, the passage in context, a link to the original, and the stored copy behind "Show the stored record".
- **U7. A card shows one reason line built from a stored fact, at most 15 words, with its source's name, and no quote.** A card without such a fact shows its headline only. Lead's ruling on the second line, where two amendments disagreed: the headings already say topic and tie, so the card's second line says what the heading does not: the tie in words ("Studied at Ghent University") and the place fit ("in New York", "elsewhere in the US", "place unknown").
- **U8. "Remove from network" for a person and "Not correct" for a fact.** After a fact is removed, its "Removed · Undo" line stays where the fact was and the page returns to that line.
- **U9. The map opens on the area of the shown people**, with a zoom limit so one person does not open at street level. Count markers that overlap use the map library's own clustering. Markers are buttons with a label such as "4 people near Boston", open with Enter or Space and close with Esc.

### Rulings after the second walkthrough

Three agents walked the rebuilt pages ([research/ux2-walk-new.md](research/ux2-walk-new.md), [research/ux2-walk-check.md](research/ux2-walk-check.md), [research/ux2-design-review.md](research/ux2-design-review.md)). The way back, the layout and the source page hold. What the person page says does not yet. The lead's rulings, each a rule of the design system first and of the site second:

- **V1. Work opens with the current job.** The first line is the employer whose years reach the last two years and span the longest time, with the role a source states for it. Then stated roles from pages and lists, then Belgian organizations, then the rest by span. Affiliations that a record lists for one year only fold into one last line, "Also named at n other organizations", behind Show more. The head's line is the first Work line. Today one-year affiliations from co-authored papers sort first, so a professor at one university since 2009 opens as a professor at another.
- **V2. A year on a line is the fact's own year.** Years come from the years a source states for the fact. The day a record was changed or read is never shown as a fact's year, though it still tells the ranker the fact was current then. A fact with several years shows one span, first to last; the full list stands in the proof.
- **V3. A page's title is not a job.** When a page names a person without a role, FN stored the page's title as the role. Such a line is no fact: it is not shown under Work, never names the head, and the page stands under Sources.
- **V4. Each fact is worded with the design system's relation words**, and the list is completed there first: Works at, Worked at, Studied at, Fellow of, Member of, Honorary consul for, Hosted by, Named at (for a record's affiliation), Lives in, Born in, Origin, Topic. A stated role joins its organization when one source gives both ("Head of gynecology, UZ Leuven"). A list entry reads as its relation ("Fellow of the Belgian American Educational Foundation, 2015"), never as the list's title.
- **V5. "Ties to Flanders and Belgium" holds ties only**: a birthplace, an origin, a fellowship, a membership, a consul's post. A job is under Work, a degree under Education, a topic under Work as "Topic".
- **V6. The summary's tie row shows the strongest tie.** With a search it is the tie the ranker stored; without one, the tie evidence picks. The row reads "Tie to Flanders" when the tie's organization or place lies in Flanders and "Tie to Belgium" otherwise. When that tie is the degree, the Studied row is left out, so the summary never says one fact twice.
- **V7. A quote is hidden only when it is page furniture**: a field label after a list mark ("* Name:"), image or author-list tokens, markup entities, or fewer than four words. A sentence that says "she" stays. Today the filter hides about half of all web quotes.
- **V8. Sources has one row per record**, as many rows as the head's "Combined from n records" says, each named by where it came from (a page by its host, a list by its name, "OpenAlex record"), with "Not this person" on every record but the page's own.
- **V9. A stored LinkedIn profile is a record, not a page.** Its proof shows no passage of scraper lines.
- **V10. The source page names its source** under the sentence: the page's or list's name and its date.
- **V11. Actions land where they were made.** Same person, Different person and the back link from a possible match return to the Possible matches section.
- **V12. The first-screen budget of 90 words counts the head, the why block and the summary**, not the first facts and not the "Not correct" links.

### Rulings on the person page plan (13 November)

- **V13. A tie reads "Tie to Flanders" only when the organization is in the Flemish Region.** Brussels and federal bodies, the two fellowship foundations among them, read "Tie to Belgium".
- **V14. A job a source states with "works at" is current whatever its year.** An affiliation counts as current only when its years reach the last two.
- **V15. The head names a job only:** the current job or a stated role. A topic, a paper, a past job or a list entry never names the head.
- **V16. One-year affiliations at a Belgian organization never fold** into the "Also named at" line.
- **V17. A place a record gives for an institution is no fact on the page.** The head still uses it.
- **V18. A page with no fact line shows its one Sources row** with "· no facts".
- **V19. A field label is page debris only after a list mark.**
- **V20. "Not correct" on a joined role line hides the role and the employer together**, and Undo restores both. Hiding one would leave half a line standing.
- **V21. The Flemish Region check reads the organization's region first, then Flemish words in its city or name.** A city-to-region table is a follow-up: 22 of 542 Belgian organizations carry a region today.

### Rulings after the third walkthrough (13 November)

- **V22. The card's reason line is what the person does today on the question's subject**: a stated role or a topic a page gives, else a topic fact such as a paper, else no line. Never a past job, a host institution, a record's affiliation, a study, a fellowship or a page's title, and never a repeat of the role line.
- **V23. The first results heading reads "Topic and a tie to Flanders or Belgium."** A tie in Brussels or Wallonia stands under it too. Under "Topic, no known tie" a card does not repeat that there is no tie.
- **V24. One place per card.** The role line names the place. The second line and the why block say "place unknown" when it shows none, and never a place fit in other words beside it.
- **V25. The why block says each fact once.**
- **V26. A stated role joins only a current job of the same source**, never a past one, and a role that already names its organization is not followed by it again.
- **V27. "Consul for Belgium"**, not "Honorary consul for": a career consul is not honorary, and a list of honorary consuls says so in the person's own role line.
- **V28. The place the ranker reads is the place the card shows.** A person whose card says Leuven does not count as in the US because of a fellowship host there years ago.

### What the first after-measurement showed (13 November)

- **The people are missing, not misordered.** After the evidence and tier changes the judges found 1 invitable card in the first ten of the ten development questions, the same as before. One judge then labelled every complete card (a role and an employer) of all 14 questions: 1,162 cards, 2 invitable. No order of this pool scores above 2.
- **Why.** 84 of the 1,162 cards are on topic. Of those, 59 lack a current role, employer or fresh date, and 71 lack a place in the asked area. The stored people are fellows and researchers; the questions ask for people in a job, in a US place, today.
- **Consequence.** The next gain comes from finding people on the open web the way an organizer would, with their role, employer, place and a dated source. Order changes wait until the pool holds such people.

## Who owns what

One owner per row. A module calls another's entry point, never its internals. Rows that change in this round are marked.

| Responsibility | Owner |
| --- | --- |
| The wishes of a question: topics, roles, tie, place, each as a must or nice to have, and related words (changed) | `parse.py` with `prompts/parse.md` |
| Whether a question asks for research expertise (new) | `parse.wants_research` |
| The local search over the people FN holds: which records, which words, the cap (changed) | `lanes/seeds.py` |
| Finding pages for a web query: backends, spacing, daily caps, the fallback (new) | `websearch.py`; the web lanes and the lookup batch call `websearch.find` |
| Fetching and reading a found page, robots.txt (new) | `pageread.py`; the scout lane hands it the links |
| The web queries of a question (new) | `parse.py` writes them, `websearch.queries` checks and fills them |
| People with a tie on web pages | `lanes/web.py` |
| People with the topic and no tie asked (new) | `lanes/web_topic.py` |
| Asking a web researcher for people: the angles, the call, cleaning and merging its leads, which addresses FN may fetch (new) | `scout.py` with `prompts/scout.md` |
| People a web researcher found: the page budget, which people of a page are kept (new) | `lanes/scout.py` |
| What a page says about a person: role, relations, origin, topics (changed) | `extract.py` with `prompts/extract.md` |
| Researchers | `lanes/openalex.py`; skipped by `search.py` when no research is asked |
| Which steps run, in which order, and what each lane is told (changed) | `search.py` |
| What a card shows for a question: topic, tie with its grade, role fit, place (changed) | `evidence.py` |
| Tiers, the order inside a tier, cuts and caps (changed) | `rank.py` |
| Who is one person | `identity.py` |
| Looking up what thin records miss (changed: a web lookup kind) | `enrich.py` |
| Seed lists | `scripts/seeds/`, `seedload.py` |
| How a person, a fact, a reason line and a source read; which facts a page shows (changed) | `present.py` |
| Markup of each part | `web/parts.py` |
| Routes, the origin a page was opened from, redirects that keep it (changed) | `web/staff.py` |
| Scroll position of the list, the map's start and markers (changed) | `web/static/results.js`, `map.js` |
| Every part, state and string | the design system, then its copy in the site |
| Scoring results | `score.py` for gold metrics; the judge run for the benchmark |

## Contracts that change

- `Chip` gains `need` (`must` or `nice`, default `must`) and `related` (a list of words). A role chip also has `research` (true or false).
- `Chips` gains `roles`, `tie` (one chip or none) and `version` (1 for chips stored before this round, 2 from the new parse step). `Place` gains `need`.
- `Relation` gains `origin`. The page reader's answer gains `topics` per person.
- `Tie` gains `grade`. Its kinds gain `belgian_degree`, `born_in_belgium` and `belgian_origin`, and lose `institution`.
- `Evidence` gains `role` with a fit of `met`, `fails` or `unknown`.
- `Candidate` gains `tier` (1 to 7) and `fit` (tie grade, tie claims, place fit, role fit), stored in new columns. `CutReason` gains `no_tie`.
- `LaneName` gains `web_topic`. `LaneIn` gains the count of people under the first heading so far.
- View models: the person page's summary rows, why lines, sources with their records, and the back link with its label; a card's reason line and second line; a results heading with its count.

## How we measure

- **The benchmark.** 14 questions in the organizer's voice that do not ask for researchers, ten for development and four held out ([research/benchmark.md](research/benchmark.md)). Each runs as a real search on a separate copy of the database. Three judges score the first 20 cards on topic, tie, place and "could he invite this person on what the card shows". Names are masked. The number to climb is the count of invitable people in the first 10, summed over the development questions. The baseline is judged twice to know the noise, and a change counts only when its gain is more than twice that noise.
- **Guards.** The held-out questions, gold picks in the first 20, pairs of one person in a first 20 and labelled-different pairs on one card must not get worse.
- **The gold questions run again with the new parse step**, because stored chips have no roles, tie or related words. Cached pages and model answers are reused, and only new requests cost a call.
- **The pages.** Two browser walkthroughs repeat the flows of the first two after the build. The pages pass when neither reports a blocker or a should. Word counts are measured on 20 cards and 5 person pages against the text budget: 25 words a card, 90 words on a person page's first screen.

## Not doing

- Reading LinkedIn, or search-engine snippets of LinkedIn pages.
- SEC filings as a source. The SEC asks for a contact email in every request, which is the owner's decision.
- A side panel for a person next to the list. The full page with Previous and Next comes first.
- A local embedding index. It needs a new dependency.
- Tags written per stored person by a model batch. Related words at parse time come first.
- A lookup of thin people during a search. The offline batch comes first.
- Belgian company deeds and the Flemish research portal as sources: they hold people in Flanders, and the benchmark asks for people in the US.

## Risks

- A neutral web search brings people without any tie. They stand under their own heading, and never show when the tie is a must.
- Related words widen the local search. Their hits rank below the question's own words and the cap of 300 stays.
- Model judges may not agree with the owner. Ten cards judged invitable are checked against public sources each round, and the owner can spot-check twenty.
- New prompts for parse and for page reading make every recorded model answer miss once. One paid re-read of the stored pages follows, and after it runs replay again.
- The web lookup batch can attach a namesake's facts. The anchor rule and the hand check of twenty records hold that.
