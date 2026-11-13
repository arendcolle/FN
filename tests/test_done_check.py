import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Built from parts so this file does not match its own pattern.
PATTERN = re.compile("|".join([r"\bti" r"es\b", "tie" "_json", "tie" "_text", "GOLD" "_TIE", "HIT" "_LIMIT"]))
SKIPPED = (ROOT / "src" / "fn" / "migrations",)


class DoneCheckTest(unittest.TestCase):
    def test_no_name_of_the_removed_label_is_left_in_src_or_tests(self):
        """No file under src/ or tests/ names the removed label, its step, column or limit; migrations are history."""
        found = []
        for path in sorted(p for d in ("src", "tests") for p in (ROOT / d).rglob("*") if p.is_file()):
            if "__pycache__" in path.parts or any(path.is_relative_to(d) for d in SKIPPED):
                continue
            for number, line in enumerate(path.read_bytes().decode("utf-8", errors="replace").splitlines(), 1):
                if PATTERN.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
