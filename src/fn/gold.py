"""fn-gold: run the gold cases, match each known pick to the result list, and write the report and top5.csv."""
import csv
import io
import json
import sys
from datetime import UTC, datetime

from fn import config, net, orgs, rank
from fn.config import ROOT
from fn.contracts import (
    Candidate,
    CaseResult,
    Claim,
    GoldCase,
    GoldGroup,
    GoldPick,
    Org,
    Person,
    PickResult,
    TopCard,
    group_key,
    name_key,
)
from fn.llm import from_settings
from fn.store import Store
from fn.web.app import titles, trace_rows
from fn.worker import Worker

GOLD_SET = ROOT / "data" / "gold" / "gold-set.json"
REACH = ROOT / "data" / "gold" / "reach.json"
DEV = ("GS-02", "GS-10")
HELD_OUT = ("GS-15", "GS-16", "GS-23", "GS-24", "GS-28")
TOP_N = 10
DEV_TARGET = 3
TOP5_COLUMNS = ["case", "position", "section", "section_rank", "name", "lanes", "reason_quote", "belgian_claims",
                "good_pick"]


def group_of(case_id: str) -> GoldGroup:
    return "dev" if case_id in DEV else "held-out" if case_id in HELD_OUT else "other"


def load_cases(ids: list[str]) -> list[GoldCase]:
    """The gold cases named in ids (all when empty), in gold-set order, each pick with its pin and reach.

    The pin (an OpenAlex id) and the reach verdict come from reach.json; a pick it does not list has neither.
    Raises ValueError naming an unknown case id.
    """
    cases = json.loads(GOLD_SET.read_text(encoding="utf-8"))["questions"]
    unknown = sorted(set(ids) - {c["id"] for c in cases})
    if unknown:
        raise ValueError(f"unknown gold case {', '.join(unknown)}")
    reach = {(p["case"], p["name"]): p for p in json.loads(REACH.read_text(encoding="utf-8"))["picks"]}
    loaded = []
    for case in cases:
        if ids and case["id"] not in ids:
            continue
        picks = []
        for person in case["people"]:
            known = reach.get((case["id"], person["name"]), {})
            picks.append(GoldPick(
                case_id=case["id"], name=person["name"], gold_tie=person["tie"], openalex_id=known.get("openalex_id"),
                reachable=known.get("reachable"), reach_evidence=known.get("evidence", ""),
            ))
        loaded.append(GoldCase(id=case["id"], question=case["question"], picks=picks))
    return loaded


def match(pick: GoldPick, candidates: list[Candidate], persons: dict[str, Person],
          pinned: str | None) -> Candidate | None:
    """The candidate that carries the pick: the one holding its pinned person, else the one sharing its group key.

    pinned is the stored person for the pick's OpenAlex id; a pin the store does not hold falls back
    to the name. With several candidates the best one wins, section network first.
    """
    key = group_key(name_key(pick.name))
    found = [c for c in candidates if (pinned in c.person_ids if pinned
                                       else any(group_key(persons[p].name_key) == key for p in c.person_ids))]
    return min(found, key=lambda c: (c.section != "network", c.rank), default=None)


def lost_at(rows: list[list[object]], near: Candidate | None) -> tuple[str, str]:
    """The step and reason where a pick left the search, from its trace rows [seq, step, stage, kept, reason].

    near is the candidate that carries the pick when it ranks below the top 10.
    """
    if near is not None:
        return "rank", f"ranked {near.section} #{near.rank}, below the top {TOP_N}"
    dropped = [r for r in rows if r[3] == "dropped"]
    if dropped:
        return str(dropped[0][1]), str(dropped[0][4])
    kept = [r for r in rows if r[3] == "kept"]
    if kept:
        return str(kept[-1][1]), "kept there, but no candidate carries its name or id"
    lanes = [r for r in rows if str(r[1]).startswith("lane:")]
    return (", ".join(str(r[1]) for r in lanes),
            "not found by any lane; " + "; ".join(f"{r[1]} {str(r[4]).removeprefix('not present; ')}" for r in lanes))


def claim_line(claim: Claim, org: Org) -> str:
    lang = f"name in {org.name_lang}" if org.name_lang else "name language unknown"
    return (f"{org.name} ({org.region or 'no region'}, {lang}) {claim.relation or claim.kind} "
            f"{claim.claim_date or 'no date'}")


def claims_text(store: Store, claims: list[Claim], facts: dict[str, Org], scored: list[str]) -> str:
    """The claims at Belgian organizations and the org ids without facts, as the card lists them.

    The claims in scored come first, each with its years; the other Belgian claims follow 'not scored:'.
    Only when every org id has facts and none is Belgian does it name the sources read instead.
    """
    found, missing = orgs.belgian_claims(claims, facts), orgs.missing_facts(claims, facts)
    if not found and not missing:
        sources = store.get_sources([c.source_id for c in claims])
        return f"No Belgian organization found in {titles(claims, sources)}"
    lines = [f"{claim_line(c, o)}, years {rank.years_text(rank.units(c))}" for c, o in found if c.id in scored]
    others = [claim_line(c, o) for c, o in found if c.id not in scored]
    lines += ["not scored: " + "; ".join(others)] if others else []
    parts = ["Belgian claims: " + "; ".join(lines)] if lines else []
    return "; ".join(parts + ([f"org facts not stored for {', '.join(missing)}"] if missing else []))


