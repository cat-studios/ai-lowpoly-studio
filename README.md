# Low Poly Studio (ai-low-poly)

Turn a short "What if…?" idea into a finished vertical Instagram Reel (1080×1920) in an N64 / VHS low-poly style,
starring your VRoid catgirl. You write the script (or let the AI write it); everything after that is automated:
directing, voice, 3D animation, cameras, render, filter, captions, music and sound.

From idea to video:

1. **Idea** - 🪄 **Custom Video** walks you through it step by step (title, look, sound, captions, script, scenes,
   shots); 🎲 **Make a Random Video** does it all from a few fun cards.
2. **Script** - write it by hand, or have Ollama write it from the title, your character's "about" text and the set.
3. **Directing** - each line becomes one or more shots with a camera, action, expression and sound effect. Override
   any line with `[closeup, angry, boom]`-style directions.
4. **Voice** - your own recording cloned with Chatterbox on your GPU (free). Every line is checked with Whisper and
   regenerated if words are missing.
5. **3D render** - Blender animates your model (walking, jumping, waving, cat ears reacting), with lip-sync and
   facial expressions, plus any other characters, people and things in the scene.
6. **Look** - a post filter matched to the reference video: chunky pixels, colour fringing, washed-out colours,
   scanlines and grain. Seven presets.
7. **Final mix** - pixel captions, title, watermark and end card, music at 5 %, timed sound effects, the set's
   ambience, and a calm intro and outro with fades.

**The opening** decides whether people keep watching, so the first line is a hook (a surprising claim or bold
question of at most 8 words - the AI writer is told so, and its editor checks it), the camera pushes in on her while
she says it (no more walking in) in a close-up, and the hook's key word pops up twice the size as she says it (Settings → Text &
branding → "Hook word pops up big").

**Batch from Ideas**: on the 💡 Ideas page press **☑ Pick several**, tick up to 10 ideas and **🎬 Make the
videos**: each idea becomes its own video (its own kind of video, its first title or a new one, script, scene and
shots), queued to render one after another. Pick a length, regulars for every video and a note if you like. One
idea failing doesn't stop the others.

