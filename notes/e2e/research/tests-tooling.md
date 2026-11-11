# How FN is tested, run locally and seeded

FN has one test runner (`uv run python -m unittest`), no lint, type-check or format tool, and no network in tests. Every test builds its own temp SQLite file, a stub LLM and a stub or mock HTTP client from `tests/helpers.py`. Recorded fixtures live in `tests/fixtures/`. The OpenAlex and extract fixtures, the seed lists and the gold files are gitignored, so a fresh checkout has none of them and the seed and OpenAlex tests fail until they are copied in. The server runs against any database through `FN_*` variables. Seed lists come from five scrapers that write JSONL rows; `fn-seed` loads them.

## 1. Building test doubles without the network

All helpers are in `tests/helpers.py`.

| Helper | Signature | What it does | Example use |
|---|---|---|---|
| `SECRET` | `str` constant (`helpers.py:21`) | A fake API key that tests look for in logs | `tests/test_web.py` imports it to check redaction |
| `FIXTURES` | `Path` (`helpers.py:22`) | `tests/fixtures` | `tests/test_geo.py:9` |
| `make_settings` | `(test: TestCase) -> Settings` (`helpers.py:25`) | Temp `var_dir`, removed in cleanup; `env="test"`, `llm_mode="replay"`, `http_mode="replay"`, fake OpenAlex key | `tests/test_seeds_lane.py:37` |
| `make_db` | `(test, settings=None) -> Store` (`helpers.py:32`) | A migrated `Store` in the temp dir; `store.close` added as cleanup | `tests/test_seeds_lane.py:38` |
| `make_seeded_db` | `(test, settings=None) -> Store` (`helpers.py:74`) | `make_db` plus every seed row and the recorded org facts. The load runs once per process into a cached temp file (`_seeded`, `helpers.py:59-71`), then the file is copied | `tests/test_seedload.py:14`, `tests/test_seeds_lane.py:96` |
| `recorded_orgs` | `(request: httpx.Request) -> httpx.Response` (`helpers.py:40`) | An `httpx.MockTransport` handler serving `fixtures/http/ror/<id>.json` and `fixtures/http/wikidata/<action>-<id>-<prop>.json`; 404 for anything else | default handler of `save_recorded_orgs` |
| `save_recorded_orgs` | `(store, settings, handler=recorded_orgs) -> Search` (`helpers.py:53`) | Runs the `fn-orgs` job over `data/org_aliases.csv` through a `net.Client` on a mock transport (live mode, mock transport) and returns the ended job | `helpers.py:67` |
| `StubLLM` | `StubLLM(answer=None, error=None, cost_usd=0.002)`; `.structured(task, data, schema)` (`helpers.py:81-95`) | Returns `schema.model_validate(answer)` for every call, or raises `error`; records one `llm` call on the current step | `StubLLM(error=AssertionError("parse must not run"))` at `tests/test_seeds_lane.py:97` |
| `cities_zip` | `() -> bytes` (`helpers.py:98`) | The tracked GeoNames extract zipped like the real dump | `tests/test_geo.py:31` |
| `StubHttp` | `.get(url, params=None)`, `.post(url, body, params=None, *, timeout_s, cost, keep, cache="refresh")` (`helpers.py:107-127`) | GET of the GeoNames URL returns the extract; any other GET returns an empty OpenAlex list; POST returns `{"results": []}`; POST with `cache="only"` raises `net.CacheMiss`. Each call is recorded | `StubHttp()` at `tests/test_seeds_lane.py:98` and `tests/test_web.py:57` |

There is no helper for a `StepContext`. A test builds it by hand with the dataclass fields (`src/fn/steps.py:27-35`: `search_id, store, llm, http, now, new_id, log, settings`). Example, `tests/test_seeds_lane.py:51-52`:

```python
ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                  log=logging.getLogger("fn.step"), settings=self.settings)
```

Other doubles live in the tests that need them:

- A real `net.Client` over `httpx.MockTransport`: `helpers.py:55` and `tests/test_openalex.py` (`route`, imported by `tests/test_gold.py:25`).
- A fake `Popen` for the Claude CLI: `FakeProc` at `tests/test_llm.py:34`.
- A one-off class with a `get` method for the GeoNames fetch: `tests/test_geo.py:28` and `:45`.

