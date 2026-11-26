"""Two main characters talking with each other (autodirect.conversations).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import ideas  # noqa: E402
import templates  # noqa: E402

CHAT = ("Who would win, a cat or a dog?\nEthan: A dog, obviously.\nNo way, cats are faster!\n"
        "Ethan: Faster at napping maybe.\nComment who wins!")


class Conversation(unittest.TestCase):
    def test_back_and_forth_lines_talk_to_each_other(self):
        s = A.direct(CHAT, "cafe", beat_words=0, speakers={"ethan": "ethan"})["shots"]
        self.assertEqual([x.get("talk_to") for x in s], [None, "main", "ethan", "main", None])   # hook + "comment!"
        self.assertTrue(any(x.get("both") for x in s))

    def test_not_with_one_main_character(self):
        s = A.direct("Who would win?\nA cat, obviously.", "cafe", beat_words=0)["shots"]
        self.assertFalse(any(x.get("talk_to") for x in s))

    def test_template_is_listed(self):
        self.assertIn("conversation", templates.TEMPLATES)
        self.assertIn("conversation", ideas.TEMPLATE_IDS)


if __name__ == "__main__":
    unittest.main()
