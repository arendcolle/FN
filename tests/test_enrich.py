import hashlib
import threading
import unittest
from datetime import UTC, date, datetime
from unittest import mock

import httpx

from fn import enrich, identity, net, present, resolve
from fn.contracts import (
    Candidate,
    ClaimDraft,
    EnrichIn,
    Identifier,
    LaneHit,
    LaneOut,
    Search,
    Source,
)
from fn.lanes import openalex
from tests.helpers import make_db, make_settings

AT = datetime(2026, 11, 1, tzinfo=UTC)
SMALL = {"id": "https://openalex.org/I9000001", "ror": "https://ror.org/00fict001",
         "display_name": "Fictional University", "country_code": "BE"}
OTHER = {"id": "https://openalex.org/I9000002", "ror": "https://ror.org/00fict002",
         "display_name": "Elsewhere Institute", "country_code": "US"}
BIG = {"id": "https://openalex.org/I9000003", "ror": "https://ror.org/00fict003",
       "display_name": "Large Fictional University", "country_code": "BE"}
GEO = {SMALL["id"]: {"city": "Leuven", "region": "Flanders", "country": "Belgium", "latitude": 50.88, "longitude": 4.70},
       BIG["id"]: {"city": "Ghent", "region": "Flanders", "country": "Belgium", "latitude": 51.05, "longitude": 3.72}}
ORCID_A, ORCID_B, ORCID_C = "0000-0001-0000-000A", "0000-0001-0000-000B", "0000-0001-0000-000C"


def author(author_id: str, name: str, inst: dict) -> dict:
    """A minimal OpenAlex author record with one affiliation, which is also its last known institution."""
    return {"id": f"https://openalex.org/{author_id}", "display_name": name, "orcid": None,
            "last_known_institutions": [inst], "updated_date": "2026-10-01",
            "affiliations": [{"institution": inst, "years": [2019, 2024]}]}


def employment(org: str, title: str | None, start: str, end: str | None = None, ror: str | None = None) -> dict:
    """One ORCID employment summary group, dated by YYYY-MM strings."""
    def when(text):
        year, month = text.split("-")
        return {"year": {"value": year}, "month": {"value": month}, "day": None}
    ref = {"disambiguated-organization-identifier": ror, "disambiguation-source": "ROR"} if ror else None
    return {"summaries": [{"employment-summary": {
        "role-title": title, "start-date": when(start), "end-date": when(end) if end else None,
        "organization": {"name": org, "address": {"city": "Leuven"}, "disambiguated-organization": ref}}}]}


class Recorded:
    """Serves made-up OpenAlex author searches, institution records and ORCID employments; logs each request."""

    def __init__(self, named: dict[str, list[dict]] | None = None, jobs: dict[str, list[dict] | int] | None = None):
        self.named, self.jobs, self.requests = named or {}, jobs or {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "pub.orcid.org":
            found = self.jobs.get(request.url.path.split("/")[2])
            if isinstance(found, int):
                return httpx.Response(found, json={"error": "made-up failure"})
            return httpx.Response(200, json={"affiliation-group": found or []})
        if request.url.path == "/authors":
            results = self.named.get(request.url.params["search"], [])
            return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})
        if request.url.path == "/institutions":
            ids = request.url.params["filter"].split(":", 1)[1].split("|")
            results = [{"id": f"https://openalex.org/{i}", "display_name": i, "geo": GEO[f"https://openalex.org/{i}"]}
                       for i in ids if f"https://openalex.org/{i}" in GEO]
            return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})
        return httpx.Response(404, json={"error": f"no fixture for {request.url}"})


class EnrichTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)

    def seed(self, name: str, *insts: dict, scheme: str = "seed") -> str:
        """A seed record, or a record of another scheme, with an affiliation claim at each institution's org."""
        person = self.store.resolve_person([Identifier(scheme=scheme, value=f"fict|{name}|2010")], name)
        text = f"{name}, " + ", ".join(i["display_name"] for i in insts)
        source = Source(id=hashlib.sha1(text.encode()).hexdigest(), kind="seed_page", url="https://example.org/fellows",
                        text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(), fetched_at=AT)
        for inst in insts:
            start = text.index(inst["display_name"])
            self.store.upsert_claim(ClaimDraft(
                person_id=person.id, kind="affiliation", relation="affiliated_with", org_id=openalex.org_of(inst),
                value=inst["display_name"], quote=inst["display_name"], quote_start=start,
                quote_end=start + len(inst["display_name"]), source=source, claim_date="2010",
                date_precision="year", date_method="record_field"), AT)
        return person.id

    def orcid_holder(self, orcid: str) -> str:
        return self.store.resolve_person([Identifier(scheme="orcid", value=f"https://orcid.org/{orcid}")],
                                         f"Holder {orcid[-1]}").id

    def enrich(self, handler: Recorded, kind: str, limit: int = 200) -> dict[str, tuple[str, str]]:
        """Run the fn-enrich job; the verdict and detail of each lookup by record."""
        client = net.Client(self.settings, httpx.MockTransport(handler), sleep=lambda _: None)
        job = enrich.refresh(self.store, self.settings, client, EnrichIn(kinds=[kind], limit=limit))
        self.assertEqual(job.status, "done", job.error)
        rows = self.store.conn.execute("SELECT person_id, verdict, detail FROM lookups WHERE kind = ?", (kind,))
        return {r[0]: (r[1], r[2]) for r in rows}

    def openalex_records(self, author_id: str) -> list[str]:
        return list(self.store.person_ids_by_identifier("openalex", [author_id]).values())

    def card_of(self, seed_id: str) -> list[str]:
        """The records resolve puts on the card of a seeds-lane hit on the seed record."""
        hit = LaneHit(person_id=seed_id, name_key=self.store.get_persons([seed_id])[seed_id].name_key, lane="seeds",
                      rank=1, score=1.0, matched_on="list")
        known = identity.load(self.store, [seed_id])
        (entry,) = [e for e in resolve.group([LaneOut(lane="seeds", query="q", total_seen=1, hits=[hit])],
                                             known.same_key, known).entries if seed_id in e.hit_person_ids]
        return entry.card_person_ids

    def test_an_author_with_the_name_at_a_shared_org_is_a_new_record_on_the_seed_card(self):
        """An author with the seed's name key and an affiliation at its org is stored as its own record.

        Identity calls the pair likely, the verdict is matched, and the card resolve builds shows the author's place.
        """
        seed = self.seed("Ada Fictief", SMALL)
        found = self.enrich(Recorded({"Ada Fictief": [author("A9000001", "Ada Fictief", SMALL)]}), "openalex_author")
        (record,) = self.openalex_records("A9000001")
        self.assertNotEqual(record, seed)
        self.assertEqual(found[seed][0], "matched")
        card = self.card_of(seed)
        self.assertEqual(card, [seed, record])
        (view,) = present.person_views(self.store, [card], date(2026, 11, 12))
        self.assertEqual(view.place, "Leuven, Flanders, Belgium")
        self.assertEqual(self.store.identifiers_of([seed])[seed], [Identifier(scheme="seed", value="fict|Ada Fictief|2010")])

    def test_an_author_with_the_name_at_another_org_is_not_stored(self):
        """A name match without a shared org stores nothing and gives no_match."""
        seed = self.seed("Ada Fictief", SMALL)
        found = self.enrich(Recorded({"Ada Fictief": [author("A9000002", "Ada Fictief", OTHER)]}), "openalex_author")
        self.assertEqual(found[seed][0], "no_match")
        self.assertEqual(self.openalex_records("A9000002"), [])

    def test_two_authors_with_a_common_name_at_a_large_org_are_ambiguous_and_stay_off_the_card(self):
        """Both authors are stored, identity calls them possible, the verdict is ambiguous and the card holds the seed only."""
        for n in range(identity.BIG_ORG):
            self.seed(f"Filler Person{n}", BIG, scheme="import")
        seed = self.seed("Jan Gewoon", BIG)
        for n in range(2):
            self.store.resolve_person([Identifier(scheme="import", value=f"file|Jan Gewoon|{n}")], "Jan Gewoon")
        twins = [author("A9000003", "Jan Gewoon", BIG), author("A9000004", "Jan Gewoon", BIG)]
        found = self.enrich(Recorded({"Jan Gewoon": twins}), "openalex_author")
        self.assertEqual(found[seed][0], "ambiguous")
        self.assertEqual(len(self.openalex_records("A9000003") + self.openalex_records("A9000004")), 2)
        self.assertEqual(self.card_of(seed), [seed])

    def test_an_author_stored_by_a_search_is_reused(self):
        """An author record that exists already is the one the lookup links, not a second record."""
        seed = self.seed("Ada Fictief", SMALL)
        record = author("A9000001", "Ada Fictief", SMALL)
        before = self.store.resolve_person([Identifier(scheme="openalex", value="A9000001")], "Ada Fictief").id
        found = self.enrich(Recorded({"Ada Fictief": [record]}), "openalex_author")
        self.assertEqual(self.openalex_records("A9000001"), [before])
        self.assertEqual(found[seed][0], "matched")
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM persons WHERE display_name = 'Ada Fictief'")
                         .fetchone()[0], 2)

    def test_an_open_employment_gives_a_role_and_a_dated_works_at_claim_and_an_ended_one_nothing(self):
        """Each employment without an end date gives its title as a role and a works_at claim dated by its start.

        An employment without a title gives the works_at claim only; an ended one gives no claim.
        """
        holder = self.orcid_holder(ORCID_A)
        jobs = [employment("Fictional University", "Research Engineer", "2021-03", ror="https://ror.org/00fict001"),
                employment("Second Fictional Lab", None, "2022-01"),
                employment("Old Fictional Lab", "Postdoc", "2015-01", end="2018-12")]
        found = self.enrich(Recorded(jobs={ORCID_A: jobs}), "orcid_employment")
        self.assertEqual(found[holder][0], "matched")
        (view,) = present.person_views(self.store, [[holder]], date(2026, 11, 12))
        self.assertEqual(view.role, "Research Engineer")
        claims = self.store.claims_of([holder])
        works = {c.value: (c.relation, c.org_id, c.claim_date, c.date_precision, c.date_method) for c in claims
                 if c.kind == "affiliation"}
        self.assertEqual(works, {
            "Fictional University": ("works_at", "ror:00fict001", "2021-03", "month", "record_field"),
            "Second Fictional Lab": ("works_at", None, "2022-01", "month", "record_field")})
        self.assertEqual([c.value for c in claims if c.kind == "role"], ["Research Engineer"])
        sources = self.store.get_sources([c.source_id for c in claims])
        self.assertEqual({s.title for s in sources.values()}, {f"ORCID record {ORCID_A}"})

    def test_only_ended_employments_give_no_match(self):
        holder = self.orcid_holder(ORCID_A)
        found = self.enrich(Recorded(jobs={ORCID_A: [employment("Old Fictional Lab", "Postdoc", "2015-01", "2018-12")]}),
                            "orcid_employment")
        self.assertEqual(found[holder][0], "no_match")
        self.assertEqual(self.store.claims_of([holder]), [])

    def test_a_failed_call_is_an_error_the_batch_goes_on_and_the_next_run_tries_it_again(self):
        """A 404 gives one error row and the other lookups end; the next run asks for that record only."""
        failing, fine = self.orcid_holder(ORCID_A), self.orcid_holder(ORCID_B)
        jobs = {ORCID_A: 404, ORCID_B: [employment("Fictional University", "Engineer", "2020-01")]}
        found = self.enrich(Recorded(jobs=jobs), "orcid_employment")
        self.assertEqual(found[failing][0], "error")
        self.assertIn("404", found[failing][1])
        self.assertEqual(found[fine][0], "matched")
        again = Recorded(jobs={ORCID_A: [], ORCID_B: 500})
        found = self.enrich(again, "orcid_employment")
        self.assertEqual([r.url.path for r in again.requests], [f"/v3.0/{ORCID_A}/employments"])
        self.assertEqual(found[failing][0], "no_match")

    def test_a_second_run_makes_no_call_for_records_with_a_row(self):
        self.seed("Ada Fictief", SMALL)
        self.enrich(Recorded(), "openalex_author")
        again = Recorded()
        self.enrich(again, "openalex_author")
        self.assertEqual(again.requests, [])

    def test_the_limit_stops_the_batch_after_that_many_calls(self):
        """A run looks up at most limit records, one call each; the next run takes the rest."""
        holders = [self.orcid_holder(o) for o in (ORCID_A, ORCID_B, ORCID_C)]
        first = Recorded()
        self.assertEqual(len(self.enrich(first, "orcid_employment", limit=2)), 2)
        self.assertEqual(len(first.requests), 2)
        rest = Recorded()
        self.assertEqual(set(self.enrich(rest, "orcid_employment", limit=2)), set(holders))
        self.assertEqual(len(rest.requests), 1)

    def test_records_on_kept_cards_go_first_best_rank_first(self):
        """With a limit of one, the record on the best-ranked kept card of a stored search is looked up first."""
        plain, second, first = (self.orcid_holder(o) for o in (ORCID_A, ORCID_B, ORCID_C))
        self.store.create_search(Search(id="s1", question="q", status="done", created_at=AT, code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates("s1", [Candidate(search_id="s1", person_id=p, person_ids=[p], section="new", rank=r,
                                                    score=0.1, lane_ranks={}, reason_claim_ids=[], hit_person_ids=[p])
                                          for p, r in ((second, 2), (first, 1))], [])
        self.assertEqual(list(self.enrich(Recorded(), "orcid_employment", limit=1)), [first])
        self.assertNotIn(plain, self.enrich(Recorded(), "orcid_employment", limit=1))

    def test_every_store_write_comes_from_the_step_thread(self):
        """Persons, claims, orgs, calls and lookup rows are written by the thread that runs the step."""
        self.seed("Ada Fictief", SMALL)
        self.orcid_holder(ORCID_A)
        threads: dict[str, set[int]] = {m: set() for m in
                                        ("add_call", "upsert_claim", "resolve_person", "upsert_org", "save_lookup")}
        for method, seen in threads.items():
            real = getattr(self.store, method)

            def spy(*args, real=real, seen=seen, **kwargs):
                seen.add(threading.get_ident())
                return real(*args, **kwargs)

            patcher = mock.patch.object(self.store, method, spy)
            patcher.start()
            self.addCleanup(patcher.stop)
        handler = Recorded({"Ada Fictief": [author("A9000001", "Ada Fictief", SMALL)]},
                           {ORCID_A: [employment("Fictional University", "Engineer", "2020-01")]})
        self.enrich(handler, "openalex_author")
        self.enrich(handler, "orcid_employment")
        self.assertEqual(threads, {m: {threading.get_ident()} for m in threads})


if __name__ == "__main__":
    unittest.main()
