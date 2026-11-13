# Task Q-1: the two prompts and their contracts

## Goal

FN cannot tell what kind of person a question asks for, whether the tie to Flanders is a must, or which words a record uses instead of the question's. Nine of 19 gold picks FN holds but never returns fail on vocabulary alone ("Founder & CEO" for "entrepreneurs"), and 3 more because parse made no chip from the kind of person (`research/held-not-returned.md`). The page reader cannot say "Belgian chocolatier" is a tie, nor what a person works on. This task changes both prompts and their contracts at once, because any prompt or schema change makes every recorded model answer miss once (`src/fn/llm.py:65-67`, the fixture key hashes the system prompt, the user turn, the schema and the model). Nothing reads the new fields yet, so stored searches rank as before. The parse call also writes the web queries (W2), so the parse prompt and its schema change once. Decisions R2, R3, R5, W2 and the lead's rulings in `design.md`.

## What to build

### `src/fn/contracts.py`

- `Need = Literal["must", "nice"]`.
- `Chip` (line 103) gains `need: Need = "must"`, `related: list[str] = []`, `research: bool | None = None`.
- `Place` (line 110) gains `need: Need = "nice"`. A stored place never cut anyone, so its legacy meaning is "nice".
- `Chips` (line 117) gains `roles: list[Chip] = []`, `tie: Chip | None = None`, `version: int = 1`, `queries: list[WebQuery] = []`. Above it, `class WebQuery(Model): text: str; lang: Literal["en", "nl"]`.
- `Relation` (line 26) gains `"origin"`.
- New `PageTopic(Model)`: `topic: str`, `quote: str`. `PageMention` (line 331) gains `topics: list[PageTopic] = []`. `Located` (line 343) gains `topics: list[tuple[str, Span]] = []`.
- Leave `CONTRACTS_VERSION` at "2": the fields are additive and old payloads still validate, and a bump hides every old step in the trace (`src/fn/web/debug.py:256`).

### `src/fn/prompts/parse.md`

Keep the text and add these fields after `ask`, word for word:

```
- roles: the kinds of person the question asks for, such as "founders", "business leaders" or "faculty". One chip per kind. Each role chip has research: true when the kind is an academic research job (professor, lecturer, postdoc, PhD student, researcher or scientist at a university or public research institute), else false.
- tie: the words that ask for a connection to Flanders or Belgium, such as "Flemish" or "ideally connected to Flanders", as one chip. Use null when the question asks for no such connection, or names Flanders or Belgium only as the venue or the host.
- need, on every chip and on place: "must" or "nice". A topic, an institution and a role are "must". A tie is "must" when it describes the people asked for ("Flemish founders", "Which Belgian faculty") and "nice" with "ideally", "preferably", "if possible" or similar words. A place is "must" only when the question says the people must be based or live there, else "nice". When unsure, use "nice".
- related, on every topic and role chip: up to 6 words or short phrases that a record about such a person would use instead of the chip's own words: synonyms, the full form of an abbreviation, sector words, job titles, and the Dutch and French forms. Lowercase. Never the chip's own words, and never general words such as "research", "expert", "Belgian" or "people". Institutions and the tie get an empty list.
- queries: up to 5 web search queries that would find pages naming such people, such as interviews, speaker lists, board pages or alumni pages. Write at least one in English and at least one in Dutch. Each names the kind of person or the topic, and the place when the question gives one. Each keeps a country word such as "Belgian", "Flemish", "Belgische" or "Vlaamse". At most one may be limited to Belgian newspaper or university sites with site:, such as "site:tijd.be". Each has text and lang, "en" or "nl". Never a person's name.
```

The span rules apply to role and tie chips too. Add "research is null on every chip but a role chip."

### `src/fn/parse.py`

