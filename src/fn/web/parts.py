"""The HTML of each design-system part: search box, recent line, person card, quote, notice and error page."""
from datetime import date

from fn.contracts import ClaimView, OrgView, PersonView, QuoteView, Search
from fn.present import days_ago, plural
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


def orgs_line(found: list[OrgView], more: int) -> list[object]:
    """The organizations as 'KU Leuven 2008–2013', joined by ' · ', then '+2 more' for the rest."""
    parts: list[object] = []
    for org in found:
        parts += [" · " if parts else None, org.org, [" ", h.span(org.years, class_="text-year")] if org.years else None]
    return parts + ([f" · +{more} more"] if more else [])


def quote(view: QuoteView) -> Safe:
    """The quote with its source as a link and its date under it."""
    return h.blockquote(view.text, h.cite(h.a(view.label, href=view.href), f", {view.date}",
                                          class_="fn-quote__cite text-small"), class_="fn-quote text-quote")


def statement(view: ClaimView) -> list[Safe]:
    """A claim from a record as a plain statement with its years, and its citation under it."""
    years = [", ", h.span(view.years, class_="text-year")] if view.years else None
    return [h.p(view.what, years, class_="fn-fact text-body"),
            h.p(h.a(view.label, href=view.href), f", {view.date}", class_="fn-cite text-small")]


def notice(search: Search, read: int) -> Safe:
    """What the page says instead of people: that the search stopped, with Try again, or that it found nobody.

    read is the number of sources the search's lanes looked at.
    """
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
    what = (f"FN read {plural(read, 'source', 'sources')} and found nobody with a Belgian tie for this question."
            if read else "FN found no sources for this question.")
    return h.div(h.h2("No people found", class_="fn-notice__title text-title"),
                 h.p(what, " A broader topic or a wider area may find more.", class_="text-body"), class_="fn-notice")


def person_card(view: PersonView) -> Safe:
    """The person's card: name, role and place, Belgian organizations, then the evidence as a quote or a statement."""
    job = ", ".join(x for x in (view.role, view.employer) if x)
    shown = view.evidence
    return h.article(
        h.h3(view.name, class_="fn-card__name text-name"),
        h.p(" · ".join(x for x in (job, view.place or "location not found") if x), class_="fn-card__role text-body"),
        h.p(orgs_line(view.orgs, view.more_orgs), class_="fn-card__ties text-body") if view.orgs else None,
        (quote(shown.quote) if shown.quote else statement(shown)) if shown else None,
        class_="fn-card", data_person=view.person_id,
    )
