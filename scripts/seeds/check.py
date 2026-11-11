# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

# Counts come from independent hand counts of each source on 2026-10-29 (fayat on 2026-11-12), not from the scrapers.
EXPECTED = {"consuls": 34, "baef": 3577, "kvab": 545, "francqui": 331, "climate": 453, "fayat": 95}
GOLD = {
    "consuls": ["Anne Deconinck"],
    "baef": ["Michel Goemans", "Pierre Lermusiaux", "Julien de Wit", "Milena Janjevic"],
    "kvab": ["Pattie Maes", "Valerie Trouet", "Jeroen Dewulf", "Wim Sweldens", "Lieven Danneels"],
    "francqui": ["Michel Goemans"],
    "climate": ["Valerie Trouet", "Hans Bruyninckx"],
    "fayat": [],
}


def fold(name: str) -> str:
    """First and last name token, folded, so a middle initial does not hide a gold pick."""
    tokens = common.row_key("x", name, None).split("|")[1].split("-")
    return f"{tokens[0]}-{tokens[-1]}"


def check(list_name: str) -> list[str]:
    """Return every problem found in one seed file; an empty list means it passed."""
    path = common.SEEDS / f"{list_name}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    problems = []
    if len(rows) != EXPECTED[list_name]:
        problems.append(f"{len(rows)} rows, expected {EXPECTED[list_name]}")
    try:
        validate(list_name, rows)
    except ValueError as exc:
        problems.append(str(exc))
    names = Counter(fold(r["name"]) for r in rows)
    for gold in GOLD[list_name]:
        if names[fold(gold)] == 0:
            problems.append(f"gold pick missing: {gold}")
    return problems


def validate(list_name: str, rows: list[dict]) -> None:
    """Run write_rows' checks without rewriting the file."""
    original = common.SEEDS
    tmp = original / ".check"
    tmp.mkdir(exist_ok=True)
    common.SEEDS = tmp
    try:
        common.write_rows(list_name, rows)
    finally:
        common.SEEDS = original
        for leftover in tmp.iterdir():
            leftover.unlink()
        tmp.rmdir()


if __name__ == "__main__":
    failed = False
    for name in EXPECTED:
        problems = check(name)
        print(f"{name}: {'ok' if not problems else 'FAIL'}")
        for problem in problems:
            print(f"  - {problem}")
        failed |= bool(problems)
    sys.exit(1 if failed else 0)
