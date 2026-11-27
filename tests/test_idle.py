"""Idle auto-make (web/server.py idle_ready): no daily limit since 2026-11-27 (a cap of 3 stopped it at 3 overnight),
a pause on low disk.  python -m unittest discover tests"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "pipeline"))
import server  # noqa: E402

ON = {"on": True, "minutes": 10}
NOW = 1_000_000.0


def job(status, ended=None):
    return types.SimpleNamespace(status=status, ended=ended)


class IdleReady(unittest.TestCase):
    def test_quiet_and_free_makes_a_batch_any_number_of_times(self):
        done = [job("done", NOW - 3600) for _ in range(40)]          # 40 earlier batches today: no limit
        self.assertEqual(server.idle_ready(ON, done, NOW, NOW - 3600, 200.0), "")

    def test_waits_while_something_runs_or_just_finished(self):
        self.assertEqual(server.idle_ready(ON, [job("running")], NOW, NOW - 3600, 200.0), "busy")
        self.assertEqual(server.idle_ready(ON, [job("done", NOW - 120)], NOW, NOW - 3600, 200.0), "not quiet")
        self.assertEqual(server.idle_ready(ON, [], NOW, NOW - 120, 200.0), "not quiet")   # someone used it

    def test_off_and_low_disk(self):
        self.assertEqual(server.idle_ready({"on": False}, [], NOW, 0, 200.0), "off")
        self.assertEqual(server.idle_ready(ON, [], NOW, 0, server.IDLE_MIN_FREE_GB - 1), "low disk")

    def test_state_says_how_long_until_it_starts(self):
        st = server.idle_state(ON, [], NOW, NOW - 240, 200.0)        # used 4 min ago, needs 10
        self.assertEqual((st["why"], st["wait"], st["on"]), ("not quiet", 360, True))
        self.assertEqual(server.idle_state({"on": False}, [], NOW, 0, 200.0)["on"], False)


class CountsAsUse(unittest.TestCase):
    BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/150"}

    def test_a_browser_using_the_studio_counts(self):
        self.assertTrue(server.counts_as_use("/api/episodes", self.BROWSER))

    def test_polling_own_jobs_and_other_programs_dont(self):
        self.assertFalse(server.counts_as_use("/api/jobs", self.BROWSER))
        self.assertFalse(server.counts_as_use("/api/idle", self.BROWSER))
        self.assertFalse(server.counts_as_use("/api/episodes", {**self.BROWSER, "X-Studio-Job": "1"}))
        # production 2026-11-27: a script on the PC asked /api/health every ~15 min
        self.assertFalse(server.counts_as_use("/api/health", {"User-Agent": "python-requests/2.34.2"}))
        self.assertFalse(server.counts_as_use("/api/episodes", {"User-Agent": "python-requests/2.34.2"}))


if __name__ == "__main__":
    unittest.main()
