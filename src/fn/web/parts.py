"""The HTML of each design-system part: search box, recent searches, person card, network row, filter bar and notices."""
from datetime import date
from urllib.parse import urlencode

from fn.contracts import (
    ClaimView,
    ContactView,
    LastView,
    NetworkFilter,
    OrgView,
    PersonView,
    ProfileView,
    QuoteView,
    Search,
)
from fn.present import FIELDS, cut, days_ago, plural
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


def person_card(view: PersonView, search_id: str | None = None) -> Safe:
    """The person's card: the name linking to their page, role and place, Belgian organizations, then the evidence.

    search_id is the search the card shows on, which the Person page links back to.
    """
    job = ", ".join(x for x in (view.role, view.employer) if x)
    shown = view.evidence
    query = urlencode({"search": search_id, "from": "card"} if search_id else {"from": "card"})
    return h.article(
        h.h3(h.a(view.name, href=f"/people/{view.person_id}?{query}"), class_="fn-card__name text-name"),
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
            h.h3(h.a(view.name, href=f"/people/{view.person_id}?from=row"), class_="fn-row__name text-name"),
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


FACT_STEP = 10
GROUP_IDS = {"Ties to Belgium": "belgium", "Work": "work", "Places": "places"}
MATCH_NOTE = "These have the same name, but nothing in FN links them to this person for sure."


def role_line(view: PersonView) -> str:
    """Role and employer, then the place after ' · ', as the card and the network row say it."""
    job = ", ".join(x for x in (view.role, view.employer) if x)
    return " · ".join(x for x in (job, view.place or "location not found") if x)


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


def profile_state(view: ProfileView, here: str) -> Safe | list[Safe]:
    """The head's network state: since when with Remove, the done line of Add or Skip, else the buttons."""
    person, last, pid = view.person, view.last, view.person.person_id
    if last and last.kind in ("add", "skip"):
        done = h.span(last.words, class_="fn-done text-strong" if last.kind == "add" else "text-strong")
        return undo_form(last, done, "fn-profile__acts", here)
    if person.status == "in_list":
        since = f"In your network since {person.added}" if person.added else "In your network"
        return h.form(h.span(since), h.input(type="hidden", name="next", value=here),
                      h.button("Remove", type="submit", class_="fn-link text-meta"),
                      method="post", action=f"/people/{pid}/remove", class_="fn-profile__status text-meta")
    quiet = "fn-btn fn-btn--quiet text-control"
    skip = post_form(f"/people/{pid}/skip", "Skip", quiet, here)
    if match := view.name_match:
        theirs = f"/people/{match.person_id}"
        return [h.p("Same name as ", h.a(match.name, href=theirs), " in your network", class_="fn-card__match text-body"),
                h.div(post_form(f"{theirs}/merge", "Same person", quiet, theirs, other=pid),
                      post_form(f"/people/{pid}/add", "Add as new", quiet, here, not_same=match.person_id), skip,
                      class_="fn-profile__acts")]
    return h.div(post_form(f"/people/{pid}/add", "Add", "fn-btn fn-btn--add text-control", here), skip,
                 class_="fn-profile__acts")


def profile_head(view: ProfileView, search: Search | None, here: str) -> Safe:
    """The name, the role line and the network state, under a link back to the search the page was opened from."""
    back = None
    if search:
        back = h.p(h.a(f"Back to the results for “{cut(search.question, 60)}”", href=f"/searches/{search.id}"),
                   class_="fn-back text-meta")
    return h.div(back, h.h1(view.person.name, class_="fn-profile__name text-name"),
                 h.p(role_line(view.person), class_="fn-profile__role text-body"), profile_state(view, here),
                 class_="fn-profile__head")


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
                  typed: str | None = None) -> list[Safe]:
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
            cite = [h.a(claim.label, href=claim.href), f", {claim.date}"]
            saved = last and last.kind == "edit_contact" and last.claim_id == claim.claim_id
            shown = [h.p(h.a(contact.value, href=f"{scheme}:{contact.value}"), class_="fn-contact__value text-body"),
                     undo_form(last, [cite, " · Saved"], "fn-cite text-small", here, "fn-link text-small") if saved
                     else h.p(cite, class_="fn-cite text-small")]
        else:
            shown = h.p("Not provided", class_="fn-contact__none text-body")
        edit_href = f"{here}{'&' if '?' in here else '?'}edit={contact.kind}"
        rows.append(h.div(h.dt(label, class_="text-label"), h.dd(shown), h.dd(h.a("Edit", class_="text-meta", href=edit_href)),
                          class_="fn-contact__row"))
    return [h.h2("Contact", class_="fn-section text-label", id="contact"), h.dl(rows, class_="fn-contact")]


