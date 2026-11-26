"""The check after each render (pipeline/review.py), the parts without the picture model.
python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import review  # noqa: E402

TIMING = {"fps": 24, "shots": [{"f0": 1, "n": 12}, {"f0": 13, "n": 72}, {"f0": 85, "n": 48}]}


class Checks(unittest.TestCase):
    def test_short_and_lost_cutaways(self):
        ep = {"shots": [{"line": "Number 5:", "cutaway": "cheetah"}, {"line": "it runs"}, {"line": "a falcon"}]}
        out = []
        review.cutaway_issues(ep, TIMING, [0, 2], out)               # the script asked for 2, one was dropped
        whats = " | ".join(i["what"] for i in out)
        self.assertIn("under 1 s", whats)                             # 12 frames at 24 fps = half a second
        self.assertIn("1 of 2 cutaway(s)", whats)
        self.assertEqual(out[1]["shots"], [3])

    def test_weak_prop_and_squeezed_arrival(self):
        ep = {"shots": [{"events": [{"who": "kudu", "do": "appear"}]}],
              "cast": {"kudu": {"type": "thing", "def": {"checked": False, "look_score": 4}}}}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "blender.log").write_text("[cast] warning: no free spot beside her at (0.0, 0.0) for a "
                                                   "1.21 m cast member (11x furniture)", encoding="utf-8")
            out = []
            review.cast_issues(ep, Path(tmp), out)
        self.assertIn("kudu (4/10)", out[0]["what"])
        self.assertEqual(out[0]["shots"], [1])
        self.assertIn("no room", out[1]["what"])

    def test_nothing_to_say_about_a_clean_video(self):
        out = []
        review.cutaway_issues({"shots": [{"line": "hi"}, {"line": "a"}, {"line": "b"}]}, TIMING, [], out)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
