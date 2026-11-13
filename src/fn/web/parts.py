"""The HTML of each design-system part: search box, recent searches, person card, network row, filter bar and notices."""
from datetime import date
from urllib.parse import parse_qsl, urlencode

from fn.contracts import (
    BackLink,
    CardView,
    ClaimView,
    ContactView,
    FactGroup,
    FoldView,
    ImportPreview,
    ImportRow,
    LastView,
    ListPlace,
    NetworkFilter,
    OrgView,
    PersonView,
    ProfileView,
    QuoteView,
    Search,
    SummaryRow,
    name_key,
)
from fn.present import (
    FIELDS,
    FOLD_SHOWN,
    RESULTS_STEP,
    UNKNOWN_DATE,
    cut,
    days_ago,
    plural,
)
from fn.store import fold
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


def quote(view: QuoteView, back: str | None = None) -> Safe:
    """The quote with its source as a link and its date under it; back is the page the source page returns to."""
    return h.blockquote(view.text, h.cite(h.a(view.label, href=with_back(view.href, back)), f", {view.date}",
                                          class_="fn-quote__cite text-small"), class_="fn-quote text-quote")


def statement(view: ClaimView, back: str | None = None) -> list[Safe]:
    """A claim from a record as a plain statement with its years, and its citation under it."""
    years = [", ", h.span(view.years, class_="text-year")] if view.years else None
    return [h.p(view.what, years, class_="fn-fact text-body"),
            h.p(h.a(view.label, href=with_back(view.href, back)), f", {view.date}", class_="fn-cite text-small")]


def notice(search: Search, read: int) -> Safe:
    """What the page says instead of people: that the search stopped before it found anyone, with Try again, or that
    it found nobody.

    read is the number of sources the search's lanes looked at.
    """
    if search.status in ("failed", "interrupted"):
        return h.div(
            h.h2("This search stopped", class_="fn-notice__title text-title"),
            h.p("FN ran into a problem before it found anyone. Your question is kept, so Try again runs it once more.",
                class_="text-body"),
            h.form(h.input(type="hidden", name="question", value=search.question),
                   h.button("Try again", type="submit", class_="fn-btn fn-btn--dark text-control"),
                   method="post", action="/searches"),
            class_="fn-notice fn-notice--failed",
        )
    what = (f"FN read {plural(read, 'source', 'sources')} and found nobody with a Belgian tie for this question."
            if read else "FN found no sources for this question.")
    return h.div(h.h2("No people found", class_="fn-notice__title text-title"),
                 h.p(what, " A broader topic or a wider area may find more.", class_="text-body"), class_="fn-notice")


def status_line(people: int) -> Safe:
    """The StatusLine while a search runs: 'Searching…', then how many people it found so far."""
    words = f"Searching… {plural(people, 'person', 'people')} so far" if people else "Searching…"
    return h.p(h.span(words), h.span(class_="fn-status__bar"), class_="fn-status text-strong")


def status_note(text: str, button: str, question: str) -> Safe:
    """The StatusLine note over the people of a search that ended with a problem; the button posts the question again."""
    return h.div(
        h.p(text, class_="text-strong"),
        h.form(h.input(type="hidden", name="question", value=question),
               h.button(button, type="submit", class_="fn-btn fn-btn--quiet text-control"),
               method="post", action="/searches"),
        class_="fn-status-note",
    )


def person_href(person_id: str, search_id: str | None, shown: int, key: str | None, origin: str) -> str:
    """The Person page's URL from a search's card: the search, the shown count when not 20, the card and the origin."""
    query = {"search": search_id, "shown": str(shown) if search_id and shown != RESULTS_STEP else None,
             "card": key if search_id else None, "from": origin}
    return f"/people/{person_id}?{urlencode({k: v for k, v in query.items() if v})}"


def with_back(href: str, back: str | None) -> str:
    """The href with back=<page> added to its query, before any anchor; the href itself when back is None."""
    if not back:
        return href
    target, mark, anchor = href.partition("#")
    return f"{target}{'&' if '?' in target else '?'}{urlencode({'back': back})}{mark}{anchor}"


