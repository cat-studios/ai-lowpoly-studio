"""
Convert .mdl game models to OBJ (+ MTL + PNG textures) so Blender can import them. Pure Python, stdlib only.

Three engines use the .mdl extension. The header tells them apart:

  Quake 1      "IDPO" version 6      one file; skins are 8-bit and need a palette (palette.lmp, found in the pack if present)
  Half-Life 1  "IDST" version 10     one file (textures may be in "<name>T.mdl"); the palette is stored with each texture
  Source       "IDST" version 44-49  geometry is split across .mdl (bones, body parts), .vvd (vertices) and .vtx
               (triangles); textures are only material NAMES (the pictures are .vtf files), so parts come out grey

    python pipeline/mdl_convert.py model.mdl out_dir

All three use x forward, y left, z up; they are turned into Blender's x right, y forward, z up.
Only the first frame (Quake) and the default model of each body part (Half-Life, Source) are exported.

Written from the published file layouts and checked against files made by test_mdl_convert.py. Not yet checked
against real game files.
"""
import math
import struct
import sys
import zlib
from pathlib import Path

IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


class MdlError(Exception):
    pass


def flavour_of(buf):
    if len(buf) < 8:
        raise MdlError("file is too small to be a model")
    magic = bytes(buf[:4])
    version = struct.unpack_from("<i", buf, 4)[0]
    if magic == b"IDPO" and version == 6:
        return "quake"
    if magic == b"IDST" and version == 10:
        return "goldsrc"
    if magic == b"IDST" and 40 <= version <= 60:
        return "source"
    raise MdlError(f"not a Quake, Half-Life or Source model (header {magic!r}, version {version})")


def _check(cond, what):
    if not cond:
        raise MdlError(f"file looks damaged or unusual ({what})")


# ----------------------------------------------------------------------------- output
def _png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "model"


def write_obj(out_dir, name, parts):
    """parts: [{"name", "verts": [(x,y,z)], "uvs": [(u,v)], "faces": [((vi,ti),(vi,ti),(vi,ti))],
                "texture": (w, h, rgb) or None, "color": (r,g,b)}]
    -> out_dir/<name>.obj, .mtl and one .png per textured part."""
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _safe(name)
    lines = [f"# converted from {base}.mdl by pipeline/mdl_convert.py", f"mtllib {base}.mtl"]
    mtl, vo, to, textures = [], 0, 0, 0
    for i, p in enumerate(parts):
        mat = f"{base}_{i}"
        if p.get("texture"):
            w, h, rgb = p["texture"]
            (out_dir / f"{mat}.png").write_bytes(_png(w, h, rgb))
            textures += 1
            mtl += [f"newmtl {mat}", "Kd 1 1 1", f"map_Kd {mat}.png", ""]
        else:
            r, g, b = p.get("color", (0.6, 0.6, 0.6))
            mtl += [f"newmtl {mat}", f"Kd {r:.3f} {g:.3f} {b:.3f}", ""]
        lines.append(f"g {mat}")
        lines.append(f"usemtl {mat}")
        for x, y, z in p["verts"]:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for u, v in p["uvs"]:
            lines.append(f"vt {u:.6f} {v:.6f}")
        for corners in p["faces"]:
            lines.append("f " + " ".join(f"{vo + vi + 1}/{to + ti + 1}" for vi, ti in corners))
        vo += len(p["verts"])
        to += len(p["uvs"])
    obj = out_dir / f"{base}.obj"
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / f"{base}.mtl").write_text("\n".join(mtl) + "\n", encoding="utf-8")
    return {"obj": obj, "textures": textures, "parts": len(parts)}


def _to_blender(x, y, z):
    """Valve/Quake axes (x forward, y left, z up) -> Blender (x right, y forward, z up)."""
    return (-y, x, z)


def _indexed_rgb(idx, w, h, pal):
    if pal is None:                       # no palette available: a grey ramp, so the shapes still read
        pal = bytes(v for i in range(256) for v in (i, i, i))
    out = bytearray(w * h * 3)
    for i, c in enumerate(bytes(idx[:w * h])):
        out[3 * i:3 * i + 3] = pal[3 * c:3 * c + 3]
    return (w, h, bytes(out))


