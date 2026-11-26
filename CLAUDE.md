# Low Poly Studio - notes for AI assistants

Automated pipeline + local web app that turns a short script into a vertical (1080×1920) Instagram Reel in an
N64 / VHS low-poly style, starring the user's VRoid **catgirl** (the character system is generic: catgirl is just
the active profile; other main characters can join a video as co-stars). The user writes or AI-generates
"What if…?" scripts; everything after that is automated.
README.md is the user-facing guide; this file is the developer map. Keep both up to date when you change things.

## Run it

```powershell
python web/server.py --lan          # web app on :8765 (LAN for the user's phone); or start-studio.bat
python pipeline/run_episode.py episodes/<id>.json [--fresh-voice] [--no-render] [--no-tts]
python pipeline/make_set.py [--idea "haunted bakery"] [--where inside|outside] [--light day|sunset|night] [--ai auto|off] [--comfy required|auto|off] [--replace <id>]
python pipeline/music_gen.py --style "lofi chill" --seconds 60 [--engine auto|ace|synth]
python pipeline/sfx.py              # (re)synthesise the 24 built-in sounds
python pipeline/run_episode.py episodes/<id>.json --preview storyboard|rough   # quick look, output/previews/
python -m unittest discover tests   # quick tests (director, script cleanup, cutaways, ideas filter) - run before pushing
& "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" -b --factory-startup --python pipeline/prepare_character.py -- assets/characters/<x>.vrm --out assets/characters/<id>.blend
```
- `--no-tts` = no voice; `--no-render` re-encodes existing frames (the web app's "Re-apply look only" =
  `reuse_frames`) - only when the shots are the same as in that render (it stops otherwise).
- Checking Blender code without rendering: an episode with `"_no_render": true` builds the whole scene,
  animation, cast and cameras and writes `timing.json`, but no frames. Use it (on a copy in the scratchpad) to
  test `blender_*.py` changes when the user hasn't asked for a render. `run_episode` stops after the Blender
  build(s) with "Build check done" (multi-scene episodes build every scene).
- **Development vs production (since 2026-11-24):** this folder (`C:\Users\kat5\git\ai-lowpoly-studio-dev`, a git
  repo pushed to GitHub, branch `main`) is the development copy - all code changes happen here. The user's
  production install is a separate folder, `C:\Users\kat5\ai-lowpoly-studio` (started with its own
  `start-studio.bat`, port **8765** with `--lan`, holding their characters, voices, sets, videos and settings).
  **Test scenes and test videos run in production** (the user's decision, 2026-11-25: the dev copy lacks voice-venv
  and their assets, so tests there hit errors): push the change, ask the user to `git pull` there and restart, then
  test on :8765. Never edit production code, and never pull or restart it yourself; they move changes over:
  production is a clean clone of the same GitHub repo (`main`), so the route is dev branch → merged into `main` on
  GitHub → `git pull` in production → restart the studio. All personal data is gitignored, so a pull never touches
  it - keep it that way when adding new data folders (add them to `.gitignore`). Never run `git clean` there.
- Preview servers for Claude's browser pane (`.claude/launch.json`): `studio-dev` (:8766) and `studio-check`
  (:8767), for checking the web pages of dev code. Don't start a server on :8765 - that's production (already
  running from its own folder; test videos go through it, see above).
- **The server imports pipeline modules once - restart it after editing any `.py`** (web files are re-read per
  request; reload the page with a cache-busting query like `?v=N`). A 404 on a new route = not restarted yet.

## Environment (Windows 11, PowerShell)
- **Python 3.15** (`python`) runs the pipeline and server - stdlib only, no pip deps (except `edge-tts`).
- **tools/voice-venv** = Python 3.11 with chatterbox-tts, torch 2.6.0+cu124 (CUDA - the pip default was CPU and
  had to be force-reinstalled), faster-whisper, Pillow. Used for local TTS (`local_tts.py`), icons, `sprite_cut.py`
  and `picture_colors.py`.
- **Blender 5.3** at `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe`, run headless with
  `--factory-startup`. Engine id is `BLENDER_EEVEE`. VRM add-on = `bl_ext.blender_org.vrm` (installed with
  `--online-mode -c extension install -s -e vrm`); enabling it needs `addon_utils.enable(..., default_set=True)` or
  the importer crashes on missing add-on preferences.
- **ffmpeg** 9 (gyan full build, has libass). GPU: RTX 4070 12 GB (Blender, Chatterbox and ComfyUI share it).
- **Ollama** at :11434, default model `eriktonon/deepseek-v4.1-flash-1017:latest` (send `"think": false`);
  vision model `qwen3.5:4b` (`settings.ollama.vision_model`).
- **ComfyUI Desktop** at **:8666** (`settings.DEFAULTS` and the user's `config/settings.json` both say 8666;
  `comfy.find_server()` also probes 8188/8189/8000). Image model =
  **Z-Image Turbo** (`z_image_turbo_bf16` via UNETLoader + CLIPLoader `qwen_3_4b` type `lumina2` + VAE `ae`,
  8 steps, CFG 1, `res_multistep`/`simple`, ModelSamplingAuraFlow shift 3, no negative prompt → put "no text" in
  the positive prompt). Music model = **ACE-Step 1.5** (`ace_step_1.5_turbo_aio` checkpoint +
  `TextEncodeAceStepAudio1.5`). The only "checkpoint" is the music model, so `comfy.image_models()` filters out
  audio/video models.

## Status (updated 2026-11-24)
This dev copy starts as a fresh install: no characters, sets other than Legacy Cafe / Legacy Park, props, packs,
music, episodes or videos, and no `config/settings.json` (defaults apply until Settings are saved). The first server
start synthesises the built-in sounds. `tools/voice-venv` (the cloned voice, drawn props, scene from a picture) is not
in git - see README "Installing on a new PC"; without it the free Edge voices are used. The only working copy is in
production (`C:\Users\kat5\ai-lowpoly-studio\tools\voice-venv`, moved there 2026-11-24 - its `pip.exe` launchers
still point at the old path, so use `python -m pip`); this dev copy has none yet. The old project folder
`C:\Users\kat5\git\ai-low-poly` was deleted on 2026-11-24 (personal data moved to production first).
Open items:
- A cast member's spot is picked beside where she stands when they arrive; if she walks on during that shot they can
  end up between her and the camera for a moment.
- Not seen in a render yet: walking round furniture in a generated set, "human" cast as a person, the three-lane
  job queue under load (they build without errors in Blender no-render checks).
