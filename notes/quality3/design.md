# How does FN get faster, show fewer wrong people and fill the profiles of the best ones?

**TL;DR.** After round two the owner is happy with the pages and the ranking, and names four problems: a search takes about five minutes, the list holds people who fail an essential wish (the wrong city, the wrong country, dead), a good person can show up with too few facts to decide on, and one question returns 300 people. This round turns the search into stages: broad and cheap first, then a lookup of missing facts for the first people only. It makes every wish either required or a wish, and the ranker reads that. It runs the lanes side by side.

## What is wrong today, in numbers

Measured on the owner's search "Belgian scientists in the Washington D.C. area" unless said otherwise. The research notes with the queries are kept outside git because they quote real people.

| Problem | Number |
| --- | --- |
| Seconds for one search | 272 (the midterms search: 294) |
| Share of that time spent waiting on model calls | 95% |
| Seconds the web research lane waited on text about people it then dropped | 83 |
| People kept | 342 |
| People under the first heading who are known to be outside the area | 75 of 104 (59 outside the US) |
| People in tier 1 without a known place | 23 of 29 |
| Of those 23, people whose employer is outside the area by its name | 21 |
| Chip needs that any code reads | the tie's only; place and role needs change nothing |
| Stored email addresses and phone numbers | 0 |
| First 50 cards with a role, an employer, a place | 41, 47, 29 |
| Claims that state a death | 0 (52 persons have a death line in a stored page) |
| OpenAlex calls refused on the day the enrich job ran | 823 of 1,800: the daily budget of $1 was spent on name searches |

## What the judges measured

Twenty questions: the 14 of round two and 6 new short ones, as the owner types them. Three model judges score the first 20 cards of each question with the written rubric, and an arbiter rules on disputed first-ten cards. A card is invitable when the topic fits, the card shows a current role and employer with a recent sourced fact, and the tie and place rules of the question hold.

| Measure | Start of the round | All slices (run c7) | With F1 and F2 (run c9) |
| --- | --- | --- | --- |
| Invitable people in the first tens, 13 development questions | 22 of 130 | 34 | 43 |
| Invitable people in the first tens, 7 held-back questions | 5 of 70 | 14 | 13 |
| Invitable people in the first twenties, all 20 questions | 30 | 64 | 73 |
| Questions with nobody invitable in the first ten | 8 of 20 | 7 | 5 |
| First-twenty cards that are noise (topic 0 or 1, wrong place, gone) | not judged for the 14 older questions | 233 of 387 | 211 of 386 |
| First-ten cards with a role, an employer and a place | 30% | 40% | not counted |
| First-ten people with an email or phone stored | 0 of 200 | 24 of 200 | not counted |

Seconds per search, live:

| Question | Start of the round | Lanes side by side, no lookup | With the lookup after the lanes | With the lookup beside the lanes, 12 people |
| --- | --- | --- | --- | --- |
| Belgian scientists in the Washington D.C. area | 247 | 97 to 121 | 196 to 228 | 145 |
| Political scientists in New York City specializing in federal politics | 272 | 116 to 146 | 175 to 196 | 128 |

The first cards show after 20 to 24 s in every version.

On the owner's database after the rollout, live: the Washington question took 127 s with the first cards after 16 s, the New York question 154 s with the first cards after 17 s. A first run of the New York question took 214 s on a thin reading (decision P1).

What the numbers do not show. The judges are models and score only what a card shows; a person can be right and score low because the card dates a fact by the day FN read the page. Five questions still have nobody invitable in the first ten: journalists in New York who grew up in Belgium, life-science investors in Boston with a Flemish degree, food traders in Chicago, economists in Chicago with a KU Leuven degree, Flemish architects in Los Angeles. Those people are not in the stored lists and the open web names few of them; a profile source such as LinkedIn would.

## The shape of a search after this round

