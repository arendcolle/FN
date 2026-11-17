# Task o1: a stored index of researchers in the US with a Belgian affiliation

## Goal

For "Belgian scientists in the Washington D.C. area" a web researcher found 0 to 2 people; OpenAlex lists 452 at the NIH (D2). On 17 November 2026 the filter `last_known_institutions.country_code:US,affiliations.institution.country_code:BE` returns 31,921 authors; FN holds 741. A new job, `fn-index`, stores every one as the OpenAlex lane stores an author, plus its main topics and years with works. With a required place, the stored-lists lane starts from the people inside the area (D3).

## OpenAlex facts relied on (read 17 November 2026)

- Cursor paging: `cursor=*`, then `meta.next_cursor`; null with empty `results` ends it. Past page one it needs a key (else 401). `per_page` 1 to 100. https://help.openalex.org/how-to-use-the-api/get-lists-of-entities/paging
- `select` takes root-level fields, on list calls too. https://help.openalex.org/how-to-use-the-api/get-single-entities/select-fields
- Author: `topics` (ranked, `display_name`, `count`), `works_count`, `counts_by_year` (unsorted), `affiliations` with `years`, `last_known_institutions`. https://help.openalex.org/api-entities/authors/author-object
- Every response carries `X-RateLimit-Remaining`. https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication

## What to build

### `src/fn/net.py`

`Client._send` (line 199) returns a live 2xx answer with its `x-ratelimit-*` headers only (all headers would re-decode a gzip body). Cached answers carry none.

### `src/fn/contracts.py`

`class IndexIn(Model): pass` and `class IndexOut(Model): pages: int; authors: int; new: int; skipped: int; malformed: int; stopped: str = ""`.

### `src/fn/lanes/openalex.py`

`author_topics(record: dict, person_id: str, fetched_at: datetime) -> list[ClaimDraft]`, beside `topic_drafts` (line 223). One `record_source(record["id"], f"OpenAlex author topics {name}", fields, raw, fetched_at, updated)` with lines `id`, `display_name`, `years_with_works` (years of `counts_by_year` with `works_count` > 0, ascending, ", "-joined), then `topics.{i}.display_name` for the first `TOPICS = 5`; `raw` keeps `id`, each topic's `id`, `display_name`, `count`, and `counts_by_year`. One topic claim per topic, quoting its line with `quote` (line 132), no `years` (they are not per topic), and when there are years with works `claim_date` the last, precision year, method `record_field`. No other change.

### `src/fn/store.py`

`source_kinds(source_ids: list[str]) -> dict[str, SourceKind]`, beside `claim_records` (line 550) and in its style: `SELECT id, kind FROM sources WHERE id IN (SELECT value FROM json_each(?))`.

### `src/fn/usindex.py` (new)

- `FILTER` as above; `SELECT = "id,display_name,orcid,affiliations,last_known_institutions,updated_date,topics,works_count,counts_by_year"`; `PER_PAGE = 100`; `MAX_WORKS = 1000`; `RESERVE = 3000`.
- `remaining(response: httpx.Response) -> float | None`: the `x-ratelimit-remaining` header as a number.
- `run(ctx: StepContext, inp: IndexIn) -> IndexOut`. Raises RuntimeError without an HTTP client, when `http_mode` is `prefer` (it would serve cached pages, net.py:160, so a refresh needs `live`), or when `http_mode != "replay"` and `openalex_api_key` is unset. Pages `GET {openalex.API}/authors` with `filter`, `select`, `per_page`, `cursor` to the end. Per page: skip a result without `id` or `display_name` (`malformed`), an id already seen this run, and `works_count` over `MAX_WORKS` (`skipped`). Fetch last known institutions not yet fetched this run with `openalex.fetch(ctx, "institutions", "openalex", ids, openalex.INSTITUTION_SELECT)` (line 115) into one run-wide dict. `new` counts ids that `store.person_ids_by_identifier("openalex", ids)` (store.py:505) does not hold. Each author gets its own `ctx.store.tx()`: `openalex.save_author` (line 204) with the record cut to the `openalex.AUTHOR_SELECT` keys, as the lane stores it, then `upsert_claim` per `author_topics` draft. Log each page with credits left. After a page, stop when `remaining` is under `RESERVE`, with `stopped` "N credits left, under the reserve of 3000". A 429 `HttpError` stops it too, with its message; other errors raise.
- `refresh(store, settings, http) -> Search` and `main() -> int` as `enrich.refresh` and `enrich.main` (enrich.py:194, 204): job `fn-index`, step `index`; prints the counts and `stopped`.