**Regulars (recurring cast)**: people who come back from video to video, with the same look and voice.
- Keep a guest from a finished video: Videos → **🎭 Guests** → ⭐ Keep (give them a name - "Mom", "Grandma Rose").
- Or make one by hand: Assets → Actors → + New, tick **⭐ Regular**, and write their **Personality** ("grumpy,
  always hungry").
- Pick them in Custom Video → 💡 Idea → **⭐ Regulars**: the script writer brings them in and gives them their own
  lines, in character, and they're played by their own actor.

**The check after every render**: the studio looks at each finished video for the things that go wrong - her
missing or hidden behind something in a shot (the picture model looks at every shot, and asks itself twice before
it says so), cutaways too quick to see or dropped, made props shown although they didn't quite look like
themselves, arrivals with no room beside her, two sounds at once, a broken encode. The Videos page shows
**⚠️ N to look at** (tap it: what, which shots, what to do) or **✓ checked**. Run it again by hand with
`python pipeline/review.py episodes/<video>.json`.

**Cover picture**: every render also makes `output/<video>_cover.jpg` (1080x1920) - the best frame of the video
(the picture model looks at up to 8 shots that show her face and picks one) with the title on top, in the same
look. On the Videos page it's the video's still before you press play; **🖼 Cover** shows it big with ⬇ Download,
🔄 Let the AI pick again, or "use shot N" (the order 🎞 Shots shows). Picking again needs the render's frames
(Settings → Free up disk space deletes them).

## Installing on a new PC (Windows 10/11)

1. **Python 3.12 or newer** (python.org; tick "Add to PATH"), then the one package the app itself needs:
   ```powershell
   python -m pip install edge-tts
   ```
2. **ffmpeg** (a full build with libass):
   ```powershell
   winget install Gyan.FFmpeg
   ```
3. **Blender 5.3** at `C:\Program Files\Blender Foundation\Blender 5.3\` (or set the `BLENDER` environment
   variable to your `blender.exe`), plus its VRM add-on for importing VRoid models:
   ```powershell
   & "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" --online-mode -c extension install -s -e vrm
   ```
4. **Optional - your own cloned voice** (Chatterbox on an NVIDIA GPU; it also checks every line with Whisper).
   Needs Python 3.11 in `tools\voice-venv`:
   ```powershell
   py -3.11 -m venv tools\voice-venv
   ```
   ```powershell
   tools\voice-venv\Scripts\python -m pip install chatterbox-tts==0.1.7 faster-whisper==1.2.1 pillow
   ```
   ```powershell
   tools\voice-venv\Scripts\python -m pip install --force-reinstall torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
   ```
   (the last one replaces the CPU-only PyTorch that pip installs by default). Pillow in this environment is also used
   for drawn props, "scene from a picture" and the app icons. Without it the app uses the free Microsoft voices.
5. **Optional - AI helpers**: [Ollama](https://ollama.com) (titles, scripts, sets, props, sounds, translations) and
   ComfyUI (textures, prop pictures, music - Z-Image Turbo and ACE-Step 1.5). Pick the models in Settings → AI
   tools. Everything works without them except translating videos into other languages and ComfyUI "Required" mode.
6. Start the app (below). The first start makes the 24 built-in sound effects. Then go to **Characters → + New
   character** and import your VRoid `.vrm` - until then videos use a simple placeholder body.

## Updating to a new version

Your characters, voices, sets, videos, imported packs, animations and settings are not part of the code (git
ignores them), so updating never touches them. In the studio folder, with the studio closed:
```powershell
git pull
```
then start it again. Don't change code files in this folder yourself (a pull would clash with your edits), and never
run `git clean` here - that WOULD delete the ignored personal files.

## Starting it

Double-click `start-studio.bat`, or:

```powershell
python web/server.py --lan
```

Open http://127.0.0.1:8765 on this PC. `--lan` also opens it to phones and tablets on the same Wi-Fi - the console
prints the address (e.g. `http://192.168.1.20:8765`; it can change after a router restart). Without `--lan` only this
PC can open it.

**On your phone:** open that address in Safari → Share → *Add to Home Screen*. It gets the catgirl icon and opens
full screen like an app (Android: ⋮ → *Install app*). Set a PIN in Settings → Phone & network so other people on
the network can't use it (this PC never needs the PIN). If the phone can't connect, Windows Firewall must allow
Python on this network: Windows Security → Firewall → *Allow an app through firewall* → Python.

**After updating the code**, use Settings → *Restart the app* (anything still running stops).

The progress bar at the top right shows every running job; click it for the live log. A failed job has a
↻ **Retry** button there. Videos render one at a time, scenes build one at a time (even while a video renders),
and everything else runs in its own lane.

## The pages

### Create
Three big buttons:
- **🎲 Make a Random Video** - pick fun cards (kind of video, place, topic, vibe, guest, time, length); the studio
  writes, builds and renders it all.
- **📺 Make a Series** - one idea, 1-4 episodes, each made and rendered for you.
- **🪄 Custom Video** - a step-by-step popup with everything in your hands. Tap the cards; every step can be
  changed later (tap a step at the top, or a pill on the last step). Closing it keeps your picks.
  1. **💡 Idea** - kind of video, the title (or ✨ Give me ideas), who stars and who else is in it.
  2. **🎨 Look** - the retro filter and the language it's voiced and captioned in.
  3. **🎵 Sound** - music (▶ to listen) and the sound of the place.
  4. **💬 Captions** - how the words appear, and quick cuts or one shot per line.
  5. **✍️ Script** - length, places (one place / a little journey / let the AI decide), vibe and a note, then
     ✨ Write my script - or write it yourself. Edit anything. `[@ a place]` marks where the story moves.
  6. **🗺 Scenes** - every place the script needs, in order. Pick one of your sets for each, or **Make a new one**
     (🪄 Make it now, a few minutes, or leave it to be made when the video renders).
  7. **🎬 Shots** - the script directed in those sets: change any camera or action, or open **🔧 Fine-tune every
     detail** (lines, moves, places, sounds, effects, light, cutaways, who says it, others in the shot, the cast).
  8. **🚀 Render** - everything at a glance, record the voice again if you like, check the translation, then
     **▶ Render my video!** (or save it without rendering). Want a look first? **👀 Storyboard** (about a minute:
     one picture per shot with its line, no voice) or **🎞 Rough preview** (a few minutes: a small moving video
     with the voice and captions, plain look). Previews never make anything new - a set, prop or move that isn't
     made yet shows as a stand-in (the closest set you have); the real render makes it.
     **🎭 Who and what appears** (same step) shows a card for everyone and everything else in the video - the
     people, things and cutaways - with what will play it (your actor, an imported model, a made prop with its
     look score, or "will be designed") and its picture. Swap it before rendering: **📦 One of my models**
     (any imported model, by category), **🖼 Draw it** (a 2D picture), **🧊 Make a new 3D one**, or
     **↺ Let the studio choose**.

The scenes come after the script on purpose: the script decides where the story goes, and the shots are directed
last so walks and pointing use the real sets' own places. Each video is its own new episode (named from the title).
On the Videos page, ✏️ Edit → **🪄 Open in Custom Video** opens a video in the popup (on its last step) and keeps
its file.

### Ideas
What's trending today - Google Trends and Google News (science, tech, health) in the US, UK and Lithuania,
Wikipedia (most-read, Did you know, On this day), NASA's picture of the day, holidays, Bluesky, Hacker News and
YouTube's popular videos (with a free API key: Settings → AI tools → Ideas, where every source can be switched
off) - turned into family-friendly video ideas by your AI (no real people, brands or film/game franchises),
plus your own ideas. The list refreshes by itself every 12 hours (or press 🔄). Per idea: ✨ Titles (tap a title to
make it as a Custom Video), 🪄 Custom Video, 📺 Series, ☆ star, 🙈 hide. Ideas used for a video are marked used, so
you don't repeat yourself. Trending ideas also show up in Custom Video's first step, among the random video's topic
cards and in the series popup.

