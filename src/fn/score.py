"""fn-score: score the searches of a frozen snapshot with this checkout's code, and compare two scorecards."""
import argparse
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

from fn import config, geo, gold, net, present, search
from fn.config import ROOT, Settings
from fn.contracts import Chips, GeoArea, GoldCase, LaneOut, Search, group_key, name_key
from fn.llm import from_settings
from fn.steps import StepContext
from fn.store import Store
from fn.worker import Worker, code_state, new_id, now

SCHEMA = 1
TOP = 20
FRESH_YEARS = 5
COMPLETE = ("place", "role", "employer", "tie", "sources2")
SUMS = ("gold_at_10", "gold_at_20", "gold_at_50", "gold_found", "doubles_top20", "doubles_top50")
STOP = {"the", "and", "for", "with", "of", "in", "on", "at", "to", "a", "an", "us", "usa", "from", "their", "who", "has"}
# The LinkedIn lane asks the cache only and notes "off" on a miss, so its miss is not a fault.
OFF_BY_DESIGN = "lane:linkedin"
MODES = ("rescore", "rerank", "replay")
# A gate fails when the metric moves this way from A to B; complete may fall by 0.02.
GATES = {"doubles_top20": 1, "gold_at_20": -1, "gold_found": -1, "complete": -1}
COMPLETE_SLACK = 0.02


def share(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def snapshot(settings: Settings, dest: Path, extra: list[Path]) -> None:
    """Freeze the database, the response cache and every LLM fixture into dest, which must be empty or new.

    The database is copied with the SQLite backup API from a read-only connection. Raises FileExistsError
    for a dest that holds files.
    """
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    (dest / "llm").mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    target = sqlite3.connect(dest / "fn.sqlite3")
    with target:
        source.backup(target)
    source.close()
    target.close()
    if (settings.var_dir / "cache").is_dir():
        shutil.copytree(settings.var_dir / "cache", dest / "cache")
    for folder in (settings.fixtures_dir, settings.var_dir / "llm", *extra):
        for path in folder.glob("*.json"):
            shutil.copyfile(path, dest / "llm" / path.name)


def cities(cache: Path) -> geo.Names | None:
    """The GeoNames index from the snapshot's response cache; None if the download is not cached."""
    body = net.cached_get(cache, geo.CITIES_URL)
    return geo.from_zip(body) if body is not None else None


def likely_same(a: str, b: str) -> bool:
    """Whether two name keys read as one person: equal group keys, equal first and last tokens, or one surname
    with first names equal or one an initial of the other."""
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return False
    if group_key(a) == group_key(b) or (ta[0], ta[-1]) == (tb[0], tb[-1]):
        return True
    first, other = sorted((ta[0], tb[0]), key=len)
    return ta[-1] == tb[-1] and len(ta) > 1 and len(tb) > 1 and len(first) == 1 and other.startswith(first)


def doubles(cards: list[dict]) -> int:
    """Pairs of cards that are likely one person: likely_same names and at least one shared org id."""
    return sum(1 for i, a in enumerate(cards) for b in cards[i + 1:] if a["orgs"] & b["orgs"] and likely_same(a["key"], b["key"]))


def topic_pattern(chips: Chips | None) -> re.Pattern | None:
    """A pattern for the topic chip words (stop words and single letters dropped) at a word start, or None."""
    found = {w for c in (chips.topics if chips else []) for w in re.findall(r"[^\W_]+", c.text.casefold())
             if w not in STOP and len(w) > 1}
    return re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(found))) + ")", re.IGNORECASE) if found else None


def fresh(claims: list, employer: str | None, created: date) -> bool:
    """Whether the newest claim for the employer is dated on or after created minus FRESH_YEARS years.

    The date is valid_to or claim_date: YYYY, YYYY-MM or YYYY-MM-DD, padded to its first day.
    """
    jobs = [c for c in claims if c.relation in present.EMPLOYED and c.value == employer]
    newest = max(jobs, key=lambda c: (c.valid_to or c.claim_date or "", c.claim_date or ""), default=None)
    stamp = (newest.valid_to or newest.claim_date or "") if newest else ""
    try:
        claimed = date.fromisoformat(stamp + "-01-01"[max(len(stamp) - 4, 0):] if len(stamp) in (4, 7) else stamp)
    except ValueError:
        return False
    return (claimed.year, claimed.month, claimed.day) >= (created.year - FRESH_YEARS, created.month, created.day)


