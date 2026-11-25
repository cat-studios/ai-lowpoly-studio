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


def edit_model(mid, name=None, description=None, category=None):
    """Assets -> Imported -> ✏️: your own name, description and category for a model (they win over the file name,
    the picture model's naming and the AI's categories; matching uses the new name's words too)."""
    idx = load_index()
    m = next((x for p in idx["packs"] for x in p.get("models", []) if x["id"] == mid), None)
    if not m:
        raise ValueError("no such model")
    if name is not None and str(name).strip() and str(name).strip() != m.get("name"):
        m.setdefault("original_name", m.get("name"))
        m["name"] = re.sub(r"\s+", " ", str(name)).strip()[:60]
        m["tags"] = sorted(set(m.get("tags") or []) | words(m["name"]))
    if description is not None:
        m["description"] = re.sub(r"\s+", " ", str(description)).strip()[:300]
    if category is not None:
        c = re.sub(r"\s+", " ", str(category)).strip()[:30]
        if c:
            m["category"] = c[:1].upper() + c[1:]
        else:
            m.pop("category", None)             # back to the automatic category
    save_index(idx)
    return m


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


def _blank_png(path):
    """True for a PNG that is one flat colour (a model that rendered invisible). Stdlib only: the decompressed
    scanlines of a flat picture hold just a few distinct byte values, whatever filter the encoder used."""
    import struct
    import zlib
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    pos, idat = 8, b""
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return False
    return len(set(raw)) <= 6


def previews_all():
    """Pictures for every ready model that has none yet (also used by `imported.py previews`)."""
    idx = load_index()
    models = [m for p in idx["packs"] for m in p["models"] if m.get("status") == "ok"]
    # blank pictures count as missing: models whose materials came in see-through (blender_models.fix_invisible)
    # rendered an empty white picture (not byte-identical files - their metadata differs - so look at the pixels)
    blank = [PREVIEWS / f"{m['id']}.png" for m in models if _blank_png(PREVIEWS / f"{m['id']}.png")]
    for pv in blank:
        pv.unlink()                                   # redrawn just below (a picture, not a user asset)
    if blank:
        print(f"[import] {len(blank)} blank picture(s) will be drawn again")
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

    # the same model file twice (already imported, or twice in this zip) is skipped: identical bytes = same model
    known = known_hashes(idx)
    fresh, dupes = [], 0
    for p in found:
        h = file_hash(p)
        if h in known:
            (dest / "_duplicates").mkdir(exist_ok=True)       # kept aside, not deleted
            p.replace(dest / "_duplicates" / p.name)
            dupes += 1
            log(f"[import] {p.name}: already imported as '{known[h]}' - skipped")
            continue
        known[h] = p.stem
        fresh.append((p, h))
    # the same model saved in several formats (Female_Hairstyle_1 .fbx + .blend + .obj): one is enough
    by_stem = {}
    for p, h in fresh:
        by_stem.setdefault(p.stem.lower(), []).append((p, h))
    fresh = []
    for group in by_stem.values():
        fmts = [MODEL_FORMATS[p.suffix.lower()] for p, _ in group]
        if len(group) > 1 and len(set(fmts)) == len(fmts):
            group.sort(key=lambda ph: FORMAT_PREF.index(MODEL_FORMATS[ph[0].suffix.lower()]))
            for p, _ in group[1:]:
                (dest / "_duplicates").mkdir(exist_ok=True)
                p.replace(dest / "_duplicates" / p.name)
                dupes += 1
            group = group[:1]
        fresh += group
    found = sorted(p for p, _ in fresh)
    hashes = {str(p): h for p, h in fresh}
    if dupes:
        log(f"[import] {dupes} duplicate model(s) skipped")
    if not found:
        raise SystemExit("every model in this zip is already imported")

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
               "height": None, "width": None, "depth": None, "hash": hashes.get(str(p))}
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
    progress.report(0.97, "Sorting the models into categories")
    try:
        import settings as S
        ai_categorize(S.load_settings().get("ollama"), log)      # names the word list doesn't know
    except Exception as exc:
        log(f"[import] categories: AI skipped ({exc.__class__.__name__}) - sorted by name only")
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


def delete_models(ids):
    """Remove single models: their files (same name, any extension: .obj + .mtl...) and preview move to
    packs/.trash/models-<stamp>/ (never hard-deleted); they leave the index. Shared textures stay. Returns the count."""
    ids = set(ids)
    idx = load_index()
    dest = PACKS / ".trash" / f"models-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 0
    for pack in idx["packs"]:
        keep = []
        for m in pack.get("models", []):
            if m["id"] not in ids:
                keep.append(m)
                continue
            f = ROOT / m["file"]
            # only this model's own file (+ an OBJ's .mtl): the same name in another format may be the copy we keep
            own = [f] + ([f.with_suffix(".mtl")] if f.suffix.lower() == ".obj" else [])
            if m.get("source_file"):
                own.append(ROOT / m["source_file"])
            for sib in [x for x in own if x.exists()]:
                rel = sib.relative_to(PACKS) if PACKS in sib.parents else Path(pack["id"]) / sib.name
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                sib.replace(dest / rel)
            pv = PREVIEWS / f"{m['id']}.png"
            if pv.exists():
                (dest / "previews").mkdir(parents=True, exist_ok=True)
                pv.replace(dest / "previews" / pv.name)
            n += 1
        pack["models"] = keep
    save_index(idx)
    return n


