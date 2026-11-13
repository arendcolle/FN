# Task Q-2: the local search covers every person FN holds, with related words

## Goal

The seed lane searches 5,429 of the 27,400 records with claims, because it skips web mentions, LinkedIn profiles and OpenAlex and ORCID records (`src/fn/lanes/seeds.py:23`). Three gold picks sit only in web mentions it skips (GS-32#1, #3, #4), and 9 of 19 held picks hold none of the question's words (`research/held-not-returned.md`). This task makes the local search reach web mentions and LinkedIn profiles always, OpenAlex and ORCID records only when research is asked, puts the role chips' words in the query, and runs a second pass with the related words whose hits rank below the first pass. Decisions R1, R2 and the search side of R3 in `design.md`. Owner: `lanes/seeds.py`. Needs Q-1.

## What to build, in `src/fn/lanes/seeds.py` only

- Remove `EXCLUDED`. Add `excluded(chips: Chips) -> tuple[SourceKind, ...]`: `()` when `parse.wants_research(chips)`, else `("record",)`. Use it in `run` (line 84) and in `near` (lines 59 and 66), which gains a `chips: Chips` parameter: `near(ctx, area, chips)`. Update the comment at line 83 to one line: "OpenAlex and ORCID records count only when the question asks for research."
- `fts_query(chips, aliases)` (line 31): the terms are the topic chips' content words, then the role chips' content words, then the institution tokens and aliases as today. No role chips gives today's query exactly.
- New `related_query(chips: Chips, first: str) -> str`: each `related` entry of every topic and role chip as one `phrase`, in chip order, ORed, without a term already in `first`. Empty for version-1 chips.
- `run`: pass 1 is today's loop over `match_claims(query, exclude)`. Pass 2 runs `match_claims(related, exclude)` when `related` is not empty and skips persons pass 1 found. Ranks run on from pass 1, and `MAX_HITS = 300` caps both passes together. A pass-2 hit has `score=-score` as pass 1, `matched_on=claim.value`, and its considered reason is `fts rank {rank}, related word, matched {claim.value!r}`; below the cap, `fts rank {rank}, related word, below the top 300`. The stage stays `fts`.
- `LaneOut.query` is `query` alone without related words, else `f"{query}; related: {related}"`.
- The place search (line 78) runs when there is no topic content word and no institution chip; role words alone no longer turn it off, so "Flemish founders in New York" gets role hits and then up to 20 people near New York, as today's place hits follow text hits.
- The log line (line 108) names both counts: `seed lane: %d people match %s, %d more on related words, %d place hits added near %s`.

## Which records each question searches

| Chips | Source kinds searched | Records with claims, frozen snapshot |
| --- | --- | --- |
| version 1 (stored before this round; research counts as asked) | all | 27,400 |
| version 2, no role chip | all | 27,400 |
| version 2, any role chip with research true | all | 27,400 |
| version 2, every role chip research false | all but `record` | 6,952 (5,429 seed, 1,498 web mention, 25 LinkedIn) |

## Worked examples (made-up names)

- Chips v2: role "founders" (research false, related `["founder", "co-founder", "ceo", "oprichter"]`), topic "nanotech". Query `"nanotech" OR "founders"`, related `"founder" OR "co-founder" OR "ceo" OR "oprichter"`. A seed person whose claim says "Founder & CEO" is a pass-2 hit ranked after every pass-1 hit. An OpenAlex record that says "nanotech" is not searched.
- Same chips, a web-mention person whose role claim says "nanotech entrepreneur": pass-1 hit.
- Chips v1 with topic "6G": the query is `"6g"` as today, and OpenAlex records, web mentions and LinkedIn profiles that say 6G are hits.
- 280 pass-1 hits and 50 pass-2 hits: 300 hits, the last 30 considered rows say "below the top 300".
- A person who matches in both passes is one hit at its pass-1 rank.

## Inputs a real run will meet

Chips with only roles and a place; role words that are all generic ("experts"), which add no term; a related entry with quotes, a hyphen or "AND" in it (`phrase` keeps it plain text); a related entry that equals a pass-1 term; no related words; a hidden (rejected) claim, which `match_claims` already leaves out; 1,498 mention records, many from one page; more than 300 hits in pass 1 alone, where pass 2 adds nothing.

## Tests (each must fail without the change), in `tests/test_seeds_lane.py`

- Every row of the table above: the same 6G claim from `seed_page`, `vendor_page`, `vendor_record` and `record` sources is a hit or not.
- `fts_query` with a role chip puts its words after the topic words and before the institution.
- `related_query` leaves out a term already in the first query, and is empty for v1 chips.
- Pass-2 hits rank after pass-1 hits, carry the related reason, and a person in both passes is one hit.
- The cap counts both passes (280 + 50 gives 300).
- Role chip plus a city runs the place search; a topic word plus a city still does not.

## Existing tests that change

`test_claims_from_lane_and_vendor_sources_are_no_seed_hit_and_page_claims_are` pins the old exclusion. Its edited chips are version 1, so every kind is now a hit; it changes to expect all five, and gains a version-2 case with one non-research role chip in which the `record` claim is no hit. Its docstring changes with it. No other existing test may change; if `SeedPlaceTest` or `SeedLaneSearchTest` fails, stop and report.

## Numbers to expect

- `research/held-not-returned.md`: today's words over every source kind put 3 of the 19 held picks in a first 300 (the three GS-32 web mentions). Hand-picked extra words put 11 or 12 there. That is an upper bound: the words were chosen after reading the records. The note names six picks no word reaches: GS-08#2, 16#3 and 16#4 need place or tie retrieval, and GS-18#4, 22#1 and 28#4 have records too thin to match.
- Reaching a lane's first 300 is not reaching the first 20 cards; that is Q-3 and Q-4.

## Hand check and measure

- `uv run python -m unittest` all green.
- Replay (stored chips, version 1): `fn-score run <snapshot> --mode replay --allow-degraded --out <scratch>`. Every search now searches all kinds, so the seed lane's hits change; the web lane is degraded after Q-1 until the paid re-read. Then `fn-score diff main.json branch.json --names <snapshot>` for GS-32: say whether the three mention picks are now seed-lane hits.
- Live-preferring (lead, paid): `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-gold <dev case ids>`, then `fn-score snapshot <dir>` from that var and `fn-score run <dir> --mode rescore`. Count held picks in the seed lane's first 300 (from the trace) against the 11-of-19 bound, and check held-out I10 per R2. The lead tunes the related-word lines of `prompts/parse.md` on the ten development questions only.

## Not doing

New index, per-person document or embedding. Place names as words (they add noise, `held-not-returned.md`). Seed list names from the gold questions, such as Fayat, as related words. Changes to `store.match_claims` or to the place cap of 20. Reading related words in evidence or rank: Q-3 makes a related word topic evidence and Q-4 orders it.