### Sets
A gallery of every scene, newest first, with a preview and its walkable places.
- **How it's made** (also in Custom Video's Scenes step and Settings → AI tools):
  🏛 **Hand-built base** (the default) - one of 12 rooms and outdoor places built by hand in the Legacy Cafe/Park
  style (a dressed back wall, lamps, a layout made for the vertical frame, one palette); the AI only picks the base,
  the colours and the things in it. 🎨 **Palette** - the free AI layout with one palette, flat colours, a dressed
  wall and lamps. ⚖️ **Judged** - the free AI layout, checked against the Legacy sets' pictures and redesigned if
  it falls short. 🎲 **Classic** - the free AI layout. Random videos pick one of the first three by chance; series
  always use hand-built bases.
- **Generate** a new set: from an idea ("haunted bakery"), from a **picture** (the vision model builds a matching
  scene and takes its colours and ground from the photo), or fully random. Options: inside/outside, time of day,
  theme, room size (small / medium / large), ground, AI on/off, textures, seed.
- **Themes**: *Auto* (from the words in your idea), *Random* (the free AI layout - sometimes odd), *Generated
  theme* (the AI writes a new theme and saves it), or a named one: cafe, park, bedroom, classroom, arcade, kitchen,
  living room, forest, beach, snow, city, desert, space station, graveyard, candyland.
