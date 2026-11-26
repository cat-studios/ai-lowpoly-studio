"""The weekly plan takes the best kinds of video first (Stats numbers).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import weekly  # noqa: E402


class Rank(unittest.TestCase):
    def db(self):
        return {"ideas": [{"id": "1", "template": "quick_facts", "added": 1},
                          {"id": "2", "template": "top_five", "added": 2},
                          {"id": "3", "template": "what_if", "added": 3},
                          {"id": "4", "template": "top_five", "added": 4}]}

    def test_best_kind_comes_first_when_slots_are_short(self):
        got = weekly.pick(self.db(), 2, rank=("top_five",))
        self.assertEqual(got[0]["template"], "top_five")
        self.assertEqual(len(got), 2)

    def test_with_more_slots_every_kind_still_appears(self):
        kinds = {i["template"] for i in weekly.pick(self.db(), 3, rank=("top_five",))}
        self.assertEqual(kinds, {"top_five", "quick_facts", "what_if"})

    def test_no_ranking_keeps_the_plain_order(self):
        # newest first, one of each kind in turn: top_five (4), what_if (3), quick_facts (1)
        self.assertEqual([i["id"] for i in weekly.pick(self.db(), 3)], ["4", "3", "1"])


if __name__ == "__main__":
    unittest.main()
