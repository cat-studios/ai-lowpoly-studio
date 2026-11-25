"""Quick previews (run_episode --preview): never make sets or animations, and the storyboard has one still per shot.
python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import propgen  # noqa: E402
import run_episode as R  # noqa: E402


class PreviewSets(unittest.TestCase):
    def test_new_and_auto_sets_become_existing_ones(self):
        ep = {"title": "What if cats ran a cafe?", "set": "auto",
              "shots": [{"line": "hi", "want": "salute"}, {"line": "there", "set": "new:a haunted volcano lair"},
                        {"line": "x", "set": "park"}]}
        R.preview_sets(ep, log=lambda m: None)
        for sid in [ep["set"]] + [s["set"] for s in ep["shots"] if s.get("set")]:
            self.assertTrue(R.set_exists(sid), sid)
        self.assertEqual(ep["shots"][2]["set"], "park")          # a real set stays
        self.assertNotIn("want", ep["shots"][0])                 # no animation making in a preview


class Storyboard(unittest.TestCase):
    def test_one_still_per_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames, out = Path(tmp) / "frames", Path(tmp) / "out"
            frames.mkdir()
            for f in range(1, 11):
                (frames / f"f_{f:04d}.png").write_bytes(b"png%d" % f)
            ep = {"title": "T", "set": "cafe", "shots": [{"line": "one", "camera": "wide"}, {"line": "two"}]}
            timing = {"shots": [{"f0": 1, "n": 4}, {"f0": 5, "n": 6}]}
            sb = json.loads(R.write_storyboard(ep, timing, frames, out).read_text(encoding="utf-8"))
            self.assertEqual([s["image"] for s in sb["shots"]], ["shot_01.png", "shot_02.png"])
            self.assertEqual((out / "shot_02.png").read_bytes(), b"png8")    # the middle of shot 2 (frames 5-10)
            self.assertEqual(sb["shots"][0]["camera"], "wide")


class PreviewProps(unittest.TestCase):
    def test_stand_in_without_ai(self):
        os.environ["STUDIO_PREVIEW"] = "1"
        try:
            d = propgen.design("zz_preview_test_gadget", "a shiny gadget", ollama={"url": "http://127.0.0.1:9"},
                               save=False, use_imported=False)
            self.assertTrue(d.get("preview"))
            self.assertFalse(propgen._prop_check_on())
        finally:
            os.environ.pop("STUDIO_PREVIEW", None)


if __name__ == "__main__":
    unittest.main()
