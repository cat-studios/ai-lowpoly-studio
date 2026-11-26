"""Fact check (pipeline/factcheck.py), its report in review.py, and the writer's hooks/endings.  python -m unittest discover tests"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import factcheck  # noqa: E402
import llm  # noqa: E402
import review  # noqa: E402

EP = {"template": "quick_facts", "shots": [{"line": "Octopuses have three hearts."}, {"line": "Bananas are berries."},
                                             {"line": "Wow, you didn't know that!"}]}
SETTINGS = {"ollama": {"url": "http://x", "model": "m"}}


class FactCheck(unittest.TestCase):
    def run_check(self, extracted, verdicts, articles):
        build = Path(tempfile.mkdtemp())
        chat = mock.Mock(side_effect=[extracted] + verdicts)
        with mock.patch.object(factcheck.S, "load_settings", lambda: SETTINGS), \
                mock.patch.object(factcheck.llm, "chat_json", chat), \
                mock.patch.object(factcheck, "article", lambda q, claim="": articles.get(q, (None, ""))):
            res = factcheck.check_episode(EP, build, log=lambda *a: None)
        return res, build

    def test_claims_are_judged_against_the_article_and_saved(self):
        extracted = {"claims": [{"n": 1, "claim": "Octopuses have three hearts.", "search": "octopus heart"},
                                {"n": 2, "claim": "Bananas are berries.", "search": "banana"}]}
        articles = {"octopus heart": ("https://en.wikipedia.org/wiki/Octopus", "An octopus has three hearts."),
                    "banana": ("https://en.wikipedia.org/wiki/Banana", "A banana is an elongated, edible fruit.")}
        verdicts = [{"verdict": "supported", "note": "the article says so"},
                    {"verdict": "contradicted", "note": "bananas are not berries in the botanical sense"}]
        res, build = self.run_check(extracted, verdicts, articles)
        self.assertEqual(res["status"], "done")
        by_claim = {c["claim"]: c for c in res["claims"]}
        self.assertEqual(by_claim["Octopuses have three hearts."]["verdict"], "supported")
        self.assertEqual(by_claim["Bananas are berries."]["verdict"], "contradicted")
        self.assertEqual(by_claim["Bananas are berries."]["shot"], 2)
        self.assertEqual(by_claim["Octopuses have three hearts."]["source"], "https://en.wikipedia.org/wiki/Octopus")
        saved = json.loads((build / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["claims"]), 2)

    def test_no_article_means_unknown_without_a_judging_call(self):
        extracted = {"claims": [{"n": 1, "claim": "Octopuses have three hearts.", "search": "nothing"}]}
        res, _ = self.run_check(extracted, [], {})
        self.assertEqual(res["claims"][0]["verdict"], "unknown")

    def test_a_model_that_cannot_run_never_fails_the_render(self):
        build = Path(tempfile.mkdtemp())
        with mock.patch.object(factcheck.S, "load_settings", lambda: SETTINGS), \
                mock.patch.object(factcheck.llm, "chat_json", mock.Mock(side_effect=OSError("refused"))):
            res = factcheck.check_episode(EP, build, log=lambda *a: None)
        self.assertEqual(res["status"], "error")
        self.assertTrue((build / "facts.json").exists())

    def test_the_judge_reads_the_paragraphs_about_the_claim(self):
        text = ("The octopus is a soft-bodied mollusc with eight limbs and no skeleton at all.\n"
                "== Anatomy ==\n"
                "Octopuses live in every ocean, and many species live on the sea floor near the coast.\n"
                "They have three hearts: one pumps blood round the body, two pump it through the gills.\n")
        got = factcheck.relevant(text, "Octopuses have three hearts")
        self.assertIn("three hearts", got)
        self.assertTrue(got.startswith("The octopus is"))           # the intro always comes first
        self.assertNotIn("== Anatomy ==", got)

    def test_a_claim_its_line_never_made_is_dropped(self):
        extracted = {"claims": [{"n": 3, "claim": "It is a secret.", "search": "secret"},      # line 3: "Wow, you didn't..."
                                {"n": 1, "claim": "Octopuses possess three hearts.", "search": "nothing"}]}
        res, _ = self.run_check(extracted, [], {})
        self.assertEqual([c["claim"] for c in res["claims"]], ["Octopuses possess three hearts."])

    def test_a_claim_about_the_speaker_is_not_a_fact(self):
        extracted = {"claims": [{"n": 3, "claim": "You didn't know that.", "search": "know"},
                                {"n": 1, "claim": "Octopuses possess three hearts.", "search": "nothing"}]}
        res, _ = self.run_check(extracted, [], {})
        self.assertEqual([c["claim"] for c in res["claims"]], ["Octopuses possess three hearts."])

    def test_an_article_about_something_else_is_no_source(self):
        pages = {"query": {"search": [{"title": "Jackie - Public, Private, Secret"}], "pages": [
            {"extract": "Jackie - Public, Private, Secret is a 2008 documentary film about a famous woman's life."}]}}
        with mock.patch.object(factcheck, "_wiki", lambda params: pages):
            self.assertEqual(factcheck.article("bananas", "Bananas grow on trees"), (None, ""))

    def test_the_same_script_reuses_the_last_check(self):
        extracted = {"claims": [{"n": 1, "claim": "Octopuses have three hearts.", "search": "nothing"}]}
        res, build = self.run_check(extracted, [], {})
        chat = mock.Mock(side_effect=AssertionError("the model was asked again"))
        with mock.patch.object(factcheck.S, "load_settings", lambda: SETTINGS), \
                mock.patch.object(factcheck.llm, "chat_json", chat):
            again = factcheck.check_episode(EP, build, log=lambda *a: None)
        self.assertEqual(again["claims"], res["claims"])

    def test_only_fact_kinds_are_checked(self):
        self.assertTrue(factcheck.applies({"template": "myth_or_fact"}, {}))
        self.assertFalse(factcheck.applies({"template": "what_if"}, {}))
        self.assertFalse(factcheck.applies({"template": "quick_facts"}, {"facts": {"check": False}}))


class Report(unittest.TestCase):
    def test_contradicted_is_a_warning_and_unknown_an_info(self):
        build = Path(tempfile.mkdtemp())
        (build / "facts.json").write_text(json.dumps({"claims": [
            {"shot": 2, "claim": "Bananas are berries.", "verdict": "contradicted", "note": "not botanically",
             "source": "https://en.wikipedia.org/wiki/Banana"},
            {"shot": 3, "claim": "Octopuses dream.", "verdict": "unknown", "note": "no article"},
            {"shot": 1, "claim": "Octopuses have three hearts.", "verdict": "supported"}]}), encoding="utf-8")
        out = []
        review.fact_issues(EP, build, out)
        self.assertEqual([i["level"] for i in out], ["warn", "info"])
        self.assertEqual(out[0]["shots"], [2])

    def test_a_check_of_an_older_script_is_not_reported(self):
        build = Path(tempfile.mkdtemp())
        (build / "facts.json").write_text(json.dumps({"key": "something-else", "claims": [
            {"shot": 2, "claim": "Bananas are berries.", "verdict": "contradicted"}]}), encoding="utf-8")
        out = []
        review.fact_issues(EP, build, out)
        self.assertEqual(out, [])


class Writer(unittest.TestCase):
    def test_each_script_gets_one_hook_style_and_the_loop_ending(self):
        for seed in range(5):
            style = llm.pick_hook_style(random.Random(seed))
            self.assertIn(style, llm.HOOK_STYLES)
            self.assertIn(llm.HOOK_STYLES[style], llm.hook_rule(style))
        self.assertIn(llm.HOOK_STYLES["number"], llm.hook_rule("not-a-style"))
        self.assertIn("loops back", llm.ENDING_RULE)


if __name__ == "__main__":
    unittest.main()
