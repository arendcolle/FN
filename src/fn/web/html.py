"""Escape-by-default HTML builders: only a Safe is written as is, and URLs are http, https or relative."""
import re
from collections.abc import Iterable
from functools import partial
from html import escape
from urllib.parse import urlsplit

VOID = {"input", "meta", "link", "br", "hr"}
URL_ATTRS = {"href", "src", "action"}
ATTR_NAME = re.compile(r"[a-z][a-z0-9-]*")
type Attr = str | bool | None


class Safe(str):
    """HTML that is already escaped; build it only in this module."""


def esc(value: object) -> Safe:
    """The value as escaped text; a Safe passes through unchanged."""
    return value if isinstance(value, Safe) else Safe(escape(str(value)))


def safe_url(url: str) -> str:
    """The url when it is http, https or relative to this site, else '#'; //host and /\\host count as another site."""
    stripped = re.sub(r"[\t\n\r]", "", url).strip()
    if stripped[:2].replace("\\", "/") == "//":
        return "#"
    try:
        return url if urlsplit(stripped).scheme in ("", "http", "https") else "#"
    except ValueError:
        return "#"


def _attrs(attrs: dict[str, Attr]) -> str:
    parts = []
    for key, value in attrs.items():
        name = key.rstrip("_").replace("_", "-")
        if not ATTR_NAME.fullmatch(name):
            raise ValueError(f"bad attribute name {key!r}")
        if value is None or value is False:
            continue
        if value is True:
            parts.append(name)
            continue
        text = safe_url(value) if name in URL_ATTRS else value
        parts.append(f'{name}="{escape(text)}"')
    return "".join(f" {p}" for p in parts)


def _children(items: Iterable[object]) -> str:
    out = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            out.append(_children(item))
        else:
            out.append(esc(item))
    return "".join(out)


def tag(name: str, /, *children: object, **attrs: Attr) -> Safe:
    """<name attrs>children</name>.

    Children may be str (escaped), Safe, None (skipped) or lists of these. In attrs a trailing
    underscore is dropped and the rest of the underscores become hyphens (class_, http_equiv);
    True writes a bare attribute and None or False drops it.
    """
    if not ATTR_NAME.fullmatch(name):
        raise ValueError(f"bad tag name {name!r}")
    if name in VOID:
        return Safe(f"<{name}{_attrs(attrs)}>")
    return Safe(f"<{name}{_attrs(attrs)}>{_children(children)}</{name}>")


class _Tags:
    def __getattr__(self, name: str):
        return partial(tag, name)


h = _Tags()


def table(headers: list[object], rows: Iterable[list[object]]) -> Safe:
    """A table with a header row; every cell is escaped like any child."""
    return h.table(
        h.tr([h.th(c) for c in headers]),
        [h.tr([h.td(c) for c in row]) for row in rows],
    )


def page(title: str, *body: object, refresh: int | None = None, extra_head: object = None) -> str:
    """A full document with the site nav; refresh reloads every that many seconds, extra_head adds head children."""
    head = h.head(
        h.meta(charset="utf-8"),
        h.title(title),
        h.meta(http_equiv="refresh", content=str(refresh)) if refresh else None,
        h.link(rel="stylesheet", href="/static/fn.css"),
        extra_head,
    )
    nav = h.p(h.a("Searches", href="/"), " ", h.a("Request errors", href="/debug/errors"))
    return "<!doctype html>" + tag("html", head, h.body(nav, body), lang="en")