def person_card(view: PersonView, search_id: str | None = None, acts: object = None, card_id: str | None = None,
                why: str | None = None, shown: int = RESULTS_STEP, back: str | None = None) -> Safe:
    """The person's card: the name linking to their page, role and place, Belgian organizations, the why line, the
    evidence and the combined line.

    search_id is the search the card shows on and shown its shown count, which the Person page links back to; acts
    follow the combined line; back is the page the card's source links return to.
    """
    evidence = view.evidence
    key = card_id.removeprefix("card-") if card_id else None
    href = person_href(view.person_id, search_id, shown, key, "card")
    combined = h.p(h.a(f"Combined from {view.records} records", href=f"{href}#sources"),
                   class_="fn-card__combined text-small") if view.records > 1 else None
    return h.article(
        h.h3(h.a(view.name, href=href), class_="fn-card__name text-name"),
        h.p(role_line(view), class_="fn-card__role text-body") if role_line(view) else None,
        h.p(orgs_line(view.orgs, view.more_orgs), class_="fn-card__ties text-body") if view.orgs else None,
        h.p(why, class_="fn-card__why text-small") if why else None,
        (quote(evidence.quote, back) if evidence.quote else statement(evidence, back)) if evidence else None,
        combined,
        acts,
        class_="fn-card", id=card_id, data_person=view.person_id,
    )


def results_href(search_id: str, shown: int, skipped: bool, view: str = "list") -> str:
    """The URL of the results page with a shown count other than the first step, the skipped people and the view."""
    query = urlencode({k: v for k, v in (("shown", str(shown) if shown != RESULTS_STEP else None),
                                         ("skipped", "1" if skipped else None)) if v})
    path = f"/searches/{search_id}" + ("/map" if view == "map" else "")
    return f"{path}?{query}" if query else path


def match_line(match: PersonView, back: str | None = None) -> Safe:
    return h.p("Same name as ", h.a(match.name, href=with_back(f"/people/{match.person_id}", back)), " in your network",
               class_="fn-card__match text-body")


def result_card(card: CardView, search_id: str, here: str, shown: int = RESULTS_STEP) -> Safe:
    """The card in its state: Add and Skip, the same-name buttons, the added line with its note, or the skipped line.

    here is the results page URL the forms return to and shown its shown count; a network card has no buttons, an
    Undo shows when given.
    """
    view, card_id = card.person, f"card-{card.key}"
    anchored, action = f"{here}#{card_id}", f"/searches/{search_id}/people/{card.key}"
    if card.state == "skipped":
        words = f"Skipped {view.name}"
        line = (undo_form(card.undo_event, words, "fn-skipline text-body", anchored) if card.undo_event
                else h.p(words, class_="fn-skipline text-body"))
        return h.article(line, class_="fn-card fn-card--skipped", id=card_id)
    quiet = "fn-btn fn-btn--quiet text-control"
    skip = post_form(f"{action}/skip", "Skip", quiet, here)
    acts = None
    if card.state == "new":
        acts = h.div(post_form(f"{action}/add", "Add", "fn-btn fn-btn--add text-control", here), skip,
                     class_="fn-card__acts")
    elif card.state == "name_match":
        acts = [match_line(card.match, anchored),
                h.div(post_form(f"{action}/same", "Same person", quiet, here, match=card.match.person_id),
                      post_form(f"{action}/new", "Add as new", quiet, here, match=card.match.person_id), skip,
                      class_="fn-card__acts")]
    elif card.state == "added":
        note = None
        if card.note and card.note_href:
            note = [h.span("·", class_="text-body"), h.a(card.note, class_="text-body", href=with_back(card.note_href, anchored))]
        elif card.note:
            note = h.span(card.note, class_="text-body")
        done = [h.span("Added to your network", class_="fn-done text-strong"), note]
        acts = [match_line(card.match, anchored) if card.match else None,
                undo_form(card.undo_event, done, "fn-card__acts", anchored) if card.undo_event
                else h.div(done, class_="fn-card__acts")]
    return person_card(view, search_id, acts, card_id, card.why, shown, anchored)


def network_href(flt: NetworkFilter, limit: int = NETWORK_STEP, view: str = "list", path: str = "/people") -> str:
    """The URL of the network list with the filter, a limit other than the first step and the map view."""
    query = {"q": flt.text.strip(), "import": flt.import_id, "new": "1" if flt.new_only else None,
             "limit": str(limit) if limit != NETWORK_STEP else None, "view": "map" if view == "map" else None}
    text = urlencode({k: v for k, v in query.items() if v})
    return f"{path}?{text}" if text else path


def is_filtered(flt: NetworkFilter) -> bool:
    return bool(flt.text.strip() or flt.import_id or flt.new_only)


