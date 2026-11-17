# Task G4: a phone number must look like one

## Goal

`extract.contacts` stored 19 phone claims on the owner's database. 8 are no phone number: page ranges, a DOI, a handle address, an author id and a bare run of 8 digits. This task makes a run count as a phone number only when it has a mark: a leading `+`, the North American shape, or a phone label right before it on the same line. The reach rule, the 7 to 15 digits, the fax rule and "the nearest wins" stay. Owner: `extract.py` (brief G4, decision of the lead).

## What to build

### `src/fn/extract.py`

Add these next to `PHONE` and `NOT_PHONE` (lines 36 to 38). Keep `NOT_PHONE`: one case is left that the marks do not reject, a label word followed by a year range ("Cell 2019-2020", a journal, and "T 2019-2024"). Removing it makes both a phone in the scratch check.

```python
# A run is a phone number only with a mark: a leading +, the North American shape, or a label right before it.
NORTH_AMERICAN = re.compile(r"(?:1[ .\-])?(?:\(\d{3}\) ?|\d{3}[ .\-])\d{3}[ .\-]\d{4}")
PHONE_LABEL = re.compile(r"(?<!\w)(?:t[eé]l(?:[eé]phone|efoon|efon)?|phone|ph|mobile|cell|gsm|t|m)\.?[^\S\n]*:?[^\S\n]*\Z",
                         re.IGNORECASE)
LABEL_REACH = 40


def _is_phone(text: str, start: int, run: str) -> bool:
    """True when the PHONE run at start is a phone number: 7 to 15 digits, no date or fax, and a mark."""
    digits = len(re.sub(r"\D", "", run))
    if not 7 <= digits <= 15 or NOT_PHONE.fullmatch(run.strip("()")) \
            or "fax" in text[max(0, start - 8):start].casefold():
        return False
    return (run.startswith("+") and digits >= 8) or bool(NORTH_AMERICAN.fullmatch(run)) \
        or bool(PHONE_LABEL.search(text, max(0, start - LABEL_REACH), start))
```

`PHONE_LABEL` reads at most 40 characters before the run (`pos`, `endpos`; `\Z` holds at `endpos`). Its lookbehind still sees the character before `pos`, so "hotel" cut to "tel" is no label. `[^\S\n]` keeps label and number on one line.

In `contacts` (line 325), the phone loop (lines 352 to 357) becomes:

```python
    for m in PHONE.finditer(text):
        gap = reach(m.start(), places + ([email[1]] if email else []))
        if gap is not None and _is_phone(text, m.start(), m.group()):
            phones.append((gap, m.start(), m.end()))
```

The docstring's phone sentence becomes: "A phone is a PHONE run with a mark (`_is_phone`) that starts within CONTACT_REACH of such a place or of the email; the nearest wins." Nothing else in `extract.py` changes.

### Callers

`contacts` has one caller, `deepen.py:273`. Its signature does not change, so `deepen.py` does not change.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a run of digits is a phone number | `extract._is_phone` |
| Which email and phone on a page are the person's | `extract.contacts` |
| From which pages and for whom contact details are stored | `deepen.py` |

## Recorded answers, replay and stored searches (S6)

No prompt changes, so every recorded model answer stays valid. No stored claim changes; the lead cleans them after the merge. `rank.py` and `evidence.py` read no phone claim, so a search stored with version-1 chips keeps its order exactly. Only new lookups store fewer phones, and `deepen.py:104` then counts such a person as without contact details.

## Inputs a real run will meet

All 58 cases below ran against the patterns in a scratch copy, as expected. Tests 1 to 7 cover them.

- Taken: the right shapes of the brief, `+1 (999) 999-9999`, a `+` number inside an address (`?tel=+3216321000`), "T +32 ...", "M: 0470 12 34 56", "Phone : ", the Dutch, French and German labels, "Tel 016/32 10 00", "Tel: 12345678".
- Not taken: the 8 wrong shapes, a fax that starts with `+`, a label on the line before, "hotel 2019 2020", "Intel 8086 4004", "cell biology 2019-2020", "Cell 2019-2020", "Ph.D. 2019 2023", `1234-617-555-0100`, a bare `016/32 10 00`, "+1234567", a labelled run of 16 digits, a text with no number.
- "617-555-0100 x123" and "ext. 123" give `617-555-0100`. Two marked numbers: the nearer wins. The same number twice: one claim.
- A page with 5,000 page ranges or a 200,000-character line: under 0.1 s.

## Tests (each must fail without the change)

In `tests/test_extract.py`, class `PersonTest`, with its `contacts` helper (line 648) and the made-up "Jan Peeters". Each test holds a run that today's rule takes wrongly:

