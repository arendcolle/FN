"""Reads a web page itself: robots.txt first, a fetch through net.Client, then the page's text with the standard library."""
import re
import threading
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from fn.net import CacheMiss, HttpError
from fn.steps import StepContext, fan_out

MAX_CHARS = 40_000
MIN_CHARS = 300
MAX_REDIRECTS = 3
WORKERS = 6
AGENT = "FN"
USER_AGENT = "FN/0.1"
SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template", "iframe"}
BLOCKS = {"p", "div", "li", "br", "tr", "td", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
          "main", "blockquote"}
MAIN = {"main", "article"}
ROBOTS: dict[str, RobotFileParser] = {}
_LOCK = threading.Lock()
_HOST_LOCKS: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class Read:
    url: str
    title: str | None
    text: str | None
    failed: str | None
    truncated: bool = False


class _Text(HTMLParser):
    """Collects the title, the whole body's lines and the lines inside main or article."""

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.main = 0
        self.in_title = False
        self.title: list[str] = []
        self.body: list[str] = []
        self.inside: list[str] = []
        self.line: list[str] = []
        self.main_line: list[str] = []

    def _break(self) -> None:
        for parts, lines in ((self.line, self.body), (self.main_line, self.inside)):
            if line := " ".join("".join(parts).split()):
                lines.append(line)
            parts.clear()

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif self.skip:
            return
        if tag == "title":
            self.in_title = True
        if tag in BLOCKS:
            self._break()
        if tag in MAIN:
            self.main += 1

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(self.skip - 1, 0)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
        if tag in BLOCKS:
            self._break()
        if tag in MAIN:
            self.main = max(self.main - 1, 0)

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
            return
        self.line.append(data)
        if self.main:
            self.main_line.append(data)


def html_text(html: str) -> tuple[str | None, str]:
    """The page's title and its text, one line per block.

    The text is what stands inside main or article when that has at least MIN_CHARS characters, else the whole
    body. Script, style, navigation, header, footer, aside and form text is left out.
    """
    parser = _Text()
    parser.feed(html)
    parser.close()
    parser._break()
    body, inside = "\n".join(parser.body), "\n".join(parser.inside)
    return " ".join("".join(parser.title).split()) or None, inside if len(inside) >= MIN_CHARS else body


def _robots(ctx: StepContext, root: str) -> RobotFileParser:
    """The parsed robots.txt of scheme://host, fetched once per process; raises HttpError when it cannot be read."""
    with _LOCK:
        lock = _HOST_LOCKS.setdefault(root, threading.Lock())
    with lock:
        if root in ROBOTS:
            return ROBOTS[root]
        parser = RobotFileParser()
        try:
            parser.parse(ctx.http.get(f"{root}/robots.txt", redirects=MAX_REDIRECTS, agent=USER_AGENT).text.splitlines())
        except HttpError as exc:
            if exc.status in (401, 403):
                parser.parse(["User-agent: *", "Disallow: /"])
            elif isinstance(exc, CacheMiss) or (exc.status is not None and 400 <= exc.status < 500):
                # A replay sends nothing, so a robots.txt that was never cached (a 404 is not) forbids nothing.
                parser.parse([])
            else:
                raise
        ROBOTS[root] = parser
        return parser


def allowed(ctx: StepContext, url: str) -> str | None:
    """None when robots.txt lets FN fetch url, else the reason it may not."""
    parts = urlsplit(url)
    try:
        parser = _robots(ctx, f"{parts.scheme}://{parts.netloc}")
    except HttpError as exc:
        return f"robots.txt could not be read: {exc}"
    return None if parser.can_fetch(AGENT, url) else "robots.txt disallows it"


def read(ctx: StepContext, url: str) -> Read:
    """Fetch url after the robots.txt check and return its text, or the reason it could not be read."""
    if reason := allowed(ctx, url):
        return Read(url, None, None, reason)
    try:
        body = ctx.http.get(url, redirects=MAX_REDIRECTS, agent=USER_AGENT).content
    except HttpError as exc:
        return Read(url, None, None, str(exc))
    if body.startswith(b"%PDF-"):
        return Read(url, None, None, "a PDF, not a web page")
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError:
        html = body.decode("cp1252", errors="replace")
    title, text = html_text(html)
    if len(text) < MIN_CHARS:
        return Read(url, title, None, f"{len(text)} characters of text, under {MIN_CHARS}")
    return Read(url, title, text[:MAX_CHARS], None, len(text) > MAX_CHARS)


def read_all(ctx: StepContext, urls: list[str]) -> list[Read]:
    """read for each url on WORKERS threads, in url order; an exception becomes that url's failure."""
    results = fan_out(lambda url: read(ctx, url), urls, WORKERS)
    return [Read(url, None, None, f"{type(r).__name__}: {r}") if isinstance(r, Exception) else r
            for url, r in zip(urls, results)]


def _last_word(name: str) -> str | None:
    words = name.split()
    return words[-1] if words else None


def windows(text: str, names: list[str], *, around: int = 1500, limit: int = 12_000) -> str:
    """The parts of text within `around` characters of a name's last word, in page order, joined by a line of …

    A text of at most `limit` characters comes back unchanged. A text with none of the names comes back as its
    first `limit` characters. Parts start and end at line ends, or inside a line far longer than the window,
    and are copied character for character; the result is cut to `limit` characters at a line end.
    """
    if len(text) <= limit:
        return text
    words = [re.escape(w) for n in names if (w := _last_word(n))]
    hits = list(re.finditer(rf"\b(?:{'|'.join(words)})\b", text, re.IGNORECASE)) if words else []
    if not hits:
        return text[:limit]
    spans: list[list[int]] = []
    for hit in hits:
        start = text.rfind("\n", 0, max(hit.start() - around, 0)) + 1
        end = text.find("\n", hit.end() + around)
        end = len(text) if end == -1 else end
        # A line far longer than the window is cut inside the line, so the name always stays in its part.
        start = hit.start() - around if hit.start() - start > 2 * around else start
        end = hit.end() + around if end - hit.end() > 2 * around else end
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    joined = "\n…\n".join(text[a:b] for a, b in spans)
    if len(joined) <= limit:
        return joined
    cut = joined.rfind("\n", 0, limit + 1)
    return joined[:cut] if cut > 0 else joined[:limit]
