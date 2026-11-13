# Plan: who comes back and in what order

This section covers decisions R1 to R8 of [design.md](design.md) and the lead's rulings on legacy chips, origin, topic claims, the fourth heading, `web_topic`, one web search function, seven tiers, the stored fit, which lists give a strong tie, related words as topic evidence, the OpenAlex cap, stored searches gaining nobody, the order inside a tier (role met, then own words before related words, then grade, place, topic words, score) and tier 6 split by the tie under headings 3 and 4. R9 and the web backends are planned in [plan-web.md](plan-web.md); both call `websearch.find`, which Q-5 adds. The pages (U1 to U9) are planned apart in [plan-pages.md](plan-pages.md) and read `Candidate.tier`, `Candidate.fit` and `rank.heading`. The order of all tasks in both tracks is under "Order across both tracks" below.

## Tasks, in order

| Task | One line | Needs |
| --- | --- | --- |
| [Q-1](tasks/q-1-prompts-and-contracts.md) | Parse returns roles, tie, need, related words and version 2; the page reader returns origin and topics; nothing reads them yet | none |
| [Q-2](tasks/q-2-local-search.md) | The local search covers mentions and profiles always, OpenAlex records when research is asked, role words in pass 1, related words in pass 2 | Q-1 |
| [Q-3](tasks/q-3-evidence.md) | Tie grades by kind and seed list, role fit, related words as topic evidence, org names and page titles no longer give a full topic match | Q-1 |
| [Q-4](tasks/q-4-tiers.md) | Seven tiers under four headings, the no-tie cut, the demotion, the OpenAlex cap, the exemption cap, the stored tier and fit (migration 012) and scorecard counts | Q-1, Q-3 |
| [Q-5](tasks/q-5-lanes.md) | OpenAlex skipped without research, role chips in web queries, `websearch.find`, the `web_topic` lane | Q-1, Q-4 |

Q-2 and Q-3 run at the same time after Q-1: Q-2 touches only `lanes/seeds.py` and its test file, Q-3 only `evidence.py`, two type lines of `contracts.py`, one line of `rank.py` and their test files. Q-4 and Q-5 run one after the other: both touch `contracts.py`, and Q-5 counts the tiers Q-4 saves.

## File map

| File | Q-1 | Q-2 | Q-3 | Q-4 | Q-5 |
| --- | --- | --- | --- | --- | --- |
| `src/fn/contracts.py` | Chip, Place, Chips, Relation, PageTopic, Located | | TieGrade, RoleFit | PlaceFit, CardFit, Candidate.tier and .fit, CutReason | LaneName, LaneIn |
| `src/fn/prompts/parse.md`, `parse.py` | changed | | | | |
| `src/fn/prompts/extract.md`, `extract.py` | changed | | | | |
| `src/fn/store.py` | `unlocated_places` | | | tier and fit columns | |
| `src/fn/present.py`, `src/fn/web/debug.py` | origin ("Origin: {value}"); chips form | | | | |
| `src/fn/lanes/seeds.py` | | changed | | | |
| `src/fn/evidence.py` | origin is no place | | changed | | |
| `src/fn/rank.py` | | | `run` uses `card_of` | changed | |
| `src/fn/migrations/012_candidate_tier.sql` | | | | new | |
| `src/fn/score.py` | | | | tier counts | |
| `src/fn/websearch.py`, `lanes/web_topic.py` | | | | | new |
| `src/fn/lanes/web.py`, `lanes/__init__.py`, `search.py` | | | | | changed |

## Interfaces

