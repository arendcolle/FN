# Panel records, round three

One panel of three judges voted on fourteen decisions in three rounds: the organizer, a search engineer and a data steward. Each judge voted alone first, then saw the others' reasons. The brief they read is summarized in [design.md](design.md); the options are in the round's working files. Below: the winning option, whether the vote was unanimous, and each judge's final reason.

## N1. When is a place required

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. parse.md:13 made "in the Washington D.C. area" nice, which put 75 people known elsewhere under the first heading (diag-rank section 1). The venue exception keeps the two midterms Washington analysts that BQ-01 accepts, and diag-rank 7(b) shows option b drops them.
- **search-engineer**, option a: Keep. parse.md:13 made "in the Washington D.C. area" nice, and that put 75 people known elsewhere under the first heading (diag-rank section 1). The venue exception keeps the two midterms Washington analysts that BQ-01 accepts, which option b would drop (diag-rank 7b). The rule fits in one sentence and parse eval rows can test it.
- **data-steward**, option a: Unchanged. diag-rank section 1 traces the D.C. failure to parse.md:13, which made "in the Washington D.C. area" nice although it describes the people the same way "Belgian" does. The venue exception keeps the two Washington analysts in the midterms search that BQ-01 accepts, and diag-rank 7(b) shows option b would drop them.

## N2. Required place, person in the US outside the area

Winner: option b, unanimous.

- **organizer**, option b: Unchanged and unanimous. A closed group named after its reason keeps the 16 outside people one click away and shares one pattern with "Other people found", abroad and died. Place data is weak (19 of 23 unknowns lack only an org link, diag-rank section 3), so the card must show the place fact and its source that set the person aside.
- **search-engineer**, option b: Keep. A closed group named after the failed must uses the same mechanism as "Other people found" and the died group. It matches the met/not-met grading in web-ir.md. The D.C. first 50 lose all 16 outside people, and those people stay one click away.
- **data-steward**, option b: Unchanged since round 2. A closed group named after its reason keeps the person one click away and works the same way as "Other people found". A place fact can be stale or attached to the wrong person, so the card has to show the fact that put them there. rank.exempt (rank.py:284-291) must not bring them back.

## N3. Person outside the US, question names a US place

Winner: option b, unanimous.

- **organizer**, option b: Unchanged and now unanimous. The owner's own case is a New York venue question (a nice place), and he would never email a scientist in Amsterdam (brief.md:11). Midterms holds only 1 abroad person in positions 51 to 86 (diag-rank 7d), and the closed group keeps everyone abroad reachable. I endorse the search-engineer's wording because it states that questions without a place keep abroad people as today.
- **search-engineer**, option b: Keep. The owner's own case is a nice venue place (New York), and he would never email a scientist in Amsterdam (brief.md). Midterms holds only 1 abroad person in positions 51 to 86 (diag-rank 7d), so recall barely drops. Being abroad is a sourced fact.
- **data-steward**, option b: Unchanged. The owner's own case is a New York venue question, so the place is nice, and he would never email a scientist in Amsterdam (brief.md:11). Being abroad is a sourced fact, not thin evidence, and the closed group keeps everyone reachable. The scope must stay limited to questions that name a US place.

## N4. Required place, place unknown

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. Option b would hide 38 of the D.C. first 50 (diag-rank combined table: 12 inside, 38 unknown). Under a the 6 known inside people stand at positions 1 to 6 and the card says the place is unknown, and the org-link fix (evidence.py:123-127) settles most unknowns.
- **search-engineer**, option a: Keep. Option b would hide 38 of the D.C. first 50, which hold 12 inside people and 38 unknown after the rules (diag-rank section 7). Under a, the 6 known inside people take positions 1 to 6. 19 of the 23 unknowns lack only an org link (evidence.py:123-127), so fixing that data settles most of them.
- **data-steward**, option a: Unchanged and unanimous. 19 of the 23 tier-1 people with an unknown place lack one only because their employer claim has no org link (diag-rank section 3, evidence.py:123-127). Hiding them would hide people on missing data, and today's FITS rule (rank.py:33) lets them outrank known D.C. people.

## N5. Wished place, order inside a tier

Winner: option b, unanimous.

- **organizer**, option b: Unchanged and unanimous. Today tie grade sorts before place (rank.py:237-238), so unknown-place people fill positions 4 to 18 ahead of a known Baltimore match. For a talk I would ask the local person first, and in midterms the first unknown only moves from position 2 to 5.
- **search-engineer**, option b: Keep. Today tie grade sorts before place (rank.py:237-238), so a nice place has no effect on order. Option b gives a wish real ranking weight. In midterms it only moves the first unknown from position 2 to 5 (diag-rank 7c).
- **data-steward**, option b: Unchanged and unanimous. A place known to fit is a sourced fact and should sort before an unknown place. Today tie grade sorts before place (rank.py:237-238), which puts unknown-place people at positions 4 to 18 above a known Baltimore match at 19 (diag-rank section 3). In midterms the cost is small: the first unknown moves from position 2 to 5.

