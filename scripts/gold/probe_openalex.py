# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx"]
# ///
"""One-off probe that records OpenAlex responses for the GS-02 and GS-10 picks and writes data/gold/reach.json."""
import json
import os
import re
import subprocess
import time
import unicodedata
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "http" / "openalex"
REACH = ROOT / "data" / "gold" / "reach.json"
SEEDS = ROOT / "data" / "seeds"
BASE = "https://api.openalex.org"
CALL_LIMIT = 60
MIT_ROR = "https://ror.org/042nb2s44"
WORK_SELECT = "id,display_name,publication_year,authorships"
INSTITUTION_SELECT = "id,display_name,ror,country_code,type,geo,lineage"

# Chips as the parse step is expected to give them for each case.
CASES = {
    "GS-02": {
        "topics": ["telecommunications", "6G", "wireless"],
        "institutions": [],
        "seed_terms": [r"telecom", r"\b6g\b", r"wireless"],
    },
    "GS-10": {
        "topics": [],
        "institutions": ["MIT"],
        "seed_terms": [r"\bmit\b", r"m\.i\.t\.", r"massachusetts institute of technology"],
    },
}

# Author ids were chosen by reading the author_search_* responses; only the Deconinck match is unconfirmed.
PICKS = [
    ("GS-02", "Wim Sweldens", "flemish", "A5035336231", ""),
    ("GS-02", "Yves Baeyens", "flemish", "A5063711273", ""),
    ("GS-02", "Peter Vetter", "flemish", "A5069633689", ""),
    ("GS-02", "Thierry Klein", "none", "A5112227257", ""),
    ("GS-10", "Michel Goemans", "belgian", "A5112864313", ""),
    ("GS-10", "Pierre Lermusiaux", "belgian", "A5062670983", ""),
    ("GS-10", "Julien de Wit", "belgian", "A5008973078", ""),
    ("GS-10", "Milena Janjevic", "belgian", "A5022179613", ""),
    ("GS-10", "Anne Deconinck", "belgian", "A5071555585", "identity with the consul is plausible (MIT, Harvard, biotech) but unconfirmed"),
]

calls = 0
index: dict[str, dict] = {}


def api_key() -> str:
    """Read the OpenAlex key from the env var, else the macOS Keychain. Raises when it is empty; never prints it."""
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key:
        done = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ["USER"], "-s", "OPENALEX_API_KEY", "-w"],
            capture_output=True, text=True, check=True,
        )
        key = done.stdout.strip()
    if not key:
        raise RuntimeError("OPENALEX_API_KEY is empty in the environment and the Keychain")
    return key


def fetch(client: httpx.Client, name: str, path: str, params: dict) -> dict:
    """GET one OpenAlex list call, save the raw body as <name>.json, and return the parsed body.

    Raises RuntimeError past CALL_LIMIT and httpx.HTTPStatusError on a non-2xx answer.
    """
    global calls
    if calls >= CALL_LIMIT:
        raise RuntimeError(f"call limit of {CALL_LIMIT} reached before {name}")
    calls += 1
    response = client.get(BASE + path, params=params)
    response.raise_for_status()
    (FIXTURES / f"{name}.json").write_bytes(response.content)
    body = response.json()
    index[name] = {
        "file": f"{name}.json",
        "path": path,
        "params": params,
        "status": response.status_code,
        "count": body.get("meta", {}).get("count"),
        "bytes": len(response.content),
        "fetched": date.today().isoformat(),
    }
    time.sleep(0.2)
    return body


def short(openalex_id: str) -> str:
    return openalex_id.rsplit("/", 1)[-1]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))


def first_last(name: str) -> tuple[str, str]:
    tokens = fold(name).replace(".", " ").split()
    return tokens[0], tokens[-1]


def institution_ids(authors: list[dict]) -> list[str]:
    """Institutions to fetch: last known and every Belgian one, plus the newest affiliation as evidence for the no-fallback note."""
    wanted: set[str] = set()
    for author in authors:
        wanted.update(short(i["id"]) for i in author["last_known_institutions"] or [])
        affiliations = author["affiliations"]
        if affiliations:
            newest = max(affiliations, key=lambda a: max(a["years"] or [0]))
            wanted.add(short(newest["institution"]["id"]))
        wanted.update(short(a["institution"]["id"]) for a in affiliations if a["institution"]["country_code"] == "BE")
    return sorted(wanted)


