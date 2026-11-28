"""✅ Verified (the user, 2026-11-28: "a manual verified button to override the AI automatic scoring") for made
props and animations.  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import animgen  # noqa: E402
import animlib  # noqa: E402
import propgen  # noqa: E402


class Props(unittest.TestCase):
    def test_verified_counts_as_passed_and_skips_the_check(self):
        d = {"kind": "kudu", "parts": [{"shape": "box"}], "look_score": 2, "checked": False, "complex": True}
        propgen.set_verified(d, True)
        self.assertTrue(d["checked"])
        self.assertFalse(d["complex"])                 # a low score had made it a picture
        with mock.patch.object(propgen, "look_score", side_effect=AssertionError("checked again")):
            self.assertIs(propgen.look_checked(d, "kudu", "", "", {}), d)
        propgen.set_verified(d, False)
        self.assertFalse(d["checked"])                 # the score (2/10) decides again
        self.assertNotIn("verified", d)

    def test_users_own_sprite_stays_a_sprite(self):
        d = {"kind": "x", "parts": [{}], "form": "sprite", "complex": True}
        propgen.set_verified(d, True)
        self.assertTrue(d["complex"])


class Anims(unittest.TestCase):
    def test_verified_animation_is_used(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(animlib, "LIB", Path(tmp)):
            a = dict(next(iter(animlib.BUILTIN.values())), name="yawn", checked=False, score=3)
            animlib.save(a)
            got = animgen.set_verified("yawn", True)
            self.assertTrue(got["verified"])
            self.assertTrue(animlib.library()["yawn"]["checked"])
            got = animgen.set_verified("yawn", False)
            self.assertFalse(got["checked"])
            self.assertNotIn("verified", got)


if __name__ == "__main__":
    unittest.main()