# ----------------------------------------------------------------------------- Quake 1 (IDPO v6)
def parse_quake(buf, palette=None):
    scale = struct.unpack_from("<3f", buf, 8)
    origin = struct.unpack_from("<3f", buf, 20)
    numskins, skinw, skinh, numverts, numtris, numframes = struct.unpack_from("<6i", buf, 48)
    _check(0 < numverts < 65536 and 0 < numtris < 200000 and 0 < skinw <= 4096 and 0 < skinh <= 4096
           and numframes >= 1, "quake counts")
    off = 84                                    # header size

    skins = []
    for _ in range(numskins):
        group = struct.unpack_from("<i", buf, off)[0]
        off += 4
        if group == 0:
            skins.append(bytes(buf[off:off + skinw * skinh]))
            off += skinw * skinh
        else:
            nb = struct.unpack_from("<i", buf, off)[0]
            off += 4 + 4 * nb                   # count + one time per skin
            for _ in range(nb):
                skins.append(bytes(buf[off:off + skinw * skinh]))
                off += skinw * skinh

    st = []
    for _ in range(numverts):
        st.append(struct.unpack_from("<3i", buf, off))     # onseam, s, t
        off += 12
    tris = []
    for _ in range(numtris):
        front, a, b, c = struct.unpack_from("<4i", buf, off)
        tris.append((front, (a, b, c)))
        off += 16

    # first frame only. A group frame lists its sub-frame count, bounds and times before the sub-frames.
    ftype = struct.unpack_from("<i", buf, off)[0]
    off += 4
    if ftype != 0:
        nf = struct.unpack_from("<i", buf, off)[0]
        off += 4 + 8 + 4 * nf
    off += 8 + 16                              # bounds + frame name
    verts = []
    for _ in range(numverts):
        vx, vy, vz, _n = struct.unpack_from("<4B", buf, off)
        verts.append(_to_blender(vx * scale[0] + origin[0], vy * scale[1] + origin[1], vz * scale[2] + origin[2]))
        off += 4

    tex = _indexed_rgb(skins[0], skinw, skinh, palette) if skins else None
    uvs, faces = [], []
    for front, tri in tris:
        corners = []
        for vi in tri:
            onseam, s, t = st[vi]
            if not front and onseam:           # back-facing triangles use the far half of the skin
                s += skinw // 2
            uvs.append(((s + 0.5) / skinw, 1 - (t + 0.5) / skinh))
            corners.append((vi, len(uvs) - 1))
        faces.append(tuple(corners))
    return [{"name": "body", "verts": verts, "uvs": uvs, "faces": faces, "texture": tex}]


def quake_palette(search_root):
    """palette.lmp (768 bytes) from the pack, if it has one (Quake keeps its palette in the game data)."""
    if not search_root or not Path(search_root).exists():
        return None
    for p in Path(search_root).rglob("palette.lmp"):
        data = p.read_bytes()
        if len(data) == 768:
            return data
    return None


