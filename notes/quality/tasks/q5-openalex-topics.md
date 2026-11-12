# Task Q5: OpenAlex stores why a person matches the topic

## Goal

The OpenAlex lane finds an author because a work of theirs matched the topic of the question, and then stores only where the author works. So a card cannot say why the person fits, and the ranker cannot tell an author of a matching paper from a colleague at the same university: 68% of first-20 cards hold no claim that names the topic. This task stores the matching works as topic claims. It also runs the lane's batch calls at the same time. Background: [research/ranking.md](../research/ranking.md) finding 3, [research/speed.md](../research/speed.md) finding 4.

## What to build (`src/fn/lanes/openalex.py`)

### 1. Topic claims from matching works

`seen_authors` reads one page of works per topic chip (`select` already returns each work's `id`, `display_name` and `publication_year`). Do not change any request the lane sends: a replay serves stored answers by URL, and a changed URL finds none.

- Remember, per author, the works they were found on: id, title, year and the chip. Keep the first 3 per author, in the order seen.
- For each hit author with such works, store one claim per work: `kind="topic"`, the title as value, dated by the publication year as a record field. The source is a record source for the work, built with `record_source` like the lane's other sources: title "OpenAlex work <title>", fields `id`, `display_name`, `publication_year`. The quote is the title field.
- Add the claim ids to the hit's `claim_ids`, after the affiliation and location reasons.
- A work without a title or without a year gives a claim only when it has a title; without a year the claim is undated.
- An author found only through an institution list gets no topic claim.
- A second run of the same search writes no new claim.

### 2. Batch calls at the same time

`fetch` gets records in batches of 100 ids, one after another. Run the batches through `steps.fan_out` with 3 workers and merge the answers in batch order. A failed batch raises as it does today, after the calls that finished are logged. Three workers stay under OpenAlex's limit of 5 requests a second for filters with many ids.

## What must hold

- The requests of a replayed search are the same set as before, so `fn-score run --mode replay` on the frozen snapshot has no new degraded search.
- The order of the lane's hits does not change.
- The logged call order is the same on every run.

## Inputs a real run will meet

A topic page with no works; a work with 300 authors (each gets the claim); a work without a title; two chips that return the same work for one author (one claim); an author seen on five works (three claims); a very long title (stored whole; the page cuts it when it shows it); a batch that fails.

## Tests

With made-up names and titles, in the existing OpenAlex lane tests:

- an author on a topic work gets a topic claim with the title, the year and a quote that stands in the work's record source at its offsets
- five works give three claims; the same work under two chips gives one
- an institution-list author gets none
- the hit's `claim_ids` include the topic claims
- running the lane twice writes no new claim
- with a fake HTTP client that sleeps, six batches on three workers finish in about a third of the serial time, and the merged records and logged calls keep batch order

Each new test must be seen failing without the change it covers.

## Changes to existing tests, approved

Two tests in `tests/test_openalex.py` pin the claims of an author who is found on a topic work: `test_author_without_a_belgian_affiliation_is_kept_as_a_hit` and `test_every_fetched_author_is_a_hit_and_the_ranker_puts_the_belgian_one_first`. Such an author now has a topic claim, and it is one of the hit's reasons. In those two tests, the assertions on that author's `claim_ids` and on the count of that author's claims follow the new behaviour: the topic claim's id, read from the store, and one claim more. Change nothing else in them. No other existing test may change.

## Hand check and gate

From this worktree: `uv run fn-score run var/score/2026-11-12 --mode replay --out <a scratch folder> --allow-degraded`, and the same from the main checkout (read only), then `uv run fn-score compare main.json branch.json`. Expected: exit 0, `topic` rises, the gold counts stay, the only degraded search is the one that is degraded on main too. Accepted after measuring: the median of people kept moves by half a person and one gold pick moves from 144 to 152, because the new topic claims enter the text index whose statistics the seed lane's ranking uses. Paste both aggregates and, with SQL on your throwaway copy, the number of topic claims on OpenAlex records after one replayed search.

## Not doing

- Any change to the ranker. A later task reads these claims.
- Narrowing the lane to authors in the US, or changing its queries.
- How the profile words such a claim. The page task does that.
- Running the lanes side by side.