## N6. How much the list shows

Winner: option d, by majority.

- **organizer**, option a: I keep a. The cap in d runs after order_key, so every one of those rows is already fetched and scored; the cut saves nothing on cost and only removes people. The closed group already answers the owner's "they only look at the first 50": the open list holds the match tiers (62 of 342 in the D.C. simulation, diag-rank section 1), and nothing in the tail costs me scrolling.
- **search-engineer**, option d: Keep, with less at stake than last round. N3 b moves people abroad into their own group, so most of the 238 D.C. "Other people found" (201 abroad) leave it, and the cap of 50 binds only on vague queries. The match headings stay uncapped, and midterms positions 51 to 86 are all tier 6 or 7 (diag-rank 7d). The organizer's worry about A2 people does not apply under my A2 vote, which keeps them in their tier.
- **data-steward**, option d: I keep d. The organizer is right that a cap drops people for good, but it only touches the remainder that has no confirmed topic or role: D.C. held 238 people there, 201 of them abroad, and midterms positions 51 to 86 are all tier 6 or 7 (diag-rank 7(d)). From my lens, holding hundreds of weakly evidenced rows about real people has its own cost, and storing the cut reason over_cap keeps the cut auditable.

## N7. Showing how FN read the question

Winner: option a, by majority.

- **organizer**, option a: Unchanged. The D.C. failure came from a reading nobody could see (place parsed as nice, diag-rank section 1), and must or nice now decides who is set aside. Flipping on the page reruns a 272 to 294 s search (diag-speed), no better than asking again.
- **search-engineer**, option a: The must/nice reading now decides who goes into the closed groups. The D.C. failure came from a reading the owner could not see (diag-rank section 1). One line costs nothing and can be tested against the parsed chips. Flipping a reading on the page reruns a 272 to 294 s search (diag-speed.md), which gains nothing over asking again.

## A1. A source says the person died

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. Two men who died in 1966 and 1922 stood in the D.C. first 50 (diag-age section 6). The 400-character window misattributed 2 of 10 deaths, so death needs entry-bounded attribution or P570 plus a second fact, and the hidden card shows the source quote.
- **search-engineer**, option a: Keep. Two people who died in 1966 and 1922 stood in the D.C. first 50 (diag-age section 6). The 400-character window gave 2 of 10 deaths to the wrong person, so the rule is safe only with attribution bounded to the person's own entry and with the source quote on the card. The data-steward's closed group makes it the same pattern as N2.
- **data-steward**, option a: Unchanged and unanimous. A person whose death a source states cannot be invited, and two stood in the D.C. first 50. The 400-character window gave 2 of 10 deaths to the wrong person (diag-age section 6, rank 26 is alive), so the rule is only safe with entry-bounded attribution and the source quote on the card.

## A2. First dated fact 60 years back, nothing recent

Winner: option b, by majority.

- **organizer**, option a: I keep a. diag-age section 8 finds the D class (first fact 1963 or earlier) right 2 of 2 times, both dead, and section 11 supports a rank-group move for D only; the 11 contradicted people are R-class professors, which A2 does not touch. The 115 namesake cases all hold recent OpenAlex years, and my amendment keeps them in their tier. Under my N6 vote nobody in "Other people found" is dropped. Amendment: Two or more OpenAlex years in the last ten years, or a role dated by record_field, page_date or sitemap (never read_date), count as recent and keep the person in their tier. Compute the first year without born_in and with the lone-leading-year gap fix (diag-age 7.2), and show "First record 1958, nothing recent" on the card.
- **search-engineer**, option b: Keep. Two of 2 correct D-class cases is too small a sample. In diag-age section 8, 115 of 129 contradictions are namesake merges or bad OpenAlex years, so the organizer's override on OpenAlex years leans on the least reliable signal. Sorting last in the tier costs nothing when the estimate is wrong, and it touches about 1 of the D.C. first 50 because only 13 have a dated fact.
- **data-steward**, option b: I keep b. The organizer's override with recent OpenAlex years helps, but diag-age section 8 shows those same years are unreliable: 115 of 129 contradictions are namesake merges or bad OpenAlex years, and 11 of 22 people touched are active professors. The organizer's D class was right 2 of 2 times, which is too small a sample. With N6 capping "Other people found", a move could drop a living person, while sorting last in the tier costs nothing when the estimate is wrong.

