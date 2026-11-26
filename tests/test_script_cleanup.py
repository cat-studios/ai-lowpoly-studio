"""Script cleanup (llm._clean_lines), cutaways (run_episode.resolve_cutaways), the ideas filter and imported-model
name rules: each test is a bug seen in a real video.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import ideas  # noqa: E402
import imported  # noqa: E402
import llm  # noqa: E402
import run_episode as R  # noqa: E402


class CleanLines(unittest.TestCase):
    def test_myth_or_fact_words_in_brackets_are_said(self):
        # the first production try: "Myth!" inside the brackets, and "+second_claim" brought in as a person
        out = llm._clean_lines("[medium, laugh, Myth!] They remember for months!\n"
                               "[+second_claim enter, wide, sad] Second claim: do they sleep?", main=["Catgirl"])
        self.assertEqual(out, ["[medium, laugh] Myth! They remember for months!", "[wide, sad] Second claim: do they sleep?"])

    def test_list_labels_are_said_not_people(self):
        # the Top 5 / Myth or fact / Guess what formats: "Number 5:" brought in a person called number_5
        out = llm._clean_lines("Number 5: [cutaway: an owl] Owls turn their heads.\n[closeup] Clue 2: It swims.\n"
                               "Myth: goldfish forget fast.", main=["Catgirl"])
        self.assertEqual(out, ["[cutaway: an owl] Number 5: Owls turn their heads.", "[closeup] Clue 2: It swims.",
                               "Myth: goldfish forget fast."])

    def test_her_own_label_goes_others_stay_and_are_brought_in(self):
        out = llm._clean_lines("Catgirl: I declared myself Empress!\n[closeup] Mom?! Hi!\n"
                               "Mom: Honey, your alarm is ringing!\nNarrator: And so it ends.", main=["Catgirl"])
        self.assertEqual(out[0], "I declared myself Empress!")
        self.assertEqual(out[2], "[+mom enter] Mom: Honey, your alarm is ringing!")   # she used to read Mom's line
        self.assertEqual(out[3], "And so it ends.")

    def test_emphasis_stars_are_removed(self):
        self.assertEqual(llm._clean_lines("[wide] Cats rule the *world*, nya!")[0], "[wide] Cats rule the world, nya!")

    def test_titles_never_keep_labels(self):
        self.assertEqual(llm._clean_lines("Idea 1: What if cats flew?", people=False), ["What if cats flew?"])


class Cutaways(unittest.TestCase):
    def run_cut(self, line, cut):
        ep = {"shots": [{"line": line, "cutaway": cut}]}
        R.resolve_cutaways(ep, log=lambda m: None)
        return ep

    def test_a_comparison_cutaway_is_dropped(self):
        # "[cutaway: a blue whale swimming] Scientists say it swells up..." in a video about sleep
        ep = self.run_cut("Scientists say it swells up three times bigger", "a blue whale swimming")
        self.assertNotIn("cutaway", ep["shots"][0])
        self.assertFalse(ep.get("cast"))

    def test_subject_names(self):
        for line, cut, who in (("Even an elephant would bounce that high!", "an elephant bouncing high", "elephant"),
                               ("like a stretched rubber band", "a stretched rubber band", "rubber_band"),
                               ("First a crumb starts running", "a crumb running across the counter", "crumb")):
            self.assertIn(who, self.run_cut(line, cut)["cast"], cut)


class IdeaFilter(unittest.TestCase):
    def test_sad_and_violent_news_is_blocked(self):
        for t in ("Jeddah floods swamp the city", "A fire breaks out on a ship", "massacres in", "an obituary"):
            self.assertTrue(ideas.BLOCK.search(t), t)

    def test_curious_things_pass(self):
        for t in ("Einstein presents general relativity", "First telephone call", "Why cats purr"):
            self.assertFalse(ideas.BLOCK.search(t), t)


class ImportedNames(unittest.TestCase):
    def test_compound_names(self):
        self.assertIn("hot dog", imported.COMPOUNDS)      # "Raw Hot Dog" played a dog
        self.assertIn("teddy bear", imported.COMPOUNDS)


if __name__ == "__main__":
    unittest.main()
