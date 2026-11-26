"""Stats (pipeline/stats.py) and cover B (pipeline/cover.py).  python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import cover  # noqa: E402
import stats  # noqa: E402


class Stats(unittest.TestCase):
    def test_a_post_is_matched_to_its_video_by_the_title(self):
        titles = {"goldfish": "Do goldfish really forget everything?", "moon": "What if the moon vanished?"}
        post = {"caption": "🐟 Do goldfish REALLY forget everything in 3 seconds? #fish #reels"}
        self.assertEqual(stats.match(post, titles), "goldfish")
        self.assertIsNone(stats.match({"caption": "a cat video"}, titles))

    def test_typed_views_and_averages(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "stats.json"
            facts = {"a": {"title": "A", "template": "top_five", "seconds": 30, "set": "park", "hook": "", "shots": 9,
                           "language": "en"},
                     "b": {"title": "B", "template": "top_five", "seconds": 55, "set": "cafe", "hook": "", "shots": 9,
                           "language": "en"}}
            with mock.patch.object(stats, "STORE", store), mock.patch.object(stats, "facts", lambda k: facts[k]):
                stats.update("a", {"views": "1000", "posted_cover": "b"})
                stats.update("b", {"views": 200})
                s = stats.summary()
        self.assertEqual([r["key"] for r in s["rows"]], ["a", "b"])
        self.assertEqual(s["by"]["kind"][0], {"value": "top_five", "videos": 2, "avg": 600})
        self.assertEqual(s["by"]["cover"][0]["value"], "B")
        self.assertEqual({e["value"] for e in s["by"]["length"]}, {"20-35 s", "50 s +"})


class YouTube(unittest.TestCase):
    def fake_api(self, path, api_key, **p):
        if path == "channels":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                               "statistics": {"subscriberCount": "1234"}}]}
        if path == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]}
        return {"items": [
            {"id": "v1", "snippet": {"title": "Do goldfish really forget everything?"},
             "statistics": {"viewCount": "900", "likeCount": "40", "commentCount": "5"}},
            {"id": "v2", "snippet": {"title": "A cat video nobody made"}, "statistics": {"viewCount": "7"}}]}

    def run_fetch(self, cfg, analytics):
        settings = {"youtube": cfg, "ideas": {"youtube_key": "KEY"}}
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "stats.json"
            with mock.patch.object(stats, "STORE", store), \
                    mock.patch.object(stats.S, "load_settings", lambda: settings), \
                    mock.patch.object(stats, "_yt_get", self.fake_api), \
                    mock.patch.object(stats, "_yt_analytics", lambda c, s, e: analytics), \
                    mock.patch.object(stats, "_video_titles", lambda: {"goldfish": "Do goldfish really forget?"}):
                n = stats.fetch_youtube(log=lambda *a: None)
                db = stats.load()
        return n, db

    def test_uploads_match_by_title_and_keep_subscribers(self):
        n, db = self.run_fetch({"channel_id": "UC1"}, {})
        self.assertEqual(n, 1)
        self.assertEqual(db["videos"]["goldfish"]["yt"]["views"], 900)
        self.assertNotIn("cat", db["videos"])
        self.assertEqual(db["youtube"]["subscribers"], 1234)
        self.assertEqual(db["youtube"]["history"][-1][1], 1234)

    def test_retention_numbers_are_kept_when_a_later_fetch_has_none(self):
        stats_cfg = {"channel_id": "UC1", "client_id": "c", "client_secret": "s", "refresh_token": "r"}
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "stats.json"
            settings = {"youtube": stats_cfg, "ideas": {"youtube_key": "KEY"}}
            with mock.patch.object(stats, "STORE", store), \
                    mock.patch.object(stats.S, "load_settings", lambda: settings), \
                    mock.patch.object(stats, "_yt_get", self.fake_api), \
                    mock.patch.object(stats, "_video_titles", lambda: {"goldfish": "Do goldfish really forget?"}):
                with mock.patch.object(stats, "_yt_analytics",
                                       lambda c, s, e: {"v1": {"avg_view_secs": 12, "avg_view_pct": 41.5,
                                                               "subs_gained": 3}}):
                    stats.fetch_youtube(log=lambda *a: None)
                with mock.patch.object(stats, "_yt_analytics", lambda c, s, e: {}):   # a later fetch, no retention
                    stats.fetch_youtube(log=lambda *a: None)
                db = stats.load()
        self.assertEqual(db["videos"]["goldfish"]["yt"]["avg_view_pct"], 41.5)
        self.assertEqual(db["videos"]["goldfish"]["yt"]["views"], 900)

    def test_summary_shows_youtube_by_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "stats.json"
            store.write_text(json.dumps({"videos": {"g": {"yt": {"id": "v1", "views": 900, "avg_view_pct": 40.0,
                                                                 "avg_view_secs": 12, "subs_gained": 3}}},
                                         "youtube": {"channel": "UC1", "subscribers": 10, "history": [[1, 10]]}}))
            facts = {"title": "G", "template": "top_five", "seconds": 30, "set": "park", "hook": "", "shots": 9,
                     "language": "en"}
            with mock.patch.object(stats, "STORE", store), mock.patch.object(stats, "facts", lambda k: facts):
                s = stats.summary()
        self.assertEqual(s["rows"][0]["key"], "g")
        self.assertEqual(s["yt_by"][0], {"value": "top_five", "videos": 1, "avg_views": 900, "avg_view_pct": 40.0,
                                         "avg_view_secs": 12, "subs": 3})
        self.assertEqual(s["youtube"]["subscribers"], 10)


class CoverB(unittest.TestCase):
    def test_runner_up_is_another_frame(self):
        cands = [(0, "f0", 3), (4, "f4", 5), (9, "f9", 3)]
        self.assertEqual(cover.runner_up(cands, 1), 2)                # equal scores: the one further away
        self.assertIsNone(cover.runner_up(cands[:1], 0))


if __name__ == "__main__":
    unittest.main()
