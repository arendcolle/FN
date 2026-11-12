"""The HTML of each design-system part: search box, recent searches, person card, network row, filter bar and notices."""
from datetime import date
from urllib.parse import urlencode

from fn.contracts import (
    ClaimView,
    NetworkFilter,
    OrgView,
    PersonView,
    QuoteView,
    Search,
)
from fn.present import cut, days_ago, plural
from fn.web.html import Safe, h, page

NETWORK_STEP = 200


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


def recent_list(searches: list[Search], counts: dict[str, int], today: date) -> Safe:
    """The searches as RecentSearches rows; counts holds people per search."""
    return h.ul([h.li(h.a(cut(s.question, 200), href=f"/searches/{s.id}", class_="text-body"),
                      recent_meta(s, counts.get(s.id, 0), today)) for s in searches], class_="fn-recent")


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


def network_href(flt: NetworkFilter, limit: int = NETWORK_STEP, view: str = "list", path: str = "/people") -> str:
    """The URL of the network list with the filter, a limit other than the first step and the map view."""
    query = {"q": flt.text.strip(), "import": flt.import_id, "new": "1" if flt.new_only else None,
             "limit": str(limit) if limit != NETWORK_STEP else None, "view": "map" if view == "map" else None}
    text = urlencode({k: v for k, v in query.items() if v})
    return f"{path}?{text}" if text else path


def is_filtered(flt: NetworkFilter) -> bool:
    return bool(flt.text.strip() or flt.import_id or flt.new_only)


def network_row(view: PersonView, n: int) -> Safe:
    """The person's network row: name as a link, role and place, Belgian organizations, new facts and the day added.

    n is the row's place in the list, which the Show more link jumps to.
    """
    job = ", ".join(x for x in (view.role, view.employer) if x)
    day, month, year = view.added.split() if view.added else ("", "", "")
    return h.div(
        h.div(
            h.h3(h.a(view.name, href=f"/people/{view.person_id}"), class_="fn-row__name text-name"),
            h.p(" · ".join(x for x in (job, view.place or "location not found") if x), class_="fn-row__role text-body"),
            h.p(orgs_line(view.orgs, view.more_orgs), class_="fn-row__ties text-body") if view.orgs else None,
        ),
        h.div(
            h.span(plural(view.new_facts, "new fact", "new facts"), class_="fn-new text-meta-strong") if view.new_facts else None,
            h.span(f"Added {day} {month[:3]} {year}", class_="fn-row__meta text-meta") if view.added else None,
            class_="fn-row__side",
        ),
        class_="fn-row", id=f"person-{n}", data_person=view.person_id, data_place=view.lat is not None and view.lon is not None,
    )


def filter_bar(flt: NetworkFilter, total: int, not_on_map: int, action: str, import_name: str | None) -> list[Safe]:
    """The filter form with its tokens, then the count line over the whole filtered set with Clear all when filtered.

    import_name is the file name of the import the filter keeps.
    """
    tokens = [(f"From import {import_name}", flt.model_copy(update={"import_id": None}))] if flt.import_id else []
    tokens += [("New facts only", flt.model_copy(update={"new_only": False}))] if flt.new_only else []
    count = [plural(total, "person", "people")] + ([f"{not_on_map:,} not on the map"] if not_on_map else [])
    return [
        h.form(
            h.div(
                h.input(class_="fn-input text-body", type="search", name="q", value=flt.text or None,
                        placeholder="Name, place or organization", aria_label="Filter your network"),
                h.button("Filter", class_="fn-btn fn-btn--quiet text-control"),
                class_="fn-filter__box",
            ),
            h.input(type="hidden", name="import", value=flt.import_id) if flt.import_id else None,
            h.input(type="hidden", name="new", value="1") if flt.new_only else None,
            h.ul([h.li(h.span(text), h.a("Clear", href=network_href(rest), aria_label=f"Clear {text}"),
                       class_="fn-token text-meta") for text, rest in tokens],
                 class_="fn-tokens", aria_label="Active filters") if tokens else None,
            class_="fn-filter", method="get", action=action, role="search",
        ),
        h.p(h.span(" · ".join(count)), h.a("Clear all", href="/people") if is_filtered(flt) else None,
            class_="fn-count text-meta"),
    ]


def show_more(shown: int, total: int, href: str) -> Safe | None:
    """'200 of 214 shown' and 'Show 14 more', linking to href at the first new row; None when everyone is shown."""
    if shown >= total:
        return None
    more = min(NETWORK_STEP, total - shown)
    return h.div(h.span(f"{shown:,} of {total:,} shown"),
                 h.a(f"Show {more:,} more", class_="fn-btn fn-btn--quiet text-control", href=f"{href}#person-{shown + 1}"),
                 class_="fn-more text-meta")


def empty_network(home: bool) -> Safe:
    """The notice for a network with nobody in it; on Home it points up at the search box, elsewhere it links there."""
    how = "search above" if home else h.a("run a search", href="/")
    return h.div(h.h2("Your network is empty", class_="fn-notice__title text-title"),
                 h.p("Import a CSV file of people you already know, or ", how, " and add people from the results.",
                     class_="text-body"), class_="fn-notice")


def nobody_matches(flt: NetworkFilter, import_name: str | None, everyone: int) -> Safe:
    """The notice for a filter that matches nobody, naming the text and the import; everyone is the network's size."""
    text, all_people = flt.text.strip(), plural(everyone, "person", "people")
    if text and flt.import_id:
        why = (f"Nobody from import {import_name} has “{text}” in their name, place or organization. Check the "
               f"spelling, clear the import filter, or use Clear all to see all {all_people}.")
    elif text:
        why = (f"Nobody in your network has “{text}” in their name, place or organization. Check the spelling, "
               f"or use Clear all to see all {all_people}.")
    else:
        why = None
    return h.div(h.h2("Nobody matches", class_="fn-notice__title text-title"),
                 h.p(why, class_="text-body") if why else None, class_="fn-notice")
