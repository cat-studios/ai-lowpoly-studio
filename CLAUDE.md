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
  Never edit, restart or test against production unless the user asks; they move changes over once they're happy:
  production is a clean clone of the same GitHub repo (`main`), so the route is dev branch → merged into `main` on
  GitHub → `git pull` in production → restart the studio. All personal data is gitignored, so a pull never touches
  it - keep it that way when adding new data folders (add them to `.gitignore`). Never run `git clean` there.
- Preview servers for Claude's browser pane (`.claude/launch.json`): `studio-dev` (:8766) and `studio-check`
  (:8767). Never use :8765 here - that's production.
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
- Blender 5.3 prints DeprecationWarnings for `World.use_nodes` / `Material.use_nodes` (removed in Blender 6.0) -
  harmless now, replace before a Blender 6 upgrade.
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
(`look_score`, 1-10, `PROP_PASS` = 6); a fail → the AI redesigns it once from the critique (keeping the real size);
a second fail → `complex: true` → a drawn sprite (ComfyUI + sprite_cut, so only where voice-venv exists - in dev
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
  pose look wrong), `vision_check()` (qwen3.5 scores 1-10, `PASS` = 6; yes/no turned down everything), best try kept,
  up to 3 tries, saved with its check picture `assets/anims/<name>.png`. `ensure(word, line)`: exists → reuse; else
  `is_action()` (Ollama) → make; non-actions are remembered in `assets/anims/.not_actions.json`. Salute: 61 s, 9/10.
  `hand_to_forehead` pose added (checked: reads as a salute). The user chose automatic making (~30-100 s each).
- Director: unknown bracket words (`[yawn]`) and `[do:salute]` set shot `"want"` (the shot keeps its mood action as
  the fallback); `run_episode.resolve_animations` makes/reuses them before Blender and moves `needs_room`
  animations (arms out) out of close cameras. The script writer is told it may write `[do:<verb>]`.
- Assets → Animations tab (`web/anims_web.py`: `GET /api/anims`, `POST /api/anims/make` job, `DELETE` → .trash,
  pictures at `/animimg/`). Ideas: more poses (both hands on head, hands together/praying, arms crossed tight, hug
  self, cover ears) - each must be checked in a render (scratch tool: temporary ARM entries + check_render).

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
- Generated props: the design guide asks for `"complex": true` only for things too detailed for primitives. Only
  `needs_picture` props get a ComfyUI picture. `p_custom` uses the parts; the sprite (billboarded per shot camera
  with LOCKED_TRACK) only when there are no parts or it's complex. Small "table" things go on tables/counters.
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
- **Never hard-delete user assets.** Removals go to `.trash/` folders (episodes, sets, music, sfx, props, actors,
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
