"""The AI writer's slips seen in four production videos (2026-11-27): spoken brackets, spoken stage directions,
doubled labels, camera words as cutaways, places that were directions, repeated entrances, giant things in her hand,
non-actions made into poses.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import animgen  # noqa: E402
import animlib  # noqa: E402
import autodirect as A  # noqa: E402


class TidyLine(unittest.TestCase):
    def test_mismatched_brackets(self):
        self.assertEqual(A.tidy_line("[mid, sneeze, facepalm) Ahhh! Just another egg day"),
                         "[mid, sneeze, facepalm] Ahhh! Just another egg day")
        self.assertEqual(A.tidy_line("(facepalm] Ahhh!"), "[facepalm] Ahhh!")
        self.assertEqual(A.tidy_line("(sighs) okay then"), "(sighs) okay then")      # plain parentheses stay

    def test_spoken_entrance_and_doubled_label(self):
        self.assertEqual(A.tidy_line("[sunset, dramatic] Enter +wizard, smug He just dropped a terabyte on me!"),
                         "[sunset, dramatic, +wizard enter] He just dropped a terabyte on me!")
        self.assertEqual(A.tidy_line("[bounce] Wizard: +Wizard: This feels heavier"), "[bounce] Wizard: This feels heavier")

    def test_directed_lines_dont_say_them(self):
        r = A.direct("[medium] Hi!\n[sunset] Enter +wizard, smug He just dropped a terabyte on me!\n"
                     "Wizard: +Wizard: This feels heavier than your soul!\n[mid, sneeze, facepalm) Ahhh! Egg day!",
                     "cafe", beat_words=4, cast={"wizard": {"type": "person", "looks": "tall"}})
        said = " ".join(s["line"] for s in r["shots"])
        for bad in ("Enter", "smug", "Wizard:", "[", ")", "sneeze,"):
            self.assertNotIn(bad, said)
        enters = [e for s in r["shots"] for e in s.get("events") or [] if e["who"] == "wizard"]
        self.assertEqual([e["do"] for e in enters], ["enter"])


class Cutaways(unittest.TestCase):
    def test_camera_words_are_cameras(self):
        self.assertEqual(A.parse_directions("[cutaway: macro, happy] Even my claws", [])[0],
                         {"expression": "happy", "camera": "macro"})
        self.assertEqual(A.parse_directions("[cutaway: zoom_in] I look", [])[0], {"move": "push_in"})
        self.assertEqual(A.parse_directions("[cutaway: a mosquito bite] The answer", [])[0]["cutaway"], "a mosquito bite")


class Places(unittest.TestCase):
    def test_place_words(self):
        self.assertEqual(A.place_words("Enter Wizard - A room with a smug wizard", {"wizard": {}}), set())
        self.assertEqual(A.place_words("The Void - where she is drifting aimlessly"), {"void"})
        self.assertIn("beach", A.place_words("the beach"))

    def test_scene_plan_skips_directions_and_described_words(self):
        shots = [{"line": "Hi there"}, {"line": "Enter wizard,"}, {"line": "look at me drifting"}]
        plan = {"scenes": [{"line": 1, "place": "Enter Wizard - a room with a smug wizard"},
                           {"line": 2, "place": "The Void - nothingness where she is drifting"}]}
        r = A.add_scene_plan({"shots": shots, "cast": {"wizard": {}}}, plan, "cafe", "new")
        self.assertFalse(any(s.get("set") for s in r["shots"]))


class Events(unittest.TestCase):
    def test_one_entrance_and_no_held_people(self):
        shots = [{"events": [{"who": "wizard", "do": "enter"}]}, {"events": [{"who": "wizard", "do": "hold"}]},
                 {"events": [{"who": "wizard", "do": "enter", "from": "top"}]}, {"events": [{"who": "wizard", "do": "exit"}]},
                 {"events": [{"who": "wizard", "do": "enter"}]}, {"events": [{"who": "cup", "do": "hold"}]}]
        A.tidy_events(shots, {"wizard": {"type": "person"}, "cup": {"type": "thing"}})
        self.assertEqual([[e["do"] for e in s.get("events", [])] for s in shots],
                         [["enter"], [], [], ["exit"], ["enter"], ["hold"]])


class Holding(unittest.TestCase):
    def test_giant_things_arent_held(self):
        shots = [{"line": "I could bounce on this giant shell!"}, {"line": "Look at this cup!"}]
        cast = {}
        A.held_things(shots, cast)
        self.assertEqual(list(cast), ["cup"])


class Light(unittest.TestCase):
    def test_all_day_isnt_a_day_arc(self):
        self.assertFalse(A.DAY_ARC.search("I walked all day without touching ground"))
        self.assertTrue(A.DAY_ARC.search("A day in the life of a cat"))


class NotActions(unittest.TestCase):
    def test_never_made_or_used(self):
        for w in ("nya", "fast", "moon", "shine", "closer"):
            self.assertIsNone(animgen.ensure(w))
        import catalog
        self.assertFalse(animlib.NOT_ACTIONS & set(catalog.ANIMS))
        self.assertEqual(A.parse_directions("[closerup, smug] So yeah", [])[0].get("camera"), "closeup")


if __name__ == "__main__":
    unittest.main()
