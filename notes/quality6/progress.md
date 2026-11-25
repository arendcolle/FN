# Progress log, round six

One line per finished step, newest last.

## 25 November 2026

- The owner asked whether a paid Apify plan is worth $19 a month. Read Apify's plans and swept twelve categories of its store. The paid plan unlocks one thing FN lacks on the free plan: the strict LinkedIn search, which allows a free account ten runs in total.
- Tested two cheaper LinkedIn scrapers on "journalists in New York with a Belgian school". One returned six journalists without a Belgian school, the other three people who live in Belgium.
- A Google search limited to LinkedIn profiles returned ten profiles for $0.001 in about 5 s. Parallel, the search service FN's web lanes use, returned profiles that met half the question, and read a whole profile for $0.001.
- The owner decided to stay on the free plan and asked for the route: Google finds, Parallel reads.
- Measured the route on the five benchmark questions without an invitable person, three queries and 20 profiles each: 33 of 89 profiles read are in the area with a Belgian school, 23 have a Belgian school elsewhere in the US and 33 have none. A reading limit of 12,000 characters cut the schools off half the profiles; 40,000 keeps them.
- A panel of three ruled on three decisions (`panel-records.md`): a parser makes the claims, the route is a second route of the `linkedin` lane, and the lane keeps a profile only when its education names a Belgian school.
- Scored the five questions on main with three judges: nobody invitable in the first ten cards for four of them, two people for the food traders in Chicago.
- Slice m1 planned by an Opus planner and approved by an Opus reviewer in two rounds. The first round found that a version-2 question without a role chip would have sent a query with an empty role part.
- Slice m1 built by a Sonnet builder and approved by an Opus reviewer in one round: 16 new tests, two approved changes to existing tests.
- First live run on a copy of the database: the route ran in all five searches, but 3 of 13 Google calls came back with other websites instead of profiles. The lead added one more ask for such an answer, with the site limit at the end of the query. A check of eight calls showed one of them losing the limit.
- A panel of three reviewed the whole diff and approved it. Two notes were taken: a profile with an empty headline line no longer gets its summary as the headline, and the query test covers an institution that is no school.

## 26 November 2026

- The judges' scores showed one profile stored as two person records, one from the web lane and one from this lane, with half the facts on the person's page. The LinkedIn lane now lands on the web lane's record for the same profile. An Opus reviewer approved that change.
- Scored the five questions with three judges: 2 invitable people in the first ten cards before, 6 after.
- Merged as pull request 112: three commits, 1,232 tests pass on main.
- A new search through the staff page of a copy server ran the route without any switch: 25 s for the lane, one query asked again, 20 profiles read, 15 kept.
