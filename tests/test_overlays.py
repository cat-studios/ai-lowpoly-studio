"""Game overlays (pipeline/overlays.py), the selfie camera lock and the new kinds of video (2026-11-27).
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import autodirect as A  # noqa: E402
import overlays as O  # noqa: E402
import templates as T  # noqa: E402


def timing(n, secs=3.0, fps=12):
    return {"fps": fps, "total_frames": int(n * secs * fps),
            "shots": [{"f0": 1 + int(i * secs * fps), "n": int(secs * fps)} for i in range(n)]}


class Parse(unittest.TestCase):
    def test_kinds(self):
        hud, rest = O.parse("closeup, meter: stress 99%, count: cookies_eaten 12, tag: BOSS: ME, label: Snack-O-Matic, "
                            "bubble: in..., sticker: nom nom, happy")
        self.assertEqual(hud, [{"kind": "meter", "name": "STRESS", "value": 99.0},
                               {"kind": "count", "name": "COOKIES EATEN", "value": 12},
                               {"kind": "tag", "text": "BOSS: ME"}, {"kind": "label", "text": "Snack-O-Matic"},
                               {"kind": "bubble", "text": "in..."}, {"kind": "sticker", "text": "nom nom"}])
        self.assertNotIn("meter", rest)
        self.assertIn("happy", rest)

    def test_bad_values(self):
        self.assertEqual(O.parse("meter: stress")[0], [])            # no number
        self.assertEqual(O.parse("meter: joy 250")[0][0]["value"], 100.0)

    def test_directions_keep_the_rest(self):
        d, text = A.parse_directions("[closeup, meter: stress 99, smug] You look tired.", [])
        self.assertEqual((d["camera"], d["expression"], d["hud"][0]["name"]), ("closeup", "smug", "STRESS"))
        self.assertEqual(text, "You look tired.")


class Events(unittest.TestCase):
    def test_meter_slides_and_shows_the_change(self):
        shots = [{"hud": [{"kind": "meter", "name": "STRESS", "value": 99.0}]}, {},
                 {"hud": [{"kind": "meter", "name": "STRESS", "value": 60.0}]}]
        lines = O.events(shots, timing(3), (216, 384), 9.0, 9.0)
        text = "\n".join(lines)
        self.assertIn("99%", text)
        self.assertIn("60%", text)
        self.assertIn("-39%", text)
        self.assertIn("STRESS", text)
        self.assertTrue(any("%" in l and "Hud" in l and str(v) + "%" in l for l in lines for v in range(61, 99)))

    def test_counter_tag_label_bubble_sticker(self):
        shots = [{"hud": [{"kind": "count", "name": "PATS", "value": 0}, {"kind": "tag", "text": "OWNER: ME"}]},
                 {"hud": [{"kind": "count", "name": "PATS", "value": 397}, {"kind": "label", "text": "PAT-O-MATIC"},
                          {"kind": "bubble", "text": "in..."}]},
                 {"hud": [{"kind": "tag", "text": "OWNER: THE DOG"}, {"kind": "sticker", "text": "BOOP"}]}]
        text = "\n".join(O.events(shots, timing(3), (216, 384), 9.0, 8.0, stickers=[("BOOM!", 1.0)]))
        for want in ("PATS", "397", "OWNER: ME", "OWNER: THE DOG", "PAT-O-MATIC", "in...", "BOOP", "BOOM!"):
            self.assertIn(want, text)

    def test_stickers_spaced_and_never_after_the_end_card(self):
        st = [("A!", 1.0), ("B!", 1.5), ("C!", 3.0), ("D!", 8.5)]
        text = "\n".join(O.events([{}], timing(1, 9.0), (216, 384), 9.0, 8.0, stickers=st))
        self.assertIn("A!", text)
        self.assertNotIn("B!", text)          # too soon after A
        self.assertIn("C!", text)
        self.assertNotIn("D!", text)          # under the end card

    def test_meter_colours(self):
        self.assertEqual(O.meter_color("STRESS", 95), "#ff5a5a")
        self.assertEqual(O.meter_color("STRESS", 5), "#5fe36a")
        self.assertEqual(O.meter_color("ENERGY", 95), "#5fe36a")


class SoundStickers(unittest.TestCase):
    def test_trigger_word_or_sound_word(self):
        import sfx
        ep = {"shots": [{"line": "And then KABOOM went the oven"}, {"line": "hello"}]}
        tm = timing(2)
        fake = lambda ep, timing, sx: [("boom", 1.0, 0.5), ("whoosh", 4.0, 0.5), ("amb_waves", 0.0, 0.3)]  # noqa: E731
        out = O.sound_stickers(ep, tm, {}, fake, sfx.all_slots, sfx.word_rx)
        self.assertEqual(out, [("KABOOM!", 1.0), ("WHOOSH!", 4.0)])


class KindsAndCamera(unittest.TestCase):
    def test_new_templates(self):
        for k in ("talk_to_you", "gadget_story"):
            self.assertIn(k, T.TEMPLATES)
        self.assertEqual(T.pacing("talk_to_you")["camera"], "selfie")
        self.assertEqual(T.pacing("talk_to_you", beats_on=False)["camera"], "selfie")
        self.assertIn("TWIST", T.get("what_if")["script"])
        self.assertIn("[label:", T.get("gadget_story")["script"])

    def test_selfie_lock(self):
        r = A.direct("[meter: stress 99] Hey you. Are you stressed out right now?\n[walk_to center] Let's breathe.\n"
                     "[wide] Look at me!\n[cutaway: a cup of tea] Tea helps.", "cafe", beat_words=4, camera="selfie")
        for sh in r["shots"]:
            if sh.get("cutaway"):
                continue
            want = "wide" if sh["line"].startswith("Look") else "selfie"     # a camera the script names still wins
            self.assertEqual(sh["camera"], want, sh["line"])
            self.assertNotIn(sh.get("action"), ("walk_to", "run_to"))
        self.assertEqual(A.parse_directions("[facecam] hi", [])[0]["camera"], "selfie")


if __name__ == "__main__":
    unittest.main()
