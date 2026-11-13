# Panel 2 brief: how does FN search the web, read pages and grow its lists without paid limits?

## What the owner asked

More use of web search and less dependence on OpenAlex and ORCID. Ideally open-source parts that run locally, because the limits of the paid services (Parallel for web search, Apify for LinkedIn) will not grow, and they would not scale if many people used FN. The people to reach are business people and plain professionals with a tie to Flanders.

## What the research found

Read these notes in `notes/quality2/research/` before you vote.

- `local-search.md`: every free route was tried live on three questions. A local SearXNG container gave 5 to 6 people-naming pages out of 10 in about 1 s, but its useful engine is Google's custom-search page, which Google's robots.txt disallows, and DuckDuckGo and Brave blocked it after 4 and 8 queries. DuckDuckGo's own HTML endpoint, called directly, gave 5 to 7 of 10 with no block in 8 queries at 4 s spacing; its robots.txt allows that host, its terms and daily ceiling were not checked. The web search built into the `claude -p` command line has clean terms and needs no key, takes 12 to 22 s a query, and about 1 in 10 of its links is dead. Query wording changed results more than the route: a Dutch query and a `site:` query on a Belgian newspaper gave the best pages of the test, and dropping "Belgian" lost the tie. Reading pages locally with the standard-library HTML parser worked on 7 of 10 pages and kept 37% more text than trafilatura; a bot block, a JavaScript-only page and a PDF failed. Parallel today costs $0.001 a search and $0.001 a page.
- `people-sources.md`: open lists of non-researchers are small. The BelCham board page and the embassy's advisors page hold about 42 people with a role, an employer and a state. IRS Form 990 officer lists of about 12 Belgian-American nonprofits would give 100 to 150 people. A wider Wikidata query gives 155 non-researchers with a personal tie and many researchers. Wikipedia categories give 189 people without a place or an employer. SEC filings wait for the owner, because the SEC asks for a contact email in each request.
- `held-not-returned.md` and `tiers.md`: the web lane's queries today are one per topic chip with the place, and its objective asks for a connection to Belgium.

The decisions of panel 1 hold: the web lanes call one function, `websearch.find`, to find pages; a second lane searches the topic without a tie when the tie is not a must; a thin-record lookup batch searches the web for one person at a time, anchored on a known school or employer.

Limits that hold for every option: no new Python dependency without the owner's consent, no route whose robots.txt forbids the pages FN would fetch, every outbound call recorded in a step and cached, the owner can switch back to Parallel with one setting, and a Docker container counts as a change to how FN is deployed, which the owner asked to keep as it is unless he opts in.

## The decisions

The options under each decision are listed in the panel's prompt.

- **W1** Which route finds pages for a web query.
- **W2** How the queries of one search are written.
- **W3** How a found page is read.
- **W4** Which seed lists are added in this round.
