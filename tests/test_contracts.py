import unittest

from pydantic import ValidationError

from fn.contracts import ClaimDraft, Source, name_key, normalize

SOURCE = Source(id="s1", kind="page", url="https://example.org", text="Anne works at KU Leuven.", content_hash="h")


class NormalizeTest(unittest.TestCase):
    def test_normalize_folds_spaces_and_quotes_and_keeps_lines(self):
        """Spaces collapse and quotes fold within a line, while each record field line stays its own line."""
        text = "  name:\u00a0 \u201eAnne\u201d  De\tConinck \r\n  affiliation: \u2018KU Leuven\u2019 "
        self.assertEqual(normalize(text), 'name: "Anne" De Coninck\naffiliation: \'KU Leuven\'')


class ClaimDraftTest(unittest.TestCase):
    def draft(self, quote: str, start: int, end: int) -> ClaimDraft:
        return ClaimDraft(person_id="p1", kind="affiliation", value="KU Leuven", quote=quote, quote_start=start,
                          quote_end=end, source=SOURCE)

    def test_quote_must_sit_at_its_offsets_inside_the_source(self):
        """A draft is valid only with a non-empty quote found at offsets that lie inside the source text."""
        self.assertEqual(self.draft("KU Leuven", 14, 23).quote, "KU Leuven")
        for quote, start, end in (("KU Leuven", 13, 22), ("", 0, 0), ("", 5, 5), ("Anne", -24, -20),
                                  ("Leuven.", 17, 99), ("x", 3, 2)):
            with self.subTest(quote=quote, start=start, end=end), self.assertRaises(ValidationError):
                self.draft(quote, start, end)


class NameKeyTest(unittest.TestCase):
    def test_name_key_folds_accents_particles_case_and_punctuation(self):
        """Spellings of one name that differ only in accents, capitals, hyphens or spacing get one key."""
        self.assertEqual(name_key("Julien de Wit"), name_key("Julien  De WIT"))
        self.assertEqual(name_key("Grégoire Wallenborn"), "gregoire wallenborn")
        self.assertEqual(name_key("Marie-Astrid de Wit"), "marie astrid de wit")
        self.assertEqual(name_key("Łukasz Ćwik"), "łukasz cwik")


if __name__ == "__main__":
    unittest.main()