- `MAX_RELATED = 6` and `RELATED_SKIP = GENERIC_WORDS | {name_key(w) for w in "specialist specialists professional professionals individual individuals staff member members specialiste specialistes professionnel professionnels deskundige deskundigen vakman".split()}`.
- `clean_related(chip: Chip) -> list[str]`: each entry on one line with single spaces, kept when it has a content word (`content_words`) not in `RELATED_SKIP`, when its `name_key` differs from the chip text's and from every kept entry's, and when its content words are not all among the chip's own; the first `MAX_RELATED`.
- `_all_chips` (line 69) also returns `chips.roles` and `chips.tie`, so `check_spans` checks and moves their spans; `fix` in `check_spans` covers `roles` and `tie`.
- `run` (line 113): after the edited-origin check, set `related=clean_related(c)` on topics and roles, `related=[]` on institutions and the tie, `research=None` on all but roles, `research=bool(c.research)` on roles, and `version=2` on the chips. A model answer's own `version` is ignored. `queries` are kept as the model wrote them; `websearch.queries` (Q-6a) checks them.
- `tie_must(chips: Chips) -> bool`: false for version 1 (lead's ruling on legacy chips: nobody is cut for lacking a tie), else true when `chips.tie` is set and its `need` is "must".
- `asks_researchers(chips: Chips) -> bool`: true for version 1 (research counts as asked), else true when any role chip has `research` true.
- `wants_research(chips: Chips) -> bool`: `asks_researchers(chips)` or no role chip. This is the owner row "whether a question asks for research expertise" in `design.md`.

### `src/fn/prompts/extract.md` and `src/fn/extract.py`

- In the relation list (line 16) add `"origin" (the country or region the text says the person is from, such as "Belgian" in "Belgian chocolatier"; org is that word as the quote writes it)`.
- After `relations`, add: `- topics: one entry per subject the text says the person works on, such as "wireless networks" in "professor of wireless networks". Each has topic, copied as the text writes it, and quote, the passage that states it, copied character for character, from the person's own quote or the lines right after it. Never a job title, an organisation or a place. Use an empty list when the text gives none.` Add "a topic" to the "Never invent" rule.
- `PLACES` (line 30) gains `"origin"`, so `drafts` gives an origin a location claim with relation `origin` and no coordinates.
- `check` (line 87): a topic is kept when its quote lies in the chunk within `NEAR_CHARS` of the mention quote's start (as relations, line 109) and `words(topic)` stands in `words(quote)`. Drop rows, stage `topic`: `topic quote not near the mention: {topic!r}, quote {quote[:200]!r}`, `topic not in quote: {topic!r}, quote {found[:200]!r}`, `same topic as before: {topic!r}` (same `name_key` and quote start).
- `drafts` (line 173): after the relation claims, one `ClaimDraft(kind="topic", value=normalize(topic), ...)` per kept topic, with its own quote and offsets, undated.

### Readers that must treat an origin like a birthplace

- `store.unlocated_places` (`src/fn/store.py:416`): `COALESCE(relation, '') NOT IN ('born_in', 'origin')`.
- `evidence.places` (`src/fn/evidence.py:86`): an origin claim is never a place.
- `present.place_of` (`src/fn/present.py:133`) leaves out origin claims; `present.what_of` (line 170) reads an origin claim as `Origin: {value}`, before its location branch. The value is the word as the quote writes it ("Belgian"), so the label reads right for an adjective or a country. UI-2 and UI-4 keep this wording.

### `src/fn/web/debug.py` `chips_from_form` (line 320)

Edited chips keep the source's `roles`, `tie` and `version`; a kept topic text keeps its `need` and `related`. A form without a source gives version 1. Edited chips get `queries=[]`, because the model's queries describe the old chips.

## Inputs a real run will meet

An answer with no roles, no tie and no related words; a role span off by two characters; the same role twice ("founders and founders"); 12 related entries; related entries of only generic words; an entry equal to the chip ("AI" for "AI"); related on an institution or the tie; Dutch and French entries with accents ("oprichter", "fondateur", "chercheur"); a role "researchers" with research true; a tie "ideally connected to Flanders"; chips stored before this round; a rerun from the debug form of a version-2 search; an origin "American"; a topic the quote does not hold; a topic 2,000 characters away; the same topic twice in one passage; a page with no topics; an answer with no queries; 7 queries; a query with an empty text.

## Tests (each must fail without the change)

- `tests/test_contracts.py`: chips JSON stored before this round (no roles, tie, version, need) loads as version 1, `need` "must" on chips, "nice" on the place, `related` empty, `queries == []`.
- `tests/test_parse.py`: a StubLLM answer with a role and a tie gives version 2 with checked spans; a StubLLM answer with two queries keeps both, with their `lang`; a role span 5 off raises `SpanError`; `clean_related` on `["AI", "research", "artificial intelligence", "machine learning", "ML", "deep learning", "neural networks", "robotics", "computer vision"]` for chip "AI" gives `["artificial intelligence", "machine learning", "ML", "deep learning", "neural networks", "robotics"]`; related on an institution comes back empty; `research` is None on a topic even when the answer sets it.
- `tie_must`, `asks_researchers`, `wants_research` on: version 1 (false, true, true, also with a tie chip of need "must" in the JSON); version 2 with no roles; one non-research role (`wants_research` false); a research and a non-research role (`asks_researchers` true); tie need "nice" (`tie_must` false); tie need "must" (true); no tie chip (false).
- `tests/test_extract.py`: "Belgian chocolatier Ann Example" gives a location claim, relation origin, no coordinates, which `locate_stored` leaves; a kept topic gives a topic claim at its offsets; each drop row above.
- `tests/test_present.py`: an origin claim reads `Origin: Belgian` and never becomes the place.
- `tests/test_web.py` or the debug tests: `chips_from_form` keeps roles, tie and version 2.

## Existing tests that change

`tests/test_parse.py` `test_recorded_english_and_dutch_questions_parse_with_checked_spans`: the two recorded answers no longer match the new key. The test copies their `result` into a temp folder under the key `FixtureLLM` now computes (`llm.prompt_sha` over `llm.system_prompt("parse")`, `llm.user_turn`, `llm.schema_json(Chips)` and `llm.MODEL`) and keeps its assertions, plus version 2. It proves old answers still validate; the lead records real answers later. No other existing test may change. `tests/test_linkedin.py` `gs02_chips` keeps reading the old fixture file, so the old fixtures stay.

## What old data does

- Stored chips load as version 1. Later tasks read version 1 through these predicates only: the tie is not a must, so nobody is cut for lacking one; research counts as asked; and the `web_topic` lane (Q-5) does not run, so a stored search keeps its people and replays without new calls. The ranker lets nobody back in from the old cut for version 1 (Q-4), so a stored search gains nobody either. Stored chips have no queries, and version 1 keeps today's web queries (Q-6a).
- Old parse and extract answers in `tests/fixtures/llm`, `var/llm` and snapshots are never served again. `fn-score run --mode replay` skips parse (stored chips) but every extract chunk misses, so the web lane reads nobody and the run is degraded until the lead's paid re-read. `--mode rerank` and `--mode rescore` are unchanged.

## Merge order

Q-1 merges first of all tasks in both tracks, before any pages task that edits `present.py` (UI-1 to UI-5). The order is in `plan-quality.md`, "Order across both tracks".

## Hand check

`uv run python -m unittest` all green. `fn-score run <snapshot> --mode rerank --out <scratch>` gives the same aggregate as main. Then the lead (paid): `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-gold <two dev case ids>` and reads the stored chips: roles, tie with need, at most 6 related words per chip.

## Not doing

Any reader of roles, tie, need, related or topic claims (Q-2 to Q-5), or of queries (Q-6a). Rewording the existing prompt lines. Recording fixtures. A `CONTRACTS_VERSION` bump.
