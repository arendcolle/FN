import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fn import geo, gold, score
from fn.contracts import (
    Candidate,
    Chips,
    ClaimDraft,
    GoldCase,
    GoldPick,
    Identifier,
    LaneHit,
    LaneOut,
    Org,
    Place,
    Search,
    Source,
    StepRun,
)
from tests.helpers import cities_zip, make_db, make_settings

CREATED = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
LEUVEN = Org(id="ror:05f950310", name="KU Leuven", country_code="BE", source_id="org", fetched_at=CREATED)
OTHER = Org(id="ror:0abc12399", name="Other Lab", country_code="BE", source_id="org", fetched_at=CREATED)
BOSTON, LEUVEN_CITY, PARIS = (42.36, -71.06), (50.88, 4.7), (48.85, 2.35)
FIRST = ["Ana", "Bram", "Cora", "Dirk", "Elin", "Finn", "Gina", "Hugo", "Iris", "Jelle", "Kira", "Lars", "Mila", "Noor",
         "Odo", "Pia", "Quinn", "Rosa", "Sven", "Tess", "Uma", "Vera"]
NAMES = {i: f"{first} Zander{first}" for i, first in enumerate(FIRST, 1)} | {
    1: "Ana Vell", 22: "Ana Vell", 3: "Maya Ostrand", 17: "Maya J Ostrand", 7: "Noor Brandt", 19: "Noor Brandt",
    10: "Hana Quill", 12: "Jan Visser", 13: "J Visser", 20: "Ivo Reyes", 21: "Lena Sorrel"}
# Index of the card to what differs from a card with every field: place, role, employer, tie, two sources.
CHANGES = {
    1: {"role_quote": "Wind energy lead"}, 2: {"place": None}, 3: {"role": None}, 4: {"employer": None},
    5: {"tie": False}, 6: {"sources": 1}, 7: {"date": "2018"}, 8: {"date": "2010", "valid_to": "2024"},
    9: {"role_quote": "Tailwind lead"}, 10: {"role_quote": "Windmill engineer"}, 11: {"place": LEUVEN_CITY},
    12: {"place": PARIS}, 13: {"place": "no coordinates"}, 14: {"place": "no coordinates"},
    15: {"place": "born in Boston, lives in Leuven"}, 19: {"org": OTHER}}
for i in (2, 4, 5, 6, 7, 8):
    CHANGES[i] = {"role_quote": "Wind energy lead"} | CHANGES[i]
LANES = {**{i: {"openalex": i} for i in range(1, 14)}, **{i: {"seeds": i} for i in (14, 15, 16)}, 17: {"web": 17},
         **{i: {"openalex": i, "seeds": i} for i in (18, 19, 20)}, 21: {"web": 21}, 22: {"openalex": 22}}
QUESTION = "Who knows wind power around Boston?"


def add_person(store, name: str, *, place=BOSTON, role: str | None = "Engineer", role_quote: str = "Team member",
               employer: str | None = "KU Leuven", org=LEUVEN, tie: bool = True, sources: int = 3, date: str = "2025-03",
               valid_to: str | None = None) -> str:
    """Store a person with a claim per field given; sources=1 puts every claim in one source."""
    person = store.resolve_person([Identifier(scheme="seed", value=f"{name}-{uuid.uuid4()}")], name)
    drafts = []
    if place is not None:
        spots = [("lives_in", "Boston", place)] if isinstance(place, tuple) else []
        if place == "no coordinates":
            spots = [("lives_in", "Boston", (None, None))]
        if place == "born in Boston, lives in Leuven":
            spots = [("born_in", "Boston", BOSTON), ("lives_in", "Leuven", LEUVEN_CITY)]
        drafts += [("location", rel, value, f"Based in {value} {rel}", {"lat": lat, "lon": lon}) for rel, value, (lat, lon) in spots]
    if role:
        drafts.append(("role", None, role, role_quote, {}))
    if employer or not tie:
        drafts.append(("affiliation", "works_at", employer or "Some Co", f"Works at {employer or 'Some Co'}",
                       {"org_id": org.id if tie else None, "claim_date": date, "valid_to": valid_to}))
    if not employer and tie:
        drafts.append(("affiliation", "studied_at", "KU Leuven", "Studied at KU Leuven", {"org_id": LEUVEN.id}))
    shared = " ".join(d[3] for d in drafts)
    for n, (kind, relation, value, quote, fields) in enumerate(drafts):
        text = shared if sources == 1 else quote
        key = "all" if sources == 1 else str(n)
        source = Source(id=f"{person.id}:{key}", kind="page", url=f"https://example.org/{person.id}/{key}", title="Team",
                        text=text, content_hash=key)
        store.upsert_claim(ClaimDraft(person_id=person.id, kind=kind, relation=relation, value=value, quote=quote,
                                      quote_start=text.index(quote), quote_end=text.index(quote) + len(quote),
                                      source=source, **fields))
    return person.id


