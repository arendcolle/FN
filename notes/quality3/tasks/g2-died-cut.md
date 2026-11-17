# Task G2: a person a source says has died is cut, not set aside

## Goal

The owner, 2026-11-17: drop "People who have died" from the bottom of a search. The live Washington search (`19037dc3-259f-4be7-8282-74faef5d7549`) holds 9 such people among its 35 set aside. The ranker now cuts them like the other cuts. Everything that served only the died group goes, and a migration converts stored rows so a stored search opens without the group and without a rerank.

## What to build

### `src/fn/contracts.py`

`CutReason` (line 53) gains `"died"`. `Aside` (line 54) and `CardState` (line 61) lose `"died"`. `ReasonView` (line 546) loses `year`, which only `death_line` set.

### `src/fn/rank.py`

- `ASIDES` (line 36) becomes `(None, "outside", "abroad", "unfit")`.
- `aside` (line 274) loses its `found.age.died` branch and the death words of its docstring.
- New `death_cut(section: Section, found: "evidence.Evidence | None", question: Question | None) -> CutReason | None`: `"died"` for a new-section person with evidence, chips of version 2 or later and `found.age.died`; else None.
- `fuse` (line 412): `reason=(None if n in back else r.reason or no_tie(...)) or death_cut(r.section, r.found, question)`. Another reason wins, and `exempt` sees the same rows as today. Line 429 already stores no aside on a cut row. Died rows were the last kept rows, so everyone else keeps their kept order and rank.

### `src/fn/present.py`

- `GROUP_KEYS` (line 80) and `GROUP_TITLES` lose `"died"`. Delete `death_line` (line 790).
- `card_view` (line 800): drop the `died` variable, its branches, the `state="died"` return and its docstring sentence. `line` is `aside_line(...)` for outside and abroad, else None; `shown` is `view.model_copy(update={"place": None}) if line else view`.
- `what_of` (line 225) keeps "Died {year}" for the person page.

### `src/fn/web/parts.py`

Line 171 drops the year span: `h.p(aside.text, " · ", h.a(...), class_=...)`. `fn.css` does not change; the old-record line still uses `.fn-card__fit .text-year`.

### `src/fn/web/debug.py`

`trace_rows` (line 259): a `ValidationError` from `model.model_validate_json(output)` appends `[step.seq, step.step, "-", "-", "stored under an older contract, not shown"]` and goes on. Stored `RankOut` payloads still hold `aside: "died"`, and the trace page and `gold.lost_at` read them.

### `src/fn/migrations/015_died_cut.sql` (new)

```sql
CREATE TEMP TABLE died_ranks AS
SELECT d.search_id, d.person_id,
       (SELECT count(*) FROM candidates c WHERE c.search_id = d.search_id AND c.section = d.section
          AND c.cut_reason IS NOT NULL)
       + row_number() OVER (PARTITION BY d.search_id, d.section ORDER BY d.rank) AS cut_rank
FROM candidates d WHERE d.aside = 'died' AND d.cut_reason IS NULL;
UPDATE candidates SET cut_reason = 'died', aside = NULL,
    rank = (SELECT cut_rank FROM died_ranks r WHERE r.search_id = candidates.search_id AND r.person_id = candidates.person_id)
WHERE aside = 'died' AND cut_reason IS NULL;
UPDATE candidates SET aside = NULL WHERE aside = 'died';
DROP TABLE died_ranks;
```

Died rows get cut ranks after the existing cut rows of their section. No column stores a people count: `search_progress`, `count_candidates` and `kept_card_ranks` count rows without a cut reason.

### Readers checked

`search.first_heading` (line 153) counts kept tier-1 and tier-2 new-section people, so it now leaves the dead out. It feeds `LaneIn.first_heading`, and `lanes/web_topic.py` line 26 skips its lane at `GATE = 20`; no code change. Every list, map, walk, export, fit check and lookup reads `kept_only=True`. `stats.py`, `score.py`, `gold.py` and the debug cards show the raw `cut_reason`, so `died` needs no words. `group_query` (staff.py line 439) turns `?group=died` into None.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a source states a death | `evidence.age` (unchanged) |
| Cutting a dead new-section person | `rank.death_cut`, called in `rank.fuse` |
| Groups, cards, the death fact on the person page | `present.py` |
| Converting stored rows | `015_died_cut.sql` |
| Reading old step payloads on the trace | `debug.trace_rows` |

## Inputs a real run will meet

Only dead people set aside (no "Set aside" heading); dead and outside a required area (`died`); dead under a required tie (stays `no_tie`); a dead exempted OpenAlex person (`died`); a dead network person (open); 50 tied tier-6 people plus a dead one; two searches with died rows, one without cut rows; a malformed row with `aside = 'died'` and a cut reason; a second migrate; a trace of an old search; a person page linked from a search that now cuts them; `?group=died`; version-1 chips; an export.

## Tests (each must fail without the change)

Made-up names only.

