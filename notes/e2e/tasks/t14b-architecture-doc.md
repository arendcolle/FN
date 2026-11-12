# Task T14b: bring the architecture document up to the code

Branch `docs/architecture-v4`. `notes/mvp0/architecture.md` describes FN at version 3.2: search only. The code now has a network, merges, staff decisions as events, an import, an export, a ranker cut, publish steps and owner pages. After this task the document describes the code on `main` again, as version 4.0.

Read first: `notes/mvp0/architecture.md` in full; `notes/e2e/design.md` (the design the new code follows); `notes/e2e/plan.md`; `notes/design/story-map.md`; then the code: `src/fn/contracts.py`, `store.py`, `network.py`, `importer.py`, `exporter.py`, `present.py`, `resolve.py`, `rank.py`, `search.py`, `stats.py`, `geo.py`, `web/app.py`, `web/staff.py`, `web/debug.py`, `web/parts.py`, `web/static/results.js` and `map.js`, and `src/fn/migrations/006_network.sql` and `007_cut_reason.sql`.

## What to change

Edit the document in place. Keep its structure, its voice and every statement that is still true. Change only what the code changed.

- The date and version line: 2026-11-12, version 4.0, with one clause on what 4.0 added, in the style of the earlier versions.
- The TL;DR: add the network in two or three sentences.
- "Requirements for this slice" and its "Out of scope" paragraph: Add, Skip, Merge, the list page, export and import are built. Login and depths beyond Quick are still out.
- "Module layout": the new modules and the split of `web/`.
- "Contracts": the new Literal values and models (events, imports, view models, the new fields on `Person`, `Claim` and `Candidate`).
- "Rules": identity with merges as pointers (`merged_into`, canonical ids, `store.claims_of` over a whole person, `resolve.group` mapping hits); the network (`list_status`, who writes it); rejected facts; `first_seen_at`, `seen_at` and what counts as new; import and staff sources with `fn:` URLs.
- "Storage": the new columns and the tables `events`, `not_same` and `imports`.
- "The Quick workflow": the publish steps, a failing lane that no longer stops the search, `search_progress`. "Ranking": the cut and its reason, kept ranks, where cut people show.
- "Pages": the staff pages as they are now (Home, All searches, Results with card actions and live update, Network, Person, Import, Export, Source) and the debug pages added (`/debug/stats`, `/debug/feedback`).
- "Logging": the request log line and what the two debug pages show.
- "Gold runner": a cut pick, a failed lane, `scripts/gold/cut_gate.py`.
- "Responsibility table": one row per responsibility with one owner, including the new ones. Check that no responsibility has two owners.
- "Not doing": remove what is built; add what the design leaves out (see design.md "Not doing").
- Do not rewrite "Decisions from the reviews"; add nothing there.

## Rules for this task

- Every statement you add must be true of the code on `main`. Check each against the code before you write it, and give no file:line numbers that you did not verify. If the design note and the code differ, the code wins, and you report the difference.
- Follow the writing rules in the owner's instructions: plain words, active voice, one idea per sentence, no em dashes, sentence-case headings, no names of people. Read the finished sections once at speech pace and split what reads badly.
- The done check bans the words "tie" and "ties" in `src/` and `tests/` only; the document may use them.
- Change no file outside `notes/mvp0/architecture.md`.
- Do not commit. Do not run git checkout or switch. Work only in your worktree.
- Report: the sections you changed, each difference you found between design.md and the code, and anything in the old document you could not verify.
