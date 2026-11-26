"""The big Ollama server switch (Settings -> AI tools): 3D design and text routing.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import llm  # noqa: E402
import propgen  # noqa: E402

MAIN = {"url": "http://main", "model": "small", "design_url": "http://big", "design_model": "huge",
        "design_scope": "text"}


class DesignCall(unittest.TestCase):
    def call(self, ollama):
        seen = []
        with mock.patch.object(propgen, "_DESIGN_DOWN", []):
            propgen.design_call(lambda url, model: seen.append((url, model)) or "ok", ollama)
        return seen[0]

    def test_on_uses_the_big_server_and_its_model(self):
        self.assertEqual(self.call(MAIN), ("http://big", "huge"))

    def test_off_uses_this_pc_with_its_own_model(self):
        # the big server's model ("huge") isn't on this PC: asking for it there would fail
        self.assertEqual(self.call({**MAIN, "big_server": False}), ("http://main", "small"))

    def test_no_big_server_lets_design_model_pick_a_local_model(self):
        self.assertEqual(self.call({**MAIN, "design_url": ""}), ("http://main", "huge"))


class TextRouting(unittest.TestCase):
    def test_off_keeps_all_writing_on_this_pc(self):
        with mock.patch("settings.load_settings", lambda: {"ollama": {**MAIN, "big_server": False}}):
            self.assertIsNone(llm._remote_for("http://main", False))


if __name__ == "__main__":
    unittest.main()
