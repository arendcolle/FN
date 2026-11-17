# Task R1: required wishes filter, wishes order

## Goal

On "Belgian scientists in the Washington D.C. area" the place parsed as a wish and no code reads a place's need: 75 of 104 people under the first heading are known to be elsewhere, 342 are kept. This task makes such a place required (N1), sets aside kept people known to fail a required wish (N2, N3, N8), sorts unknown places after inside ones (N4, N5) and caps two headings at 50 (N6, N9). A planning run of it left 51 people open, none known elsewhere.

## What to build

### `src/fn/prompts/parse.md`

On line 13 the sentence `A place is "must" only when the question says the people must be based or live there, else "nice".` becomes, word for word:

```
A place is "must" when it says where the people are ("scientists in the Washington D.C. area", "Who in Chicago", "Boston-based founders"). A place is "nice" when a word such as "ideally", "preferably" or "near" softens it, and when it only names where the event is held ("at our event in New York").
```

`When unsure, use "nice".` stays after it.

### `src/fn/parse.py`

`place_must(chips: Chips) -> bool` beside `tie_must` (line 90): `chips.version >= 2 and chips.place is not None and chips.place.need == "must"`.

### `src/fn/contracts.py`, `store.py`, migration

- `CutReason` (line 53) gains `"over_cap"`. New `Aside = Literal["outside", "abroad", "unfit"]`. `Candidate` (line 431) gains `aside: Aside | None = None`. `ResultsView` (line 562) gains `matched: int = 0`.
- `src/fn/migrations/013_candidate_aside.sql`: `ALTER TABLE candidates ADD COLUMN aside TEXT;`. `save_candidates` (line 567) writes it, `list_candidates` reads it.

### `src/fn/rank.py`

- `FITS_MUST = ("inside", "none")`, `ASIDES = (None, "outside", "abroad", "unfit")`, `HEADING_CAP = 50`, `CAPPED = (3, 4)`.
- `tier` (line 185), N4: with `parse.place_must`, `fits` reads `FITS_MUST`, so an unknown place falls to tier 2 or 4, same heading.
- `order_key` (line 224), N5: on version-2 chips the place spot precedes the tie grade. Version 1 keeps today's tuple.
- Under `parse.place_must`, tiers 5 and up put the spot right after the heading, before role, so N4 holds under heading 3 too.
- `aside(section, found, question, verdict) -> Aside | None`: None for the network section, no evidence or version-1 chips. Else the first that holds: `"outside"` when `place_fit` is outside and `parse.place_must`; `"abroad"` when `place_fit` is abroad, the chips have a place and `question.country == "US"`; `"unfit"` for verdict "no".
- `Row` (line 274) gains `aside`, set in the `fuse` loop. `fuse` is the only caller of `tier` and `order_key`.
- `fuse` (line 318), after `exempt` and `no_tie`: stable-sort rows by `0 if r.reason else ASIDES.index(r.aside)`; `spots` leaves out aside rows, so `capped` never moves anyone past them; `over_cap(kept, question) -> set[int]` gives, on version-2 chips, the people past the first `HEADING_CAP` of each heading in `CAPPED` (`r.key[1]`), cut `"over_cap"`. The Candidate gets `aside=None if r.reason else r.aside`. `over_cap` runs after `capped`, on the `spots` list without aside rows. `exempt` picks its 20 slots before aside applies, so a person set aside can hold one; N2 reads that way.

### `src/fn/present.py`

- `ASIDE_HEADINGS = {"outside": "Outside the area asked for", "abroad": "Outside the US", "unfit": "Work does not match the question"}`, `UNFIT_LINE = "The fit check says this work does not match the question"`.
- `heading_of` (line 573) returns the aside heading, so `results_headings` lists the groups after the open headings.
- `is_open(candidate) -> bool`: network section, no tier, or no aside and `rank.heading(...) <= 3`.
- `place_reason(store, candidate, today) -> ReasonView | None`: the claim of `evidence.shown(evidence.places(...))` over `identity.on_card`, through `claim_view` and `reason_of`. It is the place fact the ranker read.
- `card_view` (line 668): an outside or abroad card's reason line is `place_reason`, else today's; an unfit card's second line is `UNFIT_LINE`.
- `results` (line 704): `network`, `new`, `matched` and `not_on_map` all count the same people, the open list (`is_open`) without skipped people, which the map reads. So `matched` holds open network people, people without a tier and headings 1 to 3. `total` and `order` keep everyone. `is_open` reads no chips version, so a version-1 page also drops its heading-4 people from the map and the count; its order stays. That is intended.

### `src/fn/web/staff.py`, `notes/e2e/design-system/STRINGS.md`

