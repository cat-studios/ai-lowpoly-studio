"""The 🔎 Logs page's trace (pipeline/studiotrace.py, comfy.trace_workflow, llm._chat tracing), 2026-11-27.
python -m unittest discover tests"""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import comfy  # noqa: E402
import llm  # noqa: E402
import studiotrace as T  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()


class Trace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(T, "DIR", Path(self.tmp.name)), mock.patch.object(T, "IMG", Path(self.tmp.name) / "img"),
                  mock.patch.dict(os.environ, {"STUDIO_TRACE_TESTS": "1", "STUDIO_JOB_ID": "abc123def0"})]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def test_ai_call_is_traced_with_its_picture(self):
        payload = {"model": "m", "messages": [{"role": "system", "content": "judge it"},
                                              {"role": "user", "content": "a duck?", "images": [PNG]}]}
        with mock.patch.object(llm, "_chat_routed", return_value={"message": {"content": '{"score": 7}'}}):
            llm._chat("http://127.0.0.1:11434", payload, has_images=True)
        ev, nxt = T.read(T.path_for())
        self.assertEqual(nxt, 1)
        e = ev[0]
        self.assertEqual(e["kind"], "ai")
        self.assertEqual(e["data"]["answer"], '{"score": 7}')
        self.assertEqual(e["data"]["job_kind"], "vision")
        img = e["data"]["messages"][1]["images"][0]
        self.assertTrue((T.IMG / img).exists())
        self.assertIn("test_ai_call", e["data"]["caller"])

    def test_failures_are_traced_too_and_reads_continue(self):
        with mock.patch.object(llm, "_chat_routed", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                llm._chat("http://127.0.0.1:11434", {"model": "m", "messages": []})
        T.event("step", "Recording the voice")
        ev, nxt = T.read(T.path_for(), after=1)
        self.assertEqual([e["kind"] for e in ev], ["step"])
        self.assertIn("down", T.read(T.path_for())[0][0]["data"]["error"])

    def test_comfy_workflow_summary(self):
        w = comfy.trace_workflow({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red duck, no text"}},
                                  "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo"}},
                                  "3": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}}})
        self.assertIn("a red duck", w["prompts"])
        self.assertEqual(w["models"], ["z_image_turbo"])
        self.assertEqual(w["settings"]["EmptyLatentImage.width"], 512)


if __name__ == "__main__":
    unittest.main()
