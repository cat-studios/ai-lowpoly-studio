"""Batch from Ideas (pipeline/batch.py) with the studio's API faked.  python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import batch  # noqa: E402


class Batch(unittest.TestCase):
    def test_one_video_per_idea_and_a_failure_doesnt_stop_the_rest(self):
        calls = []

        def fake_call(base, method, path, body=None, timeout=0):
            calls.append((method, path, body))
            if path == "/api/ai/script":
                if body["title"].startswith("Why do volcanoes"):
                    raise OSError("the writer fell over")
                return {"script": "Hook line here.", "set": "cafe"}
            if path == "/api/autodirect":
                return {"set": "cafe", "start": "front", "shots": [{"line": "Hook line here."}],
                        "cast": {"mom": {"looks": "mom"}}}
            return {"id": "job1"}

        ideas = [{"id": "a", "topic": "volcanoes", "template": "quick_facts", "titles": ["Why do volcanoes erupt?"]},
                 {"id": "b", "topic": "moon", "template": "top_five", "titles": ["What are the 5 oddest moons?"]}]
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.json"
            spec.write_text(json.dumps({"base": "http://x", "ideas": ideas, "regulars": ["mom"]}), encoding="utf-8")
            with mock.patch.object(batch, "call", fake_call), mock.patch.object(batch, "report", lambda *a: None):
                batch.main(spec)
        puts = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 1)                               # the moon video, though volcanoes failed
        ep = puts[0][2]
        self.assertEqual((ep["idea"], ep["template"], ep["title"]), ("b", "top_five", "What are the 5 oddest moons?"))
        self.assertEqual(ep["cast"]["mom"]["actor"], "mom")          # a regular is played by their own actor
        self.assertEqual(sum(1 for c in calls if c[1] == "/api/render"), 1)


if __name__ == "__main__":
    unittest.main()
