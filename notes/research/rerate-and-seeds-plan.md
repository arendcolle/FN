# Re-rate the terms drops and scrape the seed lists

2026-10-29 · plan for the step after the terms decision in `mvp-tech-reference.md`

**TL;DR.** Two jobs run in one workflow. Opus agents re-rate the 37 findings that failed the old K6 rule, plus Exa's people category, and a second Opus pass tries to refute every verdict that is not a drop. Sonnet agents write one scraper script per seed list (US honorary consuls, BAEF, KVAB, Francqui, Belgian Climate Centre) that writes JSONL rows with a verbatim quote. I then check the files myself with one check script and write the results into `findings.json`, the reference doc and the one-pager.

## Done when

- Every re-rated finding in `findings.json` has a new verdict, `verdict_before`, `round: "k6-rerate"` and facts checked on 2026-10-29.
- Every drop names a knockout other than K6, or the pick it duplicates. A verifier has attacked every verdict, drops included, and I settled each conflict.
- `uv run --managed-python scripts/seeds/check.py` passes. It holds the only copy of the expected counts and gold picks. Each expected count comes from a verifier agent's own hand count, never from the scraper's output, with tolerance 0. BAEF is also checked per year from 2012 to 2019 against the page's own "N Belgian Fellows" lines, and every Climate Centre row needs a name from its page's `<h1>`.
- Gold picks are checked by full name, so namesakes (Wim Dewulf, Geert Deconinck, Frederik Maes) do not count. A pick named only as a host professor or mentor does not count either.
- 20 random rows per list are reviewed by a verifier against the raw copy.
- The docs change wherever a new verdict contradicts them: the counts table, Not doing, Appendix B and the benchmark arms. A grep shows no Not doing entry that contradicts `findings.json`, and a coverage gain cites a probe file or says "expected".

## Rules for the re-rating

- The rubric is the round-1 rubric: adopt, benchmark, borrow, drop, with "no maybe" and at most one adopt per group of siblings.
- K6 now means "public pages and APIs FN can reach". Vendor terms, scraping bans, robots.txt, text-and-data-mining reservations and LinkedIn origin no longer fail K6.
- K1 to K5 stay as written.
- A vendor profile record, LinkedIn-derived included, may back a claim (settled in chat). The card quotes the profile field, links the profile URL even when it needs a login, and dates the claim by the record's own position dates, else the read date. It is marked "vendor record" so staff can tell it from a page FN read.
- LinkedIn data passes K6 through APIs and through scrapers such as Apify (settled in chat). Scrapers are still judged on speed and breakage, where the POC measured 3.4 s typical and up to 17 s.
- A paid self-serve plan passes K5 at any published price. Price counts against value, not as a knockout. Only a sales call fails K5 (settled in chat).
- A source that needs a registration or a personal login (journalist login, personal-use licence, member account) still fails K5 (settled in chat).
- Raters see name, URL, what it is, pricing and the facts that do not concern terms. They do not see the old verdict, why or knockout. `verdict_before` is added after rating.
- Each group's judge also sees the incumbent picks for the same job (Parallel and Exa for search, iTunes for podcasts, OpenAlex for academics, Wikidata and FRIS for Belgian ties, EDGAR for business people).
- Probes are keyless and accountless. A source that needs a key is rated on its docs and published price, and the rater writes the probe a key would allow.

## Scope

| Group | Findings |
| --- | --- |
| LinkedIn people data | Exa people index (existing borrow row), Apify LinkedIn scrapers (new row), Clado, Pearch, Coresignal and Bright Data, Lessie, Apollo and Clearbit, People Data Labs, Happenstance, Sixtyfour, Juicebox, Diffbot Knowledge Graph |
| Talks and video | YouTube captions, YouTube channel feeds, Podcast Index, Listen Notes, Podchaser, Spotify, TED, Taddy |
| Search backends | Gemini grounding with the OpenAI and Gemini citation row, Gemini Deep Research, Brave (three rows merged), Perplexity people search |
| Belgian sources | Staatsblad and NBB, Belga.press, Expertendatabank and its back-up, VIW, De Ondernemer, Kunstenpunt, UiTdatabank, UiTwisselingsplatform, VAi, Flanders Literature, OceanExpert |
| Other | Semantic Scholar, GitHub user search, OpenSanctions PEP |
| Not re-rated | LinkedIn official APIs and Proxycurl: the route is closed because Proxycurl shut down and no LinkedIn API searches by topic |
| Text fixes only | Rows that keep their verdict but carry a void K6 condition (Exa Search, Exa Agent, Parallel FindAll, Perplexity Search, You.com MSA, Exa 4.2(a), Perplexity Addendum 2.3, the Flemish press TDM row): I rewrite `knockout_failed` |