def candidate(search_id: str, person_id: str, rank: int, lanes: dict, cut: bool = False) -> Candidate:
    return Candidate(search_id=search_id, person_id=person_id, person_ids=[person_id], section="new", rank=rank, score=1 / rank,
                     lane_ranks=lanes, hit_person_ids=[person_id], cut_reason="no_belgian_evidence" if cut else None)


def make_search(store, key: str, question: str, chips: Chips | None, status: str = "done", llm_mode: str = "replay") -> str:
    search_id = f"{key}-0000-4000-8000-000000000000"
    store.create_search(Search(id=search_id, question=question, chips=chips, status=status, created_at=CREATED,
                               code_sha="abc", dirty=False, llm_mode=llm_mode, settings_json="{}", boot_id="boot"))
    return search_id


def build(test: unittest.TestCase):
    """A snapshot of four searches: A with gold and 22 kept, B with 3 kept and no gold, C with none, D failed."""
    settings = make_settings(test)
    store = make_db(test, settings)
    source = Source(id="org", kind="record", url="https://example.org/orgs", text="orgs", content_hash="o")
    store.upsert_source(source)
    for org in (LEUVEN, OTHER):
        store.upsert_org(org, True)
    chips = Chips(topics=[{"text": "wind power", "origin": "parsed"}], place=Place(text="Boston", origin="parsed", kind="metro"))
    a = make_search(store, "aaaaaaaa", QUESTION, chips)
    people = [add_person(store, NAMES[i], **CHANGES.get(i, {})) for i in range(1, 23)]
    cands = [candidate(a, p, i, LANES[i]) for i, p in enumerate(people, 1)]
    store.save_candidates(a, [*cands, candidate(a, add_person(store, "Cut Person"), 1, {"openalex": 1}, cut=True)], [])
    b = make_search(store, "bbbbbbbb", "Who is in the US?", Chips(place=Place(text="the US", origin="parsed", kind="anywhere_us")))
    store.save_candidates(b, [candidate(b, add_person(store, f"{FIRST[i]} Quarry{i}"), i + 1, {"openalex": i + 1}) for i in range(3)], [])
    c = make_search(store, "cccccccc", "Who is on Mars?", Chips(), llm_mode="live")
    store.start_step(StepRun(id="s1", search_id=c, seq=1, step="parse", status="ok", started_at=CREATED, input_model="ParseIn"), "{}")
    store.finish_step(StepRun(id="s1", search_id=c, seq=1, step="parse", status="ok", started_at=CREATED,
                              ended_at=CREATED + timedelta(seconds=2.5), input_model="ParseIn"), "{}")
    make_search(store, "dddddddd", "Who failed?", None, status="failed")
    cache = settings.var_dir / "cache"
    cache.mkdir()
    (cache / f"{hashlib.sha256(geo.CITIES_URL.encode()).hexdigest()}.json").write_bytes(cities_zip())
    case = GoldCase(id="GS-90", question=QUESTION, picks=[GoldPick(case_id="GS-90", name=n, gold_tie="belgian")
                                                          for n in ("Hana Quill", "Ivo Reyes", "Lena Sorrel", "Zed Nobody")])
    return settings, store, case


