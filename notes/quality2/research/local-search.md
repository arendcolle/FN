# How can FN search the web and read pages without Parallel?

## TL;DR

No free route without an account matched Parallel on all counts I tried, which were quality, terms and limits. The strongest free search was a local SearXNG container. It answered the three test questions in about 1 s each with 5 to 6 people-naming pages out of 10, and in Dutch it surfaced the best Belgian-in-New-York press pages of the whole test. Its useful upstream engine was Google's custom-search page, and Google's robots.txt disallows that page. DuckDuckGo and Brave blocked SearXNG after 4 and 8 queries. The web search built into `claude -p` has clean terms and needs no new key, but it took 12 to 22 s per query, ignored `site:` filters, drifted away from "New York" and returned 7 dead URLs out of 72. For page reading, a plain httpx fetch with a standard-library HTML-to-text pass did as well as trafilatura on these ten pages, at a third of the time. It also kept about 37% more boilerplate. My recommendation is a `search_backend` setting that offers Parallel, SearXNG and `claude` WebSearch, with SearXNG as the default. The owner picks its engines in SearXNG's own config file. Page reading should become FN's own fetch, using the standard library first and trafilatura when the owner approves it. Parallel Extract stays the fallback for blocked pages, JavaScript-only pages and PDFs.

## What I tested and how

I ran each route live on 2026-11-12 with a generic User-Agent and at most 25 requests per service. I used no Parallel, Apify or OpenAlex calls. I asked three base questions:

- Q1 "speaker on the US midterms connected to Flanders or Belgium, New York"
- Q2 "Belgian founders in fintech in New York"
- Q3 "KU Leuven alumni working in semiconductor companies in Texas"

I also tried five query shapes: Q2 without "Belgian", Q2 with `site:tijd.be`, Q3 with `site:kuleuven.be`, Q2 in Dutch and Q2 in French.

"P" means a page that names people, such as a speaker list, a team page, a profile or news about a person. "N" means noise. I counted P and N from each result's title and snippet without opening the pages, so the counts are a rough screen. "On target" means the title itself shows a person who fits all three wishes.

The baseline comes from the frozen score database. It holds 26 Parallel Search calls and 26 Extract calls with $0.022 of recorded cost over 37 searches. Its 251 `vendor_page` sources average 6,381 characters, with a maximum of 11,926. Today `src/fn/lanes/web.py` sends one Search request with up to 5 queries, so one FN search equals up to 5 queries on any route below.

## Results per search route

The table below compares the routes on the three base questions.

| Route | Cost | Key or account | Runs locally | Q1 P/N | Q2 P/N | Q3 P/N | Rate limits I hit | Terms | What FN would add |
|---|---|---|---|---|---|---|---|---|---|
| Parallel Search (today) | $1 per 1,000 searches, Extract $1 per 1,000 pages (`PRICES` in web.py) | Key | No | not rerun | not rerun | not rerun | none recorded | Customer Terms limit reuse (findings.json) | nothing |
| SearXNG container | free | none | Yes (Docker) | 6/4 | 5/5 | 5/5 | DuckDuckGo CAPTCHA after 4 queries, Brave 429 after 8 | AGPL-3.0 container; scrapes Google custom search and Brave, whose robots.txt disallow those paths | one GET adapter, a container, a settings file |
| DuckDuckGo HTML endpoint | free | none | No | 7/3 | 5/5 | 6/4 | none in 8 queries at 4 s spacing | robots.txt allows `html.duckduckgo.com`; DuckDuckGo's terms not checked | one POST and a stdlib regex parser |
| `ddgs` package 9.16.1 | free | none | No | error | 2/5 (7 results) | timeout | 3 of 8 queries answered | scrapes several engines; terms per engine | new dependency (`ddgs`, `primp`, `lxml`, `click`) |
| Marginalia API | free non-commercial key by email | public key works without signing up | No | timeout | timeout | 0/10 | public key: 1 of 13 calls answered, then "QPM Limit Exceeded" | CC-BY-NC-SA 4.0 | GET adapter, attribution |
| Wikipedia search | free | none | No | 0 results | 0/10 | 0 results | none in 8 | CC BY-SA | not worth it for these questions |
| Wikidata full-text search | free | none | No | 0 | 0 | error | 6 of 8 calls returned non-JSON after 2 fast calls | CC0 | not worth it |
| Wikidata SPARQL | free | none | No | not tried | 0 rows (Belgian entrepreneurs living in New York) | 2 people, 1 on target | one 60 s timeout, one 429 | CC0 | a structured lane, not a web search |
| GDELT DOC API | free | none | No | 1 result, noise | 429 | 429 | 15 of 17 calls refused or rejected the query syntax | GDELT terms not checked | not worth it |
| Common Crawl index | free | none | No | n/a | n/a | n/a | none in 3 calls, 5 to 9 s each | Common Crawl terms of use | URL lookup per domain only, no keyword search |
| Brave Search API | $5 per 1,000, $5 free credit a month | key and card | No | not tried | not tried | not tried | n/a | storing results needs a custom plan | GET adapter, key in `KEYS` |
| Mojeek API | £2 per 1,000 (Startup), £3 (Business) | account and card | No | not tried | not tried | not tried | Startup 5 queries/s, 100,000 a day | Startup may cache 1 hour; Business has storage rights | GET adapter, key in `KEYS` |
| `claude -p` WebSearch (Haiku) | about $0.013 per query at list price, billed to the subscription | none new | No | 5/5 (3 unique) | 1/9 | 0/10 | none in 8 calls | Anthropic terms, as FN already uses `claude -p` | subprocess call with `--tools WebSearch` |

