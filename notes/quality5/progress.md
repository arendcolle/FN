# Progress log, round five

One line per finished step, newest last.

## 25 November 2026

- The owner picked five of the open follow-ups to do now: a budget for the LinkedIn lane, a subject that the parse step read as a tie, a search that ends sooner, lookups for the seed-list people with a daily cap, and Belgian employers as a tie.
- Read Apify's API for the account: $0.41 of $5.00 used, ten runs so far, all with the LinkedIn actor.
- Research by five readers, two of them checked by a second reader, each with a note kept outside git: the parse step, how a tie is decided, how a search runs and where its time goes, the LinkedIn lane, and `fn-enrich`.
- A first live LinkedIn run failed on the area name "Chicago Metropolitan Area". With "Greater Chicago Area" it returned two people with a Belgian degree in 95 s for $0.11.
- A panel of three ruled on two decisions in two rounds (A and B in `panel-records.md`): the LinkedIn lane runs for every question that does not ask for researchers only, and the second lookup pass runs after a search is done.
- Design system version 14.2 published: a done search that still looks up facts shows the count line and the status line together. No new class.
- Slice k1, the parse prompt. Three wordings were tried against live readings. A reviewer found that the examples of the first one came from the test questions, so the examples were replaced and a held-out set was added. Held-out questions with Belgium as subject or audience: 34 of 40 right on main, 40 of 40 on the branch. Merged as pull request 106.
- Live LinkedIn query tests. Runs side by side are refused. A page of 25 full profiles does not fit in the actor's 240 s. Job titles find the right people where keywords do not. Then the actor refused every run: Apify's free plan runs it ten times in total. The lane was designed for a paid plan, with a check that makes no paid call on a free one.
- Slice k5 planned, reviewed, built and reviewed: `fn-enrich` stops at the OpenAlex reserve and at the first 429. Merged as pull request 107. Run live on the owner's database: 695 lookups, 529 matched, 8 ambiguous, 158 without a match, no error, stopped with 2,979 credits left; 938 people still wait.
- Slice k3 planned, reviewed, built and reviewed: a search is done after the fit check and the second lookup pass runs after it. Merged as pull request 108. A live search on a copy was done after 128 s; its second pass ran until 160 s, with the count line and "Looking up missing facts…" on the page.
- Slice k4 planned in two review rounds, built and reviewed: the LinkedIn lane searches by job title, takes 10 profiles a run, writes a place and a job title, and runs on the staff server after a free check of the Apify plan and budget. The lead applied three notes of the review. Merged as pull request 109.
- Slice k2 planned, reviewed and built. The builder stopped at the hand check: 60 of the 114 people without a tie got one, because the other employers have no Belgian record at ROR or Wikidata. Lead ruling: no record, no row. The review found four spellings too generic to be safe ("FIT", "UCB", "Knack", "Barco") and six spellings of an Antwerp academy that were missing; all fixed. The lead added De Tijd and Galapagos and removed a timing assertion. Merged as pull request 110.
- On the owner's database: 159 organizations saved, 222 stored claims linked, people with a job at a Belgian organization 750 before and 855 after, and 37 stored searches reranked. In the midterms search the Flemish broadcaster's analyst moved from rank 3 without a tie to rank 1 with one.
- All slices on main: 1,214 tests pass (1,177 before).
