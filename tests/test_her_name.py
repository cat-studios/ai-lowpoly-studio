"""Her name comes from the Name box on the Characters page (2026-11-27: the writer called her Lila, Luna, Cat...).
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import llm  # noqa: E402

LINES = ["[closeup] My name is Lila and my stress level is huge!", "Hey guys, I'm Luna! Welcome!",
         "[wide] Hi, I'm so tired today.", "Mom: My name is Karen, honey."]


class HerName(unittest.TestCase):
    def test_invented_names_become_hers(self):
        out = llm.fix_self_names(LINES, {"name": "Lavender", "id": "catgirl"})
        self.assertEqual(out[:3], ["[closeup] My name is Lavender and my stress level is huge!",
                                   "Hey guys, I'm Lavender! Welcome!", "[wide] Hi, I'm so tired today."])
        self.assertEqual(out[3], LINES[3])                      # someone else's line stays
        self.assertIn('exactly "Lavender"', llm.name_rule({"name": "Lavender"}))

    def test_no_name_means_she_doesnt_name_herself(self):
        out = llm.fix_self_names(LINES, {"name": "", "id": "catgirl"})
        self.assertEqual(out[:2], ["[closeup] My stress level is huge!", "Hey guys! Welcome!"])
        self.assertIn("NO name", llm.name_rule({"name": ""}))


if __name__ == "__main__":
    unittest.main()
