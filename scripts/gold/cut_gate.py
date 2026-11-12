"""Gate for the ranker cut, over stored searches and the gold set: cut_gate.py DB [GOLD_SET]; exits 1 when it fails."""
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from pathlib import Path

GOLD_SET = Path(__file__).resolve().parents[2] / "data" / "gold" / "gold-set.json"
MIN_DROP = 40
MIN_FIRST_50 = 4
MIN_FIRST_100 = 6


def name_key(name: str) -> str:
    bare = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", bare.casefold()))


def group_key(key: str) -> str:
    tokens = key.split()
    return " ".join([tokens[0], *(t for t in tokens[1:-1] if len(t) > 1), tokens[-1]]) if len(tokens) > 2 else key


def is_cut(row: sqlite3.Row) -> bool:
    """The ranker's rule: a new-section candidate that only OpenAlex found and has no belgian_years part."""
    features = {p["feature"] for p in json.loads(row["score_parts_json"])}
    return row["section"] == "new" and set(json.loads(row["lane_ranks_json"])) == {"openalex"} \
        and "belgian_years" not in features


def pick_candidate(db: sqlite3.Connection, pick: dict, pins: dict[str, str], rows: list[sqlite3.Row]):
    """The candidate row carrying the pick: by its pinned OpenAlex person, else by group key; network first."""
    key = group_key(name_key(pick["name"]))
    pinned = pins.get(pick.get("openalex_id") or "")
    names = {r[0]: group_key(r[1]) for r in db.execute("SELECT id, name_key FROM persons")} if not pinned else {}
    found = [r for r in rows if (pinned in json.loads(r["person_ids_json"]) if pinned
                                 else any(names.get(p) == key for p in json.loads(r["person_ids_json"])))]
    return min(found, key=lambda r: (r["section"] != "network", r["rank"]), default=None)


def main(argv: list[str]) -> int:
    db = sqlite3.connect(f"file:{argv[0]}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cases = {c["question"]: c for c in json.loads(Path(argv[1] if len(argv) > 1 else GOLD_SET).read_text())["questions"]}
    reach = {(p["case"], p["name"]): p for p in json.loads((GOLD_SET.parent / "reach.json").read_text())["picks"]}
    pins = {r["value"]: r["person_id"] for r in db.execute("SELECT value, person_id FROM person_identifiers WHERE scheme = 'openalex'")}
    totals, kepts, failures, first_50, first_100, reached = [], [], [], 0, 0, 0
    for search in db.execute("SELECT id, question FROM searches ORDER BY created_at"):
        rows = db.execute("SELECT * FROM candidates WHERE search_id = ? ORDER BY section = 'new', rank", (search["id"],)).fetchall()
        if not rows:
            continue
        kept = [r for r in rows if not is_cut(r)]
        totals.append(len(rows))
        kepts.append(len(kept))
        case = cases.get(search["question"])
        print(f"search {search['id'][:8]} {case['id'] if case else '-'}: total {len(rows)}, kept {len(kept)}")
        for number, pick in enumerate(case["people"] if case else [], 1):
            pick = {**pick, **{k: v for k, v in reach.get((case["id"], pick["name"]), {}).items() if k == "openalex_id"}}
            row = pick_candidate(db, pick, pins, rows)
            if row is None:
                continue
            reached += 1
            if is_cut(row):
                failures.append(f"{case['id']} pick {number} reaches the ranker and is cut")
                print(f"  {case['id']} pick {number}: CUT")
                continue
            position = [r["person_id"] for r in kept].index(row["person_id"]) + 1
            first_50 += position <= 50
            first_100 += position <= 100
            print(f"  {case['id']} pick {number}: kept, position {position} of {len(kept)}")
    if not totals:
        sys.exit("FAIL: the database holds no search with candidates")
    median_total, median_kept = statistics.median(totals), statistics.median(kepts)
    drop = 100 * (1 - median_kept / median_total)
    print(f"median total {median_total:g}, median kept {median_kept:g}, drop {drop:.1f}%")
    print(f"picks that reach the ranker {reached}; in the first 50 {first_50}; in the first 100 {first_100}")
    if first_50 < MIN_FIRST_50:
        failures.append(f"only {first_50} picks in the first 50, need {MIN_FIRST_50}")
    if first_100 < MIN_FIRST_100:
        failures.append(f"only {first_100} picks in the first 100, need {MIN_FIRST_100}")
    if drop < MIN_DROP:
        failures.append(f"median drop {drop:.1f}% is under {MIN_DROP}%")
    print("\n".join(["FAIL"] + failures) if failures else "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
