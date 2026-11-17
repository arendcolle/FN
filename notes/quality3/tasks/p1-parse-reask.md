# Task P1: ask the parse task again when its reading is thin

## Goal

About 1 live parse answer in 110 holds one chip for a question with three wishes. For "Political scientists in New York City specializing in federal politics" the model returned only "federal politics", leaving 6 of 8 content words unread, and the search ran 214 s on that reading. The number of unread words alone does not mark the slip (a long spoken question has many words no chip should cover); the chip count does: no good reading of 160 has fewer than 2 chips (`research/parse-slip.md`). `parse.run` now asks once more when a reading has at most one chip and leaves three or more content words unread, and keeps the reading with more chips.

## What to build

### `src/fn/parse.py` (the only file of code that changes)

- `THIN = 1` and `UNREAD_WORDS = 3`, next to `MAX_RELATED` (line 31), under one comment line that says what they do.
- `chip_count(chips: Chips) -> int`: `len(_all_chips(chips))` (line 110): topics, institutions, roles, the tie and the place.
- `unread(question: str, chips: Chips) -> list[str]`: the words of `content_words(question)` (line 43) that are not read, in order. A word is read when it is in `content_words` of some chip's span slice `question[span.start:span.end]` (the chip's `text` when its span is None), over `_all_chips(chips)`. Words are compared as the set `content_words` gives, not by character position.
- `_reading(ctx: StepContext, question: str) -> Chips`: today's body of `run` (lines 185 to 197) moved unchanged: ask, `SpanError` for an edited chip, clean, `version` 2, `check_spans`.
- `run`: the `ctx.llm is None` check stays. `first = _reading(ctx, inp.question)`. When `chip_count(first) <= THIN and len(unread(inp.question, first)) >= UNREAD_WORDS`, call `_reading` once more inside `try`/`except Exception as exc:  # noqa: BLE001 a failed second ask keeps the first reading`, which logs `log.warning("second parse ask failed, first reading kept: %s", exc)` and returns the first. Return `ParseOut(chips=second if chip_count(second) > chip_count(first) else first)`. An error of the first ask raises as today. Never more than two asks. Add one docstring line: "Asks once more when the first reading is thin and keeps the reading with more chips."

`search.py`, `prompts/parse.md`, `llm.py`, the contracts and the pages do not change.

### What this does to recorded answers and replays (S6)

The prompt does not change, so no recorded answer gets a new key and no file under `tests/fixtures/llm` changes. A replayed thin question serves the same answer twice: the parse step records two llm calls, each with the recorded cost, and keeps the first reading, so its chips are unchanged.

- Recorded fixtures: 4 of 30 are thin: `1712b194e5dea48f` (1 chip, 12 words unread), `6aa4a910e46b6393` (1, 10), `9039843197d830df` (1, 7), `ae62cd967e0584da` (1, 11). The other 26 have 2 to 4 chips. None sits under today's prompt key; `test_parse` re-keys only the two telecom answers (3 chips each) and `test_linkedin` reads GS-02's value directly.
- The owner's `var/llm` holds 2 parse answers under today's key, none thin; on a trial copy each replays to the same chips with one call.
- `fn-score run` replays with the stored chips, so the parse step is skipped: no change.
- In record and live mode the second answer is written under the same key and replaces the first. A later replay then serves the second answer to both asks, so when the live run kept the first reading, a replay of that search can give other chips. Reruns and `fn-score` use the stored chips and are not affected.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| A reading: ask, clean, check spans | `parse._reading` |
| Chip count and unread words | `parse.chip_count`, `parse.unread` |
| Whether to ask again and which reading to keep | `parse.run` |
| Recording and replaying each ask | `llm.FixtureLLM` (unchanged) |

## Inputs a real run will meet