On-target pages were rare everywhere. On Q1, SearXNG and DuckDuckGo both found the delegation's own November 4 panel through its event page, YouTube, LinkedIn, Instagram and a CNN segment. That is lookup of a past event, which the earlier survey warned about (notes/research/mvp-tech-reference.md). On Q2, no base-question list from any route had an on-target title. On Q3, only Wikidata SPARQL returned an on-target person: a KU Leuven alumnus at a semiconductor company with its headquarters in Austin.

### Query shapes

Query shape mattered more than the choice of route. The Dutch query on SearXNG gave about 8 P and 2 N, with 2 on-target titles. One was a regional-paper interview with an Antwerp executive who invests in fintech from New York. The other was a national-paper feature on Belgian start-ups in New York. These were the best results of the whole test.

- **Without "Belgian".** Every route returned generic lists of New York fintech companies. Dropping the country word drops the Flanders tie.
- **`site:` filter.** SearXNG obeyed `site:tijd.be` and returned 10 tijd.be pages, about 4 P with 1 on target. It obeyed `site:kuleuven.be` too and found two lab alumni pages. On the tijd.be query, DuckDuckGo returned 0 results. On the KU Leuven query, it returned random kuleuven.be pages. The Claude web search ignored `site:kuleuven.be` and returned University of Texas pages.
- **French.** SearXNG answered from Google custom search alone, because Brave was rate-limited by then. It returned Belgian business press and two unrelated French Wikipedia biographies. The Claude web search found a Milken Institute speaker page and a Crunchbase profile of Belgian fintech people.

### Speed and dead links

SearXNG answered in 0.4 to 1.1 s, the DuckDuckGo HTML endpoint in 0.5 to 1.2 s, and the Claude web search in 12 to 22 s. Every Claude call ran one web search. Haiku cost $0.0126 to $0.0141 per call and Sonnet $0.0445, from `total_cost_usd`.

I fetched every result URL once. For the Claude web search, 60 of 72 unique URLs returned 200, 7 returned 404, 3 returned 403 and 2 timed out. Some 404s were on belganewsagency.eu and seedtable.com, and others were short `?p=` links. For SearXNG, 70 of 77 returned 200, with no 404s. Five were LinkedIn profiles that returned 999 and 2 returned 403. For DuckDuckGo, 56 of 62 returned 200, and 3 were LinkedIn with 999. FN can fetch the Claude URLs itself, but about 1 in 10 is dead.

### SearXNG engines and limits

The `searxng/searxng` image of 2026-11-12 enables these general engines: DuckDuckGo, Brave, Google custom search and three translation engines. It ships Bing disabled and Mojeek inactive, because Mojeek uses a proof-of-work CAPTCHA. On the first 8 queries at 2 s spacing, the engines that answered were DuckDuckGo, Brave and Google custom search. After that, only Google custom search answered: 12 more queries at 10 s spacing returned 20 results each. SearXNG suspends an engine for 3,600 s after a CAPTCHA and for 180 s after a 429, according to `suspended_times` in its default settings.

