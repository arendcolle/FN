import hashlib
import unittest
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from fn import network
from fn.contracts import Claim, ClaimDraft, Identifier, Source, SourceKind
from tests.helpers import make_db

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)

    def person(self, name: str, *idents: tuple[str, str]) -> str:
        return self.store.resolve_person([Identifier(scheme=s, value=v) for s, v in idents], name).id

    def fact(self, person_id: str, value: str, source_kind: SourceKind = "page", when: datetime = T0) -> Claim:
        url = f"https://example.org/{source_kind}/{hashlib.sha1(value.encode()).hexdigest()[:8]}"
        source = Source(id=f"{source_kind}-{url}", kind=source_kind, url=url, text=value,
                        content_hash=hashlib.sha256(value.encode()).hexdigest())
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind="topic", value=value, quote=value,
                                                  quote_start=0, quote_end=len(value), source=source), at=when)

    def status(self, person_id: str) -> str:
        return self.store.get_persons([person_id])[person_id].list_status

    def merged_into(self, *person_ids: str) -> list[str | None]:
        found = self.store.get_persons(list(person_ids))
        return [found[p].merged_into for p in person_ids]


class AddTest(NetworkTest):
    def test_one_hit_joins_the_network_once(self):
        """Add puts the hit's person in_list with one add event and seen_at at now.

        A second Add of a person already in the network writes nothing and returns the first event.
        """
        ann = self.person("Ann Example", ("seed", "ann"))
        first = network.add(self.store, [ann], via="search", now=at(1), search_id=None, rank=3, section="new")
        self.assertEqual((self.status(ann), first.kind, first.person_id, first.rank), ("in_list", "add", ann, 3))
        self.assertEqual(self.store.get_persons([ann])[ann].seen_at, at(1))
        again = network.add(self.store, [ann], via="search", now=at(2))
        self.assertEqual(again.id, first.id)
        self.assertEqual([e.id for e in self.store.events_of(ann)], [first.id])

    def test_two_hits_merge_and_their_claims_show_once_under_the_canonical_id(self):
        """Add merges a second hit without a conflicting identifier into the first.

        claims_of gives both records' claims under the canonical id, once, also when both ids are asked.
        Undo separates them again and restores the status.
        """
        ann = self.person("Ann Example", ("seed", "ann"))
        twin = self.person("Ann Example", ("openalex", "A1"))
        own, theirs = self.fact(ann, "wind energy"), self.fact(twin, "offshore grids")
        event = network.add(self.store, [ann, twin], via="search", now=at(1))
        self.assertEqual((event.detail["merged"], event.detail["left_apart"]), ([twin], []))
        self.assertEqual(self.merged_into(ann, twin), [None, ann])
        claims = self.store.claims_of([ann, twin])
        self.assertCountEqual([c.id for c in claims], [own.id, theirs.id])
        self.assertEqual({c.person_id for c in claims}, {ann})
        self.assertEqual([r.id for r in self.store.records_of(twin)], [ann, twin])
        network.undo(self.store, event.id, now=at(2))
        self.assertEqual(self.merged_into(ann, twin), [None, None])
        self.assertEqual(self.status(ann), "candidate")
        self.assertEqual({c.person_id for c in self.store.claims_of([ann, twin])}, {ann, twin})

    def test_a_record_merged_after_seen_at_brings_facts_that_count_as_new(self):
        """A claim of a record merged into a network person counts as first seen at the merge.

        So a fact stored long before the merge still has a first_seen_at later than the person's seen_at.
        """
        ann = self.person("Ann Example", ("seed", "ann"))
        twin = self.person("Ann Example", ("openalex", "A1"))
        old = self.fact(twin, "offshore grids", when=at(0))
        network.add(self.store, [ann], via="search", now=at(5))
        network.merge(self.store, [twin], ann, now=at(9))
        (found,) = [c for c in self.store.claims_of([ann]) if c.id == old.id]
        self.assertEqual(found.first_seen_at, at(9))
        self.assertGreater(found.first_seen_at, self.store.get_persons([ann])[ann].seen_at)

    def test_a_hit_declared_different_from_a_merged_record_stays_apart(self):
        """Add leaves a hit apart when a not-same pair links it to a record merged into the target."""
        ann, old = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("mention", "page#ann"))
        other = self.person("Ann Example", ("mention", "other#ann"))
        network.not_same(self.store, old, other, now=at(1))
        network.merge(self.store, [old], ann, now=at(2))
        event = network.add(self.store, [ann, other], via="search", now=at(3))
        self.assertEqual((event.detail["merged"], event.detail["left_apart"]), ([], [other]))
        self.assertEqual(self.merged_into(other), [None])

    def test_a_hit_with_another_openalex_id_stays_apart(self):
        """Two hits with different values in a strong scheme are two people: the second is left apart, unmerged."""
        ann = self.person("Ann Example", ("openalex", "A1"))
        other = self.person("Ann Example", ("openalex", "A2"))
        event = network.add(self.store, [ann, other], via="search", now=at(1))
        self.assertEqual((event.detail["merged"], event.detail["left_apart"]), ([], [other]))
        self.assertEqual(self.merged_into(other), [None])
        self.assertEqual(self.status(other), "candidate")


