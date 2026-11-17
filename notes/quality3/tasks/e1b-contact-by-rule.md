# Task E1b: contact details by rule, for every looked-up person

## Goal

The lookup step (task E1, in this worktree, not merged yet) asks the model for an email address and a phone number and stores them only for the first ten people. A live run of two questions made 50 lookups, read 30 pages of which 14 print an address, and stored no email and no phone. A probe on six of those pages showed why: the model returned an address for one page of six, reported one person up to ten times on a page, and the one address it returned stood 1,492 characters from the mention and was still dropped. This task finds contact details with code, on pages that already passed the identity rule, and stores them for every looked-up person.

## What to build

### `src/fn/extract.py`

- `contacts(person_id: str, source: Source, name: str) -> list[ClaimDraft]` replaces today's `contacts(person_id, source, located, mention)`. It reads `source.text` only:
  - Email: every match of the existing `EMAIL` pattern in the text (searched, not full-matched; trailing punctuation left out). An address is the person's when the surname stands in its local part, or when it starts within `CONTACT_REACH = 300` characters of a place where the text writes the person's name. The surname is the last word of `name_key(name)`, compared with the local part after `name_key` with spaces removed, and counts only when it has 3 letters or more. The name's places in the text are found with the same word-run search `_near` uses for a name (reuse it; do not copy it). At most one email: the first that qualifies, an address with the surname before one that only stands near the name.
  - Phone: a run that `PHONE` matches, where `PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().\-/]{6,18}\d(?!\w)")` and the digits number 7 to 15. A phone is the person's when it starts within `CONTACT_REACH` characters of a place where the text writes the name, or within `CONTACT_REACH` characters of the stored email. At most one phone, the nearest.
  - Each claim has the value as printed, the quote from `_line`, and the date fields of `page_dated(source)`, as today.
- `PersonMention` loses `email` and `phone`; `died` stays. Remove what only they used.

### `src/fn/prompts/extract_person.md`

The whole file becomes, word for word:

```
Report only the person named in the <person> block, in one entry that gathers what the text says about them. Report a person only when the name the text writes matches that name: the text may write it with initials for the first names, without a middle name, or with the same words in another order. Report nobody else, even though the rules above say to list every person the text names. The entry has one more field. died: the four-digit year the text says this person died, else null. When the text does not name this person, return an empty list.
```

### `src/fn/deepen.py`

- Contact details are stored from every confirmed page of kind `employer` or `own`, for every looked-up person: drop the `pick.contact` condition where claims are stored, and call `extract.contacts(person_id, source, pick.name)` once per confirmed page, not once per mention. `Pick.contact` keeps its one job: it lets a person of the first `CONTACT_TOP` without contact details be picked.
- `WORKERS` goes away: the lookup calls run `ctx.settings.llm_workers` at once, like every other fan-out.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which email and phone on a page are the person's | `extract.contacts` |
| From which pages and for whom contact details are stored | `deepen.py` |

## Inputs a real run will meet

An address with the surname far from the name; an address near the name without the surname; a department address near another person's name (not taken); two addresses that qualify; a surname of two letters; a name the page writes with a middle name; a page without any address; a phone next to the email and far from the name; a fax or a year range that looks like a number (a run of 4 digits is not a phone); an address followed by a full stop; text with "name at example dot org" (not taken).

## Tests (each must fail without the change)

In `tests/test_extract.py`, replacing the tests of the old `contacts`, with made-up names and the `example.org` domain: one test per input above. In `tests/test_deepen.py`: a looked-up person beyond the first ten gets the email of a confirmed employer page; a confirmed page of kind `other` stores none; the page's email is stored once when the reading returns the person twice.

## Existing tests that change, approved by the lead

The tests this slice added for the old `contacts` and for `PersonMention.email` and `.phone` (in `tests/test_extract.py` and `tests/test_deepen.py`) change with the functions they test. The test that pins the `extract_person` prompt text or hash, if any, takes the new text. Nothing else may change; stop and report.

## Hand check

`uv run python -m unittest` all green. `uv run python -c "from fn import llm; print(llm.system_prompt('extract_person')[-700:])"` ends with the new paragraph. No live call.

## Not doing

Addresses written in words, more than one email per person, any change to the identity rule, the page markup.
