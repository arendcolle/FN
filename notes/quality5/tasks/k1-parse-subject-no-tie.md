# K1: Belgium as the subject of a question is no tie

## Goal

The parse step sometimes read "Who in Chicago could talk about food and agriculture trade with Belgium?" with "with Belgium" as a required tie. A required tie cuts every person without a Belgian link (`rank.no_tie`), so the importers and traders the question asks for left the list. Main's prompt named one case without a tie: Flanders or Belgium as the venue or the host.

## What changed

One line of `src/fn/prompts/parse.md`, the rule for the `tie` chip:

- the tie is the words that say the people themselves have a connection to Flanders or Belgium;
- a named university or company is an institution chip and no tie;
- no tie when Flanders or Belgium is the venue or host, the audience, or the subject the people know about.

No code changed. `parse.py` already drops country words when it matches a topic chip, so "trade with Belgium" matches as "trade".

## Measured

Live readings of the parse step, main against the branch. A reading is right when the tie chip is absent, required or wished as the question means it.

| Questions | Readings | Main | Branch |
| --- | --- | --- | --- |
| Belgium as subject, venue or audience; the first wording was tuned on these | 10 questions, 8 each | 76 of 80 | 80 of 80 |
| The same kind, never used to tune the wording | 8 questions, 5 each | 34 of 40 | 40 of 40 |
| A tie that describes the people | 10 questions, 10 each | 94 of 100 | 99 of 100 |
| The 20 benchmark questions and 12 probes | 32 questions, 3 each | 93 of 96 | 94 of 96 |

The Dutch question "Wie in New York kent de Vlaamse startup-scene …" was read with a required tie in 5 of 5 readings on main and in none on the branch. "Who studied in Ghent and now works on trade policy in Washington?" was read with a required tie in 4 of 10 readings on main, where the other six made "Ghent" an institution, and in 9 of 10 on the branch.

A reviewer found that the first wording took three of its four examples from the test questions. The examples were replaced by phrases no test question holds, and the held-out row above was added.

## Effect on recorded answers

Recorded parse answers are keyed by the prompt text, so answers recorded with the old text no longer replay. A stored search keeps its stored chips. The tests rekey their two parse fixtures and pass unchanged.

## Not doing

A rule in code for the tie, a change to the `need` rule, and the two phrasings that stay ambiguous on main and on the branch ("Belgian trade experts in Chicago" reads as a required tie in every reading).