def network_row(view: PersonView, n: int, back: str) -> Safe:
    """The person's network row: name as a link, role and place, Belgian organizations, new facts and the day added.

    n is the row's place in the list, which the Show more link jumps to; back is the list's URL.
    """
    day, month, year = view.added.split() if view.added else ("", "", "")
    return h.div(
        h.div(
            h.h3(h.a(view.name, href=with_back(f"/people/{view.person_id}?from=row", f"{back}#person-{n}")),
                 class_="fn-row__name text-name"),
            h.p(role_line(view), class_="fn-row__role text-body") if role_line(view) else None,
            h.p(orgs_line(view.orgs, view.more_orgs), class_="fn-row__ties text-body") if view.orgs else None,
        ),
        h.div(
            h.span(plural(view.new_facts, "new fact", "new facts"), class_="fn-new text-meta-strong") if view.new_facts else None,
            h.span(f"Added {day} {month[:3]} {year}", class_="fn-row__meta text-meta") if view.added else None,
            class_="fn-row__side",
        ),
        class_="fn-row", id=f"person-{n}", data_person=view.person_id, data_place=view.lat is not None and view.lon is not None,
    )


def joined(items: list[object], sep: str = " · ") -> list[object]:
    return [part for n, item in enumerate(items) for part in ([sep] if n else []) + [item]]


def count_links(flt: NetworkFilter, total: int, new_facts: int) -> list[Safe]:
    """The count line's links: the people with new facts, which turns New facts only on, and the export."""
    links = []
    if new_facts and not flt.new_only:
        links.append(h.a(f"{new_facts:,} with new facts", href=network_href(flt.model_copy(update={"new_only": True}))))
    if total:
        links.append(h.a(f"Export these {total:,}" if is_filtered(flt) else "Export",
                         href=network_href(flt, path="/people/export.csv")))
    return links


def filter_bar(flt: NetworkFilter, total: int, not_on_map: int, action: str, import_name: str | None,
               new_facts: int = 0) -> list[Safe]:
    """The filter form with its tokens, then the count line over the whole filtered set with Clear all when filtered.

    import_name is the file name of the import the filter keeps; new_facts counts the people with a new fact.
    """
    tokens = [(f"From import {import_name}", flt.model_copy(update={"import_id": None}))] if flt.import_id else []
    tokens += [("New facts only", flt.model_copy(update={"new_only": False}))] if flt.new_only else []
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
        count_line(total, not_on_map, count_links(flt, total, new_facts),
                   h.a("Clear all", href="/people") if is_filtered(flt) else None),
    ]


def count_line(total: int, not_on_map: int, links: list[Safe], clear: Safe | None = None) -> Safe:
    """'214 people · 12 not on the map' then the links, and clear at the right."""
    count = [plural(total, "person", "people")] + ([f"{not_on_map:,} not on the map"] if not_on_map else [])
    return h.p(h.span(joined([" · ".join(count), *links])), clear, class_="fn-count text-meta")


def show_more(shown: int, total: int, href: str, step: int = NETWORK_STEP, anchor: str | None = None) -> Safe | None:
    """'200 of 214 shown' and 'Show 14 more', linking to href at the first new item; None when everyone is shown.

    anchor is that item's id, person-<n> when not given.
    """
    if shown >= total:
        return None
    more = min(step, total - shown)
    return h.div(h.span(f"{shown:,} of {total:,} shown"),
                 h.a(f"Show {more:,} more", class_="fn-btn fn-btn--quiet text-control",
                     href=f"{href}#{anchor or f'person-{shown + 1}'}"),
                 class_="fn-more text-meta")


def skipped_line(count: int, shown: bool, href: str) -> Safe | None:
    """'3 skipped people hidden' with Show, or '3 skipped people shown' with Hide; None when nobody was skipped."""
    if not count:
        return None
    words = plural(count, "skipped person", "skipped people") + (" shown" if shown else " hidden")
    return h.p(h.span(words), h.a("Hide" if shown else "Show", class_="fn-link", href=href), class_="fn-hidden text-meta")


def empty_network(home: bool) -> Safe:
    """The notice for a network with nobody in it; on Home it points up at the search box, elsewhere it links there."""
    how = "search above" if home else h.a("run a search", href="/")
    return h.div(h.h2("Your network is empty", class_="fn-notice__title text-title"),
                 h.p("Import a CSV file of people you already know, or ", how, " and add people from the results.",
                     class_="text-body"),
                 h.div(h.a("Import", class_="fn-btn fn-btn--quiet text-control", href="/imports/new"),
                       class_="fn-notice__acts"), class_="fn-notice")


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


FACT_STEP = 3
MATCH_NOTE = "These have the same name, but nothing in FN links them to this person for sure."


def role_line(view: PersonView) -> str:
    """Role and employer, then the place after ' · ', as the card, the network row and the profile say it."""
    job = ", ".join(x for x in (view.role, view.employer) if x)
    return " · ".join(x for x in (job, view.place) if x)


def post_form(action: str, label: str, button_class: str, here: str, **fields: str) -> Safe:
    """A plain POST form with one button, the fields and the page to go back to."""
    return h.form([h.input(type="hidden", name=k, value=v) for k, v in fields.items()],
                  h.input(type="hidden", name="next", value=here),
                  h.button(label, type="submit", class_=button_class), method="post", action=action)


