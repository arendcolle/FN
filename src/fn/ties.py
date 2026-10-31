"""Affiliation claims to a TieLabel, from data/ties.csv; ties.py never writes a claim."""
import csv
from collections import defaultdict
from functools import cache
from typing import NamedTuple

from fn.config import ROOT
from fn.contracts import Claim, TieIn, TieLabel, TieOut, TieType, normalize
from fn.steps import StepContext

TIES_CSV = ROOT / "data" / "ties.csv"
UNMAPPED = ROOT / "data" / "ties-unmapped.txt"
RULES_VERSION = "1"
REGION_TIE: dict[str, TieType] = {"flemish": "flemish", "belgian": "belgian", "dutch": "dutch"}
STRENGTH: list[TieType] = ["flemish", "belgian", "dutch", "none_found"]


class Org(NamedTuple):
    org_id: str
    region: str
    ror: str | None
    aliases: tuple[str, ...]


def fold(text: str) -> str:
    return " ".join(normalize(text).casefold().split())


@cache
def _orgs() -> dict[str, Org]:
    """Every alias, folded, to its org; raises ValueError for an alias listed twice or an unknown region."""
    rows = list(csv.DictReader(TIES_CSV.read_text(encoding="utf-8").splitlines()))
    aliases = defaultdict(list)
    for row in rows:
        if row["region"] not in (*REGION_TIE, "other"):
            raise ValueError(f"ties.csv: unknown region {row['region']!r} for {row['alias']!r}")
        aliases[row["org_id"]].append(row["alias"])
    found: dict[str, Org] = {}
    for row in rows:
        key = fold(row["alias"])
        if key in found:
            raise ValueError(f"ties.csv: alias {row['alias']!r} is listed twice")
        found[key] = Org(row["org_id"], row["region"], row["ror"] or None, tuple(aliases[row["org_id"]]))
    return found


@cache
def unmapped() -> frozenset[str]:
    """Institution strings checked and left out of ties.csv on purpose, folded."""
    return frozenset(fold(line) for line in UNMAPPED.read_text(encoding="utf-8").splitlines() if line.strip())


def _org(name: str) -> Org | None:
    return _orgs().get(fold(name))


@cache
def _by_id() -> dict[str, Org]:
    return {org.org_id: org for org in _orgs().values()}


def org_id_by_ror(ror: str | None) -> str | None:
    """The org id of the org that ties.csv gives this ROR url, else None."""
    return next((org.org_id for org in _by_id().values() if ror and org.ror == ror), None)


def org_id(name: str) -> str | None:
    found = _org(name)
    return found.org_id if found else None


def aliases(name: str) -> list[str]:
    """Every spelling of the org that name is an alias of; empty when name is not in ties.csv."""
    found = _org(name)
    return list(found.aliases) if found else []


def ref(name: str) -> str | None:
    """The chip ref for an institution name: ror:<url> when ties.csv knows the org's ROR id."""
    found = _org(name)
    return f"ror:{found.ror}" if found and found.ror else None


def label(claims: list[Claim]) -> TieLabel:
    """The strongest tie the affiliation claims support: flemish, then belgian, then dutch, else none_found.

    An affiliation's org is its org_id, else its value as an alias. claim_ids are the claims that support
    the tie; checked lists the source ids of every claim looked at.
    """
    support: dict[TieType, list[str]] = defaultdict(list)
    for claim in claims:
        found = (_by_id().get(claim.org_id or "") or _org(claim.value)) if claim.kind == "affiliation" else None
        if found and found.region in REGION_TIE:
            support[REGION_TIE[found.region]].append(claim.id)
    tie = next(t for t in STRENGTH if t == "none_found" or support[t])
    checked = list(dict.fromkeys(c.source_id for c in claims))
    return TieLabel(tie=tie, claim_ids=support[tie], checked=checked, rules_version=RULES_VERSION)


def combine(labels: list[TieLabel]) -> TieLabel:
    """One label for several records of one name: the strongest tie, with every checked source."""
    tie = min((lab.tie for lab in labels), key=STRENGTH.index, default="none_found")
    return TieLabel(
        tie=tie,
        claim_ids=[c for lab in labels if lab.tie == tie for c in lab.claim_ids],
        checked=list(dict.fromkeys(s for lab in labels for s in lab.checked)),
        rules_version=RULES_VERSION,
    )


def run(ctx: StepContext, inp: TieIn) -> TieOut:
    by_person: dict[str, list[Claim]] = defaultdict(list)
    for claim in ctx.store.claims_of(inp.person_ids):
        by_person[claim.person_id].append(claim)
    return TieOut(labels={p: label(by_person[p]) for p in dict.fromkeys(inp.person_ids)})
