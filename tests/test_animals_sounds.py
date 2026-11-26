"""Animals the studio builds with a body template, and sounds that would play on top of each other.
From the "Guess what?" test video (2026-11-26): a kudu was 4 grey blocks, and a boing and a pop played at once.
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import propgen as P  # noqa: E402
import run_episode as R  # noqa: E402


class Animals(unittest.TestCase):
    def test_more_animals_get_a_body(self):
        for kind in ("kudu", "gazelle", "crocodile", "ostrich", "clownfish", "butterfly"):
            self.assertIsNotNone(P.animal_family(kind), kind)

    def test_body_words_name_an_unknown_animal(self):
        self.assertEqual(P.animal_family("jackalope", "small, antlers, fur"), "beast")
        self.assertIsNone(P.animal_family("wing_chair", "big chair with wings"))    # a made thing
        self.assertIsNone(P.animal_family("cat_bed", "soft"))


class Sounds(unittest.TestCase):
    def test_an_arrival_sound_replaces_one_at_the_same_moment(self):
        ep = {"shots": [{"line": "It's a kudu!", "sfx": "boing", "sfx_at": 0.2, "talk": 1.0,
                         "events": [{"who": "kudu", "do": "appear"}]}]}
        timing = {"fps": 24, "shots": [{"f0": 1, "n": 48}]}
        names = [s for s, _, _ in R.sfx_events(ep, timing, {"volume": 0.5, "auto": True})]
        self.assertNotIn("boing", names)                    # 0.2 s: right where the kudu pops in
        self.assertEqual(len(names), 1)


if __name__ == "__main__":
    unittest.main()
