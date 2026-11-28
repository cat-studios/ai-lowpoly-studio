"""Text (ASCII) FBX -> OBJ (pipeline/fbx_ascii.py, 2026-11-28: 293 of the user's models were text FBX, which
Blender can't read).  python -m unittest discover tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import fbx_ascii  # noqa: E402

FBX = """; FBX 7.3.0 project file
; Copyright (C) 1997-2010 Autodesk
FBXHeaderExtension:  {
	FBXVersion: 7300
}
GlobalSettings:  {
	Properties70:  {
		P: "UpAxis", "int", "Integer", "",1
	}
}
Objects:  {
	Model: 100, "Model::box", "Null" {
		Properties70:  {
			P: "Lcl Translation", "Lcl Translation", "", "A+",10,0,0
		}
	}
	Model: 200, "Model::part", "Mesh" {
		Properties70:  {
			P: "Lcl Translation", "Lcl Translation", "", "A+",0,2,0
			P: "Lcl Scaling", "Lcl Scaling", "", "A",2,2,2
		}
	}
	Geometry: 300, "Geometry::", "Mesh" {
		Vertices: *12 {
			a: 0,0,0,1,0,0,1,1,0,0,1,0
		}
		PolygonVertexIndex: *6 {
			a: 0,1,-3,0,2,-4
		}
		LayerElementMaterial: 0 {
			MappingInformationType: "ByPolygon"
			Materials: *2 {
				a: 0,1
			}
		}
	}
	Material: 400, "Material::red", "" {
		Properties70:  {
			P: "DiffuseColor", "Color", "", "A",1,0,0
		}
	}
	Material: 401, "Material::blue paint", "" {
		Properties70:  {
			P: "DiffuseColor", "Color", "", "A",0,0,1
		}
	}
}
Connections:  {
	;Model::box, Model::RootNode
	C: "OO",100,0
	C: "OO",200,100
	C: "OO",300,200
	C: "OO",400,200
	C: "OO",401,200
}
"""


class Convert(unittest.TestCase):
    def test_mesh_hierarchy_and_colours(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "box.fbx"
            src.write_text(FBX, encoding="utf-8")
            self.assertTrue(fbx_ascii.is_ascii_fbx(src))
            res = fbx_ascii.convert(src, Path(d) / "out")
            self.assertEqual((res["meshes"], res["faces"], res["materials"]), (1, 2, 2))
            obj = Path(res["obj"]).read_text(encoding="utf-8").splitlines()
            verts = [tuple(float(x) for x in l.split()[1:]) for l in obj if l.startswith("v ")]
            # parent (10, 0, 0) then child (0, 2, 0) scaled 2x: (1, 1, 0) -> (12, 4, 0)
            self.assertIn((12.0, 4.0, 0.0), verts)
            self.assertIn("usemtl red", obj)
            self.assertIn("usemtl blue_paint", obj)
            mtl = (Path(d) / "out" / "box.mtl").read_text(encoding="utf-8")
            self.assertIn("Kd 0.0000 0.0000 1.0000", mtl)

    def test_binary_is_not_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.fbx"
            p.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00")
            self.assertFalse(fbx_ascii.is_ascii_fbx(p))


if __name__ == "__main__":
    unittest.main()