def belgian_text(store: Store, candidate: Candidate) -> str:
    """The claims_text of the candidate's records, then its belgian_years count and, on the list, its rank."""
    claims = store.claims_of(candidate.person_ids)
    facts = store.get_orgs([c.org_id for c in claims if c.org_id])
    part = next((p for p in candidate.score_parts if p.feature == "belgian_years"), None)
    if part is None:
        return f"{claims_text(store, claims, facts, [])}; belgian_years 0"
    count = len(rank.counted([c for c in claims if c.id in part.claim_ids], facts)[1])
    return f"{claims_text(store, claims, facts, part.claim_ids)}; belgian_years {count}, rank {part.rank}"


def stored_text(store: Store, name: str) -> str:
    """For a pick no candidate carries: the Belgian claims of the stored records with its group key.

    Returns 'no stored record' when the store holds none.
    """
    key = group_key(name_key(name))
    person_ids = [p for p, _ in store.person_ids_by_group_key([key]).get(key, [])]
    if not person_ids:
        return "no stored record"
    claims = store.claims_of(person_ids)
    facts = store.get_orgs([c.org_id for c in claims if c.org_id])
    found, missing = orgs.belgian_claims(claims, facts), orgs.missing_facts(claims, facts)
    lines = [claim_line(c, o) for c, o in found]
    lines += [f"org facts not stored for {', '.join(missing)}"] if missing else []
    if not lines:
        lines = [f"No Belgian organization found in {titles(claims, store.get_sources([c.source_id for c in claims]))}"]
    return "stored, not in the result: " + "; ".join(lines)


def judge(pick: GoldPick, near: Candidate | None, lost: tuple[str, str], belgian: str = "") -> PickResult:
    """Found when the pick ranks in the top 10 of its section; a pick no lane can reach is labelled so, not missed.

    lost is (step, reason), used only for a pick that is not found. A pick reach.json calls unreachable
    keeps the trace's step and takes reach.json's evidence as its reason. belgian describes the pick's Belgian claims.
    """
    found = near is not None and near.rank <= TOP_N
    unreachable = near is None and pick.reachable is False
    return PickResult(
        case_id=pick.case_id, name=pick.name, gold_tie=pick.gold_tie,
        verdict="found" if found else "no lane in slice" if unreachable else "missed",
        section=near.section if near else None, rank=near.rank if near else None, belgian=belgian,
        lost_step="" if found else lost[0],
        lost_reason="" if found else pick.reach_evidence if unreachable else lost[1],
    )


def search_failure(store: Store, search_id: str, error: str | None) -> tuple[str, str]:
    """The step that failed in a search that did not finish, and its error."""
    failed = next((s for s in store.list_steps(search_id) if s.status == "error"), None)
    if failed:
        return failed.step, f"{failed.error_type}: {failed.error_message}"
    return "search", (error or "did not finish").strip().splitlines()[-1]


def run_case(worker: Worker, case: GoldCase) -> CaseResult:
    """Run the case's question as a normal search and judge each of its picks against the result list."""
    store = worker.store
    search = worker.execute(worker.create_search(case.question).id)
    candidates = store.list_candidates(search.id) if search.status == "done" else []
    persons = store.get_persons([p for c in candidates for p in c.person_ids])
    pins = store.person_ids_by_identifier("openalex", [p.openalex_id for p in case.picks if p.openalex_id])
    picks = []
    for pick in case.picks:
        near = match(pick, candidates, persons, pins.get(pick.openalex_id or ""))
        if near is not None and near.rank <= TOP_N:
            lost = ("", "")
        elif search.status != "done":
            lost = search_failure(store, search.id, search.error)
        else:
            lost = lost_at(trace_rows(store, search, pick.name), near)
        picks.append(judge(pick, near, lost, belgian_text(store, near) if near else stored_text(store, pick.name)))
    top = []
    for position, c in enumerate(candidates[:5], 1):
        claim = store.get_claim(c.reason_claim_ids[0]) if c.reason_claim_ids else None
        top.append(TopCard(
            position=position, section=c.section, rank=c.rank, name=persons[c.person_id].display_name,
            lanes="; ".join(f"{lane} #{rank}" for lane, rank in c.lane_ranks.items()),
            quote=claim.quote if claim else "", belgian=belgian_text(store, c),
        ))
    chips = search.chips
    shown = "; ".join([
        *(f"topic {c.text}" for c in chips.topics), *(f"institution {c.text}" for c in chips.institutions),
        *([f"place {chips.place.text}"] if chips.place else []),
    ]) if chips else ""
    return CaseResult(case_id=case.id, group=group_of(case.id), question=case.question, chips=shown or "none",
                      search_id=search.id, status=search.status, picks=picks, top=top)


