"""Weather and time that follow the story (autodirect.story_weather).  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402

DAY = ("I woke up so happy today!\nThen my ice cream fell. I am so sad.\nNobody came to my party. So lonely.\n"
       "But then everyone showed up! Party time!\nWhat a day.")


class StoryWeather(unittest.TestCase):
    def test_sad_lines_rain_outdoors_and_lose_party_confetti(self):
        shots = A.direct(DAY, "park", beat_words=0)["shots"]
        self.assertEqual(shots[1].get("particles"), ["rain"])
        self.assertEqual(shots[2].get("particles"), ["rain"])                # "party" gave it confetti
        self.assertEqual(shots[3].get("particles"), ["confetti"])

    def test_no_rain_indoors(self):
        self.assertIsNone(A.direct("I am so sad.", "cafe", beat_words=0)["shots"][0].get("particles"))

    def test_a_day_in_the_life_goes_from_day_to_night(self):
        shots = A.direct(DAY, "park", beat_words=0, title="A day in the life of a catgirl")["shots"]
        self.assertEqual([s.get("light") for s in shots], [None, None, None, "sunset", "night"])
        self.assertFalse(any(s.get("light") for s in A.direct(DAY, "park", beat_words=0)["shots"]))


if __name__ == "__main__":
    unittest.main()
