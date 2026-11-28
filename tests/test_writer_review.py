"""2026-11-28 review of the overnight videos: the writer's prompt (only the tools a video needs), the cleanup of its
slips, titles that keep their idea, and overlay kinds switched on/off (the "BOSS: ME" corner tag is off).
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import batch  # noqa: E402
import llm  # noqa: E402
import run_episode as R  # noqa: E402
import templates  # noqa: E402

CHAR = {"id": "catgirl", "name": "Lavender"}


class Prompt(unittest.TestCase):
    def test_only_what_the_video_needs(self):
        p = llm.writer_system("What happens when your fur gets wet?", "funny", "", "stay", False, [], "question")
        for word in ("float_up", "ghost after the verb", "meter:", "[@ ", "cameras:", "sunset"):
            self.assertNotIn(word, p)
        self.assertIn("Every single line is about the title", p)
        p = llm.writer_system("What if your past self haunted you at night?", "eerie", "", "auto", False, [], "number")
        self.assertIn("ghost", p)
        self.assertIn("night", p)

    def test_no_corner_tag(self):
        self.assertNotIn("[tag:", templates.get("gadget_story")["script"])
        p = llm.writer_system("What if you built a gadget?", "funny", templates.get("gadget_story")["script"])
        self.assertIn("[label:", p)
        self.assertNotIn("[tag:", p)


class Tidy(unittest.TestCase):
    def test_production_slips(self):
        lines = ["[closet, excited] And you can sleep in the dark nya!",
                 "[hight, float_up] Oh no, I'm floating away!",
                 "[macro, sweat_drip] Why does he look more stressed than me?",
                 "[fanum tax: Lavender 20] OHIO! The sun just ate it all!",
                 "[closeup, surprised] +captain crash_in hot! The driver yelled at me!",
                 "[+pigeon float_up, smug] He knows my favorite snack!\" the smug pigeon claims.",
                 "[mid, excited] Lavender zooms over to the nurse's station!",
                 "[day, +lamp_crash_in]",
                 "Huss,\" my lava hair is starting to melt!",
                 "+scientist bow: You look great now!",
                 "[cutaway: the thing, wide] A SPARKY BEE!",
                 "[do:point] Clouds are mostly water.",
                 "[closerup, smug twist] Oh no... wait for it... do:facepalm!"]
        out, bad = llm.tidy_writer_lines(lines, CHAR)
        text = "\n".join(out)
        self.assertTrue(out[0].startswith("[closeup, happy]"))
        self.assertTrue(out[1].startswith("[high, float_up]"))
        self.assertNotIn("sweat_drip", text)
        self.assertNotIn("fanum", text)
        self.assertNotIn("crash_in hot", text)
        self.assertIn("+captain crash_in", text)
        self.assertNotIn("claims", text)
        self.assertNotIn("zooms over", text)
        self.assertIn("[+lamp crash_in] Huss, my lava hair", text)        # the empty line's cast moves on
        self.assertIn("[+scientist bow] Scientist: You look great now!", text)
        self.assertNotIn("cutaway: the thing", text)
        self.assertIn("[point] Clouds", text)
        self.assertNotIn("do:facepalm", text)
        self.assertGreater(bad, 8)

    def test_plan_words_and_bare_place(self):
        out, _ = llm.tidy_writer_lines(["[+punchline enter] Punchline: Plants are sun-powered sugar factories!",
                                        "@ quiet park bench This happens to those who think too much."], CHAR)
        self.assertEqual(out[0], "Plants are sun-powered sugar factories!")
        self.assertEqual(out[1], "[@ quiet park bench] This happens to those who think too much.")

    def test_draft_scoring(self):
        beats = ["clouds are water droplets", "the droplets weigh a lot", "air holds them up"]
        good = ["A cloud is made of water droplets!", "Those droplets weigh a lot together.", "Warm air holds them up."]
        bad = ["Hello friends!", "Hello friends!", "My tail is fluffy."]
        self.assertGreater(llm.score_script(good, 0, "How heavy is a cloud?", beats, 3),
                           llm.score_script(bad, 0, "How heavy is a cloud?", beats, 3))

    def test_review_fixes_only_named_lines(self):
        from unittest import mock
        lines = ["[surprised] Clouds weigh tons!", "My tail is fluffy.", "Air holds them up."]
        with mock.patch.object(llm, "chat_json", return_value={"fixes": [{"n": 2, "why": "off topic",
                                                                         "line": "The drops add up to tons."}]}):
            out, n = llm.review_script("u", "m", "How heavy is a cloud?", lines)
        self.assertEqual(n, 1)
        self.assertEqual(out, ["[surprised] Clouds weigh tons!", "The drops add up to tons.", "Air holds them up."])

    def test_clean_script_untouched(self):
        lines = ["Wait... clouds weigh more than elephants?", "[surprised] A cloud holds tiny drops of water."]
        self.assertEqual(llm.tidy_writer_lines(lines, CHAR), (lines, 0))


class Titles(unittest.TestCase):
    def test_on_topic(self):
        th = "Exoplanet Atmosphere - a giant hydrogen bubble floating in space"
        self.assertFalse(batch.on_topic("What happens when your fur gets wet?", th))
        self.assertTrue(batch.on_topic("What if you lived inside a hydrogen bubble?", th))
        self.assertTrue(batch.on_topic("What if you parked by the Sun?", "A spaceship too close to the Sun"))
        self.assertEqual(batch.idea_title({"topic": "Exoplanet Atmosphere", "angle": "Why is it pink?"}, {}),
                         "Why is it pink?")


class Overlays(unittest.TestCase):
    def test_kinds_switched_off(self):
        shots = [{"hud": [{"kind": "tag", "text": "BOSS: ME"}, {"kind": "meter", "name": "x", "value": 5}]}, {}]
        got = R.hud_shots(shots, {})
        self.assertEqual([h["kind"] for h in got[0]["hud"]], ["meter"])       # the tag is off by default
        got = R.hud_shots(shots, {"hud_kinds": {"tag": True, "meter": False}})
        self.assertEqual([h["kind"] for h in got[0]["hud"]], ["tag"])


if __name__ == "__main__":
    unittest.main()