| Name | Type | Made by | Read by |
| --- | --- | --- | --- |
| `Chip.need`, `Place.need` | `Literal["must", "nice"]`, defaults "must" and "nice" | Q-1 | Q-1 (`tie_must`); place and topic need are stored only |
| `Chip.related` | `list[str]`, at most 6, cleaned by `parse.clean_related` | Q-1 | Q-2, Q-3 (topic and role related words) |
| `Chip.research` | `bool \| None`, set on role chips only | Q-1 | Q-1 predicates, Q-3 |
| `Chips.roles`, `Chips.tie`, `Chips.version` | `list[Chip]`, `Chip \| None`, `int` (1 stored before, 2 from parse) | Q-1 | Q-2 to Q-5; the pages read neither `Chips.tie` nor `Chips.version`, only the stored tier and fit |
| `Chips.queries` | `list[WebQuery(text, lang)]`, written by the parse call (W2) | Q-1 | Q-6a (`websearch.queries`) |
| `parse.tie_must(chips) -> bool` | false for v1; else a tie chip with need must | Q-1 | Q-4, Q-5 (pages never read it) |
| `parse.asks_researchers(chips) -> bool` | v1, or any role chip with research | Q-1 | Q-4 (cap) |
| `parse.wants_research(chips) -> bool` | `asks_researchers` or no role chip | Q-1 | Q-2, Q-5 |
| Relation `origin`, `PageTopic`, topic claims of web people | location claim without coordinates, read as "Origin: {value}" by `present.what_of`; `ClaimKind` "topic" | Q-1 | Q-3, UI-2, UI-4 |
| `seeds.excluded(chips)`, `seeds.related_query(chips, first)` | `tuple[SourceKind, ...]`, `str` | Q-2 | seeds only |
| `evidence.card_of(identifiers, records)` | `dict[str, frozenset[str]]` with `seed:<list>` markers | Q-3 | `rank.run` |
| `TieGrade`, `RoleFit` | `Literal["strong", "medium", "weak", "none"]`, `Literal["met", "fails", "unknown"]`, in `contracts.py` | Q-3 | Q-4, UI-4, UI-5 |
| `evidence.STRONG_LISTS` | `frozenset({"baef", "francqui", "fayat", "consuls", "climate"})`; every other seed list is medium | Q-3 | evidence only |
| `Tie.grade`, `Tie.claim_ids` | `TieGrade`; claim ids strongest first | Q-3 | Q-4 |
| `Topic.related` | `bool`: the match holds only through a related word | Q-3 | Q-4 (order) |
| `Evidence.role` | `Role(fit: RoleFit, claim_ids: tuple[str, ...])` | Q-3 | Q-4 |
| `rank.tier(found, question) -> int` | 1 to 7 | Q-4 | Q-4 |
| `rank.heading(tier: int, tie_grade: TieGrade) -> int` | 1 to 4; tier 6 gives 3 with a strong or medium tie, else 4; tier 7 gives 4 | Q-4 | UI-5 |
| `rank.place_fit(found, question) -> PlaceFit` | `Literal["inside", "outside", "abroad", "unknown", "none"]`, none without a place chip | Q-4 | Q-4 |
| `Candidate.tier` | `int \| None`, None before migration 012 | Q-4 | Q-5, UI-5, score |
| `Candidate.fit` | `CardFit \| None`: `tie_grade: TieGrade = "none"`, `tie_claim_ids: list[str] = []` (strongest first), `place: PlaceFit = "none"`, `role: RoleFit = "unknown"`; column `fit_json`; None before 012 and without evidence | Q-4 | UI-4 (card lines, geo `place_fit`), UI-5 (heading) |
| `CutReason` `no_tie` | new value | Q-4 | pages (cut people are not shown) |
| `LaneIn.first_heading` | `int \| None` | Q-5 (`search.first_heading`) | `web_topic` |
| `websearch.find(ctx, objective, queries) -> Found` | `Found(pages: list[Page], considered, note)` | Q-5 | `web`, `web_topic`, the R9 batch later |
| `websearch.rule_queries(chips) -> list[str]` | one per topic and role with the place, then institutions; at most 5 | Q-5 | `web`, `web_topic`; Q-6a's `websearch.queries` |

