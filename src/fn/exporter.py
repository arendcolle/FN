"""The network as CSV text: the import columns first, so the file imports again, then what FN knows beyond them."""
import csv
import io

from fn import geo
from fn.contracts import IMPORT_COLUMNS, Claim, PersonView, name_key
from fn.present import belgian_orgs
from fn.store import Store

COLUMNS = (*IMPORT_COLUMNS, "belgian_organizations", "added", "profile")
FORMULA_STARTS = ("=", "+", "-", "@")


def place_parts(place: str | None) -> dict[str, str]:
    """The place text as city, state and country, split on commas; the first part is the city.

    A later part the alias table knows as a state is the state, unless one came before. A known country, the last
    part and any part after the state go to the country; an unknown part before the last is the state.
    """
    first, *later = [p.strip() for p in (place or "").split(",") if p.strip()] or [""]
    found = {"city": first, "state": "", "country": ""}
    for n, part in enumerate(later, 1):
        kinds = {kind for kind, _ in geo.regions_of(name_key(part))}
        if "state" in kinds and not found["state"]:
            found["state"] = part
        elif "country" in kinds or n == len(later) or found["state"]:
            found["country"] = ", ".join(filter(None, [found["country"], part]))
        else:
            found["state"] = part
    return found


def cell(value: object) -> str:
    """The value as cell text; text a spreadsheet would run as a formula gets a leading apostrophe."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text


def orgs_cell(found: list[tuple[str, list[int]]]) -> str:
    """Each Belgian organization with its years, such as 'KU Leuven 2008–2013', joined by '; '."""
    return "; ".join(" ".join([name, *([f"{y[0]}–{y[-1]}" if len(y) > 1 else str(y[0])] if y else [])])
                     for name, y in found)


def csv_text(store: Store, people: list[PersonView], base_url: str = "") -> str:
    """One row per person under COLUMNS, with a byte-order mark; base_url goes before each Person page path."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    claims: dict[str, list[Claim]] = {}
    for claim in store.claims_of([v.person_id for v in people]):
        claims.setdefault(claim.person_id, []).append(claim)
    facts = store.get_orgs(list({c.org_id for found in claims.values() for c in found if c.org_id}))
    for view in people:
        records = [r.id for r in store.records_of(view.person_id)]
        held = {i.scheme: i.value for found in store.identifiers_of(records).values() for i in found}
        orgs = orgs_cell(belgian_orgs(claims.get(view.person_id, []), facts))
        row = {"name": view.name, "email": view.email, "phone": view.phone, "organization": view.employer,
               "role": view.role, **place_parts(view.place), "linkedin_url": held.get("profile_url"),
               "orcid": held.get("orcid"), "belgian_organizations": orgs, "added": view.added,
               "profile": f"{base_url}/people/{view.person_id}"}
        writer.writerow([cell(row[c]) for c in COLUMNS])
    return "﻿" + out.getvalue()
