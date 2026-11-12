# Sources of people

Research note, 2026-11-12. No product code changed. Scratch scripts and fetched files live in the session scratchpad under `quality/sources/`.

## TL;DR

The people staff really pick sit in public records of who Flanders picked, not in OpenAlex. The 2022 Belgian economic mission program PDF alone names 26 of the 99 gold picks across 9 of 28 cases. Event pages of the delegation, chamber pages and partner institute pages name 31 more picks. Together these public records hold 56 of 99 picks; 36 picks sit only on LinkedIn or nowhere I could fetch. OpenAlex filled 349 of 510 shown people in the one live search, 183 of them located in Belgium and 16 in the US, and across the 28 stored gold searches it put no gold pick in the top 20 on its own. The seed lists hold 19 picks, but the place-rich consul list reached the shown results 3 times in 29 searches, because the seeds lane never queries place chips. Add first, in order: mission program and mission document scraper, delegation event pages, chamber pages, a Wikidata seed list. Narrow OpenAlex to authors whose last known institution is in the US, and use it as a lookup that fills academic records for people other sources found.

## Findings

### 1. What the six seed lists give today

Measured with `scratchpad/quality/sources/q1.py` over `data/seeds/*.jsonl`.

| List | Rows | Years | Place filled | US place | Other fields |
|---|---|---|---|---|---|
| BAEF fellows | 3,577 | 1920 to 2019 | 0 | 0 | 1,198 rows name a US host or student institution (regex, approximate); role 1,441; field 1,472 |
| Climate Centre experts | 453 | none | 0 | 0 | employer 452, field 453, profile URL 453; Belgium-based |
| Honorary consuls | 34 | none | 30 | 32 (place or jurisdiction) | role 34, jurisdiction 34 |
| Fayat laureates | 95 | 2022 to 2024 | 95 (country) | 30 | institution, field, LinkedIn URL on all 95 |
| Francqui fellows | 331 | 1974 to 2024 | 101 | most of the 101 are US cities | host institution 331 |
| KVAB members | 545 | 1977 to 2026 | 0 | 0 | academy class only |

- BAEF stops at 2019. The newer cohorts sit in news posts (`baef.be/2025/12/19/...`, `baef.be/2026/07/22/...`) that give counts per type, not names.
- A US host in BAEF or Francqui is a past stay, not a current base. Only consuls and Fayat give a current or recent US place.

How often seed people reach the top 20, measured with `q1db.py` on the read-only database. 29 searches are stored; 4 have no candidates, so 25 give 500 top-20 slots.

- 129 of 500 top-20 slots hold a seed person: 79 found by the seeds lane alone, 50 merged with OpenAlex. OpenAlex alone holds 341 slots, the web lane 8 alone and 17 merged with OpenAlex, LinkedIn 5.
- Every one of the 25 searches has at least one seed person in its top 20.
- Top-20 slots by list (a person in two lists counts twice): BAEF 86, Climate 66, KVAB 38, Francqui 25, Fayat 1, consuls 0. Across all shown people, consuls appear 3 times in 29 searches.
- Cause for the consuls: `fts_query` in `src/fn/lanes/seeds.py:27-34` ORs only topic and institution chip tokens. A place chip never queries seed claims, and the consul rows carry no topic text.
- 28 of the 29 stored searches ran in replay mode on older recorded calls; only `e4caaf4e` ran live on current code.

### 2. Candidate sources, checked with public fetches

All fetches used a generic User-Agent and a robots.txt check (`probe.py`). "Picks" means gold picks whose name appears in the fetched text (`q3m.py`).

