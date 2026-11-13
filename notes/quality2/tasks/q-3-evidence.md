# Task Q-3: evidence grades the tie, reads the role, takes related words, and stops org names and page titles from matching a topic

## Goal

`evidence.tie` counts any of five kinds as a tie with no grade (`src/fn/evidence.py:113-131`). Belgian text alone is the only tie for 309 kept people and lifts 81 into the top group, often from a city word in a paper title; 785 of 1,737 Wikidata people are tied only through a Belgian employer country, a US airline chief among them (`research/tiers.md`, `research/people-sources.md`). `evidence.topic` gives "health" in an institute's name a full topic match (lines 95-103). Nothing reads the kind of person asked for, though 10 of 28 gold questions ask for business people. This task adds the tie grade, the role fit, related words as topic evidence and the two topic rules. Decisions R5, R8 and the role fit of R3, and the lead's rulings on origin, topic claims, which lists give a strong tie, and related words. Owner: `evidence.py`. Needs Q-1. Ranking still uses `rank.group`; Q-4 reads the new fields.

## What to build

### `src/fn/contracts.py`

- `TieGrade = Literal["strong", "medium", "weak", "none"]` and `RoleFit = Literal["met", "fails", "unknown"]`, next to `CutReason` (line 52). Q-4's `CardFit` uses both, so they live here and `evidence.py` imports them.

### `src/fn/evidence.py`

