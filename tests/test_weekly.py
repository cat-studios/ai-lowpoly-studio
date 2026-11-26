"""The weekly plan (pipeline/weekly.py) and the batch's Postiz drafts.  python -m unittest discover tests"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import batch  # noqa: E402
import weekly  # noqa: E402

MONDAY_4AM = datetime(2026, 11, 30, 4, 0)       # a Monday


class Plan(unittest.TestCase):
    def test_due_once_a_week_after_the_hour(self):
        plan = {"on": True, "day": "mon", "hour": 3}
        self.assertTrue(weekly.due(plan, {}, MONDAY_4AM))
        self.assertFalse(weekly.due(plan, {"last_week": weekly.week_of(MONDAY_4AM)}, MONDAY_4AM))
        self.assertFalse(weekly.due(plan, {}, MONDAY_4AM.replace(hour=2)))
        self.assertFalse(weekly.due({**plan, "on": False}, {}, MONDAY_4AM))
        self.assertFalse(weekly.due(plan, {}, datetime(2026, 12, 1, 4, 0)))          # Tuesday

    def test_pick_fresh_starred_first_mixed_kinds(self):
        db = {"ideas": [
            {"id": "a", "template": "quick_facts", "added": 3},
            {"id": "b", "template": "quick_facts", "added": 2, "starred": True},
            {"id": "c", "template": "what_if", "added": 1},
            {"id": "d", "template": "what_if", "added": 5, "used": ["ep1"]},
            {"id": "e", "template": "top_five", "added": 4, "hidden": True}]}
        self.assertEqual([i["id"] for i in weekly.pick(db, 3)], ["b", "c", "a"])


class Drafts(unittest.TestCase):
    def test_a_draft_for_each_finished_render(self):
        posted = []

        def fake_call(base, method, path, body=None, timeout=0):
            if path.startswith("/api/jobs/"):
                return {"status": "failed" if "j2" in path else "done"}
            posted.append(body["video"])
            return {"id": "p"}

        with mock.patch.object(batch, "call", fake_call), mock.patch.object(batch.time, "sleep", lambda s: None):
            batch.drafts("http://x", {"Why_Cats_Purr_1126": "j1", "other_1126": "j2"})
        self.assertEqual(posted, ["why_cats_purr_1126"])                   # the failed render gets no draft


if __name__ == "__main__":
    unittest.main()