Owners added or changed, as in the design's table: `parse.wants_research` (Q-1), `lanes/seeds.py` scope (Q-2), `evidence.py` grades, role and related-word evidence (Q-3), `rank.py` tiers and the stored fit (Q-4), `websearch.py` and `lanes/web_topic.py` (Q-5). The tier-to-heading number is `rank.heading`; the heading words are `present.py`'s (UI-5). Whether the tie is a must is `parse.tie_must`'s alone; the pages read only the tier and the fit.

## One search after this round

```diff
 search.run(ctx, search)
   parse.run(ctx, ParseIn)
     llm.structured("parse", ...)            # new prompt and schema: every recorded answer misses once
+    parse.clean_related(chip)                # per topic and role chip
+    chips.version = 2
   run_step("lane:seeds", seeds.run)
+    seeds.excluded(chips) -> parse.wants_research(chips)
     seeds.fts_query(chips, aliases)          # + role chip words
     store.match_claims(query, exclude)
+    seeds.related_query(chips, query)
+    store.match_claims(related, exclude)     # pass 2, ranked after pass 1, cap 300 over both
     seeds.near(ctx, area, chips)             # also when only roles and a city
   publish -> resolve.run, rank.run, store.save_candidates
-  run_step("lane:openalex", openalex.run)
+  parse.wants_research(chips) ? run_step("lane:openalex", openalex.run) : skip_step("lane:openalex", ...)
   publish
   run_step("lane:web", web.run)
-    http.post(SEARCH_URL), http.post(EXTRACT_URL)
+    web.collect(ctx, web.objective(chips), websearch.rule_queries(chips), "web")
+      websearch.find(ctx, objective, queries)
       extract.read_all -> llm.structured("extract", ...)   # new prompt: origin and topics
+      extract.check -> topics kept near the mention
       extract.drafts                         # + origin location claim, + topic claims
   publish
+  search.first_heading(ctx)
+  run_step("lane:web_topic", web_topic.run, lane_in(first_heading=n))
+    chips.version == 1, parse.tie_must(chips) # gate: v1, must, or 20 or more under heading 1, gives a note
+    web.collect(ctx, web.objective(chips, tie=False), websearch.rule_queries(chips), "web_topic")
+  publish
   run_step("lane:linkedin", linkedin.run)
   finish: resolve.run, rank.run
-    schemes = {p: frozenset(i.scheme ...)}
+    evidence.card_of(identifiers, records)
     evidence.of(card, claims, facts, question, today, names)
-      evidence.tie(card, claims, facts, found, inst)
+      evidence.tie(card, claims, facts, found)   # kinds and grade
+      evidence.topic(claims, chips, card)        # org names and page titles give words, not a match; related words match
+      evidence.role(claims, card, question)
     rank.fuse
-      rank.group, rank.band
+      rank.tier, rank.heading, rank.place_fit, rank.fit_of
       rank.cut_reason
+      exemption of 20 (version 2 only), rank.no_tie, OpenAlex cap of 5 in the first 20
   save -> store.save_candidates                # + tier, fit_json
```

## Inputs a real run will meet

| Input | Test in |
| --- | --- |
| Chips stored before this round (no roles, tie, version): tie not a must, research asked, no `web_topic`, nobody let back in from the cut | Q-1 contracts and predicates; Q-4 legacy rules; Q-5 gate and replay |
| A model answer with no roles, no tie, no related words | Q-1 |
| Role or tie span off by up to 2, or by 5 | Q-1 |
| Twelve related entries; generic-only entries; an entry equal to its chip; related on an institution or tie | Q-1 |
| Dutch and French related words with accents | Q-1 |
| Rerun from the debug chips form of a v2 search | Q-1 |
| Origin "American"; a topic missing from its quote, far from the mention, or repeated | Q-1 |
| Roles and a city only | Q-2 (place search), Q-5 (web query) |
| Related phrase with quotes, hyphens or "AND" | Q-2 |
| More than 300 hits over two passes; one person in both passes | Q-2 |
| A question with only non-research roles, against one with a research role | Q-2, Q-5 |
| A card mixing a web mention and a seed record | Q-3 |
| A page title standing in for a role | Q-3 |
| An org name holding every topic word | Q-3 |
| A Wikidata seed row tied only by an employer; a seed list key FN does not know | Q-3 |
| A related word in a claim, with and without an own-word match | Q-3, Q-4 |
| "Research scientist" at a company and at a university | Q-3 |
| Mixed research and non-research roles | Q-3, Q-4 |
| Must tie with nobody tied | Q-4 |
| 25 people let back in from the cut | Q-4 |
| A heading that ends inside the first 20 with many OpenAlex-only people | Q-4 |
| Stored candidates from before migration 012 (tier and fit None) | Q-4, UI-4, UI-5 |
| Tier 6 with and without a tie | Q-4, UI-5 |
| No Parallel key, no results, the same page in both web lanes | Q-5 |
| 20 or more people under the first heading | Q-5 |