def undo_form(last: LastView, text: object, form_class: str, here: str, button_class: str = "fn-link text-body") -> Safe:
    """The text of what a decision did, then its Undo, as one POST form with form_class."""
    return h.form(text, " ", h.input(type="hidden", name="next", value=here),
                  h.button("Undo", type="submit", class_=button_class),
                  method="post", action=f"/events/{last.event_id}/undo", class_=form_class)


def profile_banner(view: ProfileView, refused: bool, here: str) -> Safe | None:
    """The Banner of a refused undo, else the one after Remove with its Undo, else None."""
    if refused:
        return h.p(h.span(f"This could not be undone, because {view.person.name} changed since."),
                   class_="fn-banner fn-banner--failed text-body", role="status")
    if view.last and view.last.kind == "remove":
        return h.form(h.span(view.last.words), h.input(type="hidden", name="next", value=here),
                      h.button("Undo", type="submit", class_="fn-link text-body"),
                      method="post", action=f"/events/{view.last.event_id}/undo", class_="fn-banner text-body",
                      role="status")
    return None


def profile_state(view: ProfileView, here: str, route: str | None = None) -> Safe | list[Safe]:
    """The head's network state: since when with Remove from network, the done line of Add or Skip, else the buttons.

    With a route (a card's /searches/<id>/people/<key>) the buttons decide for every record on the card.
    """
    person, last, pid = view.person, view.last, view.person.person_id
    if last and last.kind in ("add", "skip"):
        done = h.span(last.words, class_="fn-done text-strong" if last.kind == "add" else "text-strong")
        return undo_form(last, done, "fn-profile__acts", here)
    if person.status == "in_list":
        since = f"In your network since {person.added}" if person.added else "In your network"
        return h.form(h.span(since), h.input(type="hidden", name="next", value=here),
                      h.button("Remove from network", type="submit", class_="fn-link text-meta"),
                      method="post", action=f"/people/{pid}/remove", class_="fn-profile__status text-meta")
    quiet = "fn-btn fn-btn--quiet text-control"
    skip = post_form(f"{route or f'/people/{pid}'}/skip", "Skip", quiet, here)
    if match := view.name_match:
        theirs, query = f"/people/{match.person_id}", here.partition("?")[2]
        line = h.p("Same name as ", h.a(match.name, href=with_back(theirs, here)), " in your network",
                   class_="fn-card__match text-body")
        if route:
            same = post_form(f"{route}/same", "Same person", quiet, here, match=match.person_id)
            new = post_form(f"{route}/new", "Add as new", quiet, here, match=match.person_id)
        else:
            same = post_form(f"{theirs}/merge", "Same person", quiet, f"{theirs}?{query}" if query else theirs, other=pid)
            new = post_form(f"/people/{pid}/add", "Add as new", quiet, here, not_same=match.person_id)
        return [line, h.div(same, new, skip, class_="fn-profile__acts")]
    return h.div(post_form(f"{route or f'/people/{pid}'}/add", "Add", "fn-btn fn-btn--add text-control", here), skip,
                 class_="fn-profile__acts")


def back_line(back: BackLink | None, place: ListPlace | None) -> list[Safe]:
    """The BackLink part: the back link, and under it the walk line when the page was opened from a search."""
    if back is None:
        return []
    lines = [h.p(h.a(back.label, href=back.href), class_="fn-back text-meta")]
    if place:
        steps = [h.a("Previous", href=place.previous, rel="prev") if place.previous else None,
                 h.a("Next", href=place.next, rel="next") if place.next else None]
        lines.append(h.p(joined([h.span(f"{place.position:,} of {place.total:,}"), *filter(None, steps)]),
                         class_="fn-walk text-meta"))
    return lines


def profile_head(view: ProfileView, back: BackLink | None, place: ListPlace | None, here: str,
                 route: str | None = None) -> list[Safe]:
    """The back link and walk line, then the name, the role line, the combined line and the network state."""
    return [*back_line(back, place),
            h.div(h.h1(view.person.name, class_="fn-profile__name text-name"),
                  h.p(role_line(view.person), class_="fn-profile__role text-body") if role_line(view.person) else None,
                  h.p(h.a(f"Combined from {view.records} records", href="#sources"), class_="fn-profile__combined text-small")
                  if view.records > 1 else None,
                  profile_state(view, here, route),
                  class_="fn-profile__head")]


