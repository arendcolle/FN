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
from urllib.parse import urlsplit

from fn import config, evidence, geo, gold, identity, net, parse, present, search
from fn.config import ROOT, Settings
from fn.contracts import Candidate, Chips, GeoArea, GoldCase, GoldPick, HttpClient, Question, Search, name_key
from fn.llm import from_settings
from fn.steps import StepContext
from fn.store import Store
from fn.worker import Worker, code_state, new_id, now

SCHEMA = 1
TOP = 20
FRESH_YEARS = 5
COMPLETE = ("place", "role", "employer", "tie", "sources2")
SUMS = ("gold_at_10", "gold_at_20", "gold_at_50", "gold_found", "gold_free_at_10", "gold_free_at_20", "gold_free_at_50",
        "gold_free_found", "gold_by_construction", "doubles_top20", "doubles_top50", "pairs_wrong", "pairs_split",
        "seed_noise_top20")
PAIRS = ROOT / "data" / "gold" / "identity-pairs.jsonl"
PAIR_LABELS = ("same", "different", "unclear")
PAIR_WINDOW = 50
WAYBACK = re.compile(r"^(?:https?://)?web\.archive\.org/web/\d+[a-z_]*/(.+)$", re.IGNORECASE)
# The LinkedIn lane asks the cache only and notes "off" on a miss, so its miss is not a fault.
OFF_BY_DESIGN = "lane:linkedin"
MODES = ("rescore", "rerank", "replay")
# A gate fails when the metric moves this way from A to B; complete may fall by 0.02.
GATES = {"doubles_top20": 1, "gold_free_at_20": -1, "gold_free_found": -1, "pairs_wrong": 1, "complete": -1}
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
    if gold.pick_key(a) == gold.pick_key(b) or (ta[0], ta[-1]) == (tb[0], tb[-1]):
        return True
    first, other = sorted((ta[0], tb[0]), key=len)
    return ta[-1] == tb[-1] and len(ta) > 1 and len(tb) > 1 and len(first) == 1 and other.startswith(first)


def doubles(cards: list[dict]) -> int:
    """Pairs of cards that are likely one person: likely_same names and at least one shared org id."""
    return sum(1 for i, a in enumerate(cards) for b in cards[i + 1:] if a["orgs"] & b["orgs"] and likely_same(a["key"], b["key"]))


def topic_words(chips: Chips | None) -> list[str]:
    """The words of the topic chips as the evidence matcher looks for them."""
    return list(dict.fromkeys(w for c in (chips.topics if chips else []) for w in parse.chip_words(c.text)))


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


def card_ids(store: Store, candidate: Candidate) -> list[str]:
    """The records a kept candidate's card reads, as identity puts them on the card."""
    return identity.on_card(store, candidate)


def site(url: str) -> str:
    """The host of a URL without www., for the page a Wayback URL wraps; empty when there is none."""
    wrapped = WAYBACK.match(url.strip())
    url = wrapped.group(1) if wrapped else url.strip()
    host = urlsplit(url if "//" in url else f"//{url}").hostname or ""
    return host.casefold().removeprefix("www.")


def by_construction(store: Store, case: GoldCase, pick: GoldPick, hit: Candidate) -> bool:
    """Whether a record on the pick's card has a seed page from a site that the case source or the pick's sources name."""
    named = {site(u) for u in (case.source_url, *pick.sources) if u} - {""}
    sources = store.get_sources([c.source_id for c in store.claims_of(card_ids(store, hit))])
    return bool(named & {site(s.url) for s in sources.values() if s.kind == "seed_page"})


def within(picks: list[dict], k: int) -> int:
    return sum(p["position"] is not None and p["position"] <= k for p in picks)


def gold_metrics(store: Store, case: GoldCase, kept: list) -> dict:
    """Where each pick of the case sits in the kept list, as ids like GS-02#1, and the counts at 10, 20 and 50.

    The gold_free counts leave out the picks a seed list of the case's own sites names by construction.
    """
    persons = store.get_persons([p for c in kept for p in c.person_ids])
    pins = store.person_ids_by_identifier("openalex", [p.openalex_id for p in case.picks if p.openalex_id])
    found = []
    for n, pick in enumerate(case.picks, 1):
        hit = gold.match(pick, kept, persons, pins.get(pick.openalex_id or ""))
        found.append({"id": f"{case.id}#{n}", "position": kept.index(hit) + 1 if hit else None,
                      "by_construction": bool(hit and by_construction(store, case, pick, hit))})
    free = [f for f in found if not f["by_construction"]]
    return {"gold_picks": found, **{f"gold_at_{k}": within(found, k) for k in (10, 20, 50)},
            "gold_found": sum(f["position"] is not None for f in found),
            **{f"gold_free_at_{k}": within(free, k) for k in (10, 20, 50)},
            "gold_free_found": sum(f["position"] is not None for f in free),
            "gold_by_construction": sum(f["by_construction"] for f in found)}