# ----------------------------------------------------------------------------- duplicates
def file_hash(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _model_file(m):
    return ROOT / (m.get("source_file") or m["file"])     # an MDL's original, not its converted OBJ


def known_hashes(idx):
    """hash -> model name for everything imported (hashes worked out and stored for older models)."""
    out, changed = {}, False
    for pack in idx["packs"]:
        for m in pack.get("models", []):
            if not m.get("hash"):
                f = _model_file(m)
                if not f.exists():
                    continue
                m["hash"], changed = file_hash(f), True
            out.setdefault(m["hash"], m["name"])
    if changed:
        save_index(idx)
    return out


FORMAT_PREF = ["obj", "fbx", "blend", "mdl"]          # which copy of a model saved in several formats is kept


def find_duplicates():
    """[[kept model, duplicate, ...]]: models whose files are byte-for-byte the same (the first imported is kept),
    and one model saved in several formats in the same pack (same file name, a different format each - OBJ kept,
    then FBX, then BLEND)."""
    idx = load_index()
    known_hashes(idx)
    groups, seen = [], set()
    by_hash = {}
    for pack in idx["packs"]:                      # packs are in import order: the first copy is the original
        for m in pack.get("models", []):
            if m.get("hash"):
                by_hash.setdefault(m["hash"], []).append({"id": m["id"], "name": m["name"], "pack": pack["name"],
                                                          "format": m.get("format")})
    for g in by_hash.values():
        if len(g) > 1:
            groups.append(g)
            seen |= {x["id"] for x in g}
    for pack in idx["packs"]:
        by_stem = {}
        for m in pack.get("models", []):
            if m["id"] not in seen:
                by_stem.setdefault(Path(m.get("source_file") or m["file"]).stem.lower(), []).append(m)
        for g in by_stem.values():
            fmts = [x.get("format") for x in g]
            if len(g) > 1 and len(set(fmts)) == len(fmts):
                g = sorted(g, key=lambda x: FORMAT_PREF.index(x.get("format")) if x.get("format") in FORMAT_PREF else 9)
                groups.append([{"id": x["id"], "name": x["name"], "pack": pack["name"], "format": x.get("format")}
                               for x in g])
    return groups


def remove_duplicates():
    """Every copy after the first goes to the trash (delete_models). Returns how many were removed."""
    extra = [m["id"] for g in find_duplicates() for m in g[1:]]
    return delete_models(extra) if extra else 0


# ----------------------------------------------------------------------------- names and descriptions
DESCRIBE = ("You name 3D models for an asset library from a picture of the model and its file name. KEEP every "
            "meaningful word of the file name (Burned, Empty, Large, Autumn, a number) unless the picture clearly "
            "shows it's wrong, and ADD what the name is missing - the material, style or setting that tells it "
            "apart: \"fence\" -> \"Wooden Farm Fence\" or \"Sci-Fi Space Fence\", \"Bacon Burned\" -> \"Burned "
            "Bacon Strip\", \"Tree4\" -> \"Round Green Tree\". Reply with JSON only: {\"name\": \"2-5 words, Title "
            "Case\", \"description\": \"one short sentence about how it looks (shape, colours) and where you'd "
            "find it - not what games it suits\"}")


def describe_models(ollama, log=print, redo=False, limit=None):
    """The vision model looks at each model's picture and gives it a clear name + a one-line description. The
    file's name is kept as "original_name"; the new name's words join the model's tags, so matching finds it
    ("space fence"). Returns how many were described."""
    if not ollama:
        return 0
    import base64
    import llm
    model = ollama.get("vision_model") or ollama["model"]
    idx = load_index()
    todo = [(p, m) for p in idx["packs"] for m in p.get("models", [])
            if m.get("status") == "ok" and (redo or not m.get("description")) and (PREVIEWS / f"{m['id']}.png").exists()]
    if limit:
        todo = todo[:limit]
    done = 0
    for i, (pack, m) in enumerate(todo):
        progress.report(0.05 + 0.9 * i / max(1, len(todo)), f"Naming models ({i + 1}/{len(todo)})")
        b64 = base64.b64encode((PREVIEWS / f"{m['id']}.png").read_bytes()).decode("ascii")
        orig = m.get("original_name") or m["name"]
        try:
            r = llm.chat_json(ollama["url"], model, DESCRIBE,
                              f"File name: {orig}\nPack: {pack['name']}\nFolder: {m.get('folder') or '-'}",
                              0.2, images=[b64])
        except Exception as exc:
            log(f"[import] couldn't describe '{orig}' ({exc.__class__.__name__})")
            continue
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:40]
        desc = re.sub(r"\s+", " ", str(r.get("description") or "")).strip()[:200]
        if not name or not re.search(r"[A-Za-z]", name):
            continue
        m["original_name"] = orig
        m["name"], m["description"] = name, desc
        m["tags"] = sorted(set(m.get("tags") or []) | words(name))
        done += 1
        log(f"[import] {orig} -> {name}: {desc}")
        if done % 10 == 0:
            save_index(idx)
    save_index(idx)
    return done


