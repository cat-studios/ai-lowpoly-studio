"""Brain rot mode: the word bank and the writer's style (pipeline/llm.py).  python -m unittest discover tests"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import llm  # noqa: E402
import run_episode  # noqa: E402
import weekly  # noqa: E402


class BrainRot(unittest.TestCase):
    def test_words_come_from_the_bank_without_repeats(self):
        bank = ["rizz", "sigma", "ohio", "aura"]
        got = llm.pick_brainrot_words(bank, 3, random.Random(1))
        self.assertEqual(len(got), 3)
        self.assertEqual(len(set(got)), 3)
        self.assertTrue(set(got) <= set(bank))

    def test_a_small_or_empty_bank_still_works(self):
        self.assertEqual(llm.pick_brainrot_words(["rizz"], 3, random.Random(1)), ["rizz"])
        self.assertEqual(llm.pick_brainrot_words([], 3), [])
        self.assertEqual(llm.pick_brainrot_words(["  ", "ohio"], 2, random.Random(1)), ["ohio"])

    def test_the_writer_is_told_the_style_and_the_words(self):
        rule = llm.brainrot_rule(["rizz", "ohio"])
        self.assertIn("BRAIN ROT STYLE", rule)
        self.assertIn("rizz, ohio", rule)
        self.assertIn("family-friendly", rule)


class Highlight(unittest.TestCase):
    def test_bank_words_and_phrases_are_found_ignoring_case_and_punctuation(self):
        words = "THAT'S PURE RIZZ, NO CAP! FANUM TAX?".split()
        marks = run_episode.highlight_marks(words, ["rizz", "no cap", "fanum tax", "sigma"])
        self.assertEqual(marks, {2, 3, 4, 5, 6})
        self.assertEqual(run_episode.highlight_marks(["CAPTAIN", "NO"], ["no cap"]), set())   # half a phrase isn't it
        self.assertEqual(run_episode.highlight_marks(["RIZZ"], []), set())

    def test_the_caption_file_colours_the_bank_word(self):
        import tempfile
        from pathlib import Path as P
        cap = {"font": "Arial", "size": 0.05, "position": 0.3, "title_size": 0.04, "mode": "words", "group": 1,
               "hook_pop": False, "uppercase": True, "highlight_words": ["rizz"], "highlight_color": "#ff0000"}
        shots = [{"line": "Pure rizz today", "talk": 1.5, "lead": 0.1}]
        timing = {"fps": 24, "total_frames": 48, "shots": [{"f0": 1, "n": 48}]}
        out = P(tempfile.mkdtemp()) / "c.ass"
        run_episode.write_captions(out, {"title": ""}, shots, timing, [216, 384], cap, {})
        text = out.read_text(encoding="utf-8")
        rizz = next(l for l in text.splitlines() if l.endswith("RIZZ"))
        pure = next(l for l in text.splitlines() if l.endswith("PURE"))
        self.assertIn("{\\c&H000000FF&}RIZZ", rizz)                       # red, in ASS's blue-green-red order
        self.assertIn("\\fscx115\\fscy115", rizz)                         # pops in bigger and stays a bit bigger
        self.assertNotIn("&H000000FF", pure)
        self.assertNotIn("fscx115", pure)


class Chance(unittest.TestCase):
    def test_brain_rot_by_chance_for_videos_made_without_you(self):
        items = [{"id": str(i)} for i in range(200)]
        weekly.roll_brainrot(items, 30, random.Random(4))
        n = sum(1 for it in items if it.get("brainrot"))
        self.assertTrue(35 < n < 85, n)                                     # about 30 %
        self.assertFalse(any(it.get("brainrot") for it in weekly.roll_brainrot([{}, {}], 0)))
        self.assertTrue(all(it.get("brainrot") for it in weekly.roll_brainrot([{}, {}], 100)))


if __name__ == "__main__":
    unittest.main()
