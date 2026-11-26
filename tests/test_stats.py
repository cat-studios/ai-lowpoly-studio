"""Stats (pipeline/stats.py) and cover B (pipeline/cover.py).  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import cover  # noqa: E402
import stats  # noqa: E402


class Stats(unittest.TestCase):
    def test_a_post_is_matched_to_its_video_by_the_title(self):
        titles = {"goldfish": "Do goldfish really forget everything?", "moon": "What if the moon vanished?"}
        post = {"caption": "🐟 Do goldfish REALLY forget everything in 3 seconds? #fish #reels"}
        self.assertEqual(stats.match(post, titles), "goldfish")
        self.assertIsNone(stats.match({"caption": "a cat video"}, titles))

    def test_typed_views_and_averages(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "stats.json"
            facts = {"a": {"title": "A", "template": "top_five", "seconds": 30, "set": "park", "hook": "", "shots": 9,
                           "language": "en"},
                     "b": {"title": "B", "template": "top_five", "seconds": 55, "set": "cafe", "hook": "", "shots": 9,
                           "language": "en"}}
            with mock.patch.object(stats, "STORE", store), mock.patch.object(stats, "facts", lambda k: facts[k]):
                stats.update("a", {"views": "1000", "posted_cover": "b"})
                stats.update("b", {"views": 200})
                s = stats.summary()
        self.assertEqual([r["key"] for r in s["rows"]], ["a", "b"])
        self.assertEqual(s["by"]["kind"][0], {"value": "top_five", "videos": 2, "avg": 600})
        self.assertEqual(s["by"]["cover"][0]["value"], "B")
        self.assertEqual({e["value"] for e in s["by"]["length"]}, {"20-35 s", "50 s +"})


class CoverB(unittest.TestCase):
    def test_runner_up_is_another_frame(self):
        cands = [(0, "f0", 3), (4, "f4", 5), (9, "f9", 3)]
        self.assertEqual(cover.runner_up(cands, 1), 2)                # equal scores: the one further away
        self.assertIsNone(cover.runner_up(cands[:1], 0))


if __name__ == "__main__":
    unittest.main()