# ----------------------------------------------------------------------------- categories (Assets page)
# Made from each model's own name, not the zip it came in. A name that says nothing ("Material.003") takes the
# category most of its pack's models have (a food pack's odd names stay in Food).
CATEGORIES = [
    ("Vehicles", "car cars taxi bus train ambulance bicycle bike suv cop police truck van boat ship plane airplane "
                 "helicopter tractor motorcycle scooter tram rocket jeep schoolbus sportscar normalcar"),
    ("Street & traffic", "traffic sign cone streetlight lamppost hydrant mailbox bench fence road barrier"),
    ("Animals", "pug dog cat cow horse pig sheep llama zebra rat mouse frog snake spider wasp bee bat bird fish "
                "shark whale dolphin manta ray chicken duck rabbit bear fox deer lion tiger elephant monkey "
                "penguin turtle crab octopus"),
    ("Dinosaurs", "trex triceratops stegosaurus apatosaurus parasaurolophus velociraptor dinosaur dino raptor"),
    ("Fantasy & creatures", "dragon slime skeleton ghost zombie monster goblin mushroom_man creature alien"),
    ("People", "human man woman person people boy girl guy lady police_officer worker posed character"),
    ("Furniture", "chair table bed sofa couch desk shelf bookshelf cabinet drawer wardrobe lamp stool armchair "
                  "nightstand dresser rug carpet curtain mirror tv television fridge oven stove sink toilet bath "
                  "bathtub shower plant_pot pot vase clock painting frame pillow cushion door window kitchen"),
    ("Food", "food apple banana bread burger cake candy carrot cheese cherry chicken_leg cookie corn croissant "
             "cupcake donut doughnut egg fries grape hotdog icecream ice cream lemon meat melon orange pancake pear "
             "pepper pie pineapple pizza potato sandwich sausage steak strawberry sushi taco tomato watermelon "
             "bottle cup mug plate bowl can soda juice milk coffee tea wine beer fruit vegetable"),
    ("Nature", "tree pine oak palm birch bush shrub grass rock stone boulder flower plant leaf log stump cactus "
               "mushroom fern reed lily cloud mountain hill"),
]
_CAT_WORDS = [(name, set(ws.split())) for name, ws in CATEGORIES]


_CANON = {n.lower(): n for n, _ in CATEGORIES}


def _name_category(m):
    if m.get("category"):                    # the AI's answer (ai_categorize), kept in the index
        return _CANON.setdefault(str(m["category"]).lower(), m["category"])
    ws = words(m.get("name", "")) | set(m.get("tags") or [])
    for name, cw in _CAT_WORDS:
        if ws & cw:
            return name
    return None


def _word_category(m):
    ws = words(m.get("name", "")) | set(m.get("tags") or [])
    return next((name for name, cw in _CAT_WORDS if ws & cw), None)


def ai_categorize(ollama, log=print, redo=False):
    """Ollama sorts the models whose names the word list (CATEGORIES) doesn't place - into an existing category or a
    new one it names ("Instruments", "Weapons"). Answers are kept in the index as "category". redo=True asks again
    for every model the word list can't place. Returns how many got a category."""
    if not ollama:
        return 0
    idx = load_index()
    todo = [m for p in idx["packs"] for m in p.get("models", [])
            if m.get("status") == "ok" and not _word_category(m) and (redo or not m.get("category"))]
    if not todo:
        return 0
    import llm
    known = sorted({n for n, _ in CATEGORIES} | {m["category"] for p in idx["packs"] for m in p.get("models", [])
                                                if m.get("category")})
    done = 0
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        names = {str(k): " ".join(sorted(words(m["name"]))) or m["name"] for k, m in enumerate(chunk)}
        try:
            r = llm.chat_json(ollama["url"], ollama["model"],
                              "You sort 3D models into categories for an asset library. Use one of these when it "
                              f"fits: {', '.join(known)}. Otherwise make up a short plural category (1-2 words, "
                              "Title Case, e.g. Instruments, Weapons, Sports). Reply with JSON only: "
                              '{"0": "Category", "1": "Category", ...} - one entry per model number.',
                              json.dumps(names), temperature=0.2)
        except Exception as exc:
            log(f"[import] categories: Ollama failed ({exc.__class__.__name__})")
            break
        for k, m in enumerate(chunk):
            cat = str((r or {}).get(str(k)) or "").strip()[:28]
            if cat and re.fullmatch(r"[A-Za-z][A-Za-z &'-]*", cat):
                # "Street & Traffic" is the same category as "Street & traffic": the first spelling wins
                same = next((c for c in known if c.lower() == cat.lower()), None)
                m["category"] = same or (cat.title() if cat.islower() else cat)
                known = sorted(set(known) | {m["category"]})
                done += 1
    save_index(idx)
    log(f"[import] categories: {done} model(s) sorted by the AI")
    return done


def _pack_categories(pack):
    """[(model, category)] for one pack. A name that says nothing takes the pack's main category, and in a pack
    that is mostly one thing (70 %+) a word from another category loses to it: the food pack's "Fish" and
    "Mushroom" are Food, not Animals/Nature. The AI's own answers (m["category"]) are kept as they are."""
    named = [(m, _name_category(m)) for m in pack.get("models", [])]
    counts = {}
    for _, c in named:
        if c:
            counts[c] = counts.get(c, 0) + 1
    main = max(counts, key=counts.get) if counts else "Other"
    total = sum(counts.values()) or 1
    strong = counts and counts[main] >= 0.7 * total
    # only a real outlier gives way (one "Fish" among 100 foods) - not a group (the traffic signs and cone in the
    # Public Transport pack are 30 % of it and stay Street & traffic)
    outlier = lambda c: c and counts.get(c, 0) < 0.15 * total    # noqa: E731
    return [(m, main if (not c or (strong and outlier(c) and not m.get("category"))) else c) for m, c in named]


def category_map():
    """model id -> category (the same categories the Assets page shows)."""
    return {m["id"]: c for pack in packs() for m, c in _pack_categories(pack)}