def contact_edit(view: ProfileView, contact: ContactView, here: str, error: str | None, typed: str | None) -> Safe:
    """The contact Field in place: the value, Save and Cancel, and the refused value's error under it."""
    label = FIELDS[contact.kind]
    replaces = [h.input(type="hidden", name="replaces", value=contact.claim.claim_id)] if contact.claim else None
    return h.dd(h.form(
        h.div(h.input(class_="fn-input text-body", type="email" if contact.kind == "email" else "tel", name="value",
                      value=contact.value if typed is None else typed, aria_label=label,
                      aria_invalid="true" if error else None, aria_describedby="contact-error" if error else None,
                      autofocus=bool(error)),
              h.p(error, class_="fn-error text-small", id="contact-error") if error else None),
        h.input(type="hidden", name="kind", value=contact.kind), replaces,
        h.input(type="hidden", name="next", value=here),
        h.button("Save", type="submit", class_="fn-btn fn-btn--dark text-control"),
        h.a("Cancel", href=here, class_="fn-link text-body"),
        method="post", action=f"/people/{view.person.person_id}/contact", class_="fn-inline-form",
    ), class_="fn-contact__edit")


def contact_block(view: ProfileView, here: str, edit: str | None, error: str | None = None,
                  typed: str | None = None) -> Safe:
    """Email and phone, each with its value and where it came from, or 'Not provided', with Edit; edit opens one."""
    rows = []
    for contact in view.contact:
        label, claim, last = FIELDS[contact.kind], contact.claim, view.last
        if edit == contact.kind:
            rows.append(h.div(h.dt(label, class_="text-label"), contact_edit(view, contact, here, error, typed),
                              class_="fn-contact__row"))
            continue
        if claim:
            scheme = "mailto" if contact.kind == "email" else "tel"
            cite = [h.a(claim.label, href=with_back(claim.href, here)), f", {claim.date}"]
            saved = last and last.kind == "edit_contact" and last.claim_id == claim.claim_id
            shown = [h.p(h.a(contact.value, href=f"{scheme}:{contact.value}"), class_="fn-contact__value text-body"),
                     undo_form(last, [cite, " · Saved"], "fn-cite text-small", here, "fn-link text-small") if saved
                     else h.p(cite, class_="fn-cite text-small")]
        else:
            shown = h.p("Not provided", class_="fn-contact__none text-body")
        edit_href = f"{here}{'&' if '?' in here else '?'}edit={contact.kind}"
        rows.append(h.div(h.dt(label, class_="text-label"), h.dd(shown), h.dd(h.a("Edit", class_="text-meta", href=edit_href)),
                          class_="fn-contact__row"))
    return h.section(h.h2("Contact", class_="fn-section text-title"), h.dl(rows, class_="fn-contact"),
                     class_="fn-profile__section", id="contact")


def summary_list(rows: list[SummaryRow]) -> Safe | None:
    """The SummaryList under the head: each row's key and value with its years; contact values link, none reads 'Not found'."""
    def value(row: SummaryRow) -> Safe:
        if row.key == "Contact":
            if not row.claim_ids:
                return h.dd(row.value, class_="fn-contact__none text-body")
            return h.dd(joined([h.a(x, href=f"{'mailto' if '@' in x else 'tel'}:{x}") for x in row.value.split(" · ")]),
                        class_="text-body")
        return h.dd(row.value, [", ", h.span(row.years, class_="text-year")] if row.years else None, class_="text-body")

    return h.dl([h.div(h.dt(row.key, class_="text-label"), value(row), class_="fn-summary-list__row") for row in rows],
                class_="fn-summary-list") if rows else None


def cite_line(view: ClaimView, back: str) -> Safe:
    """The page title or record label as a link to the source page, the date when known, and Original page."""
    when = f", {view.date}" if view.date != UNKNOWN_DATE else None
    original = [" · ", h.a("Original page", href=view.url)] if view.url else None
    return h.p(h.a(view.label, href=with_back(view.href, back)), when, original, class_="fn-cite text-small")


def claim_line(view: ClaimView, last: LastView | None, here: str) -> Safe:
    """A fact as the Claim part: New, the fact and its years, the source name that opens its proof, and Not correct.

    The fact the latest decision removed shrinks to one line with Undo.
    """
    anchor = f"claim-{view.claim_id}"
    years = [", ", h.span(view.years, class_="text-year")] if view.years else None
    if last and last.kind == "reject_claim" and last.claim_id == view.claim_id:
        return h.div(undo_form(last, [h.span(view.what, years), h.span("· Removed")], "fn-skipline text-body",
                               f"{here}#{anchor}"), class_="fn-claim fn-claim--removed", id=anchor)
    new = h.span("New", class_="fn-new text-label") if view.is_new else None
    back = f"{here}#{anchor}"
    proof = h.details(
        h.summary(view.source, class_="fn-proof__name text-small", aria_label=f"Source for {view.what}: {view.source}"),
        h.div(h.blockquote(view.quote.text, class_="fn-quote text-quote") if view.quote else None,
              h.p(f"Years: {view.all_years}", class_="fn-cite text-small") if view.all_years else None,
              cite_line(view, back), class_="fn-proof__body"),
        class_="fn-proof")
    head = h.div(h.div(h.span(new, view.what, years, class_="fn-claim__what text-body"), " ", proof,
                       class_="fn-claim__line"),
                 post_form(f"/claims/{view.claim_id}/reject", "Not correct", "fn-link text-meta", back,
                           **({"also": view.joined_claim_id} if view.joined_claim_id else {})),
                 class_="fn-claim__head")
    return h.div(head, class_="fn-claim", id=anchor)


