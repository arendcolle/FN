# Progress log, round three

One line per finished step, newest last. Times are local.

## 17 November 2026

- Read the owner's Washington search: 272 s, 342 people kept, place parsed as a wish, 75 people known elsewhere under the first heading.
- Research by nine agents: ranking noise, speed, age signals, enrichment, industry practice, OpenAlex and death facts, and three notes for the deployment plan. The notes that quote real people stay outside git.
- Benchmark grown from 14 to 20 questions. The six new ones are short, as the owner types them: three for development, three held back.
- Baseline of the six new questions on main (run c0), three judges and an arbiter: 4 invitable people in the 60 first-ten cards; 85 of the 120 first-twenty cards are noise (wrong field, wrong place or gone).
- Panel of three judges ruled on fourteen decisions in three rounds: N1 to N7, A1 to A3, E1 to E4 in `design.md`. The lead added N8, N9 and four readings.
- Plans written and reviewed for slices s1, s2, d1, u1 and r1; all approved after one or two review rounds.
- Experiment: three new web research angles (staff pages, staff pages with a Belgian tie, CVs with a Belgian tie) on six questions found 0 to 1 person each, 10 calls. Angle wording is not the lever.
- Measured with one call each: OpenAlex lists 31,921 authors now in the US with a Belgian affiliation in their history, 452 of them at the NIH and 574 at four Houston medical institutions. A list call costs 1 of 10,000 daily credits, a name search 10. This became decisions D2 to D4 and slice o1.
- Design system version 13 drafted and reviewed by three lenses over two rounds; the lead corrected three points (a required tie reads as required, the count includes network people, an old record sorts last under its heading).
- Slices u1, s1 and d1 built, reviewed and merged (PRs 72, 73, 74). Live check of s1 on four stored pages: one page went from 9 people and 35 s to 3 people and 10 s with the same facts for the lead; one list page still returned 18 people for one lead, which the lane's filter then drops.
- Slices s2 and r1 stopped on existing tests the plans had not listed. Rulings: the stored-lists lane runs first and alone (beside the others it sometimes found people another lane had just saved, so two runs differed); the gold report lists lane steps in lane order; the pinned candidates column list gains `aside`. Both restarted.
- Design system version 13 published.
- The deployment, access and pricing plan was drafted, attacked from three lenses plus a fact check, and revised twice (24 findings in the second look, all fixed). It is kept outside git.
- Experiment for the lookup step: one model call with web search per person, at most two searches, no page opened, on eight stored people of the Washington search whose place is unknown. All eight answered in 14 to 26 s (26 s for the eight side by side), 7,000 to 11,500 input tokens and 1.3 to 2.5 cents each, and seven got a page of their employer. This is the page finder of decision E2.
- Slices r1 and s2 built, reviewed and merged (PRs 75, 76), then o1 (PR 77). The rebases needed three fixes by the lead: the pinned migration lists hold both 13 and 14, one migration test starts from 013, and the stored-lists lane uses the parser's `place_must`.
- Live timing on main after s1, s2 and r1, two questions run side by side: the Washington question 119 s (was 247 s), the New York question 127 s (was 272 s). The web lane (85 to 92 s) and the web research lane (96 to 106 s) now overlap.
- The Washington question after r1: the place parses as required, 125 people open instead of 356 kept, the first ten cards all in the area; 124 people stand aside as outside the US and 106 as outside the area.
- Live run of the employer-linking job on a copy: 1,897 names asked, 683 chosen by ROR, 1,009 claims linked, no failure. A sample of every tenth match showed about one wrong link in ten. A stricter rule (the organization's name must stand in the employer text) keeps 483 of the 683 and none of the wrong ones in the sample; this became slice d2.
- The New York political scientists question after r1: four people in the match tiers. The OpenAlex lane only searches works with a Belgian institution, so its people are in Belgium and now stand aside. This became decision D5 and slice o2.
- Experiment on the web research prompt: the researcher reports people from search results without opening pages, since FN opens the pages itself. Ten calls on two questions: 26 to 39 s each (was 51 to 94 s), 24,000 to 41,000 input tokens (was 58,000 to 153,000), and 20 leads where the current prompt gave 8.
- Slice d2 (the stricter match rule) merged (PR 78), then the search-only web research (PR 79, decision S7), changed by the lead: one prompt, one tool list, one timeout, two tests.
- The index job ran live on a copy: 320 pages in 6 min 53 s, 9,434 authors stored (8,891 new), 22,487 skipped for too many works or under two Belgian years. The database went from 1.2 to 1.6 GB.
- Where invitable people came from in the judged runs: of 23 in the first tens of the 14 older questions, 15 came from the web research lane alone, 4 from it together with the web lane, 2 from the web lane alone, 1 from stored lists. The web lane takes 65 to 92 s per search and needs the Parallel key.
- Slice o2 merged (PR 80). Live on the New York political scientists question, on a copy with the index: the area query went to 100 institutions and the first ten cards are New York political scientists, eight from the web research, where the baseline opened with eight professors in Belgium.
- The employer-linking job with the stricter rule, live on the copy with the index: 1,897 names asked, 625 chosen, 936 claims linked.
- More model calls side by side (PR 81): 97 s and 116 s for the two questions.
- Several university sites answer FN's page reader with 403 behind a bot check (seen on four hosts in one search). FN respects that and drops a lead whose pages it cannot read.
- Slices d3 (PR 82), a1 (PR 83) and u2a (PR 84) merged. The lead merged a1 and u2a by hand where both changed the presentation module: the died group joined the set-aside groups, and two tests of a1 were adapted to the closed groups. On the real page the no-match line showed for a question that asks for no tie; fixed in the same PR with a test.
- Employer linking inside a live search: 5 s, 40 names asked, 19 chosen, 43 claims linked; seven of the eleven people the web research found for the New York question got a place inside the area.
- The deaths job on the copy with the index: 15 death claims on 1,015 pages.
- Slice e1 (the lookup step) built and reviewed. Lead fixes before merge: a refused page (4xx, a refused redirect) is not retried, the stored outcome holds no unverified year of death and no address given as a page, a middle name on one side still counts as the same person, and employers a lookup finds are linked before the next ranking.
- The lookup step live on two questions: 30 and 20 lookups, 14 and 7 people with new facts, 206 and 81 claims added (25 and 10 roles, 17 and 10 current employers), 127 s and 81 s, about 70 and 41 cents of subscription-equivalent cost. It stored no email: the model returned an address for one page in six. This became task e1b (contact details by rule) and decision S8 (the lookup runs beside the lanes).
- The contact rule (task e1b) replaced the model's email and phone fields: on the pages two live lookups read, 11 of 18 people with a confirmed employer or own page get an email and 10 a phone. The lookup step merged with it (PR 85).
- Full benchmark on main with the lookup after the lanes (run c7), 20 questions on a copy with the index, the employer links and the death claims. All 20 searches ended done; 190 s on average, 132 to 245 s.
- Run c7 judged by three judges and an arbiter. Invitable people in the first tens: 34 of 130 on the development questions (22 before) and 14 of 70 on the held-back questions (5 before). In the first twenties: 45 and 19 (25 and 5 before). Questions with nobody invitable in the first ten: 7 of 20 (8 before). Of the 387 first-twenty cards, 213 scored 0 or 1 on topic, 24 state a place outside the area and 6 are gone.
- First-ten cards with a role, an employer and a place: 40% (30% before); with a place: 68% (48%). 24 of the 200 first-ten people have an email or phone stored (none before).
- The Houston energy question fell from 3 to 0 in its first ten: eight people known from one paper each, found by the new place-and-topic query, stand ahead of the people the web research found. This became task f2.
- Experiment F1 on recorded answers (run c8): the fit check read up to 120 people per question and set aside 2 to 80 more of them as other roles or topics; the first ten changed in 11 of 20 questions.
- Run c9: the 20 recorded searches reranked with F1 and F2 and judged again. Development questions 34 to 43 invitable people in the first tens, held-back questions 14 to 13, questions without anyone invitable in the first ten 7 to 5. Both kept (PR 87).
- Slice e3 merged (PR 86): the lookup starts when the stored-lists lane is published. Live, the pass shared model capacity with the lanes and ran until second 154 and 171, so the two searches took 174 s and 212 s.
- Lighter lookups (PR 89, by the lead): 12 people per search and one model call per page. Live: 145 s and 128 s, first cards after 20 and 24 s.
- Slice u2b merged (PR 88) after a hand merge with e3 in the lookup module.
- All 18 pull requests of the round (72 to 89) are on main; the suite has 1,096 tests and is green.

## Review ledger

Each build ran an Opus review loop; every slice ended with no blocker or should open. Findings the lead acted on after the last review round:

| Slice | Finding | Outcome |
| --- | --- | --- |
| d1 | About one ROR match in ten was wrong in a live sample | fixed in d2: the organization's name must stand in the employer text |
| d2 | A one-word employer text such as "University" stands inside many names | fixed before merge |
| e1 | A refused page (4xx, a refused redirect) was retried at every search | fixed before merge |
| e1 | The stored outcome held a year of death no identity check had passed, and could hold an address given as a page | fixed before merge |
| e1 | A middle name on one side made the page "not sure" | fixed before merge for the lookup step |
| e1 | The model returned an email for one page in six | replaced by a rule in e1b |
| e3 | The lookup pass did not get shorter beside the lanes | followed by the lighter settings |
| u2a | The no-match line showed for a question that asks for no tie | fixed before merge, with a test |
| a1 | A relative's lifespan in the person's own sentence counts as the person's | left as a known limit |
| e3 | A first pass that raises before it stores a row lets the second pass spend the full limit again | left as a known limit |
