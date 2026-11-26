"""What a cutaway shows (run_episode.resolve_cutaways) - from the Top 5 test video, where "a speeding car zooming by"
became a thing called "car_by".  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import propgen as P  # noqa: E402
import run_episode as R  # noqa: E402


def subject(text):
    ep = {"shots": [{"line": text + " yes", "cutaway": text}], "cast": {}}
    R.resolve_cutaways(ep, log=lambda m: None)
    return list(ep["cast"])


class Subjects(unittest.TestCase):
    def test_describing_words_are_not_the_thing(self):
        self.assertEqual(subject("a speeding car zooming by"), ["car"])
        self.assertEqual(subject("a running cheetah"), ["cheetah"])
        self.assertEqual(subject("a cheetah running"), ["cheetah"])

    def test_ing_nouns_stay(self):
        self.assertEqual(subject("a tall building"), ["tall_building"])
        self.assertEqual(subject("a diamond ring sparkling"), ["diamond_ring"])

    def test_a_cast_entry_of_that_name_is_reused(self):
        ep = {"shots": [{"line": "a rubber band snaps", "cutaway": "a stretched rubber band"}],
              "cast": {"rubber_band": {"type": "thing", "looks": "red", "model_id": "x"}}}
        R.resolve_cutaways(ep, log=lambda m: None)
        self.assertEqual(list(ep["cast"]), ["rubber_band"])          # a card's swap isn't lost to rubber_band2


class CheckVersion(unittest.TestCase):
    def test_props_checked_before_the_fix_are_checked_again(self):
        self.assertGreaterEqual(P.CHECK_V, 2)
        self.assertLess({"checked": True}.get("check_v", 1), P.CHECK_V)


if __name__ == "__main__":
    unittest.main()