- Scenes check their climate, so snow doesn't end up in a desert.
- **Regenerate** a set with changed settings - the old one is backed up first and the new one keeps its name.
- **Map editor**: a top-down view to drag, turn, resize, add and remove props.
- **3D view**: orbit and zoom around a scene (needs internet - it loads three.js from unpkg).
- **Generate 3 Starter Sets** builds three scenes from a list of starter ideas.
- Legacy Cafe and Legacy Park are the original hand-built sets; they keep their look and can't be regenerated.
- Removing a set moves it (with its textures and 3D view) to `sets/.trash`; nothing is hard-deleted.
- Sets made before 24 Nov 2026 can have two props stacked on one spot (a theme's tables in the middle of the room) -
  fix them in the map editor or regenerate them. New sets don't do this.

**ComfyUI modes** (Settings → AI tools): **Required** always textures sets (floor, walls or a painted sky, plus
pictures) and fails if ComfyUI is off · **Only when needed** only draws pictures for props that need one · **Off**
never.

### Assets
- **🧊 Props (3D)** and **🖼 Sprites (2D)** - every object made for your sets and scripts is EITHER a 3D model built
  from simple shapes OR a flat 2D picture drawn by ComfyUI, never both. Things are used in this order: one of your
  imported models, then a made 3D model, then - rarely - a sprite: only when the made 3D model still clearly doesn't
  look like the thing after a redesign (the picture model's look check). A 3D prop shows the look check's picture.
  Click one to see it big, fix its description, size or where it sits (floor / table / wall), or 🗑 delete it
  (moved to `assets/props/.trash`). A 3D prop can be turned into a sprite (🖼 **Make it a sprite**) and a sprite
  back into its 3D model (🧊 **Use the 3D model**); sprites can be 🎨 **Redrawn**. Edits apply to every set and
  video that uses it on its next render.
- **📦 Imported** - asset packs you upload as a zip of OBJ, FBX, BLEND or MDL models (folders inside are fine).
  Click a model (or ✏️) to give it your own name, description and category - scenes and scripts find it by that
  name. People in a story (Mom, a teacher, a pedestrian) are played by your imported people.
  Each model gets a picture. MDL files from Quake 1, Half-Life and Source are converted (not yet tried on real
  game files). Models are sorted into categories made from their own names (Vehicles, Animals, Furniture, Food...)
  with search; the AI sorts names it doesn't recognise on every import (or press **🏷 Categorize**). A model that is
  already imported (identical file), or the same model in several formats, is skipped on import; **🧹 Remove
  duplicates** cleans up ones imported before. **✏️ Name & describe** has the picture model give generic names a
  clear one ("fence" → "Wooden Farm Fence") and a description (the file name is kept). 🗑 deletes one,
  **☑ Select** deletes several at once (files go to the trash folder). Removing a whole
  pack is under **Packs** at the bottom. A prop or cast member whose name matches an imported model uses that
  model; with no exact match the closest one is used (a mail van → the ambulance, a dog → the pug, a police car →
  the cop car). Models are scaled to the real thing's size (a pug is 0.35 m, not the size in its file), and parts a
  pack left plain grey get colours from their names ("Red", "Windows", "Lights").
- **🧍 Actors** - the extra people in your scenes (a mom, a store clerk…): a generic body dressed from a
  description, a rigged `.blend`, or an imported model, each with a voice.
- **✨ Effects** - the particle effects with looping previews. Change colours, amount, speed and size; **Save &
  preview** renders a new clip, **Reset to default** undoes your changes.
- **🎵 Music** - upload royalty-free tracks once, pick one per episode or set a default (plays at 5 % with fades).
  ✨ **Generate**: ACE-Step 1.5 in ComfyUI composes an instrumental from a style description, or the built-in
  chiptune synth makes an instant loop.
- **🔊 Sounds** - 16 retro effects (boom, coin, boing, jump, ding, ta-da, whoosh, hiss, laser, sad trombone…) and
  8 ambience loops (arcade, waves, birds, wind, city, space, room, spooky), all synthesised. Upload your own file to
  any slot, ✨ generate a sound from a description, or add new slots with trigger words. Effects play on trigger
  words ("BOOM" → boom, timed to the word) and actions (jump, surprised, celebrate), or per shot / with `[boom]`.

### Videos
Every render, with download and:
- 🎞 **Shots** - one frame from every shot, in a strip.
- ✏️ **Edit** - a popup editor for scenes, shots (including light, who says it, what the others do), look and
  filters, text, watermark, music and sound, and the models used. It saves and re-renders the same video.
- 📤 **Postiz** - send it as a draft (see below). Earlier versions are kept (tagged "Earlier version") and can be
  sent too.
- **Rename** (display name only) and **Delete** (moved to `output/.trash`).

A video remembers the look it was made with, so changing your global look doesn't change old videos.

### Characters
Profiles with a name, *about* text (the script AI reads it), model, voice, tail and camera distance. Import or
replace a VRoid `.vrm` (old versions are kept as timestamped backups; ear bones are found automatically), make a
preview picture, upload a reference voice, test the voice, and choose the active character. A new character uses
the placeholder body until you import a model. 🗑 Delete moves a character (profile, model, preview, backups and
reference voice) to `assets/characters/.trash`; the active character can't be deleted - make another one active first.

### GIF
Turn a video (one of yours or an upload) into a GIF that stays under 10 MB.

### Settings
Render size, fps and **video file quality** (CRF, default 20: lower = sharper but bigger files; roughly 70 MB per
minute of busy footage at 20), every look/filter value, caption style, title, watermark and end card, audio timing and the
default voice, AI tools (Ollama model, ComfyUI address and mode), Postiz, phone & network (PIN), and *Restart the
app*. A fast *Preview* tries look changes on an already-rendered video. *Reset to defaults* resets everything
except your active character, the Postiz connection and the phone PIN.

**Free up disk space** (Settings, right-hand side) shows what takes room and cleans it: render work files (frames
of old renders - deleted for good; a new render makes them again, but *Re-apply look only* won't work for those
videos until then), earlier versions of videos (moved to the trash), and every trash folder (emptied for good -
this also deletes the code backup in `.trash`). **Everything the AI made** moves every generated scene and every made
3D prop and sprite to the trash, so new videos make fresh ones (Legacy Cafe/Park, imported models, characters and
finished videos stay). Finished videos and the voice cache are never touched. It waits until no job is running.

Picking a **look preset** for one video (Create page, or ✏️ Edit on the Videos page) replaces that video's saved look
with the preset; tick individual settings in the editor to change them on top of it.

## Writing scripts

One line per shot (long lines are split into several shots when "every few words" is on). Put directions in square
brackets at the start of a line.

### Directions
```
[closeup, angry, boom] I said NO pineapple!
[wide, walk_to_counter] Fine. I'll make it myself.
```
Cameras, actions, expressions and sounds from the tables below can all go in the brackets.

The AI script writer reads its own script back like an editor before you see it: it fixes made-up facts, clumsy
English, lines that don't follow on and weak endings, and leaves your directions alone. Titles it suggests come
best first.

The automatic director keeps her walking to a minimum (a walk now and then, never two close together) and moves
the camera instead: every few shots a new angle that circles, pushes in or pulls back. When she walks away from
the camera, a camera ahead of her films her face; when she points at something behind her, the shot is from the
side so you see the arm and the thing.

### More ways to make videos (2026-11-26)
- **Weather and time follow the story**: a sad line outdoors gets rain, a celebration gets confetti, and a
  "day in the life" video goes from day to sunset to night - unless your script sets those itself.
- **She holds what she talks about**: "look at this cup", "my lucky coin", "holding a cookie" - she holds it up in
  front of her for that line and puts it away after (up to 3 per video).
- **Close-up reactions**: "just kidding" gets a wink, "aww, stop it" a blush, "ugh, seriously?" an eye-roll - each
  in a close-up (up to 3 per video). Write `[wink]`, `[blush]` or `[eyeroll]` in a line's brackets to choose.
- **Regulars have jokes that come back**: give a regular a catchphrase and a running gag (Assets → Actors). The
  writer has them say the catchphrase once, works the gag in, and can call back to what they said last time (the
  studio remembers each regular's lines after every video).
- **💬 Conversation** (a new kind of video): she and a co-star (pick one under "Also in it") talk *with each
  other* - each turns to the other while talking, with two-shots of both - and only the opening and the last line
  go to the viewer. Any script where two main characters go back and forth gets this too.
- **🏠 Her room** (Sets → 🏠 Her room): make it once and "My Room" becomes her home set - any script that says
  "her room", "home" or "bedroom" goes there. After every video she keeps one thing from it (a cutaway, something
  she held) as a souvenir along the walls - the newest 10. Remove one there; switch collecting off in Settings.
- **Her own reaction sounds**: a little gasp when she's surprised, a giggle when she laughs, "hmm" when she
  thinks, "yay", "aww" or "nya" - in her own voice, just before the line (up to 3 per video; Settings → Render &
  audio → "Her own reaction sounds").
- **🔁 Variation** (Videos page): a **part 2** of a video (new facts, a nod to the first one) or the **same idea as
  another kind of video** (a Top 5 as a Myth or fact...) - written, directed and rendered by itself.
- **🎛 Remix** (Videos page): the same script in another set, look or language - up to 3 at once. **⚖️ Compare**
  plays them side by side; ⭐ Keep this one marks the one you'll post.
- **📅 Weekly plan** (Settings → AI tools): pick a day and hour, and every week the studio makes that many videos
  from fresh ideas by itself (starred first, a mix of kinds) and leaves each one as a **Postiz draft** - you post
  them. The PC and the studio need to be on; ▶ Run it now on the Ideas page (📅 Weekly plan).

### Kinds of video (templates)
Create → 1 Idea → **Kind of video** steers the title ideas, the script and the pacing (the look never changes):
- 💭 **What if…** - the classic: she imagines something silly and acts it out.
- 🔧 **How it works** - she presents a model of one real thing, opens it and shows how its parts work.
- ⚡ **Quick facts** - a few surprising true facts, each shown with a cutaway, faster cuts.
- 📖 **Mini story** - a little story with a problem and a twist, a second place and a visitor.
- 🏆 **Top 5** - a countdown from number 5 to the most amazing number 1, each with a cutaway.
- 🤔 **Myth or fact?** - three things people believe: "Myth or fact?", then the reveal with the real reason.
- ⚖️ **This or that?** - two things compared round by round; she picks one and asks for yours.
- 🔍 **Guess what?** - clues from hard to easy, a moment to guess, then the big reveal.

### Series
**📺 Make a series** (next to 🎲 Make a random video): one idea, 1-4 episodes. Each episode gets its own question
as the title, a script that knows what the others cover (and ends with a hook to the next), its own scene and
shots, and is rendered - one after another, in the background, so you can lock your phone. They show up on the
Videos page with a 📺 tag (the idea and the part number).

### Make a random video
**🎲 Make a random video** on the Create page opens a little game: after a magic shuffle it deals three cards for
where it happens, then three topics, a vibe, who drops in, the time of day and the length (🎲 Three more deals new
cards, ← Back goes back). Last comes an optional note you can type (the first cards pick the kind of video). Then the studio writes the title and script,
builds a new scene for your place, directs it and renders the video.

## Props the studio makes
When nothing you imported fits, the studio builds the prop from simple shapes (animals, insects and vehicles start
from a body template). Every new one is rendered and the picture model checks that it looks like what it should; if
not, the AI rebuilds it once, and if that still fails it becomes a drawn picture instead. A cutaway is skipped
rather than showing shapes that don't look like the thing.

## Sets the studio makes
New sets are filled so the wide shot isn't an empty room: after the layout, more of the set's own small things
(chairs, plants, crates, the AI's props...) are added where the camera looks, until it shows about 9 things
inside or 11 outside. Rooms also get see-through front and right walls: invisible from the usual camera, but a
camera that turns round inside the room sees a wall instead of the open edge.

A new set from an idea is checked before it's finished: the picture model looks at a quick preview and scores how
well it shows the place. If it doesn't (a "haunted library" that looks like a classroom), the AI adds what's
missing and removes what doesn't belong, and tries once more (the better try is kept). This can make
a new set take several minutes longer. Props that came out absurdly wide are squeezed to their real width.
Both checks (sets and props) can be turned off in Settings → 🤖 AI tools when you're in a hurry.

## Your own animations
An animation can be a small file in `assets/anims/<name>.json` that strings together ready-made poses
(`pipeline/animlib.py` lists them: hand_to_chin, hand_at_mouth, palm_up_out, wave_up, hand_on_hip, and for both
arms hands_on_head, praying_hands, arms_crossed, cover_ears, hug_self...). Its name
then works like any action: `[shrug] Who knows?`. Example:
```
{"name": "shrug", "description": "Shrugs - who knows?", "length": 1.4,
 "keys": [{"t": 0, "both": "rest"}, {"t": 0.35, "both": "palm_up_out", "head": "head_tilt", "body": "shoulders_up"},
          {"t": 1.1, "both": "palm_up_out", "head": "head_tilt"}, {"t": 1.4, "both": "rest"}]}
```
When a script asks for something she can't do yet - `[salute]`, `[yawn]` or `[do:salute]` - the AI makes it while
the video renders (from poses that are known to look right), renders a quick check and has the picture model rate
it; it's saved for every later video. That takes about half a minute to two minutes per new action. Assets →
**🕺 Animations** shows them with their check picture and score, makes one on request, and deletes (to the trash).

### Light and time of day
`[sunset]`, `[night]`, `[dawn]` or `[day]` changes the light from that line on (until the next change) - for a
story that goes from day to night. `dusk`, `evening`, `sunrise` and `morning` work too.
```
Hello! What a sunny day in the cafe.
[sunset] Oh, the sun is going down already.
[night] And now it's night time!
```

### Changing scenes, and effects
```
Today I'm finally going skydiving!
[@ falling through the clouds, wide] So I jumped out of the plane.
[@ on the moon, surprised] Then I somehow landed on the moon?!
[@ park, celebrate, confetti] But I made it home!
It started raining though.
```
- `@ place` changes the scene until the next `@`. If one of your sets fits (by name/description) it's reused;
  otherwise a new set is made when the video renders, saved to **Sets**, and remembered by the episode.
- Places with no ground (sky, space, under the sea, falling to the earth's core) are "in the air": no floor, clouds
  or rocks stream past while she falls (skydiving pose) or floats.
- Effects: `rain`, `snow`, `droplets`, `bubbles`, `dust`, `specks`, `sparkles`, `embers`, `petals`, `leaves`,
  `confetti`, `beams`, `stars`, `speed_lines`, `fireflies`, `hearts`, `music_notes`, `coins`, `candy`, `puffs`,
  `sprinkles`, `pixels`, `bolts`, `bats`, `paws`, or `no_fx`. Words in the line ("it's raining", "confetti!") switch
  them on too, and every set has a default (falling = speed lines, lava = embers…).
- **🗺 Let the AI change scenes & add weather/effects** (with *Reuse my sets when they fit* or *Always make new
  sets*). Each shot also has a **Scene** and **Effects** picker.

### Other people and things
```
[+mom enter] Mom?! What are you doing here?
Mom: You forgot your lunch again.
[+car crash_in from_left, surprised] WHY IS THERE A CAR IN MY CAFE?!
[+meteor fall, scared] Is that... a meteor?
```
- **People** (mom, boss, robot, kid…) get a low-poly body coloured from the description in the 🎭 Cast panel
  ("tall man, grey hair, blue suit"), or an actor from Assets → Actors. They can `enter`, `exit`, `appear`,
  `vanish`, or do any action. They speak lines written as `Name: …` (like `Mom:` above), in their actor's voice.
- **Things** are designed by the AI prop maker when the video renders (and kept in the prop library): `enter`,
  `exit`, `crash_in` (debris + shake + boom), `fall`, `fly_by`, `appear`, `vanish`, `bounce`, `spin`, `shake`,
  `hold` (she holds it). Add `from_left` / `from_right` / `from_back` / `from_top`. Things can't talk.
- No `+` in a hand-written script? Tick **🎭 Let the AI add other people & things** before *Direct shots*. Each
  shot also has a **🎭 Others in this shot** field (`mom enter, car crash_in`).
- **Crowds**: `[+crowd enter]`, `+audience`, `+soldiers`, `[cutaway: a herd of cows]` bring in a group made from your
  imported models - posed people (cheering, walking, running... picked from the words) or several of the animal or
  thing it names. With nothing to build it from (an "army of cats" without a cat model) the group is left out.

### Explaining how something works
She can present a model of a thing and show how it works - its parts move when she names them:
```
[show: toilet] When you flush a toilet, here's what happens.
[show: toilet open] Inside the tank, a chain lifts a rubber flap.
[show: toilet flap] The flap opens and the water drains into the bowl.
[show: off] And that's how a toilet works!
```
`[show: thing]` brings the model on beside her (she points at it), `open` takes its front off so you see inside,
a part name (`flap`) gives a close-up of that part, `[show: off]` puts it away. The AI builds the model while the
video renders, from what the script says about it (sections, the parts inside, and what each part does: turns,
slides, spins, fills, drains, beats or rattles), and each part moves on the word that names its action. Models are
kept in the prop library and reused. With ComfyUI on, a closed model shows as a drawn picture of the real thing,
and turns into the cut-open diagram when she says `open` (or looks at a part). The diagrams are simple shapes in the
same low-poly look - round things (a volcano, a heart) are cut in half like a cross-section drawing. Settings →
🤖 AI tools → *Big model server* can send this to a stronger computer's Ollama (with *Use the big server for* →
"All the AI's writing too", scripts, titles, sets, translations and captions go there as well). Picture checks,
drawings and voices always run on this PC, and if the big server is off or lacks the model, your own Ollama and
model take over.

### Cutaways
Show something instead of her while she keeps talking (voice-over):
```
[cutaway: a plane flying past] The plane was already 4000 metres up.
[cut: ants marching] There are about twenty quadrillion of them.
```
The subject moves to match the words (flying = flies across, falling = drops in, marching/walking = comes in,
otherwise it appears). Each shot has a **📷 Cutaway** field, and the AI scene option can suggest a couple.

### Floating (balloons!)
`[+balloons hold]` gives her balloons (they stay in her hand), `[float_up]` lifts her off the ground - legs dangling
- until `[land]`. The director also does it from the words: a line about balloons hands them to her, "look at me go
up" / "I'm floating" lifts her, "it popped" / "back down" brings her down.

## Sending videos to Postiz (as drafts)
1. **Settings → 📤 Postiz**: your Postiz address and API key (Postiz → Settings → Developers). Save, then
   **🔄 Load channels** and tick where drafts should go. For Discord paste the channel ID (Discord: Developer Mode
   on → right-click the channel → Copy Channel ID).
2. **Videos → 📤 Postiz**: the AI writes a caption per platform (topic hashtags + trending ones like #fyp, #reels,
   #shorts; YouTube/TikTok get a title; Discord a short announcement). Edit anything, **Create drafts**.
3. In Postiz the drafts show on the calendar as "Draft:" - set the times there. **Nothing is ever posted from the
   studio.**

## Command line

```powershell
python pipeline/run_episode.py episodes/<id>.json
```
Output: `output/<episode>.mp4` plus `output/<episode>_shots.png` (one frame per shot). Work files (frames, audio,
`scene.blend` you can open in Blender) go to `build/<episode>/`. Options: `--fresh-voice` (regenerate voice lines
instead of using the cache), `--no-tts` (no voice), `--no-render` (re-encode existing frames).

```powershell
python pipeline/make_set.py --idea "haunted bakery" --where inside --light night
```
```powershell
python pipeline/music_gen.py --style "lofi chill" --seconds 60
```
```powershell
python pipeline/sfx.py
```
(`sfx.py` re-synthesises the built-in sounds.) Settings live in `config/settings.json` and characters in
`assets/characters/<id>.json`; the command line uses the same files as the web app.

## Episode format

(Comments are for explanation only; real episode files can't contain them.)

```jsonc
{
  "title": "WHAT IF ...?",            // shown at the top during the first shot
  "set": "cafe",                       // any set id from the Sets page
  "start": "door",                     // mark where the character starts
  "character": "catgirl",              // optional, default = the active character
  "co_stars": ["ethan"],               // optional, other main characters
  "voice": { "exaggeration": 0.6 },    // optional, on top of the character's voice
  "music": "assets/music/song.mp3",    // optional, "" = none
  "shots": [
    { "camera": "wide", "move": "orbit",
      "action": "walk_to", "to": "counter",
      "expression": "happy",
      "line": "Spoken + captioned text",
      "speaker": "ethan",              // optional, who says it
      "duration": 3 }                  // optional; shots stretch to fit the line
  ]
}
```

A shot can run several actions in a row: `"actions": [{ "anim": "jump", "duration": 1 }, { "anim": "dance" }]`.
Also: `"light": "night"` (day / sunset / night / dawn - the lighting changes from that shot on), `"both": true`
(everyone in the frame), `"listen": "wave"` (what the other main characters do), `"particles"`,
`"cutaway"`, `"set"`.

| Field | Options |
|---|---|
| `action` / `anim` | idle, turn, walk_to, run_to, sneak_to, jump, wave, surprised, sad, angry, think, laugh, dance, spin, celebrate, nod, shake_head, point, stretch, sit, look_around, scared, blow_kiss, clap, bow, sneeze, facepalm, shiver, float_up, land |
| action params | `to` (mark or `[x, y]`, for *_to), `face` (camera, left, right, away, or a mark), `times`/`height` (jump), `turns` (spin) |
| `expression` | neutral, happy, surprised, angry, sad, smug, scared |
| `camera` | wide, medium, closeup, side, low, high, dramatic, back, macro (eyes), tiny (small figure in a big scene), silhouette (+ `zoom`, e.g. 1.3 = further away) |
| `move` | static, push_in, pull_out, orbit, follow, shake |
| marks: Legacy Cafe | door, center, counter, table, front, machine |
| marks: Legacy Park | left, right, center, front, tree, bench, pond, far |

Generated sets list their own marks on the Sets page ("Starts at" / "To").

## Voice

The character's voice is in `assets/characters/<id>.json` (catgirl: the local engine cloning
`assets/voices/catgirl.wav`). An episode's `"voice"` overrides it, and a shot can override that with its own
`"voice"`. Other main characters and actors use their own voices.

| Engine | Example | Notes |
|---|---|---|
| `local` | `{ "engine": "local", "ref": "assets/voices/catgirl.wav", "shift": 1.12 }` | Free, offline (Chatterbox on the GPU). `ref` = 10–30 s clean wav of a voice you have rights to. Optional `exaggeration` (0.25–1, emotion), `cfg_weight`, `temperature`, `seed`. Emotional shots get more exaggeration automatically. Each line is checked with Whisper |
| `edge` | `{ "engine": "edge", "name": "en-US-AnaNeural", "rate": "+8%", "pitch": "+15Hz" }` | Free Microsoft neural voices, needs internet and `pip install edge-tts`. List voices: `python -m edge_tts --list-voices` |
| `elevenlabs` | `{ "engine": "elevenlabs", "voice_id": "...", "model": "eleven_multilingual_v2" }` | Paid. Set the `ELEVENLABS_API_KEY` environment variable. Never tested (no key) |
| `windows` | `{ "engine": "windows", "shift": 1.25 }` | Offline fallback, robotic |

Any engine also takes `"shift": 1.2` (pitch up without changing speed). Lines are cached in `build/tts_cache`, so
re-rendering after an animation tweak doesn't regenerate voices. Voices are levelled to -14 LUFS. The local engine
runs in its own Python 3.11 environment (`tools/voice-venv`: chatterbox-tts, CUDA PyTorch 2.6, faster-whisper).

## Look

Rendered at 216×384, 30 fps, then post-processed: limited colour depth, chunky nearest-neighbour upscale, soft blur,
red/blue fringing, lifted blacks and muted colour, faint scanlines, grain and a vignette. Captions are drawn at the
low resolution (so they're pixelated with the picture), two words at a time in cycling colours, each pair shown
when she actually says it (the voice engines report when every word is spoken); the title is two lines at the top,
white then yellow.

Presets: N64 Haze (default), Clean Retro, VHS Tape, PS1 Crunch, Game Boy, Dreamy Pastel, Spooky Night - globally
(Settings) or per episode. Every value can be changed in Settings, and an episode can override any of them:

```jsonc
"look": { "blur": 1.0, "fringe": 2, "saturation": 0.9, "grain": 0, "scanlines": false, "vignette": false }
```

## Character (VRoid)

Easiest: Characters page → import a `.vrm`. By hand:

1. Export from VRoid Studio as VRM, e.g. `assets/characters/catgirl-v3.vrm`.
2. Convert it (needs Blender's VRM add-on):

   ```powershell
   & "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" -b --factory-startup --python pipeline/prepare_character.py -- assets/characters/catgirl-v3.vrm --out assets/characters/catgirl.blend
   ```

   This makes `catgirl.blend` (fewer polygons, 128 px textures, fog-ready materials) and `catgirl.report.json`.
   `catgirl.blend` is always the active model; `catgirl-v1.blend` is the first version, kept as a backup.
3. Episodes use the character's `.blend` automatically, or the placeholder body if it's missing
   (`"character": { "model": "placeholder" }` forces it).

`assets/characters/catgirl.json` also holds `tail` (procedural tail on/off - off for the catgirl), `tail_color`,
`tail_tip` and `camera_scale` (camera distance for the character's size).

## Optional AI tools
- **Ollama** (http://127.0.0.1:11434) writes titles, scripts, set designs, props, sounds, cast and scene plans,
  translations and Postiz captions. Pick the model in Settings → AI tools. A vision model reads pictures for "scene
  from a picture".
- **ComfyUI** (ComfyUI Desktop uses http://127.0.0.1:8666; 8188 and other common ports are tried too) draws set
  textures and prop pictures with Z-Image Turbo, and composes music with ACE-Step 1.5.
Everything still works without them (except videos in other languages and ComfyUI "Required" mode), just with
simpler results.

## Video language
Write everything in English - title, script, directions. Pick the **video language** (Create → Look, the video
editor's Text tab, or Settings → Render & audio for every video): English or Lietuvių (Lithuanian). The finished
video is then fully in that language: the spoken lines, captions, title and end card are translated by Ollama when
it renders, and spoken by a voice of that language.
- **🌐 Check translation** (next to the language picker) shows every translated line next to its English. Fix
  anything - the local AI model's Lithuanian is good but not perfect - and save; the video uses exactly your words.
  Translations are also remembered, so rendering again says the same thing.
- Your cloned voice only speaks English, so other languages use a Microsoft voice of that language (Lithuanian: Ona,
  female, or Leonas, male, picked to match each character's English voice; a character's profile can say
  `"gender": "male"`). Your voice's pitch shift is kept.
- Sound effects still follow the English words. The watermark is not translated.
- More languages can be added later (one line each in `pipeline/catalog.py`: the language and its two voices).

## Logs
Every request (with IP and browser) goes to the terminal and to `logs/server-YYYY-MM-DD.log`; each job's output is
in `logs/jobs/`.

## Not tested yet
- The ElevenLabs voice, MDL converters with real game files, and the app on a real phone (only checked at phone
  size in a browser).
- Starter sets and the regenerate popup from the browser; Postiz drafts of earlier versions; the 3D viewer beyond
  one scene.
- Walking round furniture in a generated set and the job lanes under heavy load haven't been seen in a render yet.
- Tested in renders: the language option (Lithuanian), people saying `Name: …` lines, co-stars, per-shot lighting,
  and long encodes (an old bug cut videos to a few seconds of picture - fixed).

## Uploads
Files with any name can be uploaded (accents and non-Latin letters included) - music, sounds, voices, VRM models,
pictures, model packs and clips.