Any outbound call needs a running step. `current_recorder()` raises `RuntimeError` outside one (`src/fn/steps.py:82-87`). That is why tests go through `Worker.execute` (`tests/test_seeds_lane.py:105`) or `run_step`.

## 2. Fixture folders

| Folder | Entries here | Holds | Tracked? | Used by |
|---|---|---|---|---|
| `tests/fixtures/geo/` | 1 | `cities15000-extract.txt`, a GeoNames extract | yes | `tests/test_geo.py:9`, `helpers.py:103` |
| `tests/fixtures/http/ror/` | 61 | ROR responses by id | yes | `recorded_orgs` |
| `tests/fixtures/http/wikidata/` | 9 | Wikidata `wbgetentities` and `wbgetclaims` responses | yes | `recorded_orgs` |
| `tests/fixtures/http/web/` | 3 | `extract.json`, `search.json`, `v1_fields.json` for the web lane | yes | `tests/test_web_lane.py:19` |
| `tests/fixtures/http/linkedin/` | 1 | `profiles.json` | yes | `tests/test_linkedin.py:56` |
| `tests/fixtures/http/openalex/` | 19 | Recorded OpenAlex responses such as `author_search_<name>.json` | no (`.gitignore:5`) | `tests/test_openalex.py:23,31` |
| `tests/fixtures/llm/` | 30 | `parse-<sha16>.json`, one per recorded prompt hash | the 30 `parse-*` files yes; `extract-*.json` no (`.gitignore:6`); none exist locally | `FixtureLLM` (`src/fn/llm.py:145-178`) |

Why ignored: the repo is public (`.gitignore:1`). The OpenAlex responses and the extract answers quote real people and their pages. No comment in `.gitignore` states this for the fixture lines; the only comment is the one on line 1.

How a test fails when a fixture is missing:

- OpenAlex JSON: `recorded()` calls `read_text` on the path, so the test raises `FileNotFoundError` (`tests/test_openalex.py:30-31`).
- LLM: replay mode raises `FixtureMissing("no LLM fixture <task>-<sha16>; prompt starts: ...")` (`src/fn/llm.py:169-172`). The key is `sha256(system prompt, user turn, schema, model)`, so editing a prompt file in `src/fn/prompts/` invalidates its fixtures (`llm.py:65-67,161`).
- HTTP in replay mode: `CacheMiss` (`src/fn/net.py:127-129`).
- ROR and Wikidata: `recorded_orgs` answers 404 (`helpers.py:48-49`), so the org job ends with an error and `_seeded` raises `RuntimeError("the recorded org facts did not load")` (`helpers.py:67-68`).
- Seed rows (`data/seeds`): `seedload.SEEDS.glob` finds nothing, so `ROWS` is empty and the count assertions fail (`tests/test_seedload.py:9,30`). The Goemans tests fail on a missing key (`tests/test_seeds_lane.py:113`).
- Geo extract: `tests/test_geo.py:9` reads it at import, so the whole module errors. It is tracked, so this only happens if it is deleted.

## 3. Test style

- Standard library `unittest` only. Classes subclass `unittest.TestCase`, files end with `if __name__ == "__main__": unittest.main()`. `pytest` is not a dependency.
- Files are `tests/test_<module>.py`, one per source module. Classes are `<Thing>Test`. Methods are long sentence names such as `test_a_second_load_changes_nothing` (`tests/test_seedload.py:45`).
- `setUp` builds the store with `make_*`. Cleanup goes through `self.addCleanup`, not `tearDown`.
- Many tests have a 1 to 3 line docstring that states the invariant. Some have none (`tests/test_seedload.py:45`).
- Loops over cases use `with self.subTest(...)` (`tests/test_seeds_lane.py:58`).
- `tests/__init__.py` exists, so imports are `from tests.helpers import ...`.
- Web pages: `tests/test_web.py` makes the real app with `create_app(settings, StubLLM(...), StubHttp())` and wraps it in `fastapi.testclient.TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)` (`test_web.py:56-60`). It enters the client as a context manager so the lifespan runs. Searches are created on the worker thread because SQLite connections are per thread (`test_web.py:63-66`). Assertions are on response text (HTML run through `html.unescape`) and headers. Hostile strings (`HOSTILE`, `test_web.py:46`) are pushed through every page to check escaping. There is no browser, Playwright or screenshot test.
- Wait helper: `wait_ended` polls the store with a 10 s deadline (`test_web.py:72-78`).
- There are 20 test files and about 270 test methods. Run: `uv run python -m unittest`.