def place_class(claims: list, area: GeoArea) -> str:
    """inside when a located claim lies within the metro radius, outside when there are located claims and none do."""
    spots = [(c.lat, c.lon) for c in claims if c.lat is not None and c.lon is not None and c.relation != "born_in"]
    if not spots:
        return "unknown"
    return "inside" if any(geo.distance_km(area.lat, area.lon, la, lo) <= geo.METRO_RADIUS_KM for la, lo in spots) else "outside"


def gold_metrics(store: Store, case: GoldCase, kept: list) -> dict:
    """Where each pick of the case sits in the kept list, as ids like GS-02#1 and the counts at 10, 20 and 50."""
    persons = store.get_persons([p for c in kept for p in c.person_ids])
    pins = store.person_ids_by_identifier("openalex", [p.openalex_id for p in case.picks if p.openalex_id])
    found = []
    for n, pick in enumerate(case.picks, 1):
        hit = gold.match(pick, kept, persons, pins.get(pick.openalex_id or ""))
        found.append({"id": f"{case.id}#{n}", "position": kept.index(hit) + 1 if hit else None})
    at = {k: sum(f["position"] is not None and f["position"] <= k for f in found) for k in (10, 20, 50)}
    return {"gold_picks": found, **{f"gold_at_{k}": n for k, n in at.items()},
            "gold_found": sum(f["position"] is not None for f in found)}


def card_metrics(store: Store, scored: Search, kept: list, created: date, area: GeoArea | None) -> dict:
    """The doubles counts, the card shares of the first TOP cards, and the place and lane shares."""
    top = kept[:50]
    views = present.person_views(store, [present.hits_of(c) for c in top], created, [c.reason_claim_ids for c in top])
    by_person: dict[str, list] = {}
    for claim in store.claims_of([p for c in top for p in present.hits_of(c)]):
        by_person.setdefault(claim.person_id, []).append(claim)
    pattern = topic_pattern(scored.chips)
    cards = []
    for c, view in zip(top, views, strict=True):
        claims = [x for p in present.hits_of(c) for x in by_person.get(p, [])]
        text = " ".join(f"{x.value} {x.quote}" for x in claims)
        card = {
            "key": name_key(view.name), "orgs": {x.org_id for x in claims if x.org_id}, "lanes": set(c.lane_ranks),
            "place": view.place is not None, "role": view.role is not None, "employer": view.employer is not None,
            "tie": view.evidence is not None or bool(view.orgs), "sources2": len({x.source_id for x in claims}) >= 2,
            "fresh": fresh(claims, view.employer, created), "topic": bool(pattern and pattern.search(text)),
            "where": place_class(claims, area) if area else None,
        }
        cards.append(card | {"complete": all(card[f] for f in COMPLETE)})
    first, out = cards[:TOP], {"doubles_top20": doubles(cards[:20]), "doubles_top50": doubles(cards)}
    flags = {f: lambda x, f=f: x[f] for f in (*COMPLETE, "complete", "fresh")}
    flags |= {f"place_{w}": lambda x, w=w: x["where"] == w for w in ("inside", "outside", "unknown")} if area else {}
    flags |= {"topic": lambda x: x["topic"]} if pattern else {}
    flags |= {"lane_openalex_only": lambda x: x["lanes"] == {"openalex"}, "lane_seeds_only": lambda x: x["lanes"] == {"seeds"},
              "lane_web_only": lambda x: x["lanes"] == {"web"}, "lane_multi": lambda x: len(x["lanes"]) >= 2}
    return out | {name: share(sum(bool(test(x)) for x in first), len(first)) for name, test in flags.items() if first}


