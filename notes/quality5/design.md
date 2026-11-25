# Which people did FN still miss, and what made a search slow?

Round five, 25 November 2026. The owner picked five of the open follow-ups to do now. This page records what was decided for each, why, what was measured and who owns what in the code. The votes are in [panel-records.md](panel-records.md), the steps in [progress.md](progress.md) and the task of each slice in [tasks/](tasks/).

## TL;DR

FN read "trade with Belgium" as a tie of the person, missed people who work at a Belgian company or broadcaster, showed a search as done only after lookups that rarely changed the list, could not look up the seed-list people without using the whole day's OpenAlex budget, and found no journalists, architects or investors. Four of the five are fixed and measured. The fifth, the LinkedIn lane, is built and finds the right people in replayed answers, and waits for a paid Apify plan: the free plan runs the actor ten times in total.

## What the owner asked for

| # | Item | Measured before |
| --- | --- | --- |
| 1 | A subject such as "trade with Belgium" is no required tie of the person | The parse step read Belgium as a required tie in 6 of 40 readings of questions where it is the subject or the audience, which cuts everyone without a Belgian link |
| 2 | A job at a Flemish employer, or its US arm, counts as a tie | 314 job claims at 118 Belgian-looking employers had no Belgian organization; the alias file held no company and no medium |
| 3 | End a search when the lanes end; lookups fill in after | The last three live searches were done 48 to 85 s after their last lane ended; the second lookup pass took 25 to 55 s of that |
| 4 | Look up the seed-list people, with a daily cap | One run used the day's 10,000 OpenAlex credits in two minutes and stored 823 people as failed; 1,633 people waited |
| 5 | Give the LinkedIn lane a budget, for people who are not academics | Five of 20 benchmark questions had nobody invitable in the first ten cards; the lane was off and searched by topic keywords |

## Decisions

| Id | Decision | Why | Slice |
| --- | --- | --- | --- |
| L1 | The parse prompt names three cases without a tie: Flanders or Belgium as the venue or host, as the audience, and as the subject the people know about. A named university or company is an institution chip and no tie. | The prompt named the venue only. The examples in the new line appear in no test question, and a held-out set checks the wording. | k1 |
| L2 | The alias file holds Belgian companies, media and government bodies, each with an id checked at ROR or Wikidata. An employer without a Belgian record at either gets no row. | A tie needs an organization whose country is Belgium, and the registry is the one source for that. A local list of organizations nobody else knows would be a second source to keep right. | k2 |
| L3 | A spelling in the alias file can be marked as a post away from home: a US arm, a consulate or embassy, a trade office, the broadcaster's news desk abroad. The job counts for the tie and the parent's city is not taken as the person's place. | An employer's city stands in for a person's place when no place is stated, and a place outside a required area sets the person aside. A consul in Atlanta is not in Brussels. | k2 |
| L4 | The match step links a name in the alias file before it asks ROR, also for claims already stored, and an alias overrules a stored ROR answer for the same name. | The alias file is checked by hand. ROR had linked the Belgian federal government to a Malaysian organization. | k2 |
| L5 | A bare short name that another employer carries gets no row ("FIT", "UCB", "Knack", "Barco"); the spelled-out forms do. | A review found a US fashion school and a US university behind two of them. A wrong alias gives a false tie without any call that could catch it. | k2 |
| B | A search is done after the fit check. The second lookup pass runs after that on the same worker thread, and the list is ranked once more with the stored verdicts when the pass added facts. | Panel, 2 to 1. The fit check changed 4 to 9 of the first ten cards in three live searches; the second pass moved nobody in two of them. | k3 |
| L6 | While a done search still looks up facts, the page shows the count line with Export and "Looking up missing facts…" under it, keeps polling and swaps the list once. No new search status. | It is the same work as during a search, so it has the same words. A done search with a running step is all the state there is. | k3 |
| L7 | A step left running on a done search is interrupted at the next server start. | Else the page would say it is looking up for ever after a restart. | k3 |
| L8 | `fn-enrich` starts no author search after an answer that leaves under 3,000 of the day's credits, or after a 429. A person it did not reach gets no row. One reserve, in the OpenAlex module, for `fn-index` and `fn-enrich`. | `fn-index` already stopped this way. A 429 is the day's budget, not a fact about the person. | k5 |
| A | On the staff server the LinkedIn lane runs for every question that does not ask for researchers only, while the month's Apify budget has room for one run. | Panel, 2 to 1. It mirrors the rule that skips OpenAlex when no research is asked. | k4 |
| L9 | The lane makes no paid call on Apify's free plan, and reads the plan and the budget free of charge before each paid run. Neither answer is cached or stored. | The actor runs ten times in total on a free plan and then answers with nothing at $0.004 a run. The account answer holds the owner's email. | k4 |
| L10 | The lane searches by job title: the role chips as singular titles. Without a role chip it sends the topic keywords as before. | In live runs keywords put an enterprise architect and three founders first for "architects or designers"; titles put an architect and a designer first. A run with plural titles found nobody. | k4 |
| L11 | A run takes 10 full profiles and may take 270 s. | On the free plan the search page took 80 to 125 s and each profile about 8.5 s. Four runs with 13 or more profiles were cut off at 240 s, charged, and returned nothing. | k4 |
| L12 | Each profile also gives a place and a job title. Chicago and Houston send LinkedIn's own area names. | Without a place a LinkedIn person lost a tier under a required place, and the card showed an employer without a role. "Chicago Metropolitan Area" matched nobody. | k4 |
| L13 | An answer without profiles is not cached. | It can be a refused run. A recorded "nobody" would hide the lane for that question for ever, and an empty run costs $0.004. | k4 |

