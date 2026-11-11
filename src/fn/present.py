"""How a person reads on a card: employer, newest place, Belgian organizations, evidence and plain-words helpers."""
from calendar import month_name
from datetime import date, datetime

from fn import orgs, rank
from fn.contracts import Candidate, Claim, LaneOut, Org, Search
from fn.store import Store


EMPLOYED = ("works_at", "worked_at", "affiliated_with")


def newest_places(claims: list[Claim]) -> dict[str, Claim]:
    """Each person's newest dated location claim with coordinates, by person id."""
    newest: dict[str, Claim] = {}
    for claim in sorted(claims, key=lambda c: (c.claim_date or "", c.id)):
        if claim.kind == "location" and claim.claim_date and claim.lat is not None and claim.lon is not None:
            newest[claim.person_id] = claim
    return newest


def employer_of(claims: list[Claim]) -> str | None:
    """The organization of the newest works_at, worked_at or affiliated_with claim, or None."""
    jobs = [c for c in claims if c.relation in EMPLOYED]
    return max(jobs, key=lambda c: (c.valid_to or c.claim_date or "", c.claim_date or "")).value if jobs else None


def belgian_orgs(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[str, list[int]]]:
    """Each Belgian organization the claims name with the years of those claims, earliest first."""
    years: dict[str, set[int]] = {}
    for claim, org in orgs.belgian_claims(claims, facts):
        years.setdefault(org.name, set()).update(int(u) for u in rank.units(claim) if u != rank.UNDATED)
    return sorted(((name, sorted(found)) for name, found in years.items()), key=lambda t: (t[1][:1] or [9999], t[0]))


def evidence(candidate: Candidate, claims: list[Claim], facts: dict[str, Org]) -> Claim | None:
    """The claim to quote on a card: the newest at a Belgian organization, else the first the search matched."""
    belgian = [c for c, _ in orgs.belgian_claims(claims, facts)]
    if belgian:
        return max(belgian, key=lambda c: (c.claim_date or "", c.id))
    return next((c for c in claims if c.id in candidate.reason_claim_ids), None)


def date_words(claim: Claim) -> str:
    """The claim's date as people write it: 2025, March 2024, 3 March 2024 or date unknown."""
    parts = [int(p) for p in (claim.claim_date or "").split("-") if p.isdigit()]
    precision = claim.date_precision or ("year", "month", "day")[min(len(parts), 3) - 1] if parts else None
    if precision == "day" and len(parts) == 3:
        return f"{parts[2]} {month_name[parts[1]]} {parts[0]}"
    if precision in ("month", "day") and len(parts) >= 2:
        return f"{month_name[parts[1]]} {parts[0]}"
    return str(parts[0]) if parts else "date unknown"


def cut(text: str, limit: int) -> str:
    """The text, or its words up to limit characters and '…' when it is longer."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def plural(count: int, one: str, many: str) -> str:
    return f"{count:,} {one if count == 1 else many}"


def days_ago(at: datetime, today: date) -> str:
    """A past moment as people say it: today, yesterday, 3 days ago, last week, else 3 March 2026."""
    local = at.astimezone()
    days = (today - local.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 7 else "last week" if days < 14 else f"{local.day} {local:%B %Y}"


def sources_read(store: Store, search: Search) -> int:
    """How many records the search's lanes looked at."""
    total = 0
    for step in store.list_steps(search.id):
        output = store.get_payload(step.id)[1] if step.output_model == "LaneOut" else None
        total += LaneOut.model_validate_json(output).total_seen if output else 0
    return total