def load_pairs(path: Path) -> list[dict] | None:
    """The labelled pairs of the file, or None when it is absent; blank lines are skipped.

    Raises ValueError naming the path and line for a line that is not an object with string a and b and a known label.
    """
    if not path.is_file():
        return None
    pairs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            pair = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: not JSON ({exc.msg})") from exc
        if not (isinstance(pair, dict) and all(isinstance(pair.get(k), str) for k in ("a", "b"))
                and pair.get("label") in PAIR_LABELS):
            raise ValueError(f"{path}:{n}: needs a and b as ids and label same, different or unclear")
        pairs.append(pair)
    return pairs


def pair_metrics(store: Store, kept: list, pairs: list[dict]) -> dict:
    """pairs_wrong: different pairs on one kept card. pairs_split: same pairs on two cards, both in the first 50.

    A pair with an id the database does not hold is skipped, and so is an unclear one.
    """
    known = store.get_persons([i for p in pairs for i in (p["a"], p["b"])])
    cards = [set(card_ids(store, c)) for c in kept]
    wrong = split = 0
    for pair in pairs:
        if pair["label"] == "unclear" or not {pair["a"], pair["b"]} <= known.keys():
            continue
        at_a, at_b = ({i for i, card in enumerate(cards) if x in card} for x in (pair["a"], pair["b"]))
        if pair["label"] == "different":
            wrong += bool(at_a & at_b)
        else:
            split += bool(at_a and at_b and not at_a & at_b and min(at_a) < PAIR_WINDOW and min(at_b) < PAIR_WINDOW)
    return {"pairs_wrong": wrong, "pairs_split": split}


def card_metrics(store: Store, scored: Search, kept: list, created: date, area: GeoArea | None) -> dict:
    """The doubles counts, the card shares of the first TOP cards, and the place, group and lane shares.

    A card's place is evidence's place of its records, so the city of a recent employer counts.
    """
    top = kept[:50]
    ids = [card_ids(store, c) for c in top]
    views = present.person_views(store, ids, created, [c.reason_claim_ids for c in top])
    by_person: dict[str, list] = {}
    for claim in store.claims_of([p for found in ids for p in found]):
        by_person.setdefault(claim.person_id, []).append(claim)
    facts = store.get_orgs(list({x.org_id for found in by_person.values() for x in found if x.org_id}))
    schemes = {p: frozenset(i.scheme for i in found) for p, found in store.identifiers_of([p for f in ids for p in f]).items()}
    question = Question(chips=scored.chips or Chips(), area=area)
    words = topic_words(scored.chips)
    cards = []
    for c, view, records in zip(top, views, ids, strict=True):
        claims = [x for p in records for x in by_person.get(p, [])]
        text = " ".join(f"{x.value} {x.quote}" for x in claims)
        found = evidence.of({p: schemes.get(p, frozenset()) for p in records}, claims, facts, question, created)
        card = {
            "key": name_key(view.name), "orgs": {x.org_id for x in claims if x.org_id}, "lanes": set(c.lane_ranks),
            "place": view.place is not None, "role": view.role is not None, "employer": view.employer is not None,
            "tie": view.evidence is not None or bool(view.orgs), "sources2": len({x.source_id for x in claims}) >= 2,
            "fresh": fresh(claims, view.employer, created), "topic": bool(words and parse.words_in(words, text)),
            "where": found.place.fit if area else None, "group0": c.group == 0,
        }
        cards.append(card | {"complete": all(card[f] for f in COMPLETE)})
    first, out = cards[:TOP], {"doubles_top20": doubles(cards[:20]), "doubles_top50": doubles(cards)}
    out["seed_noise_top20"] = 0 if scored.chips and scored.chips.institutions else sum(
        x["lanes"] == {"seeds"} and not x["topic"] for x in first)
    flags = {f: lambda x, f=f: x[f] for f in (*COMPLETE, "complete", "fresh")}
    flags |= {f"place_{w}": lambda x, w=w: x["where"] == w for w in ("inside", "outside", "unknown")} if area else {}
    flags |= {"topic": lambda x: x["topic"]} if words else {}
    flags |= {"group0_top20": lambda x: x["group0"]}
    flags |= {"lane_openalex_only": lambda x: x["lanes"] == {"openalex"}, "lane_seeds_only": lambda x: x["lanes"] == {"seeds"},
              "lane_web_only": lambda x: x["lanes"] == {"web"}, "lane_multi": lambda x: len(x["lanes"]) >= 2}
    return out | {name: share(sum(bool(test(x)) for x in first), len(first)) for name, test in flags.items() if first}