- `Tie` gains `grade: TieGrade = "none"`. `Evidence` gains `role: Role = field(default_factory=Role)` with `@dataclass(frozen=True) class Role: fit: RoleFit = "unknown"; claim_ids: tuple[str, ...] = ()`. `Topic` gains `related: bool = False`.
- `STRONG_LISTS = frozenset({"baef", "francqui", "fayat", "consuls", "climate"})`, the list names of `seedload.SPECS` (`src/fn/seedload.py:40-50`). Every other list gives a medium tie: `kvab` (the academy), `chambers`, `missions`, `wikidata`, and the three lists of decision W4 (BelCham board, the embassy's advisors, nonprofit officers) whatever keys their task gives them.
- `card_of(identifiers: dict[str, list[Identifier]], records: list[str]) -> dict[str, frozenset[str]]`: each record's identifier schemes, plus `seed:<list>` for each seed identifier, the list being the part of its value before the first `|` (row keys such as `kvab|...`, `scripts/seeds/common.py:60`, stored as the seed identifier, `src/fn/seedload.py:137`). `rank.run` (`src/fn/rank.py:236`) uses it in place of its inline dict. `score.py` keeps its own dict: it reads only the place.
- `tie(card, claims, facts, found) -> Tie` drops the `inst` parameter and the `institution` kind. Kinds, in this order:

| Kind | Claims | Grade it gives |
| --- | --- | --- |
| `seed_list` | as today (line 122); a seed record with no claim still counts | strong when a seed record on the card is on a list in `STRONG_LISTS`, or has no `seed:` marker; else medium |
| `belgian_degree` | `studied_at` at a Belgian org (`orgs.belgian_claims`), or whose value matches `BELGIAN_TEXT` | strong |
| `born_in_belgium` | `born_in` whose folded value matches `BELGIAN_TEXT` | strong |
| `belgian_origin` | relation `origin` whose folded value matches `BELGIAN_TEXT` | strong |
| `belgian_org` | as today, `rank.counted` | strong when `years >= 3` and `last >= 2016`, else medium |
| `belgian_place` | a stated place with country BE, as today | medium |
| `belgian_text` | as today | weak |

  `grade` is the best grade of the kinds present, `none` without any. A seed record without a `seed:` marker counts as strong, so cards built by older code (and `score.py`) read as before. `claim_ids` is strongest first: the claims of strong kinds, then medium, then weak, kind order within a grade, each id once. Q-4 stores this order as `CardFit.tie_claim_ids` and the card names the first. `years` and `last` are unchanged, so the cuts in `rank.cut_reason` do not move.
- `topic(claims, chips: list[Chip], card) -> Topic` takes the topic chips, not their texts. `words` and `claim_ids` as today over `f"{value} {quote}"`, from the chips' own words. `match` reads only these texts:
  - an `affiliation` claim: its quote with its value (the org name) taken out, folded with `name_key`. Its words still count in `words` (R8).
  - a claim of a record whose schemes are exactly `{"mention"}` (a web person): a `topic` claim's value and quote, and a `role` claim's value when its folded value stands in its folded quote. Any other claim of that record adds words only. This drops the page title that `extract.drafts` puts in place of a missing role (`src/fn/extract.py:184`).
  - every other claim: as today.
- Related words (lead's ruling): when no chip matches on its own words, `match` is true when one of those texts holds every word of one `related` entry of a topic chip, `parse.topic_match(chip.related, texts)`, and then `related` is true. The matching claims join `claim_ids`; a related entry's words do not join `words`. An own-word match always wins, so `related` is false whenever an own-word match exists. Version-1 chips have no related words.
- `role(claims, card, question) -> Role`, from `question.chips.roles`:
  - no role chip: `unknown`.
  - `met`: one role claim's value (kind `role`) holds every chip word of a role chip or of one of its `related` entries: `parse.topic_match([chip.text, *chip.related], values)` per chip. The claim ids are those role claims. A role claim of a record whose schemes are exactly `{"mention"}` counts only when its folded value stands in its folded quote, as in the topic rule, since `extract.drafts` stores the page title as the role when the mention has none.
  - `fails`, only when every role chip has `research` false and none is met: a role claim reads as an academic research job (below), or the card has no role claim and `only_openalex` holds (bibliographic sources only).
  - else `unknown`. A person without a role claim and with any other source is never `fails`.
- An academic research job, folded and matched with `parse.words_in`, so a word of four letters or more matches a word start:
  - always: professor, hoogleraar, docent, lecturer, postdoc, "phd student", "phd candidate", "phd researcher", "doctoral student", "doctoral candidate", "doctoral researcher", doctoraatsstudent, doctorandus, doctorant, professeur, "maitre de conferences", "charge de cours", "research fellow".
  - only with a university word in the same value: researcher, scientist, "research scientist", onderzoeker, wetenschapper, chercheur, scientifique. University words: university, universiteit, universite, universidad, college, hogeschool, polytechnic, "institute of technology", "school of medicine", "medical school".
  - A scientist at a company is not a researcher (`research/benchmark.md`, Researcher). Leave out "prof": it matches "professional". Leave out a bare "phd" or "doctoral": a business title may carry the degree.
- `of` (line 149) keeps its signature and positional order (a test wraps it, `tests/test_rank.py:394`), passes `question.chips.topics` to `topic` and fills `role`.

## Worked examples, as tests in `tests/test_evidence.py` (made-up names)

| Card and claims | Expected |
| --- | --- |
| seed record `baef|ann-example`, no claim | `seed_list`, strong |
| seed record `kvab|ann-example`, no claim / `chambers|...` / `belcham|...` (a list key FN does not know) | `seed_list`, medium each |
| seed record `wikidata|ann-example`, `works_at` a Belgian org 2020 only | `seed_list` and `belgian_org`, medium |
| seed record `wikidata|ann-example`, `studied_at` KU Leuven | strong through `belgian_degree` |
| `studied_at` KU Leuven 1995 | `belgian_degree` and `belgian_org`, strong |
| `born_in` "Ghent, Belgium" | `born_in_belgium`, strong |
| origin "Belgian" / origin "American" | strong / no kind |
| `worked_at` a Belgian org 2014 to 2019 / 2001 to 2005 | strong / medium |
| `lives_in` Brussels, located | `belgian_place`, medium |
| "Grew up in Ghent" only | weak |
| "Grew up in Ghent" (c1) and `born_in` "Ghent, Belgium" (c2) | `claim_ids` starts with c2 |
| chip "health"; affiliation "Institute for Health Policy", quote "Works at the Institute for Health Policy" | words ("health",), no match |
| chip "health"; topic claim "health economics" | match, `related` false |
| chip "AI" with related ["machine learning"]; claim "Leads machine learning at Example Corp" | match, `related` true, words () |
| same chip; claims "AI lead" and "machine learning" | match, `related` false |
| same chip, version-1 chips (no related); claim "machine learning" | no match |
| mention record, chip "AI"; role value "AI Summit speakers" (title), quote "Ann Example, CEO of Acme" | words ("ai",), no match |
| mention record, chip "wireless networks"; role "professor of wireless networks" inside its quote | match |
| roles ["founders", research false, related ["co-founder", "ceo"]]; role "Co-founder and CEO" | met |
| same roles; "Associate professor of marketing" / OpenAlex-only, no role / seed record, no role | fails / fails / unknown |
| same roles; "Research scientist at Example Corp" / "Research scientist, Ghent University" | unknown / fails |
| roles founders (false) and faculty (true); "Professor of chemistry" | unknown |
| roles ["business leaders", research false]; "Chief Scientific Officer, PhD at Example Bio" | unknown |
| roles ["founders", research false]; mention record, role value "Founders summit speakers" (title), quote "Ann Example, CTO" | unknown |

## Inputs a real run will meet

A card mixing a mention and a seed record (the mention rule holds only for the mention record's claims); a role claim equal to the page title; an org name holding every topic word; a related entry inside an org name (no match, as for own words); a claim of a record not on the card (ignored, as today); no claims; a question without role chips (role unknown for all); version-1 chips (no roles, no related words); a Wikidata row with a Belgian degree (strong through the degree); a seed record of a list name FN does not know (medium).

## Existing tests that change

`tests/test_evidence.py` `BelgianTest.test_each_kind_of_tie_names_its_claims_and_the_years_count_as_the_ranker_counts_them`: `institution` leaves the kinds and the `studied_at` Leuven claim adds `belgian_degree`. Expected kinds become `{"seed_list": ("seed",), "belgian_degree": ("org",), "belgian_org": ("org",), "belgian_text": ("text",), "belgian_place": ("place",)}`, plus `grade == "strong"`; its docstring loses "and institution". No other existing test may change. `tests/test_rank.py` builds `Tie` without a grade and must stay green, since `rank.group` still reads `kinds`.

## What it does to results

`rank.group` (line 140) reads `topic.match` and `belgian.kinds`, so group 0 changes: web people matched only by a page title and people matched only by an org name leave it, and people matched through a related word join it. People whose only tie was the question's institution also leave it, since `institution` leaves the kinds. Cuts do not move. Measure with `fn-score run <snapshot> --mode rerank` on main and the branch, then `fn-score compare`: no gold pick that main keeps may be cut, and `gold_free_at_20` must not fall. If it does, report which rule moved it; do not tune a rule. Stored chips are version 1, so related words change nothing in rerank. Stored web people have no topic claims until the paid re-read (Q-1), so the mention rule costs them matches in rerank until then.

## Hand check

`uv run python -m unittest` all green, then the rerank compare above, and three cards from `fn-score diff --names` described without names.

## Not doing

Tiers, cuts and the order (Q-4). A grade from the length of a degree. Reading the role of OpenAlex affiliations. Changes to `score.py`. Seed list keys for the W4 lists (their task names them; they are medium here by default).
