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
        with mock.patch.object(llm, "big_server_model", lambda url, wanted=None: "huge"):
            self.assertEqual(self.call(MAIN), ("http://big", "huge"))

    def test_server_without_models_falls_back_here(self):
        with mock.patch.object(llm, "big_server_model", lambda url, wanted=None: None):
            self.assertEqual(self.call(MAIN), ("http://main", "small"))


    def test_off_uses_this_pc_with_its_own_model(self):
        # the big server's model ("huge") isn't on this PC: asking for it there would fail
        self.assertEqual(self.call({**MAIN, "big_server": False}), ("http://main", "small"))

    def test_no_big_server_lets_design_model_pick_a_local_model(self):
        self.assertEqual(self.call({**MAIN, "design_url": ""}), ("http://main", "huge"))


class AutoModel(unittest.TestCase):
    """The user, 2026-11-28: his brother swaps models a lot - use whatever the server has."""
    def ask(self, wanted, tags, loaded=()):
        def req(url, path, payload=None, timeout=0):
            if path == "/api/tags":
                return {"models": [{"name": n, "modified_at": f"2026-11-{i + 10}"} for i, n in enumerate(tags)]}
            return {"models": [{"name": n} for n in loaded]}
        with mock.patch.object(llm, "_req", req), mock.patch.object(llm, "_BIG_MODEL", {}):
            return llm.big_server_model("http://big", wanted)

    def test_named_model_when_its_there(self):
        self.assertEqual(self.ask("a:1", ["a:1", "b:2"], loaded=["b:2"]), "a:1")

    def test_loaded_then_newest_when_the_name_is_gone(self):
        self.assertEqual(self.ask("old:80b", ["a:1", "b:2"], loaded=["a:1"]), "a:1")
        self.assertEqual(self.ask("", ["a:1", "b:2"]), "b:2")

    def test_down_or_empty(self):
        self.assertIsNone(self.ask("", []))
        with mock.patch.object(llm, "_req", side_effect=OSError("down")), mock.patch.object(llm, "_BIG_MODEL", {}):
            self.assertIsNone(llm.big_server_model("http://big", ""))


class TextRouting(unittest.TestCase):
    def test_off_keeps_all_writing_on_this_pc(self):
        with mock.patch("settings.load_settings", lambda: {"ollama": {**MAIN, "big_server": False}}):
            self.assertIsNone(llm._remote_for("http://main", False))


if __name__ == "__main__":
    unittest.main()
