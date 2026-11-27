"""Assets -> 🧊 Make it real 3D (propgen.make_real / made_def / can_make_real) and the 🧹 made-up animations.
python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import animlib  # noqa: E402
import propgen  # noqa: E402

SHAPES = {"kind": "lamp", "parts": [{"shape": "box"}], "height": 1.5, "looks": "a tall lamp"}


class Rules(unittest.TestCase):
    def test_which_props_can_be_made_real(self):
        self.assertTrue(propgen.can_make_real(SHAPES))
        self.assertFalse(propgen.can_make_real(dict(SHAPES, sign={"text": "SALE"})))      # its text is the point
        self.assertFalse(propgen.can_make_real(dict(SHAPES, explainer=True)))             # its parts move
        self.assertFalse(propgen.can_make_real(dict(SHAPES, source="imported")))
        self.assertFalse(propgen.can_make_real(dict(SHAPES, made={"id": "made_3d_lamp_1"})))
        self.assertFalse(propgen.can_make_real({"kind": "x", "parts": []}))

    def test_made_prop_gives_its_model_at_its_own_size(self):
        d = dict(SHAPES, made={"id": "made_3d_lamp_1"})
        fake = {"name": "lamp", "source": "imported", "height": 0.9, "model": {"id": "made_3d_lamp_1"}}
        with mock.patch("imported.model_def", return_value=fake):
            md = propgen.made_def(d)
        self.assertEqual((md["height"], md["made_3d"], md["library_kind"]), (1.5, True, "lamp"))

    def test_a_missing_model_falls_back_to_the_shapes(self):
        with mock.patch("imported.model_def", return_value=None):
            self.assertIsNone(propgen.made_def(dict(SHAPES, made={"id": "gone"})))
        self.assertIsNone(propgen.made_def(SHAPES))

    def test_design_uses_the_made_model(self):
        d = dict(SHAPES, made={"id": "made_3d_lamp_1"})
        with mock.patch.object(propgen, "library", return_value={"lamp": d}), \
                mock.patch.object(propgen, "imported_def", return_value=None), \
                mock.patch.object(propgen, "made_def", return_value={"model": {"id": "made_3d_lamp_1"}, "made_3d": True}):
            self.assertTrue(propgen.design("lamp", "a tall lamp", log=lambda *a: None)["made_3d"])


class MadeUpAnimations(unittest.TestCase):
    def test_tidy_list(self):
        for w in ("nya", "fast", "whispering", "moon"):
            self.assertIn(w, animlib.NOT_ACTIONS)
        for w in ("salute", "flex", "dizzy", "kiss"):
            self.assertNotIn(w, animlib.NOT_ACTIONS)


if __name__ == "__main__":
    unittest.main()