1. **Parse.** The model returns chips. Every chip is required or a wish.
2. **Find, side by side.** Stored lists, OpenAlex, the web lane and the web research lane run at the same time. The list is published as each one ends, so the first cards appear after the fastest lane.
3. **Rank.** Required wishes filter. Wishes order. A person known to fail a required wish is not in the open list.
4. **Look up.** For the first people who miss a fact that can change their rank, FN looks the fact up: first in records it can get by identifier, then on the web. It stops at the first sourced answer.
5. **Check and rank again.** The fit check and the final order, as in round two.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a chip is required or a wish | `parse.py` with `prompts/parse.md` |
| Whether a reading is thin and is asked again | `parse.py` |
| What a required wish does to a person's tier and to the cut | `rank.py` |
| What a person's records show: place, job, tie, first and newest dated fact, a death | `evidence.py` |
| The order in which steps run, what runs side by side, and the time budget | `search.py` |
| One step's row, its calls, and step numbers | `steps.py`, `store.py` |
| Which people get a lookup and what is looked up | `deepen.py` (new) |
| Reading a page | `pageread.py` |
| Turning page text into claims | `extract.py` with its prompts |
| Linking an employer name to an organization with a place | `orgs.py`, run by `fn-orgs` |
| What a card, a list and a person page show | `present.py`, the design system |

## Decisions the lead took from the research

### Speed

- **S1. The web research lane asks the page reader about its leads only.** Today the reader writes about every person on a page and the lane drops the others afterwards. One such call took 83 s.
- **S2. Lanes run side by side, after the stored-lists lane.** The stored-lists lane runs first and alone, because it reads the store that the other lanes write to; run beside them, it sometimes found people another lane had saved a moment earlier, and two runs of one question gave different lists. It takes about 5 s. The search thread then starts the other lanes, keeps their outputs in the fixed lane order, and publishes after each lane ends, one publish at a time. The web_topic lane keeps its place after the others, because it reads the count of the first heading.
- **S3. A step gets its number inside the transaction that inserts its row**, so two lanes can start at once.
- **S4. The city index is built before the lanes start**, behind a lock, so no lane builds it inside a write.
- **S5. At most 16 model processes run at once** in one FN process (`llm_procs`), and a lane runs up to 12 model calls at once. First set to 10 and 6; a live run of two questions with 16 and 12 took 97 s and 116 s against 121 s and 146 s, with no failed call.
- **S6. The prompt of the `extract` task does not change this round.** Recorded answers are keyed by the prompt text. A changed prompt would force every recorded page to be read again, in tests and in the benchmark. New behaviour gets its own task name.
- **S7. The web researcher reports people from search results and opens no page.** FN opens every reported page itself, so the model's own page opening was double work. Measured on ten calls: 26 to 39 s and 24,000 to 41,000 input tokens each, where the old prompt took 51 to 94 s and 58,000 to 153,000 tokens, and 20 leads where it gave 8. End to end, the New York question kept 8 people from the lane where the old prompt kept 2.
- **S8. The lookup step starts when the stored-lists lane has been published and runs beside the other lanes.** A second pass after the lanes takes the people the first pass did not see, within the same total of 20 lookups; the 90-day rule already keeps a person from being looked up twice. Run after the lanes, the step took 81 s and 127 s on two live questions and brought the searches to 196 s and 228 s.

### Data

- **D1. An employer name without a linked organization gets one through ROR's affiliation matching**, in the `fn-orgs` job. ROR data is CC0 and the call needs no key. Only a match ROR marks as chosen is taken. The job remembers each name it asked, so a rerun asks only new names.