def fold_line(fold: FoldView) -> Safe:
    """The last Work line, Also named at n other organizations: a proof that lists them, and no Not correct."""
    what = f"Also named at {plural(fold.count, 'other organization', 'other organizations')}"
    listed = " · ".join(fold.orgs[:FOLD_SHOWN]) + (" · …" if len(fold.orgs) > FOLD_SHOWN else "")
    proof = h.details(
        h.summary(fold.source, class_="fn-proof__name text-small", aria_label=f"Source for {what}: {fold.source}"),
        h.div(h.p(listed, class_="fn-cite text-small"), class_="fn-proof__body"), class_="fn-proof")
    return h.div(h.div(h.div(h.span(what, class_="fn-claim__what text-body"), " ", proof, class_="fn-claim__line"),
                       class_="fn-claim__head"), class_="fn-claim", id="work-fold")


def with_all(here: str, anchor: str) -> str:
    """The page's path and query with all=<anchor> set in place of any all."""
    path, _, query = here.partition("?")
    return f"{path}?{urlencode([*(q for q in parse_qsl(query) if q[0] != 'all'), ('all', anchor)])}"


def head_place(group: FactGroup, view: ProfileView) -> bool:
    """Whether the group's only line is the place the head shows."""
    place = view.person.place
    return bool(place and len(group.facts) == 1 and fold(group.facts[0].what) == fold(f"Lives in {place}"))


def fact_groups(view: ProfileView, here: str, every: str | None) -> list[Safe]:
    """Each fact section under its heading, its first three facts unless every is 1 or the section's id, then Show n more.

    A section is left out when all its lines stand in the summary, and Places when its only line is the head's place.
    """
    covered = {i for row in view.summary for i in row.claim_ids}
    out = []
    for group in view.facts:
        anchor = group.title.split()[0].lower()
        if (all(c.claim_id in covered for c in group.facts) and not group.fold) or (
                group.title == "Places" and head_place(group, view)):
            continue
        items = [claim_line(c, view.last, here) for c in group.facts] + ([fold_line(group.fold)] if group.fold else [])
        shown = items if every in ("1", anchor) else items[:FACT_STEP]
        more = len(items) - len(shown)
        out.append(h.section(
            h.h2(group.title, class_="fn-section text-title"), h.div(shown),
            h.p(h.a(f"Show {more:,} more", class_="fn-link", href=f"{with_all(here, anchor)}#{anchor}"),
                class_="fn-more text-meta") if more else None,
            class_="fn-profile__section", id=anchor))
    return out


def done_line(last: LastView, here: str) -> Safe:
    """A done line whose Undo returns to here, anchor included."""
    return h.div(h.div(undo_form(last, last.words, "text-body", here), class_="fn-line__main"), class_="fn-line fn-line--done")


def found_as_block(view: ProfileView, here: str) -> Safe | None:
    """Sources: each record's source with its fact count and Not this person where the record can be separated."""
    pid, last = view.person.person_id, view.last
    rows = [h.div(
        h.div(h.p(h.a(r.label, href=with_back(r.href, here)), " ",
                  h.span(f"· {plural(r.facts, 'fact', 'facts') if r.facts else 'no facts'}", class_="fn-line__meta text-meta"),
                  class_="text-body"),
              class_="fn-line__main"),
        post_form(f"/people/{pid}/not-same", "Not this person", "fn-link text-meta", f"{here}#sources", other=r.record_id)
        if r.separate else None,
        class_="fn-line") for r in view.found_as]
    if last and last.separated:
        rows.append(done_line(last, f"{here}#sources"))
    return h.section(h.h2("Sources", class_="fn-section text-title"), h.div(rows, class_="fn-lines"),
                     class_="fn-profile__section", id="sources") if rows else None


