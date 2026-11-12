"""fn-enrich: look up the records a person misses, an OpenAlex author for a seed person and ORCID employments."""
import argparse
import math
import sys
from collections import Counter
from datetime import UTC, datetime

from fn import identity, orgs
from fn.config import Settings, from_env
from fn.contracts import (
    ClaimDraft,
    DatePrecision,
    EnrichIn,
    EnrichOut,
    HttpClient,
    Lookup,
    LookupKind,
    Search,
    normalize,
    record_source,
)
from fn.lanes import openalex
from fn.steps import StepContext, fan_out, run_step
from fn.store import Store
from fn.worker import Worker

KINDS: tuple[LookupKind, ...] = ("openalex_author", "orcid_employment")
LIMIT = 200
WORKERS = 4
AUTHORS_PER_LOOKUP = 10
ORCID_API = "https://pub.orcid.org/v3.0"
PRECISION: dict[int, DatePrecision] = {1: "year", 2: "month", 3: "day"}


def queue(store: Store, kind: LookupKind) -> list[str]:
    """The records still to look up for the kind: those on kept cards first, best rank first, then the rest."""
    found = store.seed_only_persons() if kind == "openalex_author" else list(store.identifier_holders("orcid"))
    done, ranks = store.looked_up(kind), store.kept_card_ranks()
    return sorted((p for p in found if p not in done), key=lambda p: ranks.get(p, math.inf))


def failed(person_id: str, kind: LookupKind, exc: Exception) -> Lookup:
    return Lookup(person_id=person_id, kind=kind, verdict="error", detail=f"{type(exc).__name__}: {exc}")


def kept_authors(results: list[dict], name: str, org_ids: set[str]) -> list[dict]:
    """The authors whose name has the person's identity key and who have an affiliation at one of org_ids."""
    want = identity.key(name)
    return [a for a in results if want and identity.key(a.get("display_name") or "") == want
            and {openalex.org_of(f["institution"]) for f in a.get("affiliations") or []} & org_ids]


def verdict_of(person_id: str, levels: list[tuple[str, identity.Level, str]], searched: int) -> Lookup:
    """matched when identity says sure or likely of any kept author, ambiguous when only possible, else no_match."""
    found = {level for _, level, _ in levels}
    verdict = "matched" if found & {"sure", "likely"} else "ambiguous" if "possible" in found else "no_match"
    detail = ("; ".join(f"{author} {level} {reason}" for author, level, reason in levels)
              or f"{searched} authors found by name, none with the key at the person's orgs")
    return Lookup(person_id=person_id, kind="openalex_author", verdict=verdict, detail=detail)


def authors(ctx: StepContext, people: list[str]) -> list[Lookup]:
    """One OpenAlex author search by name per seed record; each kept author is stored as its own record.

    The kept authors' last known institutions come in one batched call, for their location.
    """
    persons = ctx.store.get_persons(people)
    org_ids: dict[str, set[str]] = {}
    for claim in ctx.store.claims_of(people):
        if claim.kind == "affiliation" and claim.org_id:
            org_ids.setdefault(claim.person_id, set()).add(claim.org_id)
    bodies = fan_out(lambda p: ctx.http.get(f"{openalex.API}/authors", {
        "search": persons[p].display_name, "per_page": str(AUTHORS_PER_LOOKUP), "select": openalex.AUTHOR_SELECT,
    }).json(), people, WORKERS)
    kept = {p: kept_authors(b["results"], persons[p].display_name, org_ids.get(p, set()))
            for p, b in zip(people, bodies) if not isinstance(b, Exception)}
    last = [(a.get("last_known_institutions") or [None])[0] for found in kept.values() for a in found]
    inst_ids = list(dict.fromkeys(openalex.short(i["id"]) for i in last if i))
    try:
        institutions = openalex.fetch(ctx, "institutions", "openalex", inst_ids, openalex.INSTITUTION_SELECT)
        missing = None
    except Exception as exc:  # noqa: BLE001 the lookups that needed the institutions fail, the others go on
        institutions, missing = {}, exc
    found = []
    for person_id, body in zip(people, bodies):
        if isinstance(body, Exception) or (kept[person_id] and missing):
            found.append(failed(person_id, "openalex_author", body if isinstance(body, Exception) else missing))
            continue
        try:
            with ctx.store.tx():
                now = ctx.now()
                # Every kept author is stored before identity is asked, so the name's count includes them all.
                records = {openalex.short(a["id"]): openalex.save_author(ctx.store, a, institutions, now)[0].id
                           for a in kept[person_id]}
                levels = [(a, *identity.same_person(ctx.store, person_id, r)) for a, r in records.items()]
                lookup = verdict_of(person_id, levels, len(body["results"]))
                ctx.store.save_lookup(lookup, now)
            found.append(lookup)
        except Exception as exc:  # noqa: BLE001 one failed lookup is an error row, the batch goes on
            found.append(failed(person_id, "openalex_author", exc))
    return found