- **D2. FN keeps a local copy of every OpenAlex author whose last known institution is in the US and who was ever affiliated with a Belgian institution.** On 17 November 2026 that is 31,921 authors. Fetching them takes about 320 list calls, 3% of one day's free budget. A web researcher found 0 to 2 people for "Belgian cardiologists in Houston" and "Belgian scientists in the Washington D.C. area", with the old angles and with three new ones; OpenAlex lists 574 such authors at four Houston medical institutions and 452 at the NIH. The copy is refreshed by rerunning the job.
- **D3. With a required place, the stored-lists lane starts from the people inside the area.** Today it searches words first and adds at most 20 people by place, and only when the question has no topic.
- **D4. The enrich job leaves 3,000 of OpenAlex's 10,000 daily credits for searches.** A name search costs 10 credits, a call by identifier 1 (response headers, 17 November 2026). The job stops when the remaining credits fall under the reserve.
- **D5. When a question asks for research in a required place and does not require a tie, the OpenAlex lane also searches works on each topic written at institutions inside the area.** Today the lane only searches works with a Belgian institution, so "political scientists in New York City specializing in federal politics" returns professors of Belgian politics in Belgium, whom the new rules set aside, and four people remain in the match tiers. The institutions inside the area come from FN's own stored organizations with coordinates; the index of D2 stores the institution of every indexed author, so the research institutions of a US metro are there.
- **D6. An employer named by a lane gets its organization during the search.** After the lanes, one step links the employer names of the search's people that have no organization: from the stored ROR answers first, then by asking ROR about names not asked before, at most 40 per search. Today a person the web research just found at a New York university has no place until the batch job runs, and under a required place stands under "place unknown": in a live run all 8 people the lane found for the New York question did.

### Pages

- **U1. The source page shows "Show the stored record" only when the setting `stored_record` is on.** It is off by default (`FN_STORED_RECORD=1` turns it on).

### What counts as a match, old and dead people, lookups: the panel's rulings

A panel of three judges (the organizer, a search engineer, a data steward) voted in three rounds. Twelve of fourteen decisions ended unanimous; N6 and A2 ended two to one and N7 by majority. The votes and reasons are in [panel-records.md](panel-records.md).

- **N1. A place that says where the people are is required** ("scientists in the Washington D.C. area", "who in Chicago", "Boston-based founders"). A place softened by words such as ideally, preferably or near, and a place that only names where the event is held ("at our event in New York"), is a wish.
- **N2. With a required place, a person known to be in the US but outside the area leaves the open list.** They stand in a closed group at the end, named after the reason. Each card there names the place fact and its source. The rule runs after the exemption for topic matches, so that exemption cannot bring them back.
- **N3. For every question that names a US place, required or wished, a person known to be outside the US leaves the open list** in the same way, in a group of their own. A question without a place keeps such people as today.
- **N4. With a required place, a person whose place is unknown stays under the same heading, after every person known to be inside the area.** The card says the place is unknown. The lookup step tries to find the place for the first of them.
- **N5. With a wished place, the place sorts before the tie grade inside a tier:** inside, then unknown, then outside.
- **N6. The three match headings stay open. "Other people found" is one closed group at the end, is left out of the headline count and keeps at most 50 people.** The rest are cut after ordering, with the cut reason `over_cap`.
- **N7. The results page shows how FN read the question:** one line under the question lists what FN took as required and what as a wish. The user changes it by asking again in other words.
- **A1. A person a source says has died leaves the open list** and stands in a closed group "People who have died". A death counts only from a "Died:" line or a lifespan inside the person's own entry on a page, or from a Wikidata date of death with a second matching fact (rule E3). The card shows the source quote.
- **A2. A first dated fact 60 years or more back with nothing recent keeps the person in their tier, after everyone else in it.** Recent means a role a source dates itself (never the date FN read the page) or two or more OpenAlex years in the last ten years. The first year leaves out a birth year and a lone leading year followed by a gap of more than ten years. The card says what is known, such as "First record 1958, nothing recent".
- **A3. An emeritus or retired-looking person sorts after active people in the same tier.** Retired-looking means an emeritus role, or a first dated fact 45 years or more back without a dated current role in the last five years.
- **E1. After the first ranking FN looks up missing facts for the first 20 people of the match tiers who miss a fact that can change their rank:** the place when a place was asked, a current role and employer, or any dated fact from the last five years. Contact details are looked up for the first 10 only. A lookup is stored and not repeated for 90 days. The person page gets a "Look up more" button for anyone else.
- **E2. A lookup runs in steps and stops at the first sourced answer.** First the person's OpenAlex record by its stored identifier or ORCID, in one batch call for all. Then one model call with web search, limited to two searches, that returns up to two pages, which FN reads itself. No Parallel call.
- **E3. A fact from a looked-up page is attached to a stored person only when the page names the person and also states a second fact FN already holds about them:** an employer, a place of study, a fellowship or a stored identifier. Code checks this. Otherwise nothing is attached and the lookup is stored as "not sure it is the same person".
- **E4. FN stores an email address or phone number only when it stands on a page of the person's employer or on their own professional page,** with that page as its source, and shows it on the person page only.

