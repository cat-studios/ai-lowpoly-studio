"""Recurring cast (pipeline/actors.py): keeping a guest from a video, and what the writer is told.
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import actors as AC  # noqa: E402
import autodirect as A  # noqa: E402
import llm  # noqa: E402

ROSE = {"id": "grandma_rose", "name": "Grandma Rose", "role": "grandma", "personality": "sneaky, loves cookies",
        "description": "grey bun", "kind": "generic", "regular": True}


class Regulars(unittest.TestCase):
    def test_writer_note_names_the_id_to_use(self):
        with mock.patch.object(AC, "get", lambda i: ROSE if i == "grandma_rose" else None):
            note = AC.writer_note(["grandma_rose", "gone"])
        self.assertIn("Grandma Rose (+grandma_rose)", note)
        self.assertIn("sneaky, loves cookies", note)
        self.assertEqual(AC.writer_note([]), "")

    def test_keep_a_guest_with_her_look_and_voice(self):
        info = {"type": "person", "looks": "mom, red dress", "look": {"hair": "#7a4a2a", "dress": "#d94a4a"},
                "height": 0.97, "actor": AC.GENERIC_ID}
        with mock.patch.object(AC, "save", lambda d, aid=None: d):
            got = AC.from_cast("mom", info, episode="ep1")
        self.assertEqual((got["kind"], got["look"]["dress"], got["height"]), ("generic", "#d94a4a", 0.97))
        self.assertNotEqual(got["voice"], AC.ACTOR_VOICE)          # a woman's voice, kept from now on
        self.assertTrue(got["regular"])

    def test_imported_person_stays_that_model(self):
        info = {"type": "thing", "looks": "mom", "def": {"person": True, "model": {"id": "pack_woman_3"}}}
        with mock.patch.object(AC, "save", lambda d, aid=None: d):
            got = AC.from_cast("mom", info)
        self.assertEqual((got["kind"], got["model_id"]), ("imported", "pack_woman_3"))

    def test_regular_speaks_her_own_lines(self):
        lines = llm._clean_lines("Cookies are gone!\n[+grandma_rose enter] Grandma Rose: Not me, dear.", main=["Catgirl"])
        shots = A.direct("\n".join(lines), "cafe", beat_words=0)["shots"]
        self.assertEqual(shots[1]["speaker"], "grandma_rose")

    def test_speaking_people_are_played_by_actors(self):
        mine = [{"id": "generic_human", "builtin": True},
                {"id": "candycane_lady", "name": "Candycane Lady", "role": "", "description": "", "kind": "imported"},
                {"id": "lady", "name": "Shop lady", "role": "", "description": "", "kind": "generic"},
                {"id": "store_clerk", "name": "Store clerk", "role": "store clerk", "description": "", "kind": "generic"}]
        with mock.patch.object(AC, "all_actors", lambda: mine):
            self.assertEqual(AC.side_character("mom")["id"], "lady")            # a generic woman, never an imported one
            self.assertEqual(AC.side_character("grandpa")["kind"], "generic")
            self.assertEqual(AC.side_character("neighbour")["id"], AC.side_character("neighbour")["id"])
        with mock.patch.object(AC, "all_actors", lambda: mine[:1]):
            self.assertIsNone(AC.side_character("mom"))                                # no actors: the studio body

    def test_they_remember_what_they_said(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "grandma_rose.json").write_text(json.dumps({**ROSE, "catchphrase": "Back in my day..."}), encoding="utf-8")
            ep = {"title": "Cookie heist", "cast": {"grandma_rose": {"type": "person", "actor": "grandma_rose"}},
                  "shots": [{"line": "Where are the cookies?"},
                            {"line": "Not me, dear.", "speaker": "grandma_rose"}]}
            with mock.patch.object(AC, "DIR", d):
                AC.remember(ep, log=lambda m: None)
                a = AC.get("grandma_rose")
                self.assertEqual(a["history"][-1], {**a["history"][-1], "title": "Cookie heist", "lines": ["Not me, dear."]})
                note = AC.writer_note(["grandma_rose"])
                AC.save({"name": "Grandma Rose", "kind": "generic", "regular": True}, aid="grandma_rose")
                self.assertTrue(AC.get("grandma_rose")["history"])          # an edit keeps it
        self.assertIn('"Back in my day..."', note)
        self.assertIn("Not me, dear.", note)

    def test_bare_direction_lines_go_into_the_next_line(self):
        # "+mom enter, angry" on its own line was half spoken (", angry") and Mom's next line wasn't hers
        lines = llm._clean_lines("Uh oh.\n+mom enter, angry\nMom: Again?\n+ toaster: Ding!", main=["Catgirl"])
        self.assertEqual(lines[1], "[+mom enter, angry] Mom: Again?")
        self.assertEqual(lines[2], "[+toaster enter] Toaster: Ding!")
        shots = A.direct("\n".join(lines[:2]), "cafe", beat_words=0)["shots"]
        self.assertEqual(shots[-1]["speaker"], "mom")
        self.assertNotIn("angry", " ".join(s.get("line", "") for s in shots))


if __name__ == "__main__":
    unittest.main()