## 4. The done check

`tests/test_done_check.py:12-22` has one test. It walks every file under `src/` and `tests/`, skips `src/fn/migrations/` and `__pycache__`, and asserts that no line matches `PATTERN` (`:7-8`). The pattern names a removed concept: the old "tie" label, its step, its column and a limit constant. The pattern is built from string parts so the file does not match itself (`:6`). On failure the assertion lists `path:line: text`. It guards against a half-finished removal. It does not check behaviour.

## 5. Running the server on a throwaway database

`config.from_env()` reads these (`src/fn/config.py:54-73`):

| Variable | Field | Default | Effect |
|---|---|---|---|
| `FN_VAR` | `var_dir` | `<repo>/var` | Holds `fn.sqlite3`, `cache/`, `log/`, `gold/` |
| `FN_PORT` | `port` | 8765 | Listen port |
| `FN_HOST` | `host` | 127.0.0.1 | `serve()` exits for anything but 127.0.0.1 or ::1 (`src/fn/web/app.py:842-843`) |
| `FN_ENV` | `env` | `dev` | `test` makes `ClaudeCli` refuse to start (`src/fn/llm.py:78`) |
| `FN_LLM` | `llm_mode` | `live` | `live`, `record`, `replay`, `prefer` (`contracts.py:39`) |
| `FN_HTTP` | `http_mode` | `live` | `live` or `replay` |
| `FN_LINKEDIN` | `linkedin_live` | off | `1` allows the paid Apify LinkedIn run (`lanes/linkedin.py:35,247`) |
| `OPENALEX_API_KEY`, `PARALLEL_API_KEY`, `APIFY_TOKEN` | keys | none | From the env var, else the macOS Keychain (`config.py:58-59`) |

Throwaway server on another port:

```
FN_VAR=/tmp/fn-scratch FN_PORT=8899 uv run fn-serve
FN_VAR=/tmp/fn-scratch uv run fn-seed      # fills the empty database with the seed rows
```

`setup_logging` creates the folder with mode 0700 and logs to `<FN_VAR>/log/fn.log` (`steps.py:110-122`); the lifespan migrates the database (`app.py:803-806`). Without `fn-seed` the seed lane has nothing to match.

Replay with no paid call:

```
FN_LLM=replay FN_HTTP=replay FN_VAR=/tmp/fn-scratch FN_PORT=8899 uv run fn-serve
```

- `FN_LLM=replay` builds a `FixtureLLM` that reads `tests/fixtures/llm` and calls no CLI (`llm.py:181-186`). Only questions whose parse prompt was recorded work. Any other question raises `FixtureMissing`. A search created with stored chips skips parse (`tests/test_seeds_lane.py:135-141`). The extract step needs `extract-*` fixtures, which are not in the repo.
- `FN_HTTP=replay` serves only `<FN_VAR>/cache/<sha256>.json` and raises `CacheMiss` otherwise (`net.py:119-129`). A fresh `FN_VAR` has an empty cache, so every HTTP call misses, including the GeoNames dump (`geo.py:54`). To replay recorded calls, point `FN_VAR` at a directory whose `cache/` was filled by an earlier live run. The cache key is the request URL, plus the sorted JSON body for a POST (`net.py:196`).
- `FN_LLM=prefer` serves a fixture when one exists and otherwise calls `claude -p` on the subscription, writing no fixture (`llm.py:170-171`). Use it only when a call on the subscription is acceptable.
- `FN_LLM=record` calls the CLI for every prompt and writes `tests/fixtures/llm/<task>-<sha16>.json` (`llm.py:163-168`).

## 6. How a seed list is produced

**Scrapers.** Five scripts in `scripts/seeds/`: `baef.py` (317 lines), `climate.py` (154), `consuls.py` (228), `francqui.py` (300), `kvab.py` (221). Each is a PEP 723 script (`# /// script` header with `requires-python` and `dependencies = ["httpx"]`; `kvab.py` adds `docling`). They are run directly, for example `uv run scripts/seeds/consuls.py`. Each has a `main()` that:

1. fetches the source with `common.fetch`;
2. parses it into lines or entries (`consuls.py` uses a `HTMLParser` subclass, `LineParser`, `:49`);
3. saves the raw bytes and a normalized text layer with `common.save_raw`;
4. builds row dicts;
5. calls `common.write_rows(LIST, rows)`;
6. prints the row count.

`consuls.py` also raises its own `StructureError` when the page shape changed and exits 1 (`:45,223-228`).

**Common helpers** (`scripts/seeds/common.py`):

| Helper | Line | Behaviour |
|---|---|---|
| `fetch(url)` | 27 | GET at most once a second per host, user agent `FN-prototype/0.1 (personal research)`, 60 s timeout, `raise_for_status` |
| `norm(text)` | 42 | NFC, NBSP and curly quotes folded, single spaces |
| `save_raw(list_name, filename, content, text)` | 50 | Writes bytes to `data/seeds/raw/<list>/<filename>` and `norm(text)` to `<filename>.txt`; returns the repo-relative `.txt` path |
| `row_key(list_name, name, year, extra="")` | 60 | `list|folded-name|year|extra` |
| `write_rows(list_name, rows)` | 65 | Validates every row, then replaces `data/seeds/<list>.jsonl` through a `.tmp` file and `os.replace` |

**JSONL row** (one JSON object per line; types from `REQUIRED`, `common.py:15-21`; example from `consuls.py:195-200`):

| Field | Type | Meaning |
|---|---|---|
| `list` | str | List name; must equal the file's list |
| `row_key` | str | Unique within the list; becomes the person's `seed` identifier |
| `name` | str | Cleaned name; not empty |
| `name_on_page` | str | Name as printed; must appear in `quote` after `norm` |
| `year` | int or null | Year of the record; dates the claims when set |
| `role` | str or null | Role claim text; falls back to `source_title` |
| `institutions` | list of `{name: str, relation: "home"/"host"/"employer"/"member_of"}` | One affiliation claim each |
| `field` | str or null | Topic claim text |
| `place` | str or null | Stored in the row only |
| `jurisdiction` | list or null | Stored in the row only (consul states) |
| `profile_url` | str or null | Stored in the row only |
| `source_url` | str | Page the row came from |
| `source_title` | str | Page title |
| `source_date` | str or null | `YYYY`, `YYYY-MM` or `YYYY-MM-DD` |
| `date_method` | str | One of the keys of `seedload.DATE_METHODS` |
| `page` | int or null | PDF page |
| `quote` | str | Text the claims quote; must occur in the raw text layer |
| `raw_path` | str | Repo-relative path of the `.txt` layer |
| `fetched_at` | str | ISO date |

No other field is allowed (`common.py:78-79`). `seedload` reads only `list, row_key, name, year, role, institutions, field, source_url, source_title, source_date, date_method, quote, raw_path, fetched_at` (`seedload.py:43-79`).

**Raw pages.** `data/seeds/raw/<list>/`: one HTML, PDF or DOCX per list, or per person for `climate`, each with a `.txt` sibling. All of `data/seeds/raw/` is gitignored (`.gitignore:3`).

**Validation.** `write_rows` raises `ValueError` for a missing or mistyped field, an unknown field, an empty name, a wrong list, a bad institution, a quote without the name, a quote absent from the raw text, or a duplicate `row_key` (`common.py:71-92`); nothing is written then. `scripts/seeds/check.py` re-runs those checks on every file through `validate` (`:48-60`, which swaps `common.SEEDS` for a `.check` folder and removes it). It also asserts the row count against `EXPECTED` (hand counts of 2026-10-29: consuls 34, baef 3577, kvab 545, francqui 331, climate 453) and that each `GOLD` name is present by first and last token (`:14-21,30-45`). Run `uv run scripts/seeds/check.py`; exit code 1 on any problem.

**Loading.** `fn-seed` is `fn.seedload:main` (`pyproject.toml:13`). `load(store)` (`seedload.py:82-97`) reads `data/seeds/*.jsonl` in name order inside one transaction. Per row it:

1. builds one `Source` (kind `seed_page`, id = sha1 of the URL, text = normalized raw `.txt`) per `raw_path`;
2. calls `store.resolve_person` with a `seed` identifier from `row_key`;
3. upserts claims from `drafts()` (`:54-79`): one `role` claim for the list, one `affiliation` claim per institution, one `topic` claim when `field` is set.