### Rulings the lead added, from the panel's principle

The panel's principle is that a person known to fail a required wish is not in the open list. Two cases follow from it that the vote list did not name. The owner can overrule either.

- **N8. A stored person the fit check answers "no" for leaves the open list** on a current question, into a closed group of their own. The role and the topic are always required, and "no" is the one sign FN has that they fail. Today such people stand under "Tie, topic not confirmed".
- **N9. "Tie, topic not confirmed" keeps at most 50 people,** like "Other people found", with the same cut reason.
- **F1 (an experiment, kept only if the benchmark agrees). The fit check also reads the people under "Tie, topic not confirmed",** after the match tiers and within its 120 places. A "no" sets such a person aside. A "yes" confirms a person whose card shows where they work: the model read the record and says the person does what the question asks, which word matching missed.
- **F2. Inside a tier a known job comes first, then a recent fact.** A role and an employer sort before an employer alone before neither, and a person whose newest dated fact is more than ten years old sorts last. The judges' reasons showed people known from one paper ahead of people with a role, and people whose newest fact is from 2001 under the first heading. F1 and F2 were judged together and kept: see the measurements.
- **A2 as built: an old first record sorts after everyone else under the same heading,** not only inside its tier. With a required place the first heading holds two tiers, people inside the area and people with an unknown place. A person inside the area whose first record is from 1958 is less likely to be invitable than an active person whose place is unknown, so the old record goes last.
- **The headline count is the open list:** the people under "In your network" plus the people under the three match headings. People set aside are not counted.
- **A search stored with version-1 chips is unchanged on the page too:** its list, its count and its map.
- **The fit check skips people already set aside,** so its 120 places go to the open list.
- **P1. A thin reading is asked again.** About 1 live parse answer in 110 holds one chip for a question with several wishes, and the whole search then runs on it: the first live run of the New York question on the owner's database read only "federal politics" and listed political scientists in Belgium. The parse step asks once more when a reading holds at most one chip and leaves three or more of the question's content words outside it, and keeps the reading with more chips. A share of unread words was tried as the rule and dropped: good readings of long spoken questions leave most words unread, and a short question with one wish would be asked twice. The rule asks again for none of 190 good readings measured.

## Briefs for the first slices

Each brief is the lead's decision. A planner turns it into a task file under `tasks/`, a reviewer checks the plan against the code, and only then is it built.

### Slice s1: the web research lane reads its leads only (S1, S6)

In `lanes/scout.py` the lane reads each page, cuts windows around the lead names, and calls `web.people`, which runs the `extract` task over the text and then keeps only the leads through `focus`. The model writes about everyone in the window first.

Build a second extraction task, `extract_leads`, used by the scout lane only. Its prompt is the `extract` prompt followed by one added paragraph that says: the `<leads>` block lists the people to report, in the spelling a researcher used; report only people whose name matches one of them, allowing initials, a missing middle name and another order of the same words; report nobody else. The base prompt text stays in one file and is not copied: the `extract_leads` prompt is built from `prompts/extract.md` plus `prompts/extract_leads.md`. The `extract` task's rendered prompt must stay byte for byte what it is today. The `focus` filter in the lane stays as the guard.

Done when: on the recorded scout pages of the tests the kept hits are the same as before; a test shows the leads reach the model call; a test shows the `extract` task's prompt hash did not change.

Not in this slice: contact details, deaths, any change to the web lane.

### Slice s2: lanes side by side (S2 to S5)

