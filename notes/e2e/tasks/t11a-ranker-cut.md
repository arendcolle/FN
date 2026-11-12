# Task T11a: the ranker cuts people without Belgian evidence

Branch `feat/ranker-cut`. After this task `rank.py` marks the people a search should not show, the stored searches are marked the same way, and the owner can see who was cut and why on the debug page. The staff results page starts using the cut in a later task.

Read first: [design.md](../design.md) "Candidates and the cut", [panel-records.md](../panel-records.md) record D6, and `research/lanes-rank.md` sections on `rank.py` and `gold.py`.

## Why

A search returns a median of 1,098 people over the 24 stored searches with results. The OpenAlex lane returns up to 2,000 authors, Belgian or not, and leaves the Belgian cut to the ranker, which has none (`src/fn/rank.py`).

## What changes

1. **The rule, in `rank.py`.** A candidate in section `new` gets `cut_reason = "no_belgian_evidence"` when OpenAlex is the only lane that found it and it has no `belgian_years` score part. Everyone else is kept: every network candidate, everyone with a `belgian_years` part, everyone found by the seed, web or LinkedIn lane. No score floor and no year threshold.
2. **Rank numbers.** `rank` counts kept candidates only, from 1 per section, in the order `fuse` has today. Cut candidates are numbered from 1 among themselves in that same order, so `rank` stays an integer. Kept candidates keep their relative order.
3. **Store.** `list_candidates(search_id, kept_only=False)` returns kept candidates before cut ones within a section, and only kept ones with `kept_only=True`. `count_candidates` counts kept candidates only, so the home page says how many people a search shows.
4. **Stored searches.** Migration `007_cut_reason.sql` sets `cut_reason` on the stored candidates with the same rule, in SQL over `lane_ranks_json` and `score_parts_json`. It changes no rank number and deletes no row.
5. **Debug page.** The debug search page says how many candidates are kept and cut, and each cut card says "cut: no_belgian_evidence". The trace page shows a cut person's rank row as dropped with that reason.
6. **Gold runner.** `gold.py` reports a pick that was cut as lost at the rank step with the reason, through the trace rows it already reads, and its top list holds kept people only.
7. **Gate script.** `scripts/gold/cut_gate.py` (a PEP 723 script or plain stdlib) opens a database read-only and the gold set, and prints: per stored search the total and the kept count; the median of each and the drop in percent; for every gold pick that reaches the ranker in a stored search, whether the rule keeps it and its position among kept people; how many picks stand in the first 50 and the first 100. It exits 1 when a pick that reaches the ranker is cut, when fewer than 4 picks stand in the first 50 or fewer than 6 in the first 100, or when the median kept count is not at least 40% below the median total. Print no person's name: use the case id and a pick number.

## Tests

- `tests/test_rank.py`: a web-only person with no Belgian years is kept; an OpenAlex-only person with none is cut; a network person with none is kept; an OpenAlex-only person with Belgian years is kept; kept ranks run 1..n with no gap and cut candidates are numbered apart.
- `tests/test_db.py`: migration 007 marks a stored OpenAlex-only candidate without a `belgian_years` part and leaves the others; `list_candidates(kept_only=True)` leaves the cut one out; `count_candidates` counts kept ones.
- `tests/test_gold.py`: a cut pick is reported as lost at rank with the reason.
- `tests/test_web.py`: the debug page shows the kept and cut counts.

Each new test must fail without the change. An existing test that asserts a rank number or a count the cut changes on purpose: list it in your report with the old and the new expectation, change it, and say so. Any other failing test: stop and report.

## Hand check

Run `scripts/gold/cut_gate.py` on a throwaway copy of the owner's database and paste its output. Then run the app's migration on that copy and report, for search `f10ee197-4c35-48f1-80f6-07cdbceae261`, the total and the kept count.

## Not in this task

The staff results page (`web/staff.py`, `web/parts.py`, `present.py`): another task is rewriting it. Skipped people. "Show more". Any change to the order of kept people.

## Rules for this task

- Run `uv run python -m unittest` before you start (300 tests pass) and when you finish.
- No new dependency. Only `store.py` runs SQL. Match the style of the file you edit; single-line comments only.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
