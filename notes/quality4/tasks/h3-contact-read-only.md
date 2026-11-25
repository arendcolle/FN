# Task H3: contact details are read-only, three rows with one behaviour

## Goal

Staff can type an email or phone but not a LinkedIn address, and cannot remove a found value. On the owner's database nobody typed one (0 `edit_contact` events), while 16 people hold a found email and 25 a LinkedIn address. This task removes typing, shows three read-only rows and gives Email and Phone "Not correct" (brief H3, Profile part version 14).

## What to build

### `src/fn/contracts.py`

- `DateMethod` (line 32) loses `"staff_edit"`, `SourceKind` (35) `"staff"`, `EventKind` (52) `"edit_contact"`.
- `Source._http_only` (183) accepts `fn:` for `kind == "import"` only. `record_source` (192): `kind: Literal["record", "vendor_record", "import"]`.
- `ContactView` (621): `kind: Literal["email", "phone", "linkedin"]`; new `url`, `label`, `href`, `date`, `removed`, each `str | None = None`.

### `src/fn/network.py`

Delete `CONTACT_KINDS`, `MAX_CONTACT`, `_checked`, `staff_source`, `set_contact`, `_undo_contact`, the `"edit_contact"` entry of `UNDO`, and the imports this orphans: `hashlib`, `ClaimDraft`, `Identifier`, `Source`, `normalize`.

### `src/fn/store.py`

- `hidden_keys` (85) takes `list[Claim]` and loses the retyped rule. `_person_claims` (570) returns `list[Claim]` without the sources join. Fix the `claims_of` docstring.
- `EVENT_KINDS = get_args(EventKind)`; `get_event` (756) and `events_of` (760) add `AND kind IN (SELECT value FROM json_each(?))` with `json.dumps(EVENT_KINDS)`.

### `src/fn/present.py`

- `FIELDS` (63) gains `"linkedin": "LinkedIn"`. `RECORD_LABELS` loses `"staff"`, `RECORD_DATES` `"staff_edit"`, `DONE` `"edit_contact"`. `contact_of` (1089) and `summary_of` stay.
- New `linkedin_of(store: Store, persons: list[str]) -> ContactView | None`. Of the records (`store.records_of`, store.py:709) holding a `profile_url` (`store.identifiers_of`, 822), take the latest `merged_at` (unmerged counts earliest, ties by id) and its first address; `url = profile_url(value)` (contracts.py:1083). Its source, among that record's claim sources (`claims_of(persons, include_hidden=True)`, `claim_records`, `get_sources`): a `vendor_record` with `profile_url(source.url) == url`, else the newest `import` by `fetched_at`. Returns `value=url.removeprefix("https://www.")`, `url`, `href=f"/sources/{source.id}"`, and label "From a LinkedIn record" with no date, or "From import {source.title}" with `day_words(source.fetched_at)`. No source: no label, href or date.
- `profile` (1279): `contact` is `contact_of` for email and phone, with `removed=gone[0].value` on the kind of `gone[0]`, then `linkedin_of(store, persons)`; a view with neither value nor `removed` is left out.

### `src/fn/web/parts.py`

`contact_edit` goes. `contact_block(view: ProfileView, here: str) -> Safe | None`, one `fn-contact__row` per view:

- Email or Phone with a value: today's value markup (proof, or cite line for an import), then `h.dd(post_form(f"/claims/{claim_id}/reject", "Not correct", "fn-link text-meta", f"{here}#contact"), class_="fn-contact__acts")`.
- `removed`: the `dd` opens with `undo_form(view.last, [h.span(removed), h.span("· Removed")], "fn-skipline text-body", f"{here}#contact")`, then the next value, if any, as above.
- LinkedIn: `<p class="fn-contact__value text-body"><a href="{url}">{value}</a></p>`, then, with a label, `<p class="fn-cite text-small"><a href="{with_back(href, here)}">{label}</a>, {date}</p>` (no comma without a date). No action.
- No row, network person: `<p class="fn-note text-small">FN found no contact details. An <a href="/imports/new">import</a> can add them.</p>`. No row otherwise: None.

Strings, from STRINGS.md: "Email", "Phone", "LinkedIn", "Not correct", "· Removed", "Undo", "From a LinkedIn record", "From import `{file name}`, row `{n}`", "FN found no contact details. An import can add them."

### `src/fn/web/staff.py`

Delete the route `edit_contact` (754), `CONTACT_KINDS` (106), the `normalize` and `fold` imports. `person_page(store, person_id, params, fetched=False)` loses `error`, `typed`, `edit`; it calls `contact_block(view, here)`. `?edit=` becomes an ignored query key.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which email, phone and LinkedIn address show, with which source | `present.contact_of`, `present.linkedin_of` |
| Contact markup | `parts.contact_block` |
| Rejecting a claim and its undo | `network.reject_claim` and its route (unchanged) |
| Which rejected claims stay hidden | `store.hidden_keys` |
| Leaving out events of an unknown kind | `store.get_event`, `store.events_of` |

## An old row

FN holds none. An `edit_contact` event is left out: no done line, and its Undo answers 404. A claim with a `staff` source fails validation in `store.get_sources`, so that person's page answers 500.

