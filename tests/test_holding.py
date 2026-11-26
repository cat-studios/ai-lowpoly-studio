"""Props she holds (autodirect.held_things).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402


def direct(script):
    return A.direct(script, "cafe", beat_words=0)


class Holding(unittest.TestCase):
    def test_she_holds_it_for_the_line_and_puts_it_away(self):
        r = direct("Look at this cup I found!\nIt is so shiny.\nThis is my lucky coin!")
        s = r["shots"]
        self.assertIn({"who": "cup", "do": "hold"}, s[0]["events"])
        self.assertIn({"who": "cup", "do": "vanish"}, s[1]["events"])
        self.assertEqual(s[0]["action"], "idle")              # "look at" was a point with the cup hand
        self.assertIn({"who": "coin", "do": "hold"}, s[2]["events"])
        self.assertTrue(r["cast"]["cup"]["held"])

    def test_not_without_a_cue_or_on_someone_elses_line(self):
        self.assertFalse(direct("I like to read a book.")["cast"])
        r = direct("[+mom enter] Mom: Look at my cup!")
        self.assertNotIn("cup", r["cast"])


if __name__ == "__main__":
    unittest.main()