- `tests/test_rank.py`: on version 2 a dead tier-1 person is cut `died` with aside None and tier 1, and the kept rows equal those of the same call without them; dead outside a must area is cut `died`; dead with a weak tie under a required tie stays `no_tie`; a dead exempted OpenAlex person with a topic match is cut `died`; of 50 tied tier-6 people plus a dead one, only the dead one is cut, as `died`.
- `tests/test_db.py`, migration 015 on a database at 014. Search one: open ranks 1 and 2, `unfit` 3, died 4 and 5, `no_tie` cuts 1 and 2, network 1; afterwards the died rows are `died` cuts at ranks 3 and 4 without aside, and every other row is unchanged. Search two: one died row and no cut rows gets cut rank 1. A row with `aside = 'died'` and `cut_reason = 'no_tie'` keeps `no_tie` and loses the aside. `search_progress(...).people` drops by the died rows.
- `tests/test_results_headings.py`: an open person plus one cut `died` gives no "Set aside" heading, no group and a count of one; `?group=died` opens no group.
- `tests/test_person_page.py`: a person cut `died`, opened with `?search=s1&card=<id>&from=card`, answers 200, shows "Died 1966" under Work and no walk line.
- `tests/test_card_actions.py`: the search export leaves out a person cut `died`.
- `tests/test_search.py`: 20 saved kept tier-1 new-section people, one of them cut `died`, give `first_heading` 19.
- `tests/test_web.py`: the trace of a search whose stored `RankOut` holds `aside: "died"` answers 200 with the note row.

## Existing tests that change, approved by the lead

- `test_rank.py` `test_a_dead_tier_1_person_stands_under_died_after_unfit_and_on_version_1_keeps_tier_1` becomes `test_a_dead_tier_1_person_is_cut_as_died_and_on_version_1_keeps_tier_1`. Old: kept order open, nope (unfit), dead (died). New: kept rows open, nope (unfit); dead has `cut_reason` `died`, aside None, tier 1. The version-1 part stays.
- `test_rank.py` `test_died_beats_outside_and_a_dead_network_person_stays_open` becomes `test_a_dead_person_outside_a_must_area_is_cut_as_died_and_a_dead_network_person_stays_open`. Old: `aside == "died"`. New: `(cut_reason, aside) == ("died", None)`. The network part stays.
- `test_fitcheck.py` `test_a_died_person_is_not_sent`: the setup `aside="died"` becomes `cut="died"`; the assertions stay.
- `test_results_headings.py`: delete `test_the_died_group_follows_the_other_groups`, `test_a_died_card_names_the_death_and_its_source` and `test_a_died_card_has_no_role_reason_or_acts_and_a_rejected_death_gives_a_normal_card`. They test the removed group and card.
- `test_db.py`: the expected `migrate()` lists at lines 78, 104 and 174 gain `15`.
- `test_web.py` line 654 and `test_orgs.py` line 354: each expected `migrate()` list gains `15`.

No other existing test may change; stop and report.

## Recorded model answers and replay (S6)

No prompt changes and no new task. The fit check and the lookup never sent people set aside, and the kept order of the rest is unchanged, so their recorded inputs stay and replay finds them. One new call can follow: where dead tier-1 and tier-2 people held `first_heading` at 20 or more, the `web_topic` lane now runs, with a paid web search and extract calls live. A full-search replay of such a question asks for answers never recorded and needs new recordings; `fn-rerank` and `refinish` run no lane and are unaffected. In `fn-score`, `kept`, `tier_1` to `tier_7` and `first_heading_under_5` drop or change by the dead people, and `cut_seed` may list their seed records.

## Hand check

`uv run python -m unittest` all green. Make a copy with `V=$(mkvar.sh g2)` and save this as `$S/dump.py` in a scratch folder outside the repo:

```python
import sys, datetime
from fn import config, present
from fn.store import Store
s = Store(config.from_env().db_path); s.migrate(); q = s.get_search(sys.argv[1])
r = present.results(s, q, datetime.date(2026, 11, 17))
print([p for p, _ in r.order]); print([(g.key, g.count) for g in r.groups])
print(sorted(c.person_id for c in s.list_candidates(q.id, kept_only=True, include_skipped=False)))
```

```sh
ID=19037dc3-259f-4be7-8282-74faef5d7549
FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run python $S/dump.py $ID > $S/before.txt  # from a worktree pinned to main
FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run python $S/dump.py $ID > $S/after.txt   # from this worktree; migrates
FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run fn-rerank $ID
FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run python $S/dump.py $ID > $S/rerank.txt
```

Expect: before shows `died` 9 and after has no `died` group; the other group counts are equal; the after order is the before order without the 9; none of the 9 is in the export ids; the rerank dump equals the after dump, or each difference is explained. Cut ranks may differ after the rerank, since `fuse` orders died rows among the other cuts.

## Not doing

Any change to the other groups, death extraction, `evidence.age` or the person page. A staff list of cut people. Rewriting stored step payloads. Design-system edits (the lead's).