## Recorded answers and stored searches (S6)

No prompt or model call changes, so recorded answers and replay stay valid. Ranking reads no contact claim or identifier, and `hidden_keys` changes only for staff claims (none exist), so version-1 searches keep their order exactly.

## Inputs a real run will meet

Tests 1 to 9 cover: two emails from two pages; one email from two pages; an email rejected without an event; an imported email; a phone only; someone outside the network; an address on a merged record; two addresses on two records; a trailing slash or country host; a record with no matching source; an email of 209 characters; `?edit=email`; an unknown event kind; a hand-made POST to the old route.

## Tests (each must fail without the change)

Made-up names only, in `tests/test_profile_page.py` unless named.

1. `test_not_correct_on_an_email_shows_the_next_one_and_undo_brings_it_back`: emails from 2024 and 2026 pages; Not correct on the newer gives its skipline and the older with its own Not correct; Undo restores the newer.
2. `test_one_email_from_two_pages_is_one_row_and_one_not_correct_hides_both`: 209 characters long; after Not correct, the skipline and no other Email row.
3. `test_an_email_rejected_without_an_event_is_not_shown`: a network person gets the note line.
4. `test_an_imported_email_and_a_phone_only_each_have_one_row_with_not_correct`: the import cite; one Phone row; outside the network, rows with Not correct and no summary Contact row.
5. `test_a_linkedin_row_names_its_record_or_its_import_and_has_no_action`: "From a LinkedIn record"; the import cite; no form; no source gives no cite line.
6. `test_the_linkedin_row_shows_the_record_merged_last`: the later merge wins; a stored `https://be.linkedin.com/in/ada-fictief/` shows `linkedin.com/in/ada-fictief` linking to `https://www.linkedin.com/in/ada-fictief`.
7. `test_a_network_person_without_contact_gets_the_import_line`: link to `/imports/new`; with only a LinkedIn address, no note.
8. `tests/test_person_page.py` `test_no_page_offers_edit_and_the_old_route_is_gone`: `?edit=email` answers 200 without an input named value or "Edit"; `POST /people/{id}/contact` answers 404 or 405.
9. `tests/test_person_page.py` `test_an_event_of_an_unknown_kind_is_left_out`: an `edit_contact` row inserted by SQL; the page answers 200 without Undo; its undo POST answers 404.

## Existing tests that change, approved by the lead

- `test_network.py` `test_contact_edits_replace_hide_and_undo`: deleted.
- `test_network.py` `test_fn_urls_are_valid_for_import_and_staff_sources_only` becomes `test_fn_urls_are_valid_for_import_sources_only`. Old: import and staff accept `fn:`. New: import does; kind staff raises `ValidationError`.
- `test_person_page.py` `test_a_refused_contact_value_reopens_the_field_with_its_sentence`: deleted.
- `test_person_page.py` `test_a_network_persons_page_shows_head_contact_and_groups_in_order`: old two "Not provided"; new one "FN found no contact details.".
- `test_person_page.py` `test_each_decision_shows_its_done_line_and_undo_restores_the_page` and `test_a_second_press_of_any_button_writes_nothing`: the contact case is dropped.
- `test_person_page.py` `test_an_undo_after_a_later_decision_comes_back_with_the_refusal_banner`: the later decision is Not correct on a second fact; assertions stay.
- `test_profile_page.py` `test_a_found_contact_value_has_its_source_name_and_proof_and_only_a_member_gets_edit` becomes `..._and_not_correct`. Old: a member's rows have Edit. New: every Email and Phone row has one Not correct, nobody has Edit.
- `test_present.py` `test_a_record_gives_a_citation_and_a_page_gives_its_quote`: the `"staff"` case goes.

No other existing test may change; if one fails, stop and report.

## Hand check

`uv run python -m unittest` all green. `V=$(mkvar.sh h3)`, and in a scratch folder outside the repo `check.py`:

```python
import datetime
from fn import config, present
from fn.store import Store
from fn.web.parts import contact_block
s = Store(config.from_env().db_path); s.migrate()
ids = [r[0] for r in s.conn.execute(
    "SELECT DISTINCT COALESCE(merged_into, id) FROM persons WHERE id IN (SELECT person_id FROM person_identifiers "
    "WHERE scheme = 'profile_url') OR id IN (SELECT person_id FROM claims WHERE kind IN ('email', 'phone'))")]
for pid in ids:
    v = present.profile(s, pid, datetime.date(2026, 11, 24))
    html = str(contact_block(v, f"/people/{pid}"))
    print([(c.kind, c.label or (c.claim and c.claim.source)) for c in v.contact], html.count("Not correct"), "Edit" in html)
```

`FN_VAR=$V FN_HTTP=replay FN_LLM=replay uv run python check.py`. Expect 25 rows "From a LinkedIn record", 16 email and 11 phone rows with one Not correct each, and `False` throughout. Screenshot one page's Contact section.

## Not doing

Typing any fact. Not correct for LinkedIn. Removing an identifier. ORCID as a row. Changes to the lookup, import, export, summary row or `fn.css` (the lead's). A migration. Handling a `staff` source beyond the 500 above.