def tree_hashes(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.settings, self.store, self.case = build(self)
        patch = mock.patch.object(gold, "load_cases", return_value=[self.case])
        patch.start()
        self.addCleanup(patch.stop)
        self.work = Path(tempfile.mkdtemp(prefix="fn-score-test-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.snap = self.work / "snap"
        score.snapshot(self.settings, self.snap, [])

    def run_score(self, mode: str = "rescore", name: str = "out", *flags: str) -> tuple[int, dict]:
        out = self.work / name
        with contextlib.redirect_stderr(io.StringIO()):
            code = score.main(["run", str(self.snap), "--mode", mode, "--out", str(out), *flags])
        return code, json.loads((out / "scorecard.json").read_text())

    def test_every_metric_of_the_search_with_gold_matches_the_hand_count(self):
        """Search A has 22 kept cards, a cut one and picks at 10, 20, 21 and nowhere; each share is counted by hand."""
        code, result = self.run_score()
        row = result["searches"]["aaaaaaaa"]
        self.assertEqual(code, 0)
        self.assertEqual(row["gold_picks"], [{"id": "GS-90#1", "position": 10}, {"id": "GS-90#2", "position": 20},
                                             {"id": "GS-90#3", "position": 21}, {"id": "GS-90#4", "position": None}])
        expected = {
            "kept": 22, "gold_case": "GS-90", "gold_at_10": 1, "gold_at_20": 2, "gold_at_50": 3, "gold_found": 3,
            "doubles_top20": 2, "doubles_top50": 3,
            "place": 0.95, "role": 0.95, "employer": 0.95, "tie": 0.95, "sources2": 0.95, "complete": 0.75, "fresh": 0.9,
            "topic": 0.4, "place_inside": 0.7, "place_outside": 0.15, "place_unknown": 0.15,
            "lane_openalex_only": 0.65, "lane_seeds_only": 0.15, "lane_web_only": 0.05, "lane_multi": 0.15,
        }
        self.assertEqual({k: row[k] for k in expected}, expected)

    def test_searches_without_gold_cards_place_or_results_leave_those_metrics_out(self):
        """B has 3 cards, no gold case and an anywhere_us place; C has nothing kept; D failed and is only listed."""
        _, result = self.run_score()
        b, c = result["searches"]["bbbbbbbb"], result["searches"]["cccccccc"]
        self.assertEqual((b["kept"], b["gold_case"], b["complete"], b["lane_openalex_only"]), (3, None, 1.0, 1.0))
        for name in ("gold_at_20", "gold_picks", "place_inside", "place_unknown", "topic"):
            self.assertNotIn(name, b)
        self.assertEqual(sorted(c), ["gold_case", "kept", "question_sha256"])
        self.assertEqual(c["kept"], 0)
        self.assertNotIn("dddddddd", result["searches"])
        self.assertEqual(result["meta"]["skipped"], ["dddddddd"])
        self.assertEqual(result["live_step_seconds"], {"cccccccc": {"parse": 2.5}})

    def test_aggregate_sums_counts_and_averages_shares_over_the_searches_that_have_them(self):
        """Gold and doubles are summed, kept is the median of searches with results, shares are means."""
        _, result = self.run_score()
        agg = result["aggregate"]
        self.assertEqual((agg["gold_at_20"], agg["doubles_top50"], agg["kept"], agg["searches"]), (2, 3, 12.5, 3))
        self.assertEqual((agg["complete"], agg["place_inside"], agg["topic"]), (0.875, 0.7, 0.4))

    def test_the_output_holds_no_names_and_scoring_twice_gives_identical_bytes(self):
        """No person's name appears in the JSON or the table, and two runs of one snapshot write equal files."""
        self.run_score(name="one")
        self.run_score(name="two")
        for file in ("scorecard.json", "scorecard.md"):
            first = (self.work / "one" / file).read_bytes()
            self.assertEqual(first, (self.work / "two" / file).read_bytes())
            for name in NAMES.values():
                self.assertNotIn(name, first.decode())

    def test_a_run_in_every_mode_leaves_the_snapshot_unchanged(self):
        """Rescore, rerank and replay work on a copy of the database; every file of the snapshot keeps its hash."""
        before = tree_hashes(self.snap)
        for mode in ("rescore", "rerank", "replay"):
            self.run_score(mode, mode, "--allow-degraded")
        self.assertEqual(tree_hashes(self.snap), before)

    def test_a_replay_without_the_llm_fixtures_is_degraded_and_exits_2(self):
        """A search with no stored chips calls parse, the fixture folder is missing, and the search is degraded."""
        make_search(self.store, "ffffffff", "Who needs parse?", None)
        shutil.rmtree(self.snap)
        score.snapshot(self.settings, self.snap, [])
        shutil.rmtree(self.snap / "llm")
        with self.assertLogs("fn.worker", "ERROR"):
            code, result = self.run_score("replay", "strict")
        self.assertEqual(code, 2)
        self.assertIn("ffffffff", result["meta"]["degraded"])
        self.assertNotIn("cccccccc", result["meta"]["degraded"])
        self.assertEqual(result["aggregate"]["searches"], 4 - len(result["meta"]["degraded"]))
        with self.assertLogs("fn.worker", "ERROR"):
            self.assertEqual(self.run_score("replay", "lenient", "--allow-degraded")[0], 0)

    def test_rerank_runs_the_steps_after_the_lanes_on_the_stored_lane_outputs(self):
        """A search stored with a lane hit and no candidates has none under rescore and one under rerank."""
        person = add_person(self.store, "Kai Rerank")
        search_id = make_search(self.store, "eeeeeeee", "Who reranks?", Chips())
        hit = LaneHit(person_id=person, name_key="kai rerank", lane="seeds", rank=1, score=0.5, matched_on="m")
        out = LaneOut(lane="seeds", query="q", total_seen=1, hits=[hit])
        run = StepRun(id="lane1", search_id=search_id, seq=1, step="lane:seeds", status="ok", started_at=CREATED, input_model="LaneIn")
        self.store.start_step(run, "{}")
        self.store.finish_step(run.model_copy(update={"ended_at": CREATED}), out.model_dump_json())
        shutil.rmtree(self.snap)
        score.snapshot(self.settings, self.snap, [])
        self.assertEqual(self.run_score("rescore", "a")[1]["searches"]["eeeeeeee"]["kept"], 0)
        self.assertEqual(self.run_score("rerank", "b")[1]["searches"]["eeeeeeee"]["kept"], 1)

    def test_a_snapshot_copies_the_database_cache_and_every_fixture_folder_and_refuses_a_full_folder(self):
        """The snapshot holds the three parts, takes fixtures from each folder, and will not fill a folder with files in it."""
        extra, other = self.work / "extra", self.settings.var_dir / "llm"
        other.mkdir()
        extra.mkdir()
        (extra / "extract-x.json").write_text("{}")
        (other / "parse-y.json").write_text("{}")
        fresh = self.work / "fresh"
        score.snapshot(self.settings, fresh, [extra])
        self.assertTrue({"extract-x.json", "parse-y.json"} <= {p.name for p in (fresh / "llm").iterdir()})
        self.assertTrue((fresh / "fn.sqlite3").stat().st_size > 0 and any((fresh / "cache").iterdir()))
        with self.assertRaises(FileExistsError):
            score.snapshot(self.settings, fresh, [])


    def test_a_snapshot_refuses_an_llm_path_that_is_not_a_directory(self):
        """An --llm path that is a file or missing prints the path and exits 2 without writing the snapshot."""
        path = self.work / "not-a-dir.json"
        path.write_text("{}")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch("fn.score.config.from_env", return_value=self.settings):
            code = score.main(["snapshot", str(self.work / "out"), "--llm", str(path)])
        self.assertEqual(code, 2)
        self.assertIn(str(path), err.getvalue())
        self.assertFalse((self.work / "out").exists())


class FreshTest(unittest.TestCase):
    def test_a_stamp_is_padded_to_its_first_day_and_compared_with_the_search_date_minus_five_years(self):
        """2021-01 is older than 2021-11 and not fresh for a search of 2026-11; 2022 is fresh."""
        created = date(2026, 11, 12)
        for stamp, expected in (("2021-01", False), ("2021-11-11", False), ("2021-11-12", True), ("2022", True), ("", False), ("n/a", False)):
            with self.subTest(stamp=stamp):
                claim = SimpleNamespace(relation="works_at", value="Acme", valid_to=None, claim_date=stamp)
                self.assertEqual(score.fresh([claim], "Acme", created), expected)


class DoublesTest(unittest.TestCase):
    def test_two_cards_of_one_person_with_a_shared_org_are_a_double_and_other_pairs_are_not(self):
        """Middle initials, an initial for a first name and an equal name count as likely; a name with no shared org does not."""
        def card(name: str, *orgs: str) -> dict:
            return {"key": score.name_key(name), "orgs": set(orgs)}

        self.assertEqual(score.doubles([card("Maya Ostrand", "o1"), card("Maya J Ostrand", "o1")]), 1)
        self.assertEqual(score.doubles([card("Jan Visser", "o1"), card("J Visser", "o1")]), 1)
        self.assertEqual(score.doubles([card("Jan Visser", "o1"), card("Jan Visser", "o2")]), 0)
        self.assertEqual(score.doubles([card("Jan Visser", "o1"), card("Jos Visser", "o1")]), 0)
        self.assertEqual(score.doubles([card("Jan Visser"), card("Jan Visser")]), 0)


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="fn-score-compare-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def compare(self, old: dict, new: dict, old_pos: int = 5, new_pos: int = 5) -> tuple[int, str]:
        paths = []
        for name, agg, pos in (("a", old, old_pos), ("b", new, new_pos)):
            path = self.work / f"{name}.json"
            path.write_text(json.dumps({"aggregate": agg, "meta": {"degraded": []},
                                        "searches": {"s1": {"gold_picks": [{"id": "GS-90#1", "position": pos}]}}}))
            paths.append(str(path))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = score.main(["compare", *paths])
        return code, out.getvalue()

    def test_each_gate_fails_on_its_own_move_and_an_ungated_metric_does_not(self):
        """Doubles up, gold at 20 or found down, or complete down by over 0.02 exit 1; a fall in fresh exits 0."""
        base = {"doubles_top20": 1, "gold_at_20": 3, "gold_found": 5, "complete": 0.5, "fresh": 0.9}
        for name, value in (("doubles_top20", 2), ("gold_at_20", 2), ("gold_found", 4), ("complete", 0.4799)):
            with self.subTest(name=name):
                self.assertEqual(self.compare(base, base | {name: value})[0], 1)
        for name, value in (("fresh", 0.1), ("complete", 0.48), ("doubles_top20", 0), ("gold_at_20", 4)):
            with self.subTest(name=name):
                self.assertEqual(self.compare(base, base | {name: value})[0], 0)

    def test_a_gated_metric_missing_in_b_fails_the_gate_and_names_the_metric(self):
        """A gated metric present in A and absent in B exits 1 and prints its name; an ungated one does not."""
        code, text = self.compare({"gold_at_20": 3, "fresh": 0.9}, {})
        self.assertEqual(code, 1)
        self.assertIn("gold_at_20 is missing", text)
        self.assertNotIn("fresh is missing", text)

    def test_compare_prints_the_changed_metrics_with_the_delta_and_the_picks_that_moved(self):
        """An unchanged metric is not printed; a changed one shows both values and the delta; a moved pick shows both positions."""
        code, text = self.compare({"gold_at_20": 3, "kept": 500}, {"gold_at_20": 4, "kept": 500}, 30, 12)
        self.assertEqual(code, 0)
        self.assertIn("gold_at_20: 3 -> 4 (+1)", text)
        self.assertNotIn("kept", text)
        self.assertIn("GS-90#1 (search s1): 30 -> 12", text)


if __name__ == "__main__":
    unittest.main()
