"""Floating (autodirect float_up / land): two production videos (2026-11-27) floated from [float_up] to the end with
her right hand raised.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402


def actions(script):
    return [s.get("action") for s in A.direct(script, "cafe", beat_words=0, opening="walk")["shots"]]


class Floating(unittest.TestCase):
    def test_floating_with_nothing_holding_her_comes_down(self):
        a = actions("Wow, look at this street.\n"
                    "[surprised, float_up] Whoa, why am I floating?!\n"
                    "It feels so light up here.\n"
                    "Now every step feels like treasure.\n"
                    "I'm rich enough to buy this street!")
        self.assertEqual(a[1], "float_up")
        self.assertNotEqual(a[2], "land")                     # still up for the next line
        self.assertEqual(a[3], "land")                        # then down
        self.assertNotIn("float_up", a[4:])

    def test_beats_of_one_line_count_as_one_line(self):
        # the director works per beat (a few words each): the gold video's lift-off line is 3 beats long
        s = A.direct("Look at this street.\n"
                     "[surprised, float_up] Whoa, why am I floating three feet off the pavement?!\n"
                     "Now every step feels like stomping on hot treasure.\n"
                     "And listen to this rhythmic clink of my paws!", "cafe", beat_words=4, opening="walk")["shots"]
        lift = next(k for k, x in enumerate(s) if x.get("action") == "float_up")
        land = next(k for k, x in enumerate(s) if x.get("action") == "land")
        self.assertNotEqual(s[land]["beat_group"], s[lift]["beat_group"])
        self.assertTrue(s[land]["line"].lower().startswith("and listen"))   # the first beat of the line after next

    def test_a_landing_word_still_lands_her_first(self):
        a = actions("Hello there.\n[float_up] I'm floating!\nOkay, back down now.\nThat was fun.")
        self.assertEqual(a[2], "land")

    def test_balloons_keep_her_up_until_they_pop(self):
        a = actions("Look at my balloons!\n"
                    "[float_up] I'm floating with my balloons!\n"
                    "So high up here.\n"
                    "The clouds are so soft.\n"
                    "Oh no, they popped!")
        self.assertNotIn("land", a[2:4])                      # held up by the balloons
        self.assertEqual(a[4], "land")


if __name__ == "__main__":
    unittest.main()