A question without content words (nothing unread, one ask); a short question with one chip and one or two words unread ("Who is based in Chicago?", one ask); an empty answer `{}` (0 chips, asks again); a 1,000-character question, the form's limit, with one chip (asks again); two equal topic chips (count 2, one ask); a second answer that fails the schema, claims an edited chip or loses every chip in the span check (first kept); a first ask that raises (the step fails as today; `test_model_answer_claiming_an_edited_chip_fails_the_step` and the bad-language case of the queries test in `tests/test_parse.py` cover it).

## Tests

Each test fails without the change, except the two marked as guards, which pass on main and fail when the code asks too often.

In `tests/test_parse.py`, with a local fake `Turns(answers)` that returns or raises its answers in order and counts calls. `SLIP` is the question above; `ONE` is the topic "federal politics"; `FULL` adds the role "Political scientists" and the place "New York City".

- `test_unread_counts_content_words_outside_every_chip`: `SLIP` with `ONE` leaves political, scientists, new, york, city and specializing unread, `chip_count` 1; with `FULL`, specializing and 3; a question without content words leaves none.
- `test_a_thin_reading_is_asked_again_and_the_fuller_one_kept`: `[ONE, FULL]` returns `FULL`, two calls.
- `test_two_chips_or_a_mostly_read_question_ask_once` (guard): `SLIP` with "federal politics" and "Political scientists" (two chips), "Who knows offshore wind?" with "offshore wind" and "Who knows wind?" with "wind" (one word unread) each make one call.
- `test_a_second_answer_without_more_chips_keeps_the_first`: `[ONE, {}]`, `[ONE, the topic "politics"]` and `[ONE, a topic whose text is not in the question]` keep `ONE`, each after two calls.
- `test_a_second_ask_that_raises_keeps_the_first_and_logs_one_line`: second turns `LLMCallError`, a `ValidationError` from a bad answer, and an edited chip: `ONE` kept after two calls, one warning each.
- `test_inputs_a_real_run_meets`: `{}` asks twice; a 1,000-character question with one chip asks twice; two equal topics ask once (guard).
- `test_a_replayed_thin_question_gives_the_same_chips`: record `ONE` with `FixtureLLM` in record mode over `StubLLM`, replay through a `Worker`: same chips, parse step with two llm calls.

## Existing tests that change, approved by the lead

Two of 1,096 tests pin the cost of a search whose stub reading is thin (GS-10's stub reading has 1 chip and 10 words unread), and take the cost of the second ask.

- `tests/test_gold.py` `RunCaseTest.test_the_report_names_the_lanes_behind_each_pick_and_the_vendor_and_llm_cost_of_the_search`: `llm_cost_usd` from 0.012 to 0.014 and "LLM $0.0120" to "LLM $0.0140".
- `tests/test_gold.py` `StubbedRunTest.test_the_search_cost_is_split_into_vendor_and_llm_call_costs`: `llm_cost_usd` from 0.002 to 0.004; the docstring says "the two stub parse calls, $0.004".

Other tests that make a thin reading pin no count and pass unchanged. No other existing test may change; stop and report a failure.

## Lead ruling after the build

The first build used a share: at most one chip and at least half of the content words unread. That rule asks again for a short question with one wish and one more word ("Who is based in Chicago?", "Who knows wind?"): one of the owner's stored readings, and two more pinned tests. The rule became a word count: at most one chip and three or more content words unread. It still asks again for the slip (6 words unread) and for none of the 190 good readings measured (30 stored with today's chip format, 160 asked live). `tests/test_steps.py` and `tests/test_llm.py` keep their old expectations.

## Hand check

```
uv run python -m unittest
```

Then, from this worktree and from one pinned to main, replay each parse answer in `/Users/arend/Developer/FN/var/llm` through `parse.run` with `SimpleNamespace(llm=FixtureLLM(folder, "replay"))` and a `CallBuffer(parent=None)` set on `steps._recorder`, skipping `FixtureMissing`. Expected: equal chips on both sides, one call each.

## Not doing

- Any change to `prompts/parse.md`, a retry hint, or a new task name.
- A check against the place index for a missing place.
- Voting over more than two answers.
- Any change to what the results page shows.