Read the speed research note's sections on parallel lanes first (the planner gets its path). Build S2 to S5. Keep `refinish` and stored searches working: a rerank reads lane outputs by step and must not depend on the order in which lanes ended. A lane that raises keeps its error row and counts as an empty output, as today. The fit step and the steps after the lanes stay as they are.

Done when: a test with stub lanes that sleep shows the search takes about the slowest lane and not the sum; step numbers are unique under concurrent starts; the outputs given to resolve are in lane order whatever the finishing order; a publish runs after each lane that added hits; the tests that pin today's step order are updated to the new order and listed in the report.

Not in this slice: a lookup step, a time budget, any change inside a lane.

### Slice d1: link employer names to organizations (D1)

2,300 claims name an employer, a host or a school without a linked organization (857 distinct names for `works_at` alone). Without the link the ranker finds no place for the person.

Add a mode to `fn-orgs` that takes each distinct unlinked name of `works_at`, `worked_at`, `affiliated_with`, `hosted_by` and `studied_at` claims, asks ROR's affiliation matching for it, and when ROR marks one organization as chosen, stores that organization with its country, city and coordinates and sets it on the claims with that name. A name is asked once; the answer, also "no match", is remembered. The job respects ROR's documented rate limit and can be stopped and rerun.

Done when: tests with recorded ROR answers show a chosen match is linked, a match that is not chosen is not, a name is not asked twice, and a rerank after the job gives a person with such an employer a place.

Not in this slice: fuzzy matching of FN's own, any model call, the ROR data dump.

### Slice u1: the stored record behind a setting (U1)

`Settings.stored_record` (default off, `FN_STORED_RECORD=1`). The source page leaves out the "Show the stored record" disclosure when it is off. Tests that pin the disclosure run with the setting on; one new test shows the page without it. The design system's Source part says the disclosure is for debugging and off by default.

### Slice r1: required wishes filter, wishes order (N1 to N6, N8, N9)

`prompts/parse.md` gets the N1 rule for the place need. `rank.py` reads the place need. `Candidate` gains `aside`, the reason a kept person stands outside the open list: `outside` (N2), `abroad` (N3), `unfit` (N8); the value `died` is added by the next slice. A person set aside is kept, not cut. Tiers change as N4 says, the order inside a tier as N5 says, and the two caps (N6, N9) cut the rest with `over_cap`. All of this holds for questions with current chips only: a search stored with version-1 chips keeps its order exactly.

`present.py` gives the page the open headings, then "Other people found", then one group per aside reason, each with its count, and for each card set aside the fact and source that put it there. The headline count is the number of people under the three match headings. Until the pages slice closes the groups, the results page shows each aside group under its own heading at the end of the list, with the existing heading part. The map shows the people of the open list.

The parse prompt changes, so recorded parse answers get a new key. The plan says which recorded answers and tests depend on the parse prompt, gives the lead one command that re-keys them without changing their content, and names any whose expected content changes because of N1.

Done when: tests show each rule with made-up people; a rerank of a search stored with version-1 chips is unchanged; on a copy of the owner's data a rerank of the Washington search with its place need set to required keeps the six people inside the area first and puts nobody known elsewhere in the open list.

Not in this slice: deaths and age (A1 to A3), the line that shows how FN read the question (N7), closing the groups, any lookup.

### Slice a1: deaths and age (A1 to A3)

`evidence.py` owns what a person's records say about age: the first dated fact (without a birth year, and without a lone leading year followed by a gap of more than ten years), whether anything is recent (a role a source dates itself, never the read date, or two or more OpenAlex years in the last ten), whether a role says emeritus, and whether a source states a death. `extract.py` owns finding a death in page text: a "Died:" line or a lifespan inside the person's own entry, bounded so a neighbour's line is never taken; it stores a claim with the year and the quote. A job fills this in for pages already stored. `rank.py` sets `aside` to `died` (A1), sorts a person with an old first fact and nothing recent after everyone else in their tier (A2), and a retired-looking person after active people in the same tier (A3). A person with a death claim has no current job, whatever OpenAlex years say. `present.py` gives the page the death fact with its source for the group, and the words of A2 for the card.

