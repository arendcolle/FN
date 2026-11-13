# Task Q-1b: a chip's position comes from its text

## Goal

A search fails when the model miscounts one character position. In the baseline run of the benchmark, the question "Which business development people or investors in Boston life sciences studied at a Flemish university…" ended as failed after 12 s: the model put the chip "life sciences" five characters off, `parse.check_spans` tolerates two (`SPAN_SLACK`), and it raised `SpanError`. The organizer sees a failed search for a good question. After Q-1 the parse answer holds more chips (roles, the tie), so more positions to miscount. The model copies text well and counts badly, so the code finds each position itself. This task follows Q-1 and touches only `src/fn/parse.py` and its tests.

## What to build

In `src/fn/parse.py`:

- `locate(question: str, text: str, near: int | None) -> Span | None`: every place `text` stands in `question`, compared exactly first; when there is none, compared with both sides casefolded (the lengths are then equal, so the span is still exact). It returns the span whose start is nearest to `near`, the first one when `near` is None or on a tie, and None when the text stands nowhere or is empty.
- `check_spans(question, chips) -> Chips`: for each parsed chip (topics, institutions, roles, the tie, the place): keep the span when `question[start:end]` equals the text; else use `locate(question, chip.text, claimed start)`. A found span replaces the model's, with one info log line as today. When the match was only casefolded, the chip's text becomes the question's own slice, so the text is always a copy of the question. A parsed chip whose text stands nowhere in the question is dropped, with one warning log line `chip {text!r} is not in the question; dropped`. A dropped place or tie becomes None. An edited chip keeps today's rule: it may lack a span and is never dropped.
- `SPAN_SLACK`, `_nearby` and `SpanError` go when nothing uses them any more. Search the package and the tests for each name and update every reference (the debug pages or the worker may name the error type).
- The step's log already holds the log lines of a step; nothing else records the drop.

Nothing else changes: the prompt, the contracts and the chips' other fields stay as Q-1 left them.

## Inputs a real run will meet

A span 5 off; a span outside the question; a span of the right length on the wrong word; a text that stands twice in the question (the nearer one wins); a text whose case differs from the question ("ai" for "AI"); a text the question does not hold ("machine learning" for a question about AI): dropped; every chip dropped: the search goes on with empty chips and the lanes say they have no query; an empty text; a chip without a span from the model; an edited chip without a span; a question with accents and an emoji (positions are counted in Python characters, as today).

## Tests (each must fail without the change)

In `tests/test_parse.py`:

- A topic span 5 characters off comes back on the text, and the search ends done, not failed.
- A text that stands twice gets the occurrence nearest to the claimed start.
- A text in another case gets the question's own slice as its text.
- A text the question does not hold is dropped with a warning, the other chips stay, and the search ends done.
- A place and a tie that stand nowhere become None.
- An edited chip without a span is kept as it is.

## Existing tests that change, approved by the lead

The tests in `tests/test_parse.py` that pin today's rejection follow the new rule: the one whose docstring starts "A span whose slice differs from the chip text, or lies outside the question, raises SpanError", the assertion that a far-off span raises, and the one whose docstring starts "A model answer with a wrong span stops the search at the parse step with a SpanError". Each becomes a test of the repaired span or the dropped chip, with a search that ends done. If Q-1 added a test that a role span 5 off raises `SpanError`, it changes the same way. Say in your report which tests changed and how. No other existing test may change.

## Hand check

`uv run python -m unittest` all green. Then, with a stub model as the tests use, run `parse.run` on the question above with the topic span set to `[62:76]` and print the chips: the span reads `[57:70]` and `question[57:70]` is "life sciences".

## Not doing

- Asking the model again after a bad answer.
- Fuzzy matching of a text that is not in the question.
- Any change to the prompt or to what a chip means.