def cut_seed(store: Store, candidates: list[Candidate]) -> list[str]:
    """The 12-character ids of the records on cut cards that hold a seed-list record, without those on a kept card."""
    records = {id(c): c.card_person_ids or c.hit_person_ids or c.person_ids[:1] for c in candidates}
    cut = [c for c in candidates if c.cut_reason]
    schemes = store.identifiers_of([p for c in cut for p in records[id(c)]])
    seeded = {p[:12] for c in cut if any(i.scheme == "seed" for p in records[id(c)] for i in schemes.get(p, []))
              for p in records[id(c)]}
    return sorted(seeded - {p[:12] for c in candidates if not c.cut_reason for p in records[id(c)]})


def score_search(store: Store, scored: Search, stored: Search, case: GoldCase | None, names: geo.Names | None,
                 pairs: list[dict] | None = None) -> dict:
    """The metrics of scored's kept candidates; stored supplies the date that freshness counts from.

    pairs are the labelled identity pairs; without them the pair metrics are left out. cut_seed lists the ids
    that compare looks for in the other scorecard's first 20.
    """
    every = store.list_candidates(scored.id)
    kept = [c for c in every if not c.cut_reason]
    place = scored.chips.place if scored.chips else None
    area = geo.locate(place.text, names) if place and names and place.kind in geo.METRO_KINDS else None
    row = ({"question_sha256": hashlib.sha256(stored.question.encode()).hexdigest(), "gold_case": case.id if case else None,
            "kept": len(kept)} | ({"cut_seed": cut_seed(store, every)} if every else {})
           | (gold_metrics(store, case, kept) if case else {}))
    if not kept:
        return row
    top20 = [{"id": c.person_id[:12], "rank": n, "lanes": sorted(c.lane_ranks), "parts": [p.feature for p in c.score_parts]}
             for n, c in enumerate(kept[:TOP], 1)]
    return (row | card_metrics(store, scored, kept, stored.created_at.date(), area)
            | (pair_metrics(store, kept, pairs) if pairs is not None else {}) | {"top20": top20})


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


