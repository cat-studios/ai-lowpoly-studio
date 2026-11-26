"""The director (pipeline/autodirect.py): each test is a bug seen in a real video.
Run all tests:  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import run_episode as R  # noqa: E402


def shots(script, **kw):
    return A.direct(script, "cafe", beat_words=0, **kw)["shots"]


class StageDirections(unittest.TestCase):
    def test_plus_name_after_brackets_is_a_direction_not_speech(self):
        # "+mom enter from_left" was spoken and captioned "from left mom"
        s = shots("[wide] Hello!\n[medium, happy] +mom enter from_left Mom! You're upside down again!")
        self.assertEqual(s[1]["line"], "Mom! You're upside down again!")
        self.assertIn({"who": "mom", "do": "enter", "from": "left"}, s[1]["events"])

    def test_plus_name_mid_line_is_said_as_the_name(self):
        s = shots("[closeup] Wow +tiny_dragon is here.")
        self.assertEqual(s[0]["line"], "Wow tiny dragon is here.")

    def test_scene_words_glued_to_a_place_go_back_to_the_directions(self):
        d, text = A.parse_directions("[@ kitchen jump, excited] Look!", ["center"])
        self.assertEqual(d["scene"], "kitchen")
        self.assertEqual(d["action"], "jump")
        d, _ = A.parse_directions("[@library enter] Oh no", ["center"])
        self.assertEqual(d["scene"], "library")
        self.assertNotIn("want", d)      # "enter" is a cast verb, not a pose to invent


class BracketWords(unittest.TestCase):
    def test_camera_and_move_words_are_mapped(self):
        self.assertEqual(A.parse_directions("[mid, happy] hi", [])[0].get("camera"), "medium")
        self.assertEqual(A.parse_directions("[wide, zoom_in] hi", [])[0].get("move"), "push_in")

    def test_junk_words_never_become_animations(self):
        for word in ("angle", "swim_by", "sidewalk_to", "hold", "dreamy"):
            d, _ = A.parse_directions(f"[{word}] hi", [])
            self.assertNotIn("want", d, word)


class LightAndWalking(unittest.TestCase):
    def test_night_without_time_words_is_dropped(self):
        s = shots("[wide] Hello.\n[night, surprised] Wait, why is the sun here?")
        self.assertNotIn("light", s[1])

    def test_night_with_time_words_stays(self):
        s = shots("[wide] Hello.\n[night] It got dark, time to sleep.")
        self.assertEqual(s[1].get("light"), "night")

    def test_at_most_two_walks(self):
        s = shots("[wide] Hello!\n[walk_to left] One.\n[run_to right] Two.\n[sneak_to back] Three.")
        walks = [x for x in s if x.get("action") in ("walk_to", "run_to", "sneak_to")]
        self.assertLessEqual(len(walks), A.MAX_WALKS)


class Speakers(unittest.TestCase):
    def test_a_person_brought_in_speaks_their_own_line(self):
        s = shots("[wide] Cats rule!\n[closeup] Mom?! You're in my dream!\n"
                  "[+mom enter] Mom: Honey, your alarm is ringing!")
        self.assertEqual(s[2].get("speaker"), "mom")
        self.assertEqual(s[2]["line"], "Honey, your alarm is ringing!")


class Cast(unittest.TestCase):
    def test_body_parts_and_the_sun_are_never_people(self):
        r = {"shots": [{"line": "my head hurts"}, {"line": "the sun!"}, {"line": "mom!"}], "cast": {}}
        A.add_cast_plan(r, {"cast": {"head": {"type": "thing"}, "sun": {"type": "person"}, "mom": {"type": "person"}},
                            "events": [{"line": 0, "who": "head", "do": "appear"},
                                       {"line": 1, "who": "sun", "do": "enter"},
                                       {"line": 2, "who": "mom", "do": "enter"}]})
        self.assertNotIn("head", r["cast"])
        self.assertEqual(r["cast"]["sun"]["type"], "thing")
        self.assertEqual(r["cast"]["mom"]["type"], "person")



class Opening(unittest.TestCase):
    def test_hook_pushes_in_instead_of_walking(self):
        first = shots("The moon just vanished tonight.\nThe tides would stop!")[0]
        self.assertEqual((first["camera"], first["move"]), ("closeup", "push_in"))
        self.assertNotIn(first["action"], ("walk_to", "run_to"))

    def test_hook_word(self):
        self.assertEqual(R.hook_word("WHAT IF THE MOON VANISHED?".split()), 4)
        self.assertIsNone(R.hook_word("WHAT IF IT IS".split()))

class Negation(unittest.TestCase):
    def test_a_negated_mood_word_is_not_that_mood(self):
        self.assertEqual(A.mood_of("I'm not mad."), "neutral")
        self.assertEqual(A.mood_of("Don't be sad"), "neutral")
        self.assertEqual(A.mood_of("I'm never scared"), "neutral")
        self.assertEqual(A.mood_of("I'm so mad!"), "angry")
        self.assertEqual(A.mood_of("Ugh, seriously?"), "angry")


if __name__ == "__main__":
    unittest.main()