def record_calls(client: httpx.Client) -> dict:
    """Make every call and return the author ids each query reached, in result order."""
    reached: dict[str, list[str]] = {}
    for _, name, _, _, _ in PICKS:
        fetch(client, f"author_search_{slug(name)}", "/authors", {"search": name, "per_page": 6})
    for topic in CASES["GS-02"]["topics"]:
        body = fetch(client, f"works_topic_{slug(topic)}", "/works", {
            "search": topic, "filter": "institutions.country_code:BE", "per_page": 100, "select": WORK_SELECT,
        })
        reached[f"works_topic_{slug(topic)}"] = [
            short(a["author"]["id"]) for w in body["results"] for a in w["authorships"] if a["author"]["id"]
        ]
    page, seen = 1, 0
    while True:
        body = fetch(client, f"authors_institution_mit_p{page}", "/authors", {
            "filter": f"last_known_institutions.ror:{MIT_ROR},affiliations.institution.country_code:BE",
            "per_page": 200, "page": page, "select": "id,display_name",
        })
        reached[f"authors_institution_mit_p{page}"] = [short(a["id"]) for a in body["results"]]
        seen += len(body["results"])
        if seen >= body["meta"]["count"] or not body["results"] or page >= 4:
            break
        page += 1
    batch = fetch(client, "authors_batch_picks", "/authors", {
        "filter": "ids.openalex:" + "|".join(p[3] for p in PICKS), "per_page": 50,
    })
    fetch(client, "institutions_batch_picks", "/institutions", {
        "filter": "openalex:" + "|".join(institution_ids(batch["results"])), "per_page": 100, "select": INSTITUTION_SELECT,
    })
    return reached


def seed_rows() -> list[dict]:
    return [json.loads(line) for path in sorted(SEEDS.glob("*.jsonl")) for line in path.read_text().splitlines()]


def seed_evidence(case: str, name: str, rows: list[dict]) -> dict:
    """Seed lane reach, approximated as a regex match of the case's chip terms on each row's text."""
    first, last = first_last(name)
    own = [r for r in rows if first_last(r["name"]) == (first, last)]
    if not own:
        return {"reachable": False, "files": [], "evidence": "no seed row with this name"}
    for row in own:
        text = " ".join(filter(None, [
            row["quote"], row["field"], row["role"], row["place"], *(i["name"] for i in row["institutions"]),
        ])).casefold()
        matched = [t for t in CASES[case]["seed_terms"] if re.search(t, text)]
        if matched:
            return {"reachable": True, "files": [row["row_key"]], "evidence": f"seed row {row['row_key']} text matches {matched}"}
    keys = [r["row_key"] for r in own]
    return {"reachable": False, "files": keys, "evidence": f"seed rows {keys} exist but their text matches none of {CASES[case]['seed_terms']}"}


def openalex_evidence(case: str, openalex_id: str, record: dict, reached: dict) -> dict:
    """OpenAlex lane reach: the pick is an author in a query recorded for the case."""
    names = [n for n in reached if n.startswith("works_topic_" if case == "GS-02" else "authors_institution_mit")]
    for name in names:
        if openalex_id in reached[name]:
            where = "the authorships of the 100 works" if name.startswith("works_") else "the author list"
            position = reached[name].index(openalex_id) + 1
            return {
                "reachable": True, "query": index[name], "files": [index[name]["file"]],
                "evidence": f"{openalex_id} is in {where} in {name}.json (position {position} of {len(reached[name])} {'authorships' if name.startswith('works_') else 'authors'}; the query matches {index[name]['count']})",
            }
    last_known = [i["display_name"] for i in record["last_known_institutions"] or []]
    belgian = sorted({a["institution"]["display_name"] for a in record["affiliations"] if a["institution"]["country_code"] == "BE"})
    return {
        "reachable": False, "query": None, "files": [index[n]["file"] for n in names] + ["authors_batch_picks.json"],
        "evidence": f"{openalex_id} is in none of {', '.join(n + '.json' for n in names)}; record has last known institutions {last_known or 'none'} and Belgian affiliations {belgian or 'none'}",
    }


def write_reach(reached: dict) -> None:
    records = {short(a["id"]): a for a in json.loads((FIXTURES / "authors_batch_picks.json").read_text())["results"]}
    rows = seed_rows()
    picks = []
    for case, name, tie, openalex_id, note in PICKS:
        lanes = {"seeds": seed_evidence(case, name, rows), "openalex": openalex_evidence(case, openalex_id, records[openalex_id], reached)}
        reachable_by = [lane for lane in ("openalex", "seeds") if lanes[lane]["reachable"]]
        lead = lanes[reachable_by[0]] if reachable_by else lanes["openalex"]
        picks.append({
            "case": case, "name": name, "gold_tie": tie, "openalex_id": openalex_id, "identity_note": note,
            "lane": reachable_by[0] if reachable_by else "none",
            "reachable_by": reachable_by,
            "reachable": bool(reachable_by),
            "query": lead.get("query"),
            "evidence": lead["evidence"],
            "evidence_files": lead["files"],
            "lanes": lanes,
        })
    REACH.write_text(json.dumps({
        "recorded": date.today().isoformat(),
        "note": "reachable means the lane returns the pick before ranking; place ranking and the section cutoff are not applied.",
        "cases": {c: {"topics": v["topics"], "institutions": v["institutions"]} for c, v in CASES.items()},
        "picks": picks,
    }, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"Authorization": f"Bearer {api_key()}"}, timeout=90) as client:
        reached = record_calls(client)
    (FIXTURES / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    write_reach(reached)
    print(f"{calls} calls; wrote {len(index)} fixtures and {REACH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
