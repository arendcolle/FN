# Plan: what the person and source pages say (rulings V1 to V12)

The second walkthroughs found the way back and the layout sound, and the content wrong: Work order, page titles as jobs, record dates as years, the tie row, hidden quotes and Sources rows. This section covers rulings V1 to V12 in [design.md](design.md). Two tasks: the design system first, then the site.

## Tasks in order

| Task | What it does | Needs |
| --- | --- | --- |
| [UI-6a](tasks/ui-6a-design-system-12.md) | Design system version 12: Work order and head line, relation words, one-span years, the fold line, Ties contents, Sources rows, the tie row's two labels, the quote furniture rule, the source page's cite line, the passage wrap fix, previews and two v12 mockups. Reports the new `bundle.css` sha256 | nothing; can run while UI-5 is built |
| [UI-6b](tasks/ui-6b-person-page-content.md) | The site: copies version 12 (the only task that does) and builds V1 to V12 in `evidence.py`, `present.py`, `parts.py`, `staff.py` | UI-5 merged, UI-6a done |
| [UI-4](tasks/ui-4-card-and-map.md) | Card lines, why block, map | UI-6b merged, since it reuses the tie and the wording |

UI-5 (headings) is being built now and edits `present.results` and `staff.person_cards`; UI-6b edits `person_view` and `person_views`, so expect conflicts only in imports. Merge UI-5 first.

## File map

| File | UI-6a | UI-6b |
| --- | --- | --- |
| `ds/project/components/{Claim,Profile,SummaryList,Quote,SourceText}/`, `bundle.css`, `STRINGS.md`, `DESIGN-NOTES.md`, `preview/page-*-v12.html` | edit | read |
| `src/fn/web/static/fn.css`, `notes/e2e/design-system/`, `BUNDLE_SHA` | | copy |
| `src/fn/evidence.py` | | `stated_role`, `shows_tie`, `FLEMISH_TEXT`, `in_flanders` |
| `src/fn/present.py` | | `prose`, `own_years`, `span_words`, `what_of`, `is_fact`, `group_of`, `joined_roles`, `work_lines`, `person_view`, `debris`, `fit_tie`, `evidence_tie`, `tie_claim`, `summary_of`, `found_as`, `source_sentence`, `source_cite`, `profile`; `employer_of` and `is_job` go |
| `src/fn/contracts.py` | | `FoldView`; `FactGroup.fold`; `ClaimView.all_years`; `SummaryRow.key` gains "Tie to Belgium" |
| `src/fn/web/parts.py`, `staff.py` | | `claim_line`, `fact_groups`, `head_place`, `possible_line`, `possible_block`, `found_as_block`; `person_page`, `source_page` |
| New test file | | `tests/test_person_content.py` |

## Interfaces UI-4 reads

- `present.tie_claim(claims, facts, ids: Sequence[str]) -> Claim | None`: the first id that shows a tie. It no longer falls back by itself: UI-4 passes `present.fit_tie(candidate.fit)`, and `present.evidence_tie(store, persons, claims, facts, today)` when that is None. This changes the signature UI-4's task assumes (`ids` was optional); UI-4's task text needs that one line.
- `present.what_of`, `span_words`, `own_years`, `prose`: the words, years and quote rule of a fact.
- `evidence.stated_role(claim, source)`: a page title is never a reason line.
- `PersonView.role` and `.employer` now come from the first Work line; the card's role line follows without UI-4 work.

## Findings and who closes them

New = [ux2-walk-new](research/ux2-walk-new.md), check = [ux2-walk-check](research/ux2-walk-check.md), review = [ux2-design-review](research/ux2-design-review.md). Every blocker and should:

| Finding | Severity | Closed by |
| --- | --- | --- |
| Record date shown as a fact's year (new, check, review 3) | blocker | V2, UI-6a and UI-6b |
| A page title as the only job (check; review 2) | blocker | V3 |
| Work opens with one-year affiliations; head names another job (review 1; new "Show 73 more"; check "Show 73 more") | blocker, should | V1 |
| "Tie to Flanders" for a Walloon tie (review 4; check) | blocker, should | V6 with `in_flanders` |
| Summary ignores the stored tie; names a job word (review 5; check "Scientist") | should | V6 with `fit_tie`, `shows_tie` |
| Ties section holds jobs, fields and list titles (new, check, review 6) | should | V5, V4 |
| Relation words outside STRINGS, bare roles (review 7) | should | V4 |
| Debris rule hides good quotes (check medtech CEO; review 8) | should | V7 |
| Year lists in mono (review 9; new nit) | should | V2 |
| Sources rows outnumber records; three alike rows (new, check, review 10) | should | V8 |
| Summary says one fact twice (review 11) | should | V6 |
| First screen over 90 words (new, check, review 12) | should | V12 test in UI-6b |
| LinkedIn profile proof is empty, passage raw (new) | should | V9 |
| Possible match back and Same or Different person land at the top (new, check) | should | V11 |
| Source page does not name its source (review 13) | should | V10 |
| Long email widens the source page at 390 px (review 14) | should | UI-6a `bundle.css` |
| Head becomes "ALA" after Not correct; a fact its quote does not support (new, check) | should | V1 picks the current employer by span. Left out: the page reader storing a wrong organization is a page-reading fault, not a page rule |

Nits closed on the way: lower-case roles, "Based in" from OpenAlex places, the past job before the current one. Left out, all nits: history entries per post, a closed proof after Back, Esc on a proof, Tab stops on results, header marks on the match and source pages, Contact "Not found" next to "Not provided", Add and Skip after Remove, "###" and "*" in passages, other people's contact data on list pages, near-duplicate lines, a paper without "Paper:", a quote cut mid-word, a stray letter in a name, the long stored record, the record cite repeating its label, the PDF address in a list's name.

## Settled in the tasks, for the lead to confirm

1. Brussels reads "Tie to Belgium"; so do the BAEF and Francqui (region `BRU`).
2. A `works_at` claim counts as current whatever its year, because the source states it as current; only `affiliated_with` needs a year in the last two. Without this, today's tests and the Wikidata, ORCID and LinkedIn employers lose their head line.
3. The head names only a job line (the current job or a stated role), never a topic, paper, past job or list entry.
4. One-year affiliations at a Belgian organization stay out of the fold.
5. An OpenAlex institution's place is no fact on the page; the head still uses it.
6. A page that only names the person shows its one Sources row with "· no facts".
7. V7 hides a field label only after a list mark, so a longer "Name: …" line without one now shows as a quote.
8. Not correct on a joined line ("Head of gynecology, UZ Leuven") hides the employer claim; the role shows alone on the next load.

## Done check

1. `uv run python -m unittest` is green.
2. The two walkthroughs and the design review run again with their flows, widths and pages, on a throwaway copy after `fn-rerank --all`. None reports a blocker or a should on the person or source pages.
3. On 5 person pages of search `186cbce6`, the words of head, why block and summary are at most 90 (V12), and no Wikidata fact shows a year.
