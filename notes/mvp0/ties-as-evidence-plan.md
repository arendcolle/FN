# Remove the tie label and rank on affiliation claims

2026-11-02 · plan for the owner's decision "ties are evidence, not a label" in `architecture.md`, revised after an independent review and three owner decisions

**TL;DR.** The tie label goes everywhere, including a hidden copy inside the OpenAlex lane. Institutions become records with facts from ROR, Wikidata or OpenAlex, each with its source. The ranker gets one new ranked list, people ordered by how many dated years their claims place them at a Belgian organization, and fuses it with the lane rankings by the same reciprocal rank fusion it already uses. No weight is set by hand. Cards and the gold report show the claims behind the score; nothing turns them back into a label.

## Owner decisions (2026-11-02)

- Every Belgian organization counts the same for ranking. Region and name language are shown on the card only.
- Any claim that places a person at a Belgian organization counts: studied, worked, member (KVAB foreign members too), fellow, consul, hosted.
- fn-gold prints the gold tie next to the evidence and gives no verdict.

## What the data allows (checked 2026-11-02)

- ROR records carry a region code (KU Leuven `VLG`, VUB and ULB `BRU`, UCLouvain `WAL`, MIT `MA`) and the language of the `ror_display` name (VUB `nl`, ULB `fr`). Both are shown, not scored.
- ROR's affiliation matcher picked an institution for 34 of the 80 most common seed spellings, 2 of them wrong. Spelling-to-institution stays a hand-kept list of ids.
- KVAB has no ROR record. Wikidata Q1301699 gives its country through P17 (Q31) and that item's P297 (`BE`).
- OpenAlex institution records, which the lane already fetches, carry the ROR id and the country code, so the lane adds no calls.

## Design

1. **Institution identity.** `data/ties.csv` becomes `data/org_aliases.csv` with `alias` and `org_id`, where `org_id` is `ror:<id>` or `wikidata:<Q>`. The region column and the old internal ids (`ku-leuven`, `kvab`, `baef`, `belgium` and the rest) go, in claims and role claims alike. `fn/orgs.py` replaces `fn/ties.py`: `orgs.org_id(text)`, `orgs.ref(text)` for parse, `orgs.names(org_id)` for the seed lane. Parse refs take the same `ror:<id>` form.
2. **Institution facts.** Migration 002 adds `orgs(id, name, country_code, region, name_lang, source_id, fetched_at)`. `orgs.save(store, facts, source)` is the only writer. `fn-orgs` fetches every id in the alias file from ROR or Wikidata through `net.py` and saves it. The OpenAlex lane saves the institutions it already fetched, from their OpenAlex records. Each row points at the Source it came from. An empty fact stays empty.
3. **Claims.** `store.upsert_claim` updates `org_id` and `relation` on a known claim id, so rerunning fn-seed moves the 13,394 stored claims to the new ids. `CONTRACTS_VERSION` becomes 2, and the trace page skips payloads from version 1 with a note.
4. **The OpenAlex lane stops ranking by Belgian share.** It orders kept authors by place group, then by where they appeared in the works and author lists, and returns every kept author, at most 800 per institution chip, with no 100-hit cut. Its Belgian-affiliation filter stays and is named as the lane's scope.
5. **Ranking.** `rank.py` fuses ranked lists with `1 / (60 + rank)`, as now. The lane rankings are lists; the new list is `belgian_years`. It orders entries by the number of distinct calendar years covered by the claims of their lane-hit records at organizations with `country_code = BE` (a year span from `valid_from` to `valid_to`, else the year of `claim_date`, else one undated unit). Entries with none are not on that list. Records joined only by a shared name are shown, never scored. Each Candidate stores `score_parts: list[ScorePart(feature, rank, points, claim_ids, detail)]`, and the parts sum to the score.
6. **Cards.** Each card lists the claims at Belgian organizations, with institution, region, name language, years, quote, source and date, and the score parts. A person with none shows "No Belgian organization found in" and the sources read. No badge, no filter.
7. **Gold runner.** For each pick, the report prints the gold tie, the `belgian_years` count and its best claims. The agreement column goes, and acceptance criterion 9 changes to match.

