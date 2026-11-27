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


if __name__ == "__main__":
    unittest.main()