def categorised():
    """Every model with a "category" (and its pack's name/license), for the Assets page."""
    out = []
    for pack in packs():
        for m, c in _pack_categories(pack):
            pv = PREVIEWS / f"{m['id']}.png"
            out.append({**m, "category": c, "pack_id": pack["id"], "pack": pack["name"],
                        "license": pack.get("license", ""), "real_height": real_height(m),
                        "preview_v": int(pv.stat().st_mtime) if pv.exists() else 0})   # a redrawn picture shows
    return out


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


# No model with the thing's own name: the nearest stand-in the user has, by kind, best first. A near fit (an
# ambulance for a mail van) looks far better than shapes the AI makes up - but only within a kind that reads
# right: a vehicle for a vehicle, the same animal for an animal (never a cow for a cat).
NEAREST = {
    "van": ["van", "ambulance", "suv", "bus", "car", "taxi"], "minivan": ["van", "suv", "car"],
    "truck": ["truck", "lorry", "van", "ambulance", "bus", "suv", "car"], "lorry": ["truck", "van", "bus"],
    "pickup": ["truck", "suv", "car"], "firetruck": ["truck", "ambulance", "bus"],
    "delivery": ["van", "truck", "ambulance", "suv"], "postal": ["van", "truck", "ambulance"],
    "car": ["car", "taxi", "suv", "cop"], "vehicle": ["car", "van", "suv", "taxi"], "auto": ["car", "taxi"],
    "automobile": ["car", "taxi"], "sedan": ["car", "taxi"], "jeep": ["suv", "car"], "limo": ["car"],
    "limousine": ["car"], "racecar": ["sport", "car"], "police": ["cop"], "cruiser": ["cop"],
    "cab": ["taxi", "car"], "coach": ["bus"], "schoolbus": ["bus"], "tram": ["train", "bus"],
    "trolley": ["train", "bus"], "subway": ["train"], "locomotive": ["train"], "bike": ["bicycle"],
    "cycle": ["bicycle"], "ambulance": ["ambulance", "van", "suv"],
    "dog": ["dog", "pug"], "puppy": ["dog", "pug"], "doggo": ["dog", "pug"], "mouse": ["mouse", "rat"],
    "mice": ["mouse", "rat"], "goldfish": ["fish"], "koi": ["fish"], "salmon": ["fish"], "trout": ["fish"],
    "tuna": ["fish"], "orca": ["whale", "dolphin"], "dinosaur": ["trex", "triceratops", "apatosaurus"],
    "dino": ["trex", "triceratops"], "pony": ["horse"], "piglet": ["pig"], "lamb": ["sheep"],
    "toad": ["frog"], "serpent": ["snake"], "bee": ["wasp"], "hornet": ["wasp"], "monster": ["slime", "dragon"],
}


def _word_score(w, tags):
    """1 for the word itself in the model's name, less for a stand-in from NEAREST (earlier = closer), else 0."""
    if w in tags:
        return 1.0
    for i, t in enumerate(NEAREST.get(w, [])):
        if t in tags:
            return max(0.5, 0.85 - 0.07 * i)
    return 0.0


