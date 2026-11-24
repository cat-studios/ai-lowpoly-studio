"""
Saving edits made in the video editor (Videos page -> ✏️ Edit & re-render).

    POST /api/episodes/<id>/apply   body = {episode: {...full episode...}, cast_models: {name: "imp:<model id>" | "generate"}}

Saves the episode file, so a render started afterwards uses it. Cast members can be given a model picked from the
imported library ("imp:<id>"), or told to generate their own ("generate"); anything else keeps what they had.
Shot camera marks that the new scene doesn't have are moved to the scene's first mark.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
if str(PIPE) not in sys.path:
    sys.path.insert(0, str(PIPE))


def _kind(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")[:28] or "prop"


def apply(path, body):
    import catalog
    import imported

    ep = body.get("episode")
    if not isinstance(ep, dict) or not isinstance(ep.get("shots"), list):
        raise ValueError("the edited video needs a shots list")
    cast = ep.get("cast") or {}

    for name, choice in (body.get("cast_models") or {}).items():
        info = cast.get(name)
        if not isinstance(info, dict):
            continue
        if choice == "generate":
            info.pop("def", None)
            info["generated"] = True            # render designs it itself, even when an imported model matches
        elif isinstance(choice, str) and choice.startswith("imp:"):
            d = imported.model_def(choice[4:], _kind(name), str(info.get("looks") or ""))
            if not d:
                raise ValueError(f"the model for {name} is no longer in the imported library")
            info["def"] = d
            info.pop("generated", None)

    # camera marks must exist in the scene they're used in
    sets = catalog.all_sets()
    moved = []
    for i, s in enumerate(ep["shots"]):
        scene = s.get("set") or ep.get("set") or "cafe"
        marks = (sets.get(scene) or {}).get("marks") or []
        if s.get("to") and marks and s["to"] not in marks:
            s["to"] = marks[0]
            moved.append(i + 1)

    ep.pop("set_recipe", None)                  # rebuilt from the chosen scene when it renders
    path.write_text(json.dumps(ep, indent=2), encoding="utf-8")
    return {"ok": True, "moved_marks": moved}
