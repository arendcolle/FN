# Panel records of the second quality round

Three panels of three judges decided the open design questions. Each judge voted alone in round one, then read the others' reasons and voted again, for at most three rounds. A decision needs two votes; all 22 ended unanimous. The lead's later rulings, including the one that drops the DuckDuckGo route panel 2 chose, are in [design.md](design.md).

## Panel 1: who comes back and in what order

Judges: the organizer's advocate, the staff engineer and the evidence skeptic. Brief: [panels/p1-retrieval-and-tiers.md](panels/p1-retrieval-and-tiers.md). Rounds: 3. Unanimous after each round: 7, 7, 9 of 9.

### R1: option c, unanimous

- **organizer** (c): I keep c. The only measured gain is the 3 web-mention picks (GS-32#1, 32#3, 32#4) that seeds.py:23 EXCLUDED shuts out. The first 20 is already 44% OpenAlex-only with no gold pick among them (gold-reality.md:9), so adding 20,448 OpenAlex and ORCID records to every question would hand Paul more people he cannot use.
- **engineer** (c): I keep c. The only measured gain is the 3 web-mention picks (GS-32#1, 32#3, 32#4) that seeds.py:23 EXCLUDED shuts out. Adding the 20,448 OpenAlex and ORCID records to every question would feed a first 20 that already reads 69% academic (gold-reality.md). The gate reuses the R3 role chip, so no new index or document is needed.
- **skeptic** (c): I keep c. The only measured gain is the 3 web-mention picks (GS-32#1, 32#3, 32#4) that seeds.py:23 EXCLUDED shuts out. Adding the 20,448 OpenAlex and ORCID records to every question would repeat the 44% OpenAlex-only first-20 share that holds no gold pick (gold-reality.md).

Amendments proposed:

- skeptic, round 1: Do not take the rule for when a question asks for research expertise from the gold questions. Use the R3 role chip, so the same signal gates R1 and R7.
- organizer, round 1: For business, media or culture questions, an OpenAlex or ORCID record may still supply a place for a seed or mention person whose name already matched, but it never adds a new person to the local hits.
- engineer, round 1: Build no new per-person document. Take vendor_page out of EXCLUDED in seeds.py for every question, and take record out only when the parse role chips (R3) ask for researchers. That signal is the same one R7 uses, and parse owns it.
- skeptic, round 3: Use the existing index with no new per-person document, and gate OpenAlex and ORCID records on the same parse role chip as R3 and R7.

### R2: option b, unanimous

- **organizer** (b): I keep b. 9 of 19 held picks fail on vocabulary alone, and hand-picked words bring 11 or 12 into the first 300 (held-not-returned.md). b reuses the parse call and ranks expansions below the question's own words. I accept the skeptic's point that named list entries like Fayat come from the gold questions, so I drop that part and keep the per-chip cap after GENERIC_WORDS and tuning on dev questions only.
- **engineer** (b): I keep b. Hand-picked words put 11 or 12 of the 19 held picks in the first 300 (held-not-returned.md), and b reuses the parse call FN already makes. The recorded chips replay offline through seeds.fts_query. I agree with the skeptic that the tuning must use dev questions only and be judged against the 11 upper bound on held-out I10.
- **skeptic** (b): I keep b. Hand-picked words put 11 of 19 held picks in the first 300 (held-not-returned.md), but those words were chosen after reading the records, so 11 is an upper bound. Recorded parse calls make b replayable through seeds.fts_query. I still leave out list names such as Fayat, because they come from the gold questions and would fit the expansion to the benchmark.

Amendments proposed:

- skeptic, round 1: Tune the expansion prompt on the benchmark dev questions only. Report how many of the 19 held picks it reaches with automatic words against the 11 upper bound, and gate the change on held-out I10.
- organizer, round 1: The related words also include list and programme names the question implies (Fayat, chamber, mission, alumni). The query keeps a lane-wide cap on expansion terms so that a generic word like 'university' cannot flood it, as it did for GS-29#2 (rank 382).
- engineer, round 1: Cap related words at about 8 per chip and run them through parse.content_words and GENERIC_WORDS, because GS-29#2 fell to rank 382 when 'university' flooded the query. Add parse fixtures for an empty chip, a duplicate chip and a role-only chip.
- skeptic, round 3: Cap related words per chip after the GENERIC_WORDS filter, tune only on dev questions, and judge the result on held-out I10 against the 11-of-19 upper bound.

### R3: option c, unanimous

- **organizer** (c): I keep c with both amendments. The skeptic's 5-of-8 figure is the accuracy for business cards, but the demotion only fires on an academic reading, which the spot check got right 8 of 8 (gold-reality.md:105). A thin business record is never demoted under the R3/organizer rule. Under b, 'business leaders' left 1,000 of 1,002 people in the lowest tier (tiers.md:41), so professors with the topic still sit above every founder on Paul's first screen.
- **engineer** (c): I keep c. With 'business leaders', 1,000 of 1,002 people sat in the lowest tier (tiers.md), so under b a professor with the topic still outranks every founder. The two amendments answer the skeptic's 5-of-8 concern. Demotion fires only on an academic research role or a bibliographic-only record, and only when every role chip is non-research, so the 35% with no role claim and thin business records stay where they are. fn-score rerank replays this on stored searches before it ships.
- **skeptic** (c): I move from b to c. My objection rested on the business read (5 of 8), but the organizer's amendment demotes only on an academic research role or bibliographic-only sources, and academic was read right 8 of 8 (gold-reality.md:105). With 1,000 of 1,002 people in the lowest tier for 'business leaders' under b (tiers.md:41), b leaves the owner's complaint as it is, and fn-score rerank can replay c on stored searches.

Amendments proposed:

- organizer, round 1: 'Clearly fails' uses the benchmark.md researcher definition: an academic research role, or no role and only bibliographic sources. A person with no role claim and a non-bibliographic source is never demoted, and a met role still orders people inside a tier as in b.
- engineer, round 2: Demote only when every role chip from parse is non-research, so a mixed question never demotes researchers.
- skeptic, round 3: Use the benchmark.md:113 researcher definition for 'clearly fails', never demote a person with no role claim and a non-bibliographic source, and demote only when every role chip is non-research.
- organizer, round 3: 'Clearly fails' means an academic research role, or no role and only bibliographic sources. It applies only when every role chip is non-research. A met role still orders people inside a tier as in b.

### R4: option b, unanimous

- **organizer** (b): I keep b. Topic-first leaves the top tier empty in 7 of 27 searches against 17 for tie-first (tiers.md), and headings show Paul where the tie ends. Hiding the no-tie heading when the tie is a must keeps people he cannot use off the page. The cap of 20 on the no_belgian_evidence exemption holds until a benchmark run shows those 135 unscored people help.
- **engineer** (b): I keep b. Topic-first leaves the top tier empty in 7 of 27 searches against 17 for tie-first (tiers.md section 2), and the headings cost 0.5 to 1 day in present.py. The cap of 20 on the people the no_belgian_evidence cut lets back in (tiers.md:177) holds until a scorecard shows they help.
- **skeptic** (b): I keep b. Topic-first leaves the top tier empty in 7 of 27 searches against 17 for tie-first, and the median list stays at 149 with no gold pick lost (tiers.md). The no_belgian_evidence exemption brings back 135 people never scored (tiers.md:82).

Amendments proposed:

- skeptic, round 1: Cap the people the no_belgian_evidence exemption lets back in at 20 per search until a benchmark run shows they help, as tiers.md's risks section proposes.
- skeptic, round 3: Cap the no_belgian_evidence exemption at 20 people per search until a benchmark run shows they help.
- engineer, round 3: Cap people the no_belgian_evidence cut lets back in at 20 per search until a benchmark run shows they help.
- organizer, round 3: Cap people admitted through the no_belgian_evidence exemption at 20 per search until a benchmark run shows they add gold picks.

### R5: option d, unanimous

- **organizer** (d): I keep d. Belgian text alone is the only tie for 309 kept people and lifts 81 into tier 2, often from a city word in a paper title (tiers.md), so it cannot sit under a heading Paul trusts as a tie. The Wikidata employer-country branch ties 785 of 1,737 people, including a US airline CEO (people-sources.md:38), so it counts as medium, not strong.
- **engineer** (d): I keep d. Dropping institution as a tie costs nothing, because 0 kept people have it as their only kind. Belgian text alone lifts 81 people into tier 2 (tiers.md), so the 'Topic and a tie' heading would claim a tie FN cannot show. The Wikidata employer-country branch gives the only tie for 785 of 1,737 rows and includes false ties (people-sources.md:38), so it counts as medium.
- **skeptic** (d): I keep d. Belgian text alone is the only tie for 309 kept people and lifts 81 into tier 2, and the rubric scores that tie as 1 (tiers.md). 785 of 1,737 Wikidata people are tied only through a Belgian employer country, which made a US airline CEO look tied (people-sources.md:38).

Amendments proposed:

- skeptic, round 1: Keep a seed list as strong, but do not count the Wikidata branch where the only tie is a Belgian employer country (785 of 1,737 in people-sources.md) as strong.
- organizer, round 1: A Wikidata seed row whose only tie is an employer with Belgium as its country counts as medium, not strong, because people-sources.md found that branch gives false ties (a US airline CEO).
- engineer, round 1: When the tie is a must, show weak-tie people at the bottom of the 'Tie, topic not confirmed' group, so a misparsed must hides nobody.
- skeptic, round 3: Count the Wikidata employer-country branch as medium, never strong.
- engineer, round 3: The Wikidata employer-country branch counts as a medium tie, never strong.
- organizer, round 3: A tie from Wikidata employer country alone counts as medium, never strong.

### R6: option c, unanimous

- **organizer** (c): I keep c. Only 1 stored person has the topic and a place without a tie (tiers.md), so a no-tie group needs a new search. The gate saves 2 Parallel calls and 12 to 21 page reads in about a quarter of searches, and d puts at risk the web lane that found every creative pick (gold-reality.md).
- **engineer** (c): I keep c. Only 1 cut person has the topic and a place without a tie (tiers.md:9), so a no-tie tier needs a new search. That search costs 2 Parallel calls and 12 to 21 page reads, and the gate skips it in about a quarter of searches. d has no measurement and puts the web lane that found every creative pick at risk.
- **skeptic** (c): I keep c. Only 1 stored person has the topic and the place without a tie (tiers.md), so a no-tie tier needs a new search, and the gate skips about a quarter of the extra Parallel calls. d has no measurement and puts the Belgian yield of the web lane at risk.

Amendments proposed:

- engineer, round 1: Fire the second request only when parse marks the tie as nice, or when the tie is a must and tiers 1 and 2 hold fewer than 20 people. Log its added seconds in step_calls so the latency can be read on the first live runs.
- skeptic, round 3: Log the added seconds and Parallel calls of the second search in step_calls so the cost shows on the first live runs.
- engineer, round 3: Log the second search's added seconds and calls in step_calls.
- organizer, round 3: Send the second search always when the tie is a nice-to-have and only under the fewer-than-20 gate when it is a must, and log the added seconds in step_calls.

### R7: option b, unanimous

- **organizer** (b): I keep b with my skip amendment. The skip covers c's budget saving where parse returns only non-research role chips. The cap also guards the case c leaves open: parse missed a role chip for 3 held picks, and then c runs the lane uncapped into a first 20 that is already 44% OpenAlex-only with no gold pick (gold-reality.md:9). The engineer's metric belongs here too, so the share and the researcher picks (GS-10, 15, 29) stay checked.
- **engineer** (b): I move from c to b with the organizer's amendment. The skip still applies where the signal is clear: no OpenAlex calls when every role chip is non-research. My earlier argument missed the questions with no role chip. There R3 c demotes nobody and the lane runs, so only a cap stops the 44% OpenAlex-only share of the first 20 (gold-reality.md). The cap is a single number that fn-score rerank can test on stored searches, and the share metric plus a replay of GS-10, 15 and 29 confirm the researcher picks keep their place.
- **skeptic** (b): I keep b, but drop one argument: the 5-of-8 figure measures card classification, not how parse reads the question, so it does not count against a skip. The cap still matters for questions with no role chip, where c runs the lane uncapped and the 44% OpenAlex-only, zero-gold first 20 (gold-reality.md) stays. A cap of 5 can be tested with fn-score rerank on stored searches, and the organizer's skip adds c's budget saving where parse returns only non-research chips.

Amendments proposed:

- skeptic, round 1: Count the 5 mixed research and business questions as asking for researchers. Report the OpenAlex-only share of the first 20 as an fn-score metric so the cap stays visible.
- organizer, round 1: Skip the lane entirely when parse returns only non-research role chips (founders, journalists, executives), to save the daily OpenAlex budget for the questions that use it.
- engineer, round 1: Use the same parse role signal as R1 and R3. Replay the gold searches with the OpenAlex lane removed for business questions, and check that the researcher picks (GS-10, 15, 29) keep their place.
- engineer, round 2: Report the OpenAlex-only share of the first 20 as an fn-score metric, and replay the gold searches to confirm the researcher picks (GS-10, 15, 29) keep their place.
- skeptic, round 3: Skip the lane when every role chip is non-research, cap OpenAlex-only people at 5 of the first 20 otherwise unless the question asks for researchers, and report the OpenAlex-only share as an fn-score metric with GS-10, 15 and 29 replayed.
- organizer, round 3: Skip the lane when parse returns only non-research role chips. Otherwise run it and cap OpenAlex-only people at 5 of the first 20 unless the question asks for researchers.

### R8: option c, unanimous

- **organizer** (c): I keep c. evidence.topic (src/fn/evidence.py:95-103) gives a full match for 'health' in an institute's name. Thin business records carry an employer in 64% of cases but a topic claim in only 22% (held-not-returned.md), so b would erase their only sector signal.
- **engineer** (c): I keep c. A business record has an employer in 64% of cases but a topic claim in only 22% (held-not-returned.md), so b would remove the only sector signal those records carry. The change stays inside evidence.topic (src/fn/evidence.py:95-103), and rerank can measure it.
- **skeptic** (c): I keep c. evidence.topic (src/fn/evidence.py:95-103) matches chip words in organization names, giving 'health' in an institute name a full match. Business records hold an employer in 64% of cases but a topic claim in 22% (held-not-returned.md), so b would remove their only sector signal.

Amendments proposed:

- engineer, round 1: In evidence.topic, words found only in the org name of an employer claim count toward Topic.words but never set Topic.match.
- skeptic, round 3: An org-name word adds to Topic.words but never sets Topic.match.
- engineer, round 3: Words from an organization name go into Topic.words but never set Topic.match.
- organizer, round 3: Words from an organization's name go into Topic.words but never set Topic.match.

### R9: option b, unanimous

- **organizer** (b): I keep b. Business records hold a median of 2 claims and a place in 19% of cases (held-not-returned.md), so even a correct founder pick rarely looks invitable to Paul. A batch over about 460 records fits the Parallel limits and keeps FN_LLM=record replay working. A lookup during the search would add time to a 68 s search.
- **engineer** (b): I keep b. A lookup during the search (c) adds live calls to a 68 s search and breaks FN_LLM=record replay. An offline batch over about 460 business records is one new lookup kind in fn-enrich, so it keeps one owner. GS-03#1 and GS-22#1 have OpenAlex namesakes (held-not-returned.md), so the anchor rule and an audit of 20 records come before the full run.
- **skeptic** (b): I keep b. Business records have a median of 2 claims and a place in 19% (held-not-returned.md), and the batch can be scored on the benchmark before and after. c adds live calls to a 68 s search and breaks FN_LLM=record replay.

Amendments proposed:

- skeptic, round 1: Look up only seed and web-mention records that have a school or employer anchor. Store a fact only when the fetched page names that anchor next to the person, keep it under its own source kind, and audit a sample of 20 for namesakes before the rest of the batch runs.
- organizer, round 1: Limit the batch to non-OpenAlex records with a role or seed-list entry and fewer than 3 claims or no place. Store only claims with a quoted source excerpt, so a namesake page cannot add a false role.
- engineer, round 1: Add a web lookup kind to fn-enrich, limited to seed and mention records that have a role but no place or employer. Store a claim only when the page also names the person's known school or employer, which guards against namesakes (GS-03#1 and 22#1 have one). Spread the runs over several days to stay inside the Parallel limit.
- skeptic, round 3: Anchor each lookup on a known school or employer, store only claims with a quoted excerpt that names the anchor next to the person under their own source kind, and audit 20 records for namesakes (GS-03#1, 18#4, 28#4 rest on name and school) before the full batch runs.
- engineer, round 3: Anchor each lookup on a known school or employer. Store only claims with a quoted excerpt, under their own source kind. Audit 20 records for namesakes before the full batch runs.
- organizer, round 3: Anchor each lookup on a known school or employer, store a fact only when the page names the anchor next to the person and quotes the excerpt, and audit 20 records for namesakes (GS-03#1, 18#4, 28#4) before the full batch runs.

## Panel 3: how the pages read

Judges: the organizer's advocate, the design-system designer and the page engineer. Brief: [panels/p3-pages.md](panels/p3-pages.md). Rounds: 2. Unanimous after each round: 8, 9 of 9.

### U1: option b, unanimous

- **organizer** (b): I keep b. Both walks lost the place on every return at 1280 px (card 9 to card 1, card 27 to card 1 with 20 shown instead of 40; ux-walk-walk-new.md section 2). Previous and Next let Paul check three speakers with one tap each instead of open, back, scroll, open. The other two amendments fit with mine. The designer's always-present anchor is the guarantee, and the engineer's sessionStorage restore covers the browser's Back at 900 px and wider.
- **designer** (b): I keep b. Both walks reset the list panel to card 1 at 1280 px (2183 px to 0, 9979 px to 0), and the back link drops shown=40. The existing card-<key> anchors fix that without touching ResultsLayout or PersonCard. Previous and Next are plain links, so they work at 390 px and need no JavaScript. The three amendments fit together: carry the parameters, show the line only with a search, and restore scroll as a fallback.
- **engineer** (b): I keep b. All three judges found the same cause: parts.py profile_head links back to the bare /searches/{id}, which drops shown and the #card anchor. Previous and Next are plain links over the order results() already computes, so a server test can check the neighbour hrefs. The three amendments fit together. Carrying search, shown and card on every link also covers the bfcache case that nobody checked.

Amendments proposed:

- organizer, round 1: Previous and Next carry the same search, shown and card parameters, so the Back link after walking returns to the card last viewed, not the one first opened.
- designer, round 1: Previous/Next and '4 of 40' go into the Profile part as one line under the back link, shown only when the page was opened with a search. The back link always carries shown and #card-<key>, because the anchor is the guarantee and bfcache was not checked.
- engineer, round 1: Show Previous and Next only when the URL carries search and card, and carry search, shown and card on every link. To restore the inner list scroll on browser Back at 900 px and wider, results.js saves .fn-results__list scrollTop in sessionStorage on pagehide and restores it on pageshow, and falls back to the #card anchor.

### U2: option b, unanimous

- **organizer** (b): I keep b. Five screens have no way back except the browser button (ux-walk-walk-new.md section 3), and a person page opened from a search marks Network (f3-01-person-full.png). On a 390 px screen a breadcrumb adds a row of words for a path that is at most three levels deep. The engineer's rule to show no back link when the origin is unknown is better than a guessed one.
- **designer** (b): I keep b. All three judges count the same dead ends: source, possible match, map popup, Network list, and the page after Remove, Undo or Same person. The person page reached from a search wrongly marks Network. FN is at most three levels deep, so a breadcrumb would only repeat the back link. The engineer's rule to show no back link when the origin is unknown is better than guessing one.
- **engineer** (b): I keep b. The five dead ends have one cause: a link or redirect drops where the page was opened from. back_to in staff.py already follows a next path, so b is about a day of work, with one test per route. A breadcrumb would be a second way back that can disagree with the first.

Amendments proposed:

- designer, round 1: The ViewSwitch marks Search with aria-current='page' whenever the URL carries a search id. Every link and redirect that leaves a page (map popup, Combined link, POST redirects) keeps the search and origin parameters, so the back link survives.
- engineer, round 1: A source page and a possible-match page take a from= parameter naming the page that opened them, so their back link names it. With no origin, show no back link rather than guess one.

### U3: option b, unanimous

- **organizer** (b): I keep b. Quotes are 60% to 79% of a person page's words, and 'Studied at' sits under Work (ux-patterns.md, f3-01-person-full.png). The designer is right that 'Works at' and 'Based in' repeat the head word for word and break the 90-word first-screen budget, so I take that cut. With mine added, a person with 3 to 5 facts sees each fact once.
- **designer** (b): I keep b. Quotes are 60% to 79% of a person page's words, and 'Studied at Brandeis' is filed under Work. Labelled sections fix both inside Profile and Claim, and tabs would hide facts on pages that hold only 3 to 5. The summary must not repeat the head's headline and place, and sections must not repeat the summary. Those two amendments together keep the first screen inside the 90-word budget.
- **engineer** (b): I keep b. The summary data already exists in present.py, and sections with Show n more already exist in parts.py fact_groups. The designer is right that 'Works at' and 'Based in' would repeat role_line in the head, so the summary should keep only the rows the head lacks. I do not endorse the organizer's rule to drop a section when the summary holds all its rows: section headings would then appear or vanish from person to person, and both the page and its tests become harder to predict.

Amendments proposed:

- organizer, round 1: When a section's only rows already appear in the summary, leave that section out, so a person with 3 to 5 facts does not see each fact twice.
- designer, round 1: The summary keeps only rows the head does not show (Studied, Tie to Flanders, Contact) and is added to the design system as a SummaryList part before use. Sections show three rows, then ShowMore, as in option c.
- engineer, round 1: Build the 'why for this search' block only when the page has a search, from the same why_of output the card uses, so card and page cannot disagree. Leave an empty summary row out, except Contact, which shows 'Not found'.
- organizer, round 2: The summary holds only the rows the head does not show (Studied, Tie to Flanders, Contact). Leave a section out when its only rows are already in the summary.

### U4: option b, unanimous

- **organizer** (b): I keep b. All 54 of 54 combined cards open a page that disagrees with the card on role, place and the Flanders tie (ux-walk-walk-new.md problem 1). Merging for good (c) would hide wrong links with no way to undo them. The engineer's amendment fixes the cause: parts.py:129 drops the search from the card links. It also leaves the Network pages unchanged.
- **designer** (b): I keep b. All 54 of 54 combined cards open a page that contradicts them (ux-walk-walk-new.md, problem 1). Profile's existing 'Found as' list becomes Sources with 'Not this person' on each record, which keeps the repair path that option c would remove. The engineer's amendment names the dropped search parameter at parts.py:129 and keeps the Network pages unchanged.
- **engineer** (b): I keep b. identity.on_card groups the card, while profile() reads only the canonical id, so all 54 of 54 combined cards open a page that contradicts them. 'Not this person' reuses the existing not-same route. Option c writes identity links nobody confirmed and offers no way to undo them in bulk.

Amendments proposed:

- engineer, round 1: The card's name link and its 'Combined from N records' link both carry search (parts.py:129 drops it today). profile() then reads on_card(candidate) for the group. Without a search the page shows the canonical person as today, so the Network pages do not change.

### U5: option b, unanimous

- **organizer** (b): I keep b. One line per fact, with the proof in a <details> element that opens on tap, lets Paul check a fact at 390 px without leaving the page (ux-patterns.md C1). The designer's amendment drops debris quotes such as 'Author Orcid Image'. The engineer's keeps the remove control from moving when the proof opens. Both cost Paul nothing.
- **designer** (b): I keep b. One line per fact meets the 12-word fact budget. A native <details> proof works by keyboard and by tap at 390 px (ux-patterns.md, C1), and claim_line in parts.py:437 already holds the quote. The summary needs an accessible name, and debris quotes must be dropped. Keeping 'Not correct' outside the <details> element stops the control from moving when the proof opens.
- **engineer** (b): I keep b. claim_line in parts.py already renders view.quote and the cite, so b moves existing markup into a <details> element that needs no JavaScript, and quote_words already sets the 25-word cap. The designer's accessible summary name and the rule against debris quotes fix the 'Author Orcid Image' case. My amendment keeps the remove control from moving when the proof opens.

Amendments proposed:

- designer, round 1: The Claim part's summary element is the source name, with an accessible name such as 'Source for Studied at Ghent University: Wikidata'. The quote is cut around the matched words, and a quote of raw page text ('Author Orcid Image', '* Name:') is left out in favour of the title and link.
- engineer, round 1: Keep 'Not correct' (U8) on the fact line outside the <details> element, so opening the proof never moves the remove control.

### U6: option b, unanimous

- **organizer** (b): I keep b. Today the source page opens 724 px down with no person, no fact and no back link, and one runs to 17,729 words (ux-walk-walk-check.md problem 4). Option c loses the stored copy just when the original page has changed. The two amendments keep the sentence free of model calls and keep the long stored record off the default view.
- **designer** (b): I keep b. Source pages today run 1063 to 17,729 words, open 724 px down and name neither the person nor the fact. source_page (staff.py:243) already loads the claim, so the sentence and the back link come from stored data. The stored copy stays one disclosure away for sources whose original page has moved.
- **engineer** (b): I keep b. source_page already loads the claim, so the sentence and the back link come from data the route already has, built from a template with no model call. The stored copy is the only proof left when the original page changes, so c is weaker. Putting the raw record behind a disclosure keeps today's working highlight-and-scroll.

Amendments proposed:

- designer, round 1: The one sentence is built from the stored fact that linked to the page (template plus field values), with no model call, and the page heading names the person.
- engineer, round 1: When the page opens from a fact, open the stored-record disclosure scrolled to the highlight only on request; the default view is the sentence, the passage in context and the original link.

### U7: option b, unanimous

- **organizer** (b): I keep b. Cards have a median of 41.5 words, with a 30-word quote on 19 of 20 cards, and some quotes are debris (ux-patterns.md). A 15-word reason with its source fits the 25-word budget. The designer is right that 20 cards should not repeat their tier heading. So the wishes line, including unmet wishes, appears only where tiers.md section 5 headings are not adopted.
- **designer** (b): I keep b. The median card has 41.5 words, 30 of them quote, and some quotes are page debris such as 'Author Orcid Image'. A templated reason line from the claim that evidence() already picks (present.py:81) explains the match within the 25-word budget. I leave out the organizer's unmet-wish text: if the tier headings already state the met wishes, 20 cards would repeat their heading and go over budget.
- **engineer** (b): I keep b. evidence() in present.py already picks one claim per card, so the reason line is a template over that claim, testable by counting words on 20 cards. I endorse the designer's amendment because it ties the wishes line to panel 1's choice, which stops 20 cards repeating their tier heading. The organizer's rule to list unmet wishes on every card would bring that repetition back.

Amendments proposed:

- organizer, round 1: The wishes line also names an unmet or unknown wish ('place unknown', 'no known tie'), so it agrees with the tier headings in tiers.md section 5 and a partial match reads as fair.
- designer, round 1: If panel 1 adopts the tiers.md section headings that name met wishes, the card drops its wishes line and keeps only the reason line, so 20 cards do not repeat their heading. A card with no stored fact for the reason shows its headline only, never an invented sentence.
- engineer, round 1: Write the reason line as a template over the stored claim (what, organization, years), never as generated prose. Test it by counting words on the 20 cards of a stored search.

### U8: option b, unanimous

- **organizer** (b): I keep b over the designer's c. The reviewer drops a wrong fact while deciding whether to add someone, and 'Not correct' reads clearly on a candidate, where the old bare 'Remove' did not. Distinct labels fix the misclick from the walk (f6-1280-03-person-in-network.png, parts.py:368 and :447). The anchor redirect in the engineer's amendment fixes the confirmation that lands below the fold at 390 px.
- **designer** (b): I move from c to b. The engineer and the organizer show that the reviewer drops wrong facts while deciding whether to add someone, and today's Undo covers that case. The confusion the new-user walk found came from the shared word 'Remove' (parts.py:368 and :447), and distinct labels fix that alone. With c, a reviewer could not correct a fact before Add.
- **engineer** (b): I keep b over the designer's c. parts.py claim_line puts the reject control on every fact, candidates included, and that is how a reviewer drops a wrong fact before deciding on Add. Undo already covers a mistake there. The confusion the designer cites comes from the shared word 'Remove' (parts.py:368 and :447), which the new labels fix, and 'Not this person' (U4) is a separate per-record control. It does not replace removing one wrong fact.

Amendments proposed:

- designer, round 1: After 'Not correct' the redirect lands on #fact-<id>, so the in-place 'Removed · Undo' line is on screen. The check walk found it below the fold at 390 px. The redirect replaces the history entry instead of adding one.
- engineer, round 1: After Not correct and after Undo, back_to redirects to the person page with #claim-<id>, so the 'Removed, Undo' line is on screen at 390 px.
- designer, round 2: After Not correct and after Undo, the redirect lands on #claim-<id> and replaces the history entry instead of adding one, so 'Removed, Undo' is on screen at 390 px and Back does not replay the action.
- organizer, round 2: The redirect after Not correct and after Undo replaces the history entry instead of adding one, so the browser's Back still returns to the results.

### U9: option b, unanimous

- **organizer** (b): I keep b. For a Boston question the map opens on the whole world, and only 2 of 9 count markers can be clicked (f5-1280-01-map.png, ux-walk-walk-check.md flow 5). The designer's maximum zoom keeps a one-person view from opening at street level. MapLibre's built-in clustering, from the engineer, avoids custom code for markers that overlap.
- **designer** (b): I keep b. At world zoom only 2 of 9 count markers can be clicked, and Tab skips the map (k1-1280-tab10.png). Count markers are already DOM elements (map.js:162 to 171), so making them buttons costs little. MapLibre's built-in clustering avoids custom spiderfy code. A maximum zoom on the opening view stops a single person from opening at street level.
- **engineer** (b): I keep b. map.js already fits bounds, and count markers are DOM elements, so making them <button> elements with labels costs a few lines. Today 2 of 9 markers can be clicked and Tab skips the map. Using MapLibre's built-in clustering avoids custom spiderfy code, and capping the zoom keeps one person from opening at street level.

Amendments proposed:

- designer, round 1: MapMarker gains tabindex, a label such as '4 people near Boston', Enter or Space to open the popup, and Esc to close it and return focus to the marker. The opening view fits the shown people with a maximum zoom so one person does not open at street level.
- engineer, round 1: Fix overlap with MapLibre's built-in GeoJSON clustering on the existing source instead of custom spiderfy code. Count markers become <button> elements that open the same popup on Enter.

## Panel 2: how FN searches the web, reads pages and grows its lists

Judges: the organizer's advocate, the staff engineer and the steward of terms and limits. Brief: [panels/p2-web-and-sources.md](panels/p2-web-and-sources.md). Rounds: 1. All 4 unanimous in round one.

### W1: option b, unanimous

- **organizer** (b): The search route matters less than the wording of the queries. In local-search.md the DuckDuckGo HTML endpoint gave 7, 5 and 6 people-naming pages out of 10 on the three test questions, in about 1 s and with no block in 8 queries, so it is a sound free default when no Parallel key is set. The Claude web search is too slow to be more than a last resort: 12 to 22 s a query, and 7 of its 72 URLs returned 404. Querying two backends on every search (d) doubles the load on an endpoint whose daily ceiling and terms nobody has checked. I keep Parallel as the default (b rather than c) because Paul gets the most proven results from it, at $0.001 a query.
- **engineer** (b): Parallel is the only route with known terms and no observed block, at $0.001 a query (web.py PRICES), so it stays the default while a key is set. DuckDuckGo's HTML endpoint gave 5 to 7 of 10 people pages in 0.5 to 1.2 s with no block over 8 queries, but its terms and daily ceiling are unchecked (local-search.md), so it should be the keyless default and not the primary (option c). Asking two backends on every search (d) doubles calls and gives a 3 a.m. failure two places to happen, and no note measured any gain in recall from merging.
- **steward** (b): local-search.md shows the DuckDuckGo HTML endpoint gave 5 to 7 people pages of 10 with robots.txt allowing html.duckduckgo.com, but its terms and daily ceiling were never checked, so it should not replace a paid route that works today (Parallel, $0.001 a query, no cap recorded). b keeps Parallel when a key is set, adds a free route without one, and leaves SearXNG off because its useful engine scrapes cse.google.com, whose robots.txt disallows /, and DuckDuckGo and Brave blocked it after 4 and 8 queries. d doubles the scraping load on an endpoint with an unknown ceiling, and c makes an unchecked route the default.

Amendments proposed:

- organizer: Send panel 1's second web query, the one without a tie, to DuckDuckGo even when a Parallel key is set. tiers.md:84 proposes this to keep Parallel calls flat while the extra lane brings in topic experts without a tie.
- engineer: Put all backends behind websearch.find and select them with one search_backend setting. Each adapter is tested against recorded responses, including a DuckDuckGo CAPTCHA page and an empty page. Fall back to the Claude web search only when the primary raises or is blocked, and record the fallback as a Considered note. A short result list does not trigger it, because Claude queries take 12 to 22 s and about 1 in 10 of its links is dead.
- steward: The DuckDuckGo adapter spaces queries at least 4 s apart, keeps a daily query count with a cap in settings, and on a CAPTCHA, 403 or 429 marks itself suspended for the day and falls through to the next backend with a recorded note. The choice is one setting `search_backend` (parallel, ddg_html, searxng, claude) so the owner can switch back with one line.

### W2: option d, unanimous

- **organizer** (d): Query wording changed results more than the route did. The Dutch query gave about 8 people-naming pages out of 10 with 2 on target, the best of the whole test, and dropping 'Belgian' lost the tie (local-search.md). Today web.py:56 writes one query per topic chip, which misses Dutch press interviews with Flemish executives in the US, the kind of guest Paul invites. Letting the parse call write the queries adds role and sector words, which held-not-returned.md names as the largest recall gain (11 of 19 picks). The rule from b catches a bad or empty model answer at no extra cost.
- **engineer** (d): local-search.md found that query wording mattered more than the route: the Dutch query gave the two best on-target pages of the test, and dropping 'Belgian' lost the tie. A rule cannot put a free-text topic chip into Dutch, so b cannot deliver its Dutch half without a model, while the parse call already runs on every search and costs no extra call. A deterministic rule fallback keeps the lane working, and testable, when the model returns nothing or a malformed list.
- **steward** (d): local-search.md found query shape changed results more than the route: the Dutch query gave about 8 P and 2 N with 2 on-target titles, and dropping 'Belgian' lost the tie on every route. The parse call already runs, so model-written queries add no cost and can carry role words the topic chips miss (web.py:56 today sends only chip text plus place), while the rule fallback keeps search working when the model output is empty or malformed. Site-filtered queries only pay off on some backends: DuckDuckGo returned 0 for site:tijd.be and the Claude search ignored site:kuleuven.be.

Amendments proposed:

- organizer: Send the query restricted to Belgian press and university sites only to a backend that honours it (Parallel or SearXNG). On DuckDuckGo, replace it with a second Dutch query, because DuckDuckGo returned 0 results for site:tijd.be.
- engineer: Validate the model's list in the parse schema (at most 5 strings, each with the place) and fall back to b's English rule. The no-tie lane drops the country word by rule, not by a second model output. Send site: queries only to backends that honour them: DuckDuckGo returned 0 results for site:tijd.be and the Claude web search ignored site:kuleuven.be.
- steward: Validate the model's list against the rule's invariants: at most 5 queries, at least one in Dutch, and the country word kept in the tie lane, filling the missing ones from the rule of b. Send the site: query only to a backend that honors it (Parallel or SearXNG), and record the final query list in the step so cached runs replay identically.

### W3: option b, unanimous

- **organizer** (b): The standard-library parser read 7 of 10 pages, kept the line naming both analysts on the CNN page where trafilatura failed, and took 131 ms for nine pages. That means FN stops paying Parallel per page for most pages and needs no new dependency. The three failures were a 403, a JavaScript-only page and a PDF. pdftotext turned the PDF into text in 0.18 s, and conference speaker pages like the 403 one are exactly where Paul's speakers are listed, so keeping Parallel Extract as a fallback for failed pages (b, not c) protects recall.
- **engineer** (b): The stdlib parser preferring main or article read 7 of 10 pages in 131 ms in total for nine HTML pages, with no new dependency, and pdftotext read the PDF in 0.18 s (local-search.md). The three failures (a 403, a JavaScript-only page, a PDF) are the cases where an optional Extract fallback costs $0.001 a page, so dropping it (c) loses pages for nothing. Fetching through net.Client keeps recording and caching in one place.
- **steward** (b): The stdlib parser preferring main or article read 7 of 10 pages, kept the article first on both newspaper pages, and took 131 ms for nine pages against 418 ms for trafilatura, with no new dependency; pdftotext read the PDF in 0.18 s. The three failures (a 403, a JavaScript-only page, a PDF) need a fallback, and the brief requires the owner can switch back to Parallel with one setting, which c removes. net.py on main has no robots.txt check, and once FN fetches arbitrary pages itself that becomes FN's responsibility.

Amendments proposed:

- engineer: Count a local read as failed on a non-2xx status, a 999, under 300 characters of text, or a PDF without pdftotext on the PATH. Store locally read pages under a new source kind, not vendor_page, so score runs stay comparable. Check each host's robots.txt (cached per host) before fetching, as the brief's limits require.
- steward: Before a local fetch, check the host's robots.txt with the stdlib urllib.robotparser (cached per host through net.Client) and skip disallowed URLs such as LinkedIn profiles, sending them to Parallel Extract only when a key is set. Store locally read pages under their own source kind, not vendor_page, and keep `page_reader` and `parallel_fallback` as settings.

### W4: option c, unanimous

- **organizer** (c): The Form 990 officer lists are the best open source found for plain professionals. They found 2 of the 5 non-researcher gold picks (GS-23#2, GS-32#4) and add 100 to 150 people with a role and a year in 1 to 1.5 days (people-sources.md). The BelCham and embassy lists add 42 business people with a role, an employer and a state in half a day. The wider Wikidata query (d) found 0 of 5 gold picks and mostly adds researchers. Paul asked for business people, so that time is better spent on search and ranking this round.
- **engineer** (c): The Form 990 officer lists are the only open source measured that reaches plain professionals, and they find 2 of the 5 non-researcher gold picks (GS-23#2, GS-32#4), against 1 of 5 for the two one-page lists (people-sources.md). The work is 1 to 1.5 days on top of half a day, and reading the public IRS e-file XML runs locally and carries the fiscal year. The Wikidata widening (d, e) found 0 of 5 gold picks and waits on a User-Agent decision, so it can wait for a later round.
- **steward** (c): people-sources.md names Form 990 officers as the best open source measured for plain professionals: about 100 to 150 people from about 12 organizations, finding 2 of the 5 non-researcher gold picks (GS-23#2, GS-32#4), against 1 of 5 for the BelCham and embassy pages alone. Both are clean on terms if read from the public IRS e-file XML, and the embassy page's phones and emails must be dropped at load. The wider Wikidata query found 0 of 5 gold picks, its count comes from a mirror with an unknown snapshot, and the Wikimedia endpoints ask for contact details in the User-Agent, which is the owner's decision, so d and e wait.

Amendments proposed:

- engineer: Fix the list of about 12 organisations by hand in the seed script, and store each officer row's fiscal year as the claim date. Drop the embassy page's phone numbers and email addresses at parse time, and add a test that checks they are not stored.
- steward: Read the 990 officers from the IRS bulk e-file XML rather than ProPublica's pages (ProPublica's terms beyond robots.txt were not checked), and store the fiscal year on each row so a lagging officer list reads as dated history. The embassy loader keeps name, role, employer, state and page date only.
