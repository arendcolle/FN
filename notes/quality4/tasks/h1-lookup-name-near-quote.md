# Task H1: a looked-up page counts when it names the person next to the model's quote

## Goal

12 of 77 recorded `extract_person` answers are dropped only because the quote lacks the model's name (`extract.py:138-139`), and the lookup stores "does not name the person". All 12 are about the looked-up person. The lookup's reader now keeps such a mention when the model's name is the person and the chunk writes a name form of the person inside the quote or at most `NAME_REACH` (1,000) characters before it. 11 of the 12 then count; 6 of 13 `not_sure` lookups should become confirmed. Brief H1.

## What to build

Two commits: first the structural split (no behaviour change), then the fallback.

### `src/fn/extract.py`, commit 1: split `check` (line 120)

- New `_drop(source: Source, mention: PageMention, stage: str, reason: str) -> Considered`: the body of today's inner `drop`, with `name = clean_name(mention.name)` and `person_key=identifier(source.url, name).value`.
- New `_attached(source: Source, end: int, span: tuple[int, int], mention: PageMention) -> tuple[Located, list[Considered]]`: lines 140 to 167 of today's `check` moved unchanged (relations, topics, the `Located`), calling `_drop`.
- `check` keeps its signature, its three mention drops and their rows, and ends with `return _attached(source, end, span, mention)`. Its behaviour does not change; every existing test passes unchanged.

### `src/fn/extract.py`, commit 2: the fallback

Add `from collections.abc import Callable`, and next to `NAME_REACH`:

```python
# A name form is the last word of the person's name with up to this many words before it, on one line.
FORM_WORDS = 3
NAME_TOKEN = re.compile(r"[^\W\d_][\w.'-]*")


def name_forms(text: str, start: int, end: int, person: str, same: Callable[[str, str], bool]) -> list[int]:
    """Where in text[start:end] a name form of person starts: the last word of the name with up to FORM_WORDS words
    before it on one line, accepted by same(person, form)."""
    last = name_key(clean_name(person)).split()[-1:]
    tokens = list(NAME_TOKEN.finditer(text, start, end))
    found = []
    for i, token in enumerate(tokens):
        if name_key(token.group()).split()[-1:] != last:
            continue
        for k in range(1, FORM_WORDS + 1):
            if i < k or "\n" in (form := text[tokens[i - k].start():token.end()]):
                break
            if same(person, form):
                found.append(tokens[i - k].start())
                break
    return found


def anchored(source: Source, start: int, end: int, mention: PageMention, person: str,
             same: Callable[[str, str], bool]) -> tuple[Located, list[Considered]] | None:
    """The mention at its own quote when its name is the person by same and the chunk source.text[start:end] writes a
    name form of the person inside the quote or starting at most NAME_REACH characters before it; else None."""
    if len(name_key(clean_name(mention.name)).split()) < 2 or not same(person, mention.name):
        return None
    span = locate(source.text, mention.quote, start, end)
    if span is None or not any(at >= span[0] - NAME_REACH for at in name_forms(source.text, start, span[1], person, same)):
        return None
    return _attached(source, end, span, mention)
```

This is the research script's token rule, except that a token matches on its last folded word, so "D'Hondt" and "Smith-Jones" (one token, two folded words) still start a form; the measured 11 of 12 holds. `_near` (line 315) does not fit: it finds one fixed phrase.

`read_person` (line 219) gains `same: Callable[[str, str], bool] | None = None`. The loop names the person (`for (source, person), cuts in ...`), and line 249 becomes:

```python
                located, dropped = check(source, start, end, mention)
                if located is None and same is not None and (kept := anchored(source, start, end, mention, person, same)):
                    located, dropped = kept
```

`anchored` runs only after `check` drops a mention and repeats its two-word and quote-found tests, so it keeps only "name not in quote" drops. Docstring sentence: "With same, a mention dropped because its quote lacks its name is kept when `anchored` accepts it." `read_all` and `check` are untouched.

### `src/fn/deepen.py`

Line 205 passes the name rule: `extract.read_person(ctx, [...], same=named_as)`. `named_as` (line 128) does not change and stays the one name rule. Nothing else changes: `attach`, `same_one` and the detail words stay.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a name is the looked-up person | `deepen.named_as` (unchanged) |
| Where a page writes a name form, and keeping a mention at its quote | `extract.name_forms`, `extract.anchored` |
| The strict mention check for every lane | `extract.check` (behaviour unchanged) |
| Handing the name rule to the reader | `deepen.look_up` |
| Held fact and the lookup's verdict | `deepen.same_one`, `deepen.attach` (unchanged) |

## Recorded answers, replay and stored searches (S6)

