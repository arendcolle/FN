# Progress log, round four

One line per finished step, newest last.

## 24 November 2026

- The owner reported five things after a week of use: a lookup that drops pages, duplicate facts on a person page, contact details that can be typed for two fields and not a third, too many "same person?" questions with too much scrolling, and a deployment plan too long to read.
- Looked at the owner's own cases on a copy of the database. The owner's network export, imported again, asked 8 questions in 14 rows, each with identical details on both sides. The example person page showed 14 Work lines for about 7 facts.
- Research by five agents, each with a note kept outside git: where FN asks "the same person?" and how often, why a page repeats a fact, what staff can change by hand, what the deployment plan decides, and which lookup pages are dropped.
- Measured: 12 of 77 recorded lookup page readings were dropped only because the model's quote lacked the name, and all 12 are about the right person. 2,125 of 37,897 person pages show a fact twice. 605 of 6,703 result cards lead to a page that lists namesakes, 900 pairs.
- A panel of three ruled on four decisions in two rounds (D1 to D4 in `design.md`, votes in `panel-records.md`).
- Slice h1 planned, reviewed twice, built and reviewed: the lookup keeps a page that names the person next to the model's quote. The suite passes on the structural commit alone (1,127 tests) and on both (1,133). A replay of the 77 recordings moves exactly the 12 readings: 11 now count, one still fails the held-fact check on an employer's short name. Merged as pull request 98.
- Design system version 14 written, reviewed and published: the Compare part, read-only contact rows, folded fact lines and the changed import check page. The lead narrowed "Differs" to six rows (employer, place, email, phone, LinkedIn, ORCID) and dropped the "Added" row after seeing the previews.
- The deployment plan became a decision page and four short plans, scored by a council of two models over several rounds. Kept outside git.
- Slice h4a planned, reviewed twice, built and reviewed: an import recognizes a person by the `profile` column of an FN export. The owner's export, imported again on a copy: 14 rows recognized and no question (6 and 8 before), no new person and no new claim; with an email typed into one row, one new claim. On main the same file with the boxes left unticked made 8 second people. Merged as pull request 99.
- The whole suite on main failed twice under load (a load average near 30 from parallel agents): the new large-file import test asserted a wall-clock bound, and two older tests are timing-sensitive (`test_six_batches_run_on_three_workers`, and the progress check in `test_flows`, which passed three of three runs on its own before and after today's merges). The new test lost its clock (pull request 100). From then on a test may count work, never time it.

## 25 November 2026

- The style sheet of design system version 14 merged on its own (pull request 101), with the test that pins its hash.
- Slice h3 built and reviewed: contact details are read-only, with Email, Phone and LinkedIn rows, "Not correct" on email and phone, and typing gone with all that served it. On a copy: 16 email rows, 11 phone rows and 25 LinkedIn rows render, and a rerank of three stored searches gives the same order as main. Merged as pull request 102.
- Slice h2 built and reviewed in two rounds: the person page shows one line per fact. Lead rulings: a line without a stated role reads as the newer of its "Works at" and "Worked at" facts; the wordings of "Also described as" keep their Work order. The design system got version 14.1 to say the same. On the research snapshot none of the 1,681 pages that showed a line twice word for word still does; the example page goes from 14 Work lines to 9, from 3 places to 2, and its tie shows once. Merged as pull request 103.
- Slice h5 built and reviewed in two rounds: one Compare table for the import question, a possible match and a search result with a network namesake, and possible matches only on network people's pages. The lead's check on real data found a false "Differs" where one employer was written two ways, with the shared employer hidden behind "and 15 more". Fixed before the merge: one employer written two ways is the same, and a shared value is listed first. On a copy: no result card outside the network leads to a page with possible matches (605 before), and the 4 network people keep their 5 pairs. A last review of the hand fix found two more cases (a shared value dropped as a duplicate of an unshared one, and any text in brackets cut from an employer name), fixed with tests. Merged as pull request 104.
- All slices on main: 1,177 tests pass.
