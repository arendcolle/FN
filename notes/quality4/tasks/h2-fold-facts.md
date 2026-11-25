# Task H2: one line per fact on the person page

## Goal

Two claims make one line only with one kind, relation and organization or value (`line_key`, `present.py:993`). On the owner's snapshot 546 pages show a tie twice, 1,133 show "Named at X" twice and 431 name one organization on several Work lines; the example person has 14 Work lines for about 7 facts. This task folds lines where the page is built (D4). Stored claims, ranking, head line, cards, network rows and export stay.

## What to build

### `src/fn/contracts.py`

- `ClaimView.joined_claim_id` (line 503) becomes `fold_ids: list[str] = []`: the other claims Not correct hides.
- New `TitlesView(Model)`: `what: str`, `source: str`, `facts: list[ClaimView]`. `FactGroup` (line 634) gains `titles: TitlesView | None = None`.

### `src/fn/present.py`

- `Line` (line 389) gains `roles: list[Claim] = field(default_factory=list)`, set by `line_of` (line 460) to `[joins[c.id] for c in found if c.id in joins]`.
- `lines_of` (line 439): every key becomes `(bool(claim.rejected_at), *key)` in place of `(claim.id,)` for a rejected claim, so the claims one Not correct removed form one removed line.
- `text_key(what: str) -> str`: `" ".join(what.split()).casefold()`.
- `merged(base: Line, others: list[Line]) -> Line`: base keeps `shown`, `role`, `org`, `what`, and takes the others' `claims` and `roles`, the union of `own`, max `last`, min `tier`.
- `fold_lines(lines: list[Line], work: bool) -> list[Line]`: lines fold only within one rejected state; a folded line stands where its group's first line stood; newest is the rule of `newest` (line 159). Three passes:
  1. Work only. A line whose `shown.relation` is in `RELATIONS` is keyed by `line.org.id`; without an orgs row, by the smallest id of an organization whose name has the same `text_key` as `shown.value`, else by `text_key(shown.value)`. Joined lines with one `text_key(role.value)` fold into their newest. Lines without a role fold into the newest role line, else into the newest line.
  2. A `location` line with coordinates is keyed `(relation, round(lat, 2), round(lon, 2))`; the base has the longest `what`, then is newest.
  3. Lines with one `text_key(what)` fold; the base is a line about an organization before a loose title, then the newest.
- `line_view` (line 998): `fold_ids` is every id of `(*line.claims, *line.roles)` but the shown one, once; `is_new` reads the same claims.
- `fact_lines` (line 1015) sorts `fold_lines(lines_of(...), work=False)`.
- `same_fact(claim, claims, facts, sources)` (line 1055): folds the claim's section (`group_of`, line 971) with `fold_lines(lines_of(...), work=group == "Work")` and returns the ids of the line holding the claim, else `[claim.id]`. `summary_of` (line 1064) passes `facts, sources`.
- `titles_of(views: list[ClaimView]) -> TitlesView`: `what` is `"Also described as " + " · ".join(kept)`, leaving out a wording whose `name_key` word set lies in another's or equals an earlier one's. `source` is the one `view.source`, else `f"{n} sources"`.
- `profile` (lines 1269 to 1282): `fold_of` still reads `work_lines(...)`; Work shows `fold_lines([s for s in work if not s.folded], work=True)`. Two or more lines with `s.role is s.shown` and no `rejected_at` become `titles`, which also lists the Work section and counts as a fact for `found_as`.

### `src/fn/web/parts.py`

- `post_form` (line 395): `**fields: str | list[str]`, one hidden input per value. `claim_line` (line 579) passes `also=view.fold_ids`.
- `titles_line(titles: TitlesView, here: str) -> Safe`, the Profile part version 14 markup: `div.fn-claim#work-titles`, `<span class="fn-claim__what text-body">{what}</span>`, and a `details.fn-proof` with summary `{source}` and aria-label `Source for {what}: {source}`. Its body holds per title a `div.fn-claim__head` `id="claim-{id}"`: New, wording, years, Quote, `cite_line`, its own Not correct. The line has none.
- `fact_groups` (line 623): items are claim lines, `titles_line`, `fold_line`; a group with titles is never left out as covered (line 632).

Strings, from STRINGS.md version 14: "Also described as `{wording}` · `{wording}`", "`{n}` sources", "Source for Also described as `{wordings}`: `{source name}`", "Not correct", "· Removed", "Undo".

