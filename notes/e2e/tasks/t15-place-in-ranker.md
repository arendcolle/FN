# Task T15: use the place a question names in the ranker, if the numbers support it

Branch `feat/place-in-ranker`. Measure first. Build only the variant the numbers support, and build nothing when none passes.

Read first: [design.md](../design.md) "Candidates and the cut"; [panel-records.md](../panel-records.md) record D6; `research/lanes-rank.md`; `src/fn/rank.py`, `src/fn/geo.py`, `src/fn/gold.py`, `scripts/gold/cut_gate.py` and `src/fn/present.py` (`place_of`).

## Why

The ranker never reads the place of a question (`src/fn/rank.py`). After the cut on Belgian evidence a search still keeps a median of 518 people, and the order puts people with many Belgian years first wherever they are. On the stored search "Which entrepreneurs could share lessons from failure and growth with Belgian delegates visiting Los Angeles?" the first cards are people whose last known place is in Belgium. The to-do list asks for searches that return far fewer people.

## Step 1. Measure three variants on the stored searches

Write a throwaway script in your temp folder (not in the repo) that opens a copy of the owner's database read-only (the prompt says how to get a copy) and the gold set, and replays the ranking for every stored search with results, as `scripts/gold/cut_gate.py` does. For each search that has a place chip `geo.area` can locate (kind `metro` or none), work out for each kept candidate whether its person's place is inside the radius, outside it or unknown. A person's place is what `present.place_of` returns for the claims of the candidate's hit persons.

Compare with today's ranking:

- **A. Place cut.** Cut a new-section candidate whose place is known and outside the radius.
- **B. Place list.** Add one more reciprocal-rank-fusion list, as `belgian_years` is one: every candidate inside the radius is on it at rank 1. Nobody is cut.
- **C. Both.**

Report, for today and for each variant:

- per search and as a median: people kept, and how many of the first 50 are inside, outside and unknown;
- for each gold pick that reaches the ranker in a stored search (12 today): whether it is kept, its position among kept people, and whether its place is inside, outside or unknown. Use the case id and a pick number, never a name;
- picks in the first 10, the first 50 and the first 100.

Also report how many stored searches have a located place at all, and what happens to the others (nothing may change for them).

## Step 2. Decide

A variant passes when no pick that reaches the ranker is cut, the picks in the first 50 and in the first 100 are at least today's (4 and 6), and it improves at least one of: the median people kept, the picks in the first 10, or the median position of the picks. If more than one passes, prefer the one that cuts nobody unless the cut removes at least a third of the kept people in searches with a place.

Write the numbers and the decision to `notes/e2e/research/place-ranking.md` in your worktree: a summary first, then the tables. Plain sentences, no names of real people.

If no variant passes: stop there, change no code, and return status `not_feasible` with the note's path.

## Step 3. Build the variant that passed

- The rule for where a person is must have one owner. `present.place_of` holds it today. Move it to `geo.py` and let `present.py` and `rank.py` both call it there.
- `rank.run` locates the question's place through `geo.area(ctx.http, chips.place)`, as two lanes already do.
- Variant A or C: a new cut reason `outside_place` in `CutReason`, set by `rank.py` after the Belgian-evidence rule; a candidate with an unknown place is never cut for its place; a network candidate is never cut. A migration marks the stored searches the same way only if it can be done in SQL from stored data; otherwise leave stored searches as they are and say so.
- Variant B or C: a score part with feature `place`, stored like every other part, so the debug page shows it. `ScorePart.feature` gains the value.
- The debug page and the trace show the new reason or part without further work if they already list reasons and parts; check that they do.
- `scripts/gold/cut_gate.py` learns the new rule, so the gate keeps checking the ranker as it is.

## Tests

In `tests/test_rank.py`: a person inside the radius, one outside, one with no place and a network person outside, each with the outcome the built variant gives; a question with no place or a place `geo` cannot find changes nothing. In `tests/test_geo.py`: `place_of` picks the newest dated located claim, else an undated one, never a `born_in` claim.

Each new test must fail without the change. An existing test whose expected order or count changes on purpose: list it with the old and the new expectation.

## Hand check

Run the updated gate on a copy of the owner's database and paste its output. For search `f10ee197-4c35-48f1-80f6-07cdbceae261`, replay the ranking with the new code (a rerun through `Worker.execute` with `FN_HTTP=replay FN_LLM=replay`) and report the place of each of the first ten kept people as inside, outside or unknown, before and after.

## Rules for this task

- Run `uv run python -m unittest` before you start and when you finish.
- No new dependency. Only `store.py` runs SQL. Match the style of the file you edit; single-line comments only. The done check bans the word "tie" and its plural in `src/` and `tests/`.
- Other tasks are changing `web/staff.py`, `web/parts.py`, `present.py` and `web/static/` at the same time: in `present.py` change only what moving `place_of` needs.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
