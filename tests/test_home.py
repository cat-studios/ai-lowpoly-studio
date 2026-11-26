"""Her room's souvenirs (pipeline/home.py).  python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import home  # noqa: E402


class Souvenirs(unittest.TestCase):
    def test_a_cutaway_is_kept_first_and_placed_along_the_walls(self):
        ep = {"title": "Top 5 fast animals", "cast": {
            "mom": {"type": "person"},
            "cup": {"type": "thing", "def": {"parts": [1], "height": 0.2}},
            "cheetah": {"type": "thing", "def": {"parts": [1], "height": 0.9}}},
            "shots": [{"events": [{"who": "mom", "do": "enter"}, {"who": "cup", "do": "hold"}]},
                      {"events": [{"who": "cheetah", "do": "appear", "cutaway": True}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "home.json"
            p.write_text(json.dumps({"props": [{"kind": "bed", "pos": [-2.3, 2.9]}]}), encoding="utf-8")
            with mock.patch.object(home, "path", lambda: p), mock.patch.object(home, "on", lambda: True):
                sv = home.collect(ep, log=lambda m: None)
                rec = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(sv["kind"], "cheetah")
        souv = [x for x in rec["props"] if x.get("souvenir")]
        self.assertEqual(len(souv), 1)
        self.assertNotEqual(souv[0]["pos"], [-2.3, 2.9])                  # not on the bed's spot
        self.assertAlmostEqual(souv[0]["scale"], 0.6 / 0.9, places=2)    # a keepsake, not a full-size cheetah
        self.assertIn("souv_cheetah", rec["custom_props"])

    def test_people_are_not_souvenirs(self):
        ep = {"cast": {"mom": {"type": "person"}}, "shots": [{"events": [{"who": "mom", "do": "enter"}]}]}
        self.assertIsNone(home.souvenir_from(ep))


if __name__ == "__main__":
    unittest.main()
