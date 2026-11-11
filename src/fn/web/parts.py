"""The HTML of each design-system part: search box, recent line, person card, quote, notice and error page."""
from datetime import date
from urllib.parse import urlsplit

from fn.contracts import Candidate, Claim, Org, Search, Source
from fn.present import belgian_orgs, cut, date_words, days_ago, employer_of, evidence, plural, sources_read
from fn.store import Store
from fn.web.html import Safe, h, page


def error_page(title: str, text: str) -> str:
    return page(title, h.div(h.h1(title, class_="text-title"), h.pre(text), class_="fn-page"))


def search_box(question: str = "", message: str | None = None) -> Safe:
    """The question box and its Search button; message is a refused question, shown under the box."""
    return h.form(
        h.div(
            h.textarea(question, name="question", rows="3" if len(question) > 80 else "1", class_="fn-input text-body",
                       placeholder="Flemish experts in 6G research near New York", aria_label="Question",
                       aria_invalid="true" if message else None, aria_describedby="question-error" if message else None),
            h.p(message, class_="fn-error text-small", id="question-error") if message else None,
            class_="fn-search__field",
        ),
        h.button("Search", type="submit", class_="fn-btn fn-btn--dark text-control"),
        method="post", action="/searches", class_="fn-search",
    )


def recent_meta(search: Search, people_count: int, today: date) -> Safe:
    if search.status in ("queued", "running"):
        return h.span("Searching…", class_="fn-recent__meta fn-recent__meta--running text-meta-strong")
    if search.status in ("failed", "interrupted"):
        return h.span("Failed", class_="fn-recent__meta fn-recent__meta--failed text-meta-strong")
    return h.span(f"{plural(people_count, 'person', 'people')} · {days_ago(search.created_at, today)}",
                  class_="fn-recent__meta text-meta")


def orgs_line(found: list[tuple[str, list[int]]]) -> list[object]:
    """The first three organizations as 'KU Leuven 2008–2013', joined by ' · ', then '+2 more' for the rest."""
    parts: list[object] = []
    for name, years in found[:3]:
        span = f"{years[0]}–{years[-1]}" if len(years) > 1 else "".join(map(str, years))
        parts += [" · " if parts else None, name, [" ", h.span(span, class_="text-year")] if span else None]
    return parts + ([f" · +{len(found) - 3} more"] if len(found) > 3 else [])


def quote_block(claim: Claim, source: Source) -> Safe:
    """The claim's quote in quote marks, cut at 240 characters, with its source and date under it."""
    text = " ".join(claim.quote.split()).replace('"', "'").replace("“", "‘").replace("”", "’")
    label = source.title or urlsplit(source.url).hostname or source.url
    return h.blockquote(
        f"“{cut(text, 240)}”",
        h.cite(h.a(label, href=f"/sources/{claim.source_id}?claim={claim.id}#quote"), f", {date_words(claim)}",
               class_="fn-quote__cite text-small"),
        class_="fn-quote text-quote",
    )


def notice(store: Store, search: Search) -> Safe:
    """What the page says instead of people: that the search stopped, with Try again, or that it found nobody."""
    if search.status in ("failed", "interrupted"):
        why = "FN was restarted while this search ran" if search.status == "interrupted" else (
            "FN ran into a problem during this search")
        return h.div(
            h.h2("This search stopped", class_="fn-notice__title text-title"),
            h.p(f"{why}, so nothing it found is shown.", class_="text-body"),
            h.form(h.input(type="hidden", name="question", value=search.question),
                   h.button("Try again", type="submit", class_="fn-btn fn-btn--dark text-control"),
                   method="post", action="/searches"),
            class_="fn-notice fn-notice--failed",
        )
    read = sources_read(store, search)
    what = (f"FN read {plural(read, 'source', 'sources')} and found nobody with a Belgian tie for this question."
            if read else "FN found no sources for this question.")
    return h.div(h.h2("No people found", class_="fn-notice__title text-title"),
                 h.p(what, " A broader topic or a wider area may find more.", class_="text-body"), class_="fn-notice")


def person_card(candidate: Candidate, persons: dict, by_person: dict[str, list[Claim]], places: dict[str, Claim],
                facts: dict[str, Org], sources: dict[str, Source]) -> Safe:
    claims = [c for p in candidate.person_ids for c in by_person.get(p, [])]
    place = next((places[p].value for p in candidate.person_ids if p in places), "location not found")
    found, quote = belgian_orgs(claims, facts), evidence(candidate, claims, facts)
    return h.article(
        h.h3(persons[candidate.person_id].display_name, class_="fn-card__name text-name"),
        h.p(" · ".join(x for x in (employer_of(claims), place) if x), class_="fn-card__role text-body"),
        h.p(orgs_line(found), class_="fn-card__ties text-body") if found else None,
        quote_block(quote, sources[quote.source_id]) if quote else None,
        class_="fn-card", data_person=candidate.person_id,
    )
