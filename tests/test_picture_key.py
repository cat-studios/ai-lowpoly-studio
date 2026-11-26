"""Reusing the last render's frames when only sound or text changed (run_episode.picture_key).
python -m unittest discover tests"""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import run_episode as R  # noqa: E402

EP = {"title": "T", "set": "cafe", "fps": 24, "render_res": [216, 384], "music": "a.mp3", "look_preset": "N64 Haze",
      "captions": {"group": 2}, "shots": [{"line": "Hello there", "camera": "medium", "duration": 2.0, "sfx": "pop"},
                                          {"line": "Bye", "camera": "closeup", "duration": 1.5}]}


class PictureKey(unittest.TestCase):
    def test_sound_and_text_changes_keep_the_picture(self):
        k = R.picture_key(EP)
        ep = copy.deepcopy(EP)
        ep.update(music="b.mp3", look_preset="Game Boy", captions={"group": 1}, brainrot=True, hook_style="question",
                  branding={"watermark": "@me"}, translations={"lt": {}})
        ep["shots"][0]["sfx"] = "boing"
        self.assertEqual(R.picture_key(ep), k)

    def test_picture_changes_need_a_new_render(self):
        k = R.picture_key(EP)
        for change in (lambda e: e["shots"][1].update(camera="wide"),          # a camera
                       lambda e: e["shots"][0].update(duration=2.4),           # timing (a new voice take)
                       lambda e: e["shots"][0].update(line="Hello you"),       # lip-sync / word timing
                       lambda e: e.update(set="park"),
                       lambda e: e.update(render_res=[270, 480])):
            ep = copy.deepcopy(EP)
            change(ep)
            self.assertNotEqual(R.picture_key(ep), k)

    def test_a_changed_model_file_needs_a_new_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "her.blend"
            model.write_bytes(b"v1")
            ep = {**copy.deepcopy(EP), "character": {"model": str(model)}}
            k = R.picture_key(ep)
            model.write_bytes(b"version 2")
            os.utime(model, (time.time() + 5, time.time() + 5))
            self.assertNotEqual(R.picture_key(ep), k)

    def test_frames_must_all_be_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            frames = build / "frames"
            frames.mkdir()
            (build / "timing.json").write_text(json.dumps({"total_frames": 3, "fps": 24, "shots": []}))
            for i in (1, 2):
                (frames / f"f_{i:04d}.png").write_bytes(b"x")
            self.assertFalse(R.frames_complete(build, frames))
            (frames / "f_0003.png").write_bytes(b"x")
            self.assertTrue(R.frames_complete(build, frames))


if __name__ == "__main__":
    unittest.main()
