"""Finding pages for a web query: Parallel Search, then Extract on each unique URL."""
import json
import logging
from dataclasses import dataclass

from fn.contracts import Chips, Considered
from fn.steps import StepContext

log = logging.getLogger("fn.websearch")
SEARCH_URL = "https://api.parallel.ai/v1/search"
EXTRACT_URL = "https://api.parallel.ai/v1/extract"
MAX_QUERIES = 5
MAX_CHARS = 12_000
FETCH_TIMEOUT_S = 20
EXTRACT_TIMEOUT_S = 90
# Dollars per count of each SKU in a response's `usage`, as live calls named them on 2026-11-03.
PRICES = {"sku_search": 0.001, "sku_extract_excerpts": 0.001}


@dataclass(frozen=True)
class Page:
    """One result page: its rank, address, title, candidate texts as (label, markdown) in reading order, and raw answers."""
    rank: int
    url: str
    title: str | None
    texts: list[tuple[str, str]]
    published: str | None
    raw: dict
    unread: str | None


@dataclass(frozen=True)
class Found:
    """The unique pages of one search, the repeated-URL rows, and a note when nothing was found."""
    pages: list[Page]
    considered: list[Considered]
    note: str | None = None


def search_body(objective: str, queries: list[str]) -> dict:
    """The Search body: the objective and at most 5 queries, which is Parallel's limit."""
    return {"objective": objective, "search_queries": queries[:MAX_QUERIES], "mode": "fast"}


def rule_queries(chips: Chips) -> list[str]:
    """One query per topic and per role chip with the place text, then one per institution; at most 5."""
    place = f" {chips.place.text}" if chips.place else ""
    queries = [f"{c.text}{place}" for c in [*chips.topics, *chips.roles]] + [c.text for c in chips.institutions]
    return queries[:MAX_QUERIES]


def extract_body(urls: list[str], objective: str) -> dict:
    """The Extract body: full content up to 12,000 characters a page and a 20 s live-fetch timeout."""
    return {"urls": urls, "objective": objective,
            "advanced_settings": {"full_content": {"max_chars_per_result": MAX_CHARS},
                                  "fetch_policy": {"timeout_seconds": FETCH_TIMEOUT_S}}}


def usage_cost(body: bytes) -> float | None:
    """Dollars for the response's `usage` at PRICES.

    None when it lists no SKU, and None with a warning when one is not in PRICES.
    """
    usage = json.loads(body).get("usage") or []
    unknown = [u["name"] for u in usage if u["name"] not in PRICES]
    if unknown:
        log.warning("Parallel usage names SKUs without a price: %s", ", ".join(unknown))
        return None
    return sum(PRICES[u["name"]] * u["count"] for u in usage) if usage else None


def find(ctx: StepContext, objective: str, queries: list[str]) -> Found:
    """Search for the queries, then Extract each unique URL once.

    No results gives a note and no Extract call. Raises MissingKey without a Parallel key, HttpError for a failed call.
    """
    results = ctx.http.post(SEARCH_URL, search_body(objective, queries), cost=usage_cost).json().get("results") or []
    if not results:
        return Found([], [], "Parallel Search returned no results; Extract not called")
    unique: dict[str, tuple[int, dict]] = {}
    considered: list[Considered] = []
    for rank, result in enumerate(results, 1):
        if result["url"] in unique:
            considered.append(Considered(person_key=result["url"], name="", stage="page", kept=False,
                                         reason=f"rank {rank}: same URL as rank {unique[result['url']][0]}"))
        else:
            unique[result["url"]] = (rank, result)
    answer = ctx.http.post(EXTRACT_URL, extract_body(list(unique), objective), timeout_s=EXTRACT_TIMEOUT_S,
                           cost=usage_cost).json()
    read = {r["url"]: r for r in answer.get("results") or []}
    failed = {e["url"]: e for e in answer.get("errors") or []}
    pages = []
    for url, (rank, result) in unique.items():
        got = read.get(url, {})
        texts = [("Extract full content", got.get("full_content") or ""),
                 ("Extract excerpts", "\n\n".join(got.get("excerpts") or [])),
                 ("Search excerpts", "\n\n".join(result.get("excerpts") or []))]
        pages.append(Page(rank=rank, url=url, title=got.get("title") or result.get("title"), texts=texts,
                          published=got.get("publish_date") or result.get("publish_date"),
                          raw={"search": result, "extract": got or failed.get(url)},
                          unread=failed[url]["error_type"] if url in failed else None))
    return Found(pages, considered)
