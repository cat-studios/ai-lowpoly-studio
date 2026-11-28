"""The imported model list can't be lost again (2026-11-28: a delete from the page and a "make real 3D" job saved at
once through one temp file -> broken JSON -> read as EMPTY -> 3,462 models gone from the list).
python -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import imported as IM  # noqa: E402


def pack(pid, *mids):
    return {"id": pid, "name": pid, "models": [{"id": m, "status": "ok"} for m in mids]}


class IndexSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lib = Path(self.tmp.name)
        self.p = [mock.patch.object(IM, k, v) for k, v in (
            ("LIB", lib), ("INDEX", lib / "index.json"), ("BACKUP", lib / "index.backup.json"),
            ("SNAPS", lib / "index.snapshots"), ("LOCK", lib / "index.lock"))]
        for x in self.p:
            x.start()
        IM.INDEX.write_text(json.dumps({"packs": [pack("a", "a1", "a2"), pack("b", "b1")]}), encoding="utf-8")

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def ids(self):
        return sorted(m["id"] for p in json.loads(IM.INDEX.read_text())["packs"] for m in p["models"])

    def test_two_writers_both_changes_kept(self):
        job = IM.load_index()             # the job loads ...
        page = IM.load_index()            # ... and the page loads the same list
        page["packs"][0]["models"] = [m for m in page["packs"][0]["models"] if m["id"] != "a1"]   # delete a1
        IM.save_index(page)
        job["packs"].append(pack("made_3d", "m1"))                                              # add a model
        IM.save_index(job)
        self.assertEqual(self.ids(), ["a2", "b1", "m1"])     # the delete stays deleted, nothing else is lost

    def test_broken_list_is_never_empty(self):
        IM.save_index(IM.load_index())                       # makes the backup
        IM.INDEX.write_text('{"packs": [] } {"half": ', encoding="utf-8")
        self.assertEqual(len(IM.load_index()["packs"]), 2)   # the backup, not an empty list
        IM.BACKUP.unlink()
        with self.assertRaises(IM.IndexBroken):
            IM.load_index()

    def test_snapshot_kept(self):
        IM.save_index(IM.load_index())
        self.assertTrue(any(IM.SNAPS.glob("index-*.json")))


if __name__ == "__main__":
    unittest.main()
