# Task Q4: the seed lane searches only words that carry meaning

## Goal

The seed lane searches every word of every topic chip, joined by OR. For the topic "AI in health care" it also searches "in", and 54 of its 100 hits in a live search matched nothing else. Across 25 stored searches, 488 of 1,664 seed hits matched only a function word or a generic word such as "research", and in two searches all 100 did. This task makes the lane search only the words `parse.content_words` returns, and raises its cap so real hits are not pushed out. Background: [research/ranking.md](../research/ranking.md), findings 3 and 4.

## What to build (`src/fn/lanes/seeds.py`)

- `fts_query` takes the words of each topic chip from `parse.content_words(chip.text)`. Institution chips keep today's behaviour: every token, plus each alias as a whole phrase.
- When no topic word is left and the question has no institution chip, the lane returns nothing, with the reason it gives today for an empty query.
- `MAX_HITS` goes from 100 to 300. The ranking note measured that with 100, dropping a generic word from a climate question pushes a gold pick past the cap.
- The lane's log line and its `query` field show the query as sent.

## Changes to existing tests, approved

A test that pins the lane's query, its hit count or its order for a chip that holds a function word or a generic word follows the new behaviour: the word is gone from the query. A test that pins the cap of 100 follows the new cap. Say in your report which tests changed and how. No other existing test may change.

## Inputs a real run will meet

A topic of one function word; a topic of only generic words ("Belgian research"); a topic in Dutch or French; "AI" (kept); a chip with punctuation or quotes (still quoted as today); a question with only an institution chip; more than 300 matches.

## Tests

With made-up seed rows, in the seed lane tests:

- "AI in health care" queries ai, health and care, and a row that holds only "in" is no hit
- a topic of only generic words and no institution gives no query
- an institution chip still queries its tokens and aliases
- with 301 matching rows the lane keeps 300

Each new test must be seen failing without the change it covers.

## Hand check and gate

From this worktree and from the main checkout (read only): `fn-score run var/score/2026-11-12 --mode replay --out <scratch> --allow-degraded`, then `fn-score compare main.json branch.json` and `fn-score diff main.json branch.json`. Paste the output. Gates: exit 0 from compare, `seed_noise_top20` falls, and no gold pick that main keeps is lost (`gold_free_found` not lower). The count does not reach 0: the text index stems words, so "designers" finds "design", and the scorecard counts only exact word starts. Measured: 22 to 10, all 10 left are stem matches of real topic words. Report how the median of people kept moves.

## Not doing

- Searching the place of a question. A later task does that.
- Any change to the ranker.
- A stemmer or synonyms.