- Sets made before 2026-11-24 can contain stacked props (a theme's tables at (0, 0.3)); older sets name imported
  props' walk-to places `imp_table` (new sets: `table`).
- Cast warning "no free spot ... moved to (x, y), clearance N m" = `spot()` found nothing beside her and
  `_roomiest()` picked a place instead (expected in crowded sets); the message lists why each spot was refused.
- Scene jobs can run while a video renders: Blender and ComfyUI can fight for the 12 GB GPU, and regenerating a set
  changes it under a video that's rendering with it.
- The local Ollama model's Lithuanian needs checking (🌐 Check translation) - it wrote "Laukinis" for a plane.
- Never run end to end: ElevenLabs (no API key), importing a VRM through the web page (CLI import works), MDL
  converters on real game files, starter sets + regenerate popup from the browser, Postiz drafts of earlier versions,
  the 3D viewer beyond one scene (it needs internet: three.js from unpkg), the app on a real phone.

## Features and fixes from the 2026-11-24 review

- **New features** (tested in renders):
  - Per-shot lighting: Light picker on every shot (Create page + video editor) and `[day]/[sunset]/[night]/[dawn]`
    (aliases dusk, evening, sunrise...: `catalog.LIGHTS` / `LIGHT_ALIASES`) in scripts. Fixed on the way: the
    lighting keys took the FIRST change's light from frame 1; now the set's own light holds until the first change.
  - The AI script writer gives co-stars lines (`generate_script(..., others=[{name, about, aliases}])`, the server
    passes `co_stars`). `_clean_lines(text, keep)` keeps `Name:` prefixes of co-stars and `+name` people, splits a
    script the model put on one line, and handles `**Name:**`. `settings.speaker_names(prof)` = id, name and a
    `Name: …` line in the about text (e.g. a profile whose about text says "Name: Ethan") -
    used for directing and to rewrite the AI's prefix to the profile name.
  - Videos page: 🎞 Shots shows the shot sheet.
  - Settings → Free up disk space (`web/storage_web.py`, `/api/storage`): render frames/scenes in `build/` (deleted
    for good), earlier versions (moved to `output/.trash`), every `.trash` folder (emptied for good, listed per
    folder). The voice cache is never cleaned (old videos would get new
    takes). Refused while any job is queued or running.
  - "Says it" on every shot when there's more than one possible speaker (her, co-stars, cast people) - Create page
    and video editor; with co-stars also "The others while this is said" (`listen`, non-moving anims) and
    "Everyone in the frame" (`both`).
  - Fixed while testing: co-stars stood at a fixed spot in the room (out of every shot once she walked off) - now
    beside where she is when they first speak (`_primary_pos_at`); `both` aimed between everyone at a fixed
    distance (an empty middle) - now a side-on two-shot pulled back to fit the span (28 mm).
- **Output language (2026-11-24, tested: `output/zz_test_lithuanian.mp4`)**: scripts/titles are written in
  English; the finished video is in `ep["language"]` or `settings.language` (`catalog.LANGUAGES`: en, lt). At render
  `run_episode.translate_episode` translates the spoken lines (a beat group as one sentence, its words shared out
  over the beats by English word count), the title and the end card (`translation_units`, `translations_for`:
  the episode's own `translations[lang]` first, then `build/translations.json`, then `llm.translate_lines`).
  English stays in `shot["line_src"]` (sound-effect trigger words). `voice_for()` → `language_voice()`: other
  languages use the language's Edge voice (female/male from the character's `gender`, else guessed from the
  English Edge voice name, `MALE_VOICE_WORDS`) - Chatterbox only speaks English (its multilingual model has no
  Lithuanian). Without Ollama a non-English render stops with a clear message. UI: Create → Look → Video
  language + 🌐 Check translation (`/api/translate`, editable, saved to `ep.translations`), video editor Text tab,
  Settings → Render & audio. The local model's Lithuanian needs checking (it wrote "Laukinis" for a plane).
  Add a language: one entry in `catalog.LANGUAGES` with its two Edge voices (`python -m edge_tts --list-voices`).

### Bugs fixed in that review (offline tests + browser checks)
- Props stacked on one spot: `setgen._place_zone` "center" always returned (0, 0.3), so a theme's 2-3 tables
  (cafe) landed on top of each other. It now tries a few spots round the middle and skips taken ones.
- Script lost on redraw: the Create page rebuilt the script box from the directed shots (beats without their
  `[directions]`, `+cast`, `@ scenes`, `Name:`), so directing again dropped them. The typed text is kept in
  `CS.scriptDraft`, and a directed episode stores the script it came from in `ep["script"]`.
- `Mom: …` lines: people brought in with `+name` in the same script are now speakers (`autodirect.direct`
  pre-scans the brackets), so they say their lines with their actor's voice.
- `autodirect.direct` returned a start mark from the LAST scene's set; it is now from the first set (`front`
  when the given one doesn't exist).
- Uploads with accents / non-Latin file names failed in the browser (headers must be ISO-8859-1): every upload
  sends `encodeURIComponent(name)` and the server `unquote`s `X-Filename`.
- Picking a look preset (Create page or video editor) did nothing on a rendered video: `remember_look` had saved
  a full `look`, which wins over the preset. Choosing a preset now drops the saved `look`.
- Videos page Rename/Delete toasted "✓" after a failure. Settings → Reset kept wiping the Postiz key, channels
  and the PIN (now kept). Several outdated UI texts (Audio page, port 8188, "only she speaks").
- Voice cache: a failed ffmpeg run could leave a broken wav in `build/tts_cache` (now written to `.part.wav`
  then renamed); the Windows fallback voice was cached under the Edge voice's key.
- `--no-render` without an earlier render crashed; with a different number of shots it silently mis-timed. Both
  now stop with a clear message.
- Sound generation moved the old sound to the trash before the new one was made (a failure left the slot empty).
- `llm.chat_json` returned lists/strings that callers used as dicts; `make_theme` crashed on odd counts;
  "Generated theme" failed the whole set when Ollama was off (now falls back to auto).
- A new set could silently overwrite another with the same id (name slug + seed % 10000): `make_set` now adds
  `_2`, `_3`... Deleting a set also moves its `.glb` and texture folder to `sets/.trash`.
- `comfy.colour_word` crashed on non-hex colours; ComfyUI jobs that finished without a picture waited 5 minutes.
- Earlier versions of a video now have their shot sheet (one stamp for the mp4 and the png copy).
- Optimisations: `setgen.load_all` caches parsed recipes by mtime (all_sets() runs many times per request);
  `comfy.status` is cached 30 s inside a process (the server's `/api/comfy/status` always asks fresh) and the Sets
  page no longer waits for it; job logs keep their file open while the job runs; old finished jobs are dropped
  from memory (50 kept); Postiz uploads stream the mp4 instead of loading it twice into memory; the map editor
  scans the prop library once; settings and character files are written atomically (`settings.write_json`).
- `web/server.py` `StudioServer` asks Windows for the port exclusively (current Python already refuses a second
  bind - this keeps it that way). PIN checks use `hmac.compare_digest`.


## Test render review (2026-11-24, `episodes/zz_test_cafe_day.json`, dev copy)
A 22-shot cafe → park test render was checked frame by frame. Fixed and checked in re-renders
(`output/zz_test_cafe_day_v2.mp4` … `_v4.mp4`, `output/zz_test_mom_scene.mp4`, pose grid `output/zz_test_pose.mp4`):
- No `tools/voice-venv`: a `local` voice now falls back to the Edge voice with a warning (`_normalize_voice`)
  instead of stopping the render.
- `autodirect.direct`: the opening walk goes TOWARD the camera (`_opening_walk`: to a nearer mark, or in from a
  mark further back to the start, so the episode's `start` can change) - before, she walked away showing her back.
  Walks with no `to` pick the least-visited mark, never `door`/`far` (`_pick_dest`, `EXITS`) - before, every
  auto-walk went to the set's first mark (the cafe door), so she left mid-line. No auto-walk on beats of 1-2 words.
  A walk never keeps a closeup/macro/dramatic camera (`CLOSE_CAMS` → medium follow; the macro camera ended up in
  her hair). A new place opens on a wide shot. A mood-less beat keeps the previous beat's emotion in the same line.
- Sounds: trigger words match endings and stretched letters (`sfx.word_rx`: hissing, Hsssss, popping);
  `sfx.trigger()` = words only. The action's sound (`ACTION_SFX`) only on a line's first beat, and never the same
  sound twice in a row in one line (`"sfx": ""` written so the render doesn't add it back).
- Cast people: an actor with the default voice gets one from their name/looks (`actors.role_voice`: mom → a
  female Edge voice, grandma → elderly, little girl → child; a voice set on the actor wins) - mom used to speak
  with the male `ACTOR_VOICE`. The studio body's head is about twice hers: `CAST_TRACKS` carry `cam_scale` = their
  height and `head_dist` 1.6, so head shots (closeup/dramatic/macro) pull back - mom's close-up filled the frame.
  `autodirect.direct` moves a speaker's arrival (enter/walk_to/run_to/crash_in) to the shot BEFORE their line (and
  makes that shot medium if it was a close one) - mom said her line walking in, filmed from behind because she
  stood in the way. Arrival shots (`blender_cast.FOCUS`) pull back until both fit the frame (an angle test
  per person) - the old fixed push-back left the arrival outside it.
- Gestures at the viewer (`SHOW_ANIMS`: wave, blow_kiss, clap, celebrate, point) get a front medium shot when the
  camera came from the cycle (closeups cut the hand off; the side camera showed the wave in profile).
- `a_facepalm`: upper arm well forward and twisted in (`rotR` -1.6), elbow folded, head down (`nod` > 0 = down) -
  the old arm-out-to-the-side pose read as a salute. Picked from rendered variants; use the same approach (a few
  temporary `ANIMS` entries in one closeup episode, removed afterwards) for other poses.
- "turn on / press / push the / button / grab / pick up" lines → `point` (`ACTION_WORDS`).
- Cutaways: a `fly_by` subject makes a short pass (±2.2 m, 1.7 m up) and the camera follows it from ~3 m (was a
  14 m pass filmed from 6 m: a speck); a cutaway thing with a drawn sprite shows the sprite even when it has parts.
- An episode-level `voice` is the main character's only: co-stars and cast people keep theirs (`speaker_voice`).
- Animals (`propgen.animal_family` by the prop's NAME - "cat bed"/"bird feeder" are not animals, `THING_WORDS`):
  built from a body template (`animal_parts`: bird / beast (four legs) / fish - head, eyes, beak or snout, ears,
  legs, wings/fins, tail), coloured from colour words in the looks, else `ANIMAL_COLORS`, else the AI design's main
  colour; sized by `real_size`; `"animal": fam` and `complex: true` (a ComfyUI sprite still wins when one can be
  drawn). Library animals without `"animal"` are rebuilt once when next used (old file → `assets/props/.trash/
  <kind>-blocks-<stamp>.json`); Assets edits (looks/height/on) are kept. The AI's own animals were a few blocks.
- `point` aims: shot `"at"` (mark name or [x, y]). Director: `[point counter]` (point is the exception to "action
  + mark = walk there"), else a non-plain mark named anywhere in the script line, else - for handling words
  (`HANDLING`: turn on, press...) - the thing she stands at. Blender `point_target()`: hand-built sets'
  `BUILTIN_THINGS` (the machine is behind its mark), a generated set's nearest prop of that kind, else the mark.
  `a_point`: body turns a third of the way (≤ 0.95 rad), the arm on that side covers the rest (behind her: back
  and up over the shoulder). From the front camera a target straight behind her still reads as "off to the side".
- Arrivals (enter/appear, not cutaways) get a camera that can frame both (`ARRIVAL_CAMS`), also when the director
  moves a speaker's entrance - a side shot lost the dog.
Checking poses: renders at `"render_res": [540, 960]` - at the default 216×384 the facing was misread twice.

## Second test round (2026-11-25, "What if cats ran the post office?", made through the dev API like the Create page)
`output/zz_test_post_office.mp4` (before) / `_v2.mp4` (after). Fixed:
- **Imported models first, with stand-ins** (`imported.match`): the name's LAST word is the thing itself; a model
  named after it, or a stand-in from `NEAREST` (van → ambulance/SUV/bus, truck → ambulance/bus, police → Cop,
  dog → Pug, goldfish → fish, dinosaur → Trex...), wins over a model that only shares the other words ("ice cream
  truck" was the IceCream Cone). Synonym hits score less than real ones; `stand_in: true` is logged. Never one
  animal species for another. The dev copy has the user's packs copied from production for testing.
- **Vehicle templates** (`propgen.vehicle_family/vehicle_parts/make_vehicle`, when no imported model fits): car /
  van / truck / bus, coloured from colour words, `VEHICLE_COLORS` (mail = blue, taxi = yellow...) or the AI design;
  real lengths (`VEHICLE_SIZE`), "toy/mini" ones tiny. Built nose-first along -y (moving things turn -y to their
  travel direction). `template_for()`/`apply_template()` cover animals + vehicles; old library ones are rebuilt once.
  The AI's van was four overlapping tilted 4 m slabs.
- Big arrivals (radius ≥ 1.2 m) never land straight behind her unless nothing else fits (`blender_cast.spot`): the
  van filled the background of every later shot.
- Director: happy lines without greeting words rotate `HAPPY_ANIMS` (nod, laugh, clap, idle, celebrate) instead of
  waving (4 waves in 25 s); a walk away from the camera gets `side` + `follow` (her back for a whole line);
  `+mail van crash_in` = one cast member `mail_van` (`_known_word`, also in the speaker pre-scan: "Old lady: ...");
  the AI's own words map onto the vocabulary (`MOOD_WORDS` excited → happy..., `ANIM_WORDS` floating → float_up,
  only when no real action is named).
- Blender: a still camera on a walk frames from the end nearest the camera (walking toward it she ended up almost
  in the lens). `a_sneeze` = forearm across the mouth then the head drops into it; `a_blow_kiss` = hand at the lips
  then thrown forward (both read as waves/points before; same forward + twisted-in arm as the facepalm).
- Sounds: everyday trigger words removed (boing had "what"/"wait", ding "got", tada "did/finally/win", coin
  "point", stomp "fall", fail "wrong/sad/nobody", sparkle "wow", whoosh "fast/fly").
- Title: its own dark outline (`captions.title_outline`, default 1) - over a pale sky it was hard to read.
- Prompts: `place_for_title` starts IN a place the title names (post office → not "busy city street corner");
  `generate_script` asks for family-friendly lines (no swearing) and one-word cast names (`+mail_van`).
- Music is a per-video choice (about half the user's videos have none) - `audio.default_music` left alone.

Round 2b (v2 → `_v3`/`_v4`, same script directed again):
- Weather never comes from an indoor set's defaults: `llm.make_coherent` drops snow/rain/droplets/leaves/petals
  for inside plans, `blender_fx.WEATHER` filters an indoor recipe's default at render (a shot may still ask).
- The AI cast step never casts the main characters (`add_cast_plan(..., skip=names)`, server passes the character's
  and co-stars' `speaker_names`; `run_episode.resolve_cast` also drops them from older episodes) - "catgirl" was a
  generic-human double in every shot. AI arrivals are skipped when the script brings that person in itself.
- `SCARED` no longer matches a bare "run" ("I run the place"): only run!/run away/run for it.
- People given things' verbs (crash_in/fall/fly_by) run in instead (`resolve_cast`).
- Close shots (closeup/dramatic/macro) put captions lower (MarginV 15% of height) - they covered her face.
- Cameras check for blockers (`_view_blocked`/`_clear_view`: floor props from OBST, cast tracks, `blender_cast.TAKEN`)
  at the shot's start/middle/end (along the path for `follow`) and swing round her to the nearest clear angle,
  preferring the camera's side of her.
- Imported models: real heights (`imported.TYPICAL_HEIGHT` by name, else `ask_height` → Ollama, cached in the index
  as `real_height`; `match_model` scales width with it) - files use any units (Pug 2.65, Cow 5.1, Bicycle 3.1).
  `blender_models.recolour_grey`: materials left at Blender's default grey (0.64) get colours from their names
  (`NAME_COLOURS`: Red, Windows, Lights, Wheel...) or the vehicle's body colour (`BODY_COLOURS`) - the Public
  Transport pack had 48/48 grey materials (no texture files exist; previews redrawn in dev only).
- Assets → Imported: models grouped by `imported.categorised()` (categories from model names, `CATEGORIES`; a
  name that says nothing takes its pack's majority category), search + category chips, 🗑 per card, ☑ Select +
  "Delete N picked" (`delete_models`: same-stem files + preview → `packs/.trash/models-<stamp>/`), packs listed
  under a collapsed "Packs" with Remove pack. API: `GET /api/imported/all`, `DELETE /api/imported/model/<id>`,
  `POST /api/imported/delete {ids}`.
- Categories for names the word list doesn't know: `imported.ai_categorize` (Ollama, 40 names per call, may invent a
  category: Utensils, Containers...; spellings merged ignoring case) runs at the end of every import and from the
  🏷 Categorize button (`POST /api/imported/categorize` → job `imported.py categorize [--redo]`); answers are kept
  in the index as `category` and win over the word list.
- Category-aware matching (`imported.match`): every model's category (`category_map`; a single outlier word in a
  70 %+ one-category pack takes the pack's category - the food pack's "Fish"), the setting's categories
  (`SETTING_CATS`: kitchen → Food, aquarium → Animals, street → Vehicles...) rank first, then the thing's own
  category (`kind_category`); indoors (`INDOOR_WORDS`) a Vehicles/Street/Trees/Dinosaurs model is only used when
  the thing asked for is one; words that disagree reject (plant pot ≠ CookingPot; `SYNONYMS` street~traffic); no
  match by the old half-the-words rule (table lamp ≠ Table) - the studio generates instead.
- Duplicates: every model has a SHA-1 `hash` (computed for older ones by `known_hashes`); import skips a file
  already imported or twice in the zip, and one model in several formats (same file name: OBJ kept, then FBX,
  BLEND - `FORMAT_PREF`), moving the copies to the pack's `_duplicates/`. 🧹 Remove duplicates (`find_duplicates`
  / `remove_duplicates`, `GET /api/imported/duplicates`, `POST /api/imported/dedupe`): byte-identical copies and
  same-name-other-format copies → trash (the user's Posed Background Humans pack: 28 models × 3 formats).
  `delete_models` moves only the model's own file (+ an OBJ's .mtl) - not every file with that name.
- ✏️ Name & describe (`describe_models`, job `imported.py describe [--redo]`): the vision model looks at each
  preview and gives a clearer name (keeping the file name's words: "Bacon Burned" → "Burnt Bacon Strip") + a
  one-line description; `original_name` kept, new name words join the tags (matching). ~4 s per model; the small
  model sometimes guesses wrong ("Bacon Cooked" → "Burned..."), hence original_name.

## Look check for made props (2026-11-25)
Every prop the studio makes (AI shapes or a body template: duck, van, ant) gets `propgen.look_checked`: a check
render (`check_render`: blender_build straight, the prop as a one-shot cutaway, 270x480) scored by the vision model
(`look_score`, 1-10, `PROP_PASS` = 5 - was 6, too slow); a fail → the AI redesigns it once from the critique (keeping the real size);
a second fail scoring under 3 → `complex: true` → a drawn sprite (since the 3D-first change, see Prop priority) (ComfyUI + sprite_cut, so only where voice-venv exists - in dev
it keeps the best shape, marked `checked: false`). Library props made before are checked once on their next use.
Templates no longer force `complex` (they're checked like anything else). Mailbox: 4/10 twice → sprite (54 s);
rubber duck via the bird template: 8/10 (19 s). `run_episode.drop_weak_cutaways`: a cutaway only shows a person,
an imported model, a built-in prop, a sprite or a prop that didn't fail the check - "a feline army marching" (four
boxes) filled the screen. The AI cast step skips groups (`autodirect.GROUP_WORDS`: army, crowd, team...). Insects
have a body template (`bug`: ant, beetle, ladybug...); animals/vehicles are decided by the name's LAST word
("ant farm" isn't an ant). An automatic walk is never added to a line whose brackets chose a close camera.
Popup test round ("How big is the space for all your pasts?", haunted library): the wizard now writes the script
for `new:<picked place>` (it said "Welcome to Legacy Cafe"); a `+name` the AI put mid-line is spoken as the name and
is that person's entrance (it said "+tiny_dragon"); smile/frown/wink/glare... are expressions (`MOOD_WORDS`) and
`animgen.IS_ACTION` excludes face-only things; animations that failed the check (< 5/10) aren't used or listed in
`catalog.ANIMS`; size words scale imported models (tiny/baby 0.25, small 0.55, giant 1.8 - a "tiny dragon" was the
3 m Dragon); cast members always count as blocking the camera (the "she stands at it" exception is only for
furniture) - the dragon filled 14 shots; length cards: short 4-5 lines, medium 6-8, long 10-13 (12 lines ran 60 s).

## Look check for sets (2026-11-25)
`make_set.create_set` (AI sets from an idea, with a preview): after the layout the set is saved and previewed
untextured and judged BLIND (`judge_picture`: the vision model says what place it sees + the things in it, NOT
told the target; the text model compares that with the idea → score 1-10, `SET_PASS` = 5 (was 6), + what to add/remove).
Told the target, qwen3.5:4b scored two near-identical empty rooms 4 and 8; blind it called the post office "a cozy
living room (piano)" and a library set "a classroom (blackboard, easel)". A fail → `fix_plan` turns the critique into concrete changes (Ollama: add
[{kind, count, looks}] placed in `showcase` - in the wide shot -, remove [kinds], also from wall_pictures/new_props;
the retry uses theme "random" so a theme can't put them back) and the designer is asked again with the critique
(`llm.design_set(feedback=)`); things it asks to add carry `"generate": True` (setgen skips the imported
stand-in - the user's imported bookshelf is an empty frame - and propgen designs + look-checks one); up to `SET_TRIES` = 2 (was 3: a stomach set took 20+ min; `fix_plan` adds at most 2 kinds), the best-scoring try is kept, then textures + the final
preview. Re-asking with the critique alone repeated the same set 3 times (a "haunted library" with a chalkboard
and no bookshelves, 4/10 each, 12 min). Military parade ground: 4/10 (a park) → 8/10.
- `propgen.squeeze_to_width`: a made prop far wider than the real thing (real width from `real_size`, allowing
  25 % of its height for bits that stick out) is squeezed sideways - a 6 m "flagpole" was 8 m wide and filled a
  set's preview; 8 of 20 library props in dev were too wide (fixed on their next use, also in production).
- Cost: each try can design new props, and each new prop gets its own look check (~50 s) - a set can take
  5-12 min when it needs retries. Settings → AI tools has two switches (both on by default): `sets.look_check`
  (the set check) and `sets.prop_check` (`propgen._prop_check_on`, the prop check + sprite fallback).

## Animations as data (phase 1 done 2026-11-25; plan: generator → vision check → director hookup)
- `pipeline/animlib.py`: pose vocabulary - `ARM` (one arm: arm/raise/rot/elbow; rest, slump, hand_to_chin,
  hand_at_mouth, hand_over_eyes (+0.2 nod), arm_forward, reach_forward, point_side, wave_up, arm_up_high,
  hand_by_face, fist_up, across_body, palm_up_out, hand_on_hip, behind_back), `HEAD`, `BODY` (added). Each arm
  pose was rendered and checked (`hand_by_face` needed rot 1.1 - the surprised values only read with both arms
  plus the hop). Format: `{name, description, length, loop, keys: [{t, R/L/both, head, body}], shake}`;
  `validate()`, `library()` (BUILTIN `x_` examples + `assets/anims/*.json`, gitignored), `sample()`.
- `blender_build` registers every library animation in `ANIMS` (`_anim_player`: arms go to the pose, head/body
  are added, `env` ramp); `catalog.ANIMS` lists them (not `x_`), so `[shrug]` works in scripts and the UI.
  `x_facepalm/x_sneeze/x_blow_kiss` render the same as the hand-coded ones.
- Phases 2-4 (done): `pipeline/animgen.py` - `write()` (Ollama, GUIDE = the pose list + the x_ examples, format
  errors fed back), `check_render()` (blender_build straight, 270x480 @ 12 fps, closeup + medium, candidate passed
  with env `ANIMLIB_EXTRA`, the REAL character via `run_episode.resolve_character` - the stand-in body made every
  pose look wrong), `vision_check()` (qwen3.5 scores 1-10, `PASS` = 5 (was 6); yes/no turned down everything), best try kept,
  up to 2 tries (was 3), saved with its check picture `assets/anims/<name>.png`. `ensure(word, line)`: exists → reuse; else
  `is_action()` (Ollama) → make; non-actions are remembered in `assets/anims/.not_actions.json`. Salute: 61 s, 9/10.
  `hand_to_forehead` pose added (checked: reads as a salute). The user chose automatic making (~30-100 s each).
- Director: unknown bracket words (`[yawn]`) and `[do:salute]` set shot `"want"` (the shot keeps its mood action as
  the fallback); `run_episode.resolve_animations` makes/reuses them before Blender and moves `needs_room`
  animations (arms out) out of close cameras. The script writer is told it may write `[do:<verb>]`.
- Assets → Animations tab (`web/anims_web.py`: `GET /api/anims`, `POST /api/anims/make` job, `DELETE` → .trash,
  pictures at `/animimg/`). Two-arm poses added 2026-11-25 (use with `both`): hands_on_head, praying_hands,
  arms_crossed, cover_ears, hug_self - each picked from rendered variants (scratch tool: temporary ARM entries +
  `animgen.check_render`, 2-3 candidates per pose). Note: `arm` > 0 does NOT swing the arm behind her - this rig's
  arm only goes out sideways/forward and the elbow only bends forward (no thumb-over-the-shoulder pose).

## Third round (2026-11-25): fuller sets, crowds, less walking, word-timed captions
- **Fuller sets** (`setgen.fill_view`, after all props are placed): counts the things the wide shot sees
  (`in_view`: |x| < 0.36·(y+6), `view_count` ignores rugs/fences/hills/wall pictures) and copies the set's own
  small things (`DRESSING` words or kinds it already has 2+ of; never `ONE_OFF` doors/flags/counters, never
  `INDOOR_BIG`) into the `showcase` / new `view` zone (the whole camera cone, keeping the spot just behind her open)
  until `FILL_IN` 9 / `FILL_OUT` 11. Indoor props without a zone favour `showcase` (the left wall and most of a
  14x12 room's floor are outside the wide shot). Fixed: `showcase` put props behind a small room's back wall
  (y up to 4.8 in a 6 m deep room). Existing sets went from 4-7 to 7-11 things in view (offline simulation).
- **Dollhouse walls** (`blender_sets.dollhouse_walls`): indoor rooms also get a front (camera side) and right wall
  with back faces culled and no shadow - invisible from outside, a wall from inside (9 m tall: a lead camera
  looking back saw sky over a 5 m wall).
- **Lead camera** (`CAMS["lead"]`, catalog "lead"): ahead of her walk, looking back, turned along the walk's
  direction in the camera loop. The director uses it for walks away from the usual camera (was `side`, which
  still showed her three-quarters from behind). `_clear_view` keeps a camera on its own side of her.
- **Pointing behind her**: no arm pose reads as "back there" from the front (tried a thumb over the shoulder, a
  straight arm up-and-back, turning side-on - all read as sideways/waving or hid the arm). The director gives a
  point at something behind her (`at` more behind than beside) the `side` camera, and Blender puts the side camera
  on the target's side (else her body hides the pointing arm; dead behind = her right, matching `a_point`).
- **Less walking**: `walk_every` 3 → 8 and never within `WALK_GAP` 5 shots of another walk; new `move_every` 3 =
  a "camera beat" (`CAMERA_BEATS`: side+orbit, low+push_in, high+pull_out...) on static shots; `high` added to
  `CAM_CYCLE`; the script writer is told to walk at most once or twice (change camera, action, place instead).
- **Crowds** (`imported.crowd_def`, `is_group`, `GROUP_WORDS`): "crowd", "audience", "soldiers", "herd of cows",
  "army of dinosaurs" = several imported models in two loose rows (`{"crowd": [defs], "offsets": [[x, y, turn]]}`,
  built by `p_custom`). The group's noun comes from the NAME or "of X" in the description (not every word: "people
  at the beach"); a thing (cow, Trex) is repeated (3 when big); else People-category models (hair-only models
  skipped, one per name in the preferred format), posed by the words (`CROWD_POSES`: cheering → waving, marching →
  walking, running, scared → covering eyes); sitting models only with seat words. One scale per pack from its
  standing people (1.72 m). A named non-person noun with no model ("feline army", no cat) = None (nothing on
  screen rather than people or boxes). Used by `resolve_cast` (before actors), `propgen.imported_def` (set props
  like "marching_soldier_group"), `add_cast_plan` (groups are kept when a crowd can be built), cutaways.
- **Word-timed captions and beat cuts**: Edge TTS is asked for `WordBoundary` events (edge-tts 7 defaults to
  sentences), the local voice keeps Whisper's word times for the take it keeps (`word_timestamps=True`); both are
  saved as `<wav>.words.json` next to the cached take (times from the first word: the start silence is cut).
  `run_episode.word_starts(text, wav, total)` matches them to the line's words (difflib, by spelling; gaps filled by
  word length) → shot `word_t`; captions show each group from its first word to the next group's; a beat group's
  cuts land where each beat's first word is said. Edge lines cached before this have no word times and are redone
  once (quick); local-voice lines keep the old even spread until re-voiced (🎙 fresh voice).
- **Script editor pass** (`llm.polish_script`, on by default in `generate_script(polish=True)`): lists problems
  (made-up facts, broken English, lines that don't follow, repeated jokes, a weak ending) then rewrites only the
  spoken words - each line keeps its own `[directions]` / `Name:` (the model's copies are dropped), a line that loses
  a `+name` or grows past 22 words keeps the original, wrong line count = the script as it was. Asking it to
  "change as little as needed" changed nothing. Titles: `rank_titles` scores them (curiosity, clarity, real
  question) and fixes small grammar slips, best first. Label junk the model copies into brackets (`[cameras:
  macro]`, `[action: shrug]`) is stripped.
- Blender 6: `use_nodes` is only set when a new material/world has no node tree (5.x always has one).

## Explainer objects (2026-11-25, step 1 of the "explainer" plan)
The user compared the studio with a faceless explainer channel (a narrated toilet cross-section) and chose: the
catgirl stays on screen as the presenter, the LOOK never changes (memory: keep-video-look), order = moving
cut-open objects first, then style templates (pacing/content only) + series, later a storyboard step and a gliding
camera.
- Script: `[show: toilet]` brings the object on beside her (it stays until another is shown or `[show: off]`),
  `[show: toilet open]` takes its cover off, `[show: toilet flap]` = a close-up of that part. Director
  (`autodirect.direct`, `shown`): an `appear` event with `to: [x, y]` = 1.5 m beside where she ends that shot, on
  the side towards the middle; every later shot carries `show: {who, open[, part]}`; the show line gets a medium
  two-shot and she points at it (an opening walk-in stays a walk); a part shot gets closeup + push_in; cameras
  that would lose it (side/back/silhouette/tiny/macro) become medium; no automatic walks while it's on stage.
  `blender_cast.spot` takes a `[x, y]` `to`. The script writer is told about `[show:]`.
- Design (`propgen.design_explainer`, at render from `resolve_cast` for cast entries with `"explainer": True`,
  saved as `assets/props/explain_<kind>.json` and reused): first a plain-text "anatomy" answer (sections, real
  sizes, what's inside, what moves), then `EXPLAIN_GUIDE` JSON: SECTIONS placed against each other
  (first/behind/in_front/on_top/left/right + z fraction) and PARTS at FRACTIONS inside them, moves with a hinge
  EDGE and a direction word. `_layout_explainer` turns that into metres: box sections = hollow (back/sides/bottom/
  top walls, `WALL` 3.5 cm) + a front panel `cover: true`; other shapes = the shape as cover + a dark back panel;
  liquids fill their section wall to wall (the AI only sets the level); inner parts are clamped inside the walls.
  Asked for positions in metres, the local model stacked every part on one spot or made a flat slab.
  `_clean_moves`: turn (degrees about x/y/z round a pivot), slide (dir metres, capped at 0.35 x height), spin
  (turns/s), fill/drain (level 0-1), pulse, shake; each with a `word`. Look-checked once more on a fail, never
  made a sprite (the moving parts are the point).
- Blender: `blender_sets.p_explainer` hangs each named group under an empty at its pivot (a turn's pivot, the
  bottom middle for fill/drain, else the middle) and the covers under their own empty (`EXPLAIN[root.name]`).
  `blender_cast.explain_moves`: each move starts when its word is said (`word_frames`: shot `word_t`, else spread
  over the talk; translated videos use `line_src` spread) while it's on stage (moves whose word never comes play
  one after another in its first shot), keyframes every frame, parts stay where moved; the cover slides forward and
  shrinks away at the first `open` shot; show shots without a part go to `FOCUS` (two-shot), part shots to `CUT`
  (target = the part's middle, `z` = its height; `blender_build` uses `cut["z"]` and a 0.8 m minimum distance).
  Size: about 1.5 m tall (a demonstration model), whatever the real size.
- Quality limit: the local model's objects read as diagrams ("a green cabinet" with a tank of water, a gold chain
  and a red flapper inside), not as the real thing - toilet, volcano and heart all score 3-4/10 in the look check.
  The mechanics (open, moves on words, framing, her pointing) work in renders (`episodes/zz_check_explain.json`).
  Tried a bigger local model (qwen3:14b, 2026-11-25): no better (all 4/10 or less) and 2-3x slower - removed at
  the user's request. `ollama.design_model` (Settings -> AI tools, "" = `ollama.model`, `propgen.design_model()`)
  stays: it's used by the prop maker and the explainer maker. Code-set shapes (`ROUND_SHAPES`: volcano -> cone,
  heart -> sphere, tank -> cylinder for the biggest section) didn't save it either: the model put the cone on a box
  column, and for the heart it ignored the sections format.
- **Closed = a drawn picture, open = the cut-away** (the fix for recognisability): with ComfyUI on,
  `design_explainer(comfy_cfg=)` also gets a sprite (`add_sprite`, as other props); `p_explainer` puts the sprite
  under a `__closed` empty and the model under `__diagram`; `explain_moves` swaps them (0.35 s) at the first
  `open` shot (a part close-up counts as open). Never opened = the picture only. Dev has no voice-venv, so no
  sprites here: tested with a stand-in picture (`episodes/zz_check_volcano_pic.json`).
- **Round sections** (`blender_sets._half`): a cone/cylinder/sphere section is bisected down its middle (bmesh
  `bisect_plane` + `holes_fill`, the cut capped in a darker colour): the back half stays, the front half is the
  cover - a cross-section. Box sections stay hollow boxes. Parts carry `"half": "back"|"front"` through `clean()`.

## Templates and series (2026-11-25, step 2 of the explainer plan)
- **Templates** (`pipeline/templates.py`: `TEMPLATES`, `get`, `pacing`, `as_list`; in `catalog.as_dict()["templates"]`)
  = the KIND of video, never the look: `what_if` (default, the classic), `how_it_works` (`[show:]` explainer
  objects, no walks), `quick_facts` (3-5 true facts each with a `[cutaway:]`, faster cuts: beat_words 3,
  move_every 2, wipe_every 3), `mini_story` (`[@ place]` + `+name`, a twist), and since 2026-11-26 `top_five`
  (countdown, `[cutaway:]` per entry), `myth_or_fact` (claim + "Myth or fact?", then the reveal), `this_or_that`
  (two things, a cutaway each per round), `guess_what` (clues hard to easy, the reveal's cutaway last). Lines like
  "Number 5: ..." / "Clue 2: ..." / "Myth: ..." are spoken (`llm.SPOKEN_LABEL`, scripts only - title lists still
  strip labels) and directions written after the label are moved in front of it. `ideas.TEMPLATE_IDS` lists them
  for the Ideas picker. Writer examples use placeholders (`<the entry>`), never a real thing (the whale lesson). Each has title starts + a hint
  (`llm.generate_titles(starts=, hint=)`), extra writer rules + a default tone and line range, and director
  pacing (`beat_words/walk_every/move_every/wipe_every` for `autodirect.direct`). Server: `/api/ai/titles`,
  `/api/ai/script`, `/api/autodirect` take `template`; the episode keeps `"template"`. UI: Create → 1 Idea →
  "Kind of video" (`CS.ep.template`, sets tone + lines), and the random-video popup's first card step (`kind`;
  `MW_STEPS` is built per open from `MW_STEPS_BASE`).
- **Series** (`pipeline/series.py`, job kind `series` in the `other` lane, `POST /api/series {idea, count 1-4,
  template, length short|medium|long, note, character, model}` writes a spec to `build/series/` and runs it): the
  job plans the episode titles (`llm.series_titles`: one question each, different angles, no "Part 1"), then for
  each episode calls the studio's OWN API on localhost - `/api/ai/script` (set "auto", the other titles in the
  notes so they don't repeat, a hook to the next one), `/api/autodirect` (AI cast + scenes), `PUT /api/episodes`,
  `/api/render` - so it gets everything the Create page does, and the renders wait in the render queue. Episodes
  carry `"series": {id, idea, part, of}`; the Videos page shows a 📺 idea part/of pill (`list_videos`). UI: Create →
  📺 Make a series (`openSeriesDialog`).
- **Design server** (the user's brother's Ollama, `10.1.2.196:11435`, online since 2026-11-25 with ONE model,
  `qwen3-coder-next:latest` (80B, 52 GB) - use only that; dev's `config/settings.json` points 3D design at it): `ollama.design_url` +
  `ollama.design_model` (Settings → AI tools, free text: the model must already be on that server - never pull
  there). 3D object design always uses it (`propgen.design_call` for `GUIDE` redesigns, explainer anatomy + plan;
  unreachable → the main Ollama for the rest of the run, `_DESIGN_DOWN`). `ollama.design_scope` "text" (Settings:
  "Use the big server for: all the AI's writing too") also sends every TEXT chat there: `llm._chat` →
  `_remote_for(url, has_images)` reroutes calls aimed at the main `ollama.url` with no images to `design_url` +
  `design_model`; on any failure (unreachable, model missing = 404, bad answer) it falls back to the main url with
  the caller's own model and skips the big server for `REMOTE_RETRY` 300 s (`_REMOTE_DOWN`). Vision checks,
  ComfyUI and voices always stay local (the user: "only things using the LLM purely").
  Test (toilet/volcano/heart): 52-89 s each (local 8B: 80-215 s), 5-8 moves (local 0-4), real cone/ball shapes -
  but still 4/10 in the look check: every designer from 8B to 80B scores 3-4, so the 4B vision judge is now the
  limit, not the designer. A section `on_top` of a cone/pyramid/sphere sinks into it (the crater floated).
  Settings → AI tools: the default model and the big server's model are pickers (`ollamapick`, `GET /api/ollama/models[/big]?url=`
  = the typed address), each with a ✓ Connected / ✗ why
  line, 🔄); `settings.load_settings` strips spaces and trailing slashes from the Ollama fields - production had
  `" qwen3-coder-next:latest"` typed in, his server answered 404 (no such model) and the log said "not reachable"
  (`propgen.design_call` now says which).

## Ideas: trending topics -> video titles (2026-11-25, the user's idea)
- `pipeline/ideas.py`: `gather()` = Google Trends daily RSS for `REGIONS` US/GB/LT (the user chose all three),
  Wikipedia most-read (en + lt) and featured/"on this day" (Wikimedia feed API), and `CALENDAR` (holidays and
  seasons in the next 45 days, offline). Reddit refuses requests without an account (403 on JSON and RSS) - not
  used. Generic User-Agent, nothing about the user is sent. `BLOCK` words (tragedies, politics, crime, weapons,
  betting...) drop items before the AI; `pick_ideas` (Ollama, `PICK`) keeps family-friendly ones as {topic, angle,
  template}, in English, never a named person/brand/film/game franchise (original content), and a topic that's just
  the trending proper name ("Grand Theft Auto VI") is dropped. DB `assets/ideas/ideas.json` (gitignored): ideas are
  only hidden/starred, `used` = episode ids (`mark_used` when an episode with `"idea"` is saved). Stale after 12 h:
  the Ideas page / `fresh` cards start a fetch job (kind `ideas`, other lane) by themselves.
- `web/ideas_web.py`: `GET /api/ideas`, `GET /api/ideas/fresh?n=`, `POST /api/ideas/fetch`, `POST /api/ideas` (own),
  `PUT /api/ideas/<id>` (starred/hidden), `POST /api/ideas/<id>/titles` (`llm.generate_titles` with the idea as
  theme + its template's title starts).
- UI: 💡 Ideas page (`pageIdeas`: filters New/Starred/Used/Yours/Hidden/All, regions, add your own, 🔄 fetch,
  per card ✨ Titles / 🪄 Custom Video / 📺 Series / ☆ / 🙈; a title chip -> `customFromIdea` -> `CS.wizPreset` ->
  the Custom Video popup with title, kind and `idea`). Custom Video's Idea step has a 🔥 trending row (tap = topic +
  kind + ✨ Give me ideas); the random video's topic step deals one 🔥 trending card of three (its idea is marked
  used); the series popup shows trending chips and passes `idea_id` (`series.py` puts it on every episode).
  First dev test: 134 trending items -> 22 ideas in ~35 s (moon phases, why blood is red, solstice, lemurs...).
- More sources (the user, 2026-11-25: "I like to have options"): `ideas.SOURCES` = source -> (Settings switch,
  label): Google News science/technology/health RSS per country (`NEWS_LOCALE`), Wikipedia "Did you know"
  (Template:Did_you_know via the parse API), NASA Image of the Day RSS (the APOD API timed out / gave 500 -
  it is the backup, `ideas.nasa_key` or DEMO_KEY), On this day = the full onthisday/events list sorted by `CURIOUS`
  words (the featured pick was all wars and deaths), the AI keeps the best 1-2 per source, batches shuffled; public holidays
  (Nager.Date, per country) + the offline calendar, Bluesky trending topics (public API), Hacker News front page
  (Algolia API), YouTube mostPopular per country in categories 28/27/15/20 (`ideas.youtube_key`; skipped without).
  Settings -> AI tools -> Ideas: a switch per source + the two keys (`settings.SECRETS`: masked like the Postiz key,
  an API key is also blanked from logged errors). `PER_SOURCE` 30 items per source per fetch (news alone gave 118).
  Region `WW` = worldwide sources. Ideas page: a Source chip row with counts (`ideaSrc`: old "calendar" ->
  holidays). Dev test: 346 items -> 303 after the word filter -> +40 ideas from every source.

## Whales and invisible people (2026-11-25, 6 videos rendered in production)
- Invisible people: the Quaternius "Posed Background Characters" FBX materials import with Principled Alpha 0
  (HASHED) - cast people / crowds / cutaways rendered as only a blob shadow, and their Assets pictures were blank
  white. `blender_models.fix_invisible` (in `load_model`) makes an unlinked alpha < 0.05 solid.
  `imported.previews_all` redraws blank pictures (`_blank_png`: a flat PNG decompresses to a few byte values - the
  blank files were not byte-identical) - also the Quaternius animals, guns and village houses (same cause)
  (`imported.py previews`; 126 blank in production).
- Whales: the Quick facts template's own example was "[cutaway: a blue whale swimming]" and the writer copied it
  into a sleep series as a comparison. The example is gone; the writer and `find_scenes` are told a cutaway shows
  exactly the thing its line names; `resolve_cutaways` drops a cutaway whose subject shares no word with its line
  (beat group). Subject = the words before the first "-ing", last two kept ("an elephant bouncing high" ->
  elephant, was elephant_high; "a stretched rubber band" -> rubber_band).
- Wrong models: "Raw Hot Dog" was categorised Animals and played a dog - `imported.COMPOUNDS` (hot dog, dog house,
  teddy bear...) reject a model whose name has the compound when the thing asked for doesn't. The AI cast step
  skips body parts (`autodirect.BODY_PARTS`: a "head" was played by an imported celebrity head).

## Set styles (2026-11-25): A hand-built bases, B palette, C judged, classic
The user asked why the Legacy Cafe/Park (hand-written in `blender_build.set_cafe/set_park`) still beat AI sets:
one primitive style, a small palette with matching fog/sun, a layout made for the 9:16 wide shot (signature piece at
the back, furniture groups, lamps in the top of the frame, corner framing) and a dressed back wall. Every way of
making a set is now a style (`catalog.SET_STYLES`, `make_set.create_set(style=)`, `--style`, Settings
`sets.style` default "base"):
- **A `base`** (`pipeline/set_bases.py`): 12 hand-built bases (`BASES`: shop, kitchen, bedroom, living_room,
  classroom, office, scifi, hall, street, park, beach, forest), each with 2-3 palettes, fixed pieces built from
  parts in the palette (`WALL` back-wall pieces: window, board, whiteboard, shelf, pictures, clock, neon, porthole,
  banners, torches; `lamps()`; outdoor backdrops `o_buildings`/`o_sea`/tree rows; `HANDMADE` pieces like the
  throne) and SLOTS (`IN_SLOTS`/`OUT_SLOTS`: hero, side, group_a, group_b, corner) with built-in defaults. `dress()`
  = one AI call (base, palette, light, what fills each slot, the two wall pieces); `_Picker` resolves slot things:
  built-in prop > imported (ONE pack per set) > made 3D prop told the palette colours. A table gets seats
  (`GROUPS`). Pieces are custom props with `"exact": True` (no colour wobble in `p_custom`) and `source: "base"`.
  No ComfyUI textures (flat colours, like the Legacy sets), no look check. Not for air sets or picture sets
  (those fall back to classic). `pick_base()` = words, else the AI's pick.
- **B `palette`**: the free AI layout + `set_bases.palette_pass` (made props' colours pulled 35% toward the
  palette, no textures, inside: two wall pieces replace the poster/window wall props + hanging lamps) and one
  imported pack per set (`imported.PACK_LOCK` / `PACK_PREFER`: the first match picks the pack).
- **C `judged`**: the free AI layout + `make_set.legacy_judge` (the vision model compares the preview with
  `sets/_cafe.png` / `_park.png`; the lower of the two scores and its fix drive the redesign; one extra try).
- **classic**: the free AI layout as before.
Who picks: the Sets page and Regenerate popup (`#g-style`, `#rg-style`), the Custom Video Scenes step (cards when a
place is new; `ep.set_style` for places made at render - `run_episode` passes it to `create_set`), random videos
pick one of A/B/C by chance, series always `base` (`series.py` sets `set_style`). Set cards show 🏛/🎨/⚖️.
Tested in production (2026-11-25, one set per base, `Test base ...` / `Test base v2 ...` previews): outdoor bases read
as well as Legacy Park first time; indoor ones needed: a set id (`None.json` was saved), a 10 x 8 room (12 x 10 left
things small and the floor bare), a second group + back-right corner + a centre rug, the hero NOT hidden behind
group_c, a bright plant as the half-in-frame front piece (dark lamps/slabs read as holes), wall pieces only from the
base's `wall_options`, and the AI's slot picks limited: a variant of the default ("cloud_bed", "throne") stays the
hand-built piece, only the hero may be newly designed and only when the idea names it (its "teacher_desk" was a
blue-green slab), other slots = built-in or imported. Known: an outdoor ground patch can look like a dark hole.
- Also fixed: the random video threw "Cannot set properties of null" at the end when you had left the Create page
  (its status line was gone); `watchJob` accepts a missing box and the random flow works from `CS` state.

## Series review (2026-11-25, "What if cats ruled the world?", 4 mini-story episodes rendered in production)
- Walking: no automatic walks in any template (`walk_every` 0) and `autodirect.MAX_WALKS` 2 per video, the opening
  walk-in included (later walks become standing shots, `follow` -> `push_in`); the writer may walk ONCE.
- End card: the last shot's hold is at least `branding.end_seconds` + 0.3 s, so the end card comes after her last
  word (it covered the last caption in all 4 videos).
- Stage directions after the brackets ("[medium] +mom enter from_left Mom! ...") are taken as directions (they were
  spoken and captioned "from left mom"). `[@ kitchen jump]` / `[@library enter]`: direction words glued to a place go
  back to the directions. Light changes only on a line with time words (`TIME_WORDS`: "[night] Wait..." went dark at
  noon). The AI's own words: `CAM_WORDS` (mid -> medium...), `MOVE_WORDS` (zoom_in -> push_in), `JUNK_WORDS` and
  cast verbs / made-up `x_to`/`x_by` are ignored - they used to reach the animation maker (it made "zoom_in",
  "angle", "sidewalk_to", "swim_by" poses). `NOT_PEOPLE`: the sun was cast as a person.
- Others speak for themselves (the user): the writer gives anyone brought in their own `Name:` lines and never has
  her report them ("Mom says..."); `_clean_lines(main=)` keeps another person's `Name:` label (it was stripped, so
  she read Mom's line) and adds `[+name enter]` on their first line; only labels for her (`main`, `NOT_SPEAKERS`)
  go. "nya" at most twice; `*emphasis*` stars removed; `[show:]` only taught for how_it_works (`explain=`);
  `polish_script` checks these too. Series: titles must keep the idea's subject (the "no cat words" rule made
  cats-ruled-the-world titles about gravity and naps); the series note is a MUST.
- Cast people without an actor of your own are played by one of your imported people (`imported.person_def`: a
  woman for mom - `FEMALE_WORDS`/`MALE_WORDS`/`CHILD_WORDS`, the plainest pose), as a thing with a voice (no mouth
  moves); the studio body is the fallback (its hair now always contrasts with the skin - Mom was a brown block).
  Set props named after people ("pedestrian", `PERSON_NOUNS` + `ROLE_WORDS`) also use imported people, never blocks.
- Imported matching: a model renamed by Name & describe matches by its seen name (the file "building-structure" is a
  "Wooden Farm Fence" and was a city's buildings; "Single Bed with Pillow" is a bed, not a pillow).
- Fill the view: at most 2 of each tall thing (`TALL_SINGLES`: lamps, shelves...), 4 indoors / 6 outdoors of others.
- `animlib.library()` skips dotfiles (`.not_actions.json` was read as an animation every render).
- Checked fine in these renders: word-timed captions (every shot had `word_t`), lead camera used, no `use_nodes`
  warnings. The brown blurs are the wipes (`wipe_every`), copied from the reference video on purpose.
- New: Settings -> Free up disk space -> "Everything the AI made" (`storage_web._generated`: sets' recipes, previews,
  .glb, texture folders + the whole prop library) -> `sets/.trash/cleared-<stamp>/`, `assets/props/.trash/...`.
  Assets -> Imported: ✏️ / click a card = your own name, description, category (`imported.edit_model`,
  `PUT /api/imported/model/<id>`; category "" = automatic).

## Create page = three buttons + the Custom Video popup (2026-11-25, the user's mock-up)
- The page shows only 🎲 Make a Random Video, 📺 Make a Series and 🪄 Custom Video (`.hero-btn`, star bursts from
  `sparkle()`), the progress (`#make-status`, `#job`) and the finished video (`#result`). The old step-by-step page
  is still in the DOM but always `hidden` (`#full-ed`): the random flow (`#make-all`) and the save/render buttons
  work through its fields. The user wants everything in the popup - don't bring the old page back as a toggle.
- `openCustomWizard()` (state in `CS.wiz`, kept when the popup closes; `cwFromEpisode(ep, id)` fills it from a saved
  video for the Videos page's ✏️ → "🪄 Open in Custom Video", which keeps the file via `editId`): steps `CW_STEPS`
  idea → look & language → music & ambience → captions → script → scenes → shots → summary. The user asked for
  script before scenes; shots come after scenes (their choice was open, Claude's call) so walks/pointing use the real
  sets' marks. Cards = `cwCards()` (`.cw-card`, `.on` = picked), the step trail jumps back to any visited step.
- Script: `/api/ai/script` takes `scenes` = `stay|move|auto` → `llm.generate_script(scenes=)`; the writer is now told
  about `[@ place]` (before, only `find_scenes` at directing added scene changes).
- Scenes: `POST /api/scenes/plan {script, set, title}` → `autodirect.plan_scenes` (the start - "auto" asks
  `auto_set` - and every `[@ place]` line with up to 3 fitting sets). Picks are written back into the script as
  `[@ <set id>]` / `[@ new:<place>]` (`match_set` passes `new:` through unchanged); "Make it now" runs
  `/api/sets/generate`. Shots: `/api/autodirect` with `scene_ai: false` (the scenes are already decided); the
  🔧 Fine-tune panel reuses `drawShots`/`drawCast` on a temporary episode sharing `W.shots`. Unchanged inputs
  (`cwKey`) keep the shots and any hand edits.
- `.mw-card` animations use fill-mode `backwards` (`both` held `transform: none` and killed the hover lift).

## Quick previews (2026-11-26)
`run_episode --preview storyboard|rough` (Custom Video's last step: 👀 Storyboard / 🎞 Rough preview,
`POST /api/preview {id, kind}` → job kind `preview` in the render lane, files at `/media/previews/`). Nothing new is
made: env `STUDIO_PREVIEW=1` makes `propgen` return stand-ins (`fallback`, no look check, no sprite, no real-size
ask, explainers too), `preview_sets` swaps `auto` / `new:` / missing sets for the closest existing one (never written
back - `resolve_scenes` gets no episode path), shot `want` is dropped. Build dir `build/<name>__preview`.
Storyboard: no voice (estimated timing), 216x384 at 2 fps, `write_storyboard` copies each shot's middle frame to
`output/previews/<name>/shot_NN.png` + `storyboard.json`, no ffmpeg. Rough: real voice, 270x480 at 12 fps, the look
minus blur/fringe/bloom/scanlines/grain/vignette, x264 veryfast → `output/previews/<name>_rough.mp4`, no sheet.
The popup saves the episode first (`W.previewId`), and the real render then uses that same file.

## Stronger opening (2026-11-26)
- Writer (`llm.generate_script`): the FIRST line is a hook (<= 8 words, surprising claim / bold question, no
  greeting, name or "Today we..."); `polish_script` lists a weak first line as a problem.
- Director: `autodirect.direct(opening="hook")` (default) - the first line is a `closeup` + `push_in` on her (medium started ~5 m out: a tiny figure in the first test) with the
  line's own action (a move becomes idle), not the walk-in; `opening="walk"` = the old `_opening_walk`. A `[show:]`
  opening or an action in the brackets still wins.
- Captions: `captions.hook_pop` (default on; Settings → Text & branding): in the first line (its whole beat group),
  `run_episode.hook_word` picks the longest word not in `HOOK_SKIP`, up to 8 letters (longer ones can barely grow inside the frame), the earlier on a tie; its caption group pops in from 40 % to 125 %
  and the word is drawn at up to 2x size (`\fs`, capped so it fits the frame width: 0.92 * width / (0.68 * letters)),
  in its cycle colour. Drawn at render resolution like every caption, so it stays pixelated.

## Cover pictures (2026-11-26)
`pipeline/cover.py`, step 5 of every full render (never fails the video; not for previews): `candidates` = the middle
frame of shots whose camera shows her (`GOOD_CAMS`, no cutaways), scored (close cameras, an expression, early in
the video, her own lines), at most `MAX_CANDIDATES` 8 spread over the video; `grid` tiles them (ffmpeg `tile`,
216x384 each) for ONE vision call (`pick`: "best": n; no Ollama / bad answer = best heuristic score); `render`
puts the frame through `low_res_chain` + the title ASS (`title_ass`: caption font, title colours, second half in
`title_color2`, as big as fits, top third) at render res, then the neighbor upscale and grade ->
`output/<name>_cover.jpg`, `build/<name>/cover.json` {shot, why}. CLI `cover.py episodes/<id>.json [--shot N]` =
`POST /api/videos/<key>/cover {episode, shot?}` (job kind `cover`, other lane; needs `build/<name>/frames`).
`list_videos` gives `cover` (with an mtime `?v=`), the card uses it as the `<video poster>`; earlier versions /
delete / trash carry the cover like the shot sheet. `/media/` serves jpg.

## Recurring cast (2026-11-26)
- Actors (`pipeline/actors.py`) gained `personality`, `regular` (⭐, offered in Custom Video) and `from_video`; an
  edit that doesn't send a voice keeps the actor's old one (a regular always sounds the same). `regulars()`,
  `writer_note(ids)` (what the writer is told: "Name (+id) - role, personality ... bring each in with [+id enter]
  ... their own 'Name:' lines"), `from_cast(who, info)` = an actor from a rendered video's cast entry
  (`build/<name>/resolved.json`): an actor that already played them is copied, an imported person stays that model
  (`def.model.id`), else the studio body with its resolved `look` + `height`; voice = `role_voice`.
- API (`web/actors_web.py`): `POST /api/actors/guests {episode}` (the people in that render), `POST /api/actors/keep
  {episode, who, name}`. `/api/ai/script` takes `regulars` (ids) → `writer_note` in the writer's extra rules.
- Actor dialog → Imported model: every model (the picker stopped at 200; production has ~3000), category chips from
  `imported.category_map` (People first), search across all, "Show more" by 120 (`model_choices` sends `category`).
- UI: Videos → 🎭 Guests (`openGuests`); Custom Video Idea step → ⭐ Regulars chips (`W.regulars`); after directing,
  a regular's cast entry gets `actor: <id>` (`type: person`). Assets → Actors dialog: Personality + ⭐ Regular.
- Script cleanup (`llm._clean_lines`): a bare direction line ("+mom enter, angry", no brackets) goes into the next
  line's brackets - it was half spoken (", angry") and Mom's next line wasn't recognised as hers; "+ name" (space)
  = "+name"; "+name: words" = that person's line, brought in if they weren't yet.

## Batch from Ideas (2026-11-26)
`pipeline/batch.py` (job kind `batch`, other lane; `POST /api/batch {ideas: [ids] (<= 10), length, note, regulars,
model}` writes a spec to `build/series/<stamp>-batch.json`): for each idea `title_for` (its first saved title,
else `generate_titles` with its template's starts) → `/api/ai/script` (its own template, its angle + the note,
`regulars`) → `/api/autodirect` → `PUT /api/episodes` (`idea` = its id, so it's marked used; `set_style` "base";
regulars' cast entries get `actor`) → `/api/render`, reusing `series.call/slug/LENGTHS`. An idea that fails is
logged and skipped. UI: Ideas page ☑ Pick several (`IDEA_PICK`, a Set; card tick boxes, `.picked`) → 🎬 Make the
videos → `openBatchDialog`.

## Production test videos (2026-11-26: `zz_test_hook_goldfish`, `zz_test_guess_animal`)
- Storyboards at 2 fps lost her: `Smoother` took 4 steps per frame, so 1/8 s steps blew the 7 Hz springs up to
  ~1e254 (only the blob shadow stayed). Now `ceil(96 / FPS)` steps (<= 1/96 s; 24 fps unchanged).
- Hook: `closeup` push-in (a `medium` push-in starts at 1.3 x 4 m = a tiny figure); `hook_word` <= 8 letters.
- Myth or fact: the local model put "Myth!" inside the brackets and cast "+second_claim" - `_clean_lines` moves
  `SAID_IN_BRACKETS` words out and drops `LABEL_CAST`. It still writes wrong facts (believes the myths) - a model
  limit; the user checks those scripts before rendering.
- Guess what: a "kudu" had no body template (4 blocks, 3-4/10) - `ANIMAL_FAMILIES` grew (antelopes, deer kin,
  reptiles, more birds/fish/bugs) and `BODY_HINTS` (antlers, hooves, fur, feathers, fins) name unknown animals
  unless the name/looks are a made thing (`MADE_THINGS`: a wing chair). Its spot: no free spot beside her, and
  `blender_cast._roomiest` chose 2.8 m IN FRONT of her (it counts as "in shot") - spots in front now score -2 - depth.
  `sfx_events`: a cast arrival's sound replaces any sound within 0.35 s (boing + pop played at once).
- Top 5 (`zz_test_top5_fast`): a script cutaway landed on the 2-word beat "Number 5:" (half a second) - `_merge_cutaway_beats`
  joins the line's next beats until `CUTAWAY_MIN_WORDS` 4 (in `direct` and after `add_scene_plan`); the AI scene step
  adds no cutaway to a line (beat group) that has one ("faster than a speeding car" got a car); the hook keeps its
  close-up push-in when the writer asked a far camera (`[wide, excited]` on line 1).
- Fine in both: word-timed captions, cover pick (a close-up of her face), stream lengths, a new base set made at
  render (Grassy Field, 19 props). Whole-video loudness ~-16 LUFS (voice -14; the quiet intro/outro lowers it).

## The look check judged HER (fixed 2026-11-26)
`propgen.check_render` puts the prop in a one-shot cutaway, but `blender_build` hid her only when the SHOT had
`cutaway` - the check's shot only had a cutaway EVENT, so she stood in front of every prop and the vision model scored
her legs/skirt/ears ("a human character wearing a skirt", "cat ears, not cheetah ears"). That is why nearly every
made prop scored 3-4/10 since the look check began, why many became flat sprites, and why the Top 5 test video's 7
animal cutaways were all dropped (`drop_weak_cutaways`) after 10 minutes of designing them. Fixed both ways:
`blender_build._is_cutaway(shot)` (shot `cutaway` or any cutaway event) and the check's shot sets `cutaway`.
`propgen.CHECK_V` 2: `look_checked` stamps `check_v`; library props with an older check (or none) are checked again
on their next use - also ones a bad check had made a sprite (not ones the user made a sprite: `form: "sprite"`);
a pass sets `complex: False`. The PROP_PASS/SPRITE_BELOW thresholds were lowered while the judge was wrong - worth
revisiting once props are judged on themselves. Also from that video: a cutaway's subject skips describing "-ing"
words ("a speeding car zooming by" was `car_by`; `ING_NOUNS` keep "building", "ring"...), a cast entry named like
the subject is reused (`key`), more dog/antelope words. A "sandy savanna" was built as the beach base ("sandy" half-matched
"sand"): the park base now has savanna, safari, grassland, prairie, plains.
Cutaways (the user, 2026-11-26): `drop_weak_cutaways` drops a made prop only below `SPRITE_BELOW` (3/10, "not the
thing" - and those get a sprite where ComfyUI runs); a "bit off" 3-4/10 one is shown (the re-rendered Top 5 lost 4 of
5 animals at 4/10 under the old rule; the greyhound passed at 8/10 once the check judged the prop).

## "Who and what appears" cards (2026-11-26)
`pipeline/castcards.py` `cards(ep)` (`POST /api/castcards {episode}`): runs `resolve_cutaways` on a COPY (so
cutaway subjects are cast members, named as at render), then per cast member `card_for` follows resolve_cast's
order without making anything or asking the AI: a `model_id` pick > an imported `def` > a person's actor > an
imported person (`imported.person_def`) > the studio body; things: imported (`imported.match` / `crowd_def`, no
height ask) > built-in prop > the prop library (picture `/propimg/<kind>.3d.png` or the sprite, `look_score`) >
"will be designed". Swaps go into the episode's cast entry and `run_episode.resolve_cast` reads them: `model_id`
(an imported model plays it, people too - they move as a whole; a missing id falls back), `form: "sprite"`
(a drawing in this video only), `generated: true` (its own 3D design). `resolve_cutaways` reuses a cast entry named
like the subject (`key`), so a swap on a cutaway sticks. UI: Custom Video's last step `#cw-cards` (`drawCards`,
`W.castPick {who: {looks, set}}` merged into `build()`'s cast), `pickImportedModel(startCat, query)` = a standalone
model picker (category chips, search, Show more; the name is only the first search when it finds something).

## The check after every render (2026-11-26)
`pipeline/review.py` `check(ep, timing, build, mp4, cfg, requested, ffmpeg)`, step 6 of every full render (never
fails it) -> `output/<name>_check.json {time, issues: [{level warn|info, what, shots (1-based), fix?}]}`:
`cutaway_issues` (shorter than `SHORT_CUTAWAY` 1 s; asked for in the episode FILE - `requested_cutaways` - but not
shown), `cast_issues` (made props with `checked: False` and no sprite, Blender's "no free spot" warnings),
`sound_issues` (`sfx_events` closer than `SOUND_GAP`), `stream_issues` (video/audio lengths, > 90 s),
`picture_issues` (the vision model: shots that should show her, 8 per grid, yes/no per frame "visible?" /
"blocked?" - asked for a list of problems it flagged every far-away shot; each flagged frame is asked again alone at
full size and only kept when it says the same - a small top-down shot was a false alarm). Tested on the broken
2 fps storyboard (caught) and the fixed one + three real videos (nothing after the second look). `list_videos`
gives `check`; the card shows ⚠️ N / ✓ checked (`.check-chip`, popup with 🎞 Show the shots); delete moves the json
too. CLI `python pipeline/review.py episodes/<id>.json` (needs the build folder).

## Ideas round (2026-11-26): story weather, holding, faces, regulars' jokes, conversations, her room, reaction sounds, remixes, weekly plan, covers, stats
- **Story weather** (`autodirect.story_weather`, end of `direct(title=, story_fx=True)`; the server passes the
  title): a sad line outdoors gets `rain` (built-in `park` is outdoor, `cafe` indoor, a `new:` place unknown = none),
  a sad line loses festive particles a word gave it (`FESTIVE_FX`: "nobody came to my party" got confetti),
  celebrate/dance get `confetti`; `DAY_ARC` words in the title/script ("a day in the life", "from morning to night")
  set the light day -> sunset (45 %) -> night (80 %) over the lines when no shot sets a light.
- **Holding** (`autodirect.held_things`, after `story_weather`): a `HOLDABLE` noun (cup, book, coin, plush...) with a
  `HOLD_CUES` word up to 4 words before it ("look at this cup", "my lucky coin", "holding a cookie") -> cast
  `{type: thing, looks: "a small hand-held X", held: True}`, a `hold` event on that line's first shot and `vanish`
  on the next line's; at most `MAX_HOLDS` 3, never on cutaway/show lines, someone else's line, or a thing the script
  brings in; a `point` on that line becomes idle (she pointed with the cup hand). Blender: `_held_shots()` -> `HELD`,
  `holding_pose` blends her right arm to (-0.9, 0.15, 0.3, 0.45) = held up in front at chest height (picked from
  storyboards: palm_up_out stuck the arm out sideways, arm_forward / elbow 1.0 brought it to her face) unless the
  shot's move uses that arm (`RIGHT_ARM_ANIMS`); `blender_cast` keeps a `held` thing 15-35 cm (the "show tiny
  things bigger" rule made the cup 5.5x).
- **Close-up reactions**: expressions `wink` (`Fcl_EYE_Close_R` + MTH/BRW Fun), `blush` (shy smile + two pink discs
  on her cheeks: `VRoidRig.blush`, placed from the `J_Adj_?_FaceEye` bones - 1.25 x eye distance out, 1.75 forward,
  1.15 down - parented to the head bone, scaled in by `face_extras`), `eyeroll` (half lids + the eye bones turned up
  and across over 0.9 s, `eye_up`/`eye_side`, a small head tilt). Eye bones are added outside `BONES` (other
  models: no eye-roll, no warning). In `catalog.EXPRESSIONS` (writer, pickers), `MOOD_WORDS` (wink, blushing, shy,
  unimpressed...). Director `face_closeups`: `FACE_CUES` ("just kidding" -> wink, "aww / stop it" -> blush, "ugh /
  seriously / whatever" -> eyeroll) set the line's expression and a static close-up on the beat with the cue,
  unless the brackets set expression or camera (`_set_expr`/`_set_cam`, removed before returning); never line 1,
  another speaker or a cutaway; `MAX_FACES` 3. Checked in a 540x960 close-up render (`episodes/zz_check_faces.json`).
- **Regulars' jokes**: actors gained `catchphrase`, `gag` (running gag) and `history` (kept by the render:
  `actors.remember(ep)` after the cover - a regular's own speaker lines, last `HISTORY_KEEP` 4 videos, an edit keeps
  it). `writer_note` adds "their catchphrase, said once", "running gag: ..." and "last time (<title>) they said: ...
  a short callback is welcome". Actor dialog: Catchphrase + Running gag fields and a "What they said last" list.
- **Conversations**: template `conversation` (needs a co-star; the writer has them talk TO EACH OTHER, only the
  hook and the last line to the viewer; beat_words 6). Director `conversations(shots, mains)` (mains = "main" +
  the co-star ids from `speakers`; not with one main character): each line of a back-and-forth gets `talk_to`
  (who it answers, else who answers it) - never line 1 or a `TO_VIEWER` line ("comment...", "let me know") - and
  every other line of the run is a two-shot (`both`, unless the brackets chose the camera). Blender `fix_faces(segs,
  who)`: a speaker with `talk_to` turns `TALK_TURN` 0.65 of the way towards them (`_pos_at`). Checked with a
  dev-only copy of her profile as a co-star (`assets/characters/twin.json`, `episodes/zz_check_talk.json`).
- **Her room** (`pipeline/home.py`, set id `home`, "My Room"): `make()` = `make_set.create_set(keep_id="home",
  style="base")` once (Sets → 🏠 Her room → Make, `POST /api/home/make`, job kind `set`). After every render
  `home.collect(ep)` (Settings `home.souvenirs`, default on) keeps one thing from the video - a cutaway subject
  first, then something she held, then another thing; never people, crowds or explainers - in the recipe's
  `souvenirs` (newest `MAX_SOUVENIRS` 10) and `place()` lays them out at `SPOTS` along the walls inside the wide
  shot, clear of the room's own props (0.9 m), as `souv_<kind>` custom props scaled to ~`SOUVENIR_H` 0.6 m,
  `souvenir: True`. `GET /api/home`, `DELETE /api/home/souvenir/<kind>`. `autodirect.match_set`: `HOME_WORDS`
  ("her room", "home", "bedroom") pick it when it exists. Not made in dev (needs the AI dresser): try it in production.
- **Her reaction sounds**: director `reactions(shots)` (with `story_fx`) puts `react` on the first beat of her own
  lines - surprised -> gasp, laugh -> giggle, think -> hmm, celebrate -> yay, blush -> aww, wave -> nya
  (`REACTION_FOR`), at most `MAX_REACTIONS` 3, `REACTION_GAP` 2 lines apart, no cutaways or other speakers.
  `run_episode`: `REACT_TEXT` is said with `tts()` in her own voice (cached; the cloned voice in production),
  timed by `sound_length` (silencedetect to the first silence: a "Huh?!" take was 0.26 s of voice + 1.4 s of
  silence); the line's `lead` and the shot grow by that + `REACT_GAP`, `react_at` = the old lead, and the clip
  joins the voice mix as `("r<shot>", wav)`. Settings `audio.reactions` (default on). Checked in a dev render
  (`zz_check_react`): the gasp at 0.85-1.09 s, the line from 1.24 s.
- **Variations** (`POST /api/variation {episode, mode part2|kind, template, length}`): a one-idea batch spec
  (`idea.id` None, topic = the title, the template's own or the chosen one, a note with what part 1 said) with
  `variation_of {id, title, mode}` -> `batch.py` writes, directs, saves (`variation_of` instead of `batch`/`idea`)
  and queues the render. Videos: 🔁 Variation (`openVariation`), pill 🔁 Part 2 / Variation.
- **Remixes** (`POST /api/remix {episode, variants: [{set?, look_preset?, language?}] <= 3}`): copies of the
  episode (`<id>_rmxN_<stamp>`), a new set = the script directed again there (`autodirect.direct` with the
  template's pacing; cast merged), a look preset drops the saved `look`, a language drops the translations; all
  carry `remix {group, of, what}` (the original joins the group as "original") and are queued with
  `queue_render` (the render route's job, shared). ⚖️ Compare (`openCompare`): the group's videos side by side,
  ⭐ Keep this one = `POST /api/remix/pick` (`remix.picked`). Tested in dev (Game Boy + Legacy Park remixes).
- **Big text server time limit** (found while testing): a call to it waited the full 5-minute chat timeout when the
  80B model was slow, and it was tried again every 5 minutes - a script hung 10+ minutes. Now `REMOTE_TIMEOUT`
  120 s, then this PC's Ollama, and a too-slow server is skipped `REMOTE_SLOW_SKIP` 30 min; `_remote_alive` (a
  4-second `/api/tags` check, kept 60 s) skips an unreachable server or one without the model at once.

## How an episode becomes a video (`pipeline/run_episode.py`)
1. Resolve the **character** profile (`settings.active_character` or episode `"character"`), **co-stars**
   (`resolve_co_stars`), **cast** (`resolve_cast`), **scenes** (`resolve_scenes`: `new:<place>` sets are made now and
   written back), **cutaways** (`resolve_cutaways`), the **set** (built-in code or `sets/<id>.json` recipe embedded as
   `set_recipe`, `embed_set`), render size/fps and voice layers (global < character < episode < shot; a layer with a
   different `engine` replaces the previous ones; `speaker_voice` picks the speaker's own voice).
2. **Voice** per line (`tts()`; engines `local` Chatterbox clone / `edge` / `elevenlabs` / `windows`), cached in
   `build/tts_cache` by hash of text+voice. Local lines are batched (`prefetch_local`) so the model loads once, and
   each take is Whisper-checked and regenerated if words are missing. Emotional shots raise `exaggeration`. Beats
   of one script line (`beat_group`) are voiced once as one take and split by word weight. Voice is loudness-
   normalised to -14 LUFS.
3. Shot durations = max(given, lead + speech + tail_pad); first shot gets `audio.intro`, last gets `audio.outro`
   (per-shot `lead` is used by Blender lip-sync, captions and audio delays - keep them consistent). `talk` = speech
   length, written into each shot.
4. **Blender** (`blender_build.py`, headless) builds set + characters + cast + procedural animation (one keyframe
   per frame) + cameras + particles, renders PNG frames to `build/<episode>/frames`, writes `timing.json`.
   Consecutive shots in the same set = one Blender pass in `build/<ep>/scene<N>/`, frames renumbered into `frames/`.
5. **ffmpeg**: low-res chain (tint, dither/colour-depth, captions via ASS at render resolution so text is pixelated
   too) → nearest-neighbour upscale → blur/fringe/grade/bloom → scanline multiply → grain/vignette/fades → blurred
   foreground wipes at shots marked `wipe`; audio mix = voice + music (5 %, fades) + sound effects (timed to trigger
   words) + ambience loop (switches per scene). Output `output/<episode>.mp4` + `_shots.png` contact sheet (taken
   from the finished mp4). The previous mp4 is kept in `output/previous/` on re-render.

## File map

**Core pipeline**
| Path | What |
|---|---|
| `pipeline/run_episode.py` | The whole render (above). `resolve_*` steps, `tts`, timing, ASS captions, ffmpeg chain, `segments`/`segment_episode` for multi-scene videos. |
| `pipeline/catalog.py` | Shared vocabulary: `ANIMS`, `EXPRESSIONS`, `CAMERAS`, `MOVES`, `CAST_VERBS`, `PERSON_WORDS`, built-in `SETS` (cafe, park) + `all_sets()` (merges `sets/*.json`, hides `sets/.hidden.json`). Used by Blender, server, director, LLM. |
| `pipeline/settings.py` | `DEFAULTS` (render, look, captions, branding, voice, audio, sfx, ollama, comfy, sets, server, postiz), `LOOK_PRESETS`, character profiles, `layered_voice`, `public_settings` (masks secrets), `write_json` (atomic JSON write - use it for files the app and the user both touch). Saved to `config/settings.json` (deep-merged over defaults). |
| `pipeline/autodirect.py` | Script lines → shots by mood keywords; `[closeup, angry, boom, walk_to_center]` bracket directions; `+name verb` cast directions (`_take_cast`); `Name: line` speakers (`SPEAKER`); beats (`expand_beats_grouped`: long lines split into ~4-word shots, `walk_every` / `wipe_every`); `beat_sets` (rotate places per line); `match_set` / `auto_set`; `add_cast_plan()` / `add_scene_plan()` merge the Ollama plans. |
| `pipeline/blender_build.py` | Blender scene builder. Placeholder rig + `VRoidRig` (maps world-axis pose channels to VRoid bones; ears auto-detected), procedural anims `a_*`, expressions → VRoid `Fcl_*` shape keys, one track per main character (`CO_STARS`, `SPEAKER_POS`, `fix_faces`), cameras `CAMS`, per-shot lighting `LIGHT_KEYS`, built-in sets, walking obstacles (`OBST`, `_route`), `_still` preview mode, `_export_glb`. |
| `pipeline/progress.py` | Job progress: `report(frac, stage)` prints `PROGRESS 0.42 Stage` (the server turns it into `job.progress`/`job.stage` and keeps it out of the log), `FrameWatcher(folders, total, lo, hi)` counts rendered PNGs while Blender runs, `quiet()` mutes nested steps. The web app's top-right bar (`updateQueue`/`drawQueue`/`drawJobPanel`) shows it; click = panel with live logs. |
| `pipeline/fonts.py` | Font lookup for libass (legacy family names). |

**Sets and props**
| Path | What |
|---|---|
| `pipeline/setgen.py` | Set recipes: `generate_random()`, `generate_from_plan()` (Ollama plan → validated layout; unknown props → `propgen`, `liquid` → pool/river/sea `kind: "liquid"`), `generate_air()`, placement zones `_place()` (`showcase` = in the wide shot; sides `far@left`), `_marks_for()`, `place_on_surfaces`, `set_room()`. `THEMES` (cafe, park, bedroom, classroom, arcade, kitchen, living_room, forest, beach, snow, city, desert, space_station, graveyard, candyland) + saved themes in `sets/themes/*.json`; `THEME_WORDS`, `theme_for(plan, choice)`, `theme_list()`. |
| `pipeline/blender_sets.py` | Builds set recipes from ~40 primitive props (`p_<kind>`, front faces −Y), `p_custom` (propgen defs), `p_sprite` (billboard cut-out), `p_model` (imported), `p_balloons`, floors/walls/sky (`_room()`), ComfyUI textures (`textured_panel`, `texture_world_uv`, `sky_backdrop`), `make_thing` for cast. |
| `pipeline/make_set.py`, `set_preview.py` | `create_set()` (also called by run_episode for scene changes): theme → Ollama design (text or picture) → `llm.make_coherent` → new props → layout → optional new ambience slot (`new_ambience`) → ComfyUI textures → preview `sets/<id>.png`. `apply_picture_colours`, `--replace`. |
| `pipeline/set_export.py` | Exports a set to `sets/<id>.glb` (+ refreshes its preview) for the 3D view. |
| `pipeline/starter_sets.py` | "Generate 3 Starter Sets": picks ideas from `STARTER_IDEAS` and builds them with make_set. |
| `pipeline/propgen.py` | AI-made props: Ollama designs an object as primitive parts (box/cylinder/cone/pyramid/sphere/rock, pos/size/rot/color/glow) → `clean()` (ground, recentre, gravity `_settle`, size caps) → `assets/props/<kind>.json`, reused by later sets. Recipes embed the defs they use (`custom_props`). `needs_picture(d)` (complex or no parts) → `add_sprite()` (ComfyUI `object_sprite` + `sprite_cut`). `real_size()` asks the real height/width and floor/table/wall. `redraw` CLI for the Assets page. |
| `pipeline/sprite_cut.py` | voice-venv (Pillow): cuts a Z-Image object drawn on flat magenta out to an RGBA sprite (edge flood fill, hole cleanup, fringe erosion, crop, ≤128 px). |
| `pipeline/picture_colors.py` | voice-venv (Pillow): sky/middle/ground colours and palette of a picture (scene from a picture). |
| `pipeline/blender_fx.py` | Particle effects `FX` (rain, snow, droplets, bubbles, dust, specks, sparkles, embers, petals, leaves, confetti, beams, stars, speed_lines, fireflies, hearts, music_notes, coins, candy, puffs, sprinkles, pixels, bolts, bats, paws). Shared mesh per shape, per-object colour, world-space motion wrapped in a box between each shot's camera (`CAM_POS`) and her. Shot `particles` or the set's default. Runs after the cameras. `effective()` applies `assets/fx_overrides.json`. |
| `pipeline/fx_preview.py` | Looping preview clips of the effects → `assets/fx_previews/<fx>.mp4/.jpg` (stars/fireflies on a night set). |

**Characters, cast, imports**
| Path | What |
|---|---|
| `pipeline/prepare_character.py` | VRM → `.blend` (decimate, 128 px textures, hard alpha cut-out, fog-ready materials with `fog_in`/`fog_out` nodes) + `.report.json`. |
| `pipeline/character_preview.py` | Still preview `assets/characters/<id>.preview.png`; runs after a model import and from the Characters page. |
| `pipeline/blender_cast.py` | The rest of the cast, on the global timeline after the main characters: people = `build_catgirl(look, cat=False)` driven by the same ANIMS (they can talk: mouth from `talk`); things = `blender_sets.make_thing` keyframed by verb (enter, crash_in + debris, fall, fly_by, appear, vanish, exit, bounce, spin, shake, hold). `spot()` (beside her, in the marks area, in view, not `hidden()`) → `_roomiest()` fallback (`_gap()` clearance, warns). `attach_to_hand`, `CUT[si]` for cutaways. Warns when a thing has lines. |
| `pipeline/actors.py` | Actor store (`assets/actors/<id>.json`, deleted → `.trash`): extra people, kinds `generic` (studio body dressed with `look`), `rigged` (a .blend), `imported`. Matched to cast names by role; a cast person speaks with its actor's voice (default: picked from the role by `role_voice`). The generic human (`GENERIC_ID`) is built in. Not the main characters (those are in `assets/characters`). |
| `pipeline/imported.py` | Imported asset packs: zip import (safe extraction, nested folders), MDL conversion, Blender measuring, pictures (`make_previews`), `match(kind, looks, setting)`. Index `assets/imported/index.json`. CLI `imported.py import <zip> --pack NAME --license TEXT --source ORIGINAL.zip`, `imported.py previews`. |
| `pipeline/imported_probe.py`, `imported_preview.py` | Inside Blender: measure each model; render a still of each for the Imported tab. |
| `pipeline/blender_models.py` | Loads OBJ/FBX/BLEND models inside Blender (`load_model`, `bounds`, `clear_scene`). |
| `pipeline/mdl_convert.py` | Pure-Python converters: Quake 1 (IDPO v6), Half-Life (IDST v10), Source (IDST + .vvd/.vtx) → OBJ + MTL + PNG. Only tested on self-made files. |

**Audio, AI clients, other tools**
| Path | What |
|---|---|
| `pipeline/local_tts.py` | voice-venv: Chatterbox batch + Whisper QA. |
| `pipeline/sfx.py` | Sound slots (built-in synth recipes, custom slots, trigger words, theme→ambience), `generate_sound()` (Ollama → parametric synth `build_sound`), `suggest()` (custom slots win over built-ins), `list_library()`. |
| `pipeline/music_gen.py` | ACE-Step via ComfyUI, or ffmpeg chiptune synth fallback → `assets/music/gen-*.mp3`. |
| `pipeline/llm.py` | Ollama: `generate_script`, `generate_titles`, `design_set` (text or `image=`), `make_coherent`, `make_theme`, `find_cast`, `find_scenes`, `place_for_title`, `social_copy`, `chat_json` (format=json). |
| `pipeline/comfy.py` | ComfyUI client: status/models, `find_server`, Z-Image + checkpoint txt2img, `texture_set(mode=required|auto)`, `object_sprite`, `floor_prompt`, `colour_word`. |
| `pipeline/postiz.py` | Postiz client: `channels()`, `upload()`, `captions()` (`llm.social_copy` + `TRENDY` tags), `draft()` (POST /posts type "draft", one per ticked channel, `settings_for()` per provider; discord needs a channel ID). Base `<url>/api/public/v1`, header `Authorization: <key>` (no Bearer). **Drafts only - never schedule/publish.** |
| `pipeline/review.py` | The check after every render: missing/hidden her, short or lost cutaways, weak props, sounds, streams. |
| `pipeline/castcards.py` | Custom Video's "who and what appears" cards: what plays each cast member / cutaway, no AI. |
| `pipeline/batch.py` | Batch from Ideas: several ideas -> one video each through the studio's own API. |
| `pipeline/cover.py` | The Reel's cover picture: best frame (vision pick from a grid) + title in the video's look. |
| `pipeline/gif.py` | Video → GIF: palette from all frames, Sierra dithering; keeps under 10 MB by stepping down fps, then size, then colours. |

**Web app**
| Path | What |
|---|---|
| `web/server.py` | Stdlib HTTP server + job queue, REST API, Range-capable media, optional PIN (cookie; localhost exempt). Queue `LANES` = `render` (videos) / `scene` (set jobs: make_set, previews, 3D views, starter sets) / `other` (props, fx, music, sfx, imports, character previews, Postiz, GIF, voice tests); one job at a time per lane, `lane_of()` picks it from the job kind. `remember_look`, `set_layout`/`save_set_layout`, `POST /api/jobs/<id>/retry`, `POST /api/server/restart` (starts a detached copy that waits for the port). |
| `web/app.js`, `style.css`, `index.html` | Vanilla SPA (no build). Pages: Create, Sets, Assets (tabs Props / Imported / Actors / Effects / Music / Sounds; `#audio` still routes to Music/Sounds), Videos, Characters, GIF, Settings. Dialogs: `openModal({title, body, buttons, wide, onOpen})`, `uiConfirm()`, `uiPrompt()` - use these, never `prompt()`/`confirm()`. Mobile layout ≤760 px; PWA manifest + icons (`web/make_icons.py`). Create-page state is `CS`. |
| `web/actors.js`, `actors_web.py` | Assets → Actors tab UI (loaded after app.js) and `/api/actors`. |
| `web/imported_web.py` | `/api/imported` (upload, models list, delete). |
| `web/episode_edit.py` | Video editor save (`POST /api/episodes/<id>/apply`): cast model choices, camera marks fixed per scene. |
| `web/gif_web.py` | `/api/gif`; uploads → `output/gifs/uploads/`, results → `output/gifs/`. |
| `web/storage_web.py` | `/api/storage` (GET sizes, POST `clean` frames/previous/trash) for Settings → Free up disk space. |
| `web/viewer.html` | 3D view (three.js from unpkg, orbit by drag, zoom by wheel); loads `/api/sets/<id>/model.glb`. |
| `web/logs.py` | Terminal + `logs/server-YYYY-MM-DD.log` (IP, browser, method, path, status, ms, changed fields with secrets masked) + `logs/jobs/<id>.log`. Routine polling/static files stay out of the terminal but are in the daily log. |
| Other API | Assets: `/api/assets/props` (GET list + usage, PUT edit, POST `<kind>/redraw`), `/api/assets/fx` (GET, PUT/DELETE overrides, POST preview job); images at `/propimg/`, `/fxprev/`, `/charimg/`. Postiz: `/api/postiz/channels`, `/captions`, `/draft` (job). Set layout: `GET/PUT /api/sets/<id>/layout`. |

## Data formats
- **Episode** (`episodes/<id>.json`): `title`, `set`, `start` (mark), optional `character`, `co_stars`, `cast`,
  `look_preset`, `look`, `captions`, `branding`, `music` (path or `""` = none), `ambience` (`auto`/slot/`""`),
  `voice`, `language` (output language, default `settings.language`), `translations` (`{lang: {english: text}}`,
  checked by hand), `script` (the text it was directed from - kept so directing again doesn't lose the `[directions]`),
  `shots[]`. The web app gives every new video a unique id (title slug + stamp). The first render stores
  the look/captions/branding into the file (`server.remember_look`) so later global changes don't alter old videos.
- **Shot**: `line`, `camera` (+`zoom`), `move`, `action` (+`to` mark or `[x, y]` for `*_to`, `face`, `times`,
  `height`, `turns`), `expression`, `duration`, `voice` (e.g. `{"exaggeration": .9}`), `sfx` (name, list, or `""`;
  missing = auto), `sfx_at`, `sfx_volume`, `actions[]` (multi-action), `particles`, `set`, `events`, `cutaway`,
  `speaker`, `beat_group`, `wipe`, `light` (day/sunset/night/dawn - the sun and world colour change from that shot
  on), `listen` (anim for non-speakers), `both` (a two-shot of everyone). `talk`/`lead` are written by run_episode.
- Vocabulary (`catalog.py`): anims idle, turn, walk_to, run_to, sneak_to, jump, wave, surprised, sad, angry, think,
  laugh, dance, spin, celebrate, nod, shake_head, point, stretch, sit, look_around, scared, blow_kiss, clap, bow,
  sneeze, facepalm, shiver, float_up, land, fall, float. Cameras wide, medium, closeup, side, low, high, dramatic,
  back, macro (eyes), tiny (small figure, big scene), silhouette. Moves static, push_in, pull_out, orbit, follow,
  shake. Expressions neutral, happy, surprised, angry, sad, smug, scared.
- **Main characters / speakers**: episode `co_stars` = character ids (or `{"id", "start"}`); `resolve_co_stars`
  loads full profiles. A script line `Ethan: …` (character name or id, or a cast person's name) sets shot
  `speaker`; no speaker = the episode's character. Each main character is its own track in Blender; non-speakers
  idle (or `listen`) and turn to the speaker. Cast people can speak too, with their actor's voice: anyone in the
  episode's cast or brought in with `+name` in the script's brackets (if `cast_kind` says person). Things can't.
- **Beats**: Create → "Cut to a new shot every few words" (`beat_words` 4, default on) splits long lines into
  shots of ~4 words (cut at punctuation), so the camera cuts every 2-3 s like the reference videos. Every 3rd beat
  she walks (`walk_every`), every 4th cut gets a blurred wipe (`wipe_every`). Picking two or more places on the
  Create page (`beat_sets`, can include `new:<place>`) rotates the set per script line.
- **Cast**: episode `cast` = `{name: {type: person|thing, looks, look?, height?, prop?, def?, start?, actor?}}`,
  shot `events` = `[{who, do, from?, to?, at?, duration?, sfx?}]`. Verbs in `catalog.CAST_VERBS` (+ any anim for
  people). `resolve_cast()` fills `look`/`height` from the description, designs things via `propgen`, and turns a
  `thing` whose looks say "human" into a person.
- **Scenes**: shot `set` (another set id, or `"new:<place>"` = made at render, ids written back). Script syntax
  `[@ place]` (lasts until the next `@`); `match_set` reuses sets by name/description words (generic words
  ignored); `add_scene_plan` merges `llm.find_scenes` (AI picks are verified; needs a move verb).
- **Set "auto"** (Create → Set → ✨ Auto from the title): `auto_set(title)` → `llm.place_for_title` → `match_set`
  or `"new:<place>"`. Resolved by the script/autodirect endpoints (response `set`, the UI switches the dropdown) or
  at render by `resolve_scenes`.
- **Cutaways**: shot `"cutaway": "<what to show>"` (script `[cutaway: …]` / `[cut: …]`, the 📷 field, or
  `llm.find_scenes` "cutaways"). `resolve_cutaways` makes a cast member (reused by name) + an event with
  `cutaway: true` and a verb from the words (flying → fly_by, falling → fall, marching → enter, else appear).
  In Blender she's scaled to ~0 for that shot (voice-over), the subject stands where she was, `CUT[si]` frames it by
  the sprite's drawn size, and it vanishes after the shot.
- **Floating / holding**: `float_up` raises a persistent altitude (`alt0/alt1` on segments, `start_alt`;
  `airborne()` adds height + dangling legs + right hand up), `land` ends it. Cast verb `hold`: the thing follows her
  right hand (COPY_LOCATION, `attach_to_hand`, `RIG.hand`) until its next event. Built-in prop `balloons`.
  autodirect: balloon lines → `+balloons hold`, `FLOAT_UP` (about her) → float_up, `LANDING` → land ("pop" vanishes
  the balloons); ground-only actions become idle while airborne.
- **Air sets** (`"air": sky|space|underwater|core`, `"motion": fall|float`): no ground, props float in a 3D column
  and (falling) stream upward, wrapped; shadows hidden; shots become `fall`/`float`. Plans with `where: "air"` +
  `air_kind`.
- **Set recipe** (`sets/<id>.json`): `indoor`, `light` (day/sunset/night), `palette`, `floor`, `fog`, `room`,
  `props[]` (`kind`, `pos`, `rot`, `z`, `scale`), `custom_props`, `marks` (walkable places → "Starts at"/"To"),
  `ambience`, `particles`, `texture_prompts`, `textures` (slot → `sets/<id>/<slot>.png`), optional `air`/`motion`.
  Positions in metres, rotation in radians.
- **Character** (`assets/characters/<id>.json`): `name`, `about` (fed to the script AI), `model` (.blend), `voice`,
  `tail*`, `camera_scale`, optional `ear_bones`. Import one on the Characters page (VRM → `<id>.blend`); a reference voice goes to `assets/voices/<id>.wav`.
- **Sounds**: `assets/sfx/builtin/*.wav` (synthesised), `assets/sfx/custom/<slot>.<ext>` (+ `.json` if generated),
  `assets/sfx/custom_slots.json`. **Music**: `assets/music/`.
- **Videos**: `output/<id>.mp4` + `_shots.png`; `output/labels.json` (display names from Rename);
  `output/previous/` (earlier versions, listed with an "Earlier version" tag, can go to Postiz as drafts);
  `output/.trash/` (deleted). Re-rendering a changed script from the Create page makes a NEW video
  (`CS.rendered`/`CS.keepId`); ✏️ Edit on the Videos page (`openVideoEditor`) keeps the file.

## How the bigger systems fit together

**Prop priority: imported model > generated 3D (primitive parts) > 2D picture.**
- `imported.match()` is checked first wherever a prop is needed (`propgen.design`, `setgen.generate_from_plan` -
  imported kinds get the key `imp_<kind>` so the built-in of the same name isn't used - and `resolve_cast`).
  Matching: at least half of the kind's words must be in the model's file or folder name. Imported props render
  through `p_model` (normalised to their height, on the ground).
- Generated props are a 3D model OR a 2D sprite, never both (the user, 2026-11-25): `propgen.shown_as_sprite` /
  `needs_picture` = no parts, or `complex` (= sprite form). `complex` is set ONLY by a clear look-check fail
  (`look_checked`: best score after the redesign < `SPRITE_BELOW` 3 - a 3-4 "bit off" stays 3D; the 4B judge gives
  most fine props 3-4, which had made 45 of 60 dev props flat) or the Assets page (🖼 Make it a sprite = `redraw`
  sets `complex` + `form: "sprite"`; 🧊 Use the 3D model = PUT `form: "3d"`). The AI's own "complex" guess is
  ignored (`clean()`), and `library()` turns old guessed / 3-4-score ones back into 3D on load. Only sprite-form
  props get a ComfyUI drawing (cast things, old set props and cutaways no longer get one; cutaways no longer swap a
  3D model for its drawing). Explainers: a closed drawing only when its look score < 3. `p_custom` uses the parts;
  the sprite (billboarded per shot camera with LOCKED_TRACK) only for sprite form. Library form changes reach sets
  (`embed_set`) and older episodes' cast copies (`resolve_cast`). The look check's render is kept as the 3D prop's
  picture (`assets/props/<kind>.3d.png`, `/propimg/`). Assets has two tabs: 🧊 Props (3D) / 🖼 Sprites (2D)
  (`prop_info["form"]`). Small "table" things go on tables/counters.
- Library edits (Assets → Props) win over the copies embedded in sets (`run_episode.embed_set`).
- Imported packs: `assets/imported/packs/<pack>/` (originals), `_converted/` (MDL → OBJ), `previews/<id>.png`.
  Deleting a pack moves its folder to `packs/.trash`.

**Making a set** (`make_set.create_set`):
1. Theme: `setgen.theme_for(plan, choice)` - `auto` (THEME_WORDS in the idea), `random` (free AI layout, can be
   odd), `generated` (`llm.make_theme` writes one and saves it to `sets/themes/`), or a theme id. A theme's props
   replace the AI's prop list, and its `floor` and `room` apply. Picture scenes always use `random` (or the
   picture's own objects get swapped out).
2. Plan: `llm.design_set` (text) or `design_set(image=...)` (vision model). Every plan goes through
   `llm.make_coherent`: climate-matched ground/colour and weather particles (no snow in a desert).
3. Room size: `set_room("small"|"medium"|"large")` = 7×6, 10×9, 14×12 m, stored as `recipe["room"]`.
4. Picture input: `apply_picture_colours` (Pillow colours → sky/walls/ground and `_floor_for`). `"side":
   left|centre|right` becomes a zone `place@left` (`_place_hint`); `_place` keeps only spots on that side.
5. Textures (ComfyUI mode Required / Only when needed / Off): `comfy.floor_prompt(recipe)` = ground type + colour
   name + the scene's description.
6. Ids: name slug + `seed % 10000`; a new set never overwrites an existing file (`_2`, `_3`... is added).
   Regenerate: `--replace <id>` backs the old files up to `sets/.trash/replaced-<id>-<stamp>/`, then builds under
   the same id. The popup sends idea, name, theme, room, ground, light, AI, textures, seed.
7. Map editor (Sets page): drag/turn/resize/add/remove props via the layout API; the old recipe goes to
   `sets/.trash/layout-...`.
8. 3D view: `set_export.py` runs `blender_build` with `_export_glb` and `_still`; shown in `web/viewer.html`.
- Built-in Legacy Cafe / Legacy Park (`catalog.SETS`, hand-placed in `blender_build.set_cafe/set_park`) can't be
  regenerated; they keep their ids because old videos use them.

**Create page "Make a whole video"** (🎲 Make a random video): `openMakeWizard()` - a popup with a little magic
animation (`mwMagic`) between steps and three random cards per step (🎲 Three more, ← Back): place, topic, vibe
(the script tone), guest, time ("day turning into night" asks for [sunset]/[night] changes), length (lines), then an
optional typed note. `MW_STEPS` holds the card lists, `MW_LIGHT` maps the time to the set's light. Then: titles
(theme = topic) → script (tone + extra = place/guest/time/note) → a new set (idea = place + title) → direct →
render. CSS `.mw-*` in style.css (respects prefers-reduced-motion).

## Gotchas learned the hard way
**Tooling / Windows**
- Don't patch files through bash heredocs that contain `\n` / `\b`: escapes turned into real newlines/backspaces
  (broke app.js and a regex), and exact-match patches silently stop matching. Write patch scripts with the Write
  tool, or use Edit. Most files use CRLF (Python's `write_text` on Windows writes CRLF); a few are LF. Both
  work - Git Bash `grep $'\r'` did not detect them reliably, so check line endings from Python.
- PowerShell `Out-File`/pipes add a UTF-8 BOM - read JSON with `utf-8-sig`; prefer temp Python scripts over long
  `python -c` one-liners (quoting breaks).
- Windows Application Control can block DLLs in `tools/voice-venv` (a sklearn `.pyd` broke a render). That's a
  security policy - report it, don't work around it.
- `Stop-Process` on the user's processes was refused by the auto-mode classifier until the user said so. Ask first.
- Each set build runs in its own process, so a batch picks up code changes made mid-batch.

**ffmpeg**
- `blend` multiply must run on `gbrp` inputs (YUV turned everything green); `bandpass` needs `width_type=h`
  (default unit is Q → near silence); escape commas in expressions or wrap in quotes.
- libass matches the **legacy** font family name (nameID 1, e.g. "Arial Black"), see `fonts.py`.
- Never end an audio mix with a bare `apad` (an endless stream): ffmpeg 9 makes audio far ahead of slow video
  filters until "Cannot allocate memory", and `-t` doesn't stop it (a reel came out as 1.6 s of video + 704 s of
  audio). Use `apad=whole_dur=<length>`. Spot broken videos by comparing stream durations with ffprobe.
- Never run two ffmpeg processes writing the same output (a corrupt 98 MB mp4 with invalid NAL units). A `timeout`
  around a foreground ffmpeg kills the shell, not always ffmpeg - check `tasklist` for orphans.

**Blender**
- Blender 5.x: `Material.use_nodes` is deprecated (wrapped in try); `action.fcurves` is gone - don't touch fcurves.
  VRoid rig is T-pose; arms are rotated down via `arm_down`. Bone-parenting helpers need `matrix_parent_inverse`.
- Soft alpha on 128 px textures + 1-sample EEVEE dithering = sparkling edges → hard alpha cut-out (GREATER_THAN 0.5).
- Constraint influence keys: always key BOTH ends of an on/off span (f0-1, f0, f1, f1+1) - Blender eases between
  keys, so a lone 1 … 0 pair fades over the whole video (balloons drifted to the floor, sprites half-turned).
- A flat mesh built with `bmesh` has no material slot - add `me.materials.append(None)`. Check stderr as well as
  stdout for tracebacks.
- Blob shadows are NOT parented to the character (it rose on jumps): `make_shadow`/`write_shadow` keep it on the
  ground and shrink it with height. Cast uses the same helpers.

**Animation** (`blender_build`)
- Anims `a_*` set pose channels, then `secondary()` (breathing, blinks, talk gestures when `p["calm"]`), then
  `Smoother` springs every joint channel (`SPRINGS`: follow-through, and it blends one action into the next - `env()`
  only ramps at the very start/end). Locomotion sets `raw_legs` so feet don't slide; steps are driven by distance
  (`stride`). `leg_ik()` bends knees whenever `bob < 0` (`no_ik` for sit). The VRoid elbow only bends forward: use
  `rot` (upper-arm rotation) to raise a forearm (wave, celebrate) - a straight arm raised sideways reads as a T-pose.
  `shift` = weight shift. Showcase every anim with a wide/medium grid before claiming animation changes look right.
- Walking: `OBST` = floor-prop footprints of the generated set (radius from `custom_props` or `setgen.PROPS`; props
  above 1 m skipped). `resolve_pos` pushes marks out of props (`_clear_of`, `WALK_MARGIN` 0.55 m); a move is split
  into legs round obstacles (`_route`, `_pieces`) with the frame count unchanged.

**Framing / layout**
- The 9:16 wide shot only sees about |x| < 0.36·(y+6) - props in the `ring` zone are mostly off-frame, which is why
  signature props go to `showcase` first. A vertical medium shot sees only ~±1.5 m beside her, so cast land close to
  her or further back, never behind someone (`hidden`). Big AI props (cars ~2.5 m) only partly in frame - accepted.
- `CAMS` offsets are world-space (camera on the -y side): right for her (she talks to the camera), wrong for
  anyone else - a speaking co-star/cast member's offset is turned by their facing (`TRACKS`/`CAST_TRACKS` `"yaw"`)
  and swung round when she stands in the way. `blender_cast.spot()` reserves a place (`TAKEN`) - peeks must use
  `claim=False` or the real call collides with its own reservation. Placement and the walking routes both use
  `OBST` (generated sets' props, or `BUILTIN_OBST` for Legacy Cafe/Park).
- Side zones use `@`: `far@left`. Not `_left`/`_right`: `wall_left` and `hang_left` are real zones.

**AI models**
- Ollama models invent prop names and write `walk_to_center` as one token - both handled; keep validation. Unknown
  props are designed as new props (max 4 per set); before that, a plan with <2 known props silently fell back to a
  random set ("lava pit" became a beach). The deepseek model's spatial sense is weak - `propgen.clean()` repairs it.
- The vision model and Ollama plans sometimes return objects where strings are expected - check types before using a
  value as a dict key (`llm.make_coherent`).
- Z-Image draws fake lettering unless the prompt says "no text". ComfyUI ignores hex colours - use colour names
  (`comfy.colour_word`). A ground prompt built only from the description lost the ground type (snow came out sand).

## Working with this user
- Windows + PowerShell; give commands as PowerShell. They use the web app (often from their phone) while you work,
  so settings/profile files may change under you - treat on-disk state as theirs (e.g. their global look preset
  may be "Game Boy" on purpose).
- **No test renders or long encodes unless they ask.** They check videos themselves in the UI. Code-only changes
  are fine; say what was not run. When they do ask for verification: render, inspect frames/contact sheets
  (`output/*_shots.png`), measure audio (`volumedetect`/`astats`), drive the web app in the browser pane (also at
  mobile size), and say plainly what wasn't tested.
- **Never hard-delete user assets.** Removals go to `.trash/` folders (episodes, sets, music, sfx, props, actors, characters (`DELETE
  /api/characters/<id>` → `assets/characters/.trash/<id>-<stamp>/` with its voice; never the active one),
  packs, videos) or `sets/.hidden.json` for code-built sets; replaced models/voices get timestamped backups.
- Stopping processes, restarting the live app and deleting anything need an explicit go-ahead.
- Keep manual paths alongside AI ones (they write scripts by hand too). AI helpers must degrade gracefully when
  Ollama/ComfyUI are offline (except ComfyUI "Required" mode, which should fail loudly).
- Original content only: their own character, sets and royalty-free/generated audio; no copyrighted characters.
- Decisions they made (keep): music 5 %; voice -14 LUFS; intro/outro breathing room with fades; pixel captions
  2 words at a time, colour-cycled; no sound effects on transitions/wipes; "N64 Haze" look matched to their
  reference video; no procedural tail on the catgirl; every video = new episode; Postiz = drafts only.

## Reference videos (the style target)
- `Miori miorixox … (2).mp4` (68.6 s, 720×1280, ~-14 LUFS): fast cuts every 2–3 s, 1–3-word captions, coloured
  words, title card, atmospheric backdrops, eye close-ups, flashes.
- `… (3).mp4` (44 s, 716×1274, -14.1 LUFS): one town street throughout, single white words with outline, tracking
  shots, blurred brown wipes, day → dusk → night → dawn lighting.
These drove the beats, `macro` camera, wipes and per-shot `light`.