def possible_line(match: PersonView, person_id: str, here: str) -> Safe:
    """A same-name person with enough to decide, and Same person and Different person."""
    quiet, shown, here = "fn-btn fn-btn--quiet text-control", match.evidence, f"{here}#matches"
    return h.div(
        h.div(h.p(h.a(match.name, href=with_back(f"/people/{match.person_id}", here)), class_="text-popup"),
              h.p(role_line(match), class_="text-body"),
              h.p(orgs_line(match.orgs, match.more_orgs), class_="fn-line__meta text-body") if match.orgs else None,
              h.p(h.a(shown.label, href=with_back(shown.href, here)), f", {shown.date}", class_="fn-cite text-small") if shown else None,
              class_="fn-line__main"),
        h.div(post_form(f"/people/{person_id}/merge", "Same person", quiet, here, other=match.person_id),
              post_form(f"/people/{person_id}/not-same", "Different person", quiet, here, other=match.person_id),
              class_="fn-line__acts"),
        class_="fn-line",
    )


def possible_block(view: ProfileView, here: str) -> Safe | None:
    """Possible matches under their note, and the done line of the latest merge or different-person decision."""
    last = view.last
    rows = [possible_line(m, view.person.person_id, here) for m in view.possible]
    if last and (last.kind == "merge" or (last.kind == "not_same" and not last.separated)):
        rows.append(done_line(last, f"{here}#matches"))
    if not rows:
        return None
    return h.section(h.h2("Possible matches", class_="fn-section text-title"),
                     h.p(MATCH_NOTE, class_="fn-note text-small"), h.div(rows, class_="fn-lines"),
                     class_="fn-profile__section", id="matches")


def banner(text: str, link: tuple[str, str] | None = None) -> Safe:
    """One line on what an action changed elsewhere, with the next step as a link; link is (label, href)."""
    return h.p(h.span(text), h.a(link[0], href=link[1]) if link else None, class_="fn-banner text-body", role="status")


IMPORT_NOTES = {
    "name": "The person's full name.",
    "email": "A contact detail. FN also recognizes the person by it in a later import.",
    "phone": "A contact detail.",
    "organization": "Where the person works.",
    "role": "The person's job title.",
    "city": "With state and country, puts the person on the map.",
    "state": "The US state, or the province or region elsewhere.",
    "country": "The country of the city.",
    "linkedin_url": "The address of their LinkedIn profile. FN recognizes the person by it in later imports and searches.",
    "orcid": "Their ORCID iD. FN recognizes the person by it in later imports and searches.",
}
OUTCOME_WORDS = {"new": "New", "update": "In your network", "name_match": "Same name"}
IMPORT_ROWS_SHOWN = 200


def data_table(label: str, headers: list[str], rows: list[list[tuple[str, str | None]]]) -> Safe:
    """A DataTable in its scrolling region; each cell is its text and an extra class, such as fn-table__failed."""
    return h.div(
        h.table(h.thead(h.tr([h.th(c, scope="col", class_="text-label") for c in headers])),
                h.tbody([h.tr([h.td(text, class_=" ".join(filter(None, ["text-meta", extra]))) for text, extra in row])
                         for row in rows]),
                class_="fn-table"),
        class_="fn-table-wrap", role="region", aria_label=label, tabindex="0",
    )


def upload_form(error: str | None) -> Safe:
    """The CSV file Field with its hint and Upload; error is the sentence under the field."""
    return h.form(
        h.div(
            h.label("CSV file", class_="fn-field__label text-strong", for_="file"),
            h.p("The first row holds the column names. Commas and semicolons both work.", class_="fn-field__hint text-small",
                id="file-hint"),
            h.input(class_="fn-input text-body", id="file", name="file", type="file", accept=".csv,text/csv",
                    aria_describedby="file-hint file-error" if error else "file-hint",
                    aria_invalid="true" if error else None, autofocus=bool(error)),
            h.p(error, class_="fn-error text-small", id="file-error") if error else None,
            class_="fn-field",
        ),
        h.button("Upload", class_="fn-btn fn-btn--dark text-control"),
        method="post", action="/imports", enctype="multipart/form-data",
    )


def import_columns(columns: tuple[str, ...]) -> list[Safe]:
    """The heading, note and table of the columns FN reads."""
    return [
        h.h2("Columns FN reads", class_="fn-section text-label"),
        h.p("Name your columns like this, in any order. FN ignores other columns, and a blank cell changes nothing for "
            "someone already in your network.", class_="fn-note text-small"),
        data_table("Columns FN reads", ["Column", "Required", "What FN does with it"],
                   [[(c, None), ("Yes" if c == "name" else "No", None), (IMPORT_NOTES[c], "fn-table__text")]
                    for c in columns]),
    ]


def importable(preview: ImportPreview) -> int:
    return sum(preview.counts.get(k, 0) for k in OUTCOME_WORDS)