No prompt or task changes, so all 77 `extract_person` recordings and every other recording replay; the fallback reads answers after they come back. A replayed lookup can now confirm a page it marked `not_sure`, store its claims, and change that person's place in the second ranking. Searches with version-1 chips run no lookup (`deepen.py:169`), and `fn-rerank` runs none, so stored searches keep their order exactly.

## Inputs a real run will meet

Title line under a name heading (test 1); first-person bio under a heading (1); nickname in brackets (4); two of three name words (4); the name only in the title line `deepen` puts first (5); a namesake near the quote with the person far (3); two people near one quote (2); the name in an earlier chunk (5); the name past `NAME_REACH` or after the quote (1, 5); an empty quote (4); a quote not on the page (4); a one-word name (4); a surname with an apostrophe or hyphen (4); the same mention twice (1); a chunk full of the surname (6).

## Tests (each must fail without the change)

Made-up names only. In `tests/test_deepen.py`, `DeepenTest`, with `serve`, `deepen` and `held`:

1. `test_a_quote_under_the_name_heading_confirms_the_page_and_a_far_or_later_name_does_not`: page "Faculty\nJan Peeters\nProfessor of physics at Example University.\nMore", the model quoting the title line with a `works_at` relation, returned twice: `added`, one role claim quoting the title line. The same quote with the name only 1,001 characters before, or only after it: `not_sure`, detail "does not name the person". A first-person bio "I teach physics at Example University." under the heading: `added`.
2. `test_a_mention_named_as_someone_else_stays_refused_near_the_persons_name`: "Jan Peeters\nEls Janssens\nProfessor of physics at Example University.": model name "Els Janssens" gives `not_sure`; model name "Jan Peeters" gives `added`. The docstring says the rule accepts this second case and the model's name decides, so a later tightening is not a regression.
3. `test_a_namesake_near_the_quote_does_not_confirm_the_person`: "Jan Peeters", 1,200 characters, then "Piet Peeters\n" and the title line: `not_sure`. With "J. Peeters\n" there instead: `added`.

In `tests/test_extract.py`, `PersonTest`, calling `extract.read_person(..., same=deepen.named_as)`:

4. `test_read_person_keeps_a_mention_whose_quote_lacks_its_name_only_with_the_name_rule`: "Jan (Johnny) Peeters is professor of physics." for "Jan Peeters", and "Jan Peeters teaches physics." for "Jan Karel Peeters", and "Faculty\nJan D'Hondt\nProfessor of physics." and "Ann Smith-Jones\nProfessor of physics." with the title line as quote, are kept with `span` on the model's quote; without `same` all four give today's "name not in quote" row. An empty quote and an absent quote give "quote not found"; "Prof. Peeters" gives "name has fewer than two words"; person "Peeters" gives "name not in quote".
5. `test_read_person_looks_for_the_name_up_to_name_reach_before_the_quote_in_its_own_chunk`: a name form starting exactly `NAME_REACH` before the quote is kept, one character further is dropped; the name only in the title line 200 characters before is kept; the name at the end of chunk 1 and the quote at the start of chunk 2 is dropped.
6. `test_read_person_scans_a_chunk_full_of_the_surname_in_under_half_a_second`: 5,900 characters of "Peeters " then "J. Peeters\n" and the title line: kept, under 0.5 s.

## Existing tests that change, approved by the lead

None. `test_read_person_sends_the_person_with_every_chunk_and_keeps_each_mention` calls without `same` and is unchanged. No existing test may change; if one does, stop and report.

## Hand check

`uv run python -m unittest` all green. Then, with `R=<scratch>/q5/lookup-quote` (if gone, stop and report) and a new scratch folder `H` outside the repo:

```sh
cp $R/classify.py $R/copy.sqlite3 $H/
```

In `$H/classify.py`, after `located, dropped = extract.check(src, 0, len(page), mn)` add `located = located or (extract.anchored(src, 0, len(page), mn, person, named_as) or (None, []))[0]`. From this worktree:

```sh
FN_LLM=replay FN_HTTP=replay uv run python $H/classify.py
uv run python -c "import json,sys; a={r['file']:r['class'] for r in json.load(open(sys.argv[1]))}; b={r['file']:r['class'] for r in json.load(open(sys.argv[2]))}; print(sorted((f[:8],a[f],b[f]) for f in a if a[f]!=b[f]))" $R/rows.json $H/rows.json
```

Expected: 62 "named, held fact", 7 "named, no held fact", 0 "name not in quote", 4 "another name form", 4 "nobody returned". The diff lists exactly the 12 readings of the research note, 11 to "named, held fact" and `1443356b` to "named, no held fact". It makes no network or model call.

## Not doing

`extract.check`'s behaviour, the prompts, `same_one`, `named_as`, the alias file, `NEAR_CHARS`, the lookup's detail words, `read_all` and the scout and researcher lanes. A trace row for a kept fallback mention. A surname-first entry ("Peeters, Jan") keeps today's refusal; follow-up with the formal-first-name case.