The image also ships `braveapi`, `marginalia`, `wikidata`, `yacy`, `startpage` and `qwant` engines. That means SearXNG can call the official Brave API with the owner's key instead of scraping Brave. I did not test those engines.

Google custom search (`google_cse.py`) declares `use_official_api: False` and reads the public element's JSONP. The robots.txt of `cse.google.com` disallows `/`, and that of `search.brave.com` disallows `/search`. Enabling those two engines is the owner's call. With only the engines whose terms are clean, SearXNG keeps DuckDuckGo, which blocked it after 4 queries, plus any keyed APIs the owner adds.

## How many searches a day each route can carry

One FN search is up to 5 queries. Neither a published nor an observed ceiling exists for most free routes, so each row below says what I measured.

| Route | Queries a day | FN searches a day | Basis |
|---|---|---|---|
| Parallel | no cap checked; spend-limited | owner's budget | $0.001 a query plus $0.001 a page read |
| SearXNG, Google custom search only | at least 20 in 3 min; daily ceiling not checked | not checked | this test |
| SearXNG, DuckDuckGo and Brave scraping | 4 and 8 before a block | under 2 an hour | this test plus suspend times |
| DuckDuckGo HTML direct | at least 8 at 4 s spacing; ceiling not checked | not checked | this test |
| Brave API, free credit | 1,000 a month, about 33 a day | about 6 | $5 credit at $5 per 1,000 |
| Mojeek API, Startup | 100,000 | 20,000 | Mojeek pricing page |
| Marginalia, public key | 1 of 13 answered | under 1 | this test |
| Claude web search | subscription limit, not checked | 15 to 20 s a query in sequence | this test |

## Page reading

The test fetched ten real result pages with httpx and ran four extractors on each:

- the standard-library `html.parser`, skipping script, style, nav, header, footer, aside and form
- the same parser, preferring `<main>` or `<article>`
- trafilatura 2.3.1 with `favor_recall=True`
- readability-lxml 0.9

The extractors ran from a throwaway environment, not from the project. Fetch times were 0.19 to 1.29 s, plus one page at 9.36 s.

| Page type | HTTP | stdlib main chars | trafilatura chars | readability chars | Outcome |
|---|---|---|---|---|---|
| Delegation event page | 200 | 446 | 440 | 47 | the page names no panelists; readability failed |
| CNN video page | 200 | 2,719 | 1,481 | 386 | only stdlib and readability kept the line naming both analysts; trafilatura picked the related-videos list; the page is 4.9 MB, near net.py's 5 MB cap |
| LinkedIn post | 200 | 1,720 | 1,247 | 1,247 | readable without login; profiles returned 999 |
| Regional newspaper interview | 200 | 20,716 | 10,968 | 12,086 | full article, no paywall; stdlib adds related links |
| National newspaper feature | 200 | 19,689 | 9,568 | 9,533 | full article; stdlib adds 6 photo captions |
| University lab alumni table | 200 | 29,847 | 31,739 | 29,144 | all three kept the names; trafilatura keeps the table as markdown |
| SEMI speaker biographies | 403 | 16 | 41 | 0 | bot block |
| KU Leuven alumni chapter team | 200 | 67 | 474 (menu only) | 0 | JavaScript-only |
| ESAT report PDF | 200 | n/a | n/a | n/a | PDF; `pdftotext` (Poppler, installed on this Mac through Homebrew) gave 128,770 chars in 0.18 s |
| Milken speaker page | 200 | 1,183 | 986 | 920 | all fine |

Over the nine HTML pages, the stdlib pass took 131 ms in total, trafilatura 418 ms and readability 358 ms. The stdlib pass returned 78,086 characters, trafilatura 56,944 and readability 53,363, so stdlib carries about 37% more text than trafilatura. Because web.py caps a page at 12,000 characters before the model reads it, boilerplate at the end of a long article can push out real text. On the two newspaper pages, the article came first in the stdlib text, so the cap would cut related links rather than the article.

Three of ten pages failed every local extractor: one 403, one JavaScript-only page and one PDF. Parallel Extract may read those, but that is not checked, because Parallel was out of scope.

