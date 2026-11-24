"""
Imported real assets: free 3D model packs you downloaded (.zip files with OBJ, FBX, BLEND or MDL models,
folders inside the zip are fine). Kept apart from the AI-made props in assets/props/.

    python pipeline/imported.py import <pack.zip> [--pack NAME] [--license TEXT]
    python pipeline/imported.py list
    python pipeline/imported.py delete <pack-id>

Scenes and cast members call match() FIRST. Only when no imported model matches does the caller generate
its own prop (propgen). Matching is by words: a model called "pine_tree.fbx" or sitting in a folder called
"Trees/" matches a prop named "tree". Rename files or folders to steer it.

MDL: Blender has no MDL importer, so MDL models are listed as "needs conversion" (convert to OBJ/FBX first).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mdl_convert  # noqa: E402
import progress  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "assets" / "imported"
PACKS = LIB / "packs"
INDEX = LIB / "index.json"
UPLOADS = LIB / ".uploads"
PROBE = Path(__file__).resolve().parent / "imported_probe.py"
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe")
MODEL_FORMATS = {".obj": "obj", ".fbx": "fbx", ".blend": "blend", ".mdl": "mdl"}
TEXTURE_EXT = {".mtl", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds"}   # textures and OBJ material libraries
# Source-engine models need these companion files next to the .mdl (".dx90.vtx" also ends in .vtx)
COMPANION_EXT = {".vvd", ".vtx", ".phy", ".ani", ".lmp"}    # .lmp: Quake's palette.lmp
MAX_TOTAL_BYTES = 3 * 1024 ** 3
DEFAULT_LICENSE = "Free for commercial use (declared on import)"
# words that describe the file type or folder layout rather than the thing itself
NOISE = {"a", "an", "the", "of", "with", "and", "low", "poly", "model", "models", "pack", "free", "obj", "fbx",
         "blend", "mdl", "texture", "textures", "mesh", "meshes", "prop", "props", "asset", "assets", "file",
         "files", "tex", "mat", "materials", "material", "source", "export", "pc"}
UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')


# ----------------------------------------------------------------------------- names and words
def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:48] or "pack"


def words(text):
    """'PineTree_01.fbx' / 'Trees/Big Oak' -> {'pine', 'tree', '01', 'big', 'oak'} (lower case, singular-ish)."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or ""))
    text = re.sub(r"([a-zA-Z])([0-9])", r"\1 \2", text)            # "Donut1" -> "Donut 1"
    out = set()
    for w in re.split(r"[^a-zA-Z0-9]+", text.lower()):
        if not w or w in NOISE:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _clean_member(name):
    """A safe relative path inside the pack folder, or None (absolute paths, '..', hidden/system files)."""
    p = PurePosixPath(str(name).replace("\\", "/"))
    if p.is_absolute() or any(part in ("..", "") for part in p.parts) or re.match(r"^[A-Za-z]:", str(name)):
        return None
    parts = [UNSAFE.sub("_", part).strip() for part in p.parts]
    if not parts or any(part.startswith(".") or part == "__MACOSX" or not part for part in parts):
        return None
    return PurePosixPath(*parts)


# ----------------------------------------------------------------------------- index
def load_index():
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {"packs": []}


def save_index(idx):
    LIB.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    tmp.replace(INDEX)


def packs():
    return load_index()["packs"]


# ----------------------------------------------------------------------------- MDL flavours
def mdl_flavour(path):
    """Which engine an .mdl came from, read from its header (the file extension is the same for all of them)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return "unreadable MDL"
    magic, version = head[:4], int.from_bytes(head[4:8], "little") if len(head) == 8 else -1
    if magic == b"IDPO":
        return f"Quake 1 MDL (version {version})"
    if magic == b"IDST":
        return "Half-Life 1 / GoldSrc MDL (version 10)" if version == 10 else f"Source engine MDL (version {version})"
    if magic == b"IDSQ":
        return "Source engine animation file (not a model)"
    return "unknown MDL format (not Quake, Half-Life or Source)"


# ----------------------------------------------------------------------------- Blender probe
def _probe(models, log):
    """Measure obj/fbx/blend files in Blender. Returns {path_str: result}."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "in.json").write_text(json.dumps([{"path": str(p), "format": f} for p, f in models]), encoding="utf-8")
        cmd = [BLENDER, "-b", "--factory-startup", "--python", str(PROBE), "--", str(tmp / "in.json"),
               str(tmp / "out.json")]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        for line in (r.stdout or "").splitlines():
            if line.startswith("[probe]"):
                log(line)
        out = tmp / "out.json"
        if r.returncode != 0 or not out.exists():
            raise SystemExit("Blender couldn't measure the models (is Blender installed?): " + (r.stderr or "")[-400:])
        return json.loads(out.read_text(encoding="utf-8-sig"))


# ----------------------------------------------------------------------------- pictures for the Imported tab
PREVIEWS = LIB / "previews"