def import_counts(preview: ImportPreview) -> Safe:
    """The counts in words, a count of 0 left out."""
    counts = preview.counts
    lines = [plural(counts.get("new", 0), "new person", "new people"),
             f"{counts.get('update', 0):,} already in your network",
             f"{counts.get('name_match', 0):,} with the same name as someone in your network",
             plural(counts.get("skipped", 0), "row skipped", "rows skipped")]
    shown = [line for line, n in zip(lines, [counts.get(k, 0) for k in ("new", "update", "name_match", "skipped")]) if n]
    return h.ul([h.li(line) for line in shown], class_="fn-summary__counts text-body")


def import_notes(preview: ImportPreview) -> list[Safe]:
    """What FN does with rows already in the network, why rows are skipped, the ignored columns and row notes."""
    notes = []
    if updates := preview.counts.get("update", 0):
        notes.append(f"FN adds what is new in the {plural(updates, 'row', 'rows')} already in your network to their "
                     "profiles.")
    notes += [r.message for r in preview.rows if r.outcome == "skipped" and r.message]
    if ignored := preview.ignored_columns:
        notes.append(f"FN ignores {plural(len(ignored), 'column', 'columns')}: {', '.join(ignored)}.")
    lines = [h.p(" ".join(notes), class_="fn-note text-small")] if notes else []
    return lines + [h.p(r.message if r.message.startswith("Row ") else f"Row {r.n}. {r.message}", class_="fn-note text-small")
                    for r in preview.rows if r.outcome != "skipped" and r.message]


def facts_line(*parts: str | None) -> str:
    return " · ".join(p for p in parts if p)


def name_match(row: ImportRow, view: PersonView) -> Safe:
    """One name match: the unticked box 'Row 7. Same as <name>?' and the file's facts beside the network person's."""
    cells = row.cells
    file_job = ", ".join(cells[c] for c in ("role", "organization") if c in cells)
    place = ", ".join(cells[c] for c in ("city", "state", "country") if c in cells)
    job = ", ".join(x for x in (view.role, view.employer) if x)
    return h.div(h.div(
        h.p(h.input(type="checkbox", id=f"m{row.n}", name="merge", value=str(row.n)),
            h.label(f"Row {row.n}. Same as ", h.a(view.name, href=f"/people/{view.person_id}"), "?", class_="text-body",
                    for_=f"m{row.n}"), class_="fn-check"),
        h.p("In the file: ", facts_line(file_job, place, cells.get("email")),
            class_="fn-check__detail fn-line__meta text-small"),
        h.p("In your network: ", facts_line(job, view.place, f"added {view.added}" if view.added else None),
            class_="fn-check__detail fn-line__meta text-small"),
        class_="fn-line__main"), class_="fn-line")


def name_matches(rows: list[ImportRow], views: dict[str, PersonView]) -> list[Safe]:
    """The name matches under their heading, with the header box that ticks them all."""
    shown = [name_match(r, views[r.person_id]) for r in rows if r.outcome == "name_match" and r.person_id in views]
    if not shown:
        return []
    return [
        h.h2("Same name as someone in your network", class_="fn-section text-label"),
        h.p("Tick a row only if it is the same person. An unticked row becomes a new person, and you can still merge it "
            "later from the profile.", class_="fn-note text-small"),
        h.div(h.p(h.input(type="checkbox", id="all", name="same_all", value="1"),
                  h.label("All of these are the same person", class_="text-strong", for_="all"), class_="fn-check"),
              class_="fn-summary__all"),
        h.div(shown, class_="fn-lines"),
    ]


def what_happens(row: ImportRow) -> tuple[str, str | None]:
    if row.outcome != "skipped":
        return OUTCOME_WORDS[row.outcome], None
    return ("Skipped" if name_key(row.name) else "Skipped: no name"), "fn-table__failed"


def import_rows(preview: ImportPreview, columns: tuple[str, ...]) -> list[Safe]:
    """The heading and table of the file's rows with what happens to each, the first 200 and how many there are."""
    label, rows = f"Rows in {preview.filename}", preview.rows
    return [
        h.h2(label, " ", h.span(f"{len(rows):,}"), class_="fn-section text-label"),
        data_table(label, ["Row", "What happens", *columns],
                   [[(str(r.n), None), what_happens(r), *[(r.cells.get(c, ""), None) for c in columns]]
                    for r in rows[:IMPORT_ROWS_SHOWN]]),
        h.div(h.span(f"{IMPORT_ROWS_SHOWN:,} of {len(rows):,} shown"), class_="fn-more text-meta")
        if len(rows) > IMPORT_ROWS_SHOWN else None,
    ]
