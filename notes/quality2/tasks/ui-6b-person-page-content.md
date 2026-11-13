# Task UI-6b: what the person and source pages say

## Goal

The rebuilt pages look right and say wrong things ([research/ux2-walk-new.md](../research/ux2-walk-new.md), [research/ux2-walk-check.md](../research/ux2-walk-check.md), [research/ux2-design-review.md](../research/ux2-design-review.md)). A professor at one university since 2009 opens as a professor at another, because one-year OpenAlex affiliations sort first. 28 of 143 pages show a page title as a job. All 10 pages with Wikidata facts show the day the record was read as a year. The summary calls a Liège tie Flemish and ignores the tie the ranker stored. The debris rule hides 1,165 of 2,746 web quotes. This task builds rulings V1 to V12 of [design.md](../design.md) on main as it is now.

## Before you start

UI-5 is merged and UI-6a is done; the lead gives you its folder `ds/` and the sha256 it reported. This task is the only one that copies design-system version 12: copy `ds/project/components/bundle.css` over `src/fn/web/static/fn.css`, `ds/STRINGS.md` and `ds/DESIGN-NOTES.md` over `notes/e2e/design-system/`, and set `BUNDLE_SHA` in `tests/test_results_page.py:25` to that sha. Copy markup and strings from `ds/project/components/{Claim,Profile,SummaryList,Quote,SourceText}/README.md` and `ds/preview/page-person-v12.html`, `page-source-v12.html`. If you need a class or string they lack, stop and report it.

## How a claim is dated, on main

`rank.units` (`rank.py:42`) mixes two kinds of date. The fact's own years: `Claim.years` (OpenAlex, `lanes/openalex.py:180-181`), `valid_from`/`valid_to` (pages `extract.py:200-203` with `stated_in_quote`; LinkedIn `lanes/linkedin.py:172-173`; ORCID `enrich.py:138-139`), and `claim_date` with `record_field` when a seed row has its own year (`seedload.py:98-99`) or a paper its year (`lanes/openalex.py:232`). The day a record was changed or read: `read_date` (OpenAlex place, `lanes/openalex.py:199`), `sheet_date` (`importer.py:236-237`), `staff_edit` (`network.py:206`, `:237`), and a seed row without a year, which takes its source's date and method (`seedload.py:100-102`): `page_date`, `sitemap`, `document_heading`, or `record_field` for Wikidata's "item modified" (`seedload.py:66`). So `record_field` alone does not tell them apart: 1,419 seed claims carry `record_field` with `claim_date` equal to `Source.source_date`, all Wikidata. No stored claim has a `claim_date` without a method.

## Owners

One owner per rule. A module calls the owner's function and never copies its rule.

| Rule | Owner |
| --- | --- |
| What a stated role is; what shows a tie; whether a tie lies in Flanders | `evidence.stated_role`, `evidence.shows_tie`, `evidence.in_flanders` |
| The tie's claims without a search | `evidence.tie`, called through `present.evidence_tie` |
| A fact's own years, the Work order, the head line, wording, sections, Sources rows, debris | `present.py` |
| Markup | `web/parts.py`; routes and the stored fit: `web/staff.py` |

## `src/fn/evidence.py`

1. `stated_role(claim: Claim, source: Source) -> bool`: `claim.kind == "role"`, `claim.relation is None`, and the value is not `source.title`, the url's host or the url (`extract.py:195` stores those when a page gives no role). `present.is_job` goes; its callers use this. `usable_role` stays for the ranker.
2. `TIE_RELATIONS = ("studied_at", "born_in", "origin", "lives_in", "fellow_of", "member_of", "consul_for")`. `shows_tie(claim: Claim, facts: dict[str, Org]) -> bool`: the claim's org is in `facts` with `country_code == "BE"`, or its relation is in `TIE_RELATIONS` and `BELGIAN_TEXT` finds `name_key(claim.value)`. A bare role or a topic never shows a tie.
3. `FLEMISH_TEXT`, a regex folded like `BELGIAN_TEXT`: flemish, flanders, vlaams\w*, vlaanderen, antwerp\w*, ghent, gent, leuven, hasselt, mechelen, bruges, brugge, kortrijk, aalst, genk, oostende, ostend. `in_flanders(claim: Claim, org: Org | None) -> bool`: `org.region == "VLG"` when the org has a region; else `FLEMISH_TEXT` on `org.city` and `org.name`; without an org, on `claim.value`. `Org.region` is ROR's `country_subdivision_code` (`orgs.py:130`): on the copy 22 of 542 Belgian orgs have one (`VLG` 10, `BRU` 8, `WAL` 4). Wikidata and OpenAlex orgs never do. Brussels (`BRU`) is not Flanders.

