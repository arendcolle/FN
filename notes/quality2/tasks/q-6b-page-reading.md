# Task Q-6b: FN reads found pages itself

## Goal

Parallel Extract reads every found page today, at $0.001 a page (`src/fn/lanes/web.py:30`), and a backend without a key leaves FN with search snippets only. The standard-library HTML parser that prefers `main` or `article` read 7 of 10 test pages in 131 ms for nine pages, with no new dependency, and `pdftotext` read the PDF in 0.18 s; the three failures were a 403, a JavaScript-only page and a PDF (`research/local-search.md`). This task adds `pageread.py`, which fetches a page through `net.Client` after a robots.txt check and reads it, and makes `websearch.find` send only failed pages to Extract, and only with a key. Pages FN read itself are stored as source kind `page`. Decision W3 in `design.md`. Owner: `pageread.py`. Needs Q-6a.

## What to build

### `src/fn/net.py` and `src/fn/contracts.py`

- `HttpError.__init__(self, message: str, status: int | None = None)` keeps `status`; the raise for a non-2xx answer (line 187) passes `response.status_code`. `allowed` below reads it.
- `class Redirect(HttpError)` with `location: str`. `_send` raises it, recorded as today, for a 301, 302, 303, 307 or 308 that has a `Location` header.
- `get(..., redirects: int = 0)`: on `Redirect` with hops left, GET `urljoin(current, location)` as its own recorded call (the http and https check of `_request` applies). After more than `redirects` hops, raise `HttpError(f"GET {url} redirected more than {redirects} times")`. A live final answer is also written to the cache file of the first URL, so prefer and replay serve it there. `HttpClient.get` gains `redirects: int = 0`.
- `page_source` (`src/fn/contracts.py:211`) gains `*, kind: Literal["vendor_page", "page"] = "vendor_page", plain: bool = False`. `plain` skips the markdown pass and only applies `normalize`. The id holds `kind` in place of the fixed "vendor_page" (line 221). Default calls are unchanged.

### `src/fn/config.py`

`page_reader: Literal["local", "parallel"] = "local"`, read from `FN_PAGE_READER`. "parallel" sends every page to Extract as today, so the owner can switch back with one line.

`score.run` (`src/fn/score.py:325`) adds `page_reader=os.environ.get("FN_PAGE_READER") or "parallel"` to its replay `Settings`, next to Q-6a's `search_backend`, so stored searches replay their recorded Extract calls; their robots.txt and page GETs were never cached. A snapshot taken after this task replays its local reads with `FN_PAGE_READER=local`.

### `src/fn/pageread.py` (new; owner of fetching and reading a found page)