## Seed lists

| List | Source | Gold picks by full name |
| --- | --- | --- |
| consuls | Belgian embassy page for US honorary consulates (dated "Last updated on July 16, 2026"); one row per person, states in `jurisdiction` | Anne Deconinck |
| baef | BAEF alumni page, 1920 to 2018 or 2019, every year imported with its year | Michel Goemans, Pierre Lermusiaux, Julien de Wit, Milena Janjevic; report Verdonck and De Cock if found |
| kvab | KVAB Jaarboek 2025, the whole "Samenstelling Academie, December 2025" section (PDF pages 129 to 137), parsed by its headings: every class, ordinary, honorary and foreign members, and the Jonge Academie | Pattie Maes, Valerie Trouet, Jeroen Dewulf, Wim Sweldens, Lieven Danneels |
| francqui | Complete-list-of-Francqui-Fellows-SEPT25.docx (last modified September 2025) | Michel Goemans |
| climate | Belgian Climate Centre expert sitemap, name from each page's `<h1>`, profile URL kept | Valerie Trouet, Hans Bruyninckx |

`scripts/seeds/common.py` owns fetching (one request a second per domain, declared user agent), saving the raw bytes plus a normalized text layer, normalization (NFC, NBSP to space, straight quotes) and the validated, atomic JSONL write. Its row schema is `list`, `row_key`, `name`, `name_on_page`, `year`, `role`, `institutions` (each `{name, relation}` with relation home, host, employer or member_of), `field`, `place`, `jurisdiction`, `profile_url`, `source_url`, `source_title`, `source_date`, `date_method`, `page`, `quote`, `raw_path` and `fetched_at`. The write rejects a quote without `name_on_page` and a quote absent from the text layer. Each list script guards on structure (the headings it expects, no empty names) and holds no expected counts. `data/seeds/raw/` is in `.gitignore`, because the Climate Centre pages alone come to about 350 MB.

## Inputs the sources will throw at the parsers

- The same person in two lists or two years: kept as separate rows; the Person resolver merges later
- Particles and accents (de Visscher, François): stored as on the page, NFC-normalized
- Titles and suffixes (Dr., Prof., PhD): kept in `name_on_page` and the quote, removed from `name`
- One consul covering several states: one row with every state in `place`
- Missing year, field or institution: null, never an empty string
- A changed layout, a 403 or a missing heading: the script exits non-zero and writes no JSONL
- Consuls: a name alone on its line, "Esq." and "(Lee)" inside names, states with no consul ("Please refer to the Consulate General"), a state split by county, and emails and phones kept out of the quote
- BAEF: "SURNAME, Given" in capitals, married names (Verly-MAIRLOT), particles (du BUS de WARNAFFE), nobility titles, "Ms./Dr.", "MD", "Jr.", name-only rows before 1990, typos, entries split over lines, and US host professors named inside an entry
- KVAB: "Surname Given (year)" for members against "Surname, Given (year)" for the Jonge Academie, baron and jonkheer, "'t Hooft", two columns, a year wrapped to the next line, a missing year, trailing periods
- Francqui: runs glued without a separator (CASERTPostdoctoral), line breaks inside a paragraph, mixed-case surnames (CARTON de TOURNAI, D'HALLUIN), a fragment with no given name, "(Collen-Francqui Fellow)" between name and text
- Climate Centre: slugs that are escaped or reversed, and "Belgian Climate Centre" itself in the institution line

## Responsibility table

| Responsibility | Owner |
| --- | --- |
| Fetch, save raw and text layer, normalize, validate and write rows | `scripts/seeds/common.py` |
| Parse one list into seed rows and guard its structure | that list's script in `scripts/seeds/` |
| Count each list by hand and review 20 random rows | a seed verifier agent per list |
| Expected counts and gold picks, checked against all seed files | `scripts/seeds/check.py`, written by me from the verifiers' counts |
| Load seed rows into FN | the Importer, not built yet |
| Rate one finding | a rater agent |
| Keep at most one adopt per job, against the incumbents | the group judge agent |
| Attack each verdict, drops included | a verifier agent |
| Record the chat answers, settle rater against verifier conflicts, write `findings.json` and the docs | me |

## Not doing

- Loading seeds into a database; there is no app yet
- Fayat, consuls outside the US, BAEF 2020 to 2026 (no public names) and enrichment through OpenAlex or Wikidata
- Creating accounts or keys, or paying for any source
- Committing; that waits for an OK
- Retrying pages that refused FN (403, login wall, CAPTCHA) through a headless browser. That gets around bot protection, so the press probe was dropped
