"""Random videos on the server (pipeline/randomvid.py) and the batch path for them (pipeline/batch.py).
python -m unittest discover tests"""
import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import batch  # noqa: E402
import randomvid  # noqa: E402


def js_cards():
    """The card lists as web/app.js has them (MW_STEPS_BASE): key -> cards."""
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("const MW_STEPS_BASE = ["):]
    block = block[:block.index("\n];")]
    out = {}
    for seg in re.split(r'\{ key: "', block)[1:]:
        key = seg[:seg.index('"')]
        out[key] = re.findall(r'"([^"]+)"', seg[seg.index("cards:"):])
    return out


class Cards(unittest.TestCase):
    def test_the_server_cards_match_the_browser_cards(self):
        js = js_cards()
        self.assertEqual(set(js), set(randomvid.CARDS))
        for key, cards in randomvid.CARDS.items():
            self.assertEqual(js[key], cards, f"'{key}' cards differ from app.js")

    def test_an_item_is_an_idea_with_a_random_part(self):
        it = randomvid.item(random.Random(3), template_ids=["quick_facts", "top_five"])
        self.assertIsNone(it["id"])
        self.assertIn(it["template"], ("quick_facts", "top_five"))
        r = it["random"]
        self.assertIn(r["scene"], randomvid.CARDS["scene"])
        self.assertIn(r["style"], randomvid.STYLES)
        self.assertLessEqual(r["lines"][0], r["lines"][1])

    def test_light_and_length_follow_the_browser_flow(self):
        self.assertEqual(randomvid.light_for("a golden sunset"), "sunset")
        self.assertEqual(randomvid.light_for("day turning into night"), "day")     # first word that has a light
        self.assertEqual(randomvid.lines_for("short (about 20 s)"), (4, 5))
        self.assertEqual(randomvid.lines_for("long (about a minute)"), (10, 13))

    def test_the_writer_is_told_the_place_and_guest(self):
        text = randomvid.extra({"scene": "a haunted library", "guest": "a ghost", "time": "a stormy night"})
        self.assertIn("Place: a haunted library.", text)
        self.assertIn("a ghost shows up", text)
        self.assertNotIn("nobody", randomvid.extra({"scene": "a zoo", "guest": "nobody - just her", "time": "a sunny day"}))


class RandomInBatch(unittest.TestCase):
    def test_a_random_item_makes_its_set_first_and_then_its_video(self):
        calls = []

        def fake_call(base, method, path, body=None):
            calls.append((method, path))
            if path == "/api/ai/script":
                assert body["set"] == "new:a zoo", body["set"]
                return {"script": "Hello\nGoodbye", "set": "auto", "lines": ["Hello", "Goodbye"]}
            if path == "/api/sets/generate":
                return {"id": "job1"}
            if path == "/api/jobs/job1?from=0":
                return {"status": "done", "result": {"set": "zoo_set"}}
            if path == "/api/autodirect":
                assert body["set"] == "zoo_set" and body["start"] == "front", body
                return {"set": "zoo_set", "start": "front", "shots": [{"line": "Hello"}], "cast": {}}
            if path.startswith("/api/episodes/"):
                assert body["set"] == "zoo_set" and body["set_style"] == "palette", body
                return {}
            if path == "/api/render":
                return {"id": "render1"}
            raise AssertionError(path)

        item = randomvid.item(random.Random(1))
        item["random"].update(scene="a zoo", style="palette")
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.json"
            spec.write_text(json.dumps({"base": "http://x", "ideas": [item], "length": "medium", "render": True}),
                            encoding="utf-8")
            settings = {"ollama": {"url": "http://x", "model": "m"}, "active_character": "c"}
            with mock.patch.object(batch, "call", fake_call), \
                    mock.patch.object(batch.S, "load_settings", lambda: settings), \
                    mock.patch.object(batch.S, "load_character", lambda c: {}), \
                    mock.patch.object(batch.llm, "generate_titles", lambda *a, **k: ["A Title"]), \
                    mock.patch.object(batch.time, "sleep", lambda s: None):
                batch.main(str(spec))
        paths = [p for _, p in calls]
        self.assertLess(paths.index("/api/sets/generate"), paths.index("/api/autodirect"))
        self.assertIn("/api/render", paths)


if __name__ == "__main__":
    unittest.main()
