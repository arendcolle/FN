# Task Q-9a: FN reads a web page itself

## Goal

The new scout lane (Q-9b) gets page addresses from a web researcher and needs each page's text. Today only Parallel Extract reads pages, at $0.001 a page and within limits that will not grow. The standard-library HTML parser read 7 of 10 test pages in 131 ms with no new dependency (`research/local-search.md`). This task adds `pageread.py`, which fetches a page through `net.Client` after a robots.txt check and returns its text. It replaces the earlier task Q-6b and builds its core only: nothing in the web lane or in `websearch.py` changes here. Owner: `pageread.py` (fetching and reading a found page).

## What to build

### `src/fn/net.py`

- `HttpError.__init__(self, message: str, status: int | None = None)` keeps `status`; the raise for a non-2xx answer passes `response.status_code`.
- `class Redirect(HttpError)` with `location: str`. `_send` raises it, recorded as today, for a 301, 302, 303, 307 or 308 that has a `Location` header.
- `get(url, params=None, *, redirects: int = 0, agent: str | None = None)`: on `Redirect` with hops left, GET `urljoin(current, location)` as its own recorded call (the http and https check of `_request` applies). After more than `redirects` hops, raise `HttpError(f"GET {url} redirected more than {redirects} times")`. A live final answer is also written to the cache file of the first URL, so prefer and replay modes serve it there. When `agent` is set, the request goes out with `User-Agent: {agent}` in place of `net.USER_AGENT`, which holds the repository's address. A call without `agent` keeps today's header.
- `HttpClient.get` in `contracts.py` (the protocol) gains the same keyword arguments. `tests/helpers.py` `StubHttp.get` takes `**options`.

### `src/fn/contracts.py`

`page_source` gains `*, kind: Literal["vendor_page", "page"] = "vendor_page", plain: bool = False`. `plain` skips the markdown pass and only applies `normalize`. The id holds `kind` in place of the fixed "vendor_page". Default calls are unchanged. The source kind `page` exists already.

### `src/fn/pageread.py` (new)

- `MAX_CHARS = 40_000`, `MIN_CHARS = 300`, `MAX_REDIRECTS = 3`, `WORKERS = 6`, `AGENT = "FN"`, `USER_AGENT = "FN/0.1"`, `SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template", "iframe"}`, `BLOCKS = {"p", "div", "li", "br", "tr", "td", "dd", "dt", "h1" to "h6", "section", "article", "main", "blockquote"}`.
- `@dataclass(frozen=True) class Read`: `url: str`, `title: str | None`, `text: str | None`, `failed: str | None`, `truncated: bool = False`.
- `read_all(ctx: StepContext, urls: list[str]) -> list[Read]`: `read` over `fan_out(..., WORKERS)`, one `Read` per url in order; an exception becomes `failed=f"{type(exc).__name__}: {exc}"`.
- `read(ctx, url) -> Read`: `allowed` first; then `ctx.http.get(url, redirects=MAX_REDIRECTS, agent=USER_AGENT)`. A body that starts with `%PDF-` fails with `a PDF, not a web page`. Any other body is decoded as UTF-8, else cp1252 with replacement, and goes to `html_text`. The text is cut to `MAX_CHARS` with `truncated` set.
- Failure reasons, word for word: `robots.txt disallows it`, `robots.txt could not be read: {error}`, the `HttpError` message (a 403, a 999, a 404, too many redirects), `a PDF, not a web page`, `{n} characters of text, under 300`.
- `allowed(ctx, url) -> str | None`: one `urllib.robotparser.RobotFileParser` per `scheme://host`, kept in a module dict `ROBOTS` under a lock for the process; `tests/test_pageread.py` calls `pageread.ROBOTS.clear()` in `setUp`. Its robots.txt comes through `ctx.http.get(f"{scheme}://{host}/robots.txt", redirects=MAX_REDIRECTS, agent=USER_AGENT)`, so it is recorded and cached like any call. An `HttpError` with status 401 or 403 disallows the host; any other 4xx allows it; any other error is the "could not be read" failure. Returns None when `can_fetch(AGENT, url)`.
- `html_text(html: str) -> tuple[str | None, str]`: an `html.parser.HTMLParser` that skips text inside `SKIP`, starts a new line at each tag in `BLOCKS`, and keeps the text inside `main` or `article` apart. It returns the `<title>` text and the `main`/`article` text when that has at least `MIN_CHARS` characters, else the whole body's text. Lines get single spaces and empty lines go.
- `windows(text: str, names: list[str], *, around: int = 1500, limit: int = 12_000) -> str`: the parts of `text` within `around` characters of any occurrence of a name's last word (compared casefolded, on word boundaries), cut at line ends, overlapping parts merged, in page order, joined by a line holding only `…`, and cut to `limit` characters at a line end. A text of at most `limit` characters comes back unchanged. A text that holds none of the names comes back as its first `limit` characters. The scout lane uses it so a long page costs one page-reading call, and every kept line is a character-for-character copy of the page's line.

## Inputs a real run will meet

A 200 page with a `main` of 50 characters and a long body; nested `article` inside `main`; a JavaScript-only page (under 300 characters); a 403; a 999; a 301 to https then a 200; four redirects; a redirect to `ftp:`; robots.txt that disallows the path, answers 404, answers 403, times out; two pages on one host (one robots fetch); a PDF; a 4.9 MB page; a cp1252 page; a text of 60,000 characters whose name stands at character 50,000 (cut at 40,000: the name is lost and the first 12,000 characters come back); a name that stands 30 times; an empty names list; replay mode, where every fetch comes from the cache.

## Tests (each must fail without the change)

The builder writes every page fixture by hand, with made-up names.

- New `tests/test_pageread.py`, over `net.Client` with `httpx.MockTransport`: each failure reason above; `main` preferred and the body used when `main` is short; nav, script and footer text absent; the 40,000 cut; one robots.txt call for two pages on a host; a 404 robots allows; a 301 chain followed and the final body served in replay mode under the first url; the recorded request of a page fetch and of its robots.txt carries exactly `FN/0.1`; `windows` on a long text with one name, two far-apart names, overlapping parts, no name, and a short text.
- `tests/test_net.py`: `HttpError.status` on a 404; `redirects` follows, caps and refuses a non-http location; `agent` replaces the header and a call without it keeps today's.
- A `page_source(..., kind="page", plain=True)` test: the kind is `page` and "a_b_c" stays as written.

## Existing tests that change

`tests/helpers.py` `StubHttp.get` takes `**options`. No other existing test may change; stop and report a failure.

## Hand check

`uv run python -m unittest` all green. Then, with the real network and no key, from a scratch script: `pageread.read` on three public pages of your choice that are safe to fetch once (for example a Wikipedia article, a university staff page, a news article), printing for each the title, the number of characters and the first 200 characters, or the failure reason. Do not fetch linkedin.com.

## Not doing

- PDF text. The web lane's use of this reader, the Parallel Extract fallback and a `page_reader` setting (the earlier Q-6b). JavaScript rendering. Any new dependency.
