"""Deep theory kind (templates + autodirect.set_mood), lying down / kneeling (POSE_WORDS, low_poses) and fire
(autodirect.fire_of / [fire: x], run_episode.fire_def), 2026-11-27.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import catalog  # noqa: E402
import run_episode as R  # noqa: E402
import templates as T  # noqa: E402


class DeepTheory(unittest.TestCase):
    SCRIPT = ("What if this moment happened before?\nScientists call it deja vu.\n"
              "[@ new:a rainy rooftop] Some think the brain files a moment twice.\n"
              "What if this moment happened before?")

    def test_mood_and_loop(self):
        r = A.direct(self.SCRIPT, "park", title="Deja vu", **T.pacing("deep_theory"))
        shots = r["shots"]
        self.assertEqual(shots[0]["light"], "night")
        self.assertTrue(all(s.get("particles") == ["rain"] for s in shots if not s.get("cutaway")))
        self.assertTrue(all(s["voice"]["rate"].startswith("-") for s in shots))
        self.assertNotIn("react", " ".join(str(s) for s in shots))
        last = shots[-1]
        self.assertEqual(last.get("set"), "park")                 # back where it began
        self.assertEqual(last["camera"], shots[0]["camera"])
        self.assertEqual(last["move"], "static")

    def test_kept_with_beats_off_and_listed(self):
        self.assertTrue(T.pacing("deep_theory", beats_on=False)["loop_end"])
        import ideas
        self.assertIn("deep_theory", ideas.TEMPLATE_IDS)


class Poses(unittest.TestCase):
    def test_words_pick_poses(self):
        self.assertEqual(A.pose_of("I knelt at her grave"), "kneel")
        self.assertEqual(A.pose_of("I placed some roses by the stone"), "kneel_place")
        self.assertEqual(A.pose_of("then I lay down on the bed"), "lie_down")
        self.assertIsNone(A.pose_of("this is a grave mistake"))
        for a in ("lie_down", "kneel", "kneel_place"):
            self.assertIn(a, catalog.ANIMS)

    def test_on_furniture_and_cameras(self):
        r = A.direct("[medium] Hi.\n[sad, closeup] Then I went home and lay down on the bed.\n[lie_down sofa] Resting.",
                     "park")
        bed, sofa = r["shots"][1], r["shots"][2]
        self.assertEqual((bed["action"], bed["expression"], bed["on"], bed["camera"]), ("lie_down", "sad", "bed", "medium"))
        self.assertEqual(sofa["on"], "sofa")

    def test_pose_holds_for_the_whole_line(self):
        r = A.direct("[medium] Hi.\n[lie_down] And if you felt this chill on my neck... it is real.\n"
                     "[kneel_place] We would be seeing the world through two pairs of eyes.\nThe end.", "park",
                     beat_words=4)
        acts = [s["action"] for s in r["shots"]]
        self.assertEqual(acts[1:4], ["lie_down"] * 3)
        self.assertEqual(acts[4:6], ["kneel_place", "kneel"])
        self.assertNotIn(acts[-1], A.LOW_POSES)


class Fire(unittest.TestCase):
    def test_words(self):
        self.assertEqual(A.fire_of("The house is on fire!"), "house")
        self.assertEqual(A.fire_of("Look at the burning car"), "car")
        self.assertEqual(A.fire_of("Fire!"), "here")
        self.assertIsNone(A.fire_of("You're fired."))
        self.assertIsNone(A.fire_of("my heart is on fire"))
        self.assertIsNone(A.fire_of("the fire truck came"))

    def test_carries_until_off(self):
        r = A.direct("[medium] Hi.\n[fire: window] Uh oh.\nThe car is on fire too!\n[fire: off] Phew.", "park")
        got = [s.get("fire") for s in r["shots"]]
        self.assertEqual(got, [None, ["window"], ["window", "car"], None])
        self.assertIn("embers", r["shots"][1]["particles"])

    def test_production_fire_ghost_script(self):
        # zz_test_fire_ghost as first directed: windows -> a generic fire, "on fire!" celebrated, the lie-down broke
        r = A.direct("[medium] Hi.\n[wide, scared] Wait... the windows are on fire!\n"
                     "[fire: off] [medium] The fire just... stopped.\n"
                     "[medium] So I lay down on the bed and finally slept.", "park", beat_words=4)
        s = r["shots"]
        self.assertEqual(s[1]["fire"], ["window"])
        self.assertNotIn("celebrate", [x["action"] for x in s])
        self.assertNotIn("embers", s[3].get("particles") or [])
        lie = [x for x in s if "bed" in x["line"] or "slept" in x["line"] or "lay" in x["line"]]
        self.assertTrue(all(x["action"] == "lie_down" and x.get("on") == "bed" for x in lie))
        self.assertNotIn("confetti", str(lie))

    def test_fire_things(self):
        self.assertEqual(R.fire_height("campfire"), 0.8)
        self.assertIsNone(R.fire_height("fire_truck"))
        d = R.fire_def("campfire", 0.8)
        self.assertTrue(d["fire"])
        self.assertGreater(len(d["parts"]), 5)                  # logs and stones


if __name__ == "__main__":
    unittest.main()