def make_previews(models, log=print, only_missing=True):
    """A still picture of each model (Blender, one session for all of them) -> assets/imported/previews/<id>.png.
    Records get rec["preview"] = "/impimg/<id>.png" when a picture exists."""
    todo = [m for m in models if not (only_missing and (PREVIEWS / f"{m['id']}.png").exists())]
    if not todo:
        return
    progress.report(0.9, f"Drawing {len(todo)} picture(s) of the models")
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "in.json").write_text(json.dumps([{"id": m["id"], "path": str(ROOT / m["file"]), "format": m["format"]}
                                                 for m in todo]), encoding="utf-8")
        cmd = [BLENDER, "-b", "--factory-startup", "--python", str(PIPE_DIR / "imported_preview.py"), "--",
               str(tmp / "in.json"), str(PREVIEWS)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        for line in (r.stdout or "").splitlines():
            if line.startswith("[preview]"):
                log(line)
    for m in models:
        if (PREVIEWS / f"{m['id']}.png").exists():
            m["preview"] = f"/impimg/{m['id']}.png"


def previews_all():
    """Pictures for every ready model that has none yet (also used by `imported.py previews`)."""
    idx = load_index()
    models = [m for p in idx["packs"] for m in p["models"] if m.get("status") == "ok"]
    make_previews(models, print)
    for p in idx["packs"]:
        for m in p["models"]:
            if (PREVIEWS / f"{m['id']}.png").exists():
                m["preview"] = f"/impimg/{m['id']}.png"
    save_index(idx)


PIPE_DIR = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------- import
def import_zip(zip_path, pack_name=None, license_text=None, log=print, source_name=None):
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise SystemExit(f"{zip_path.name} is not a zip file")
    name = (pack_name or zip_path.stem).strip()[:80] or "Pack"
    idx = load_index()
    base = slug(name)
    taken = {p["id"] for p in idx["packs"]}
    pid, n = base, 2
    while pid in taken or (PACKS / pid).exists():
        pid, n = f"{base}_{n}", n + 1
    dest = PACKS / pid

    progress.report(0.02, "Reading the zip")
    kept_models = kept_other = skipped = 0
    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise SystemExit("this zip unpacks to more than 3 GB - split the pack")
        for i, info in enumerate(infos):
            rel = _clean_member(info.filename)
            ext = Path(info.filename).suffix.lower()
            if rel is None or (ext not in MODEL_FORMATS and ext not in TEXTURE_EXT and ext not in COMPANION_EXT):
                skipped += 1
                continue
            target = (dest / rel).resolve()
            if dest.resolve() not in target.parents:       # belt and braces against path tricks
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if ext in MODEL_FORMATS:
                kept_models += 1
            else:
                kept_other += 1
            progress.report(0.02 + 0.2 * (i + 1) / max(1, len(infos)), "Extracting")

    found = sorted(p for p in dest.rglob("*") if p.is_file() and p.suffix.lower() in MODEL_FORMATS)
    if not found:
        shutil.rmtree(dest, ignore_errors=True)
        raise SystemExit("no OBJ, FBX, BLEND or MDL models in this zip")
    log(f"[import] {pack_name or zip_path.stem}: {len(found)} models, {kept_other} textures kept, "
        f"{skipped} other files ignored")

    # MDL files are converted to OBJ first (pipeline/mdl_convert.py), then measured like any other model
    converted = {}                                   # original .mdl path -> (obj path or None, note)
    for p in found:
        if MODEL_FORMATS[p.suffix.lower()] != "mdl":
            continue
        progress.report(0.22, f"Converting {p.name}")
        try:
            res = mdl_convert.convert(p, dest / "_converted" / slug(p.stem), search_root=dest)
            converted[str(p)] = (Path(res["obj"]), f"{res['note']}; {res['textures']} texture(s)")
        except Exception as exc:                    # a damaged or unsupported file must not stop the pack
            converted[str(p)] = (None, f"could not convert: {str(exc)[:160] or exc.__class__.__name__}")
            log(f"[import] {p.name}: {converted[str(p)][1]}")

    measurable = []
    for p in found:
        fmt = MODEL_FORMATS[p.suffix.lower()]
        if fmt == "mdl":
            if converted[str(p)][0] is not None:
                measurable.append((converted[str(p)][0], "obj"))
        else:
            measurable.append((p, fmt))
    measured = {}
    if measurable:
        progress.report(0.3, "Measuring models in Blender")
        measured = _probe(measurable, log)

    models = []
    for p in found:
        fmt = MODEL_FORMATS[p.suffix.lower()]
        rel = p.relative_to(dest)
        rec = {"id": f"{pid}_{slug(p.stem)}_{hashlib.md5(str(rel).encode('utf-8')).hexdigest()[:6]}",
               "name": p.stem.replace("_", " "),
               "file": str((PACKS / pid / rel).relative_to(ROOT)).replace("\\", "/"), "format": fmt,
               "folder": "/".join(rel.parts[:-1]), "size_mb": round(p.stat().st_size / 1048576, 2),
               "tags": sorted(words(p.stem) | words("/".join(rel.parts[:-1]))),
               "height": None, "width": None, "depth": None}
        if fmt == "mdl":
            obj, note = converted[str(p)]
            rec["flavour"] = mdl_flavour(p)
            if obj is None:
                rec.update(status="failed", note=note)
                models.append(rec)
                continue
            # the model Blender loads is the converted OBJ; the original .mdl stays in the pack
            rec.update(source_file=rec["file"], file=str(obj.relative_to(ROOT)).replace("\\", "/"), format="obj",
                       note=f"{rec['flavour']} - {note}")
            m = measured.get(str(obj), {})
        else:
            m = measured.get(str(p), {})
        if m.get("ok"):
            rec.update(status="ok", height=m["height"], width=m["width"], depth=m["depth"])
        else:
            rec.update(status="failed", note=m.get("error") or rec.get("note") or "could not be measured")
        models.append(rec)

    make_previews([m for m in models if m["status"] == "ok"], log)
    pack = {"id": pid, "name": name, "license": (license_text or DEFAULT_LICENSE).strip()[:200],
            "source": source_name or zip_path.name, "added": time.time(), "skipped": skipped, "models": models}
    idx["packs"].append(pack)
    save_index(idx)
    progress.report(1.0, "Done")
    return pack


def delete_pack(pid):
    idx = load_index()
    pack = next((p for p in idx["packs"] if p["id"] == pid), None)
    if not pack:
        raise ValueError(f"no pack '{pid}'")
    folder = PACKS / pid
    if folder.exists():                    # never hard-delete: the pack folder goes to .trash
        (PACKS / ".trash").mkdir(parents=True, exist_ok=True)
        folder.replace(PACKS / ".trash" / f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}")
    idx["packs"] = [p for p in idx["packs"] if p["id"] != pid]
    save_index(idx)
    return pack


# ----------------------------------------------------------------------------- lookup (used by scenes and cast)
def _best(kind, looks=""):
    kt = words(kind)
    if not kt:
        return None, 0.0
    lt = words(looks)
    best, best_key = None, None
    for pack in packs():
        for m in pack.get("models", []):
            if m.get("status") != "ok":
                continue
            tags = set(m.get("tags") or [])
            hit = kt & tags
            ratio = len(hit) / len(kt)
            if ratio < 0.5:                 # at least half of the prop's words must be in the model's name/folders
                continue
            key = (ratio, len(lt & tags), -len(tags), m["id"])
            if best_key is None or key > best_key:
                best, best_key = (pack, m), key
    return best, (best_key[0] if best_key else 0.0)


def match(kind, looks="", setting=""):
    """The imported model for `kind`, as a prop definition (same shape as propgen's), or None."""
    hit, _ = _best(kind, looks)
    if not hit:
        return None
    pack, m = hit
    return match_model(pack, m, kind, looks)


def model_def(model_id, kind="", looks=""):
    """A prop definition for one specific imported model (chosen by hand in the video editor)."""
    for pack in packs():
        for m in pack.get("models", []):
            if m["id"] == model_id and m.get("status") == "ok":
                return match_model(pack, m, kind, looks)
    return None


def match_model(pack, m, kind, looks=""):
    height = m.get("height") if m.get("height") and 0.005 <= m["height"] <= 12 else 1.2
    width = max(m.get("width") or 0.0, m.get("depth") or 0.0, 0.3)
    return {"kind": kind, "looks": looks, "by": "imported", "source": "imported", "name": m["name"],
            "pack": pack["name"], "license": pack.get("license", ""),
            "model": {"id": m["id"], "file": m["file"], "format": m["format"]},
            "height": round(height, 3), "width": round(width, 3), "radius": round(width / 2, 2),
            "place": "near", "parts": []}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import")
    p_imp.add_argument("zip")
    p_imp.add_argument("--pack")
    p_imp.add_argument("--license")
    p_imp.add_argument("--source", help="the zip's original file name (shown on the Assets page)")
    sub.add_parser("list")
    sub.add_parser("previews", help="draw a picture for every model that has none")
    p_del = sub.add_parser("delete")
    p_del.add_argument("pack_id")
    a = ap.parse_args()
    if a.cmd == "import":
        pack = import_zip(a.zip, a.pack, a.license, source_name=a.source)
        ok = sum(1 for m in pack["models"] if m["status"] == "ok")
        print(f"IMPORTED={pack['id']} ok={ok} total={len(pack['models'])}", flush=True)
    elif a.cmd == "list":
        print(json.dumps(packs(), indent=1))
    elif a.cmd == "previews":
        previews_all()
        print("PREVIEWS=done", flush=True)
    elif a.cmd == "delete":
        delete_pack(a.pack_id)
        print(f"DELETED={a.pack_id}", flush=True)