def date_of(when: dict | None) -> str | None:
    """An ORCID fuzzy date as YYYY, YYYY-MM or YYYY-MM-DD; None without a year."""
    parts = [((when or {}).get(p) or {}).get("value") for p in ("year", "month", "day")]
    if not parts[0]:
        return None
    return "-".join(p for p in parts[:next((i for i, p in enumerate(parts) if not p), 3)])


def employment_drafts(body: dict, orcid: str, person_id: str, now: datetime) -> list[ClaimDraft]:
    """A role claim with the job title and a works_at claim per employment without an end date.

    Both are dated by the start date and quote the employment's lines of one ORCID record source. The org id
    comes from the alias file by name, else from the ROR id ORCID gives.
    """
    open_ = [s["employment-summary"] for g in body.get("affiliation-group") or [] for s in g.get("summaries") or []
             if s.get("employment-summary") and not s["employment-summary"].get("end-date")]
    fields: list[tuple[str, object]] = []
    for n, job in enumerate(open_):
        org = job.get("organization") or {}
        ref = org.get("disambiguated-organization") or {}
        fields += [(f"employments.{n}.organization.name", org.get("name")),
                   (f"employments.{n}.organization.{ref.get('disambiguation-source')}",
                    ref.get("disambiguated-organization-identifier")),
                   (f"employments.{n}.role-title", job.get("role-title")),
                   (f"employments.{n}.start-date", date_of(job.get("start-date")))]
    modified = (body.get("last-modified-date") or {}).get("value")
    source, spans = record_source(f"https://orcid.org/{orcid}", f"ORCID record {orcid}", fields, body, now,
                                  datetime.fromtimestamp(modified / 1000, UTC).date().isoformat() if modified else None)
    drafts = []
    for n, job in enumerate(open_):
        lines = [p for p, _ in fields if p.startswith(f"employments.{n}.") and p in spans]
        name, start = normalize((job.get("organization") or {}).get("name") or ""), date_of(job.get("start-date"))
        ref = (job.get("organization") or {}).get("disambiguated-organization") or {}
        ror = ref.get("disambiguated-organization-identifier") if ref.get("disambiguation-source") == "ROR" else None
        base = {"person_id": person_id} | ({"claim_date": start, "date_precision": PRECISION[start.count("-") + 1],
                                            "date_method": "record_field", "valid_from": start} if start else {})
        if title := normalize(job.get("role-title") or ""):
            drafts.append(ClaimDraft(kind="role", value=title, **base,
                                     **openalex.quote(source, spans, f"employments.{n}.role-title", lines[-1])))
        if name:
            org_id = orgs.org_id(name) or (f"ror:{ror.rsplit('/', 1)[-1]}" if ror else None)
            drafts.append(ClaimDraft(kind="affiliation", relation="works_at", org_id=org_id, value=name, **base,
                                     **openalex.quote(source, spans, f"employments.{n}.organization.name", lines[-1])))
    return drafts


