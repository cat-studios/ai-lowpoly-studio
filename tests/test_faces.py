"""Close-up reactions: wink, blush, eye-roll (autodirect.face_closeups).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import catalog  # noqa: E402


class Faces(unittest.TestCase):
    def test_cue_words_give_the_reaction_in_a_close_up(self):
        s = A.direct("Hello friends!\nJust kidding, I ate it all.\nAww, stop it!\nUgh, seriously?", "cafe",
                     beat_words=0)["shots"]
        self.assertEqual([x["expression"] for x in s[1:]], ["wink", "blush", "eyeroll"])
        self.assertTrue(all(x["camera"] == "closeup" for x in s[1:]))

    def test_the_script_wins_and_the_hook_is_left_alone(self):
        s = A.direct("Ugh, seriously?\n[wide, happy] Just kidding!", "cafe", beat_words=0)["shots"]
        self.assertNotEqual(s[0]["expression"], "eyeroll")          # the opening line is the hook
        self.assertEqual((s[1]["camera"], s[1]["expression"]), ("wide", "happy"))

    def test_they_are_expressions_scripts_can_use(self):
        for e in ("wink", "blush", "eyeroll"):
            self.assertIn(e, catalog.EXPRESSIONS)
        self.assertEqual(A.direct("[blushing] Oh!", "cafe", beat_words=0)["shots"][0]["expression"], "blush")


if __name__ == "__main__":
    unittest.main()