def score_search(store: Store, scored: Search, stored: Search, case: GoldCase | None, names: geo.Names | None) -> dict:
    """The metrics of scored's kept candidates; stored supplies the date that freshness counts from."""
    kept = store.list_candidates(scored.id, kept_only=True)
    place = scored.chips.place if scored.chips else None
    area = geo.locate(place.text, names) if place and names and place.kind in geo.METRO_KINDS else None
    row = {"question_sha256": hashlib.sha256(stored.question.encode()).hexdigest(), "gold_case": case.id if case else None,
           "kept": len(kept)} | (gold_metrics(store, case, kept) if case else {})
    return row | (card_metrics(store, scored, kept, stored.created_at.date(), area) if kept else {})


def step_seconds(store: Store, stored: Search) -> dict[str, float]:
    """Seconds per step name of a stored search, summed over steps of one name."""
    out: dict[str, float] = {}
    for step in store.list_steps(stored.id):
        if step.ended_at:
            out[step.step] = out.get(step.step, 0.0) + (step.ended_at - step.started_at).total_seconds()
    return {name: round(sec, 4) for name, sec in out.items()}


def degraded(store: Store, search_id: str, known: set[str]) -> bool:
    """Whether a step the run added (not in known) failed, logged FixtureMissing or had a response cache error.

    The LinkedIn lane's cache miss does not count.
    """
    for step in store.list_steps(search_id):
        if step.id in known:
            continue
        if step.status not in ("ok", "skipped") or "FixtureMissing" in step.log:
            return True
        if step.step != OFF_BY_DESIGN and any("response cache" in (call.error or "") for call in store.list_calls(step.id)):
            return True
    return False