| Source | Reachable | Form | People | Fields | Fresh | Build, hours (estimate) | Legal or robots |
|---|---|---|---|---|---|---|---|
| Mission program PDF 2022 (partner site) | origin returns 403 to a generic UA, also on robots.txt; Wayback copy fetched | 69-page PDF, multi-column | at least 65 named speakers (regex lower bound) | name, title, employer, session, city, date; tie by construction of being picked | one mission per 2 to 3 years | 8 to 12 | use the archived copy or ask the partner |
| Trade agency mission pages (`abh-ace.be/en/past-mission/...`) | yes, 19 PDFs downloaded | PDFs: participants brochure, press overview, signing-ceremony releases, trade study | 2022 participants brochure 369 pages with 151 CEO or managing director lines; 2025 brochure 166 pages | name, title, Belgian company; mostly Belgium-based delegates | missions 2008, 2011, 2013, 2016, 2022, 2025 | 6 to 10 | robots allows; public government files |
| Mission site `belgianeconomicmission.be` | page reads "will be launched soon" | none | 0 | none | none | 0 | none |
| Delegation site `flandersintheusa.org` news | yes | HTML list, 47 pages of 5 items | most items are Flanders news, not people | title, date | newest item 2026-11-04 | 4 to 6 | crawl-delay 10 |
| Delegation old event pages `/event/...` | yes, still live but unlinked; no sitemap (404) | HTML | not counted; enumeration through Wayback CDX failed with 503 | speaker names, roles, venue, date | 2018 to 2024 | 4 to 6 plus URL discovery | crawl-delay 10 |
| Delegation events calendar | yes, empty, footer says 2022 | HTML | 0 | none | stale | 0 | none |
| BELWEST (West Coast chamber) `/bem`, `/board`, `/events` | yes | Squarespace HTML | board and mission speakers; not counted | name, role, company, California city | 2025 mission | 3 to 5 | robots blocks only account and search paths |
| BACoS (Southeast) `about.html` | yes | static HTML | board list | name, role, company | current | 2 | allowed |
| BelCham (New York) | yes | Squarespace HTML | no gold pick on the pages fetched | event highlights | current | 3 | allowed |
| Global Atlanta event pages | 403 to a generic UA | HTML | not measured | not measured | not measured | blocked | origin blocks |
| UGent alumni chapters | yes | HTML | ambassadors per country only | name, country | current | 2 | allowed |
| UGent alumni invitation PDFs | yes, the gold PDF fetched | PDF | per event, a few speakers | name, role | per event | 2 per format | allowed |
| KU Leuven alumni chapters | yes, chapter list names the US; robots allows all | HTML | member lists not public | chapter only | current | not worth it | allowed |
| Amici Lovanienses | yes | HTML bio pages | a few | bio, city | current | 2 | allowed |
| FIT and consulate staff pages | yes | HTML | staff | name, office | current | 1 | allowed; staff are the users, gold removes them |
| Wikidata through SPARQL | WDQS answered 429 "1 req / min" during an outage; the QLever mirror answered in 2 s | SPARQL JSON | 949 living people | label 97%, description 97%, ORCID 73%, birth date 37%, enwiki 23%, LinkedIn id 11%, OpenAlex id 1%; US employer statement 917, of which 558 open-ended and 688 with an employer HQ city | edited continuously | 3 to 4 | CC0 |
| Wikipedia categories | yes, API | category lists | 198 Belgian emigrants to the US, 98 of Belgian descent, 17 of Flemish descent, 50 expatriates; includes the dead | article only | slow | 2 | CC BY-SA |
| ORCID public API | yes, no key | JSON | 138 with a past Flemish university and a current employer among 10 large US universities; a full US count needs one query per institution | sample of 20: 17 have a current US employer with city, 16 a role title, 15 a start date, 15 a Belgian education | self-maintained | 4 as a lookup | open API terms, rate limits |
| OpenAlex, US-narrowed | yes | JSON | 25,973 authors with a US last known institution and any Belgian affiliation | institution, years, city from institution geo | weekly | 1 (filter change) | CC0 |
| Flemish press | Knack and VRT robots allow articles; tijd.be returns 403 on robots.txt; paywalls | HTML | not measured | not measured | daily | not worth it as a list | paywalls |
| LinkedIn | robots `Disallow: /` for every agent | needs login | not measured | role, city, education | current | not allowed | robots and terms |

Wikidata detail (`wd2.py`, `wdan.py`). The population is living humans with a Belgian education plus a US employer, or Belgian citizenship plus a US employer or US residence, or a Belgian birthplace plus a US employer. 494 of 812 with a Belgian education studied at a Flemish institution. 782 have an academic occupation; "researcher" alone covers 546, so most of the set is academic. 133 already match a seed name.

### 3. Gold set against the sources

Name matching on fetched text, `q3_matrix.txt`. 99 picks in 28 cases. A pick can be in several sources.

| Source | Picks | Cases |
|---|---|---|
| Mission program PDF 2022 | 26 | GS-01, 02, 03, 04, 10, 16, 22, 29, 33 |
| Seed lists today (by name) | 19 | GS-02, 03, 05, 06, 08, 10, 15, 16, 18, 22, 28, 33 |
| Delegation event and news pages | 11 | GS-05, 09, 11, 12, 23 |
| Chamber pages | 10 | GS-03, 04, 31, 32 |
| Trade agency mission documents | 9 | GS-02, 03, 07, 16, 22, 33 |
| Wikidata US-tie population | 8 | GS-01, 04, 05, 10, 16, 28 |
| Partner and government press pages | 6 | GS-06, 08, 30 |
| Alumni pages and invitation PDF | 4 | GS-29, 32 |
| Any public source other than seeds | 56 | |
| No fetched source | 36 | GS-13 (5), 14 (1), 15 (1), 16 (4), 18 (3), 21 (5), 22 (3), 24 (6), 27 (5), 28 (1), 33 (2) |

