# Panel 1 brief: who comes back for a question, and in what order?

## What the owner asked

After the first quality round the owner said the results lean too much on researchers and on OpenAlex and ORCID. Business people and plain professionals are an untapped group. He wants better and worse matches in one list, so a useful list still comes back when nobody meets every wish: first someone with the topic and a tie to Flanders, then, when that person does not exist, a topic expert without a tie. His example: a speaker on the US midterms, ideally connected to Flanders.

## What the research found

Read these notes in `notes/quality2/research/` before you vote. Each number below comes from one of them.

- `gold-reality.md`: of 99 real picks, 39 are business people, 25 researchers, 12 chamber or community staff, 11 creatives, 8 government. No business pick reaches a first 20 on merit. First-20 cards read 69% academic and 13% business. 44% of first-20 cards come only from OpenAlex, and no gold pick in a first 20 comes from OpenAlex alone. 10 of 28 questions ask for business people, 5 for researchers.
- `held-not-returned.md`: 19 picks FN never returns are stored in its database. 9 fail because the record holds none of the question's words ("Founder & CEO" for "entrepreneurs"). 5 sit in web mentions or OpenAlex records, which the local search skips: it searches 5,429 of 27,400 records. 3 fail because the parser made no chip from the kind of person asked for. 2 fall below a cap. Hand-picked extra words put 11 or 12 of the 19 in the first 300 hits, an upper bound. A business record has a median of 2 claims and a place in 19% of cases.
- `tiers.md`: FN measures topic, tie and place. It has no field for the kind of person. A strict top tier is empty in 17 of 27 stored searches. Only 1 stored person has the topic and the place without a tie, because every lane asks for Belgian people. The note proposes a six-tier ladder under three headings, a graded tie, and a parse step that marks each wish as a must or as nice to have.
- `people-sources.md`: open lists of non-researchers are small, 100 to 350 people in total. The degree itself is almost never in an open record.
- `benchmark.md`: 14 new questions that do not ask for researchers, and the rubric three judges score with. The number to climb is how many people in the first 10 an organizer could invite.

How a search works today: `src/fn/search.py` (steps), `src/fn/parse.py` and `src/fn/prompts/parse.md` (chips), `src/fn/lanes/seeds.py`, `openalex.py`, `web.py` (who is found), `src/fn/evidence.py` (topic, tie, place per card), `src/fn/rank.py` (groups, bands, cuts). The decisions of the first round are in `notes/quality/design.md`.

Limits that hold for every option: one local server and one SQLite file, the small model through the `claude -p` command line, no new paid service, no new dependency without the owner's consent, the OpenAlex budget of about 1,000 calls a day, and no reading of LinkedIn.

## The decisions

The options under each decision are listed in the panel's prompt. Vote on each one. Where two decisions depend on each other, say so in your reason.

- **R1** Which stored people the local search covers.
- **R2** How the question's vocabulary reaches the records.
- **R3** How the kind of person asked for is handled.
- **R4** How better and worse matches are ordered and shown.
- **R5** What counts as a tie to Flanders or Belgium, and how strong.
- **R6** Where topic experts without a tie come from.
- **R7** What happens to the OpenAlex lane and its share of the first 20.
- **R8** Whether a word inside an organization's name counts as a topic match.
- **R9** What to do about thin records.