def rerank(store: Store, stored: Search, settings: Settings, http: HttpClient | None = None) -> bool:
    """Run search.refinish over the stored lane outputs and chips; True when the run is degraded."""
    known = {s.id for s in store.list_steps(stored.id)}
    try:
        ctx = StepContext(search_id=stored.id, store=store, llm=None, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.score"), settings=settings)
        search.refinish(ctx, stored)
    except Exception:  # noqa: BLE001 any failure marks the search degraded and the scorecard goes on
        return True
    return degraded(store, stored.id, known)


def replay(worker: Worker, stored: Search) -> tuple[Search, bool]:
    """A new search with the stored question and chips from fixtures and cache; it and whether the run is degraded."""
    new = worker.execute(worker.create_search(stored.question, stored.chips, stored.chips_origin, rerun_of=stored.id).id)
    return new, new.status != "done" or degraded(worker.store, new.id, set())


def run(snap: Path, mode: str, out: Path, allow_degraded: bool) -> int:
    """Score the snapshot's searches in a temporary copy of its database and write scorecard.json and scorecard.md.

    Returns 2 when a search is degraded and allow_degraded is not set, else 0. The snapshot is never written.
    Raises ValueError naming the line of a malformed pair file.
    """
    pairs = load_pairs(PAIRS)
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
                is_bad = rerank(store, stored, settings, client)
            elif mode == "replay":
                scored, is_bad = replay(worker, stored)
            rows[key] = score_search(store, scored, stored, cases.get(stored.question), names, pairs)
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


def seed_cuts(a: dict, b: dict) -> int | None:
    """The first-20 cards of A that B cut although they hold a seed-list record; None when B lists no cut_seed."""
    skip = set(a["meta"]["degraded"]) | set(b["meta"]["degraded"])
    keys = [k for k in sorted(a["searches"].keys() & b["searches"].keys() - skip) if "cut_seed" in b["searches"][k]]
    if not keys:
        return None
    return sum(len({p["id"] for p in a["searches"][k].get("top20", [])} & set(b["searches"][k]["cut_seed"])) for k in keys)


def compare(path_a: Path, path_b: Path) -> int:
    """Print the aggregate metrics that changed, cut_seed_top20 and the gold picks that moved; 1 when a gate fails.

    cut_seed_top20 fails when it is above 0.
    """
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
    if (seed := seed_cuts(a, b)) is not None:
        print(f"cut_seed_top20: {seed}")
        failed += ["cut_seed_top20"] if seed else []
    lines = moved_picks(a, b)
    print("gold picks moved:\n" + "\n".join(lines) if lines else "no gold picks moved")
    for name in failed:
        print(f"GATE FAILED: {name}")
    return 1 if failed else 0


def names_of(snap: Path, ids: set[str]) -> dict[str, str]:
    """The display name of each 12-character id prefix the snapshot database holds, read-only."""
    db = sqlite3.connect(f"file:{snap / 'fn.sqlite3'}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT substr(id, 1, 12), display_name FROM persons WHERE substr(id, 1, 12) IN "
                          "(SELECT value FROM json_each(?))", (json.dumps(sorted(ids)),))
        return dict(rows)
    finally:
        db.close()


def diff(path_a: Path, path_b: Path, snap: Path | None) -> int:
    """Print, per search both scorecards hold, who entered and who left the first 20, with rank, lanes and parts.

    Names come from the snapshot at snap and go to the terminal only. Searches degraded in either file or
    without a top20 list are skipped and named in one line.
    """
    a, b = (json.loads(p.read_text()) for p in (path_a, path_b))
    skip = set(a["meta"]["degraded"]) | set(b["meta"]["degraded"])
    keys = [k for k in sorted(a["searches"].keys() & b["searches"].keys() - skip)
            if "top20" in a["searches"][k] and "top20" in b["searches"][k]]
    tops = {k: ({p["id"]: p for p in a["searches"][k]["top20"]}, {p["id"]: p for p in b["searches"][k]["top20"]}) for k in keys}
    names = names_of(snap, {i for old, new in tops.values() for i in old.keys() ^ new.keys()}) if snap else {}
    if skipped := sorted((a["searches"].keys() & b["searches"].keys()) - set(keys)):
        print(f"skipped, degraded or without a first-20 list: {', '.join(skipped)}")
    if not keys:
        print("no search with a top20 list in both files")
    for key in keys:
        old, new = tops[key]
        print(f"search {key}: {len(new.keys() - old.keys())} entered, {len(old.keys() - new.keys())} left")
        for label, ids in (("entered", new.keys() - old.keys()), ("left", old.keys() - new.keys())):
            for i in sorted(ids, key=lambda i: (new.get(i) or old[i])["rank"]):
                row = new.get(i) or old[i]
                print(f"  {label} {i}{' ' + names[i] if i in names else ''}: rank A {old[i]['rank'] if i in old else '-'}, "
                      f"B {new[i]['rank'] if i in new else '-'}, lanes {','.join(row['lanes'])}, parts {','.join(row['parts'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """fn-score snapshot DIR [--llm DIR ...] | run DIR --mode MODE --out DIR [--allow-degraded] | compare A.json B.json
    | diff A.json B.json [--names SNAPSHOT_DIR].

    Returns 0, 1 when a compare gate fails, 2 for a degraded run, a snapshot dir that is not empty or a bad pair file.
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
    dif = sub.add_parser("diff")
    dif.add_argument("a", type=Path)
    dif.add_argument("b", type=Path)
    dif.add_argument("--names", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "compare":
        return compare(args.a, args.b)
    if args.command == "diff":
        return diff(args.a, args.b, args.names)
    if args.command == "run":
        try:
            return run(args.dir, args.mode, args.out, args.allow_degraded)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
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