`network.py` and `staff.py` stay: the route passes every `also` value (`staff.py:802`).

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which claims make one line, and its shown claim | `present.lines_of`, `present.fold_lines` |
| Gathering loose titles and their sentence | `present.profile`, `present.titles_of` |
| Claim ids a summary row covers | `present.same_fact` |
| Markup | `web/parts.py` |
| Hiding and restoring claims | `network.reject_claim`, `network._undo_reject` |

## Inputs a real run will meet

166 Work lines [8]; an id on one claim and only the name on another [2]; two ids with one name [3]; two jobs at one employer with and without roles [4]; a loose title equal to a joined line [5]; titles where one holds another, in two languages, or of punctuation only [5]; a rejected twin and a New twin [6]; a place without coordinates, and born in beside based in at one spot [7]; a Ties section the summary covers [1]; `?all=work` [5]; a person outside the network [1]; a removed title [9].

## Tests (each must fail without the change)

New class `FoldTest(PersonContentCase)` in `tests/test_person_content.py`. Cases 1 to 5, 7 and 8 failed on main and passed on the planner's scratch build.

1. `test_a_tie_from_a_list_and_a_page_is_one_line_and_not_correct_removes_both`: seed `role` and page `affiliation`, both `consul_for` one org, beside a born-in tie the fit names: one consul line; Not correct leaves one removed line; Undo brings one line back. Without the fit, Ties is left out.
2. `test_one_organization_is_one_work_line_with_all_its_years`: works_at 2024 with an id, worked_at 2010–2012 by name, affiliated_with 2015–2016 give "Works at Example Health, 2010–2024".
3. `test_two_ids_with_one_name_fold_only_when_the_words_match`: "Named at X" under two ids is one line; "Works at X" and "Named at X" stay two.
4. `test_two_stated_roles_at_one_employer_stay_two_lines`: engineer 2012 and director 2024 stay two; a roleless worked_at folds into director.
5. `test_loose_titles_gather_in_one_line_that_opens_into_each_title`: "honorary consul", "honorary consul in Springfield", "ereconsul" (one host) and a works_at give `["Works at Example Health", "Also described as Ereconsul · Honorary consul in Springfield"]`, also with `all=work`, and three heads with Not correct, none on the line. "lecturer", "docent", "–" on two hosts: "Also described as Docent · Lecturer", "2 sources". A loose "managing director at BGR group" folds into the joined line; one loose title stays a normal line.
6. `test_a_rejected_twin_stays_hidden_and_a_new_twin_marks_the_line_new`.
7. `test_places_at_one_spot_fold_to_the_longer_words`: "Austin, TX" and "Austin" with equal coordinates to two decimals give "Based in Austin, TX"; "Austin, Texas" without coordinates stays; born in and based in at one spot stay two.
8. `test_166_organizations_each_with_a_twin_give_166_lines`: "Show 163 more".
9. `test_a_removed_title_stands_alone_with_undo_and_the_rest_stay_gathered`.

## Existing tests that change, approved by the lead

None. All 1,127 tests passed unchanged on the scratch build. No existing test may change; if one does, stop and report.

## Recorded model answers and replay (S6)

No prompt, model call or ranking input changes, so every recording replays and a search stored with version-1 chips keeps its order: `rank.py`, `evidence.py` and `person_view` read no folded line.

## Hand check

`uv run python -m unittest` all green. With `FN_HTTP=replay FN_LLM=replay`, on copies from `mkvar.sh`, a scratch script outside the repo builds `present.profile(store, id, date(2026, 11, 24))` for every person with a claim (8 processes, about 35 minutes) and counts per section the lines (plus one for titles) and pages with two equal `what` after case and spaces; once from a worktree pinned to main, once here. Planner's measurement, 37,897 persons:

| Section | Lines, main | after | Pages with a pair, main | after |
| --- | --- | --- | --- | --- |
| Work | 256,146 | 253,627 | 1,133 | 0 (34 when punctuation is also dropped) |
| Ties | 5,714 | 5,168 | 546 | 0 |
| Places | 419 | 418 | 0 | 0 |
| Education | 646 | 644 | 2 | 0 |

The example person (id in the brief): Work 14 lines to 9, one "Also described as"; Places 3 to 2; the tie once, in the summary, so Ties is left out. Screenshot it with the gathered line open, and Undo after Not correct on the employer line.

## Not doing

Stored claims, migrations, rereading pages, a title word list, folding "Also named at" entries, a role joined to the wrong organization, ranking after Not correct, another person's claims on a combined card (left as today), design-system edits.