- The cases with no fetched source are the ones built from LinkedIn posts: GS-13, 14, 21, 24, 27 have 0 picks in any public source.
- What FN showed for the same 28 questions (stored searches): 11 gold picks shown in total, 3 in a top 20. All 3 were seed people merged with OpenAlex. OpenAlex alone showed 1 pick, never in a top 20; the web lane showed 5, none in a top 20.
- `data/gold/reach.json` covers 9 academic picks: OpenAlex reaches 5, seeds 3.

### 4. Where OpenAlex stands

- In the live search `e4caaf4e`, 349 of 510 shown people came from OpenAlex alone. By location claim: 183 in Belgium, 16 in the US, 126 elsewhere, 24 with none.
- The lane asks for works with any Belgian institution (`src/fn/lanes/openalex.py:96-97`) and authors with a Belgian affiliation at a chip institution (`:83`). Nothing asks for a US base.
- Narrowing works in the API: works on "artificial intelligence health" with a Belgian institution give 11,734; with a Belgian and a US institution, 2,751. "climate" gives 62,445 against 10,658.
- Location gaps in `e4caaf4e` are not an OpenAlex problem: 160 shown people lack a location claim, split as seeds 85, web 51, OpenAlex 24. Only 16 of the 160 carry an ORCID. Merging records across sources fills more locations than any ORCID lookup.

## Recommendations

Ordered by gold picks gained per hour of work.

1. Mission scraper, a seed list. Parse the mission program PDFs and the trade agency mission documents into one row per person per session: name, title, employer, session, city, date. About 65 or more speakers per program plus a few hundred Belgian delegates per participants brochure. Helps place and business questions. Holds 26 picks in 9 cases, 30 with the trade agency documents. Owner: a new `scripts/seeds/missions.py` writing `data/seeds/missions.jsonl`.
2. Delegation event pages, a seed list. Crawl `flandersintheusa.org/event/*` and the news pages with the 10 s crawl delay; find old URLs through the Wayback CDX API when it answers. Helps cultural, place and business questions. Holds 11 picks in 5 cases. Owner: `scripts/seeds/fitusa.py`.
3. Chamber pages, a seed list. BELWEST mission, board and event pages, BACoS board, BelCham event highlights. Helps place and business questions. Holds 10 picks in 4 cases, 7 of 8 for GS-31 and GS-32. Owner: `scripts/seeds/chambers.py`.
4. Wikidata, a seed list refreshed monthly and a lookup. 949 people with a tie and a US employer or residence, with ORCID on 73% and an employer city on 688. Helps academic questions most. Holds 8 picks in 6 cases. Owner: `scripts/seeds/wikidata.py`, run against the QLever mirror or WDQS when it is not rate-limited.
5. Let the seeds lane query place chips. Without it the consuls and every place-rich list from steps 1 to 3 stay invisible to place questions. Owner: `src/fn/lanes/seeds.py`.

OpenAlex: narrow it and make it a lookup. As a people source, keep it only for academic questions, and filter on a US last known institution plus a Belgian affiliation (authors) or a Belgian plus a US institution (works). As a lookup, use it to fill affiliation history and location for academics that seeds, missions or Wikidata found. Owner: `src/fn/lanes/openalex.py`.

ORCID: a lookup only, after the merge step works. It fills a current US city and role for 17 of 20 sampled records, but only 16 of the 160 unlocated people in `e4caaf4e` carry an ORCID.

Not worth building from the owner's document:

- Instagram: newest posts only, and no scorable gold case came from it (owner's document).
- LinkedIn by scraping: robots disallows every path for every agent and it needs a login. The 36 picks only found there stay out of reach for public scraping.
- KU Leuven and other alumni member lists: chapter pages name the US but member lists are not public.
- FIT and consulate staff pages: the staff are FN's users and the gold set removes them. Use them at most as an exclusion list.
- The delegation events calendar and `belgianeconomicmission.be`: empty or a placeholder page.
- Wikipedia categories: about 360 pages, dead people included; Wikidata covers the living ones with fields.
- Flemish press as a list of people: paywalls and no list form. Leave it to the web lane as a fact lookup.
- BAEF cohorts after 2019: the posts give counts, not names.

## Open decisions

- Mission participants brochures list Belgium-based delegates. Gold includes people flown in from Belgium (GS-03, 16, 30), but the delegation asks mostly for people in the US. Keep them as candidates or only as a tie check?
- The 2022 program PDF origin returns 403 to a generic client. Accept the Wayback copy as the source of record, or ask the partner site for access?
- Wikidata endpoint: the public QLever mirror, or WDQS with a one-request-per-minute fallback?
- Should OpenAlex run at all on place or business questions, where it put no gold pick in a top 20?

## Not measured

- The number of `/event/` pages on the delegation site (CDX returned 503).
- Global Atlanta event pages beyond the archived PDF.
- The exact speaker count of the 2022 program; 65 is a regex lower bound.
- Name matches are exact after accent folding; a pick listed under a nickname or a shorter name counts as a miss.