def employments(ctx: StepContext, people: list[str]) -> list[Lookup]:
    """One call to the public ORCID API per record with an ORCID, for its employments."""
    held = ctx.store.identifier_holders("orcid")
    orcids = {p: held[p].rsplit("/", 1)[-1] for p in people}
    bodies = fan_out(lambda p: ctx.http.get(f"{ORCID_API}/{orcids[p]}/employments").json(), people, WORKERS)
    found = []
    for person_id, body in zip(people, bodies):
        if isinstance(body, Exception):
            found.append(failed(person_id, "orcid_employment", body))
            continue
        try:
            with ctx.store.tx():
                now = ctx.now()
                claims = [ctx.store.upsert_claim(d, now) for d in employment_drafts(body, orcids[person_id], person_id, now)]
                lookup = Lookup(person_id=person_id, kind="orcid_employment", verdict="matched" if claims else "no_match",
                                detail=f"{len(claims)} claims from open employments")
                ctx.store.save_lookup(lookup, now)
            found.append(lookup)
        except Exception as exc:  # noqa: BLE001 one failed lookup is an error row, the batch goes on
            found.append(failed(person_id, "orcid_employment", exc))
    return found


def run(ctx: StepContext, inp: EnrichIn) -> EnrichOut:
    """Look up up to inp.limit records over the kinds in order; an error row is stored and tried again next run.

    Raises RuntimeError without an HTTP client.
    """
    if ctx.http is None:
        raise RuntimeError("fn-enrich needs an HTTP client")
    done: list[Lookup] = []
    for kind in inp.kinds:
        people = queue(ctx.store, kind)[:inp.limit - len(done)]
        if not people:
            continue
        found = (authors if kind == "openalex_author" else employments)(ctx, people)
        for lookup in found:
            if lookup.verdict == "error":
                ctx.store.save_lookup(lookup, ctx.now())
        done += found
    ctx.log.info("fn-enrich: %d lookups, %s", len(done), dict(Counter(f.verdict for f in done)))
    return EnrichOut(lookups=done)


def refresh(store: Store, settings: Settings, http: HttpClient, inp: EnrichIn) -> Search:
    """Run fn-enrich as a job: one searches row of kind job with one enrich step; returns the ended job."""
    worker = Worker(store, settings, llm=None, http=http)
    try:
        return worker.execute(worker.create_search("fn-enrich", kind="job").id,
                              lambda ctx, _: run_step(ctx, "enrich", run, inp))
    finally:
        worker.shutdown()


def main() -> int:
    from fn.net import Client

    parser = argparse.ArgumentParser(prog="fn-enrich")
    parser.add_argument("--limit", type=int, default=LIMIT, help="lookups in this run")
    parser.add_argument("--kind", choices=KINDS, help="one kind of lookup; both by default")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be 0 or more")
    settings = from_env()
    store = Store(settings.db_path)
    store.migrate()
    job = refresh(store, settings, Client(settings), EnrichIn(kinds=[args.kind] if args.kind else list(KINDS),
                                                              limit=args.limit))
    step = next(iter(store.list_steps(job.id)), None)
    if job.status != "done":
        print(f"fn-enrich job {job.id} {job.status}: " + (f"{step.error_type}: {step.error_message}" if step else str(job.error)))
        store.close()
        return 1
    out = EnrichOut.model_validate_json(store.get_payload(step.id)[1])
    persons = store.get_persons([f.person_id for f in out.lookups])
    for f in out.lookups:
        print(f"{f.kind} {f.person_id} {persons[f.person_id].display_name}: {f.verdict} ({f.detail})")
    counts = Counter(f.verdict for f in out.lookups)
    print(f"fn-enrich job {job.id} done: {len(out.lookups)} lookups; "
          + ", ".join(f"{v} {counts[v]}" for v in ("matched", "ambiguous", "no_match", "error")))
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