## What goes

| Item | Where |
| --- | --- |
| `TieType`, `TieLabel`, `TieIn`, `TieOut`, `Candidate.tie`, the tie fields of `PickResult` and `TopCard`, `GOLD_TIE` | `contracts.py`, `gold.py` |
| the `tie` step and its trace row | `search.py`, `web/app.py` |
| `ties.label`, `combine`, `run`, `REGION_TIE`, `RULES_VERSION`; `ties-unmapped.txt` becomes `org_aliases_unmapped.txt` | `ties.py` → `orgs.py`, `data/` |
| the Belgian-share score and `HIT_LIMIT` | `lanes/openalex.py` |
| internal org ids | `seedload.py` LISTS and relations, `lanes/seeds.py`, `lanes/openalex.py`, `parse.py`, `store.py` |
| `candidates.tie_json` | migration 002: `ALTER TABLE candidates DROP COLUMN tie_json`, `ADD COLUMN score_parts_json TEXT NOT NULL DEFAULT '[]'` |
| `tie_text` and the tie line on cards | `web/app.py` |
| tie assertions | `test_ties` → `test_orgs`; `test_rank`, `test_web`, `test_gold`, `test_map`, `test_seeds_lane`, `test_openalex`, `test_seedload`, `test_parse` |

Those tests change because the owner removed the feature they test, not to make a change pass.

## Build decisions (2026-11-02, from the task 1 builder's questions)

- **fn-orgs runs as a job through `run_step`.** Migration 002 adds `searches.kind` (`search` or `job`, default `search`), and fn-orgs stores one `job` row with one `orgs` step, so its calls, log and traceback show on the debug pages. The searches list shows only kind `search`.
- **net.py sends a descriptive User-Agent on every request:** `FN/0.1 (https://github.com/arendcolle/FN) httpx/<version>`, as Wikimedia's policy asks. The contact is the repository URL, not an email address.
- **Migration 002 rewrites old org ids in place.** It updates every stored claim (seed and OpenAlex) from the old internal ids to the new ids with explicit statements, and sets any old id with no new id to empty. No stale id is left for a later search to fix.
- **Org rows from the OpenAlex lane** come from the affiliations in the author records it already reads: `ror:<id>` when OpenAlex gives one, else `openalex:<I…>`. A lane save never replaces a stored row; an fn-orgs save always does.
- **Until task 2 removes the label,** the tie step reads org facts. This is temporary code that task 2 deletes.
- **`record_source` moves to contracts.py** to avoid an import cycle between orgs.py and the OpenAlex lane.

## Build decisions (2026-11-03, task 3)

- **Hit records are named in the entry.** `Entry.hit_person_ids` lists the records that are a lane hit; resolve fills it before adding same-name records. Only those records score.
- **Units are a set.** A person's count is the number of distinct units over all counted claims: each calendar year, plus one `undated` unit if any claim has no date. Two sources for the same year count once. A span whose end is before its start counts its endpoint years and the year of its claim date.
- **Equal counts share a rank** (1, 2, 2, 4), so no arbitrary order enters the score.
- **Only years the source lists count** (from the task 3 review). OpenAlex lists an affiliation's years with gaps ("2023, 2012" for one ULiège record), and 8,453 of 32,948 stored OpenAlex claims have gaps. Filling the span from first to last year counted years no source states. `Claim.years` (migration 005) holds the years the source lists. The count uses them when present and the span rule otherwise. Seed claims have no listed years, so the span rule still applies to them.
- **Cards and fn-gold mark what scored.** A Belgian claim in the belgian_years part is marked scored; the others, on same-name records, are shown unmarked. fn-gold also prints the stored Belgian claims of a pick that is not in the result list.