## Recommendation for the search step

Add a `search_backend` setting with three adapters behind one function that returns ranked URLs and titles. The adapters are `parallel`, today's code, `searxng` and `claude`.

1. **Default `searxng`.** FN sends GET `{searxng_url}/search?format=json&q=...` through `net.Client`, which already allows plain http and caches GET responses. The owner chooses engines in SearXNG's `settings.yml`, so switching engines or adding the Brave or Marginalia API keys needs no FN change. The owner has to decide on Google custom search, given its robots.txt.
2. **Fallback `claude`.** Use it when SearXNG is down or returns fewer than 5 results. It needs no new key, but it is slow and drifts off topic, and about 10% of its URLs are dead.
3. **Query writing.** Whatever the backend, this test says to send each topic query in English and in Dutch, and to add `site:` queries for Belgian press and university domains. Keep "Belgian" or "Flemish" in the query. These shapes changed results more than the choice of route did.

Do not adopt `ddgs`, GDELT, Common Crawl, Wikipedia search or Marginalia's public key as a search route. They failed or timed out on most calls, or they cannot search by keyword. Wikidata SPARQL found the only on-target Q3 person, but it is a structured lane for alumni of a named university at a named kind of company, not a web search.

## Recommendation for the page-reading step

Make FN fetch result pages itself through `net.Client`. Read HTML with the standard-library parser that prefers `<main>` and `<article>`, then cut to 12,000 characters as today. Use `pdftotext` through a subprocess for PDFs when the binary is on the PATH. Send a page to Parallel Extract only when a key is set and the local read fails, meaning a 403, a 999, under 300 characters of text or a PDF without `pdftotext`. Move to trafilatura when the owner approves it. The tech reference lists it as approved on 2026-10-29, but `pyproject.toml` does not install it. Trafilatura adds less boilerplate, tables as markdown, and page dates through htmldate, which FN needs for dated claims.

## Exact dependencies per option

Each option below lists what it would add to `pyproject.toml` and the machine. The project today installs fastapi, httpx, pydantic and uvicorn.

- **Stdlib reader, DuckDuckGo HTML, Wikidata SPARQL, Claude web search:** no new Python package.
- **SearXNG:** no new Python package. It needs Docker (29.9.1 is installed, and the daemon must be running) and the `searxng/searxng` image, which is 381 MB. It also needs a `settings.yml` with `search.formats: [html, json]` and a secret key, and a port such as 8820.
- **PDF text:** the Poppler `pdftotext` binary outside Python, already present here, or `pypdf` as a new package (not tested).
- **trafilatura 2.3.1:** courlan (babel, tld, urllib3), htmldate (dateparser with python-dateutil, tzdata, pytz, regex, tzlocal), justext, lxml, certifi and charset-normalizer.
- **readability-lxml 0.9:** chardet, cssselect and lxml. Not recommended, because it lost to the stdlib pass on two of nine pages.
- **ddgs 9.16.1:** click, lxml and primp. Not recommended.
- **Brave or Mojeek API:** no new package, one host in `KEYS` and one Keychain entry.

## What must stay configurable to switch back to Parallel

- `search_backend` set to `parallel`, `searxng` or `claude`, plus `searxng_url`.
- `page_reader` set to `parallel_extract` or `local`, plus a `parallel_fallback` flag, so Extract can still read the pages FN cannot.
- The Parallel key path in `KEYS` and `MissingKey`, unchanged. Without a key, today's lane returns a note, and the local backends should do the same when SearXNG is unreachable.
- The source kind. Locally fetched pages should not be stored as `vendor_page`. A separate kind keeps the score runs comparable across backends.
- `MAX_CHARS` and the fetch timeout per backend, since local fetches return up to twice the text of trafilatura.

## Not checked

- Quality on the gold set. This test used three questions and title-level labels, not the gold picks.
- Daily ceilings for SearXNG with Google custom search and for the DuckDuckGo HTML endpoint.
- DuckDuckGo's and Google's terms of service text, beyond robots.txt.
- Brave and Mojeek result quality, because I created no account.
- YaCy, Startpage, Qwant and Stract.
- Whether Parallel Extract reads the 403, JavaScript-only and PDF pages.
