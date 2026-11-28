"""Text (ASCII) FBX -> OBJ + MTL, in plain Python (2026-11-28: 293 of the user's imported models were ASCII FBX,
which Blender's FBX importer can't read - it only reads binary FBX).

What it keeps: every mesh (Geometry) with its Model's place in the hierarchy (Lcl Translation / Rotation /
Scaling, PreRotation, GeometricTranslation/Rotation/Scaling), polygons of any size, and the materials' diffuse
colours per polygon (LayerElementMaterial ByPolygon / AllSame). Not kept: textures, UVs, normals (the studio's
look is flat colours anyway), animation, cameras, lights. FBX 7.x (Objects + Connections) and the older 6.x
layout (meshes inside Model blocks) are both read.

    python fbx_ascii.py <in.fbx> <out_dir>        -> <out_dir>/<name>.obj + .mtl
"""
import math
import re
import sys
from pathlib import Path

TOKEN = re.compile(r'\s*(?:(;[^\n]*)|("(?:[^"\\]|\\.)*")|([A-Za-z_|][\w|]*)\s*:|(\*\d+)|(\{)|(\})|(,)|'
                   r'([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|([A-Za-z_][\w.]*))')


def is_ascii_fbx(path):
    """True for a text FBX (starts with a "; FBX" comment); binary ones start with "Kaydara FBX Binary"."""
    try:
        head = Path(path).open("rb").read(64)
    except OSError:
        return False
    return not head.startswith(b"Kaydara FBX Binary") and (b"FBX" in head[:40] or head.lstrip().startswith(b";"))


class Node:
    __slots__ = ("name", "values", "children")

    def __init__(self, name):
        self.name, self.values, self.children = name, [], []

    def find(self, name):
        return next((c for c in self.children if c.name == name), None)

    def all(self, name):
        return [c for c in self.children if c.name == name]

    def array(self, name):
        """Numbers of an array child ("Vertices: *9 { a: ... }") or of its own values."""
        c = self.find(name)
        if c is None:
            return []
        a = c.find("a")
        return [v for v in (a.values if a else c.values) if isinstance(v, (int, float))]

    def props(self):
        """Properties70 / Properties60 -> {name: [values after the 4 type fields]}."""
        out = {}
        for block in ("Properties70", "Properties60"):
            b = self.find(block)
            if b:
                for p in b.children:
                    if p.values and isinstance(p.values[0], str):
                        out[p.values[0]] = [v for v in p.values[1:] if isinstance(v, (int, float))]
        return out


def parse(text):
    """The FBX text -> a Node tree (root's children = the top-level sections)."""
    root = Node("")
    stack, cur = [root], None
    pos, n = 0, len(text)
    while pos < n:
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            pos += 1                                   # something odd: skip a character
            continue
        pos = m.end()
        comment, string, key, star, lb, rb, comma, num, word = m.groups()
        if comment or comma or star:
            continue
        if key is not None:
            cur = Node(key)
            stack[-1].children.append(cur)
        elif lb:
            if cur is None:
                cur = Node("")
                stack[-1].children.append(cur)
            stack.append(cur)
            cur = None
        elif rb:
            if len(stack) > 1:
                stack.pop()
            cur = None
        elif cur is not None:
            if string is not None:
                cur.values.append(string[1:-1])
            elif num is not None:
                cur.values.append(float(num) if any(c in num for c in ".eE") else int(num))
            elif word is not None:
                cur.values.append(word)
    return root


# ---- 4x4 matrices as nested lists (no numpy in the studio's Python)
def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _t(x, y, z):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def _s(x, y, z):
    return [[x, 0, 0, 0], [0, y, 0, 0], [0, 0, z, 0], [0, 0, 0, 1]]