def rerank(store: Store, stored: Search, settings: Settings) -> bool:
    """Run search.finish over the stored lane outputs and chips; True when the run is degraded."""
    known = {s.id for s in store.list_steps(stored.id)}
    outs = []
    try:
        for step in (s for s in store.list_steps(stored.id) if s.step.startswith("lane:")):
            output = store.get_payload(step.id)[1] if step.status == "ok" else None
            outs.append(LaneOut.model_validate_json(output) if output else LaneOut(lane=step.step[5:], query="", total_seen=0))
        ctx = StepContext(search_id=stored.id, store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.score"), settings=settings)
        search.finish(ctx, outs, stored.chips)
    except Exception:  # noqa: BLE001 any failure marks the search degraded and the scorecard goes on
        return True
    return degraded(store, stored.id, known)


def replay(worker: Worker, stored: Search) -> tuple[Search, bool]:
    """A new search with the stored question and chips from fixtures and cache; it and whether the run is degraded."""
    new = worker.execute(worker.create_search(stored.question, stored.chips, stored.chips_origin).id)
    return new, new.status != "done" or degraded(worker.store, new.id, set())


def run(snap: Path, mode: str, out: Path, allow_degraded: bool) -> int:
    """Score the snapshot's searches in a temporary copy of its database and write scorecard.json and scorecard.md.

    Returns 2 when a search is degraded and allow_degraded is not set, else 0. The snapshot is never written.
    """
    sha, dirty = code_state(ROOT)
    cases = {c.question: c for c in gold.load_cases([])}
    names = cities(snap / "cache")
    rows, live, bad, skipped = {}, {}, [], []
    with tempfile.TemporaryDirectory(prefix="fn-score-") as tmp:
        var = Path(tmp)
        shutil.copyfile(snap / "fn.sqlite3", var / "fn.sqlite3")
        (var / "cache").symlink_to((snap / "cache").resolve())
        settings = Settings(var_dir=var, llm_mode="replay", http_mode="replay", fixtures_dir=snap / "llm")
        store = Store(settings.db_path)
        store.migrate()
        client = net.Client(settings)
        worker = Worker(store, settings, llm=from_settings(settings), http=client)
        for stored in store.list_searches(None):
            key = stored.id[:8]
            if stored.status != "done":
                skipped.append(key)
                continue
            if stored.llm_mode == "live":
                live[key] = step_seconds(store, stored)
            scored, is_bad = stored, False
            if mode == "rerank":
                is_bad = rerank(store, stored, settings)
            elif mode == "replay":
                scored, is_bad = replay(worker, stored)
            rows[key] = score_search(store, scored, stored, cases.get(stored.question), names)
            if is_bad:
                bad.append(key)
        client.http.close()
        store.close()
    result = {
        "schema": SCHEMA, "aggregate": aggregate({k: r for k, r in rows.items() if k not in bad}), "searches": rows,
        "live_step_seconds": live,
        "meta": {"git_sha": sha, "dirty": dirty, "mode": mode, "snapshot": str(snap), "degraded": sorted(bad),
                 "skipped": sorted(skipped)},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (out / "scorecard.md").write_text(markdown(result["aggregate"]))
    if bad:
        print(f"degraded searches: {', '.join(sorted(bad))}", file=sys.stderr)
    return 2 if bad and not allow_degraded else 0


def aggregate(rows: dict[str, dict]) -> dict[str, float]:
    """Each metric over the searches that have it: the sum for gold and double counts, the median for kept
    (over searches with results), else the mean."""
    values: dict[str, list[float]] = {}
    for row in rows.values():
        for name, value in row.items():
            if isinstance(value, int | float) and (name != "kept" or value):
                values.setdefault(name, []).append(value)
    agg = {name: sum(v) if name in SUMS else statistics.median(v) if name == "kept" else statistics.fmean(v)
           for name, v in values.items()}
    return {name: round(v, 4) for name, v in sorted(agg.items())} | {"searches": len(rows)}


def markdown(agg: dict[str, float]) -> str:
    return "\n".join(["| metric | value |", "| --- | --- |", *(f"| {k} | {v} |" for k, v in sorted(agg.items()))]) + "\n"


def moved_picks(a: dict, b: dict) -> list[str]:
    """One line per gold pick whose position differs between the two scorecards, by search key and pick id."""
    skip = set(a["meta"]["degraded"]) | set(b["meta"]["degraded"])
    lines = []
    for key in sorted(a["searches"].keys() & b["searches"].keys() - skip):
        old = {p["id"]: p["position"] for p in a["searches"][key].get("gold_picks", [])}
        new = {p["id"]: p["position"] for p in b["searches"][key].get("gold_picks", [])}
        lines += [f"  {pick} (search {key}): {old[pick]} -> {new.get(pick)}" for pick in old if old[pick] != new.get(pick)]
    return lines


def compare(path_a: Path, path_b: Path) -> int:
    """Print the aggregate metrics that changed and the gold picks that moved; 1 when a gate fails, else 0."""
    a, b = (json.loads(p.read_text()) for p in (path_a, path_b))
    old, new = a["aggregate"], b["aggregate"]
    failed = []
    for name in sorted(old.keys() | new.keys()):
        if old.get(name) != new.get(name):
            delta = round(new[name] - old[name], 4) if name in old and name in new else None
            print(f"{name}: {old.get(name)} -> {new.get(name)}" + (f" ({delta:+})" if delta is not None else ""))
            if delta is not None and name in GATES and delta * GATES[name] > (COMPLETE_SLACK if name == "complete" else 0):
                failed.append(name)
    for name in sorted(GATES.keys() & (old.keys() - new.keys())):
        print(f"{name} is missing in {path_b}")
        failed.append(name)
    lines = moved_picks(a, b)
    print("gold picks moved:\n" + "\n".join(lines) if lines else "no gold picks moved")
    for name in failed:
        print(f"GATE FAILED: {name}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """fn-score snapshot DIR [--llm DIR ...] | run DIR --mode MODE --out DIR [--allow-degraded] | compare A.json B.json.

    Returns 0, 1 when a compare gate fails, 2 for a degraded run or a snapshot dir that is not empty.
    """
    parser = argparse.ArgumentParser(prog="fn-score")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("dir", type=Path)
    snap.add_argument("--llm", type=Path, action="append", default=[])
    go = sub.add_parser("run")
    go.add_argument("dir", type=Path)
    go.add_argument("--mode", choices=MODES, required=True)
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--allow-degraded", action="store_true")
    cmp = sub.add_parser("compare")
    cmp.add_argument("a", type=Path)
    cmp.add_argument("b", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "compare":
        return compare(args.a, args.b)
    if args.command == "run":
        return run(args.dir, args.mode, args.out, args.allow_degraded)
    if bad := next((p for p in args.llm if not p.is_dir()), None):
        print(f"{bad} is not a directory", file=sys.stderr)
        return 2
    try:
        snapshot(config.from_env(), args.dir, args.llm)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
