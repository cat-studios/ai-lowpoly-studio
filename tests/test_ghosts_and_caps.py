"""Ghost and shadow people (autodirect.cast_style / apply_styles, blender_cast.styled) and words in capitals read
as words, not spelled out (run_episode.speakable), 2026-11-27.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import run_episode as R  # noqa: E402


class Ghosts(unittest.TestCase):
    def test_by_direction_and_by_name(self):
        r = A.direct("[medium] Hi.\n[+mom enter ghost] Mom: I never left.\n[+shadow_figure appear] Who is that?\n"
                     "[+past_self enter] Past me says hi.\n[+crowd appear shadow] They watch.\n[+dog enter] Woof.",
                     "park")
        got = {k: (v.get("type"), v.get("style")) for k, v in r["cast"].items()}
        self.assertEqual(got["mom"], ("person", "ghost"))
        self.assertEqual(got["shadow_figure"], ("person", "shadow"))     # "shadow" alone is a thing word
        self.assertEqual(got["past_self"], ("person", "ghost"))
        self.assertEqual(got["crowd"][1], "shadow")
        self.assertIsNone(got["dog"][1])

    def test_style_words_are_never_actions(self):
        import animlib
        for w in ("ghost", "ghostly", "shadow", "silhouette"):
            self.assertIn(w, animlib.NOT_ACTIONS)
        self.assertEqual(A.cast_style("spirit_of_grandma"), "ghost")
        self.assertEqual(A.cast_style("man", {"looks": "a faceless silhouette"}), "shadow")
        self.assertIsNone(A.cast_style("baker", {"looks": "a cheerful baker"}))


class Capitals(unittest.TestCase):
    def test_emphasis_is_read_as_words(self):
        self.assertEqual(R.speakable("Did my flat just turn into an EGG?!"), "Did my flat just turn into an egg?!")
        self.assertEqual(R.speakable("going UP instead of down"), "going up instead of down")
        self.assertEqual(R.speakable("NYA! WHY?!"), "nya! why?!")

    def test_real_abbreviations_stay(self):
        self.assertEqual(R.speakable("I watch TV and NASA videos, OK?"), "I watch TV and NASA videos, OK?")
        self.assertEqual(R.speakable("My DNA is 100% CAT"), "My DNA is 100% cat")


class GhostScriptSlips(unittest.TestCase):
    """From the first ghost test video (zz_test_ghosts): a second bracket group was spoken ("Past"), the label
    "Past Lavender:" wasn't a speaker, the AI cast step added a half-named "past", [wide_eyes] was made a pose."""
    def test_two_bracket_groups_and_a_named_label(self):
        r = A.direct("[medium] Hi.\n[wide, scared] [+past_self appear ghost] Past Lavender: You forgot us!\n"
                     "[closeup, wide_eyes] Oh.", "park", speakers={"lavender": "main"}, beat_words=4)
        ghost = [s for s in r["shots"] if s.get("events")][0]
        self.assertEqual(ghost["speaker"], "past_self")
        self.assertEqual(ghost["line"], "You forgot us!")
        self.assertEqual(ghost["camera"], "wide")
        self.assertEqual(r["shots"][-1]["expression"], "surprised")
        self.assertNotIn("want", r["shots"][-1])
        r = A.add_cast_plan(r, {"cast": {"past": {"type": "person", "looks": "a ghost"}}, "events": []})
        self.assertEqual(sorted(r["cast"]), ["past_self"])

    def test_label_speaker(self):
        sp = {"mom": "mom", "lavender": "main", "past self": "past_self", "past_self": "past_self"}
        self.assertEqual(A.label_speaker("Ghost Mom", sp), "mom")
        self.assertEqual(A.label_speaker("Past Lavender", sp), "past_self")
        self.assertIsNone(A.label_speaker("Old Lady", sp))
        self.assertIsNone(A.label_speaker("Warning", sp))


if __name__ == "__main__":
    unittest.main()