# ----------------------------------------------------------------------------- Half-Life 1 / GoldSrc (IDST v10)
# Every offset inside a GoldSrc studio file is measured from the start of the file.
def _angle_matrix(pitch, yaw, roll):
    sp, cp, sy, cy, sr, cr = math.sin(pitch), math.cos(pitch), math.sin(yaw), math.cos(yaw), math.sin(roll), math.cos(roll)
    return [[cp * cy, sr * sp * cy + cr * -sy, cr * sp * cy + -sr * -sy],
            [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy + -sr * cy],
            [-sp, sr * cp, cr * cp]]


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mat_vec(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def goldsrc_bones(buf, boneindex, numbones):
    """Each bone's rest transform in model space: [(rotation 3x3, translation)]."""
    world = []
    for i in range(numbones):
        base = boneindex + i * 112
        parent = struct.unpack_from("<i", buf, base + 32)[0]
        value = struct.unpack_from("<6f", buf, base + 64)      # x, y, z, then pitch, yaw, roll
        local_r = _angle_matrix(value[3], value[4], value[5])
        local_t = value[0:3]
        if 0 <= parent < i:
            pr, pt = world[parent]
            lt = _mat_vec(pr, local_t)
            world.append((_mat_mul(pr, local_r), tuple(pt[k] + lt[k] for k in range(3))))
        else:
            world.append((local_r, local_t))
    return world


def _goldsrc_textures(buf, path, numtextures, textureindex):
    tbuf = buf
    if numtextures == 0:                       # textures live in <name>T.mdl
        tfile = Path(path).with_name(Path(path).stem + "T.mdl")
        tbuf = tfile.read_bytes() if tfile.exists() else None
    out = []
    for i in range(numtextures):
        base = textureindex + i * 80
        name = bytes(buf[base:base + 64]).split(b"\0")[0].decode("latin-1", "replace")
        w, h, data = struct.unpack_from("<iii", buf, base + 68)  # width, height, offset of the pixels
        if tbuf is None or w <= 0 or h <= 0:
            out.append((name, None))
            continue
        pix = bytes(tbuf[data:data + w * h])
        pal = bytes(tbuf[data + w * h:data + w * h + 768])
        out.append((name, _indexed_rgb(pix, w, h, pal) if len(pal) == 768 else None))
    return out


def parse_goldsrc(buf, path):
    numbones, boneindex = struct.unpack_from("<ii", buf, 140)
    numtextures, textureindex = struct.unpack_from("<ii", buf, 180)
    numskinref, numskinfam, skinindex = struct.unpack_from("<iii", buf, 192)
    numbodyparts, bodypartindex = struct.unpack_from("<ii", buf, 204)
    _check(0 < numbodyparts < 256 and 0 <= numbones < 256, "goldsrc counts")

    textures = _goldsrc_textures(buf, path, numtextures, textureindex)
    skinref = struct.unpack_from(f"<{numskinref}h", buf, skinindex) if numskinref else ()
    bones = goldsrc_bones(buf, boneindex, numbones)

    parts = []
    for k in range(numbodyparts):
        model = struct.unpack_from("<i", buf, bodypartindex + k * 76 + 72)[0]   # default model, absolute offset
        nummesh, meshindex = struct.unpack_from("<ii", buf, model + 72)
        numverts, vertinfoindex, vertindex = struct.unpack_from("<iii", buf, model + 80)
        bone_of = bytes(buf[vertinfoindex:vertinfoindex + numverts])           # one bone number per vertex
        local = []
        for v in range(numverts):
            p = struct.unpack_from("<3f", buf, vertindex + v * 12)
            b = bone_of[v] if v < len(bone_of) else 0
            r, t = bones[b] if b < len(bones) else (IDENTITY, (0.0, 0.0, 0.0))
            pw = _mat_vec(r, p)
            local.append(_to_blender(pw[0] + t[0], pw[1] + t[1], pw[2] + t[2]))

        for m in range(nummesh):                  # every mesh of the body part = one texture
            mesh = meshindex + m * 28             # absolute offset of this mesh
            numtris, triindex, skin = struct.unpack_from("<iii", buf, mesh)
            tex_index = skinref[skin] if skin < len(skinref) else skin
            tex_name, tex = textures[tex_index] if 0 <= tex_index < len(textures) else ("", None)
            verts, uvs, faces, seen = [], [], [], {}

            def corner(vidx, s, t):
                key = (vidx, s, t)
                if key not in seen:
                    seen[key] = len(verts)
                    verts.append(local[vidx] if vidx < len(local) else (0.0, 0.0, 0.0))
                    if tex:
                        uvs.append((s / tex[0], 1 - t / tex[1]))
                    else:
                        uvs.append((0.0, 0.0))
                return (seen[key], len(uvs) - 1)

            cmd = triindex
            for _ in range(100000):           # triangle commands until a zero count
                count = struct.unpack_from("<h", buf, cmd)[0]
                cmd += 2
                if count == 0:
                    break
                n = abs(count)
                cmds = []
                for _v in range(n):
                    vi, _ni, s, t = struct.unpack_from("<4h", buf, cmd)
                    cmd += 8
                    cmds.append(corner(vi, s, t))
                if count < 0:                 # triangle fan
                    for i in range(1, n - 1):
                        faces.append((cmds[0], cmds[i], cmds[i + 1]))
                else:                         # triangle strip (every other triangle flips winding)
                    for i in range(n - 2):
                        faces.append((cmds[i], cmds[i + 1], cmds[i + 2]) if i % 2 == 0
                                     else (cmds[i + 1], cmds[i], cmds[i + 2]))
            else:
                raise MdlError("goldsrc triangle commands never end")
            if faces:
                parts.append({"name": tex_name or f"part{k}_mesh{m}", "verts": verts, "uvs": uvs,
                              "faces": faces, "texture": tex})
    _check(parts, "no triangles found in the Half-Life model")
    return parts


# ----------------------------------------------------------------------------- Source (IDST v44-49 + VVD + VTX)
def parse_source(buf, path):
    numbodyparts, bodypartindex = struct.unpack_from("<ii", buf, 232)
    _check(0 < numbodyparts < 256, "source body parts")
    p = Path(path)
    vvd_path = p.with_suffix(".vvd")
    _check(vvd_path.exists(), "missing .vvd next to the model")
    vvd = vvd_path.read_bytes()
    _check(vvd[:4] == b"IDSV", ".vvd header")
    vdata = struct.unpack_from("<i", vvd, 56)[0]       # vertex data start (after the fixup table)

    vtx = None
    for suffix in (".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx"):
        cand = p.with_name(p.stem + suffix)
        if cand.exists():
            vtx = cand.read_bytes()
            break
    _check(vtx is not None, "missing .vtx next to the model")
    vtx_bodyparts = struct.unpack_from("<i", vtx, 32)[0]  # offset of the body part list in the .vtx

    parts = []
    for k in range(numbodyparts):
        bp = bodypartindex + k * 16                 # body part offsets are relative to the body part
        model = bp + struct.unpack_from("<i", buf, bp + 12)[0]    # its default model
        nummesh, meshindex = struct.unpack_from("<ii", buf, model + 72)
        numverts, vertexindex = struct.unpack_from("<ii", buf, model + 80)
        model_base = vertexindex // 48                 # first vertex of this model in the .vvd
        # .vtx side: body part -> model -> LOD 0 -> meshes (offsets relative to each struct)
        vbp = vtx_bodyparts + k * 8
        vmodel = vbp + struct.unpack_from("<i", vtx, vbp + 4)[0]
        vlod = vmodel + struct.unpack_from("<i", vtx, vmodel + 4)[0]
        vmesh_count, vmesh_off = struct.unpack_from("<ii", vtx, vlod)
        vmeshes = vlod + vmesh_off
        for m in range(min(nummesh, vmesh_count)):
            mesh = model + meshindex + m * 116
            vertex_offset = struct.unpack_from("<i", buf, mesh + 12)[0]   # first vertex of the mesh, within the model
            vmesh = vmeshes + m * 9
            nsg = struct.unpack_from("<i", vtx, vmesh)[0]
            sg_first = vmesh + struct.unpack_from("<i", vtx, vmesh + 4)[0]
            verts, uvs, faces = [], [], []
            for g in range(nsg):
                sg = sg_first + g * 25
                nv, vo, ni, io = struct.unpack_from("<iiii", vtx, sg)
                idx = struct.unpack_from(f"<{ni}H", vtx, sg + io)
                base_vert = len(verts)
                for i in range(nv):
                    orig = struct.unpack_from("<H", vtx, sg + vo + i * 9 + 4)[0]  # vertex index within the mesh
                    vv = model_base + vertex_offset + orig
                    x, y, z = struct.unpack_from("<3f", vvd, vdata + vv * 48 + 16)
                    u, w = struct.unpack_from("<2f", vvd, vdata + vv * 48 + 40)
                    verts.append(_to_blender(x, y, z))
                    uvs.append((u, 1 - w))
                for t in range(0, ni - 2, 3):
                    faces.append(tuple((base_vert + idx[t + j],) * 2 for j in range(3)))
            if faces:
                parts.append({"name": f"part{k}_mesh{m}", "verts": verts, "uvs": uvs, "faces": faces,
                              "texture": None, "color": (0.62, 0.62, 0.66)})
    _check(parts, "no triangles found in the Source model")
    return parts


# ----------------------------------------------------------------------------- entry point
def convert(mdl_path, out_dir, search_root=None, name=None):
    """Convert one .mdl. Returns {"flavour", "obj", "textures", "parts", "note"}."""
    p = Path(mdl_path)
    buf = p.read_bytes()
    kind = flavour_of(buf)
    if kind == "quake":
        pal = quake_palette(search_root)
        parts = parse_quake(buf, pal)
        note = "Quake 1 model" + ("" if pal else " - no palette.lmp in the pack, so textures are grey")
    elif kind == "goldsrc":
        parts = parse_goldsrc(buf, p)
        note = "Half-Life model"
    else:
        parts = parse_source(buf, p)
        note = "Source engine model - geometry only (its textures are .vtf files, not in the model)"
    out = write_obj(Path(out_dir), name or p.stem, parts)
    return {"flavour": kind, "obj": str(out["obj"]), "textures": out["textures"], "parts": out["parts"], "note": note}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: mdl_convert.py model.mdl out_dir")
    print(convert(sys.argv[1], sys.argv[2]))
