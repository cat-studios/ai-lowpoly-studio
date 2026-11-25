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
