"""Custom Video's "who and what appears" cards (pipeline/castcards.py).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import castcards  # noqa: E402
import imported  # noqa: E402


class Cards(unittest.TestCase):
    def test_cutaways_get_a_card_and_a_pick_shows(self):
        ep = {"set": "cafe", "shots": [
            {"line": "Number 5: the cheetah!", "cutaway": "a running cheetah"},
            {"line": "Faster than a car", "events": [{"who": "mailman", "do": "enter"}]}],
            "cast": {"mailman": {"type": "person", "looks": "mailman", "model_id": "pack_man_1"}}}
        with mock.patch.object(imported, "model_def", lambda mid, kind="", looks="": {"name": "Man 1"}):
            cards = {c["who"]: c for c in castcards.cards(ep)}
        self.assertTrue(cards["cheetah"]["cutaway"])                  # the cutaway's subject, as at render
        self.assertEqual(cards["cheetah"]["shots"], [1])
        self.assertEqual(cards["mailman"]["label"], "Your pick: Man 1")
        self.assertTrue(cards["mailman"]["picked"])
        self.assertNotIn("cheetah", ep["cast"])                       # the episode itself isn't changed


if __name__ == "__main__":
    unittest.main()
