"""Brain rot mode: the word bank and the writer's style (pipeline/llm.py).  python -m unittest discover tests"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import llm  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
