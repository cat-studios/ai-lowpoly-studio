"""Top 5 test video (2026-11-26): cutaways on two-word beats, a second AI cutaway on a line, the hook's camera.
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import templates  # noqa: E402

SCRIPT = """[wide, excited] What are the five fastest animals on Earth?
[cutaway: cheetah] Number 5: The Cheetah! At sixty miles per hour!
[cutaway: pronghorn] Number 4: The Pronghorn! Faster than a speeding car!"""


class TopFive(unittest.TestCase):
    def setUp(self):
        self.r = A.direct(SCRIPT, "cafe", **templates.pacing("top_five"))

    def test_hook_keeps_its_close_up(self):
        first = self.r["shots"][0]
        self.assertEqual((first["camera"], first["move"]), ("closeup", "push_in"))     # the writer asked [wide]

    def test_cutaway_beat_is_long_enough(self):
        cut = next(s for s in self.r["shots"] if s.get("cutaway") == "cheetah")
        self.assertEqual(cut["line"], "Number 5: The Cheetah!")                       # was "Number 5:" alone

    def test_no_second_cutaway_on_a_line(self):
        k = next(i for i, s in enumerate(self.r["shots"]) if "speeding car" in s.get("line", ""))
        A.add_scene_plan(self.r, {"cutaways": [{"line": k, "show": "a speeding car zooming by"}]}, "cafe")
        self.assertNotIn("cutaway", self.r["shots"][k])


if __name__ == "__main__":
    unittest.main()
