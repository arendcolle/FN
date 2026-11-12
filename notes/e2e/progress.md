# Progress on the seven staff flows

One line per finished step, newest last. The plan is in [plan.md](plan.md) and the design in [design.md](design.md).

## Log

- 2026-11-12 Baseline: `uv run python -m unittest` runs 267 tests and passes on `main` at `e1250ca`, once the gitignored local data (`data/seeds`, `data/gold`, `tests/fixtures/http/openalex`) is present. Without it 47 tests fail.
- 2026-11-12 Research notes written by nine reader agents: [research/](research/).
- 2026-11-12 Design draft 1 written: [design.md](design.md). Decisions D5 to D10 sent to review panels.
- 2026-11-12 Started two slices that do not depend on the panels: the city lookup fix ([tasks/geo.md](tasks/geo.md)) and the Fayat seed list ([tasks/fayat.md](tasks/fayat.md)).
- 2026-11-12 Six panels settled D5 to D10 (records in [panel-records.md](panel-records.md)). Design version 2 and the plan written.
- 2026-11-12 T3 merged: Fayat scholars as a sixth seed list (PR #5). 95 people from the public laureate page; names stay local.
- 2026-11-12 T1 merged: `web/app.py` split by job, 23 pages byte-identical before and after (PR #6).
- 2026-11-12 T2 merged: place lookup reads states, countries and metro names (PR #7). The LinkedIn location claim was left out.
- 2026-11-12 Plan reviewed by a fresh Opus reviewer in three rounds and approved. T4, the network core, started.
- 2026-11-12 T4 merged: the network core (PR #9). Migration 006 ran in 0.6 s on a copy of the 509 MB database. 300 tests.
- 2026-11-12 T5 done: seven new parts and new states published to the design system (version 8); `fn.css` is its byte copy (PR #10). The strings are in [design-system/STRINGS.md](design-system/STRINGS.md).
- 2026-11-12 Started five tasks side by side: T6 person views, T11a ranker cut, T12a publish steps, T13a owner logging, T9a import core.
- 2026-11-12 T6 merged: one person view and one claim format (PR #11). Raw record lines on cards went from 718 to 0 on the example search.
- 2026-11-12 T11a merged: the ranker cut (PR #12). Median 1,098 to 518 people; no gold pick lost.
- 2026-11-12 T12a merged: publish steps and lane failures that do not stop a search (PR #13).
- 2026-11-12 T13a merged: request log, `/debug/stats`, `/debug/feedback` (PR #14).
- 2026-11-12 T9a merged: the import core (PR #15). 348 tests.
- 2026-11-12 T7, the Network page, in progress.
- 2026-11-12 T15 measured and not built: using a question's place in the ranker. A place cut loses a gold pick, and a place list improves nothing, because the only located places are the last institutions OpenAlex knows. Numbers in [research/place-ranking.md](research/place-ranking.md).
- 2026-11-12 T7 merged: the Network page, the network on Home, All searches and the map popup (PR #16).
- 2026-11-12 T8 merged: the Person page (PR #17). T9b merged: the import pages and the export (PR #18).
- 2026-11-12 T10 merged: Add, Skip, Same person and Undo on result cards, 50 at a time (PR #19). The results page of the example search went from 913 KB to 78 KB.
- 2026-11-12 T12b merged: the results page updates while a search runs (PR #20). 403 tests.
- 2026-11-12 Browser walk on a copy of the owner's database: import of a made-up file, the people on the map, a profile, the export, Add, Undo and Skip on a stored search, and a replayed search that showed 12 cards at 5 s and the full list at 10 s without a reload.
- 2026-11-12 A search with live calls could not be run: the Claude command-line login on this machine has expired ("OAuth session expired and could not be refreshed"), and the parse step needs it. The search failed at parse after its 60 s timeout, and the page showed "This search stopped" with Try again. The owner has to sign in again before new searches work.
- 2026-11-12 T14 merged: one test per staff flow (PR #21). All seven flows could be walked; 411 tests. T14b merged: the architecture document at version 4.0 (PR #22).
- 2026-11-12 A search with live calls ran to the end after the owner signed in again: 510 people in 257 s, on one page without a reload. The page showed 96 people after the seed lane at 8 s, 446 after OpenAlex at 26 s and 510 after the web lane at 257 s. The web lane took 231 s, and 228 s of that were 19 model calls that ran one after another to read 10 pages. Two findings on the results: 54 of the seed lane's 100 hits matched only the word "in" from the topic "AI in health care", and 3 of the first 50 cards mention Boston or Massachusetts, the place of the question.

## Review ledger

Findings from plan and diff reviews, with the outcome of each.

| Id | Where | Severity | Outcome |
| --- | --- | --- | --- |
| geo R1 | `geo.py` free-text scan read an alternate city name as the city before a state name | should | fixed |
| geo R2 | A code that is both a state and a country (CA) matched only as a state | should | fixed |
| geo R3 | A metro alias inside a longer text wins over a comma qualifier | nit | declined, follows the task's rule 1 |
| geo R4 | "Netherlands" was missing from the country aliases | nit | fixed |
| fayat R1 | Scholars loaded as `hosted_by` their university | nit | fixed: new seed relation `student` loads as `studied_at` |
| fayat R2 | Two alias lines for spellings the page does not use | nit | kept, they are correct ids |
| websplit R1 | Dead `MAX_CHIPS` left in `app.py` | nit | fixed |
| websplit R2 | Blank-line drift after the move | nit | fixed |
| websplit R3 | `app.py` re-exported four debug functions for two tests | nit | fixed: the tests import from `fn.web.debug` |
| plan R1 | Same-name extras and `claims_of` would show a merged record twice | should | fixed in the plan and the T4 task |
| plan R2 | No reader for a person's identifiers | should | fixed: `store.identifiers_of` |
| plan R3 | Nobody wrote the import and export events | should | fixed: `network.record_import`, `record_export` |
| plan R4 | "New" was undefined for a person never opened, and merged-in facts were not new | should | fixed: `add` sets `seen_at`; `merged_at` counts as first seen |
| plan R5 | T10 needed the exporter from T9 | should | fixed: T10 needs T9 |
| plan R6 | No way to read a multipart upload without a new dependency | should | fixed: standard-library parser with a 5 MB cap |
| plan R7 | `test_sections_number_apart` encodes the old section rule | should | fixed: named as an intended change |
| plan R8 | No task hid skipped candidates | should | fixed: T10 owns `list_candidates(include_skipped=False)` |
| plan R9 | "Second row updates the first" contradicted the identifier rule | should | fixed: identical rows are skipped, same-name rows stay two people |
| plan R10 | A typed email was no identifier | should | fixed: `set_contact` attaches it and refuses a taken address |
| plan R11 | `save_candidates` did not write the new fields | should | fixed |
| plan R12 to R14, R16 to R18 | Missing inputs, route order, `fn:` link, task needs, file map | nit | fixed |
| plan R15 | Filter fields beyond one text box | nit | partly: the place token is cut, the two link tokens stay |
| plan R19 | `first_seen_at` came from the store's clock, the other times from the caller's | should | fixed: `upsert_claim(draft, at)` |
| plan R20 | `resolve.run` read canonical ids for hits only | should | fixed: also for same-name records |
| netcore R1 | `add` missed a not-same pair stored on a merged record | nit | fixed with a test |
| netcore R2 | A same-name record that fits no entry is dropped | nit | declined, debug only |
| netcore R3 | Undo treated an equal timestamp as later | nit | fixed with a test: order of writing decides |
| netcore R4 | Migration picks any resolve step when a search has several | nit | declined, a search has one |
| netcore R5 | Pages group claims by stored person ids | nit | follow-up in T6 |
| netcore R6 | Blank line | nit | fixed |
