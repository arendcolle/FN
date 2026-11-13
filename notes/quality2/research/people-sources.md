# Open sources for the people FN misses

2026-11-12 · research note for the quality round 2 · question: which open sources hold non-researchers with a tie to Flanders or Belgium who live or work in the US, and how many would each add?

## TL;DR

- The non-researchers FN misses sit in small, named lists: chamber boards, the embassy's advisors on economic diplomacy, the officer lists of Belgian-American nonprofits in IRS Form 990 filings, and alumni-group boards. Each list holds 10 to 40 people. Together they would add about 100 to 200 people, with a role, an employer and often a state. This is an estimate from the pages probed, not a count of every list.
- These lists are the only open sources probed that reach "a professional with only a Belgian master's degree". Wikidata, Wikipedia categories and SEC filings reach only people who are notable or who run a listed company.
- Widening the Wikidata query adds the most rows: 1,737 living people with a Belgian tie and a US residence, work place or employer, against 295 in today's seed. But 1,416 of them have a research occupation, and only 155 are non-researchers with a personal tie (citizen, born in Belgium, or a Belgian school). It found 0 of 5 non-researcher gold picks.
- Two gold picks (GS-23#2, GS-32#4) turn up in Form 990 officer lists. One (GS-23#2) is on the embassy advisors page. SEC full-text search found two of the five (GS-03#1, GS-23#2) in the earlier survey. Wikidata, Wikipedia categories and FARA found none.
- The build order: (1) the BelCham board and the embassy advisors as seed lists, (2) Form 990 officers of about a dozen Belgian-American nonprofits, (3) the wider Wikidata query, limited to people with a personal tie, (4) SEC full-text search, if the owner accepts sending a contact address in the User-Agent.

## How this was measured

- What is built today comes from `src/fn/seedload.py` (nine lists: baef, francqui, kvab, climate, consuls, fayat, wikidata, chambers, missions), from `data/seeds/*.jsonl` (5,429 rows, 295 of them Wikidata), and from `notes/quality/design.md`. The lanes are seeds, OpenAlex, web (Parallel) and LinkedIn (off).
- The survey (`notes/research/findings.json`) rates 157 findings adopt or borrow. Of those, the ones that reach people outside research are SEC EDGAR full-text search with edgartools, the Belgian mandate sources (Staatsblad, NBB), the conference speaker scraper pattern, Flemish press, Kunstenpunt and the iTunes podcast search. Only the chambers and the 2022 mission program are built.
- The five non-researcher gold picks used as a check: GS-03#1 (a flooring executive in Atlanta), GS-23#2 (an investor and former consumer-goods marketing chief in New York), GS-28#4 (a founder of an advisory and energy firm in New York, law degree from Leuven), GS-32#4 (the head of a Leuven alumni group in the Bay Area, bachelor's degree from an Antwerp college) and GS-09#2 (a consultant in South Carolina with a Vlerick degree).
- All probes ran on 2026-11-12 with the User-Agent "fn-research/0.1". Requests per service: Wikidata mirror 6, DBpedia 5, ProPublica 10, FARA 4, BelCham 3, the embassy site 4, QLever 4, Senate LDA 2. No call went to OpenAlex, Parallel, Apify or SEC. The `claude -p` command was not used.

## Sources compared

Yield is people a source returns for the query shown. "Gold" counts the five picks above. Effort is days of work to build the source as a seed list (seed) or as a lookup inside a search (lookup).

| Source | Kind of people | How to query | Yield measured | Fields it carries | Key or terms | Runs locally | Effort | Gold picks found |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Wikidata, wider query | Mostly researchers. Some executives, journalists, lawyers, artists | SPARQL: human, alive, a tie (P27 Belgium, P19 in Belgium, P69 or P108 a Belgian organization) and a US tie (P551, P937, or P108 with a US organization) | 1,737 people. 321 without a research occupation, 155 of them with a personal tie. 1,450 not in today's seed | Tie yes, role yes (occupation), employer often, place sometimes (city of residence), date rarely (statement start dates) | CC0, no key. Wikimedia endpoints ask for contact details in the User-Agent. QLever answered 429. Probed through a third-party mirror instead | Yes, as a seed list | Seed 0.5 | 0 of 5 |
| Wikipedia categories (via DBpedia) | Artists, athletes, business people, few researchers | SPARQL on dct:subject: Belgian emigrants to the US, Belgian expatriates in the US, Americans of Belgian or Flemish descent | 189 people without a death date. 180 have a Wikidata id, 25 of them already in the wider Wikidata set | Tie yes (the category), role from other categories only, employer no, place no, date of birth sometimes | Open, no key. Robots asks for a 10 s crawl delay | Yes, as a seed list | Seed 0.5 | 0 of 5 |
| IRS Form 990 officers (via ProPublica Nonprofit Explorer) | Board members of Belgian-American chambers, clubs, foundations and alumni groups: business people and plain professionals | API search by name ("belgian", "belgian american"), then each organization's page or its e-file XML | 124 organizations match "belgian", mostly dog and horse clubs. About 12 are Belgian-American groups. 9 to 10 officer rows per filing in the two read by hand | Tie through the organization, role yes (officer title), employer no, place only the organization's city, date yes (fiscal year, 2024 or 2025) | No key. Robots allows the API and organization pages, and blocks search pages. Bulk e-file XML is public | Yes, as a seed list | Seed 1 to 1.5 | 2 of 5 (GS-23#2, GS-32#4) |
| BelCham board and team page | Executives, founders, lawyers, bankers in the US | One page, belcham.org/about-us | 30 name and role rows | Tie through the chamber, role yes, employer yes, place often (US state), date no (page date only) | No key. Robots allows the page (Squarespace) | Yes, as a seed list | Seed 0.5 (the chambers script already parses two chamber pages) | 0 of 5 |
| Embassy page "Advisors on economic diplomacy" | Business people the embassy appointed, by state | One page on the embassy site | 12 advisors in 9 states, page dated 2025-05-12 | Tie yes (appointed by Belgium), role yes, employer yes, place yes (state), date yes (page date). Also phones and email addresses, which FN must not store | No key. Robots does not block it | Yes, as a seed list | Seed 0.5, together with BelCham | 1 of 5 (GS-23#2) |
| FARA bulk files | People registered to work for a Belgian principal | Bulk CSV of foreign principals and short-form registrants, joined on the registration number | 103 people under registrants whose only principals are Belgian, 9 still active. Mostly tourist office and government information staff | Tie yes, role no, employer yes (the registrant), place yes (registrant city), date yes | No key. Bulk files are public, refreshed daily | Yes, as a seed list | Seed 0.5 | 0 of 5 |
| SEC EDGAR full-text search (survey, not probed today) | Officers and directors of US-listed companies, founders who file Form D | efts JSON: an exact phrase such as a Flemish university or company name, filtered by form (DEF 14A, 10-K, Form 3, 4 or D) | From the survey: 63 proxy hits for "KU Leuven", 17 for "Ghent University" in 2024 to 2026 | Tie yes (quoted biography), role yes, employer yes, place sometimes, date yes (filing date) | No key. The SEC asks for a company name and a contact email in the User-Agent. That is the owner's decision, so it was not probed | Partly: queries go to the SEC | Lookup 2 | 2 of 5 in the survey (GS-03#1, GS-23#2) |
| Senate lobbying disclosures (LDA) | Lobbyists for Belgian clients | API, clients by country | Not measured: the server answered 403 to the generic client | Not checked | Not checked | Not checked | Not checked | Not checked |

Notes on the table:

- The Wikidata mirror (OpenLink) has an unknown snapshot date. Its count is an order of magnitude, not an exact count of live Wikidata. 287 of the 295 seed rows are in it.
- In the wider Wikidata set, 785 of 1,737 people are tied only through an employer whose country is Belgium. That branch gives false ties: a US airline chief executive is in the set because one of his employers carries Belgium as its country. Of the 321 non-researchers, 166 hold only that kind of tie.
- The DBpedia answer to the category query was cut off at about 1,400 rows. In the 81 people it parsed, the other categories split as arts 29, sport 20, business, law or press 14, research 11, born before 1930 6, other 1.
- The Form 990 officer list lags. GS-23#2 is president of BelCham in the 2024 filing but is not on today's BelCham page. Both sources together give a dated history.
- The earlier survey shows that SEC search misses most people: 0 hits for seven other gold picks and 0 for "born in Belgium" in proxies.

## Who reaches a professional with only a Belgian master's degree

Sources that reach them:

- Chamber boards and teams (BelCham, plus BACoS and Belwest, which are built). Board members are country managers, lawyers and founders, often without publications.
- The embassy advisors page.
- Form 990 officers of Belgian-American nonprofits and alumni groups. GS-32#4, with a bachelor's degree from an Antwerp college, appears there as a director.
- Event and mission programs, which are already a seed list for 2022 (67 rows).
- Alumni group boards, such as the Leuven alumni group in the Bay Area (6 board members on its site). These pages exist, but most universities do not publish US chapter boards. Only this one was found.

Sources that do not reach them:

- Wikidata and Wikipedia categories. They need notability. GS-28#4 and GS-09#2, with a law and a business degree, have no item.
- SEC filings. They reach only officers of listed companies and founders who file Form D.
- FARA. It lists people who work for a Belgian principal, which is mostly the delegation's own side.
- OpenAlex, ORCID, FRIS and Biblio UGent. They hold researchers.

The degree itself is rarely in any open record. A chamber or 990 row gives the tie through the organization, not the degree. The web lane, or a later per-person lookup, has to find "Studied at Ghent University". Whether the UGent and KU Leuven library catalogs list master's theses by author name was not checked.

## Build order

1. **BelCham board and the embassy advisors page as two more chamber-style seed lists.** About 42 rows, each with a role, an employer and a state. This takes half a day, because `scripts/seeds/chambers.py` already parses two chamber pages. It finds GS-23#2. The seed loader must store neither phone numbers nor email addresses from the embassy page.
2. **Form 990 officers of Belgian-American nonprofits.** Pick the organizations by hand once: BelCham, BACoS, BAEF, the Leuven alumni group, the Belgian-American clubs of Texas and Chicago, and the Flemish-American groups. That is about 12. Read the officers from the IRS e-file XML so that the list runs locally and carries the fiscal year. This gives about 100 to 150 rows (estimate: 12 organizations at 9 to 10 rows each, plus the larger boards), with a role and a date, in 1 to 1.5 days. It finds GS-23#2 and GS-32#4. It is the best open source measured for plain professionals.
3. **The wider Wikidata query, limited to a personal tie.** Add P27 (citizen), P19 (born in Belgium) and P937 (US work place) to `scripts/seeds/wikidata.py`, and drop the branch where the only tie is an employer whose country is Belgium. This gives about 155 non-researchers plus many researchers the seed misses, in half a day. Run it once through the endpoint the seed script already uses. The owner decides on the User-Agent there.
4. **SEC full-text search as a lookup for business questions.** This waits for the owner's decision on the contact address. It is the only source probed with a dated, quotable biography for listed-company executives (GS-03#1, GS-23#2). It takes 2 days with edgartools.
5. **Wikipedia categories.** Add these only after step 3, as a check on artists and athletes Wikidata misses. There are 189 rows, about 155 of them new, but they carry neither place nor employer.

## Ruled out, and why

- **FARA.** 103 people, 9 active, mostly tourist office and government information staff. Those are the delegation's own side, which the chambers script already excludes as staff. 0 of 5 gold picks.
- **Senate lobbying disclosures.** The server refused the generic client (403). The tie would be a Belgian client company, not the person.
- **Patents and clinical trial investigators.** They reach engineers and physicians, which are close to the researcher group FN already has from OpenAlex. Not probed. PatentsView needs a free key (not re-checked today).
- **Think-tank expert directories, speaker bureaus and conference programs.** One site per list and no Belgian filter. Better reached by the web lane with the speaker-scraper pattern from the survey than as seed lists. Not probed.
- **The Staatsblad and NBB mandate records.** These hold Belgian company director appointments, sometimes with a US address. The survey rated them adopt, but they are PDF text in Dutch and French with no US filter. Not probed, effort not checked.
- **LinkedIn and Dealroom.** These would reach every plain professional, but robots rules forbid LinkedIn and Dealroom is paid.
- **Flanders Investment and Trade press releases and the delegation's event pages.** They name US-based Flemish business people, but the design decided to wait on them (D13). Not probed in this round.

## Not checked

- The live Wikidata count. QLever answered 429, and the Wikimedia endpoints ask for contact details in the User-Agent. The numbers come from a mirror with an unknown snapshot date.
- How many of the 155 Wikidata non-researchers have a city-level place.
- The officer counts of the 990 filings other than BelCham and the Leuven alumni group. Those two were read by hand. For BACoS and BAEF, a pattern match gave 36 and 39 role entries, which were not checked by hand.
- ProPublica's terms of use beyond robots.txt.
- GS-28#4 in SEC filings. A BAEF seed row carries the same name, but whether it is the same person was not checked.