Not decided by rule: which Belgian employers without a registry record count, and whether a question such as "Belgian trade experts in Chicago" means experts who are Belgian or experts on Belgian trade. The parse step reads the second as a required tie on main and on the branch.

## Design system

Version 14.2 adds one state to the StatusLine part: a done search that still looks up facts shows the count line and the status line together, with the existing classes. The app's style sheet is unchanged.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether Belgium in a question is a tie, an institution or a subject | the parse prompt, `prompts/parse.md` |
| Which employer spellings are a Belgian organization, and which are a post | `data/org_aliases.csv`, read by `orgs._rows` and `orgs.post` |
| Linking a stored claim to an alias, and overruling a stored ROR answer | `orgs.match`, `orgs.overruled` |
| An employer's city as a person's place | `evidence.places` |
| The steps after the lanes and the second lookup pass | `search.finish`, `search.second_pass` |
| Marking a search done and running what follows it | `Worker.execute`, `Worker.run_after_done` |
| Whether a search is looking up now | `present.looking` |
| Steps left running by an earlier start | `Store.sweep` |
| The status element of the results page | `staff.results_list`; the design system's StatusLine |
| How long the page keeps polling | `results.js` |
| The OpenAlex credit reserve and the credits left | `lanes/openalex.py` (`RESERVE`, `remaining`) |
| When `fn-enrich` stops | `enrich.authors` |
| Whether a question asks for researchers only | `parse.researchers_only` |
| When the LinkedIn lane may pay | `linkedin.may_run_live`, `linkedin.check_account` |
| A role chip as a job title | `linkedin.title`, `linkedin.job_titles` |
| A call that is never cached, and a check before a call goes out | `net.Client` (`cache="none"`, `before`) |
| The size of the month's LinkedIn budget | the Apify account |

## Measured after

| What | Before | After |
| --- | --- | --- |
| Held-out questions with Belgium as subject or audience, read without a tie (40 readings) | 34 | 40 |
| Questions where the tie describes the people, read right (100 readings) | 94 | 99 |
| People with a job at a Belgian organization, on the owner's database | 750 | 855 |
| The broadcaster's analyst in the stored midterms search | rank 3, no tie | rank 1, with a tie |
| A live search: seconds until done | 141, 154, 213 in three earlier searches | 128, with the second pass running until 160 |
| Seed people looked up with an answer | 977 | 1,672 |
| OpenAlex credits left after a lookup run | 0 | 2,979 |
| Invitable people in the first ten, journalists in New York (three model judges) | 0 | 7 |
| Invitable people in the first ten, architects or designers in Los Angeles | 0 | 7 |
| Tests | 1,177 | 1,214 |

The two LinkedIn rows are replays, not live searches: answers saved from live runs on 25 November were served to the built lane as recorded runs. For the journalists the saved answer came from a wider title list, cut to the profiles whose current title holds "journalist" or "editor", so that row is an approximation of what the lane's own query returns.

## What is left

- The LinkedIn lane needs a paid Apify plan before it runs. Starter was $19 a month with $19 of usage on 25 November, about 135 runs at $0.14. The other three benchmark questions (investors in Boston, food traders in Chicago, economists in Chicago) are not measured, and job titles for them are untried.
- A search with a live LinkedIn run waits for it: about three to three and a half minutes on the free plan's speed. The speed on a paid plan is not known.
- 938 seed people still wait for a lookup. `uv run fn-enrich --kind openalex_author --limit 1000` takes about 700 a day.
- About 54 people work at Belgian employers that have no Belgian record at ROR or Wikidata: small companies, two Belgian-American chambers, a few agencies. They keep no tie from that job.
- 30 people moved from "place unknown" to "outside" or "abroad" when their Belgian employer got a record. The rule is the old one, an employer's city when no place is stated, and it is wrong for someone posted in the US under a spelling that is not marked as a post.
- The first lookup pass still picks from the stored lists only, before the other lanes have found anyone.
- The next queued search waits behind the second pass of the one before it, as it waited before.
- The parse step gave a near-empty reading in 4 of 346 readings with the new line, against none before. The step asks again for such a reading.
- Two older tests are timing-sensitive under load.