class MergeTest(NetworkTest):
    def test_merge_then_undo_restores_every_merged_into(self):
        """Merging a person re-points the records already merged into it, so depth stays one.

        Undo puts every record back where it was, the one merged into the moved person included.
        """
        ann, bob, bob_twin = (self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("seed", "b1")),
                              self.person("Ann Example", ("seed", "b2")))
        network.merge(self.store, [bob_twin], bob, now=at(1))
        event = network.merge(self.store, [bob], ann, now=at(2))
        self.assertEqual(self.merged_into(ann, bob, bob_twin), [None, ann, ann])
        self.assertCountEqual([(m["id"], m["merged_into"]) for m in event.detail["merged"]],
                              [(bob, None), (bob_twin, bob)])
        network.undo(self.store, event.id, now=at(3))
        self.assertEqual(self.merged_into(ann, bob, bob_twin), [None, None, bob])

    def test_a_person_cannot_merge_into_itself(self):
        """Merging a record into its own person raises ValueError and writes nothing."""
        ann, twin = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("seed", "twin"))
        network.merge(self.store, [twin], ann, now=at(1))
        with self.assertRaises(ValueError):
            network.merge(self.store, [twin], ann, now=at(2))
        self.assertEqual(len(self.store.events_of(ann)), 1)

    def test_a_network_person_merged_in_keeps_the_merged_person_in_the_network(self):
        """When one of the two is in the network, the merged person is."""
        ann, twin = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("seed", "twin"))
        network.add(self.store, [twin], via="search", now=at(1))
        network.merge(self.store, [twin], ann, now=at(2))
        self.assertEqual(self.status(ann), "in_list")
        self.assertEqual(self.store.network_by_group_key(), {"ann example": [ann]})

    def test_not_same_separates_a_merged_record_and_matches_leave_the_pair_out(self):
        """Not the same person clears a merged record's merged_into and stores the pair.

        possible_matches and name_matches then leave that pair out, and undo merges the record back.
        """
        ann, twin = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("openalex", "A1"))
        network.add(self.store, [ann, twin], via="search", now=at(1))
        self.assertEqual(network.possible_matches(self.store, ann), [])
        event = network.not_same(self.store, ann, twin, now=at(2))
        self.assertEqual(event.detail["separated"]["id"], twin)
        self.assertEqual(self.merged_into(twin), [None])
        self.assertEqual(self.store.not_same_pairs([ann]), {frozenset((ann, twin))})
        self.assertEqual(network.possible_matches(self.store, ann), [])
        self.assertEqual(network.name_matches(self.store, [twin]), [])
        stranger = self.person("Ann Example", ("seed", "stranger"))
        self.assertEqual(network.name_matches(self.store, [stranger]), [ann])
        self.assertEqual(network.possible_matches(self.store, ann), [stranger])
        network.undo(self.store, event.id, now=at(3))
        self.assertEqual((self.merged_into(twin), self.store.not_same_pairs([ann])), ([ann], set()))


