# Task D2: take a ROR match only when the organization's name is in the employer text

## Goal

`fn-orgs --match` links an employer name to the organization ROR marks as chosen. A live run on a copy of the owner's data asked 1,897 names and got 683 chosen answers. A sample of every tenth answer showed about one wrong link in ten: a New York medical school linked to a medical school in Indiana, two business schools linked to a school in Ottawa, a peace organization linked to a technology institute in Vienna. A wrong link gives a person a wrong place, and the ranker then sets them aside or shows them for the wrong city. A simulated rule, "one of the organization's names stands in the employer text, or the other way round", keeps 483 of the 683 and none of the wrong ones in the sample. Most of the 200 it drops are right but abbreviated ("Stanford U. Graduate School of Business"); reading a lone "U" as "University" brings many of them back.

## What to build

### `src/fn/orgs.py`

- `ror_names(record: dict) -> list[str]`: every `value` of the record's `names`, of any type, leaving out an acronym shorter than 3 characters. A record without names gives an empty list.
- `words(text: str) -> list[str]`: the words of `fold(text)`, with a lone `u` read as `university`. Punctuation separates words, so "U." and "U" both count.
- `named(record: dict, name: str) -> bool`: true when the words of one of `ror_names(record)` stand as a run of whole words in the words of `name`, or the words of `name` stand as a run in the words of one of them. An empty name or an empty list gives false.
- `chosen(body, fetched_at, name)` gains the employer name. It returns the facts only when exactly one item is chosen and `named(that organization's record, name)` holds. Otherwise None, as for no chosen item. `match` passes the name and stores the answer as before, so a match that fails the name check is remembered as no match and is not asked again.

Nothing else changes: the pace, the stored answers, the linking and the job output stay as they are.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which ROR answer counts as a match | `orgs.chosen` with `orgs.named` |
| Which names a ROR record goes by | `orgs.ror_names` |

## Inputs a real run will meet

A chosen organization whose display name differs from the employer text but whose alias or label matches ("CalTech"); an employer text that holds the organization's name plus a department; an organization name that holds the employer text; an abbreviated "U." or "U"; an acronym of two letters; names in another language; a record without names; an employer text of punctuation only.

## Tests (each must fail without the change)

In `tests/test_orgs.py`, with made-up organizations and hand-written answers in the documented shape:

- A chosen organization whose names do not stand in the employer text is not linked, and the name is stored as asked with no organization.
- A chosen organization is linked when its display name stands in a longer employer text, when an alias equals the employer text, when the employer text stands inside its name, and when the employer text writes "U." for "University".
- A two-letter acronym alone does not make a match; a four-letter acronym does.
- `named` is false for an empty name and for a record without names.

## Existing tests that change, approved by the lead

The existing match tests call `chosen` or run `match` with fixtures whose organization names stand in the employer text, so they should pass unchanged. A test that calls `chosen(body, fetched_at)` directly gains the name argument. No other existing test may change; stop and report.

## Hand check

`uv run python -m unittest` all green. No live call.

## Not doing

Fuzzy matching, a score threshold, other abbreviations than "U", undoing links a past run made.
