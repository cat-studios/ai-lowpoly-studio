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
            for sib in (f.parent.glob(f.stem + ".*") if f.parent.exists() else []):
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


def categorised():
    """Every model with a "category" (and its pack's name/license), for the Assets page."""
    out = []
    for pack in packs():
        named = [(m, _name_category(m)) for m in pack.get("models", [])]
        counts = {}
        for _, c in named:
            if c:
                counts[c] = counts.get(c, 0) + 1
        fallback = max(counts, key=counts.get) if counts else "Other"
        for m, c in named:
            pv = PREVIEWS / f"{m['id']}.png"
            out.append({**m, "category": c or fallback, "pack_id": pack["id"], "pack": pack["name"],
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


def match(kind, looks="", setting=""):
    """The imported model for `kind`, as a prop definition (same shape as propgen's), or None.
    The LAST word of the name is the thing itself ("mail van", "police car", "ice cream truck"): when any model is
    that thing or a stand-in for it (NEAREST: a van -> the ambulance), the best of those is used, scored over all
    the words (police car -> Cop, not SportsCar). Otherwise the old rule: at least half the words in its name."""
    kw = _ordered_words(kind)
    if not kw:
        return None
    head, lt = kw[-1], words(looks)
    best, best_key = None, None
    for pack in packs():
        for m in pack.get("models", []):
            if m.get("status") != "ok":
                continue
            tags = set(m.get("tags") or [])
            hs = _word_score(head, tags)
            if hs <= 0:
                continue
            score = sum(_word_score(w, tags) for w in kw) / len(kw)
            key = (score, hs, len(lt & tags), -len(tags), m["id"])
            if best_key is None or key > best_key:
                best, best_key = (pack, m), key
    if best:
        d = match_model(*best, kind, looks)
        if best_key[1] < 1.0:
            d["stand_in"] = True           # not the thing itself: the closest model there is
        return d
    hit, _ = _best(kind, looks)
    if not hit:
        return None
    return match_model(*hit, kind, looks)


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