class SkipAndUndoTest(NetworkTest):
    def test_skip_then_add_puts_the_person_in_the_network_and_a_network_person_cannot_be_skipped(self):
        """A skipped person can still be added; skipping a person in the network raises ValueError."""
        ann = self.person("Ann Example", ("seed", "ann"))
        network.skip(self.store, [ann], now=at(1))
        self.assertEqual(self.status(ann), "skipped")
        network.add(self.store, [ann], via="search", now=at(2))
        self.assertEqual(self.status(ann), "in_list")
        with self.assertRaises(ValueError):
            network.skip(self.store, [ann], now=at(3))

    def test_undo_is_refused_after_a_later_event_and_for_an_undo(self):
        """An event can be undone only while it is the latest about each of its persons.

        A later decision about any of them, or undoing an undo, raises UndoRefused with a sentence.
        """
        ann, bob = self.person("Ann Example", ("seed", "ann")), self.person("Bob Example", ("seed", "bob"))
        skipped = network.skip(self.store, [ann, bob], now=at(1))
        network.add(self.store, [bob], via="search", now=at(2))
        with self.assertRaises(network.UndoRefused) as refused:
            network.undo(self.store, skipped.id, now=at(3))
        self.assertEqual(str(refused.exception), network.LATER)
        self.assertEqual(self.status(ann), "skipped")
        added = network.add(self.store, [ann], via="search", now=at(4))
        undone = network.undo(self.store, added.id, now=at(5))
        self.assertEqual((self.status(ann), undone.undoes), ("skipped", added.id))
        for event_id in (undone.id, added.id):
            with self.assertRaises(network.UndoRefused):
                network.undo(self.store, event_id, now=at(6))

    def test_decisions_at_the_same_moment_undo_in_the_order_they_were_made(self):
        """Two decisions with one timestamp are ordered by when they were written.

        The second can be undone, and the first is then refused because the undo came after it.
        """
        ann = self.person("Ann Example", ("seed", "ann"))
        added = network.add(self.store, [ann], via="search", now=at(1))
        removed = network.remove(self.store, ann, now=at(1))
        network.undo(self.store, removed.id, now=at(1))
        self.assertEqual(self.status(ann), "in_list")
        with self.assertRaises(network.UndoRefused):
            network.undo(self.store, added.id, now=at(1))

    def test_remove_takes_a_person_out_and_undo_puts_them_back(self):
        ann = self.person("Ann Example", ("seed", "ann"))
        network.add(self.store, [ann], via="search", now=at(1))
        removed = network.remove(self.store, ann, now=at(2))
        self.assertEqual(self.status(ann), "candidate")
        network.undo(self.store, removed.id, now=at(3))
        self.assertEqual(self.status(ann), "in_list")

    def test_mark_seen_moves_seen_at_and_writes_no_event(self):
        """Opening a profile is no decision: mark_seen sets seen_at on the canonical record only."""
        ann, twin = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("seed", "twin"))
        network.merge(self.store, [twin], ann, now=at(1))
        network.mark_seen(self.store, twin, now=at(4))
        found = self.store.get_persons([ann, twin])
        self.assertEqual((found[ann].seen_at, found[twin].seen_at), (at(4), None))
        self.assertEqual(len(self.store.events_of(ann)), 1)