def _ordered_words(text):
    out = []
    for tok in re.split(r"[^a-zA-Z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or ""))):
        for w in sorted(words(tok)):
            if w not in out:
                out.append(w)
    return out


# Where it is decides between categories: a "fish" in a kitchen is food, in an aquarium an animal.
SETTING_CATS = [
    ("kitchen restaurant cafe bakery diner market supermarket picnic food dinner lunch breakfast pizzeria buffet "
     "canteen cafeteria grocery", ["Food", "Utensils", "Containers", "Condiments"]),
    ("farm barn zoo ocean sea aquarium underwater pond lake river jungle safari reef stable", ["Animals"]),
    ("forest park garden woods meadow beach island mountain camp campsite field valley desert", ["Nature", "Trees"]),
    ("street city road town parking highway garage traffic intersection crossing downtown", ["Vehicles",
                                                                                           "Street & traffic"]),
    ("room bedroom living house home office school classroom library hotel apartment studio hall lobby",
     ["Furniture"]),
    ("dungeon castle cave haunted graveyard crypt tomb lair", ["Fantasy & creatures"]),
    ("museum prehistoric jurassic dinosaur", ["Dinosaurs"]),
]
INDOOR_WORDS = set(("room kitchen cafe office shop store school house home inside indoor restaurant bakery library "
                    "hall bedroom classroom museum apartment hotel lobby post diner bar gym studio basement attic "
                    "garage hospital").split())
OUTDOOR_ONLY = {"Vehicles", "Street & traffic", "Trees", "Dinosaurs"}     # never a set's prop inside a room
SYNONYMS = {"street": {"traffic", "road"}, "road": {"traffic", "street"}, "traffic": {"street", "road"},
            "sofa": {"couch"}, "couch": {"sofa"}, "kitty": {"cat"}, "doggy": {"dog"}, "lorry": {"truck"}}


def kind_category(kind):
    """The category a thing's own name puts it in (its main word first), or None."""
    for w in reversed(_ordered_words(kind)):
        for name, cw in _CAT_WORDS:
            if w in cw:
                return name
    return None


# ----------------------------------------------------------------------------- crowds
# "a crowd", "an army of cats", "the audience": several imported models in a loose group instead of one made-up
# shape (four boxes for "a feline army marching"). People come from the People category (the Posed Background
# Humans pack), picked by what the crowd does; anything else ("herd of cows") is that thing's model, repeated.
GROUP_WORDS = set("army armies crowd crowds team teams group groups squad troops audience everyone everybody people "
                  "herd flock swarm gang class family families fans spectators onlookers mob horde pack band "
                  "choir parade line queue villagers tourists shoppers customers students kids children "
                  "soldiers guards".split())
PEOPLE_GROUPS = set("crowd audience everyone everybody people team squad troops gang class family fans spectators "
                    "onlookers mob horde band choir parade line queue villagers tourists shoppers customers "
                    "students kids children soldiers guards army".split())
CROWD_POSES = [      # words in the name/description -> pose words in the model names, best first
    (("cheer", "cheering", "audience", "fans", "spectators", "concert", "stadium", "party", "celebrate", "applause",
      "clap"), ("cheering", "waving", "standing")),
    (("march", "marching", "army", "soldiers", "troops", "parade", "walking", "walk", "queue", "line", "shoppers",
      "tourists"), ("walking", "standing")),
    (("run", "running", "chase", "chasing", "flee", "fleeing", "stampede", "rush", "mob", "horde"),
     ("running", "walking")),
    (("scared", "scary", "horror", "afraid", "shock", "shocked"), ("coveringeyes", "lookingup", "standing")),
    (("look", "looking", "watch", "watching", "stare", "staring", "sky", "stars"), ("lookingup", "standing")),
]
SEAT_WORDS = set("sitting seated sit bench benches stands bleachers stadium theater theatre cinema seats".split())
CROWD_SKIP = {"hairstyle", "hair", "head", "bust"}          # parts of people, not people
ANIMAL_ALIASES = {"feline": "cat", "felines": "cat", "kitties": "cat", "kittens": "cat", "canine": "dog",
                  "puppies": "dog", "doggos": "dog", "cattle": "cow", "birds": "bird", "fishes": "fish"}


POSE_WORDS = set("marching running cheering walking waving sitting standing angry happy scared tiny giant big small "
                 "little huge loud cheerful busy".split())
# cast people by role ("Mom: ...") - played by one of the user's imported people, a woman for mom, a man for dad
FEMALE_WORDS = set("mom mum mommy mother woman women girl girls lady grandma granny grandmother aunt sister wife "
                   "queen princess daughter waitress actress she her female".split())
MALE_WORDS = set("dad daddy father man men boy boys guy grandpa grandfather uncle brother husband king prince son "
                 "waiter he him male".split())
CHILD_WORDS = set("kid kids child children boy boys girl girls baby toddler son daughter".split())
ROLE_WORDS = FEMALE_WORDS | MALE_WORDS | CHILD_WORDS | set(
    "teacher doctor nurse chef cook baker police officer cop firefighter farmer mailman postman neighbor neighbour "
    "friend boss scientist pilot driver waiter waitress cashier clerk librarian coach judge stranger".split()) \
    - {"she", "her", "he", "him", "female", "male"}
PERSON_NOUNS = set("person persons man men woman women boy boys girl girls human humans soldier kid kids child "
                   "children student students fan fans shopper shoppers tourist tourists villager villagers "
                   "guard guards customer customers pedestrian pedestrians passerby passersby commuter commuters "
                   "visitor visitors traveler travelers traveller travellers worker workers people".split()) | ROLE_WORDS


def is_group(name):
    """Is this cast name a group of things/people ("feline_army", "crowd")?"""
    return bool(set(re.split(r"[_\s]+", str(name).lower())) & GROUP_WORDS)


def _one_per_name(models):
    """One copy of each model name, in the preferred format (the pack has OBJ, FBX and BLEND of each)."""
    best = {}
    for pack, m in models:
        k = (pack["id"], m["name"].lower())
        rank = FORMAT_PREF.index(m["format"]) if m.get("format") in FORMAT_PREF else 9
        if k not in best or rank < best[k][0]:
            best[k] = (rank, pack, m)
    return [(p, m) for _, p, m in best.values()]


def person_def(name, looks="", setting="", seed=0):
    """One imported person for a cast member ("mom", "pedestrian"): a model definition like any imported prop
    (it moves as a whole and can't move its mouth, but speaks with its own voice), or None."""
    d = crowd_def(name, looks, setting, n=1, seed=seed)
    if not d or not d.get("crowd"):
        return None
    m = dict(d["crowd"][0])
    m.update(kind=re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_"), looks=looks or m.get("looks", ""),
             person=True)
    return m


def crowd_def(name, looks="", setting="", n=None, seed=0):
    """A cast/prop definition for a group: {"crowd": [member defs], "offsets": [[x, y, turn]...], ...}, or None
    when there's nothing to build it from. Members stand in two loose rows facing the camera side (-y)."""
    import random
    text = f"{name} {looks}".lower().replace("_", " ")
    ws = set(re.findall(r"[a-z]+", text))
    rng = random.Random(f"{name}|{seed}")
    # what the group is made of: the name's own words ("feline_army", "cow_herd"), or what follows "of" in the
    # description ("a herd of cows") - not every word of it ("people at the beach" isn't a group of beaches)
    src = re.findall(r"[a-z]+", str(name).lower().replace("_", " ")) + \
        re.findall(r"\bof\s+(?:the\s+|many\s+|angry\s+|happy\s+)?([a-z]+)", str(looks).lower())
    noun = [ANIMAL_ALIASES.get(w, w) for w in src if w not in GROUP_WORDS and w not in NOISE and len(w) > 2
            and w not in POSE_WORDS and w not in PERSON_NOUNS and w not in SEAT_WORDS]
    cats = category_map()
    members = []
    thing = None
    if noun:
        for w in noun:                                         # "army of cats", "herd of cows", "feline army"
            d = match(w, looks, setting)
            if d and cats.get(d["model"]["id"]) != "People":
                thing = d
                break
    named = noun
    if thing:
        big = float(thing.get("width") or 1.0)          # three dinosaurs fill a set; six cats don't
        members = [dict(thing) for _ in range(n or (3 if big > 2.5 else 4 if big > 1.2 else rng.randint(4, 6)))]
    elif named:
        return None                                      # "an army of cats" with no cat model: not people
    else:
        seats = bool(ws & SEAT_WORDS)                    # sitting models sit on thin air unless there are seats
        people = _one_per_name([(p, m) for p in packs() for m in p.get("models", [])
                                if m.get("status") == "ok" and cats.get(m["id"]) == "People"
                                and not words(m["name"]) & CROWD_SKIP
                                and (seats or "sitting" not in m["name"].lower())])
        if not people:
            return None
        # a woman for "mom", a man for "dad", a child for "kid" - when the pack names say which
        sex = "female" if ws & FEMALE_WORDS else "male" if ws & MALE_WORDS else None
        kid = bool(ws & CHILD_WORDS)
        fit = [pm for pm in people if (not sex or sex in words(pm[1]["name"]) or
                                       (sex == "female" and words(pm[1]["name"]) & {"woman", "girl", "lady"}) or
                                       (sex == "male" and words(pm[1]["name"]) & {"man", "boy", "guy"}))
               and (not kid or words(pm[1]["name"]) & {"kid", "child", "boy", "girl"})]
        people = fit or people
        want = next((poses for trig, poses in CROWD_POSES if ws & set(trig)), ("standing", "waving", "lookingup"))

        def pose_rank(pm):
            nm = pm[1]["name"].lower().replace(" ", "")
            return next((i for i, p in enumerate(want) if p in nm), len(want))
        # one person (a cast member): the plainest pose ("Female Standing", not "...CoveringEyes")
        people.sort(key=lambda pm: (pose_rank(pm), len(words(pm[1]["name"])) if n == 1 else 0, rng.random()))
        best = [pm for pm in people if pose_rank(pm) < len(want)] or people
        k = n or rng.randint(5, 7)
        pick = (best * k)[:k] if len(best) < k else best[:max(k, 1)]
        # sitting models are short and the files use any units: one scale for the whole pack, from its standing
        # people (1.72 m), so a sitting person is sitting-height, not a giant
        for pack, m in pick:
            stand = [x.get("height") for x in pack.get("models", []) if x.get("height") and
                     "standing" in x["name"].lower() and not words(x["name"]) & CROWD_SKIP]
            ref = sorted(stand)[len(stand) // 2] if stand else max(0.01, float(m.get("height") or 1.7))
            d = match_model(pack, m, m["name"], looks)
            h = float(m.get("height") or ref) * 1.72 / ref
            d.update(height=round(h, 3), width=round(max(0.45, d["width"] * h / max(d["height"], 0.01)), 3),
                     needs_height=False)
            d.pop("needs_height", None)
            members.append(d)
    if not members:
        return None
    # two loose rows, the back row shifted half a gap so heads don't hide each other
    gap = max(0.75, max(m["width"] for m in members) * 1.05)
    offsets, row_n = [], (len(members) + 1) // 2
    for i, m in enumerate(members):
        row, col = (0, i) if i < row_n else (1, i - row_n)
        cnt = row_n if row == 0 else len(members) - row_n
        x = (col - (cnt - 1) / 2) * gap + (gap / 2 if row else 0.0) + rng.uniform(-0.12, 0.12)
        y = row * gap * 0.9 + rng.uniform(-0.1, 0.1)
        offsets.append([round(x, 2), round(y, 2), round(rng.uniform(-0.35, 0.35), 2)])
    span_x = max(abs(o[0]) for o in offsets) + gap / 2
    return {"kind": re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_"), "looks": looks, "by": "imported",
            "source": "imported", "name": f"crowd of {members[0]['name']}", "pack": members[0].get("pack", ""),
            "crowd": members, "offsets": offsets, "parts": [],
            "height": round(max(m["height"] for m in members), 3), "width": round(span_x * 2, 2),
            "radius": round(max(span_x, gap), 2), "place": "near"}


def _setting_cats(setting):
    ws = set(re.findall(r"[a-z]+", str(setting or "").lower()))
    return {c for wl, cats in SETTING_CATS if ws & set(wl.split()) for c in cats}, bool(ws & INDOOR_WORDS)


# two words that make a different thing: a model named with one isn't the thing its last word says
COMPOUNDS = ("hot dog", "corn dog", "dog house", "dog bowl", "dog bed", "dog toy", "cat food", "cat bed", "cat toy",
             "fish food", "fish tank", "fish bowl", "bird house", "bird cage", "bird feeder", "horse shoe",
             "rocking horse", "teddy bear", "gummy bear", "jelly fish", "star fish", "sea horse", "cow boy",
             "bull dozer", "fire place", "fire truck", "fire hydrant", "lady bug", "butter fly", "dragon fly",
             "egg plant", "pine apple", "light bulb", "light house", "moon cake", "sun flower", "snow man",
             "car park", "house plant", "tree house", "bat ball", "duck tape")
PACK_LOCK, PACK_PREFER = False, None    # make_set (style B): models for one set come from one pack


def match(kind, looks="", setting=""):
    """The imported model for `kind`, as a prop definition (same shape as propgen's), or None.
    - The LAST word of the name is the thing itself ("mail van", "police car", "ice cream truck"): a model must be
      that thing or a stand-in for it (NEAREST: a van -> the ambulance). Scored over all the words (police car ->
      Cop, not SportsCar).
    - Words that disagree reject a model: a "plant pot" isn't the CookingPot (both have a describing word the other
      lacks), a "table lamp" isn't a table (no lamp = no match, it gets generated).
    - Categories (category_map): the setting's categories first (a kitchen's fish is the food one), then the
      category the thing's own name is in; inside a room a street/vehicle/tree model is only used when the thing
      asked for is one (a van crashing into a shop is fine, a "light" in a cafe is not the traffic light)."""
    global PACK_PREFER                      # set below: the first match picks the set's pack (style B)
    kw = _ordered_words(kind)
    if not kw:
        return None
    head, lt = kw[-1], words(looks)
    cats = category_map()
    want_cats, indoor = _setting_cats(setting)
    kcat = kind_category(kind)
    best, best_key = None, None
    for pack in packs():
        for m in pack.get("models", []):
            if m.get("status") != "ok":
                continue
            tags = set(m.get("tags") or []) - {w for w in (m.get("tags") or []) if w.isdigit()}
            hs = _word_score(head, tags)
            if hs <= 0:
                continue
            seen_name = f"{m.get('name', '')} {m.get('original_name') or ''}".lower().replace("-", " ").replace("_", " ")
            if any(head in cw.split() and cw in seen_name and cw not in kind.lower().replace("_", " ")
                   for cw in COMPOUNDS):
                continue                    # "Raw Hot Dog" is food, not a dog (it played the dog in a video)
            if m.get("original_name") and m.get("name"):
                # renamed by the picture model (Name & describe): what it SEES wins over the file name - the file
                # "building-structure" is a "Wooden Farm Fence" and was used as a city's buildings; and the thing is
                # before "with" ("Single Bed with Pillow" is a bed, not a pillow)
                own = set(_ordered_words(re.split(r"\s+with\s+", m["name"], flags=re.I)[0]))
                if _word_score(head, own) <= 0:
                    continue
            mcat = cats.get(m["id"])
            if indoor and mcat in OUTDOOR_ONLY and kcat != mcat:
                continue
            unmatched = [w for w in kw if _word_score(w, tags) <= 0]
            expanded = set(kw) | {x for w in kw for x in SYNONYMS.get(w, ())} |                 {t for w in kw for t in NEAREST.get(w, [])}
            extra = [t for t in tags if t not in expanded and len(t) > 2]
            if unmatched and extra and not set(unmatched) & {x for t in extra for x in SYNONYMS.get(t, ())}:
                continue                    # "plant pot" vs CookingPot: each has a word the other doesn't
            if PACK_LOCK and PACK_PREFER and pack["id"] != PACK_PREFER:
                continue                    # set style B: every model from the set's one pack (styles don't clash)
            score = sum(_word_score(w, tags) for w in kw) / len(kw)
            key = (mcat in want_cats, kcat is not None and mcat == kcat, score, hs, len(lt & tags), -len(tags),
                   m["id"])
            if best_key is None or key > best_key:
                best, best_key = (pack, m), key
    if not best:
        return None                         # nothing is that thing: the studio makes its own
    if PACK_LOCK and not PACK_PREFER:
        PACK_PREFER = best[0]["id"]         # the first match decides the set's pack
    d = match_model(*best, kind, looks)
    if best_key[3] < 1.0:
        d["stand_in"] = True               # not the thing itself: the closest model there is
    return d


def model_def(model_id, kind="", looks=""):
    """A prop definition for one specific imported model (chosen by hand in the video editor)."""
    for pack in packs():
        for m in pack.get("models", []):
            if m["id"] == model_id and m.get("status") == "ok":
                return match_model(pack, m, kind, looks)
    return None


# Real-world heights (m). Model files use any units - a Pug measured 2.65, a Cow 5.1, a Bicycle 3.1 - so a
# model is scaled to how tall the real thing is: this table by name, else Ollama's answer (cached in the index
# as "real_height"), else its own height if that's believable.
TYPICAL_HEIGHT = [
    ({"traffic", "light"}, 3.0), ({"traffic", "sign"}, 2.2), ({"traffic", "cone"}, 0.7),
    ({"ambulance"}, 2.6), ({"school", "bus"}, 3.0), ({"bus"}, 3.1), ({"train"}, 3.8), ({"tram"}, 3.4),
    ({"truck"}, 3.0), ({"van"}, 2.1), ({"suv"}, 1.8), ({"sport"}, 1.2), ({"taxi"}, 1.5), ({"cop"}, 1.5),
    ({"car"}, 1.45), ({"bicycle"}, 1.05), ({"bike"}, 1.05), ({"motorcycle"}, 1.2), ({"boat"}, 1.5),
    ({"pug"}, 0.35), ({"dog"}, 0.55), ({"cat"}, 0.3), ({"cow"}, 1.5), ({"horse"}, 1.65), ({"pig"}, 0.85),
    ({"sheep"}, 0.9), ({"llama"}, 1.8), ({"zebra"}, 1.4), ({"rat"}, 0.12), ({"frog"}, 0.1), ({"spider"}, 0.08),
    ({"wasp"}, 0.05), ({"snake"}, 0.25), ({"bat"}, 0.2), ({"slime"}, 0.5), ({"dragon"}, 3.0),
    ({"skeleton"}, 1.75), ({"trex"}, 4.5), ({"triceratops"}, 3.0), ({"stegosaurus"}, 4.0),
    ({"apatosaurus"}, 7.0), ({"parasaurolophus"}, 3.5), ({"velociraptor"}, 0.8), ({"whale"}, 4.0),
    ({"shark"}, 1.2), ({"dolphin"}, 0.9), ({"manta"}, 0.6), ({"fish"}, 0.25),
    ({"chair"}, 0.9), ({"stool"}, 0.7), ({"table"}, 0.75), ({"desk"}, 0.75), ({"bed"}, 0.6), ({"sofa"}, 0.85),
    ({"couch"}, 0.85), ({"bookshelf"}, 1.8), ({"shelf"}, 1.6), ({"wardrobe"}, 2.0), ({"lamp"}, 1.5),
    ({"door"}, 2.1), ({"fridge"}, 1.8), ({"tree"}, 5.0), ({"bush"}, 1.0), ({"rock"}, 0.8), ({"flower"}, 0.4),
    ({"crate"}, 0.6), ({"barrel"}, 0.9), ({"plant"}, 0.9),
    ({"male"}, 1.78), ({"man"}, 1.78), ({"female"}, 1.66), ({"woman"}, 1.66), ({"person"}, 1.72),
    ({"human"}, 1.72), ({"soldier"}, 1.78), ({"child"}, 1.2), ({"kid"}, 1.2),
]


def real_height(m):
    """How tall the real thing is (m), or None when only Ollama can say (see ask_height)."""
    if m.get("real_height"):
        return float(m["real_height"])
    ws = words(m.get("name", "")) | set(m.get("tags") or [])
    for need, h in TYPICAL_HEIGHT:
        if need <= ws:
            return h
    return None


def ask_height(m, ollama, log=print):
    """Ask Ollama once how tall the real thing is; the answer is kept in the index ("real_height")."""
    if real_height(m) or not ollama:
        return real_height(m)
    try:
        import llm
        r = llm.chat_json(ollama["url"], ollama["model"],
                          'You know real-world sizes. Reply with JSON only: {"height_m": number} - how tall a '
                          "typical real one is, in metres.", f"Object: {' '.join(sorted(words(m['name'])))}",
                          temperature=0.2)
        h = float(r.get("height_m"))
        if not 0.02 <= h <= 60:
            return None
    except Exception as exc:
        log(f"[imported] couldn't ask how big '{m['name']}' is ({exc.__class__.__name__})")
        return None
    idx = load_index()
    for pack in idx["packs"]:
        for x in pack.get("models", []):
            if x["id"] == m["id"]:
                x["real_height"] = round(h, 3)
    save_index(idx)
    m["real_height"] = round(h, 3)
    log(f"[imported] '{m['name']}' is about {h:.2f} m tall in real life")
    return h


def match_model(pack, m, kind, looks=""):
    raw_h = m.get("height") if m.get("height") and 0.005 <= m["height"] <= 60 else None
    raw_w = max(m.get("width") or 0.0, m.get("depth") or 0.0)
    real = real_height(m)
    if real and raw_h:
        height, width = real, max(raw_w * real / raw_h, 0.3)    # the whole model scales with its height
    else:
        height = raw_h if raw_h and raw_h <= 4 else 1.2           # unknown: believe it only if it's plausible
        width = max(raw_w * (height / raw_h if raw_h else 1.0), 0.3)
        if not real:
            m = dict(m, _needs_height=True)
    return {"kind": kind, "looks": looks, "by": "imported", "source": "imported", "name": m["name"],
            "pack": pack["name"], "license": pack.get("license", ""),
            "model": {"id": m["id"], "file": m["file"], "format": m["format"]},
            "height": round(height, 3), "width": round(width, 3), "radius": round(width / 2, 2),
            "place": "near", "parts": [],
            **({"needs_height": True} if m.get("_needs_height") else {})}


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
    p_desc = sub.add_parser("describe", help="the vision model names and describes models from their pictures")
    p_desc.add_argument("--redo", action="store_true")
    sub.add_parser("dedupe", help="move byte-identical copies of models to the trash")
    p_cat = sub.add_parser("categorize", help="the AI sorts models the name list doesn't place")
    p_cat.add_argument("--redo", action="store_true", help="ask again for ones it already sorted")
    p_del = sub.add_parser("delete")
    p_del.add_argument("pack_id")
    a = ap.parse_args()
    if a.cmd == "import":
        pack = import_zip(a.zip, a.pack, a.license, source_name=a.source)
        ok = sum(1 for m in pack["models"] if m["status"] == "ok")
        print(f"IMPORTED={pack['id']} ok={ok} total={len(pack['models'])}", flush=True)
    elif a.cmd == "list":
        print(json.dumps(packs(), indent=1))
    elif a.cmd == "describe":
        import settings as S
        n = describe_models(S.load_settings().get("ollama"), print, redo=a.redo)
        print(f"DESCRIBED={n}", flush=True)
    elif a.cmd == "dedupe":
        print(f"REMOVED={remove_duplicates()}", flush=True)
    elif a.cmd == "categorize":
        import settings as S
        progress.report(0.1, "Sorting the models into categories")
        n = ai_categorize(S.load_settings().get("ollama"), print, redo=a.redo)
        print(f"CATEGORIZED={n}", flush=True)
    elif a.cmd == "previews":
        previews_all()
        print("PREVIEWS=done", flush=True)
    elif a.cmd == "delete":
        delete_pack(a.pack_id)
        print(f"DELETED={a.pack_id}", flush=True)