Done when: tests show each rule with made-up people, including a death line that belongs to the next entry on a list page (not taken) and an active professor with an old first degree (not moved); a rerank of a search stored with version-1 chips is unchanged; on a copy of the owner's data the job finds the death lines the research counted and the Washington search shows nobody with a death line in its open list.

Not in this slice: Wikidata, any web lookup, the page markup of the new lines.

### Slice e1: the lookup step (E1 to E4)

A new module `deepen.py` owns which people get a lookup and what is looked up. The step runs after the first ranking and save, before the fit check, and the search ranks and saves again after it.

Who (E1): the first 20 people of the open match tiers who miss a fact that can change their rank: the place when a place was asked, a known job, or any dated fact from the last five years. Then, among the first 10 people shown, those without contact details. Nobody is looked up twice in 90 days; each lookup is stored per person with its date and outcome (what was added, nothing new, not sure it is the same person, failed).

How (E2): one model call per person with web search, at most two searches, no page opened (task `lookup`). A live trial on eight stored people took 14 to 26 s and 1.3 to 2.5 cents each and found an employer page for seven; its prompt is kept with the round's working files and is used word for word. The model returns up to two pages, each marked as an employer page, the person's own page, or another page, and a year of death when a result states one. FN reads the pages itself. The page reader writes a link's mail or phone target after the link's text when the text does not show it. A second extraction task, `extract_person`, is built like `extract_leads` from the `extract` prompt plus one paragraph, with its own answer shape: it reports the named person only, with an email address and a phone number as the page prints them, and a year of death when the page states one.

What is attached (E3, E4): facts from a page are attached to the stored person only when the page names the person and states a second fact FN already holds about them: an employer, a place of study, a fellowship or a stored identifier. Code checks this. Otherwise nothing is attached and the outcome is "not sure". An email address or phone number is stored only from an employer page or an own professional page. At most 10 lookups run at once.

The step makes no call for a search with version-1 chips, when nobody qualifies, and on a rerank of a stored search. A step that fails leaves the first ranking.

