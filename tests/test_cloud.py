"""Local / cloud AI (Settings -> AI tools): llm._chat sends each job to OpenRouter or the local Ollama, with the local
one taking over when the cloud fails, and nothing when both are off.  python -m unittest discover tests"""
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "web"))
import cloud_web  # noqa: E402
import llm  # noqa: E402

PAYLOAD = {"model": "local-model", "stream": False, "think": False, "options": {"temperature": 0.4},
           "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]}


class Routing(unittest.TestCase):
    def setUp(self):
        self._saved = (llm.ai_cfg, llm.openrouter_chat, llm._chat_once, llm._remote_for, llm._DOWN_FILE)
        self.tmp = tempfile.TemporaryDirectory()
        llm._DOWN_FILE = Path(self.tmp.name) / "down.json"        # never the real build/remote_down.json
        llm._REMOTE_DOWN.clear()
        llm._remote_for = lambda url, has_images: None
        self.calls = []
        llm._chat_once = lambda url, payload, timeout=300: self.calls.append(("local", payload["model"])) or {"message": {"content": "local"}}
        self.cloud_fails = None

        def cloud(key, model, payload):
            self.calls.append(("cloud", model))
            if self.cloud_fails:
                raise self.cloud_fails
            return {"message": {"content": "cloud"}}
        llm.openrouter_chat = cloud

    def tearDown(self):
        llm.ai_cfg, llm.openrouter_chat, llm._chat_once, llm._remote_for, llm._DOWN_FILE = self._saved
        llm._REMOTE_DOWN.clear()
        self.tmp.cleanup()

    def use(self, local=True, cloud=True, **o):
        cfg = {"key": "sk-test", "text": True, "model": "google/gemini-x", "vision": True,
               "vision_model": "google/gemini-v", "design": True, "design_model": "", **o}
        llm.ai_cfg = lambda: ({"local": local, "cloud": cloud}, cfg)

    def test_cloud_does_its_jobs(self):
        self.use()
        self.assertEqual(llm._chat("http://local", PAYLOAD)["message"]["content"], "cloud")
        llm._chat("http://local", PAYLOAD, has_images=True)
        with llm.job("design"):                  # no design model of its own = the writing model
            llm._chat("http://local", PAYLOAD)
        self.assertEqual(self.calls, [("cloud", "google/gemini-x"), ("cloud", "google/gemini-v"), ("cloud", "google/gemini-x")])

    def test_a_job_left_unticked_stays_local(self):
        self.use(vision=False)
        llm._chat("http://local", PAYLOAD, has_images=True)
        self.assertEqual(self.calls, [("local", "local-model")])

    def test_cloud_off_or_no_key_means_local(self):
        self.use(cloud=False)
        llm._chat("http://local", PAYLOAD)
        self.use(key="")
        llm._chat("http://local", PAYLOAD)
        self.assertEqual(self.calls, [("local", "local-model")] * 2)

    def test_a_failing_cloud_falls_back_and_is_left_alone_for_a_while(self):
        self.use()
        self.cloud_fails = urllib.error.HTTPError("u", 402, "Payment Required", {}, None)
        self.assertEqual(llm._chat("http://local", PAYLOAD)["message"]["content"], "local")
        llm._chat("http://local", PAYLOAD)                     # skipped now: straight to local
        self.assertEqual(self.calls, [("cloud", "google/gemini-x"), ("local", "local-model"), ("local", "local-model")])
        self.assertEqual(llm._or_why(self.cloud_fails), "out of credit (top up on openrouter.ai)")

    def test_local_off(self):
        self.use(local=False, text=False)
        with self.assertRaises(llm.LocalOff):                  # cloud doesn't write, local is off: no AI
            llm._chat("http://local", PAYLOAD)
        self.use(local=False)
        self.cloud_fails = TimeoutError("timed out")
        with self.assertRaises(OSError):                       # LocalOff is an OSError: callers treat it as "offline"
            llm._chat("http://local", PAYLOAD)
        self.assertNotIn(("local", "local-model"), self.calls)


class DailyLimit(Routing):
    """Routing's set-up, with today's spending in a temporary file."""
    def setUp(self):
        super().setUp()
        self._spend = llm.SPEND_FILE
        llm.SPEND_FILE = Path(self.tmp.name) / "spend.json"
        llm._CAPPED_SAID.clear()

    def tearDown(self):
        llm.SPEND_FILE = self._spend
        super().tearDown()

    def test_spending_adds_up_per_day(self):
        llm.add_spend(0.25)
        d = llm.add_spend(0.5, estimated=True)
        self.assertEqual((d["spent"], d["calls"], d["estimated"]), (0.75, 2, 1))
        llm.SPEND_FILE.write_text('{"day": "2000-01-01", "spent": 9, "calls": 3}', encoding="utf-8")
        self.assertEqual(llm.spend_today()["spent"], 0.0)          # yesterday's doesn't count

    def test_limit_reached_means_local(self):
        self.use(daily_limit=1.0)
        llm.add_spend(0.99)
        llm._chat("http://local", PAYLOAD)
        llm.add_spend(0.02)
        llm._chat("http://local", PAYLOAD)
        self.assertEqual(self.calls, [("cloud", "google/gemini-x"), ("local", "local-model")])
        self.use(daily_limit=0)                                     # 0 = no limit
        llm._chat("http://local", PAYLOAD)
        self.assertEqual(self.calls[-1], ("cloud", "google/gemini-x"))

    def test_limit_reached_and_local_off(self):
        self.use(local=False, daily_limit=0.5)
        llm.add_spend(0.6)
        with self.assertRaisesRegex(llm.LocalOff, "limit"):
            llm._chat("http://local", PAYLOAD)

    def test_cost_from_answer_or_price(self):
        self.assertEqual(llm.call_cost({"usage": {"cost": 0.0123}}, "m"), (0.0123, False))
        llm._PRICES.clear()
        llm._PRICES["m"] = (0.000002, 0.00001)
        cost, est = llm.call_cost({"usage": {"prompt_tokens": 1000, "completion_tokens": 500}}, "m")
        self.assertEqual((round(cost, 6), est), (0.007, True))
        llm._PRICES.clear()


class Payload(unittest.TestCase):
    def test_pictures_and_json(self):
        p = dict(PAYLOAD, format="json", messages=[{"role": "user", "content": "look", "images": ["iVBORpng", "/9j/jpg"]}])
        out = llm.openrouter_payload(p, "m")
        self.assertEqual((out["model"], out["temperature"], out["response_format"]), ("m", 0.4, {"type": "json_object"}))
        parts = out["messages"][0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "look"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR"))
        self.assertTrue(parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/"))
        self.assertEqual(llm.openrouter_payload(PAYLOAD, "m")["messages"][1]["content"], "hi")


class Models(unittest.TestCase):
    def test_trim(self):
        raw = [{"id": "g/gem", "name": "Gem", "pricing": {"prompt": "0.000002", "completion": "0.00001"},
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
               {"id": "g/gem:batch", "architecture": {}},
               {"id": "x/painter", "architecture": {"output_modalities": ["image"]}},
               {"id": "n/tiny:free", "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {"input_modalities": ["text"]}}]
        out = cloud_web.trim(raw)
        self.assertEqual([m["id"] for m in out], ["g/gem", "n/tiny:free"])
        self.assertEqual((out[0]["in"], out[0]["out"], out[0]["vision"], out[0]["free"]), (2.0, 10.0, True, False))
        self.assertTrue(out[1]["free"])


if __name__ == "__main__":
    unittest.main()
