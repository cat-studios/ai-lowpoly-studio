"""Fixes from the first production videos of the new kinds (2026-11-27): a falling sky set picked for a bedroom
story, a made-up "whispering" pose that replaced her landing, captions wider than the frame.
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import animlib  # noqa: E402
import autodirect as A  # noqa: E402
import run_episode as R  # noqa: E402

SETS = {"deep_air_bedroom": {"name": "Deep Air Bedroom", "description": "a bedroom falling through the sky",
                             "marks": {}, "air": "sky"},
        "cozy_bedroom": {"name": "Cozy Bedroom", "description": "a bedroom with a desk", "marks": {}}}


class AirSets(unittest.TestCase):
    def test_sky_sets_only_for_sky_words(self):
        self.assertEqual(A.match_set("a cozy bedroom", SETS), "cozy_bedroom")
        only_air = {"deep_air_bedroom": SETS["deep_air_bedroom"]}
        self.assertTrue(A.match_set("a messy bedroom", only_air).startswith("new:"))
        self.assertEqual(A.match_set("a bedroom falling through the sky", only_air), "deep_air_bedroom")


class Landing(unittest.TestCase):
    def test_a_made_animation_never_replaces_a_landing(self):
        ep = {"shots": [{"action": "land", "want": "whispering"}, {"action": "nya"}]}
        R.resolve_animations(ep, log=lambda *a: None)
        self.assertEqual([s["action"] for s in ep["shots"]], ["land", "idle"])
        self.assertIn("whispering", animlib.NOT_ACTIONS)


class WideCaptions(unittest.TestCase):
    def test_a_long_word_group_is_made_smaller(self):
        import tempfile
        shots = [{"line": "Bed-Shaker-O-Matic 3000!", "talk": 1.5, "lead": 0.1}]
        timing = {"fps": 12, "total_frames": 36, "shots": [{"f0": 1, "n": 36}]}
        cap = {"font": "Arial Black", "size": 0.06, "position": 0.25, "mode": "words", "group": 2, "cycle": [],
               "title_size": 0.04, "hook_pop": False, "hud": False, "stickers": False}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.ass"
            R.write_captions(p, {"title": ""}, shots, timing, [216, 384], cap, {})
            line = next(l for l in p.read_text(encoding="utf-8").splitlines() if "SHAKER" in l)
        self.assertIn("\\fs", line)


if __name__ == "__main__":
    unittest.main()