## `src/fn/present.py`

4. `prose(source: Source) -> bool`: kind in `PROSE` and the host is not `linkedin.com` or a subdomain of it (V9). Every `source.kind in PROSE` in `present.py` and `staff.py:270` calls it. `label_of` gives "LinkedIn record" for such a page.
5. `own_years(claim: Claim, source: Source) -> frozenset[int]`: `rank.units(claim)` without `claim_date`'s year when `claim_date` is the record's date: `date_method` in `("page_date", "sitemap", "wayback_first_seen", "document_heading", "read_date", "sheet_date", "staff_edit")`, or `claim_date == source.source_date`. The years list and the `valid_*` range are always own. `span_words(years) -> str`: "2009–2026", "2015" or "". `claim_view` sets `years` to `span_words(own_years(...))`, and the new `ClaimView.all_years: str = ""` to `rank.years_text` of them when they have a gap (V2). The ranker keeps `rank.units`.
6. `what_of` (V4): `affiliated_with` reads "Named at"; topic "Topic: "; `lives_in`, and a location without relation from a prose source, "Lives in"; a role starts with a capital letter; a role with a relation in `LIST_ROLES` and an org reads "`{RELATIONS[relation]}` `{org.name}`". `FIELDS["topic"]` becomes "Topic".
7. `is_fact(claim: Claim, source: Source) -> bool`: false for a role that is not `evidence.stated_role` (with a relation it is a list role and a fact) and for a location without relation from a source that is not `prose` (an institution's place). `group_of` returns None for a non-fact, then: `studied_at` Education; `works_at`, `worked_at`, `affiliated_with`, `hosted_by` Work; `born_in` and `origin` Ties when `evidence.shows_tie`, else Places; other locations Places; `fellow_of`, `member_of`, `consul_for` Ties when the source is a `seed_page` or `evidence.shows_tie`, else Work; the rest (topics, papers, roles) Work (V5).
8. `joined_roles(claims, sources) -> dict[str, Claim]`, employer claim id to role claim: a stated role joins the `works_at`, `affiliated_with` or `worked_at` claim of the same source whose quote span overlaps its own (preferring that order, then claim order), else the only such claim when the source holds exactly one stated role and one. A joined pair is one line keyed `("joined", fold(role.value), org_id or fold(value))`, reading "`{Role}`, `{org name}`", with the employer claim's id and cite and the union of both claims' own years.
9. `work_lines(claims, facts, sources, today, place=None)` orders Work (V1). For a line: span = last own year − first + 1, else 0; last = the newest year of `rank.units`, else 0. Current: its employer claim is `works_at`, or `affiliated_with` with last ≥ `today.year - 1`. Order: (a) the head: the current line with the longest span, on equal spans first a joined role, then `in_city(org, place)`, the later last, the line's words A to Z; (b) lines with a stated role; (c) lines at a Belgian org; (d) the rest. Inside b to d: span, then last (both newest first), then words A to Z. Fold: a line of `affiliated_with` from a non-prose source with exactly one own year, not at a Belgian org and not the head. New lines no longer come first in Work. A removed line keeps its key, so its place.
10. The head line: (a) if any, else the first (b) line, else none. `person_view` sets `role` (the joined or bare role) and `employer` (its org name) from it; `employer_of` goes. `person_views` loads the sources of every claim, once per call. The card, the network row, the map popup and the export read the same line.
11. `class FoldView(Model): count: int; source: str; orgs: list[str]` (each "`{org}`, `{year}`") in `contracts.py`; `FactGroup.fold: FoldView | None = None`, set on Work when one line or more fold.
12. `debris(quote: str) -> bool` (V7): after `unescape` and collapsed white space, true when it starts with `[*•-]\s*` and 1 to 30 letters, digits or spaces before `:`; when its folded text holds "orcid image", "author orcid", "![" or "[image"; when an entity `&#?\w+;` remains; or with fewer than 4 words. The name rules go. On the copy this hides about 352 of 2,746 web quotes (was 1,165) and 2,836 of 14,340 seed quotes (was 4,235), all but 10 of them names only; the 240 LinkedIn quotes become records.
13. Tie (V6): `fit_tie(fit: CardFit | None) -> list[str] | None`: None without fit, `[]` unless `tie_grade` is strong or medium, else `fit.tie_claim_ids`. `evidence_tie(store, persons, claims, facts, today) -> list[str]`: `evidence.tie(evidence.card_of(store.identifiers_of(persons), persons), claims, facts, evidence.places(claims, facts, today))`, its `claim_ids` when strong or medium, else `[]`. `tie_claim(claims, facts, ids: Sequence[str]) -> Claim | None`: the first of `ids` among the claims that `evidence.shows_tie`; the old newest-Belgian fallback goes.
14. `summary_of(claims, facts, sources, ids)`: Studied is the newest `studied_at` with `span_words` of its line's own years; the tie row keys "Tie to Flanders" when `evidence.in_flanders(tie, org)`, else "Tie to Belgium" (`SummaryRow.key` gains it); Studied is left out when the tie's id is among its `claim_ids`.
15. `found_as` (V8): one `RecordView` per record of `records_of` over the persons. Its source is the one that gave it most claims (first on a tie), `href` that source's page; `label` its title for a `seed_page`, else `source_name`. Rows that share a label add ", `{org of the record's first Work line}`". `facts` counts its claims that `is_fact`. Rows show with two records or more, or when the page has no fact line. `separated_label` names a record the same way. `ProfileView.records` is the row count when the card holds two persons or more, else 1.
16. `source_sentence(claim, source, org, name: str)`: "The page names `{name}`." when not `is_fact`. `source_cite(claim, source, org) -> str`: the proof's "`{label}`, `{date}`", the date left out when unknown.
17. `profile(store, person_id, today, card=None, words=(), tie_ids: Sequence[str] | None = None)`: `tie_ids` None means `evidence_tie`.

## `src/fn/web/parts.py` and `staff.py`

18. `claim_line` adds the "Years:" `fn-cite` before the cite when `all_years`; `fact_groups` ends Work with the fold line markup from the Claim README, inside the three-line cut; `head_place` compares "Lives in `{place}`".
19. V11: `possible_line` and the matches done line post `next` `{here}#matches`, and the name links `with_back(..., f"{here}#matches")`; `found_as_block`'s Not this person and its done line use `{here}#sources`.
20. `staff.person_page` passes `tie_ids=fit_tie(candidate.fit)` when it found a candidate. `source_page` uses `prose`, passes the person's name, and puts `<p class="fn-source__cite text-small">` under the lead when there is a claim.

