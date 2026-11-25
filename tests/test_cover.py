"""Cover pictures (pipeline/cover.py): which frames are offered to the picture model.  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import cover  # noqa: E402


class Candidates(unittest.TestCase):
    def test_only_shots_that_show_her(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp)
            for f in range(1, 61):
                (frames / f"f_{f:04d}.png").write_bytes(b"x")
            shots = [{"camera": "closeup", "expression": "happy"}, {"camera": "back"}, {"camera": "medium", "cutaway": "an owl"},
                     {"camera": "tiny"}, {"camera": "medium"}, {"camera": "wide"}]
            timing = {"shots": [{"f0": 1 + 10 * i, "n": 10} for i in range(6)]}
            got = cover.candidates({"shots": shots}, timing, frames)
            self.assertEqual([c[0] for c in got], [0, 4, 5])         # no back view, cutaway or tiny figure
            self.assertEqual(got[0][1].name, "f_0006.png")           # the middle of the shot
            self.assertGreater(got[0][2], got[1][2])                 # a close, expressive shot scores higher

    def test_spread_over_the_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp)
            for f in range(1, 201):
                (frames / f"f_{f:04d}.png").write_bytes(b"x")
            shots = [{"camera": "medium"} for _ in range(20)]
            timing = {"shots": [{"f0": 1 + 10 * i, "n": 10} for i in range(20)]}
            got = cover.candidates({"shots": shots}, timing, frames)
            self.assertEqual(len(got), cover.MAX_CANDIDATES)
            self.assertGreaterEqual(max(c[0] for c in got), 15)      # not just the first eight shots


if __name__ == "__main__":
    unittest.main()