1. `test_a_page_range_or_an_issue_is_no_phone`: "2001, pp. 1234-5678", "59, p. 123-456. 78", "Waves, 12(3). 123-456" and "36 (Dec 2023): 1234-5678" each give `[]`.
2. `test_a_doi_a_handle_or_an_id_in_an_address_is_no_phone`: "doi: 10.1007/s13280-019-01234-5", "https://hdl.handle.net/2066.1/123456" and "detail.uri?authorId=12345678901" give `[]`; "https://example.org/?tel=+3216321000" gives that number.
3. `test_a_bare_run_is_no_phone_and_a_label_on_its_line_makes_it_one`: "\n12 Example Street\n12345678\n" gives `[]`; "Phone:\n016 32 10 00" gives `[]`; "Tel 016/32 10 00" and "Phone : 016 32 10 00" give the number.
4. `test_each_label_marks_a_run`: "M: 0470 12 34 56", "Tél.: 01 23 45 67 89", "Téléphone", "Telefoon", "Telefon:", "GSM", "Mobile", "cell:" give the number; "016/32 10 00" bare gives `[]`.
5. `test_a_label_inside_a_longer_word_is_no_label`: "hotel 2019 2020", "Intel 8086 4004", "cell biology 2019-2020", "Cell 2019-2020" and "Ph.D. 2019 2023" give `[]`.
6. `test_the_north_american_shape_and_a_plus_mark_a_run`: "(617) 555-0100", "617.555.0100", "617 555 0100", "1-617-555-0100" and "+32 16 32 10 00" are taken; "1234-617-555-0100" gives `[]`.
7. `test_a_marked_number_wins_over_a_nearer_unmarked_run`: "Jan Peeters, pp. 1234-5678. Tel 617-555-0100" gives `617-555-0100`; "Fax +32 16 32 19 99. Tel +32 16 32 10 00" gives the second; "617-555-0100 x123" gives `617-555-0100`.

## Existing tests that change, approved by the lead

None. All 1,120 tests pass unchanged with the change applied in a scratch copy; the fax test (line 698) uses North American numbers. No existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. Then `D=$(mkvar.sh g4)` and this script, which prints per stored phone claim its shape (digits as 9), whether the new rule returns it, and the shape of any other phone returned:

```python
import re, sqlite3, sys
from fn import extract
from fn.contracts import Source
from fn.store import SOURCE_COLUMNS
shape = lambda v: re.sub(r"\d", "9", v)
db = sqlite3.connect(sys.argv[1]); db.row_factory = sqlite3.Row
cols = ", ".join(f"s.{c}" for c in SOURCE_COLUMNS)
for row in db.execute(f"SELECT c.person_id, c.value, p.display_name, {cols} FROM claims c JOIN sources s ON s.id = c.source_id "
                      "JOIN persons p ON p.id = c.person_id WHERE c.kind = 'phone' ORDER BY c.rowid"):
    source = Source.model_validate({c: row[c] for c in SOURCE_COLUMNS})
    got = [d.value for d in extract.contacts(row["person_id"], source, row["display_name"]) if d.kind == "phone"]
    print(f"{shape(row['value']):20} same={row['value'] in got} other={[shape(v) for v in got if v != row['value']]}")
```

Run `uv run python handcheck.py "$D/fn.sqlite3"`; it makes no network call. Expected, from a read-only run by the planner:

- The 11 right numbers print `same=True`.
- The 8 wrong ones print `same=False`.
- Seven of the wrong ones return nothing. The handle address returns `999999999`, a run after "Phone : " on the same page that the nearer handle used to beat.

## Lead rulings before the build

- **No lone letter is a label.** `PHONE_LABEL` loses `t` and `m`: `(?<!\w)(?:t[eé]l(?:[eé]phone|efoon|efon)?|phone|ph|mobile|cell|gsm)\.?[^\S\n]*:?[^\S\n]*\Z`. None of the 19 stored numbers has such a label, a `+` number after "T" or "M" has its own mark, and a CV writes initials such as "M." before numbers. In test 4, "M: 0470 12 34 56" becomes "Mobile: 0470 12 34 56", and one more case there: "Peeters, M. 12345678" gives `[]`. `NOT_PHONE` stays for "Cell 2019-2020". The last but one line of "Not doing" falls away.
- **Two more cases in test 6:** "+32-(0)16 32 10 00" is taken, and "+1234567" (7 digits) gives `[]`.

## Not doing

- The email rule, the reach rule, which pages give contact details, and the page reader.
- Cleaning stored claims. The lead does that after the merge.
- An extension written without a space (`617-555-0100x123`), which `PHONE` does not match today.
- `F` or another short fax label. Only "fax" stays a fax label.
- A lone "M." initial right before 8 or more digits counts as a label, as the brief's lone `m` says.
- The `EMAIL` pattern takes about 1 s on a 20,000-character run without spaces. This is older than this task; it is a follow-up.