## Worked examples, each a test (made-up people)

| Rule | Given | Expect |
| --- | --- | --- |
| V1 | Elke Voorbeeld: `affiliated_with` Chalmers years 2009–2026, Ghent University (BE) 2003–2008, MIT 2006–2012, 30 others one year each, role "professor" joined to Chalmers on one record | Head "Professor, Chalmers University of Technology"; Work: that line, Ghent, MIT; fold "Also named at 30 other organizations" |
| V1 | Two `works_at`, both 2015–2020, one with a joined role | The joined line is first |
| V2 | Wikidata row, no year: `works_at` with `claim_date` = source date 2026-11-04, `record_field` | "Works at Example Health", no year |
| V2 | `years` [2009, 2011, 2012, 2019] | Line "2009–2019"; proof "Years: 2009, 2011–2012, 2019" |
| V3 | Jonas Testman: one role equal to the page title | No role line, no Work, card and row without a role; Sources one row "· no facts"; source page "The page names Jonas Testman." |
| V4 | Seed `fellow_of` with BAEF org, value "BAEF Belgian Fellows", year 2015 | "Fellow of Belgian American Educational Foundation, 2015" under Ties |
| V4 | Role "Chief scientist" on page A, `works_at` Example Health on page B | Two lines, not joined |
| V6 | Mira Proef, opened from a search whose fit is strong with the fellowship first | "Tie to Belgium: Fellow of …" (org region BRU) |
| V6 | Luc Exemple: `studied_at` UCLouvain (WAL), no search | "Tie to Belgium"; no Studied row |
| V6 | `born_in` "Brussels, Belgium" | "Tie to Belgium"; "Antwerp, Belgium" gives "Tie to Flanders" |
| V7 | "She leads the lab." (4 words) / "* Name: Mira Proef" / "Ann" | shown / left out / left out |
| V8 | Card of two OpenAlex records, one with three sources | Two rows "OpenAlex record, `{org}`", "Combined from 2 records" |
| V9 | `vendor_page` on www.linkedin.com | No quote; cite and source name "LinkedIn record"; "The record lists: …" |
| V10 | Seed fact on list "BAEF Belgian Fellows", year 2015 | Cite line "BAEF Belgian Fellows, 2015" |
| V11 | Different person on a possible match | Redirect ends `#matches` |