## A3. Emeritus or retired-looking

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. Emeritus is a direct signal (57 claims, 4 of 4 checked correct, diag-age section 8), and an emeritus professor can still be a good speaker, so sorting after active people is the right strength. The 45-year path was wrong for 11 of 22, so only source-dated roles or recent OpenAlex years may override it.
- **search-engineer**, option a: Keep. Emeritus is a direct marker in 57 claims, and 4 of 4 checked emeritus people were classed correctly (diag-age section 8). The 45-year path was wrong for 11 of 22 people, so it may only reorder, and a role dated by its source overrides it.
- **data-steward**, option a: Unchanged and unanimous. Emeritus is a direct sourced marker (57 claims, and 4 of 4 checked people were correct, diag-age 7.3 and section 8). The 45-year estimate was wrong for 11 of 22 people, which is acceptable only because option a just reorders and a source-dated role overrides it.

## E1. Who gets a lookup

Winner: option d, unanimous.

- **organizer**, option d: Unchanged and unanimous. Head lookups cost about 40 to 60 s for 20 people (diag-speed) and fill the cards I decide on: only 29 of the first 50 show a place and none an email (diag-enrich section 6). The button covers the good person on page 12 without paying for 300 lookups.
- **search-engineer**, option d: Keep. Head-only lookups, run only where the answer can change the rank, follow the Clay and Exa pattern (web-ir.md). They cost about 40 to 60 s for 20 people (diag-speed.md). The button covers the good person on page 12 at a cost the user chooses, and a stored "not sure" outcome stops repeat lookups.
- **data-steward**, option d: Unchanged and unanimous. Looking up only the first 20 people, and only facts that can change their rank, keeps the cost to about 40 to 60 s (diag-speed). Contact lookups only for the first 10 keep personal details to the people he is likely to contact, and the button covers a good person further down the list.

## E2. How a lookup finds facts

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. 21,476 persons have an OpenAlex id and 16,878 an ORCID (diag-enrich), and a batch of 100 by id costs $0.10 per 1,000 calls with no name matching (web-facts A). The owner will not raise the Parallel limits; last_known_institutions must be gated by recent works before it counts as a current place.
- **search-engineer**, option a: Keep. 21,476 persons have an OpenAlex id and 16,878 an ORCID (diag-enrich.md). A batch call fetches 100 of them at $0.10 per 1,000 calls (web-facts A), with no name matching. The owner will not raise the Parallel limits. last_known_institutions must be gated on recent works before it counts as a current place.
- **data-steward**, option a: Unchanged and unanimous. An OpenAlex record fetched by its stored id or ORCID needs no name matching, so it cannot attach a namesake's facts. Stored ids cover 21,476 persons, and a batch call costs $0.10 per 1,000 (web-facts A). last_known_institutions should count as a current place only when recent works back it.

## E3. When a looked-up fact is attached

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. Namesake merges already gave old BAEF names modern OpenAlex years (diag-age section 8), so a name match or the model's verdict attaches wrong facts. A second held fact checked by code is required, and "same field" is too broad to count as one.
- **search-engineer**, option a: Keep. Namesake merges already gave old BAEF names modern OpenAlex years (diag-age section 8), and web-facts B requires a second matching fact. Drop "same field" as a second fact: it is too broad to tell two people with a common name apart. An employer, a place of study, a fellowship or an identifier can be checked in code. Amendment: Remove "the same field" from the accepted second facts. Count only an employer, a place of study, a fellowship or a stored identifier.
- **data-steward**, option a: Unchanged and unanimous. Namesake merges already gave old BAEF names modern OpenAlex years (diag-age section 8), so a name match or the finding model's own verdict is how wrong facts get attached. The second fact must be checked by code, and "the same field" is too broad to count as one.

## E4. Contact details

Winner: option a, unanimous.

- **organizer**, option a: Unchanged and unanimous. The database holds 0 email and 0 phone claims (diag-enrich section 5), and a missing email blocked the owner's best hit. The reader drops mailto links and footers today (pageread.py:23), so it must keep them or a finds nothing.
- **search-engineer**, option a: Keep. The database holds 0 email and 0 phone claims (diag-enrich section 5). Limiting collection to employer or professional pages, with the source stored, keeps it to work contacts published for contact. Without a reader fix at pageread.py:23, which drops mailto links and footers today, nothing will be found.
- **data-steward**, option a: Unchanged and unanimous. The database holds 0 email and 0 phone claims (diag-enrich section 5). A work contact printed on an employer or professional page is published so people can make contact, while any public page (b) would pull personal addresses from aggregators. The reader drops mailto links today (pageread.py:23) and has to keep them, or nothing will be found.

## Amendments in the final round

- A2/organizer (option a, endorsed by 1): Two or more OpenAlex years in the last ten years, or a role dated by record_field, page_date or sitemap (never read_date), count as recent and keep the person in their tier. Compute the first year without born_in and with the lone-leading-year gap fix (diag-age 7.2), and show "First record 1958, nothing recent" on the card.
- E3/search-engineer (option a, endorsed by 0): Remove "the same field" from the accepted second facts. Count only an employer, a place of study, a fellowship or a stored identifier.