## Order across both tracks

This section owns the order of every task in both plans; [plan-pages.md](plan-pages.md) points here. Each task merges on its own, rebased on main, with `uv run python -m unittest` green.

| Wave | Tasks that may run at the same time | Merge rule |
| --- | --- | --- |
| 1 | Q-1; UI-0 (in the design system's working copy, not this repository) | Q-1 merges first of all repository tasks |
| 2 | Q-2, Q-3, UI-1 | each after Q-1; UI-1 also after UI-0 |
| 3 | Q-4, UI-2, UI-3 | Q-4 after Q-1 and Q-3; UI-2 and UI-3 after UI-1 |
| 4 | Q-5, UI-5, UI-4 | Q-5 after Q-4; UI-5 after UI-1 and Q-4; UI-4 after UI-2, Q-4 and UI-5 (both change `present.results`) |
| 5 | Q-6a, Q-7a; then Q-6b, Q-7b; then Q-8 | Q-6a after Q-5; Q-6b after Q-6a; Q-8 after Q-6b; Q-7a any time (it needs no other task); Q-7b after Q-7a |

Why each rule holds:

- Q-1 before any pages task that edits `present.py`. UI-1 to UI-5 all do (`walk`, the fact lines, the source sentence, the card lines, the headings), and Q-1 changes `what_of` and `place_of` there for the origin relation.
- UI-1 is the only task that copies the design-system bundle into `src/fn/web/static/fn.css` and pins its hash (`tests/test_results_page.py:25`). A later task that needs a new class stops and asks for a design-system change.
- UI-5 and UI-4 need Q-4: they read `Candidate.tier`, `Candidate.fit` and `rank.heading`, and their hand checks run `fn-rerank --all` to fill them.
- Q-4 and Q-5 run one after the other: both touch `contracts.py`, and Q-5 counts the tiers Q-4 saves.
- Tasks in one wave touch different functions. Shared files (`contracts.py`, `present.py`, `staff.py`, `parts.py`, `tests/test_web.py`) conflict only in import lists, new classes and different tests; resolve by keeping both.
- Migration 012 is Q-4's. No pages task adds a migration.

## Done check

- Every task merged with `uv run python -m unittest` green and no existing test changed beyond the ones its task names.
- `fn-score run <snapshot> --mode rerank` on main and after Q-4, then `fn-score compare`: no gold pick main keeps is cut and no person main cuts is kept (version-1 chips make no tie a must and let nobody back in); `pairs_wrong` 0; tier sizes and `first_heading_under_5` reported. The people the exemption let back in are reported after the live-preferring run.
- The lead's paid live-preferring run of the dev gold cases (`FN_LLM=prefer FN_HTTP=prefer fn-gold`) re-reads the stored pages with the new extract prompt; then `fn-score snapshot` and `--mode rescore`, and `--mode replay` is no longer degraded on that snapshot.
- The benchmark of [research/benchmark.md](research/benchmark.md) on the ten development questions: I10 rises by more than twice the judged noise; the held-out questions and the guards do not fall.
- `/debug/stats` shows `lane:web_topic` seconds and cost, and `lane:openalex` skipped on questions with only non-research roles.