Done when: tests with stub answers show who is chosen and the caps, the 90-day rule, the identity rule both ways (a namesake's page changes nothing), the contact rule both ways, the stored outcome, a failed lookup beside good ones, and that the `extract` task's prompt hash is unchanged.

Not in this slice: the "Look up more" button, a refresh from OpenAlex by identifier, Wikidata, the enrich job's reserve (D4), any page markup.

### Slice u2a: the pages that need no new data (N7 and the groups)

Built from version 13 of the design system, whose stylesheet replaces `fn.css` byte for byte and whose string list replaces the repository's copy: the line under the search box that shows how FN read the question; the "Set aside" line with its closed groups, their counts and the card line that names the fact; the count line; the notice when nobody matches every required wish; the walk line on the person page that stays inside the open list or inside one group.

### Slice u2b: the pages for deaths, age and lookups

After slices a1 and e1: the group "People who have died" with its card line, the card line for an old first record, the status words while a lookup runs, the contact section and the lookup line on the person page, and the "Look up more" button with its states.

### Slice o1: a stored index of researchers in the US with a Belgian affiliation (D2, D3)

A new job fetches every OpenAlex author with `last_known_institutions.country_code:US` and `affiliations.institution.country_code:BE`, with cursor paging, and stores each one the way the OpenAlex lane stores an author it found: the record as a source, the affiliations with their years, the last known institution with its place. It also stores what the lane does not have for such a person: the author's main topics as topic claims, and the last year with works. The job can be stopped and rerun, and it stops when OpenAlex's remaining daily credits fall under the reserve (D4). An author with more than 1,000 works is left out: such records are merged namesakes.

The stored-lists lane already searches stored OpenAlex records when the question asks for research. With a required place (`parse.place_must`, added by slice r1; until it merges, plan against a local helper of the same meaning and say so) it starts from the people inside the area: those who match the words first, then the others inside the area, then word matches elsewhere, within the lane's cap.

Done when: tests with recorded OpenAlex pages show an author is stored once, a rerun adds nothing, the reserve stops the job, an author with too many works is skipped; a test shows that with a required place a stored researcher inside the area without any word of the question is a hit, ahead of a word match outside it; a search stored with version-1 chips gets the same lane output as before.

Not in this slice: a live OpenAlex query by area and topic for questions without a tie, any lookup of a role, any model call.

### Slice o2: researchers by place and topic, without a tie (D5)

In `lanes/openalex.py` the topic query today reads `works?search=<topic>&filter=institutions.country_code:BE`. When the place is required, the question wants research and the tie is not required, the lane adds one more query per topic chip: works on the topic from the last six years whose authors' institutions include one inside the area. It takes the authors who are listed at an inside institution on that work, and they go through the lane as its other authors do. The institutions are FN's stored organizations with coordinates inside the question's area, at most 100, those with the most stored people first; with none, the lane notes it and makes no such query. With a required tie the lane makes no such query: the stored index covers those people.

The ranker already lets up to 20 people without Belgian evidence back in when they match the topic, are not abroad and the tie is not required. The plan checks that this holds for a question without any tie chip and says what a card of such a person shows.

Done when: tests with made-up OpenAlex answers show the extra query is sent only under the three conditions, uses the inside institutions, keeps only authors listed at one of them, and that such an author without any Belgian record reaches the kept candidates of a question without a tie; the lane's output for a question with a required tie, without a place, or with version-1 chips is as before.

Not in this slice: a query by role alone, any change to the ranker's caps, any model call.

### Slice d3: link employers during the search (D6)

`orgs.match` today takes every unlinked employer claim in the store. It gains two inputs: the persons whose claims to take, and the most new names to ask. `search.finish` runs it as a step before the first resolve and rank, for the persons the lanes hit, with a limit of 40 new names. A stored answer is reused without a call. A failure of the step, also a refusal by ROR, leaves the search going: the people keep an unknown place. The batch job `fn-orgs --match` keeps its behaviour.

Done when: tests show the step links a fresh hit's employer so the first ranking already knows the place; a name asked before makes no call; the limit holds; a failing ROR call leaves the search done; a rerank of a stored search makes no call; a search without an HTTP client skips the step.

Not in this slice: any change to the name check, linking during a publish.

### Slice e3: the lookup starts while the lanes run (S8)

`search.run` starts the lookup step on its own thread once the stored-lists lane has been published, with the ranking saved at that moment, and collects it with the lanes. `search.finish` then runs the step once more for people who have no stored lookup yet, with what is left of the 20. Each pass keeps its own step row. A pass that raises leaves the search going. A rerank of a stored search makes no lookup.

Done when: a test with sleeping stubs shows the first pass overlaps the lanes; the two passes together make at most 20 lookups for people with a gap; a person looked up in the first pass is not looked up in the second; the claims of the first pass are in the ranking after the lanes.

Not in this slice: any change to who qualifies or to what a lookup stores.

## What is left

- Five benchmark questions find nobody invitable in the first ten (named under the measurements).
- Several university sites refuse FN's page reader behind a bot check. FN respects that, so a person whose only pages are on such a site keeps a thin card.
- FN does not read PDF files, and many CVs are PDFs. Reading them needs a PDF library, which is a new dependency for the owner to approve.
- A death is taken when a relative with the same surname and a lifespan stands in the person's own sentence, and on a page where FN located only one of two neighbours the surname is the only guard.
- A looked-up page that writes a name in another order than FN holds it ends as "not sure".
- The lookup runs beside the lanes but still ends after them; a search takes 130 to 150 s. The next step would be to end the search when the lanes end and let the lookups update the list afterwards.
- The web lane takes 65 to 90 s per search and needs the Parallel key. In the judged runs of round two it alone gave 2 of 23 invitable people. Whether to switch it off by default is the owner's call; the deployment plan assumes it is off.
- Counts outside the results page (the searches list, the export, the gold report) still count people set aside.