def _r(rx, ry, rz):
    """FBX's default rotation order XYZ (degrees): R = Rz * Ry * Rx."""
    a, b, c = (math.radians(v) for v in (rx, ry, rz))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    rx_ = [[1, 0, 0, 0], [0, ca, -sa, 0], [0, sa, ca, 0], [0, 0, 0, 1]]
    ry_ = [[cb, 0, sb, 0], [0, 1, 0, 0], [-sb, 0, cb, 0], [0, 0, 0, 1]]
    rz_ = [[cc, -sc, 0, 0], [sc, cc, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    return _mul(rz_, _mul(ry_, rx_))


def _apply(m, v):
    x, y, z = v
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


def _vec(p, name, default):
    v = p.get(name) or []
    return tuple(float(x) for x in v[:3]) if len(v) >= 3 else default


def _local(props):
    """A Model's own transform: T * PreRotation * R * S (the pivots/offsets these packs leave at zero)."""
    t = _vec(props, "Lcl Translation", (0.0, 0.0, 0.0))
    r = _vec(props, "Lcl Rotation", (0.0, 0.0, 0.0))
    s = _vec(props, "Lcl Scaling", (1.0, 1.0, 1.0))
    pre = _vec(props, "PreRotation", (0.0, 0.0, 0.0))
    return _mul(_t(*t), _mul(_r(*pre), _mul(_r(*r), _s(*s))))


def _geometric(props):
    t = _vec(props, "GeometricTranslation", (0.0, 0.0, 0.0))
    r = _vec(props, "GeometricRotation", (0.0, 0.0, 0.0))
    s = _vec(props, "GeometricScaling", (1.0, 1.0, 1.0))
    return _mul(_t(*t), _mul(_r(*r), _s(*s)))


def _polygons(idx):
    """PolygonVertexIndex (the last index of each polygon is stored as -(i+1)) -> [[i, j, k...]]."""
    polys, cur = [], []
    for i in idx:
        i = int(i)
        if i < 0:
            cur.append(-i - 1)
            polys.append(cur)
            cur = []
        else:
            cur.append(i)
    if len(cur) >= 3:
        polys.append(cur)
    return polys


def _mesh_from(node):
    """(vertices [(x,y,z)], polygons, material index per polygon or None) of a Geometry / 6.x Model node."""
    v = node.array("Vertices")
    verts = [tuple(v[i:i + 3]) for i in range(0, len(v) - 2, 3)]
    polys = [p for p in _polygons(node.array("PolygonVertexIndex")) if len(p) >= 3 and max(p) < len(verts)]
    mats = None
    lem = node.find("LayerElementMaterial")
    if lem is not None:
        ids = [int(x) for x in lem.array("Materials")]
        mapping = (lem.find("MappingInformationType").values or [""])[0] if lem.find("MappingInformationType") else ""
        if mapping == "AllSame" or len(ids) == 1:
            mats = [ids[0] if ids else 0] * len(polys)
        elif len(ids) >= len(polys):
            mats = ids[:len(polys)]
    return verts, polys, mats


def convert(src, out_dir, name=None):
    """src .fbx (text) -> out_dir/<name>.obj + .mtl. Returns {"obj", "meshes", "faces", "materials", "note"}."""
    src, out_dir = Path(src), Path(out_dir)
    text = src.read_text(encoding="utf-8", errors="replace")
    root = parse(text)
    up = 1
    gs = root.find("GlobalSettings")
    if gs:
        up = int((gs.props().get("UpAxis") or [1])[0])
    objects = root.find("Objects")
    models, geoms, mats = {}, {}, {}
    mat_names = {}
    if objects is not None:
        for c in objects.children:
            if not c.values:
                continue
            oid = c.values[0]
            label = str(c.values[1]) if len(c.values) > 1 else ""
            if c.name == "Model":
                models[oid] = c
            elif c.name == "Geometry":
                geoms[oid] = c
            elif c.name == "Material":
                p = c.props()
                col = _vec(p, "DiffuseColor", None) or _vec(p, "Diffuse", None) or _vec(p, "Color", (0.8, 0.8, 0.8))
                mats[oid] = col
                mat_names[oid] = re.sub(r"\W+", "_", label.split("::")[-1]) or f"mat{len(mat_names)}"
    parent, model_geom, model_mats = {}, {}, {}
    conns = root.find("Connections")
    for c in (conns.children if conns else []):
        if c.name != "C" or len(c.values) < 3:
            continue
        kind, child, par = c.values[0], c.values[1], c.values[2]
        if kind != "OO":
            continue
        if child in models and (par in models or par == 0):
            parent[child] = par
        elif child in geoms and par in models:
            model_geom.setdefault(par, []).append(child)
        elif child in mats and par in models:
            model_mats.setdefault(par, []).append(child)

    def world(mid, seen=()):
        if mid not in models or mid in seen:
            return _t(0, 0, 0)
        m = _local(models[mid].props())
        par = parent.get(mid, 0)
        return _mul(world(par, seen + (mid,)), m) if par in models else m

    out_v, faces, used = [], [], {}
    meshes = 0
    targets = [(mid, gid, geoms[gid]) for mid, gids in model_geom.items() for gid in gids]
    if not targets:                                  # FBX 6.x: the mesh lives inside its Model block
        targets = [(mid, None, node) for mid, node in models.items() if node.find("Vertices") is not None]
    for mid, gid, node in targets:
        verts, polys, pmats = _mesh_from(node)
        if not polys:
            continue
        meshes += 1
        props = models[mid].props() if mid in models else {}
        m = _mul(world(mid), _geometric(props))
        base = len(out_v)
        for v in verts:
            x, y, z = _apply(m, v)
            if up == 2:                              # Z-up file -> OBJ's Y-up
                x, y, z = x, z, -y
            out_v.append((x, y, z))
        mlist = model_mats.get(mid, [])
        for k, poly in enumerate(polys):
            mi = pmats[k] if pmats and k < len(pmats) else 0
            mat = mlist[mi] if 0 <= mi < len(mlist) else (mlist[0] if mlist else None)
            mname = mat_names.get(mat, "default") if mat is not None else "default"
            used[mname] = mats.get(mat, (0.8, 0.8, 0.8)) if mat is not None else (0.8, 0.8, 0.8)
            faces.append((mname, [base + i + 1 for i in poly]))
    if not faces:
        raise ValueError("no meshes found in this FBX")
    name = name or src.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    obj, mtl = out_dir / f"{name}.obj", out_dir / f"{name}.mtl"
    lines = [f"# converted from {src.name} (ASCII FBX) by the studio", f"mtllib {mtl.name}", f"o {name}"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in out_v]
    cur = None
    for mname, idx in faces:
        if mname != cur:
            lines.append(f"usemtl {mname}")
            cur = mname
        lines.append("f " + " ".join(str(i) for i in idx))
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mtl.write_text("".join(f"newmtl {n}\nKd {r:.4f} {g:.4f} {b:.4f}\nKa 0 0 0\nKs 0.1 0.1 0.1\nd 1\nillum 1\n\n"
                           for n, (r, g, b) in used.items()), encoding="utf-8")
    return {"obj": str(obj), "meshes": meshes, "faces": len(faces), "materials": len(used),
            "note": f"converted from text FBX: {meshes} mesh(es), {len(faces)} faces, {len(used)} colour(s)"}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    print(convert(sys.argv[1], sys.argv[2]))
