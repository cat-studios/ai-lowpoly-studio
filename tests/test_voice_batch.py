"""The local voice batch with the same line twice (Deep theory's last line repeats the first): one take, no crash
(production zz_test_deep_theory, 2026-11-27: FileNotFoundError moving the second copy).  python -m unittest"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import run_episode as R  # noqa: E402


class FakeProc:
    def __init__(self, cmd, **kw):
        jobs = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
        self.n = len(jobs)
        for j in jobs:
            Path(j["out"]).write_bytes(b"RIFF")
        self.stdout = iter([])

    def wait(self):
        return 0


class VoiceBatch(unittest.TestCase):
    def test_same_line_twice(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(R, "VOICE_PY", Path(__file__)), \
                mock.patch.object(R.subprocess, "Popen", FakeProc):
            v = {"engine": "local", "exaggeration": 0.3}
            line = "I feel like I am seeing my future right now."
            R.prefetch_local([(line, v), ("Another line.", v), (line, v)], Path(d))
            raws = sorted(p.name for p in Path(d).glob("*.raw"))
            self.assertEqual(len(raws), 2)
            jobs = json.loads((Path(d) / "local_jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