class ClaimsTest(NetworkTest):
    def test_a_rejected_fact_and_its_same_value_twin_are_hidden_until_undo(self):
        """Rejecting a claim hides it and every claim of that person with the same kind and folded value.

        claims_of and match_claims leave them out; include_hidden returns them; undo brings them back.
        """
        ann = self.person("Ann Example", ("seed", "ann"))
        bad, twin = self.fact(ann, "Robotics"), self.fact(ann, " robotics", source_kind="seed_page")
        kept = self.fact(ann, "Welding")
        event = network.reject_claim(self.store, bad.id, now=at(1))
        self.assertEqual([c.id for c in self.store.claims_of([ann])], [kept.id])
        self.assertCountEqual([c.id for c in self.store.claims_of([ann], include_hidden=True)],
                              [bad.id, twin.id, kept.id])
        self.assertEqual(self.store.match_claims('"robotics"', exclude=()), [])
        network.undo(self.store, event.id, now=at(2))
        self.assertEqual(len(self.store.claims_of([ann])), 3)
        self.assertEqual([p.id for p, _, _ in self.store.match_claims('"robotics"', exclude=())], [ann])

    def test_contact_edits_replace_hide_and_undo(self):
        """set_contact writes a staff claim and the email identifier; replaces hides the old claim; undo swaps back.

        A bad email or one another person holds raises ValueError, and email claims never match a search.
        """
        ann, bob = self.person("Ann Example", ("seed", "ann")), self.person("Bob Example", ("seed", "bob"))
        first = network.set_contact(self.store, ann, "email", " Ann@Example.org ", now=at(1))
        self.assertNotIn("Ann@Example.org", str(first.detail))
        (old,) = [c for c in self.store.claims_of([ann]) if c.kind == "email"]
        self.assertEqual((old.value, old.first_seen_at), ("Ann@Example.org", at(1)))
        source = self.store.get_sources([old.source_id])[old.source_id]
        self.assertEqual((source.kind, source.url, source.date_method), ("staff", f"fn:staff/{first.id}", "staff_edit"))
        found = self.store.resolve_person([Identifier(scheme="email", value="ann@example.org")], "Someone")
        self.assertEqual(found.id, ann)
        second = network.set_contact(self.store, ann, "email", "ann@example.net", now=at(2), replaces=old.id)
        self.assertEqual([c.value for c in self.store.claims_of([ann]) if c.kind == "email"], ["ann@example.net"])
        network.undo(self.store, second.id, now=at(3))
        self.assertEqual([c.value for c in self.store.claims_of([ann]) if c.kind == "email"], ["Ann@Example.org"])
        self.assertEqual(self.store.person_ids_by_identifier("email", ["ann@example.net"]), {})
        for value in ("", "no-at-sign", "a@" + "x" * 200):
            with self.subTest(value=value), self.assertRaises(ValueError):
                network.set_contact(self.store, bob, "email", value, now=at(4))
        with self.assertRaises(ValueError) as held:
            network.set_contact(self.store, bob, "email", "ann@example.org", now=at(4))
        self.assertEqual(str(held.exception), "Another person in FN already has this email address.")
        self.assertEqual(self.store.match_claims('"ann"', exclude=()), [])

    def test_a_claim_on_a_merged_record_shows_under_the_canonical_id(self):
        """resolve_person still returns the merged record that holds the identifier.

        A claim a lane writes on it shows under the canonical id, with first_seen_at the caller's time.
        """
        ann, twin = self.person("Ann Example", ("seed", "ann")), self.person("Ann Example", ("openalex", "A1"))
        network.add(self.store, [ann, twin], via="search", now=at(1))
        found = self.store.resolve_person([Identifier(scheme="openalex", value="A1")], "Ann Example")
        self.assertEqual((found.id, found.merged_into, found.merged_at), (twin, ann, at(1)))
        claim = self.fact(found.id, "tidal power", when=at(7))
        self.assertEqual(claim.first_seen_at, at(7))
        (shown,) = [c for c in self.store.claims_of([ann]) if c.id == claim.id]
        self.assertEqual((shown.person_id, shown.first_seen_at), (ann, at(7)))

    def test_a_stored_claim_keeps_its_first_seen_at(self):
        """Upserting a stored claim again leaves first_seen_at at the first time."""
        ann = self.person("Ann Example", ("seed", "ann"))
        self.fact(ann, "wind energy", when=at(1))
        self.assertEqual(self.fact(ann, "wind energy", when=at(5)).first_seen_at, at(1))


class SourceUrlTest(unittest.TestCase):
    def test_fn_urls_are_valid_for_import_and_staff_sources_only(self):
        """FN writes fn: URLs for the sources it makes itself; a source from the web still needs http or https."""
        for kind in ("import", "staff"):
            Source(id="s", kind=kind, url="fn:staff/e1", text="email: a@b", content_hash="h")
        with self.assertRaises(ValidationError):
            Source(id="s", kind="page", url="fn:staff/e1", text="email: a@b", content_hash="h")


if __name__ == "__main__":
    unittest.main()