def claim_line(view: ClaimView, last: LastView | None, here: str) -> Safe:
    """A fact as the Claim part: New, the fact and its years with Remove, then its quote or citation.

    The fact the latest decision removed shrinks to one line with Undo.
    """
    if last and last.kind == "reject_claim" and last.claim_id == view.claim_id:
        return h.div(undo_form(last, h.span(last.words), "fn-skipline text-body", here), class_="fn-claim fn-claim--removed")
    years = [", ", h.span(view.years, class_="text-year")] if view.years else None
    new = h.span("New", class_="fn-new text-label") if view.is_new else None
    head = h.div(h.p(new, view.what, years, class_="fn-claim__what text-body"),
                 post_form(f"/claims/{view.claim_id}/reject", "Remove", "fn-link text-meta", here), class_="fn-claim__head")
    cite = h.p(h.a(view.label, href=view.href), f", {view.date}", class_="fn-cite text-small")
    return h.div(head, quote(view.quote) if view.quote else cite, class_="fn-claim")


def fact_groups(view: ProfileView, here: str, all_facts: bool) -> list[object]:
    """Each fact group under its heading, its first ten facts unless all_facts, then 'Show n more' for the rest."""
    out: list[object] = []
    every = f"{here}{'&' if '?' in here else '?'}all=1"
    for group in view.facts:
        shown = group.facts if all_facts else group.facts[:FACT_STEP]
        more, anchor = len(group.facts) - len(shown), GROUP_IDS[group.title]
        out += [h.h2(group.title, class_="fn-section text-label", id=anchor),
                h.div([claim_line(c, view.last, here) for c in shown]),
                h.div(h.span(f"{len(shown):,} of {len(group.facts):,} shown"),
                      h.a(f"Show {more:,} more", class_="fn-btn fn-btn--quiet text-control", href=f"{every}#{anchor}"),
                      class_="fn-more text-meta") if more else None]
    return out


def done_line(last: LastView, here: str) -> Safe:
    return h.div(h.div(undo_form(last, last.words, "text-body", here), class_="fn-line__main"), class_="fn-line fn-line--done")


def found_as_block(view: ProfileView, here: str) -> list[Safe] | None:
    """Found as: each record's source with its fact count and Not this person; the canonical record has no button."""
    pid, last = view.person.person_id, view.last
    rows = [h.div(
        h.div(h.p(h.a(r.label, href=r.href), " ",
                  h.span(f"· {plural(r.facts, 'fact', 'facts')}", class_="fn-line__meta text-meta"), class_="text-body"),
              class_="fn-line__main"),
        post_form(f"/people/{pid}/not-same", "Not this person", "fn-link text-meta", here, other=r.record_id)
        if r.record_id != pid else None,
        class_="fn-line") for r in view.found_as]
    if last and last.separated:
        rows.append(done_line(last, here))
    return [h.h2("Found as", class_="fn-section text-label"), h.div(rows, class_="fn-lines")] if rows else None


def possible_line(match: PersonView, person_id: str, here: str) -> Safe:
    """A same-name person with enough to decide, and Same person and Different person."""
    quiet, shown = "fn-btn fn-btn--quiet text-control", match.evidence
    return h.div(
        h.div(h.p(h.a(match.name, href=f"/people/{match.person_id}"), class_="text-popup"),
              h.p(role_line(match), class_="text-body"),
              h.p(orgs_line(match.orgs, match.more_orgs), class_="fn-line__meta text-body") if match.orgs else None,
              h.p(h.a(shown.label, href=shown.href), f", {shown.date}", class_="fn-cite text-small") if shown else None,
              class_="fn-line__main"),
        h.div(post_form(f"/people/{person_id}/merge", "Same person", quiet, here, other=match.person_id),
              post_form(f"/people/{person_id}/not-same", "Different person", quiet, here, other=match.person_id),
              class_="fn-line__acts"),
        class_="fn-line",
    )


def possible_block(view: ProfileView, here: str) -> list[Safe] | None:
    """Possible matches under their note, and the done line of the latest merge or different-person decision."""
    last = view.last
    rows = [possible_line(m, view.person.person_id, here) for m in view.possible]
    if last and (last.kind == "merge" or (last.kind == "not_same" and not last.separated)):
        rows.append(done_line(last, here))
    if not rows:
        return None
    return [h.h2("Possible matches", class_="fn-section text-label", id="matches"),
            h.p(MATCH_NOTE, class_="fn-note text-small"), h.div(rows, class_="fn-lines")]