def pick_line(r: PickResult) -> str:
    where = f"{r.section} #{r.rank}" if r.section else "not in the result list"
    belgian = f"; {r.belgian}" if r.belgian else ""
    lost = f"; lost at {r.lost_step}: {r.lost_reason}" if r.lost_step else ""
    return f"{r.case_id} {r.name}: {r.verdict}, {where}, gold tie {r.gold_tie}{belgian}{lost}"


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(head: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(lines + ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows])


def dev_found(results: list[CaseResult]) -> tuple[int, int]:
    """(found, total) over the dev picks that reach.json marks reachable."""
    reach = {(p.case_id, p.name): p.reachable for case in load_cases([]) for p in case.picks}
    picks = [p for r in results if r.group == "dev" for p in r.picks if reach.get((p.case_id, p.name))]
    return sum(p.verdict == "found" for p in picks), len(picks)


def summary(results: list[CaseResult]) -> str:
    """Per group: picks by verdict, with found split by the section it was found in."""
    rows = []
    for group in ("dev", "held-out", "other"):
        in_group = [r for r in results if r.group == group]
        picks = [p for r in in_group for p in r.picks]
        if not picks:
            continue
        found = [p for p in picks if p.verdict == "found"]
        rows.append([group, len(in_group), len(picks), sum(p.section == "network" for p in found),
                     sum(p.section == "new" for p in found), sum(p.verdict == "missed" for p in picks),
                     sum(p.verdict == "no lane in slice" for p in picks)])
    found, total = dev_found(results)
    measure = (f"Dev success measure: {found} of {total} reachable dev picks rank in the top {TOP_N} of their section "
               f"(target {DEV_TARGET}): {'met' if found >= DEV_TARGET else 'not met'}.") if total else ""
    table = md_table(["Group", "Cases", "Picks", "Found, network", "Found, new", "Missed", "No lane in slice"], rows)
    return f"{measure}\n\n{table}" if measure else table


def report(results: list[CaseResult], started: datetime, code_sha: str | None, dirty: bool, llm_mode: str,
           http_mode: str) -> str:
    """The markdown report: run header, summary per group, then one picks table per case."""
    head = ["Pick", "Result", "Section", "Rank", "Gold tie", "Belgian claims", "Lost at", "Reason"]
    parts = [
        f"# Gold run {started:%Y-%m-%d %H:%M:%S} UTC",
        (f"code sha `{code_sha}`, dirty {dirty}, llm mode {llm_mode}, http mode {http_mode}, "
         f"cases {', '.join(r.case_id for r in results)}"),
        ("Dev cases are the targets; held-out cases are reported, not targeted. A pick that reach.json marks "
         "unreachable and no search found is labelled no lane in slice. A found pick ranks in the top "
         f"{TOP_N} of its section."),
        "## Summary", summary(results), "## Cases",
    ]
    for r in results:
        parts += [
            f"### {r.case_id} ({r.group})",
            f"{r.question}\n\nsearch `{r.search_id}` {r.status}; chips: {r.chips}",
            md_table(head, [[
                p.name, p.verdict, p.section or "", p.rank or "", p.gold_tie, p.belgian, p.lost_step, p.lost_reason,
            ] for p in r.picks]),
        ]
    return "\n\n".join(parts) + "\n"


def top5_csv(results: list[CaseResult]) -> str:
    """The top five cards of each case with their Belgian claims, and an empty good_pick column for the owner to mark."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(TOP5_COLUMNS)
    for r in results:
        for c in r.top:
            writer.writerow([r.case_id, c.position, c.section, c.rank, c.name, c.lanes, c.quote, c.belgian, ""])
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    """Run the named gold cases (all 28 when none) and write var/gold/<timestamp>/report.md and top5.csv.

    Returns 0 when every search ended done, 1 when one did not, 2 for an unknown case id.
    """
    ids = sys.argv[1:] if argv is None else argv
    try:
        cases = load_cases(ids)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    worker = Worker(store, settings, llm=from_settings(settings), http=net.Client(settings))
    started = datetime.now(UTC)
    results = []
    for case in cases:
        results.append(run_case(worker, case))
        print(f"{case.id} search {results[-1].search_id} {results[-1].status}")
        for pick in results[-1].picks:
            print(f"  {pick_line(pick)}")
    out = settings.var_dir / "gold" / started.strftime("%Y%m%d-%H%M%S")
    out.mkdir(mode=0o700, parents=True)
    (out / "report.md").write_text(
        report(results, started, worker.code_sha, worker.dirty, settings.llm_mode, settings.http_mode), encoding="utf-8")
    (out / "top5.csv").write_text(top5_csv(results), encoding="utf-8", newline="")
    print(summary(results))
    print(f"report: {out / 'report.md'}\ntop five: {out / 'top5.csv'}")
    return 0 if all(r.status == "done" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
