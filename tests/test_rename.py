"""Renaming (the user, 2026-11-28): animations keep their old word working; made props keep a name you gave them
through a redesign.  python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import animgen  # noqa: E402
import animlib  # noqa: E402
import propgen  # noqa: E402


class AnimRename(unittest.TestCase):
    def test_old_word_still_works(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(animlib, "LIB", Path(tmp)):
            animlib.save(dict(next(iter(animlib.BUILTIN.values())), name="yawn", checked=True))
            (Path(tmp) / "yawn.gif").write_bytes(b"GIF89a")
            a = animgen.rename("yawn", "big yawn")
            self.assertEqual(a["name"], "big_yawn")
            lib = animlib.library()
            self.assertIn("big_yawn", lib)
            self.assertNotIn("yawn", lib)
            self.assertTrue((Path(tmp) / "big_yawn.gif").exists())
            self.assertEqual(animlib.aliases(), {"yawn": "big_yawn"})
            with mock.patch.object(animgen, "_ollama", side_effect=AssertionError("would make a new one")):
                self.assertEqual(animgen.ensure("yawn"), "big_yawn")
            with self.assertRaises(ValueError):
                animgen.rename("big_yawn", "yawn")          # the old word is taken (it's an alias)


class PropName(unittest.TestCase):
    def test_redesign_keeps_your_name(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(propgen, "LIB", Path(tmp)):
            propgen._save({"kind": "teapot", "name": "Grandma's teapot", "renamed": True, "parts": []})
            propgen._save({"kind": "teapot", "name": "teapot", "parts": [{"shape": "box"}]})   # a redesign
            d = json.loads((Path(tmp) / "teapot.json").read_text(encoding="utf-8"))
            self.assertEqual(d["name"], "Grandma's teapot")
            self.assertEqual(len(d["parts"]), 1)


if __name__ == "__main__":
    unittest.main()
