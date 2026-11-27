"""Local 3D models (pipeline/model3d.py: a drawing -> TRELLIS 2 in ComfyUI -> a low-poly GLB). No GPU needed here:
the workflow's wiring, finding the GLB in ComfyUI's history, the newer COMBO lists.  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import comfy  # noqa: E402
import model3d  # noqa: E402


class Graph(unittest.TestCase):
    def test_every_link_points_at_a_node(self):
        for up in (False, True):
            self._check(model3d.graph("drawing.png", 7, "3d/lowpoly_studio/duck", faces=1500, upsample=up), up)

    def _check(self, g, up):
        for nid, node in g.items():
            for name, v in node["inputs"].items():
                self.assertIsNotNone(v, f"{nid}.{name} was left empty")
                if isinstance(v, list):
                    self.assertIn(v[0], g, f"{nid}.{name} -> {v[0]}")
        self.assertEqual(g["low"]["inputs"]["target_face_count"], 1500)
        self.assertEqual(g["save"]["class_type"], "SaveGLB")
        self.assertEqual(g["img"]["inputs"]["image"], "drawing.png")
        ks = ("k_struct", "k_shape", "k_up", "k_tex") if up else ("k_struct", "k_shape", "k_tex")
        self.assertEqual(len({g[k]["inputs"]["seed"] for k in ks}), len(ks))
        self.assertEqual(g["low"]["inputs"]["mesh"], ["clean", 0])          # remeshed before it's simplified

    def test_uses_only_the_downloaded_files(self):
        used = {v for n in model3d.graph("x.png", 1, "p").values() for v in n["inputs"].values() if isinstance(v, str)}
        self.assertTrue(set(model3d.FILES.values()) <= used)


class Results(unittest.TestCase):
    def test_find_the_glb(self):
        outs = {"save": {"3d": [{"filename": "duck_00001_.glb", "subfolder": "3d/lowpoly_studio", "type": "output"}]},
                "x": {"images": [{"filename": "a.png"}]}}
        self.assertEqual(model3d._find_file(outs)["filename"], "duck_00001_.glb")
        self.assertIsNone(model3d._find_file({"x": {"images": [{"filename": "a.png"}]}}))


class Options(unittest.TestCase):
    def test_old_and_new_combo_lists(self):
        with mock.patch.object(comfy, "_json", return_value={"N": {"input": {"required": {"f": [["a", "b"]]}}}}):
            self.assertEqual(comfy._options("u", "N", "f"), ["a", "b"])
        with mock.patch.object(comfy, "_json", return_value={"N": {"input": {"required": {"f": ["COMBO", {"options": ["c"]}]}}}}):
            self.assertEqual(comfy._options("u", "N", "f"), ["c"])

    def test_missing_files(self):
        lists = {"unet_name": [model3d.FILES["unet"]], "clip_name": [model3d.FILES["clip_vision"]],
                 "vae_name": [model3d.FILES["shape_vae"]], "bg_removal_name": []}
        with mock.patch.object(comfy, "_options", side_effect=lambda u, n, f: lists[f]):
            self.assertEqual(sorted(model3d.missing_files("u")), sorted([model3d.FILES["texture_vae"], model3d.FILES["bg"]]))


if __name__ == "__main__":
    unittest.main()
