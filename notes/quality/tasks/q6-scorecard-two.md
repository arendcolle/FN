# Task Q6: scorecard round two

## Goal

The next tasks change who is one person, which words the seed lane searches and how people are ordered. Each needs a number that tells whether it helped, and three pieces of shared code that must have one owner before those tasks start. This task adds both. Nothing in a search result changes. Background: [research/scorecard.md](../research/scorecard.md), [research/ranking.md](../research/ranking.md), the first plan review's findings R1, R6, R12 and R15 in [progress.md](../progress.md).

## What to build

### 1. One owner for the words of a question that carry meaning (`src/fn/parse.py`)

`parse.content_words(text: str) -> list[str]`: the words of a text, folded like `contracts.name_key` folds a name, without function words and without generic words, in order, once each.

- Function words in English, Dutch and French: articles, prepositions, conjunctions, pronouns, question words and auxiliary verbs. Short lists, about 60 words a language.
- Generic words, from the ranking note: research, researcher, science, scientist, university, expert, experts, people, person, tech, technology, us, usa, belgian, belgium, flemish, flanders. A question is about people with a Belgian tie, so these words match almost every record.
- "AI" stays: a two-letter word is kept unless it is on a list.
- `score.py` drops its own `STOP` set and its topic metric calls `content_words`.

### 2. One owner for running the steps after the lanes on a stored search (`src/fn/search.py`)

`search.refinish(ctx, search)`: read the stored outputs of the search's lane steps and its stored chips, and call `finish`. `score.py`'s rerank mode calls it and loses its own loader. A search without stored lane outputs raises `ValueError` with its id.

### 3. A frozen name matcher for gold picks (`src/fn/gold.py`)

`gold.match` compares names with `contracts.group_key(name_key(...))` today. A later task changes how FN compares names, and the gold counts must not move with it. Give `gold.py` its own `pick_key(name)` with today's behaviour, used for both sides of the comparison in `match`, with a one-line comment that it is frozen on purpose. `score.py`'s doubles metric (`likely_same`) uses `gold.pick_key` too, so nothing that measures depends on `contracts.group_key`. No behaviour change today: the three modes must give the same gold counts and the same doubles counts as before this task.

### 4. Gold picks a seed list names by construction (`src/fn/score.py`)

Three seed lists to come are records the gold set was built from. A pick they name is found by construction, and it must not count as better search.

- A matched pick is by construction when a record on its card has a seed source (`sources.kind == "seed_page"`) whose site equals the site of the gold case's `source` or of any URL in the pick's `sources`. The site of a URL is its host without `www.`. A Wayback URL (`web.archive.org/web/<stamp>/<url>`, with or without the `id_` mark) counts as the URL it wraps.
- New metrics per search and summed: `gold_free_at_10`, `gold_free_at_20`, `gold_free_at_50`, `gold_free_found` (picks that are not by construction), and `gold_by_construction` (their count). Each entry of `gold_picks` gains `"by_construction": true|false`.
- The gates switch from `gold_at_20` and `gold_found` to `gold_free_at_20` and `gold_free_found`. The old four metrics stay in the output.

### 5. A labelled pair file and two metrics (`src/fn/score.py`)

`data/gold/identity-pairs.jsonl` (the folder is ignored by git; the file may be absent): one JSON object per line with `a` and `b` (person record ids), `label` (`same`, `different` or `unclear`) and `note`. This task defines and reads the format. A later task fills the file.

- One function in `score.py` says which records a kept candidate's card reads: today `hit_person_ids`, else the first of `person_ids`. The later identity task replaces its body with one call. Every metric that needs the card's records uses it.
- `pairs_wrong`: labelled-different pairs whose two records are on one kept card of the search. Summed over searches.
- `pairs_split`: labelled-same pairs whose records are on two different kept cards, both within the first 50. Summed.
- Without the file both metrics are left out. `unclear` pairs count nowhere. A pair id the snapshot does not hold is skipped.
- Gate: `pairs_wrong` must not rise.

### 6. Seed-noise slots (`src/fn/score.py`)

`seed_noise_top20`: first-20 cards that only the seed lane found and where no claim of the card's records holds a content word of any topic chip and the question has no institution chip. Summed over searches. Reported, not gated.

### 7. The first-20 diff (`fn-score diff`)

- Each search in `scorecard.json` gains `top20`: a list of `{"id": <first 12 characters of the candidate's person id>, "rank": n, "lanes": [...], "parts": [feature names of its score parts]}`.
- `fn-score diff A.json B.json [--names SNAPSHOT_DIR]` prints, per search that both files hold, the people who entered and who left the first 20, with their rank in A and in B, lanes and parts. With `--names` it looks each id up in the snapshot database and prints the name beside it. Names go to the terminal only, never into a file.

## Inputs a real run will meet

A text that is only function words (empty list); a Dutch or French question; a gold case without `source`; a pick without `sources`; a Wayback URL with and without `id_`; a `www.` host; a pair file with an id that no longer exists, with a malformed line (the command stops and names the line), and an empty file; a search with fewer than 20 kept people; `diff` on two files with different searches.

## Tests

With made-up names:

- `content_words`: "AI in health care" gives ai, health, care; "research" alone gives nothing; one Dutch and one French sentence lose their function words; a word listed twice comes back once
- `refinish` on a stored search gives the same candidates as the stored ones, and a search without lane outputs raises
- `pick_key` equals `group_key(name_key(name))` for ten made-up names, among them one with a middle initial and one with an accent
- a pick on a card with a seed source from the case's site is by construction; the same pick with a seed source from another site is not; a Wayback URL and a `www.` URL match
- `pairs_wrong` and `pairs_split` on a hand-built database, each seen failing when the pair logic is disabled
- `seed_noise_top20` counts a seed-only card with no topic word and skips one with a topic word
- `diff` prints who entered and left, and prints no name without `--names`
- the three modes on the test database give the same gold counts before and after this task

## Hand check

Run rescore, rerank and replay on the frozen snapshot `var/score/2026-11-12` (read only; the command copies it) with `--allow-degraded`, and paste the aggregates. Expected: `gold_at_10`, `_20`, `_50` and `gold_found` as on main (2 or 3, 3, 4, 12), `gold_free_*` equal to them (no new seed list exists yet, but check which picks today's seed lists name by construction and report the count), `seed_noise_top20` near the ranking note's 18.

## Not doing

- Metrics that need evidence about a person's place or the cuts. The ranking task adds them.
- Filling the pair file.
- Any change to what a search returns.