## Inputs a real run meets

A person whose one fact is a page title; 76 affiliations; no dated fact at all (Work by words A to Z); two employers with equal spans; a role whose organization comes from another source; a tie in Brussels; an organization without a region; a quote of three words; a quote with "she"; a record with five sources (one row, counted once).

## Tests

New file `tests/test_person_content.py`, one test per row above plus the inputs, each seen failing without its change. The word budget (V12): on the five pages of `test_the_first_screen_and_the_whole_page_stay_within_the_word_budget` plus Elke Voorbeeld with 76 affiliations, the words in `div.fn-profile__head`, `section.fn-why` and `dl.fn-summary-list`, forms left out, are at most 90. Names in tests avoid the plural of "tie".

## Existing tests that change, approved

- `tests/test_present.py`: `test_each_kind_and_relation_reads_as_one_plain_line` (Named at, Topic:, Lives in ×2); `test_years_read_as_runs` ("2001–2008").
- `tests/test_person_page.py`: `test_a_fact_from_two_sources_shows_once_with_the_newer_citation` ("2019–2024"); `test_new_marks_show_once_and_only_a_network_person_moves_seen_at`, `test_each_decision_shows_its_done_line_and_undo_restores_the_page`, `test_a_same_name_candidate_can_join_the_network_person` ("Topic:"); `test_a_person_with_two_records_can_separate_one` (one row per record named "example.org", one Not this person, "example.org · Separated").
- `tests/test_profile_page.py`: `test_a_section_whose_only_fact_is_the_studied_row_or_the_head_place_is_left_out` and `test_the_summary_has_the_newest_study_the_tie_and_the_contact_or_not_found` (the degree is the tie, so the tie row replaces Studied); `test_group_of_orders_its_rules` (a seed topic is Work); `test_a_card_of_two_records_shows_both_and_not_this_person_separates_the_second` (`[twin]`); `test_not_correct_on_the_second_records_fact_shows_its_removed_line_with_undo`, `test_a_fact_is_one_line_with_the_source_name_and_not_correct_beside_it` ("Topic:"); `test_quotes_that_are_page_debris_are_left_out_and_the_title_link_stays` (the sentence without the name shows); `test_debris_rules` (V7, one argument).
- `tests/test_way_back.py`: `test_a_possible_match_and_a_source_return_to_the_person_page` (back ends `%23matches`, link `#matches`).
- `tests/test_flows.py`: `walk_browse` (`:391`, at least 1 fact: the role joins its organization).
- `tests/test_results_page.py`: `BUNDLE_SHA` only.

No other existing test may change. Run `uv run python -m unittest`.

## Hand check

Throwaway var folder (`mkvar.sh ui6`), `FN_VAR` set to it, `FN_HTTP=replay FN_LLM=replay`, `uv run fn-rerank --all`, `uv run fn-serve` on a port of your own. Headless Playwright at 1280 px and 390 px on search `186cbce6`: person pages of cards 2, 3, 6, 13, 14, 18 and 78, a Wikidata person, a thin web person, and the source pages of card 2's web fact, the mission PDF and the consul list. Log per page: the head line, the first three Work lines, every year next to a Wikidata fact, the tie row, the words of head, why and summary, `scrollWidth > innerWidth`. Screenshot each first screen and card 2 with Show more. Give the paths, without names.

## Not doing

- The card's reason and second line, the why block and the map: UI-4. UI-4 reuses `tie_claim(claims, facts, ids)` with `fit_tie` or `evidence_tie`, `what_of` and `span_words` for its words, and `stated_role` so a page title never becomes a reason line. `why_of` and its "Based in" stay until UI-4 removes them.
- Rejecting both claims of a joined line: Not correct hides the employer claim; the role shows alone on the next load.
- History entries per post, Esc on a proof, markdown marks in passages, contact data of other people on list pages (nits).