All claims quote the row at its offsets in the source text. The date is `year` (precision year, method `record_field`) or `source_date` (precision from its length, method from `DATE_METHODS`). Org ids come from `orgs.org_id(name)` via `data/org_aliases.csv`. A second load changes zero rows (`tests/test_seedload.py:45-48`).

**Adding a sixth list.** Exactly these changes:

1. `scripts/seeds/<name>.py`: a scraper ending in `common.write_rows("<name>", rows)`, with the PEP 723 header.
2. `src/fn/seedload.py:23-29`, `LISTS`: add `"<name>": (relation, "<list organization name>")`. The relation must be a `Relation` literal in `contracts.py`. A new list gets no row in `LISTS` otherwise and `drafts` raises `KeyError` (`seedload.py:71`).
3. `data/org_aliases.csv`: the organization name must be an alias row, or the role claim gets `org_id=None` (`orgs.org_id` returns `None`, `orgs.py:63-64`). Run `fn-orgs` to fetch its facts.
4. A new `date_method` string needs a key in `seedload.DATE_METHODS` (`:33-39`). A new institution relation needs an entry in `common.RELATIONS` (`common.py:14`) and in `seedload.RELATIONS` (`:30-32`).
5. `scripts/seeds/check.py:14-21`: add the list to `EXPECTED` and `GOLD`. A list missing from `EXPECTED` is never checked because the run loops over `EXPECTED` (`:65`).
6. `tests/test_seedload.py:30,31,47`: the total 4940 is hardcoded in three places and must change.
7. The seed lane needs no change: it matches the `seed_page` source kind, not list names (`grep` of `src/` finds no list name outside `seedload.py` and migrations).

## 7. Data that stays local

Gitignored (`.gitignore`): `data/seeds/*.jsonl`, `data/seeds/raw/`, `data/gold/` (`gold-set.json`, `reach.json`), `tests/fixtures/http/openalex/`, `tests/fixtures/llm/extract-*.json`, `var/` (database, cache, logs, gold reports) and `*.sqlite3*`. Tracked in `data/`: only `org_aliases.csv` and `org_aliases_unmapped.txt` (`git ls-files data`).

There is no script, README step or setup command for a fresh checkout (`README.md` is one line, `# FN`). The ways to get each piece:

- Seed rows and raw pages: run the five scrapers, then `check.py`, then `fn-seed`. This needs the network, and the live pages may have changed since the 2026-10-29 counts.
- OpenAlex fixtures and `data/gold/reach.json`: `scripts/gold/probe_openalex.py` (a one-off script; it reads the key from `OPENALEX_API_KEY` or the Keychain and makes up to 60 calls, `:21,40-60`).
- `data/gold/gold-set.json`: read by `fn-gold` (`src/fn/gold.py:31`). No script in the repo writes it and no test reads it.
- Extract fixtures: recorded with `FN_LLM=prefer` or `record`.
- This worktree has these files already (copied from the main checkout), which is why tests pass here.

## 8. Lint, type check, format

None. `pyproject.toml` has no `[tool.*]` section except `[tool.uv]`, no dev dependency group, no ruff, mypy, pyright or black. There is no `.github/` folder, pre-commit file or CI config in the repo. Code style is by convention: type hints on signatures, PEP 695 generics (`def structured[T: BaseModel]`), Pydantic models, lines up to about 120 characters. The only automated guard is the test suite, including the done check.

Packaging: Python 3.13 only (`requires-python = ">=3.13,<3.14"`), dependencies `fastapi`, `httpx`, `pydantic`, `uvicorn`, build backend `uv_build`, console scripts `fn-serve`, `fn-seed`, `fn-gold`, `fn-orgs` (`pyproject.toml:1-17`). `uv` uses managed Python only (`:22-23`).

## Maintenance notes found while reading

- `notes/mvp0/architecture.md:178` says the seed text layers are tracked. `.gitignore:3` ignores all of `data/seeds/raw/` and `git ls-files data` lists none.
- `scripts/vendor_map.py` is unrelated to seeds: it downloads MapLibre GL JS and the OpenFreeMap style into `src/fn/web/static`, checks the npm integrity hash and writes `vendor.json` (`:28-45`). It runs its `main()` at import (`:48`, no `__main__` guard) and takes an optional version argument.