## Tasks

1. **Institutions as records.** `orgs.py`, `data/org_aliases.csv` with the 31 aliases that have no ROR id looked up by hand (ILVO, INBO, EnergyVille, KVAB, RMI, BIRA-IASB, RBINS and 24 US institutions), the `orgs` table, `fn-orgs`, the OpenAlex lane saving org rows, the claim upsert update and the fn-seed rerun. Tests: every alias resolves to an id in the file's form; `fn-orgs` with recorded responses writes VUB `BE`/`BRU`/`nl`, ULB `BE`/`BRU`/`fr` and KVAB `BE`; a failed fetch stops `fn-orgs` with the id and status; rerunning fn-seed rewrites org ids and changes nothing on a second run. Hand check: `fn-orgs` live, then the orgs rows for VUB, ULB, KU Leuven and KVAB.
2. **Remove the label, keep plain RRF.** Everything in "What goes", with plain lane fusion and the OpenAlex lane change. Run `fn-gold GS-02 GS-10` live and record where each pick lands; this is the baseline for task 3, and it may miss the target because the hidden Belgian share is gone. Tests: the done-check grep is empty; old v1 payloads do not break the trace page; the lane returns all kept authors in seen order.
3. **Add the `belgian_years` list.** Tests: year counting with spans, single years and undated claims; a name-only record never scores; score parts sum to the score; Sweldens' KVAB claim puts him on the list. Measure GS-02 and GS-10 against task 2's baseline and report both.
4. **Docs and diagram.** `architecture.md` (contracts, storage, workflow, rules, responsibility table, acceptance criterion 9) and the diagram page.

## Responsibility changes

| Responsibility | Owner |
| --- | --- |
| Spelling to institution id | `orgs.py` with `data/org_aliases.csv` |
| Institution facts, from ROR, Wikidata or OpenAlex | `orgs.save`, called by `fn-orgs` and the OpenAlex lane |
| Turning claims into ranked lists and fusing them | `rank.py` |

## Inputs the spec does not mention

| Input | Behaviour | Task |
| --- | --- | --- |
| A spelling not in the alias file | the claim keeps `org_id` empty and does not count; the card names the spelling | 1 |
| An alias id ROR or Wikidata does not know | `fn-orgs` stops and names the id | 1 |
| An OpenAlex institution without a ROR id | saved under its OpenAlex id with its country | 1 |
| A claim with no date at a Belgian organization | one undated unit | 3 |
| Two records that share only a name | shown on one card; only lane-hit records score | 3 |
| A search stored before this change | its page renders; its trace says the payload is from contracts v1 | 2 |

## Not doing

- Weighting Flanders above Wallonia or by language, or letting the question choose; settled by the owner for this slice.
- A place feature in `rank.py`: the OpenAlex lane already orders by place, and seed hits have no distance.
- Birthplaces through GeoNames and company records: no such claims exist yet.
- A tie badge or filter: they come with the list page, computed from claims when shown.
- Paging the results page. With the OpenAlex hit cut gone, the MIT search renders 387 candidates in 5.9 MB of HTML in 0.36 s; at the 2,000-author cap that should be about 30 MB. Acceptable on the laptop for this slice.

## Done check

- The whole suite passes.
- `grep -rn -E --exclude-dir=migrations "\bTie[A-Z]|\bties\b|tie_json|tie_text|GOLD_TIE|\.tie\b|HIT_LIMIT" src tests` prints nothing. Migrations are excluded because 001 is applied and never edited, and 004 names the column it drops.
- `fn-gold GS-02 GS-10` after task 3 is compared with task 2's baseline and with the old run (3 of 4), and the report says which picks moved and why. The target is not tuned to: if task 3 finds fewer than 3 of 4, that result is reported.
- A screenshot of the GS-10 results page shows Belgian claims with region, years and score parts, and no tie line.