`person_cards` (line 177) passes `found.matched` to `count_line`; the map flag becomes `found.matched > found.not_on_map`. STRINGS.md line 39 adds the three group headings; the count covers the open network people and headings 1 to 3.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether the place is required | `parse.place_must`, `prompts/parse.md` |
| Tier and order under a required or wished place | `rank.tier`, `rank.order_key` |
| Who stands aside, and why | `rank.aside` |
| Group order and caps | `rank.fuse`, `rank.over_cap` |
| Storing `aside` | `store.py`, migration 013 |
| Headings, card lines, headline count, map people | `present.py` |
| Showing the count and the map | `staff.person_cards` |

## Inputs a real run will meet

A place without `need` (nice); a place of kind abroad; a must `anywhere_us`; a must place not located (nobody aside); no entries; outside plus "no" (outside wins); an exempted OpenAlex person outside a must area; a network person outside it; 120 people under heading 4; a place claim gone since ranking; a row from before migration 013; version-1 chips with a must place.

## Tests (each must fail without the change)

- `tests/test_parse.py`: `place_must` for version 1, no place, nice and must; the prompt holds the N1 sentence.
- `tests/test_rank.py`, one test per rank input above, and: a must place sets an outside person aside, kept, after every open person despite the best score, a nice place keeps them in tier 2; abroad under a nice US place is aside; must puts unknown in tier 2 behind a worse-scored inside person, and in tier 5 behind an inside person with a weaker role; nice puts an inside medium tie before an unknown strong tie, version 1 the reverse; "no" gives `unfit` on version 2 only; 60 people in each of tiers 1, 5 and 7 lose 0, 10 and 10 to `over_cap`; OpenAlex-only people never pass an aside row.
- `tests/test_db.py`: `aside` round-trips; an old row reads `None`.
- `tests/test_results_headings.py`: groups follow the open headings; the count covers headings 1 to 3; a search with a network person without a place and a new person under heading 1 without a place gives `matched` 2 and `not_on_map` 2; an outside card names its place fact and source; an unfit card shows `UNFIT_LINE`.
- `tests/test_map.py`: aside and heading-4 people are off the map.

## Existing tests that change, approved by the lead

Each pinned migration list gains 13: `tests/test_db.py` lines 77 and 103, `tests/test_orgs.py` line 319, `tests/test_web.py` line 653. In the planning run every other test passed. No other existing test may change; stop and report.

## Recorded model answers and replay (S6)

Parse recordings get new keys. No test reads one by key; the 30 tracked fixtures already miss today's key. In `var/llm` two match it: midterms (stays nice) and Washington (N1 makes it "must"). Re-recorded, these tracked ones turn must: 0327b7c7, 0c894bed, 1712b194, 3cb0d4a3, 5d423891, 72c5775a, 90398431, 9347cda2, 9d7fe320, a275f91b, ae62cd96, c4472fed, d43f3873, d608109b, de924a9f, e3943d32. Other prompts stay. Fit batches follow rank order, so a full replay of a version-2 place search can miss a fit recording and end without verdicts; reranks read stored verdicts.

The re-key renames files matching today's key and keeps their bytes, so the JSON `key` field keeps the old value; `llm.py` line 168 only writes it, nothing reads it. Run it from the worktree per folder:

```
uv run python - var/llm <<'EOF'
import json, subprocess, sys
from pathlib import Path
from fn import llm
from fn.contracts import Chips
old = subprocess.run(["git", "show", "main:src/fn/prompts/parse.md"], capture_output=True, text=True, check=True).stdout
key = lambda system, user: "parse-" + llm.prompt_sha(system, user, llm.schema_json(Chips), llm.MODEL)[:16]
for path in sorted(Path(sys.argv[1]).glob("parse-*.json")):
    user = json.loads(path.read_text())["prompt"]
    if path.stem == key(old, user):
        path.rename(path.with_name(key(llm.system_prompt("parse"), user) + ".json"))
        print("re-keyed", path.name)
EOF
```

## Hand check

`uv run python -m unittest` all green. Copy the owner's data to `$A` and `$B` (`sqlite3 var/fn.sqlite3 ".backup $A/fn.sqlite3"`, `cp -R var/cache $A/`). With `FN_HTTP=replay FN_LLM=replay`, run `FN_VAR=$A uv run fn-rerank --all` from a worktree pinned to main (`git worktree add --detach $WA f9965da`) and `FN_VAR=$B ...` from the worktree. Version-1 candidate rows differing in section, rank, cut reason or tier: 0. On `$B`, set the Washington place need to "must" (`store.set_search_chips`), run `search.refinish`: five inside people lead the new section, the sixth stands in the network section, nobody open is outside or abroad.

## Not doing

Deaths and age (A1 to A3), the question line (N7), closing the groups, lookups. The fit check still sends aside people in tiers 1 to 4. `search.first_heading`, `score.py`, the searches list count and the export still count aside people.