- `MAX_CHARS = 12_000`, `MIN_CHARS = 300`, `MAX_REDIRECTS = 3`, `WORKERS = 4`, `AGENT = "FN"`, `SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template", "iframe"}`, `BLOCKS = {"p", "div", "li", "br", "tr", "td", "dd", "dt", "h1" to "h6", "section", "article", "main", "blockquote"}`.
- `@dataclass(frozen=True) class Read`: `url: str`, `title: str | None`, `text: str | None`, `failed: str | None`, `truncated: bool = False`.
- `read_all(ctx: StepContext, urls: list[str]) -> list[Read]`: `read` over `fan_out(..., WORKERS)`, one `Read` per url in order; an exception becomes `failed=f"{type(exc).__name__}: {exc}"`.
- `read(ctx, url) -> Read`: `allowed` first; then `ctx.http.get(url, redirects=MAX_REDIRECTS)`. A body that starts with `%PDF-` goes to `pdf_text`; any other body is decoded as UTF-8, else cp1252 with replacement, and goes to `html_text`. The text is cut to `MAX_CHARS` with `truncated` set.
- Failure reasons, word for word: `robots.txt disallows it`, `robots.txt could not be read: {error}`, the `HttpError` message (a 403, a 999, a 404, too many redirects), `a PDF and pdftotext is not installed`, `pdftotext failed: exit {code}`, `{n} characters of text, under 300`.
- `allowed(ctx, url) -> str | None`: one `urllib.robotparser.RobotFileParser` per `scheme://host`, kept in a module dict `ROBOTS` under a lock for the process; `tests/test_pageread.py` calls `pageread.ROBOTS.clear()` in `setUp`. Its robots.txt comes through `ctx.http.get(f"{scheme}://{host}/robots.txt", redirects=MAX_REDIRECTS)`, so it is recorded and cached like any call. An `HttpError` with status 401 or 403 disallows the host; any other 4xx allows it; any other error is the "could not be read" failure. Returns None when `can_fetch(AGENT, url)`.
- The client name on these fetches (lead's ruling): `USER_AGENT = "FN/0.1"`. `net.Client.get` gains `agent: str | None = None`; when set, the request goes out with `User-Agent: {agent}` in place of `net.USER_AGENT`, which holds the repository's address. `allowed` and `read` pass `agent=USER_AGENT` on the robots.txt GET and on every page GET, so a site a search happens to find never receives the repository's address. Test: the recorded request of a page fetch and of its robots.txt carries exactly `FN/0.1`; a call without `agent` keeps today's header.
- `html_text(html: str) -> tuple[str | None, str]`: an `html.parser.HTMLParser` that skips text inside `SKIP`, starts a new line at each tag in `BLOCKS`, and keeps the text inside `main` or `article` apart. It returns the `<title>` text and the `main`/`article` text when that has at least `MIN_CHARS` characters, else the whole body's text. Lines get single spaces and empty lines go.
- `pdf_text(body: bytes) -> str`: `shutil.which("pdftotext")` or the failure; `subprocess.run([path, "-enc", "UTF-8", "-", "-"], input=body, capture_output=True, timeout=30, check=False)`.

### `src/fn/websearch.py`

- `Page` gains `local: bool = False` and `failed: str | None = None` (FN's own read error).
- `find`, after the hits: with `page_reader == "local"`, `pageread.read_all` over the kept urls. A page read gets `texts=[("Page read by FN", text)]`, `local=True`. Failed pages go to one Extract call when a Parallel key is set; their texts are Q-5's three, then the snippet; with no key, the snippet only. An Extract error in local mode leaves those pages with their snippet and adds a row `stage="page"`, `kept=False`, reason `f"Extract failed: {exc}"`. With `page_reader == "parallel"`, Extract reads every page as before, and its errors propagate as before.
- `source_of(page: Page, fetched_at: datetime, kind: str | None = None) -> tuple[str, Source] | None`: the first text with plain text after `page_source(..., kind=kind or ("page" if page.local else "vendor_page"), plain=page.local)`, with its label; None when no text has any. This moves the loop from `web.collect` (Q-5, today `web.py:148-156`), which now calls it. Q-8 calls it with `kind="lookup_page"`.
- `web.collect` page rows, word for word: `rank {rank}, {title or url}: {n} characters from Page read by FN`, plus `; may be truncated at 12,000 characters` when `truncated`, and `; FN could not read it ({failed})` on a page Extract or the snippet filled.

### Source kinds

The kind `page` exists already and no stored source uses it (0 rows in `var/fn.sqlite3`). It is already listed everywhere it must be, so no list changes: `SourceKind` (`src/fn/contracts.py:35`), `present.PROSE` (`src/fn/present.py:40`, a quote is shown), `gold.EVENT_KINDS` (`src/fn/gold.py:38`), the local search, which leaves out only `record` once Q-2 lands (`seeds.excluded`), and `score.py:129`, which reads `seed_page` only. Identity reads identifier schemes and never source kinds (`src/fn/identity.py:15`); people on a page FN read get `mention` identifiers through `extract.identifier` as today (`src/fn/extract.py:75`).

## Inputs a real run will meet

A 200 page with a `main` of 50 characters and a long body; nested `article` inside `main`; a JavaScript-only page (under 300 characters); a 403; a 999; a 301 to https then a 200; four redirects; a redirect to `ftp:`; robots.txt that disallows the path, answers 404, answers 403, times out; two pages on one host (one robots fetch); a PDF with and without `pdftotext`; a 4.9 MB page; a cp1252 page; a text of 30,000 characters; a page failed with no key; the same url in both web lanes (one source); replay mode, where every fetch comes from the cache.

## Tests (each must fail without the change)

The builder writes every page fixture by hand under `tests/fixtures/http/pages/`, with made-up names.

- New `tests/test_pageread.py`, over `net.Client` with `httpx.MockTransport`: each failure reason above; `main` preferred and the body used when `main` is short; nav, script and footer text absent; the 12,000 cut; one robots.txt call for two pages on a host; a 404 robots allows; a 301 chain followed and the final body served in replay mode under the first url; a PDF without `pdftotext` (`shutil.which` patched to None) fails; with `pdftotext` on the PATH (`skipUnless`), a one-page PDF the test writes from raw PDF syntax gives its text.
- `tests/test_websearch.py`: two read pages and one 403 page with a key send one Extract for the 403 page only; without a key it keeps its snippet; `page_reader="parallel"` sends Extract for all; a read page is stored as kind `page` with no markdown pass ("a_b_c" stays) and an Extract page as `vendor_page`.
- `tests/test_net.py`: `HttpError.status` on a 404; `redirects` follows, caps and refuses a non-http location.

## Existing tests that change

- `tests/test_web_lane.py` `WebLaneTest.setUp` (line 161) and `WebPeopleTest.setUp` (line 397), and `tests/test_fan_out.py` `FanOutTest.setUp` (line 64): the settings gain `"page_reader": "parallel"`, so they keep testing Extract as today.
- No other existing test may change; stop and report a failure.

## Hand check

`uv run python -m unittest` all green. The lead, live: `FN_VAR=<copy> FN_LLM=prefer FN_HTTP=prefer fn-gold <two dev case ids>`; count page rows per label in `lane:web` and `lane:web_topic`, against the 7 of 10 pages the research read locally, and the Extract calls in `/debug/stats`.

## Not doing

trafilatura or any new package. Reading JavaScript pages. Page dates from the HTML. A per-host crawl delay. Changing what Extract returns.