### `pyproject.toml`

`fn-index = "fn.usindex:main"`.

### `src/fn/lanes/seeds.py`

- `must_place(chips: Chips) -> bool`: `chips.version >= 2 and chips.place is not None and chips.place.need == "must"`. It is r1's `parse.place_must`; once r1 merges, call that and delete this.
- `run` (line 94): with `must_place`, `area = area_of(ctx, chips)` whatever `lone_place` says. With an area, hits come on one rank counter under `MAX_HITS`: word and related matches whose person (`merged_into or id`) `near` (line 71) places inside, in today's order; then people inside without a match, nearest first, as today's place hits; then the other matches in today's order. Lines 126-140 run only without `must_place`. Without an area nothing changes.
- `near` (line 81) reads kinds with `ctx.store.source_kinds`, not `get_sources`, which loads 45 MB for a Washington box today.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which authors the copy holds, paging, reserve, works cut | `usindex.py`, run by `fn-index` |
| How an author record becomes a person, sources and claims | `lanes/openalex.py` |
| Rate-limit headers of a live answer | `net.py` |
| Order of the stored-lists lane's hits | `lanes/seeds.py` |
| Reading source kinds by id | `store.py` |
| Whether the place is required | `parse.place_must` (r1); `seeds.must_place` until then |

## Inputs a real run will meet

An empty first page; no key; no header (replay); a budget 429; one author on two pages; 1,001 works; no `display_name`; no topics or `counts_by_year`; an author already stored; a rerun; a required place not located or `anywhere_us`; 900 people inside (cut at 300).

## Tests (each must fail without the change)

- New `tests/test_usindex.py`, a `net.Client` on `httpx.MockTransport` with made-up pages in the documented author shape (the brief's recorded pages come from the lead's live run): each author stored once with affiliations, a location and dated topic claims; a rerun adds no person, source or claim; 2,999 credits left after page one stop before page two; a 429 stops it keeping earlier authors; a 1,001-works author, a nameless result and a repeated id are counted, not stored; an empty first page gives zeros; live mode without a key, or prefer mode, raises before any call; a replay answer without the header runs to the end.
- `tests/test_openalex.py`: `author_topics` keeps five topics, none with `years`; none without topics; undated without works years.
- `tests/test_db.py`: `source_kinds` gives each known id its kind and leaves out an unknown id.
- `tests/test_net.py`: a live answer keeps `X-RateLimit-Remaining` and drops another header.
- `tests/test_seeds_lane.py`: with a required place on a research question, a stored researcher inside without a question word is a hit ahead of a word match outside, and a word match inside comes first; with `MAX_HITS` patched to 2 and three people inside, the outside match drops; the same chips at version 1, or with a nice place, a place not located, or a required `anywhere_us` place, give today's output exactly.

## Existing tests that change, approved by the lead

None. No existing test may change; stop and report a failure.

## Recorded answers and replay (S6)

No prompt or model call changes, so no recorded answer gets a new key. Reranks do not rerun lanes, so stored searches keep their order on the same database. After the job, the 741 authors FN holds gain topic claims, which can move them in a rerank.

## Run time and growth

At most 640 credits (320 pages, 320 institution calls). A stored US-Belgian author record measures 14.5 KB of source and 30.6 claims at 600 bytes each with the search index. With the topics source and five claims, about 37 KB per author: 1.15 GB for 31,180 new authors, the database from 1.3 to 2.5 GB, plus 0.3 to 0.6 GB in `var/cache` per live run, since cursor URLs never repeat (estimate). Run time, estimated: 10 to 30 minutes. A stop loses one author at most.

## Hand check

`uv run python -m unittest` all green. On a copy (`mkvar.sh o1`), `FN_VAR=<copy> FN_HTTP=replay FN_LLM=replay uv run fn-rerank --all` before and after, saving `SELECT search_id, section, rank, person_id FROM candidates ORDER BY 1, 2, 3` from `<copy>/fn.sqlite3` each time: identical outputs prove the ranker kept every order (reranks do not rerun lanes). Time `seeds.run` on the copy for the Washington question with a `must` place, main against branch, and put both numbers in the MR. The lead times it after the live run; over the 5 s of S2 is a follow-up. The live run is the lead's.

## Not doing

A saved cursor, a migration, changes to `fn-enrich` or the lane's query, a live query by area, model calls.
