# Could FN find LinkedIn people on Apify's free plan?

Round six, 25 and 26 November 2026. The votes are in [panel-records.md](panel-records.md), the steps in [progress.md](progress.md) and the slice's task in [tasks/m1-linkedin-through-google.md](tasks/m1-linkedin-through-google.md).

## TL;DR

The LinkedIn lane needed a paid Apify plan, so it found nobody. The owner chose to stay on the free plan. The lane now has a second route for that case: a Google search limited to LinkedIn profile addresses finds people, Parallel reads each profile and a parser makes the claims. On five benchmark questions the invitable people in the first ten cards went from 2 to 6. The route adds about $0.02 and 6 to 32 s to a search.

## What the owner asked and decided

The owner asked whether Apify's $19 plan is worth its price. It unlocks one thing FN lacks on the free plan: the strict LinkedIn search of round five, which allows a free account ten runs in total. Two cheaper LinkedIn scrapers returned the wrong people. A Google search limited to `www.linkedin.com/in` returned ten profiles for $0.001 in about 5 s, and Parallel read a whole profile for $0.001. The owner decided to stay on the free plan and asked for that route.

## Measured before

Three queries a question and the first 20 distinct profiles read, counted from the profile text:

| Question | Read | In the area with a Belgian school | Belgian school, elsewhere in the US | No Belgian school |
| --- | --- | --- | --- | --- |
| Journalists or editors in New York | 20 | 13 | 2 | 5 |
| Investors or business developers in Boston | 20 | 8 | 1 | 11 |
| Importers or traders in Chicago | 20 | 4 | 10 | 6 |
| Architects or designers in Los Angeles | 20 | 5 | 7 | 8 |
| Economists in Chicago, KU Leuven | 9 | 3 | 3 | 3 |

On main, three judges found nobody invitable in the first ten cards for four of these questions and two people for the traders in Chicago.

## Decisions

| Id | Decision | Why |
| --- | --- | --- |
| M1 | The route is a second route of the `linkedin` lane. The strict scraper runs on a paid plan with budget, the Google route when the scraper may not pay. | Panel, 2 to 1, then 3 to 0. A seventh lane would give one person two score parts on a paid plan. |
| M2 | A parser turns Parallel's labelled profile text into the fields the strict route already makes claims from. No model call. | Panel, 3 to 0. FN's page reader made a `studied_at` claim on 16 of 62 stored profiles that list a school, and on 12 of 94 pages it gave claims to several people. |
| M3 | A profile is kept only when its education names a Belgian school. The others leave a trace row without a name or address. | Panel, 3 to 0. Google cannot filter on school, and 33 of 89 measured profiles had none. |
| M4 | Google goes through the scraper `scraperlink/google-search-results-serp-scraper`. | It took 15 s for three queries at $0.001 each. Apify's own scraper took 57 s at $0.0045 a page. |
| M5 | A query is `site:www.linkedin.com/in`, up to three role words, LinkedIn's area name and "City, State" in quotes, and three schools. | Without `www` four or five of ten results lived in Belgium. A bare city name matched profiles that only mention the city. Five schools in one query returned no profile. |
| M6 | One Parallel call reads the first 20 distinct addresses, up to 40,000 characters each. | The schools come last in a profile. A limit of 12,000 showed a Belgian school on 5 of 10 profiles, 40,000 on 8. |
| M7 | An answer where under half the results are profile addresses is asked once more, with the site limit at the end of the query. | In the first live run 3 of 13 Google calls came back with other websites. The second wording has its own recording, so a replay serves both. |
| M8 | Off the staff server the route serves recorded answers only. No recording for the first query means the lane is off. A recording for the first and none for a later call is a fault, and `fn-score` counts it as one. | Before, `fn-score` skipped every missing recording of this lane. |
| M9 | The lane resolves a person with the profile address and with the identifiers the web lane gives the owner of a profile page. | One profile read by both lanes was two person records, and the page showed the facts of one. |
| M10 | The Google route makes no account call. Each Google call has a charge limit of $0.05. | A free Apify account is blocked once its $5 is used, so it cannot be overdrawn. |

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which route runs, and whether a call may go out | `linkedin.run`, `linkedin.may_run_live`, `linkedin.check_account` |
| The route's steps, notes and trace rows | `linkedin.google_route` |
| Query text and area names | `linkedin.google_queries`, `linkedin.PLACES` |
| The Google call, its price and its caching | `linkedin.search_google` |
| Profile addresses and their order | `linkedin.profile_address`, `linkedin.addresses` |
| The Extract call | `websearch.extract_pages` |
| Profile text to fields | `linkedin.read_profile` |
| Which profiles are kept | `linkedin.belgian_school` |
| Sources, identifiers and claims | `linkedin.people` |
| Misses that are off by design | `linkedin.expected_misses`, read by `score.degraded` |

## Measured after

Five live searches on a copy of the owner's database, on main and on the branch, the first ten cards scored by three judges and an arbiter:

| Question | Invitable in the first ten, before | After |
| --- | --- | --- |
| Journalists or editors in New York who grew up in Belgium | 0 | 1 |
| Investors or business developers in Boston life sciences | 0 | 1 |
| Food and agriculture traders in Chicago | 2 | 2 |
| Flemish architects or designers in Los Angeles | 0 | 2 |
| Economists in Chicago with a KU Leuven degree | 0 | 0 |
| Total | 2 | 6 |

- The lane kept 13, 15, 2, 15 and 6 people in these searches and left out 7, 5, 18, 5 and 3 profiles, all but one for lack of a Belgian school.
- A search cost $0.010 to $0.024 for the route, and the lane took 6 to 32 s.
- A new search through the staff page of a copy server ("Belgian designers or architects in New York") was done in 114 s. The lane ran for 25 s, asked one query again, read 20 profiles and kept 15; six of them are among the first thirteen cards.
- Tests: 1,214 before, 1,232 after.

## What is left

- The strict scraper's replays of round five put 7 invitable people in the first ten for two of these questions; this route puts 1 and 2 there. Google matches a role word anywhere in a profile, so the economists question returned students and exchange years.
- A card that combines a seed-list record with a LinkedIn record opens the seed record's page. One journalist card was scored as not invitable because its job was not on that page.
- The HTTP cache and the recorded Extract request keep the text and the addresses of profiles the lane drops.
- A Belgian school outside the nine names is recognized only when FN has stored its organization as Belgian.
- One profile under two spellings of its address, in capitals or with encoded letters, is two records.
- A scraper answer without a results list reads in the trace as "no profile address".
- The Washington area name is located in Baltimore.
- The route depends on a community scraper and on the labels in Parallel's profile text.
