/* Low Poly Studio - single page app (no build step, no libraries). */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app");
let META = null;

async function api(method, url, body, raw) {
  const opt = { method, headers: {} };
  if (raw) { opt.body = raw.body; opt.headers = raw.headers; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch(url, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
const refreshMeta = async () => { META = await api("GET", "/api/meta"); };

function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), error ? 6000 : 2500);
}
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
async function busy(btn, label, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = label;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = old; }
}

function options(list, selected, labels = {}) {
  return list.map((v) => `<option value="${esc(v)}" ${String(v) === String(selected) ? "selected" : ""}>${esc(labels[v] ?? v)}</option>`).join("");
}
const ago = (t) => { const s = Date.now() / 1000 - t; return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : new Date(t * 1000).toLocaleDateString(); };
const titleCase = (s) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// one flat list of sets, newest first (order comes from /api/sets)
function setOptions(selected, list) {
  let html = `<option value="auto" ${selected === "auto" ? "selected" : ""}>✨ Auto from the title</option>`;
  if (String(selected).startsWith("new:")) html += `<option value="${esc(selected)}" selected>✨ New: ${esc(selected.slice(4))}</option>`;
  return html + list.map((s) => `<option value="${esc(s.id)}" ${s.id === selected ? "selected" : ""}>${esc(s.name)}</option>`).join("");
}
const WHERE = { "": "🎲 Inside or outside", inside: "Inside", outside: "Outside", air: "In the air (sky, space, sea)" };
const LIGHT = { "": "🎲 Any time", day: "Day", sunset: "Sunset", night: "Night" };
const LIGHT_ICON = { day: "☀", sunset: "🌅", night: "🌙" };
const COMFY_MODES = { required: "Required (always)", auto: "Only when needed", off: "Off" };

/* ------------------------------------------------------------------ jobs */
function watchJob(job, box, onDone) {
  box.innerHTML = `<div><span class="status ${job.status}">${job.status}</span> · ${esc(job.title)}</div><pre class="log"></pre>`;
  const pre = $("pre", box), st = $(".status", box);
  let from = 0;
  const tick = async () => {
    let j;
    try { j = await api("GET", `/api/jobs/${job.id}?from=${from}`); } catch { return setTimeout(tick, 2000); }
    if (j.log.length) {
      const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
      pre.textContent += j.log.join("\n") + "\n";
      if (stick) pre.scrollTop = pre.scrollHeight;
    }
    from = j.log_len;
    st.textContent = j.status; st.className = `status ${j.status}`;
    updateQueue();
    if (j.status === "done" || j.status === "failed") { onDone && onDone(j); return; }
    setTimeout(tick, 1000);
  };
  tick();
}

/* ------------------------------------------------------------------ job progress (top-right bar + panel) */
const JOBUI = { jobs: [], open: false, openLog: null, logFrom: {}, logs: {}, timer: null, flash: null };
const JOB_ICON = { render: "🎬", set: "🏞", music: "🎵", sfx: "🔊", props: "🎨", fx: "✨", postiz: "📤", voice: "🗣" };
const fmtDur = (s) => { s = Math.max(0, Math.round(s)); return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `${s}s`; };

function jobEta(j) {
  if (j.status !== "running" || !j.started || !(j.progress > 0.04) || j.progress >= 1) return null;
  const elapsed = Date.now() / 1000 - j.started;
  return elapsed / j.progress * (1 - j.progress);
}
function jobPct(j) { return j.progress == null ? null : Math.round(j.progress * 100); }
function jobLine(j) {
  if (j.status === "queued") return "Waiting in line…";
  if (j.status === "done") return `Done${j.ended && j.started ? ` in ${fmtDur(j.ended - j.started)}` : ""}`;
  if (j.status === "failed") return "Failed - open the log";
  const eta = jobEta(j);
  return [j.stage || j.last || "Working…", jobPct(j) != null ? `${jobPct(j)}%` : "", eta != null ? `~${fmtDur(eta)} left` : ""].filter(Boolean).join(" · ");
}
function barHtml(j, cls = "") {
  const p = jobPct(j);
  const ind = j.status === "running" && p == null;
  const state = j.status === "failed" ? "bad" : j.status === "done" ? "good" : j.status === "queued" ? "wait" : "";
  return `<span class="jb-track ${cls} ${state}"><span class="jb-fill ${ind ? "ind" : ""}" style="width:${ind ? 100 : j.status === "done" ? 100 : (p || 0)}%"></span></span>`;
}

async function updateQueue() {
  let jobs;
  try { jobs = await api("GET", "/api/jobs"); } catch { return scheduleQueue(5000); }
  const prev = JOBUI.jobs;
  JOBUI.jobs = jobs;
  // a job that just finished stays visible a few seconds with its result
  for (const j of jobs) {
    const before = prev.find((p) => p.id === j.id);
    if (before && (before.status === "running" || before.status === "queued") && (j.status === "done" || j.status === "failed")) {
      JOBUI.flash = { id: j.id, until: Date.now() + 8000 };
    }
  }
  drawQueue();
  if (JOBUI.open) drawJobPanel();
  scheduleQueue(jobs.some((j) => j.status === "running" || j.status === "queued") ? 1000 : 5000);
}
function scheduleQueue(ms) { clearTimeout(JOBUI.timer); JOBUI.timer = setTimeout(updateQueue, ms); }

function drawQueue() {
  const box = $("#queue");
  if (!box) return;
  const active = JOBUI.jobs.filter((j) => j.status === "running" || j.status === "queued");
  const flash = JOBUI.flash && Date.now() < JOBUI.flash.until ? JOBUI.jobs.find((j) => j.id === JOBUI.flash.id) : null;
  const j = active.find((x) => x.status === "running") || active[0] || flash;
  if (!j) {
    box.innerHTML = JOBUI.jobs.length ? `<button class="jobbar idle" aria-label="Recent jobs" title="Recent jobs"><span class="jb-idle">✓ Idle</span></button>` : "";
  } else {
    const more = active.length - (active.includes(j) ? 1 : 0);
    box.innerHTML = `<button class="jobbar ${j.status}" aria-label="Background jobs - show details" title="Click for details and logs">
      <span class="jb-ic">${JOB_ICON[j.kind] || "⚙"}</span>
      <span class="jb-text"><span class="jb-title">${esc(j.title)}</span><span class="jb-stage">${esc(jobLine(j))}</span>${barHtml(j)}</span>
      ${more > 0 ? `<span class="jb-badge" title="${more} more waiting">+${more}</span>` : ""}
    </button>`;
  }
  const btn = $(".jobbar", box);
  if (btn) btn.onclick = (e) => { e.stopPropagation(); toggleJobPanel(); };
}

function toggleJobPanel(force) {
  JOBUI.open = force ?? !JOBUI.open;
  let p = $("#jobpanel");
  if (!JOBUI.open) { if (p) p.remove(); return; }
  if (!p) {
    p = document.createElement("div");
    p.id = "jobpanel";
    p.className = "jobpanel";
    p.setAttribute("role", "dialog");
    p.setAttribute("aria-label", "Background jobs");
    document.body.appendChild(p);
    p.addEventListener("click", (e) => e.stopPropagation());
  }
  if (!JOBUI.openLog) {
    const run = JOBUI.jobs.find((j) => j.status === "running") || JOBUI.jobs[0];
    JOBUI.openLog = run?.id || null;
  }
  drawJobPanel();
}
document.addEventListener("click", () => { if (JOBUI.open) toggleJobPanel(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && JOBUI.open && !$(".modal-wrap")) toggleJobPanel(false); });

async function drawJobPanel() {
  const p = $("#jobpanel");
  if (!p) return;
  const jobs = JOBUI.jobs.slice(0, 12);
  const keepScroll = {};
  $$(".jp-log", p).forEach((pre) => { keepScroll[pre.dataset.id] = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24 ? "end" : pre.scrollTop; });
  p.innerHTML = `<div class="jp-head"><b>Background jobs</b><span class="muted small">${jobs.filter((j) => j.status === "running" || j.status === "queued").length} active</span>
      <button class="jp-x" aria-label="Close">✕</button></div>
    <div class="jp-list">${jobs.length ? jobs.map((j) => `
      <div class="jp-job ${j.status} ${JOBUI.openLog === j.id ? "open" : ""}" data-id="${esc(j.id)}">
        <button class="jp-row" data-toggle="${esc(j.id)}" aria-expanded="${JOBUI.openLog === j.id}">
          <span class="jb-ic">${JOB_ICON[j.kind] || "⚙"}</span>
          <span class="jp-main"><span class="jp-title">${esc(j.title)}</span><span class="jp-stage">${esc(jobLine(j))}</span>${barHtml(j, "thin")}</span>
          <span class="jp-status ${j.status}">${j.status === "running" && jobPct(j) != null ? jobPct(j) + "%" : j.status}</span>
          <span class="jp-chev">▾</span>
        </button>
        ${j.status === "failed" ? `<div style="padding:0 12px 8px"><button data-retry="${esc(j.id)}" class="primary">↻ Retry</button></div>` : ""}
        ${JOBUI.openLog === j.id ? `<pre class="jp-log" data-id="${esc(j.id)}">${esc((JOBUI.logs[j.id] || []).join("\n")) || "…"}</pre>` : ""}
      </div>`).join("") : `<p class="muted small" style="padding:14px">No jobs yet. Renders, new sets, music and uploads show up here.</p>`}</div>`;
  $(".jp-x", p).onclick = () => toggleJobPanel(false);
  $$("[data-toggle]", p).forEach((b) => b.onclick = () => { JOBUI.openLog = JOBUI.openLog === b.dataset.toggle ? null : b.dataset.toggle; drawJobPanel(); });
  $$("[data-retry]", p).forEach((b) => b.onclick = guard(async () => {
    const job = await api("POST", `/api/jobs/${b.dataset.retry}/retry`);
    toast("Retrying…");
    JOBUI.openLog = job.id;                      // show the new run's log straight away
    updateQueue();
  }));
  const pre = $(".jp-log", p);
  if (pre) {
    const id = pre.dataset.id;
    pre.scrollTop = keepScroll[id] === undefined || keepScroll[id] === "end" ? pre.scrollHeight : keepScroll[id];
    // fetch new log lines for the open job
    try {
      const j = await api("GET", `/api/jobs/${id}?from=${JOBUI.logFrom[id] || 0}`);
      if (j.log.length) {
        JOBUI.logs[id] = (JOBUI.logs[id] || []).concat(j.log).slice(-1500);
        JOBUI.logFrom[id] = j.log_len;
        const cur = $(`#jobpanel .jp-log[data-id="${id}"]`);
        if (cur) {
          const stick = cur.scrollTop + cur.clientHeight >= cur.scrollHeight - 24;
          cur.textContent = JOBUI.logs[id].join("\n");
          if (stick) cur.scrollTop = cur.scrollHeight;
        }
      }
    } catch { /* job gone */ }
  }
}

/* ------------------------------------------------------------------ voice editor (shared) */
const ENGINES = {
  local: "Local clone (free, Chatterbox)",
  edge: "Microsoft neural (free, online)",
  elevenlabs: "ElevenLabs (paid API)",
  windows: "Windows built-in (offline, robotic)",
};
async function voiceEditor(box, voice, onChange, { charId } = {}) {
  const v = voice;
  v.engine = v.engine || "edge";
  const field = (k, label, type = "text", extra = "") =>
    `<label>${label}<input type="${type}" data-k="${k}" value="${esc(v[k] ?? "")}" ${extra}></label>`;
  let html = `<div class="row"><label>Engine<select data-k="engine">${options(Object.keys(ENGINES), v.engine, ENGINES)}</select></label>`;
  if (v.engine === "local") {
    html += field("exaggeration", "Default emotion (0.25–1)", "number", 'step="0.05" min="0.25" max="1" placeholder="0.5"') + "</div>";
    html += `<div class="help-box" style="margin-top:8px">Reference voice: <code>${esc(v.ref || "none (built-in voice)")}</code>
      ${charId ? `<br><label style="margin-top:6px">Upload a new reference (10–30 s of clean speech you have rights to; wav/mp3/m4a)
      <input type="file" accept="audio/*" data-upload="voice"></label>` : ""}</div>`;
  } else if (v.engine === "edge") {
    html += `<label>Voice<input type="text" data-k="name" list="edge-voices" value="${esc(v.name ?? "en-US-AnaNeural")}"></label>`;
    html += field("rate", "Rate", "text", 'placeholder="+8%"') + field("pitch", "Pitch", "text", 'placeholder="+15Hz"') + "</div>";
    html += `<datalist id="edge-voices"></datalist>`;
  } else if (v.engine === "elevenlabs") {
    html += field("voice_id", "Voice ID") + field("model", "Model", "text", 'placeholder="eleven_multilingual_v2"') + "</div>";
    html += `<p class="help-box">Needs the <code>ELEVENLABS_API_KEY</code> environment variable set before starting the server.</p>`;
  } else html += "</div>";
  html += `<div class="row" style="margin-top:8px">${field("shift", "Extra pitch shift (1 = none)", "number", 'step="0.01" min="0.7" max="1.6" placeholder="1.0"')}</div>`;
  box.innerHTML = html;
  $$("[data-k]", box).forEach((el) => el.addEventListener("change", () => {
    const k = el.dataset.k;
    let val = el.value;
    if (el.type === "number") val = val === "" ? undefined : Number(val);
    if (val === undefined || val === "") delete v[k]; else v[k] = val;
    if (k === "engine") { for (const key of Object.keys(v)) if (key !== "engine" && key !== "shift" && !(val === "local" && key === "ref")) delete v[key]; voiceEditor(box, v, onChange, { charId }); }
    onChange(v);
  }));
  const up = $("[data-upload=voice]", box);
  if (up) up.addEventListener("change", guard(async () => {
    const f = up.files[0]; if (!f) return;
    toast("Uploading reference voice…");
    const info = await api("POST", `/api/characters/${charId}/voice-ref`, undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    Object.assign(v, info.profile.voice);
    toast("Reference voice saved");
    voiceEditor(box, v, onChange, { charId });
    onChange(v);
  }));
  if (v.engine === "edge") {
    api("GET", "/api/voices/edge").then((list) => {
      const dl = $("#edge-voices", box);
      if (dl) dl.innerHTML = list.map((x) => `<option value="${esc(x.name)}">${esc(x.gender)} · ${esc(x.locale)}</option>`).join("");
    }).catch(() => {});
  }
}

/* ------------------------------------------------------------------ CREATE */
let setsCache = [];
const blankEpisode = () => ({ title: "", set: "cafe", start: "door", shots: [] });
const CS = { id: "", ep: blankEpisode(), tab: "write", titles: [], model: "", lines: 6, tone: "funny", extra: "", autoDirect: true, places: [], newPlaces: [], beats: true };
// caption looks: how many words show at once, the colour cycle, and the outline
const CAP_COLORS = ["#ffffff", "#f0e060", "#ff8fb8", "#8fe6ff"];
const CAP_STYLES = {
  "two-colour": { label: "Two words, each word a colour", caps: { group: 2, cycle: CAP_COLORS, outline: 0 } },
  "one-colour": { label: "One word, each word a colour", caps: { group: 1, cycle: CAP_COLORS, outline: 0 } },
  "one-white": { label: "One word, white with an outline", caps: { group: 1, cycle: [], outline: 2 } },
};
function capStyleOf() {
  const c = { ...(META?.settings?.captions || {}), ...(CS.ep.captions || {}) };
  if (Number(c.group) === 1) return (c.cycle || []).length ? "one-colour" : "one-white";
  return "two-colour";
}
const TONES = ["funny", "wholesome", "chaotic", "sarcastic", "dramatic", "spooky", "cute", "deadpan",
  "excited", "romantic", "nervous", "grumpy", "confused", "proud", "silly", "heartfelt", "mysterious", "motivational"];

async function pageCreate() {
  const [eps, music, setsList] = await Promise.all([api("GET", "/api/episodes"), api("GET", "/api/music"), api("GET", "/api/sets")]);
  setsCache = setsList;
  const cat = META.catalog;
  for (const s of setsList) if (cat.sets[s.id]) cat.sets[s.id].preview = s.preview;
  if (!cat.sets[CS.ep.set] && CS.ep.set !== "auto" && !String(CS.ep.set).startsWith("new:")) CS.ep.set = setsList[0]?.id || "cafe";
  const presets = Object.keys(META.presets);
  app.innerHTML = `
  <section class="panel create-hero">
    <h2 class="hero-title">✨ What shall we make today?</h2>
    <div class="hero-btns">
      <button id="make-all" class="hero-btn" style="--d:0"><span class="hb-ico make-roll">🎲</span><b>Make a Random Video</b>
        <small>Pick fun cards - the studio writes, builds and renders it all</small></button>
      <button id="make-series" class="hero-btn" style="--d:1"><span class="hb-ico">📺</span><b>Make a Series</b>
        <small>One idea, 1-4 episodes, each made and rendered for you</small></button>
      <button id="make-custom" class="hero-btn hb-custom" style="--d:2"><span class="hb-ico">🪄</span><b>Custom Video</b>
        <small>Step by step: your idea, your look, your script, your scenes</small></button>
    </div>
    <div class="hero-foot"><span id="make-status" class="muted small"></span></div>
    <div class="make-bar"><i id="make-fill"></i></div>
    <div class="inline-job" id="make-job"></div>
    <div id="job"></div>
    <div id="result" class="hero-result"></div>
  </section>
  <!-- the old step-by-step page: never shown any more (Custom Video's popup has all of it), but the random-video
       flow and the save / render buttons still work through these fields -->
  <div class="grid2" id="full-ed" hidden>
    <div>
      <section class="panel">
        <div class="step-h"><span class="stepno">1</span><h3>Idea</h3>
          ${CS.id ? `<span class="muted small">editing “${esc(CS.ep.title || CS.id)}”</span>` : ""}
          <button id="ep-new" class="ghost" title="Clear everything and start a new episode">↺ Start over</button></div>
        <label>Title (shown at the top)<input type="text" id="ep-title" placeholder="What if a catgirl…?" value="${esc(CS.ep.title)}"></label>
        <div class="row" style="margin-top:8px">
          <label style="flex:2">Topic for title ideas (optional)<input type="text" id="t-theme" placeholder="e.g. school, cooking, video games"></label>
          <button id="t-ideas">✨ Title ideas (AI)</button></div>
        <div class="chips" id="t-chips">${CS.titles.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        <div class="row" style="margin-top:10px">
          <label>Kind of video<select id="ep-tpl" title="Steers the title ideas, the script and the pacing - the look stays the same">${(META.catalog.templates || []).map((t) =>
            `<option value="${t.id}" ${t.id === (CS.ep.template || "what_if") ? "selected" : ""}>${t.icon} ${esc(t.name)}</option>`).join("")}</select></label>
          <label>Character<select id="ep-char"><option value="">Active (${esc(META.settings.active_character)})</option>${options(META.characters, typeof CS.ep.character === "string" ? CS.ep.character : "")}</select></label></div>
        <div style="margin-top:10px"><span class="muted small">Other main characters in this video - they talk and react too. A line that starts with their name (“${esc(titleCase(META.characters.find((c) => c !== (CS.ep.character || META.settings.active_character)) || "name"))}: …”) is theirs.</span>
          <div class="chips" id="ep-co">${META.characters.filter((c) => c !== (CS.ep.character || META.settings.active_character)).map((c) =>
            `<button class="chip-btn ${(CS.ep.co_stars || []).includes(c) ? "on" : ""}" data-co="${esc(c)}">${esc(titleCase(c))}</button>`).join("")
            || '<span class="muted small">Make a second character on the Characters page first.</span>'}</div></div>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">2</span><h3>Scene &amp; style</h3></div>
        <div class="scene"><div id="set-thumb"></div><div>
          <div class="row"><label style="flex:2">Set<select id="ep-set">${setOptions(CS.ep.set, setsList)}</select></label>
            <label>Starts at<select id="ep-start"></select></label></div>
          <div style="margin-top:8px"><span class="muted small">Change place every line - pick two or more places to rotate through (leave empty to keep one place)</span>
            <div class="chips" id="rs-places">${Object.keys(META.catalog.sets).map((k) => `<button class="chip-btn ${CS.places.includes(k) ? "on" : ""}" data-place="${esc(k)}">${esc(META.catalog.sets[k].name || titleCase(k))}</button>`).join("")}</div></div>
          <label style="margin-top:8px">New places for lines (optional, comma separated) <span class="muted small">- each one is designed and textured when the video renders, which takes a few minutes each</span>
            <input type="text" id="rs-newplaces" placeholder="e.g. moon base, haunted bakery" value="${esc(CS.newPlaces.join(", "))}"></label>
          <label style="margin-top:8px">New set idea (optional)<input type="text" id="rs-idea" placeholder="e.g. haunted bakery - or leave empty to be surprised"></label>
          <div class="row" style="margin-top:6px">
            <label><select id="rs-where">${options(Object.keys(WHERE), "", WHERE)}</select></label>
            <label><select id="rs-light">${options(Object.keys(LIGHT), "", LIGHT)}</select></label>
            <button id="rs-go">🎲 Generate new set</button></div>
          <div id="rs-job" class="inline-job"></div>
          </div></div>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">3</span><h3>Look</h3></div>
        <div class="row" style="margin-top:8px">
            <label>Look<select id="ep-look"><option value="">Global settings</option>${options(presets, CS.ep.look_preset || "")}</select></label>
            <label>Video language<select id="ep-lang"><option value="">Settings default (${esc(langName(META.settings.language))})</option>${options(Object.keys(cat.languages || {}), CS.ep.language || "", cat.languages || {})}</select></label>
            <button id="ep-trans" style="align-self:flex-end" title="See every translated line and fix any of them before rendering">🌐 Check translation</button>
        </div>
        <p class="muted small" style="margin:6px 0 0">Write in English - the finished video (voice, captions, title, end card) is in the language you pick. Other languages use a Microsoft voice of that language (your cloned voice only speaks English).</p>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">4</span><h3>Music</h3></div>
        <div class="row">
            <label>Music<select id="ep-music"><option value="">${META.settings.audio.default_music ? "Default (" + esc(META.settings.audio.default_music.split("/").pop()) + ")" : "Default (none)"}</option>${options(music.map((m) => m.path), CS.ep.music || "", Object.fromEntries(music.map((m) => [m.path, "🎵 " + m.name])))}<option value="__none" ${CS.ep.music === "" ? "selected" : ""}>No music</option></select></label>
        </div>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">5</span><h3>Ambience</h3></div>
        <div class="row">
            <label>Ambience<select id="ep-amb"><option value="">Settings default (${esc(META.settings.sfx.ambience || "off")})</option><option value="auto" ${CS.ep.ambience === "auto" ? "selected" : ""}>Auto from set</option><option value="__none" ${CS.ep.ambience === "" ? "selected" : ""}>None</option>${options(Object.keys(META.sfx).filter((k) => META.sfx[k].kind === "ambience"), CS.ep.ambience || "", Object.fromEntries(Object.entries(META.sfx).map(([k, v]) => [k, v.label.replace("Ambience: ", "")])))}</select></label></div>
          <p class="muted small" style="margin:6px 0 0">Add royalty-free tracks and sound effects on the <a href="#assets">Assets</a> page (Music and Sounds).</p>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">6</span><h3>Captions</h3></div>
          <div class="row" style="margin-top:10px;align-items:flex-end;flex-wrap:wrap">
            <label class="check" style="flex:1 1 220px"><input type="checkbox" id="ep-beats" ${CS.beats === false ? "" : "checked"}> Cut to a new shot every few words</label>
            <label style="flex:1 1 240px">Caption style<select id="ep-capstyle">${options(Object.keys(CAP_STYLES), capStyleOf(), Object.fromEntries(Object.entries(CAP_STYLES).map(([k, v]) => [k, v.label])))}</select></label>
          </div>
          <p class="muted small" style="margin:6px 0 0">Long lines are cut into beats, each with its own camera angle. The voice is recorded once per line.</p>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">7</span><h3>Script</h3></div>
        <div class="tabs"><button class="tab ${CS.tab === "write" ? "on" : ""}" data-tab="write">✍ Write</button>
          <button class="tab ${CS.tab === "ai" ? "on" : ""}" data-tab="ai">🤖 AI write (Ollama)</button></div>
        <div id="tab-write" ${CS.tab === "write" ? "" : "hidden"}>
          <textarea id="script" rows="8" placeholder="One line per shot. Example:&#10;Okay! First day running my very own cafe. Nya!&#10;How hard can making coffee be?&#10;[low, angry] Fine. I'll hiss back!"></textarea>
          <div class="btns"><button id="direct" class="primary">🎬 Direct shots from script</button>
            <span class="muted small" style="align-self:center">Replaces the shot list. Optional directions per line in [brackets].</span></div>
          <label class="check" style="margin-top:6px"><input type="checkbox" id="cast-ai" ${CS.castAI !== false ? "checked" : ""}> 🎭 Let the AI add other people &amp; things the script brings in (Ollama)</label>
          <div class="row" style="align-items:center;margin-top:4px">
            <label class="check" style="flex:2"><input type="checkbox" id="scene-ai" ${CS.sceneAI !== false ? "checked" : ""}> 🗺 Let the AI change scenes &amp; add weather/effects when the story moves (Ollama)</label>
            <label style="flex:1">Scene changes<select id="scene-policy">${options(["reuse", "new"], CS.scenePolicy || "reuse", { reuse: "Reuse my sets when they fit", new: "Always make new sets" })}</select></label></div>
          <details style="margin-top:10px"><summary>Direction words you can use in [brackets]</summary>
            <div class="help-box" style="margin-top:6px">
              <b>Camera:</b> ${Object.keys(cat.cameras).map((c) => `<code>${c}</code>`).join(" ")}<br>
              <b>Move:</b> ${Object.keys(cat.moves).map((c) => `<code>${c}</code>`).join(" ")}<br>
              <b>Action:</b> ${Object.keys(cat.anims).map((c) => `<code>${c}</code>`).join(" ")}<br>
              <b>Expression:</b> ${cat.expressions.map((c) => `<code>${c}</code>`).join(" ")}<br>
              <b>Places</b> (for walk_to / run_to / sneak_to): <span id="mark-help"></span><br>
              <b>Duration:</b> e.g. <code>3s</code><br>
              <b>Light</b> (from this line on): ${Object.keys(cat.lights || {}).map((c) => `<code>${c}</code>`).join(" ")} - e.g. <code>[night] It got dark.</code><br>
              <b>Who says it:</b> start the line with a name - <code>Ethan: Hi!</code> for a co-star, <code>Mom: Lunch!</code> for someone brought in with <code>+mom</code>.<br>
              <b>Change scene:</b> <code>[@ falling through the clouds]</code> <code>[@ on the moon]</code> - lasts until the next <code>@</code>. One of your sets is reused if it fits, otherwise a new set is made (once) when the video renders and added to Sets.<br>
              <b>Cutaway</b> (show something instead of her while she talks): <code>[cutaway: a plane flying past]</code> <code>[cut: ants marching]</code><br>
              <b>Effects:</b> ${Object.keys(cat.particles || {}).map((c) => `<code>${c}</code>`).join(" ")} <code>no_fx</code> - also switched on by words like "raining" or "confetti".<br>
              <b>Others in the scene:</b> <code>+name verb</code>, e.g. <code>[+mom enter]</code> <code>[+mom angry]</code> <code>[+car crash_in from_left]</code>.
              People get a simple low-poly body, things are built by the AI prop designer.<br>
              Verbs: ${Object.keys(cat.cast_verbs || {}).map((c) => `<code>${c}</code>`).join(" ")} - people can also do any action above. From: ${(cat.from_sides || []).map((c) => `<code>from_${c}</code>`).join(" ")}</div></details>
        </div>
        <div id="tab-ai" ${CS.tab === "ai" ? "" : "hidden"}>
          <div class="row"><label style="flex:2">Model<select id="ai-model"><option>Loading models…</option></select></label>
            <label>Lines<input type="number" id="ai-lines" min="2" max="14" value="${CS.lines}"></label>
            <label>Tone<select id="ai-tone">${options(TONES, CS.tone)}</select></label></div>
          <label style="margin-top:8px">Extra notes for the AI (optional)<textarea id="ai-extra" rows="2" placeholder="e.g. she is afraid of cucumbers; end with a twist">${esc(CS.extra)}</textarea></label>
          <label class="check" style="margin-top:8px"><input type="checkbox" id="ai-auto" ${CS.autoDirect ? "checked" : ""}> Direct shots automatically</label>
          <div class="btns"><button id="ai-go" class="primary">🤖 Write script from title</button>
            <span class="muted small" style="align-self:center" id="ai-status"></span></div>
          <p class="help-box" style="margin-top:10px">Uses the title, the character's “about” text and the chosen set. Other main characters you picked get lines of their own (“Name: …”). The result lands in the ✍ Write tab, so you can edit it before rendering.</p>
        </div>
      </section>

      <section class="panel">
        <div class="step-h"><span class="stepno">8</span><h3>Shots</h3><button id="add-shot">+ Add shot</button></div>
        <div id="shots"></div>
        <div id="cast-box"></div>
        <details><summary>Advanced: edit episode JSON</summary>
          <textarea id="json" rows="12" class="mono" style="margin-top:6px"></textarea>
          <div class="btns"><button id="json-apply">Apply JSON</button></div></details>
      </section>
    </div>
    <div class="side">
      <div class="panel">
        <h3>Make the video</h3>
        <label class="check"><input type="checkbox" id="fresh"> Regenerate voice lines (new takes)</label>
        <div class="btns">
          <button id="save">💾 Save</button>
          <button id="render" class="primary">▶ Save &amp; render</button>
          <button id="relook" title="Re-apply look/captions to the last render without re-rendering 3D">Re-apply look only</button>
        </div>
        <p class="muted small" style="margin:8px 0 0">The progress and the finished video show at the top of the page.</p>
      </div>
    </div>
  </div>`;

  const marksFor = (set) => cat.sets[set]?.marks || ["center", "front", "left", "right", "back"];
  const refreshScene = () => {
    const ms = marksFor(CS.ep.set);
    if (!ms.includes(CS.ep.start)) CS.ep.start = ms.includes("front") ? "front" : ms[0];
    $("#ep-start").innerHTML = options(ms, CS.ep.start);
    $("#mark-help").innerHTML = ms.map((m) => `<code>${m}</code>`).join(" ");
    const s = META.catalog.sets[CS.ep.set];
    const note = CS.ep.set === "auto" ? "✨ The AI picks where it happens from your title when you write or direct the script (one of your sets if it fits, otherwise a new one)."
      : String(CS.ep.set).startsWith("new:") ? `✨ A new set will be made for “${CS.ep.set.slice(4)}” when the video renders.` : (s?.description || "");
    $("#set-thumb").innerHTML = (s?.preview ? `<img src="${esc(s.preview)}" alt="" onerror="this.style.visibility='hidden'">` : `<div class="noimg">✨</div>`)
      + `<div class="muted small" style="margin-top:4px">${esc(note)}</div>`;
    const sel = $("#ep-set");
    if (sel && sel.value !== CS.ep.set) sel.innerHTML = setOptions(CS.ep.set, setsCache);
  };
  refreshScene();
  // what's in the box survives redraws of the page; a directed episode keeps the script it was directed from
  $("#script").value = CS.scriptDraft ?? CS.ep.script ?? CS.ep.shots.map((s) => s.line || "").join("\n");
  $("#script").oninput = (e) => { CS.scriptDraft = e.target.value; };

  const syncJson = () => { $("#json").value = JSON.stringify(CS.ep, null, 2); };
  const renderShots = () => { drawShots($("#shots"), CS.ep, marksFor(CS.ep.set), () => { drawCast($("#cast-box"), CS.ep, syncJson); syncJson(); });
    drawCast($("#cast-box"), CS.ep, syncJson); syncJson(); };
  renderShots();
  showResult(eps.find((e) => e.id === CS.id)?.video);

  $("#ep-new").onclick = guard(async () => {
    if ((CS.ep.shots.length || CS.ep.title) && !(await uiConfirm("Clear this episode and start a new one? Saved videos stay in Videos.", { title: "Start a new video", ok: "Start new" }))) return;
    const keepSet = CS.ep.set;
    CS.ep = blankEpisode(); CS.ep.set = keepSet; CS.id = ""; CS.titles = []; CS.keepId = false; CS.rendered = null;
    CS.scriptDraft = undefined;
    pageCreate();
  });
  $$("#rs-places [data-place]").forEach((b) => b.onclick = () => {
    const id = b.dataset.place;
    CS.places = CS.places.includes(id) ? CS.places.filter((x) => x !== id) : [...CS.places, id];
    b.classList.toggle("on", CS.places.includes(id));
  });
  $("#rs-newplaces").onchange = (e) => { CS.newPlaces = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); };
  $("#ep-beats").onchange = (e) => { CS.beats = e.target.checked; };
  $("#ep-capstyle").onchange = (e) => { CS.ep.captions = { ...(CS.ep.captions || {}), ...CAP_STYLES[e.target.value].caps }; syncJson(); };
  $("#ep-title").oninput = (e) => { CS.ep.title = e.target.value; syncJson(); };
  $("#ep-tpl").onchange = (e) => {                  // the kind of video: its own tone, length and pacing
    CS.ep.template = e.target.value;
    const t = (META.catalog.templates || []).find((x) => x.id === CS.ep.template);
    if (t) { CS.tone = t.tone; CS.lines = t.lines[0]; const tn = $("#ai-tone"); if (tn) tn.value = t.tone; const ln = $("#ai-lines"); if (ln) ln.value = CS.lines; }
    toast(`${t?.icon || ""} ${t?.name || ""}: ${t?.about || ""}`);
    syncJson();
  };
  $("#ep-char").onchange = (e) => { if (e.target.value) CS.ep.character = e.target.value; else delete CS.ep.character;
    // the episode's own character can't also be a co-star
    CS.ep.co_stars = (CS.ep.co_stars || []).filter((c) => c !== (CS.ep.character || META.settings.active_character));
    if (!CS.ep.co_stars.length) delete CS.ep.co_stars;
    syncJson(); };
  $$("#ep-co [data-co]").forEach((b) => b.onclick = () => {
    const id = b.dataset.co, now = CS.ep.co_stars || [];
    CS.ep.co_stars = now.includes(id) ? now.filter((x) => x !== id) : [...now, id];
    if (!CS.ep.co_stars.length) delete CS.ep.co_stars;
    b.classList.toggle("on", !now.includes(id));
    renderShots(); syncJson();
  });
  $("#ep-set").onchange = guard(async (e) => {
    CS.ep.set = e.target.value; refreshScene(); renderShots();
    // the shots were directed for the old set (its places, e.g. "counter") - offer to direct them again
    if (CS.ep.shots.length && $("#script").value.trim() &&
        await uiConfirm("The shots were set up for the previous set, so walks to its places would be dropped.\n\n"
          + "If the script talks about the old place (e.g. “this cozy cafe”), rewrite those lines or use AI write again.",
          { title: "Direct the shots again for this set?", ok: "🎬 Direct again" })) {
      await directNow(false);
    }
  });
  $("#ep-start").onchange = (e) => { CS.ep.start = e.target.value; syncJson(); };
  const showTrans = () => { $("#ep-trans").hidden = (CS.ep.language || META.settings.language || "en") === "en"; };
  showTrans();
  $("#ep-lang").onchange = (e) => { if (e.target.value) CS.ep.language = e.target.value; else delete CS.ep.language; showTrans(); syncJson(); };
  $("#ep-trans").onclick = guard(async (e) => checkTranslation(CS.ep, e.currentTarget, syncJson));
  $("#ep-look").onchange = (e) => {
    if (e.target.value) { CS.ep.look_preset = e.target.value; delete CS.ep.look; }   // the preset IS the look now
    else delete CS.ep.look_preset;
    syncJson(); };
  $("#ep-music").onchange = (e) => { const v = e.target.value; if (v === "__none") CS.ep.music = ""; else if (v) CS.ep.music = v; else delete CS.ep.music; syncJson(); };
  $("#ep-amb").onchange = (e) => { const v = e.target.value; if (v === "__none") CS.ep.ambience = ""; else if (v) CS.ep.ambience = v; else delete CS.ep.ambience; syncJson(); };

  // title ideas
  const bindChips = () => $$("#t-chips .chip").forEach((c) => c.onclick = () => { CS.ep.title = c.textContent; $("#ep-title").value = c.textContent; syncJson(); });
  bindChips();
  $("#t-ideas").onclick = guard(async (e) => busy(e.currentTarget, "✨ Thinking…", async () => {
    const r = await api("POST", "/api/ai/titles", { theme: $("#t-theme").value, character: $("#ep-char").value, model: CS.model, template: CS.ep.template || "" });
    CS.titles = r.titles;
    $("#t-chips").innerHTML = r.titles.map((t) => `<span class="chip" title="Use this title">${esc(t)}</span>`).join("");
    bindChips();
  }));

  // random set
  $("#rs-go").onclick = guard(async () => {
    const job = await api("POST", "/api/sets/generate", { idea: $("#rs-idea").value, where: $("#rs-where").value, light: $("#rs-light").value });
    watchJob(job, $("#rs-job"), guard(async (j) => {
      if (j.status !== "done" || !j.result.set) return toast("Set generation failed - see the log", true);
      await refreshMeta();
      CS.ep.set = j.result.set; CS.ep.start = "front";
      toast(`New set: ${META.catalog.sets[j.result.set]?.name}`);
      pageCreate();
    }));
  });

  // script tabs
  $$(".tab").forEach((t) => t.onclick = () => { CS.tab = t.dataset.tab; $$(".tab").forEach((x) => x.classList.toggle("on", x === t)); $("#tab-write").hidden = CS.tab !== "write"; $("#tab-ai").hidden = CS.tab !== "ai"; });
  api("GET", "/api/ollama/models").then((r) => {
    const sel = $("#ai-model"); if (!sel) return;
    if (!r.ok) { sel.innerHTML = `<option value="">Ollama offline</option>`; $("#ai-status").innerHTML = `<span class="err">${esc(r.error)}</span>`; return; }
    CS.model = CS.model || META.settings.ollama.model;
    const names = r.models.map((m) => m.name);
    if (!names.includes(CS.model)) CS.model = names.find((n) => n.startsWith(CS.model.split(":")[0])) || names[0];
    sel.innerHTML = options(names, CS.model, Object.fromEntries(r.models.map((m) => [m.name, `${m.name}  (${m.params || m.size_gb + " GB"})`])));
  }).catch(() => {});
  $("#ai-model").onchange = (e) => { CS.model = e.target.value; };
  $("#ai-lines").onchange = (e) => { CS.lines = Number(e.target.value) || 6; };
  $("#ai-tone").onchange = (e) => { CS.tone = e.target.value; };
  $("#ai-extra").oninput = (e) => { CS.extra = e.target.value; };
  $("#ai-auto").onchange = (e) => { CS.autoDirect = e.target.checked; };
  $("#ai-go").onclick = guard(async (e) => busy(e.currentTarget, "🤖 Writing…", async () => {
    if (!CS.ep.title.trim()) throw new Error("Give the episode a title first (or use ✨ Title ideas)");
    const t0 = Date.now();
    const r = await api("POST", "/api/ai/script", { title: CS.ep.title, set: CS.ep.set, scene_policy: $("#scene-policy")?.value || "reuse", character: $("#ep-char").value,
      model: CS.model, lines: CS.lines, tone: CS.tone, extra: CS.extra, co_stars: CS.ep.co_stars || [], template: CS.ep.template || "" });
    $("#script").value = r.script; CS.scriptDraft = r.script;
    if (r.set && r.set !== CS.ep.set) { CS.ep.set = r.set; refreshScene(); toast(`Set: ${META.catalog.sets[r.set]?.name || "new - " + r.set.slice(4)}`); }
    $("#ai-status").textContent = `${r.lines.length} lines from ${r.model} in ${((Date.now() - t0) / 1000).toFixed(1)}s`;
    CS.tab = "write"; $$(".tab")[0].click();
    if (CS.autoDirect) await directNow(false);
    toast("Script written - edit it if you like");
  }));

  const directNow = async (ask = true) => {
    const script = $("#script").value;
    if (!script.trim()) throw new Error("Write a script first");
    if (ask && CS.ep.shots.length && !(await uiConfirm("Replace the current shots with new ones from the script? Changes you made to the shots are lost.", { title: "Direct shots", ok: "Replace shots" }))) return;
    const castAI = $("#cast-ai")?.checked;
    const r = await api("POST", "/api/autodirect", { script, set: CS.ep.set, start: CS.ep.start, cast: CS.ep.cast || {}, co_stars: CS.ep.co_stars || [], beat_words: CS.beats === false ? 0 : 4,
      beat_sets: (CS.places.length + CS.newPlaces.length) > 1 ? [...CS.places, ...CS.newPlaces.map((p) => "new:" + p)] : [],
      cast_ai: castAI, character: $("#ep-char")?.value, scene_ai: $("#scene-ai")?.checked, title: CS.ep.title,
      scene_policy: $("#scene-policy")?.value || "reuse", template: CS.ep.template || "" });
    CS.ep.shots = r.shots; CS.ep.start = r.start; CS.ep.script = script;
    if (r.set && r.set !== CS.ep.set) CS.ep.set = r.set;
    if (r.cast && Object.keys(r.cast).length) CS.ep.cast = r.cast; else delete CS.ep.cast;
    refreshScene(); renderShots();
    const n = Object.keys(r.cast || {}).length;
    const scenes = new Set(r.shots.map((s) => s.set || CS.ep.set)).size;
    const fresh = new Set(r.shots.filter((s) => String(s.set || "").startsWith("new:")).map((s) => s.set)).size;
    toast(`Directed ${r.shots.length} shots` + (n ? ` · 🎭 ${n} in the cast` : "") + (scenes > 1 ? ` · 🗺 ${scenes} scenes` : "")
      + (fresh ? ` (${fresh} new set${fresh > 1 ? "s" : ""} will be made when it renders)` : "")
      + (r.cast_note ? ` (${r.cast_note})` : "") + (r.scene_note ? ` (${r.scene_note})` : ""));
  };
  $("#direct").onclick = guard(() => directNow(true));
  $("#cast-ai").onchange = (e) => { CS.castAI = e.target.checked; };
  $("#scene-ai").onchange = (e) => { CS.sceneAI = e.target.checked; };
  $("#scene-policy").onchange = (e) => { CS.scenePolicy = e.target.value; };
  $("#add-shot").onclick = () => { CS.ep.shots.push({ camera: "medium", action: "idle", expression: "neutral", line: "" }); renderShots(); };
  $("#json-apply").onclick = guard(() => { CS.ep = JSON.parse($("#json").value); CS.scriptDraft = undefined; pageCreate(); toast("JSON applied"); });

  const save = async () => {
    if (!CS.ep.shots.length) throw new Error("Add at least one shot (write a script and press Direct)");
    // every new video is its own episode: unique file name from the title + a short stamp
    if (!CS.id) CS.id = ((CS.ep.title || "episode").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "episode")
      + "_" + Date.now().toString(36).slice(-5);
    await api("PUT", `/api/episodes/${CS.id}`, CS.ep);
    return CS.id;
  };
  $("#save").onclick = guard(async () => { await save(); toast("Saved"); });
  const render = (reuse) => guard(async () => {
    // a finished video is never overwritten by a different script: once a video has rendered, changing the
    // script and rendering again makes a NEW video. Videos opened for editing from the Videos page keep their file.
    if (!CS.keepId && CS.rendered && JSON.stringify(CS.ep) !== CS.rendered) CS.id = "";
    const id = await save();
    CS.rendered = JSON.stringify(CS.ep);
    const job = await api("POST", "/api/render", { id, fresh_voice: $("#fresh").checked, reuse_frames: reuse });
    watchJob(job, $("#job"), (j) => {
      if (j.status === "done") { showResult(j.result.video + "?t=" + Date.now(), j.result.sheet + "?t=" + Date.now()); toast("Video ready!"); }
      else toast("Render failed - see the log", true);
    });
  });
  $("#render").onclick = render(false);
  $("#relook").onclick = render(true);

  // one button: a random idea, a random new scene, the script and the shots (rendering stays a separate step)
  const waitJob = (job, box) => new Promise((resolve, reject) => watchJob(job, box, (j) =>
    (j.status === "done" && j.result?.set ? resolve(j) : reject(new Error("the scene could not be made - see the log")))));
  $("#make-series").onclick = guard(() => openSeriesDialog());
  // the step-by-step popup fills the episode in, then the (hidden) page's own save / render buttons run
  $("#make-custom").onclick = guard(async () => {
    const r = await openCustomWizard();
    if (!r) return;
    await pageCreate();
    $("#fresh").checked = !!r.fresh;
    $(r.how === "render" ? "#render" : "#save").click();
  });
  $$(".hero-btn").forEach((b) => b.addEventListener("click", (ev) => sparkle(b, ev)));
  if (CS.openWiz) { CS.openWiz = false; $("#make-custom").click(); }     // "Open in Custom Video" from the Videos page
  $("#make-all").onclick = guard(async (e) => {
    const btnEl = e.currentTarget;
    const picks = await openMakeWizard();        // the cards: place, topic, vibe, guest, time, length + a note
    if (!picks) return;
    const panel = btnEl.closest(".panel");
    panel.classList.add("making");
    $("#make-fill").style.width = "4%";
    try { await busy(btnEl, "🎲 Making…", async () => {
    // the status line and the bar move on together: step n of 4 fills (n - 1) quarters and a bit more
    const status = (t) => {
      $("#make-status").textContent = t;
      const n = Number((t.match(/^(\d)\/5/) || [])[1]);
      if (n) $("#make-fill").style.width = ((n - 1) * 20 + 10) + "%";
      if (t.startsWith("Done")) $("#make-fill").style.width = "100%";
    };
    const pick = (a) => a[Math.floor(Math.random() * a.length)];
    status("1/5 Thinking up an idea…");
    const kind = (META.catalog.templates || []).find((t) => `${t.icon} ${t.name}` === picks.kind);
    CS.ep.template = kind?.id || "what_if";
    if ($("#ep-tpl")) $("#ep-tpl").value = CS.ep.template;
    const tr = await api("POST", "/api/ai/titles", { theme: picks.topic, character: $("#ep-char").value, model: CS.model, template: CS.ep.template });
    if (!tr.titles?.length) throw new Error("No idea came back - try again");
    CS.ep.title = pick(tr.titles);
    $("#ep-title").value = CS.ep.title;
    // the length card picks the number of lines; music, ambience and look use their defaults, not a random pick
    // lines -> seconds: each line is ~4-5 s once split into beats (a 12-line "medium" video ran 60 s)
    const [lo, hi] = picks.length.startsWith("short") ? [4, 5] : picks.length.startsWith("long") ? [10, 13] : [6, 8];
    CS.lines = lo + Math.floor(Math.random() * (hi - lo + 1));
    CS.tone = picks.tone;
    const guest = picks.guest.startsWith("nobody") ? "" : `${picks.guest} shows up and plays a part (bring them in with +name). `;
    const when = /turning into/.test(picks.time) ? `Time: ${picks.time} - change the light along the way with [sunset], [night] or [dawn]. ` : `Time: ${picks.time}. `;
    CS.extra = `Place: ${picks.scene}. ${guest}${when}${picks.note ? "Also: " + picks.note : ""}`.trim();
    for (const k of ["music", "ambience", "look_preset"]) delete CS.ep[k];
    $("#ep-music").value = "";
    $("#ep-amb").value = "";
    $("#ep-look").value = "";
    status("2/5 Writing the script…");
    // the script is written for the picked place (the set is made after it) - not for whatever set was selected
    const r = await api("POST", "/api/ai/script", { title: CS.ep.title, set: "new:" + picks.scene, scene_policy: "reuse", character: $("#ep-char").value,
      model: CS.model, lines: CS.lines, tone: CS.tone, extra: CS.extra, co_stars: CS.ep.co_stars || [], template: CS.ep.template });
    $("#script").value = r.script; CS.scriptDraft = r.script;
    // the scene comes from the title and the script, not the other way round
    status("3/5 Making a scene that fits the script (a few minutes)…");
    const idea = `${picks.scene}. ${CS.ep.title}. ${(r.lines || []).slice(0, 2).join(" ")}`.slice(0, 300);
    const firstLight = picks.time.split(/\W+/).map((w) => MW_LIGHT[w]).find(Boolean);       // the first light word
    const done = await waitJob(await api("POST", "/api/sets/generate", { idea, where: "", light: firstLight || "" }), $("#make-job"));
    await refreshMeta();
    CS.ep.set = done.result.set;
    CS.ep.start = "front";
    status("4/5 Directing the shots…");
    await directNow(false);
    status("5/5 Rendering the video (a few minutes)…");
    const id = await save();
    CS.rendered = JSON.stringify(CS.ep);
    const job = await api("POST", "/api/render", { id, fresh_voice: $("#fresh").checked, reuse_frames: false });
    const fin = await new Promise((res, rej) => watchJob(job, $("#job"), (j) => (j.status === "done" ? res(j) : rej(new Error("render failed - see the log")))));
    showResult(fin.result.video + "?t=" + Date.now(), fin.result.sheet + "?t=" + Date.now());
    status("Done - the video is ready below.");
    }); } finally { panel.classList.remove("making"); }
  });
}

/* ---- "Make a series": one idea -> 1-4 episodes, made and queued to render by a server job (pipeline/series.py),
   so it carries on with the phone locked. */
async function openSeriesDialog() {
  const tpls = META.catalog.templates || [];
  const v = await openModal({
    title: "📺 Make a series", wide: true,
    body: `<p class="muted small" style="margin-top:0">One idea, a few episodes: each gets its own question as the title, a script that knows the other episodes, its own scene and shots, and is rendered one after another. They appear on the Videos page as they finish.</p>
      <label>The idea<input type="text" id="se-idea" placeholder="e.g. how the human body works, life in the deep sea, what if cats ruled the world"></label>
      <div class="row" style="margin-top:8px">
        <label>Episodes<select id="se-n">${[1, 2, 3, 4].map((n) => `<option ${n === 3 ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label style="flex:2">Kind of video<select id="se-tpl">${tpls.map((t) => `<option value="${t.id}">${t.icon} ${esc(t.name)}</option>`).join("")}</select></label>
        <label>Length<select id="se-len"><option value="short">Short (~20 s)</option><option value="medium" selected>Medium (~40 s)</option><option value="long">Long (~1 min)</option></select></label></div>
      <p class="muted small" id="se-about"></p>
      <label>Anything else? (optional)<input type="text" id="se-note" placeholder="e.g. she's scared of spiders; keep it cosy"></label>`,
    onOpen: (m) => {
      const about = () => { const t = tpls.find((x) => x.id === $("#se-tpl", m).value); $("#se-about", m).textContent = t ? t.about : ""; };
      $("#se-tpl", m).onchange = about; about();
      $("#se-idea", m).focus();
    },
    buttons: [{ label: "Cancel", left: true, value: null },
      { label: "📺 Make the series", primary: true, onClick: (m) => {
        const idea = $("#se-idea", m).value.trim();
        if (!idea) { toast("Give the series an idea", true); return false; }
        return { idea, count: Number($("#se-n", m).value), template: $("#se-tpl", m).value, length: $("#se-len", m).value,
          note: $("#se-note", m).value.trim() };
      } }],
  });
  if (!v) return;
  const job = await api("POST", "/api/series", { ...v, character: $("#ep-char")?.value || "", model: CS.model });
  toast(`Series started: ${v.count} episode${v.count > 1 ? "s" : ""} - follow it in the queue (top right)`);
  watchJob(job, $("#make-job"), (j) => toast(j.status === "done" ? "Series planned - the episodes are rendering one by one" : "The series failed - see the log", j.status !== "done"));
}

/* ---- "Make a whole video" wizard: a little magic show between steps, three random cards per step (re-roll for three
   more), then an optional note. The picks steer the title, the scene, the script and the light. */
const MW_STEPS_BASE = [
  { key: "scene", q: "Where does it happen?", icon: "📍", cards: [
    "a cozy cafe", "a haunted library", "a candy factory", "a busy train station", "a tropical beach", "a snowy mountain cabin",
    "a space station", "a giant kitchen", "a neon arcade", "a misty forest", "an underwater city", "a rooftop at night",
    "a school classroom", "a farm with a red barn", "a desert canyon", "a cloud kingdom in the sky", "a toy shop",
    "a museum after closing", "a bakery at dawn", "a pirate ship", "a bubble bath", "a laundromat", "a volcano island",
    "a supermarket", "a park in autumn", "a hospital waiting room", "a castle courtyard", "a tiny dollhouse",
    "a camping site by a lake", "a city street in the rain", "a greenhouse full of plants", "a bowling alley",
    "an old lighthouse", "a submarine", "the moon", "a music studio", "a bedroom at 3 am", "a zoo"] },
  { key: "topic", q: "What's it about?", icon: "💡", cards: [
    "gravity", "dreams", "black holes", "why cats purr", "the deepest ocean", "time travel", "volcanoes", "the human brain",
    "lightning", "dinosaurs", "how plants eat", "the speed of light", "money", "sleep", "ants", "chocolate",
    "the moon landing", "rainbows", "earthquakes", "memory", "yawning", "the internet", "bees", "ice ages", "magnets",
    "hiccups", "the pyramids", "octopuses", "snowflakes", "the sun", "hair", "sneezing", "coffee", "sharks", "clouds",
    "robots", "taste buds", "fireflies", "the north pole", "music"] },
  { key: "tone", q: "What's the vibe?", icon: "🎭", cards: [
    "funny", "wholesome", "chaotic", "dramatic", "spooky", "cute", "deadpan", "excited", "mysterious", "silly",
    "heartfelt", "sarcastic", "nervous", "proud", "motivational", "grumpy"] },
  { key: "guest", q: "Who drops in?", icon: "🚪", cards: [
    "nobody - just her", "a mischievous dog", "her mom", "a lost robot", "a tiny dragon", "a grumpy pigeon", "a talking cactus",
    "a confused tourist", "a ghost", "a delivery driver", "a giant snail", "a pirate", "a scientist", "a sleepy bear",
    "an alien", "a chef", "a cow", "a mail truck", "a rubber duck", "a wizard"] },
  { key: "time", q: "When?", icon: "🌗", cards: [
    "a sunny day", "a golden sunset", "a starry night", "day turning into night", "a rainy evening", "a snowy morning",
    "a foggy dawn", "a stormy night", "night turning into dawn"] },
  { key: "length", q: "How long?", icon: "⏱", cards: ["short (about 20 s)", "medium (about 40 s)", "long (about a minute)"] },
];
const MW_LIGHT = { day: "day", sunny: "day", morning: "day", sunset: "sunset", golden: "sunset", evening: "sunset",
  night: "night", starry: "night", stormy: "night", dawn: "sunset", foggy: "sunset", rainy: "sunset", snowy: "day" };

function mwPick(list, n, not = []) {
  const pool = list.filter((x) => !not.includes(x));
  const out = [];
  while (out.length < n && pool.length) out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
  return out;
}

function mwMagic(box, text) {        // the little show between steps (~0.9 s)
  return new Promise((res) => {
    box.innerHTML = `<div class="mw-magic"><div class="mw-orbit">${Array.from("✨⭐💫🌟✨").map((c, i) =>
      `<span style="--i:${i}">${c}</span>`).join("")}</div><div class="mw-wand">🪄</div><p>${esc(text)}</p></div>`;
    setTimeout(res, matchMedia("(prefers-reduced-motion: reduce)").matches ? 150 : 950);
  });
}

async function openMakeWizard() {
  const picks = {};
  // the kind of video comes first (templates: pacing and content - the look is the same for all)
  const MW_STEPS = [{ key: "kind", q: "What kind of video?", icon: "🎬",
    cards: (META.catalog.templates || []).map((t) => `${t.icon} ${t.name}`) }, ...MW_STEPS_BASE];
  return openModal({
    title: "🎲 Make a whole video", wide: true,
    body: `<div id="mw-box" class="mw-box"></div>`,
    buttons: [{ label: "Cancel", left: true, value: null }],
    onOpen: async (m, close) => {
      const box = $("#mw-box", m);
      const showStep = async (i) => {
        if (i >= MW_STEPS.length) return lastStep();
        const st = MW_STEPS[i];
        await mwMagic(box, i === 0 ? "Shuffling the ideas…" : ["Mixing the magic…", "Rolling the dice…", "Sprinkling stardust…", "Asking the stars…"][i % 4]);
        let shown = mwPick(st.cards, 3);
        const draw = () => {
          box.innerHTML = `<div class="mw-step">
            <div class="mw-dots">${MW_STEPS.map((_, k) => `<i class="${k < i ? "done" : k === i ? "on" : ""}"></i>`).join("")}<i class="${i >= MW_STEPS.length ? "on" : ""}"></i></div>
            <h3>${st.icon} ${esc(st.q)}</h3>
            <div class="mw-cards">${shown.map((c, k) => `<button class="mw-card" data-mw="${k}" style="--d:${k}">${esc(c)}</button>`).join("")}</div>
            <div class="btns" style="justify-content:center"><button id="mw-roll">🎲 Three more</button>
              ${i > 0 ? '<button id="mw-back">← Back</button>' : ""}</div></div>`;
          $$("[data-mw]", box).forEach((b) => b.onclick = () => { picks[st.key] = shown[Number(b.dataset.mw)]; showStep(i + 1); });
          $("#mw-roll", box).onclick = () => { shown = mwPick(st.cards, 3, shown); draw(); };
          if (i > 0) $("#mw-back", box).onclick = () => showStep(i - 1);
        };
        draw();
      };
      const lastStep = async () => {
        await mwMagic(box, "Almost there…");
        box.innerHTML = `<div class="mw-step">
          <div class="mw-dots">${MW_STEPS.map(() => '<i class="done"></i>').join("")}<i class="on"></i></div>
          <h3>✍️ Anything else? <span class="muted small">(optional)</span></h3>
          <p class="mw-sum">${MW_STEPS.map((s) => `<span>${s.icon} ${esc(picks[s.key] || "")}</span>`).join("")}</p>
          <textarea id="mw-note" rows="3" placeholder="e.g. she's scared of the dark; end with a twist - or leave it empty"></textarea>
          <div class="btns" style="justify-content:center"><button id="mw-back">← Back</button>
            <button class="primary" id="mw-go">✨ Make my video</button></div></div>`;
        $("#mw-note", box).focus();
        $("#mw-back", box).onclick = () => showStep(MW_STEPS.length - 1);
        $("#mw-go", box).onclick = () => close({ ...picks, note: $("#mw-note", box).value.trim() });
      };
      showStep(0);
    },
  });
}

// a little burst of stars where a button was pressed
const SPARKS = ["✨", "⭐", "💫", "🌟"];
function sparkle(el, ev) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const r = el.getBoundingClientRect();
  const x = ev?.clientX || r.left + r.width / 2, y = ev?.clientY || r.top + r.height / 2;
  for (let i = 0; i < 9; i++) {
    const s = document.createElement("span"), a = Math.random() * Math.PI * 2, d = 30 + Math.random() * 45;
    s.className = "spark"; s.textContent = SPARKS[i % SPARKS.length];
    s.style.left = x + "px"; s.style.top = y + "px";
    s.style.setProperty("--dx", Math.cos(a) * d + "px"); s.style.setProperty("--dy", Math.sin(a) * d + "px");
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 750);
  }
}

/* ---- "Custom video": the whole Create page as a step-by-step popup, in the same card style as the random one.
   Order: idea → look & language → music & ambience → captions → script → scenes → shots → summary & render.
   The script comes before the scenes on purpose: it says where the story goes ([@ place]), the Scenes step
   reuses or makes those sets, and the shots are directed last, in the real sets (walks to their own places).
   The picks live in CS.wiz, so closing the popup and opening it again carries on where you were. */
const CW_STEPS = [
  { icon: "💡", name: "Idea" }, { icon: "🎨", name: "Look" }, { icon: "🎵", name: "Sound" }, { icon: "💬", name: "Captions" },
  { icon: "✍️", name: "Script" }, { icon: "🗺", name: "Scenes" }, { icon: "🎬", name: "Shots" }, { icon: "🚀", name: "Render" },
];
const CW_LEN = { short: ["⚡ Short", "about 20 seconds", 4, 5], medium: ["🎬 Medium", "about 40 seconds", 6, 8],
  long: ["🍿 Long", "about a minute", 10, 13] };
const CW_PLACES = { stay: ["📍 One place", "the whole video happens in one spot"],
  move: ["🗺 A little journey", "the story travels to 1-3 new places"], auto: ["🤖 Let the AI decide", "it moves only if the story needs it"] };
const CW_MOVE = new Set(["walk_to", "run_to", "sneak_to"]);

// what the shots were directed from - unchanged = the shots (and your edits to them) are kept
const cwKey = (W) => JSON.stringify([W.directScript, W.set, W.beats, W.template, W.castAI, W.co_stars, W.character]);
// an existing video opened from the Videos page: every step filled in, starting on the last one; it keeps its file
function cwFromEpisode(ep, id) {
  const caps = ep.captions || {};
  const W = { step: 7, max: 7, editId: id, template: ep.template || "what_if", title: ep.title || "", topic: "", ideas: [],
    character: typeof ep.character === "string" ? ep.character : "", co_stars: (ep.co_stars || []).map((c) => (typeof c === "string" ? c : c.id)),
    look: ep.look_preset || "", language: ep.language || "",
    music: ep.music === undefined ? "__default" : (ep.music || "__none"),
    ambience: ep.ambience === undefined ? "__default" : (ep.ambience || "__none"),
    cap: Number(caps.group) === 1 ? ((caps.cycle || []).length ? "one-colour" : "one-white") : "two-colour",
    beats: ep.shots.some((s) => s.beat_group != null), length: "medium", tone: "", places: "auto", note: "",
    script: ep.script || ep.shots.map((s) => s.line || "").join("\n"), start: ep.set, castAI: true, fresh: false,
    set: ep.set, shots: ep.shots, cast: ep.cast || {}, translations: ep.translations, scenes: null };
  W.directScript = W.script;
  W.shotsFor = cwKey(W);
  return W;
}

function cwCards(list, cur, attr, cls = "") {   // list: [{v, label, sub, html}] -> tappable cards, the current one lit
  return `<div class="mw-cards cw-cards ${cls}">${list.map((c, k) => `<button class="mw-card cw-card ${String(c.v) === String(cur) ? "on" : ""}"
    data-${attr}="${esc(c.v)}" style="--d:${k}">${c.html || ""}<b>${esc(c.label)}</b>${c.sub ? `<small>${esc(c.sub)}</small>` : ""}</button>`).join("")}</div>`;
}

async function openCustomWizard() {
  const cat = META.catalog, tpls = cat.templates || [];
  const [music, sets] = await Promise.all([api("GET", "/api/music").catch(() => []), api("GET", "/api/sets").catch(() => setsCache)]);
  setsCache = sets;
  const setInfo = (id) => sets.find((s) => s.id === id) || { id, name: cat.sets[id]?.name || id };
  const fresh = () => ({ step: 0, max: 0, template: "what_if", title: "", topic: "", ideas: [], character: "", co_stars: [],
    look: "", language: "", music: "__default", ambience: "__default", cap: capStyleOf(), beats: true, length: "medium",
    tone: "", places: "auto", note: "", script: "", start: "auto", castAI: true, fresh: false });
  if (!CS.wiz) CS.wiz = fresh();
  const W = CS.wiz;
  const tpl = () => tpls.find((t) => t.id === W.template) || tpls[0] || { tone: "funny", lines: [6, 8] };

  return openModal({
    title: "🪄 Make your own video", wide: true,
    body: `<div id="cw-box" class="mw-box cw-box"></div>`,
    buttons: [{ label: "Close (your picks are kept)", left: true, value: null }],
    onOpen: (m, close) => {
      const box = $("#cw-box", m);
      const frame = (q, inner, next = "Next →") => `<div class="mw-step cw-step">
        <div class="cw-trail">${CW_STEPS.map((s, k) => `<button class="cw-crumb ${k < W.step ? "done" : k === W.step ? "on" : ""}" data-goto="${k}"
          ${k > W.max ? "disabled" : ""} title="${esc(s.name)}"><span>${k < W.step ? "🐾" : s.icon}</span><em>${esc(s.name)}</em></button>`).join("")}</div>
        <h3><span class="cw-hi">${CW_STEPS[W.step].icon}</span> ${q}</h3>${inner}
        <div class="btns cw-nav">${W.step > 0 ? '<button id="cw-back">← Back</button>' : ""}
          ${next ? `<button class="primary" id="cw-next">${next}</button>` : ""}</div></div>`;
      const go = async (k) => { W.step = k; W.max = Math.max(W.max, k); m.querySelector(".modal-body").scrollTop = 0; await STEPS[k](); };
      const wire = (onNext) => {
        $$("[data-goto]", box).forEach((b) => b.onclick = () => go(Number(b.dataset.goto)));
        if ($("#cw-back", box)) $("#cw-back", box).onclick = () => go(W.step - 1);
        if ($("#cw-next", box)) $("#cw-next", box).onclick = guard(async (ev) => {
          const btn = ev.currentTarget;          // gone from the event after the first await
          if (onNext && (await onNext()) === false) return;
          sparkle(btn, ev);
          await go(W.step + 1);
        });
        $$(".cw-card, .chip-btn", box).forEach((b) => b.addEventListener("click", (ev) => sparkle(b, ev)));
      };
      const pick = (attr, fn) => $$(`[data-${attr}]`, box).forEach((b) => b.onclick = () => {
        $$(`[data-${attr}]`, box).forEach((x) => x.classList.toggle("on", x === b));
        fn(b.dataset[attr.replace(/-(\w)/g, (_, c) => c.toUpperCase())], b);
      });

      const STEPS = [
        // 1 - the idea: kind of video, title (or ideas), who's in it
        async () => {
          const others = META.characters.filter((c) => c !== (W.character || META.settings.active_character));
          box.innerHTML = frame("What's your video about?", `
            <p class="cw-label">Kind of video</p>
            ${cwCards(tpls.map((t) => ({ v: t.id, label: `${t.icon} ${t.name}`, sub: t.about })), W.template, "tpl", "four")}
            <p class="cw-label">Title <span class="muted small">- the question at the top of the video</span></p>
            <input type="text" id="cw-title" class="cw-big" placeholder="What if a catgirl ran a bakery?" value="${esc(W.title)}">
            <div class="cw-row"><input type="text" id="cw-topic" placeholder="Stuck? A topic for ideas (optional): space, cooking…" value="${esc(W.topic)}">
              <button id="cw-ideas">✨ Give me ideas</button></div>
            <div class="chips cw-ideas" id="cw-chips">${W.ideas.map((t, k) => `<button class="chip-btn" data-idea="${k}" style="--d:${k}">${esc(t)}</button>`).join("")}</div>
            ${META.characters.length > 1 ? `<p class="cw-label">Starring</p><div class="chips">${META.characters.map((c) =>
              `<button class="chip-btn ${c === (W.character || META.settings.active_character) ? "on" : ""}" data-star="${esc(c)}">${esc(titleCase(c))}</button>`).join("")}</div>
              ${others.length ? `<p class="cw-label">Also in it <span class="muted small">- they talk too</span></p><div class="chips">${others.map((c) =>
              `<button class="chip-btn ${W.co_stars.includes(c) ? "on" : ""}" data-co="${esc(c)}">${esc(titleCase(c))}</button>`).join("")}</div>` : ""}` : ""}
            ${W.max > 0 || W.title ? '<p style="text-align:right;margin:10px 0 0"><button id="cw-reset" class="ghost small-btn">↺ Start over</button></p>' : ""}`);
          if ($("#cw-reset", box)) $("#cw-reset", box).onclick = guard(async () => {
            if (!(await uiConfirm("Clear every pick and start a new video?", { title: "Start over", ok: "↺ Start over" }))) return;
            Object.assign(W, fresh()); W.scenes = W.shots = null; STEPS[0]();
          });
          wire(() => {
            W.title = $("#cw-title", box).value.trim();
            if (!W.title) { toast("Give your video a title - or press ✨ Give me ideas", true); $("#cw-title", box).focus(); return false; }
          });
          $("#cw-title", box).oninput = (e) => { W.title = e.target.value; };
          $("#cw-topic", box).oninput = (e) => { W.topic = e.target.value; };
          pick("tpl", (v) => { W.template = v; W.tone = ""; });
          const bindIdeas = () => $$("[data-idea]", box).forEach((b) => b.onclick = (ev) => {
            W.title = W.ideas[Number(b.dataset.idea)]; $("#cw-title", box).value = W.title; sparkle(b, ev);
          });
          bindIdeas();
          $("#cw-ideas", box).onclick = guard(async (e) => busy(e.currentTarget, "✨ Thinking…", async () => {
            const r = await api("POST", "/api/ai/titles", { theme: W.topic, character: W.character, model: CS.model, template: W.template });
            W.ideas = r.titles || [];
            $("#cw-chips", box).innerHTML = W.ideas.map((t, k) => `<button class="chip-btn cw-deal" data-idea="${k}" style="--d:${k}">${esc(t)}</button>`).join("");
            bindIdeas();
          }));
          $$("[data-star]", box).forEach((b) => b.onclick = () => {
            W.character = b.dataset.star === META.settings.active_character ? "" : b.dataset.star;
            W.co_stars = W.co_stars.filter((c) => c !== b.dataset.star);
            STEPS[0]();
          });
          $$("[data-co]", box).forEach((b) => b.onclick = () => {
            const c = b.dataset.co;
            W.co_stars = W.co_stars.includes(c) ? W.co_stars.filter((x) => x !== c) : [...W.co_stars, c];
            b.classList.toggle("on", W.co_stars.includes(c));
          });
          if (!W.title) $("#cw-title", box).focus();
        },
        // 2 - look (the filter on top) and the language it's spoken in
        async () => {
          const langs = cat.languages || {};
          box.innerHTML = frame("How should it look?", `
            <p class="cw-label">Look <span class="muted small">- the retro filter over the whole video</span></p>
            ${cwCards([{ v: "", label: "⭐ My usual look", sub: META.settings.look_preset || "from Settings" },
              ...Object.keys(META.presets).map((p) => ({ v: p, label: "🎞 " + p }))], W.look, "look", "four")}
            <p class="cw-label">Language <span class="muted small">- write in English, the video is voiced and captioned in this</span></p>
            ${cwCards([{ v: "", label: "🌐 My usual", sub: langName(META.settings.language) },
              ...Object.entries(langs).map(([k, v]) => ({ v: k, label: v }))], W.language, "lang", "four")}`);
          wire();
          pick("look", (v) => { W.look = v; });
          pick("lang", (v) => { W.language = v; });
        },
        // 3 - music and the background sound of the place
        async () => {
          const amb = Object.keys(META.sfx).filter((k) => META.sfx[k].kind === "ambience");
          const dm = META.settings.audio.default_music;
          box.innerHTML = frame("What does it sound like?", `
            <p class="cw-label">Music <span class="muted small">- quiet, under her voice</span></p>
            ${cwCards([{ v: "__default", label: "⭐ My usual", sub: dm ? dm.split("/").pop() : "no music" }, { v: "__none", label: "🔇 No music" },
              ...music.map((t) => ({ v: t.path, label: "🎵 " + t.name.replace(/\.\w+$/, "").replace(/[-_]+/g, " "),
                html: `<span class="cw-play" data-play="${esc(t.url)}" title="Listen">▶</span>` }))], W.music, "music", "four")}
            <p class="cw-label">Ambience <span class="muted small">- the sound of the place (birds, rain, a busy cafe…)</span></p>
            ${cwCards([{ v: "__default", label: "⭐ My usual", sub: META.settings.sfx.ambience || "off" }, { v: "auto", label: "🗺 Match each scene" },
              { v: "__none", label: "🔇 None" }, ...amb.map((k) => ({ v: k, label: "🌿 " + META.sfx[k].label.replace("Ambience: ", "") }))], W.ambience, "amb", "four")}
            <audio id="cw-audio" hidden></audio>`);
          wire(() => { $("#cw-audio", box).pause(); });
          pick("music", (v) => { W.music = v; });
          pick("amb", (v) => { W.ambience = v; });
          $$("[data-play]", box).forEach((p) => p.onclick = (ev) => {
            ev.stopPropagation();
            const a = $("#cw-audio", box);
            if (!a.paused && a.dataset.src === p.dataset.play) { a.pause(); p.textContent = "▶"; return; }
            $$("[data-play]", box).forEach((x) => { x.textContent = "▶"; });
            a.src = p.dataset.play; a.dataset.src = p.dataset.play; a.play().catch(() => {}); p.textContent = "⏸";
          });
        },
        // 4 - captions, shown as they'll look
        async () => {
          const demo = (k) => { const s = CAP_STYLES[k].caps, words = ["WHAT", "IF", "CATS"];
            return `<span class="cw-capdemo">${words.slice(0, s.group === 1 ? 1 : 2).map((w, i) =>
              `<span style="color:${(s.cycle || [])[i] || "#fff"};${s.outline ? "text-shadow:0 0 2px #000,0 0 2px #000,0 0 3px #000" : ""}">${w}</span>`).join(" ")}</span>`; };
          box.innerHTML = frame("How do the words appear?", `
            <p class="cw-label">Caption style</p>
            ${cwCards(Object.entries(CAP_STYLES).map(([k, v]) => ({ v: k, label: v.label, html: demo(k) })), W.cap, "cap")}
            <p class="cw-label">Pace</p>
            ${cwCards([{ v: "1", label: "⚡ Quick cuts", sub: "a new camera angle every few words (like most Reels)" },
              { v: "0", label: "🎥 One shot per line", sub: "calmer, longer shots" }], W.beats ? "1" : "0", "beats")}`);
          wire();
          pick("cap", (v) => { W.cap = v; });
          pick("beats", (v) => { W.beats = v === "1"; });
        },
        // 5 - the script: written by the AI (and editable) or typed by you; it also says where the story goes
        async () => {
          const t = tpl(), tone = W.tone || t.tone || "funny";
          box.innerHTML = frame("Let's write the script", `
            <div class="cw-two">
              <div><p class="cw-label">Length</p>${cwCards(Object.entries(CW_LEN).map(([k, v]) => ({ v: k, label: v[0], sub: v[1] })), W.length, "len", "three")}</div>
              <div><p class="cw-label">Places</p>${cwCards(Object.entries(CW_PLACES).map(([k, v]) => ({ v: k, label: v[0], sub: v[1] })), W.places, "places", "three")}</div></div>
            <p class="cw-label">Vibe</p>
            <div class="chips">${[tone, ...TONES.filter((x) => x !== tone)].slice(0, 12).map((x) => `<button class="chip-btn ${x === tone ? "on" : ""}" data-tone="${esc(x)}">${esc(x)}</button>`).join("")}</div>
            <p class="cw-label">Anything the AI should know? <span class="muted small">(optional)</span></p>
            <input type="text" id="cw-note" placeholder="e.g. she's afraid of cucumbers; end with a twist" value="${esc(W.note)}">
            <div class="btns" style="justify-content:center;margin:12px 0 4px"><button id="cw-write" class="cw-magic-btn">✨ Write my script</button></div>
            <div id="cw-script-wrap" ${W.script ? "" : "hidden"}>
              <p class="cw-label">Your script <span class="muted small">- one line per moment. Change anything you like.
                <code>[brackets]</code> are directions, <code>[@ a place]</code> moves the story somewhere new.</span></p>
              <textarea id="cw-script" rows="9">${esc(W.script)}</textarea>
              <details class="cw-more"><summary>📖 Words you can use in [brackets]</summary><div class="help-box">
                <b>Camera:</b> ${Object.keys(cat.cameras).map((c) => `<code>${c}</code>`).join(" ")}<br>
                <b>Move:</b> ${Object.keys(cat.moves).map((c) => `<code>${c}</code>`).join(" ")}<br>
                <b>Action:</b> ${Object.keys(cat.anims).map((c) => `<code>${c}</code>`).join(" ")} - or any verb as <code>do:salute</code><br>
                <b>Expression:</b> ${cat.expressions.map((c) => `<code>${c}</code>`).join(" ")}<br>
                <b>Light</b> (from this line on): ${Object.keys(cat.lights || {}).map((c) => `<code>${c}</code>`).join(" ")}<br>
                <b>Who says it:</b> start the line with a name - <code>Mom: Lunch!</code> for someone brought in with <code>+mom</code>.<br>
                <b>New place:</b> <code>[@ on the moon]</code> - lasts until the next <code>@</code>. You choose the set for it in the next step.<br>
                <b>Cutaway</b> (show something while she talks): <code>[cutaway: a plane flying past]</code><br>
                <b>Show a model of something:</b> <code>[show: volcano]</code> <code>[show: volcano open]</code> <code>[show: off]</code><br>
                <b>Effects:</b> ${Object.keys(cat.particles || {}).map((c) => `<code>${c}</code>`).join(" ")}<br>
                <b>Others in the scene:</b> <code>[+mom enter]</code> <code>[+car crash_in from_left]</code> - verbs:
                  ${Object.keys(cat.cast_verbs || {}).map((c) => `<code>${c}</code>`).join(" ")}</div></details></div>
            <p class="muted small" id="cw-own" ${W.script ? "hidden" : ""}><a href="#" id="cw-self">…or write it yourself</a></p>`, "Next: the scenes →");
          const showBox = () => { $("#cw-script-wrap", box).hidden = false; $("#cw-own", box).hidden = true; };
          wire(() => {
            W.script = $("#cw-script", box).value.trim();
            if (!W.script) { toast("Write the script first - ✨ Write my script does it for you", true); return false; }
          });
          pick("len", (v) => { W.length = v; });
          pick("places", (v) => { W.places = v; });
          pick("tone", (v) => { W.tone = v; });
          $("#cw-note", box).oninput = (e) => { W.note = e.target.value; };
          $("#cw-script", box).oninput = (e) => { W.script = e.target.value; };
          $("#cw-self", box).onclick = (e) => { e.preventDefault(); showBox(); $("#cw-script", box).focus(); };
          $("#cw-write", box).onclick = guard(async (e) => {
            const btn = e.currentTarget;
            if (W.script.trim() && !(await uiConfirm("Write a new script? The one in the box is replaced.", { title: "New script", ok: "✨ Write a new one" }))) return;
            sparkle(btn, e);
            await busy(btn,"🪄 Writing… (about half a minute)", async () => {
              const [lo, hi] = CW_LEN[W.length].slice(2);
              const r = await api("POST", "/api/ai/script", { title: W.title, set: "auto", scene_policy: "reuse", character: W.character,
                model: CS.model, lines: lo + Math.floor(Math.random() * (hi - lo + 1)), tone: W.tone || tpl().tone, extra: W.note,
                co_stars: W.co_stars, template: W.template, scenes: W.places });
              W.script = r.script; W.start = r.set || "auto";
              $("#cw-script", box).value = W.script; showBox();
              $("#cw-script", box).classList.add("cw-deal");
            });
          });
        },
        // 6 - scenes: every place the script needs, matched to your sets or made new
        async () => {
          if (!W.scenes || W.scenesFor !== W.script) {
            await mwMagic(box, "Finding the places in your script…");
            const r = await api("POST", "/api/scenes/plan", { script: W.script, set: W.start || "auto", title: W.title });
            W.scenes = r.scenes.map((s) => ({ ...s, choice: s.pick, idea: s.place }));
            W.scenesFor = W.script;
          }
          W.making = W.making || {};
          const card = (sc, i, id) => {
            const s = setInfo(id);
            return `<button class="mw-card cw-card cw-set ${sc.choice === id ? "on" : ""}" data-scene="${i}" data-set="${esc(id)}">
              ${s.preview ? `<img src="${esc(s.preview)}" alt="" loading="lazy">` : '<span class="cw-noimg">🏞</span>'}<b>${esc(s.name)}</b></button>`;
          };
          box.innerHTML = frame(W.scenes.length > 1 ? `Your story has ${W.scenes.length} places` : "Where does it happen?", `
            <p class="muted small" style="margin-top:-6px">Pick one of your sets for each place, or make a brand-new one.</p>
            ${W.scenes.map((sc, i) => {
              const isNew = String(sc.choice).startsWith("new:"), line = (W.script.split("\n")[sc.line] || "").replace(/\[[^\]]*\]\s*/g, "");
              return `<div class="cw-scene" style="--d:${i}">
                <div class="cw-scene-h"><b>${i === 0 ? "🎬 It starts in" : `➡ Then, scene ${i + 1}`}</b> <span>“${esc(sc.place)}”</span>
                  ${i > 0 && line ? `<em class="muted small">at “${esc(line.slice(0, 60))}${line.length > 60 ? "…" : ""}”</em>` : ""}</div>
                <div class="cw-sets">${sc.options.map((id) => card(sc, i, id)).join("")}
                  <button class="mw-card cw-card cw-set cw-newset ${isNew ? "on" : ""}" data-scene="${i}" data-set="new"><span class="cw-noimg">✨</span><b>Make a new one</b></button></div>
                <div class="cw-row"><select data-other="${i}"><option value="">📚 …or pick any of my sets</option>${options(sets.map((s) => s.id), "", Object.fromEntries(sets.map((s) => [s.id, s.name])))}</select></div>
                ${isNew ? `<div class="cw-new"><label>Describe the new place<input type="text" data-idea-of="${i}" value="${esc(sc.idea)}"></label>
                  <div class="cw-row"><button data-make="${i}" ${W.making[i] ? "disabled" : ""}>${W.making[i] ? "🪄 Making it…" : "🪄 Make it now (a few minutes)"}</button>
                    <span class="muted small">or leave it - it's made when the video renders</span></div>
                  <div class="inline-job" id="cw-job${i}"></div></div>` : ""}</div>`;
            }).join("")}`, "Next: direct the shots →");
          wire(() => {
            if (Object.values(W.making).some(Boolean)) { toast("A new set is still being made - wait for it to finish (or pick another set)", true); return false; }
            // the script now names the exact sets: "[@ on the moon]" -> "[@ moon_base_1234]" / "[@ new:on the moon]"
            const lines = W.script.split("\n");
            for (const sc of W.scenes.slice(1)) {
              lines[sc.line] = lines[sc.line].replace(/^(\s*\[[^\]]*?)@\s*[^,\]]+/, (_, h) => `${h}@ ${sc.choice}`);
            }
            W.directScript = lines.join("\n");
            W.set = W.scenes[0].choice;
          });
          $$("[data-set]", box).forEach((b) => b.onclick = () => {
            const sc = W.scenes[Number(b.dataset.scene)];
            sc.choice = b.dataset.set === "new" ? "new:" + (sc.idea || sc.place) : b.dataset.set;
            STEPS[5]();
          });
          $$("[data-other]", box).forEach((s) => s.onchange = () => {
            if (!s.value) return;
            const sc = W.scenes[Number(s.dataset.other)];
            if (!sc.options.includes(s.value)) sc.options = [s.value, ...sc.options].slice(0, 3);
            sc.choice = s.value; STEPS[5]();
          });
          $$("[data-idea-of]", box).forEach((inp) => inp.oninput = () => {
            const sc = W.scenes[Number(inp.dataset.ideaOf)];
            sc.idea = inp.value; sc.choice = "new:" + (inp.value.trim() || sc.place);
          });
          $$("[data-make]", box).forEach((b) => b.onclick = guard(async () => {
            const i = Number(b.dataset.make), sc = W.scenes[i];
            W.making[i] = true; b.disabled = true; b.textContent = "🪄 Making it…";
            const job = await api("POST", "/api/sets/generate", { idea: `${sc.idea || sc.place}. ${W.title}`.slice(0, 300), where: "", light: "" });
            watchJob(job, $(`#cw-job${i}`, box), guard(async (j) => {
              W.making[i] = false;
              if (j.status !== "done" || !j.result?.set) { toast("The set couldn't be made - see the log", true); if (W.step === 5) STEPS[5](); return; }
              await refreshMeta();
              const fresh = await api("GET", "/api/sets");
              sets.splice(0, sets.length, ...fresh); setsCache = sets;
              sc.options = [j.result.set, ...sc.options.filter((x) => x !== j.result.set)].slice(0, 3);
              sc.choice = j.result.set;
              toast(`✨ New set ready: ${setInfo(j.result.set).name}`);
              if (W.step === 5) STEPS[5]();
            }));
          }));
        },
        // 7 - the shots, directed in the chosen sets; camera and action can be changed per shot
        async () => {
          const key = cwKey(W);
          if (!W.shots || W.shotsFor !== key) {
            await mwMagic(box, "Directing your shots…");
            const r = await api("POST", "/api/autodirect", { script: W.directScript, set: W.set, cast: {}, co_stars: W.co_stars,
              beat_words: W.beats ? 4 : 0, cast_ai: W.castAI, character: W.character, scene_ai: false, title: W.title, template: W.template });
            W.shots = r.shots; W.start = r.start; W.cast = r.cast || {}; W.shotsFor = key;
            if (r.set) W.set = r.set;
          }
          // a guess before the voice exists: ~2.6 words a second plus a little air per shot
          const secs = Math.round(W.shots.reduce((a, s) => a + (s.duration || String(s.line || "").split(/\s+/).filter(Boolean).length / 2.6 + 0.5), 0));
          const cast = Object.keys(W.cast || {});
          let lastSet = null;
          box.innerHTML = frame(`${W.shots.length} shots, ready to roll`, `
            <p class="muted small" style="margin-top:-6px">About ${secs} s · ${new Set(W.shots.map((s) => s.set || W.set)).size} scene(s)
              ${cast.length ? ` · 🎭 also in it: ${cast.map((c) => esc(titleCase(c))).join(", ")}` : ""} - change any camera or action, or just carry on.</p>
            <div class="cw-shots">${W.shots.map((s, k) => {
              const sid = s.set || W.set, head = sid !== lastSet ? `<div class="cw-shot-set">🗺 ${esc(String(sid).startsWith("new:") ? "✨ " + sid.slice(4) : setInfo(sid).name)}</div>` : "";
              lastSet = sid;
              const anims = Object.keys(cat.anims).filter((a) => !CW_MOVE.has(a) || a === s.action);
              return `${head}<div class="cw-shot" style="--d:${Math.min(k, 12)}"><span class="cw-n">${k + 1}</span>
                <span class="cw-line">${s.cutaway ? `📷 <em>${esc(s.cutaway)}</em> - ` : ""}${esc(s.line || "…")}</span>
                <select data-cam="${k}" title="Camera">${options(Object.keys(cat.cameras), s.camera, Object.fromEntries(Object.keys(cat.cameras).map((c) => [c, "🎥 " + c])))}</select>
                <select data-act="${k}" title="What she does">${options(anims, s.action, Object.fromEntries(anims.map((a) => [a, "🏃 " + a.replace(/_/g, " ")])))}</select></div>`;
            }).join("")}</div>
            <details class="cw-more" id="cw-full"><summary>🔧 Fine-tune every detail - lines, moves, places, sounds, effects, light, who's in it</summary>
              <div id="cw-shots-full"></div><div id="cw-cast-full"></div>
              <div class="btns"><button id="cw-add-shot">+ Add a shot</button></div></details>
            <div class="cw-row" style="justify-content:center">
              <label class="check"><input type="checkbox" id="cw-cast" ${W.castAI ? "checked" : ""}> 🎭 Let the AI bring in people &amp; things the script mentions</label>
              <button id="cw-redirect">🔁 Direct again</button></div>`, "Next: check & render →");
          wire();
          // the full shot editor (the same one the old Create page had), working on the popup's own shots
          const tmp = { title: W.title, set: W.set, start: W.start, shots: W.shots, cast: W.cast, co_stars: W.co_stars,
            ...(W.character ? { character: W.character } : {}) };
          const drawFull = () => {
            const marks = cat.sets[W.set]?.marks || ["center", "front", "left", "right", "back"];
            const sync = () => { W.cast = tmp.cast || {}; drawCast($("#cw-cast-full", box), tmp, () => { W.cast = tmp.cast || {}; }); };
            drawShots($("#cw-shots-full", box), tmp, marks, sync);
            sync();
          };
          $("#cw-full", box).ontoggle = (e) => {
            $(".cw-shots", box).hidden = e.target.open;          // one editor at a time, so they can't disagree
            if (e.target.open) drawFull(); else STEPS[6]();
          };
          $("#cw-add-shot", box).onclick = () => { W.shots.push({ camera: "medium", action: "idle", expression: "neutral", line: "" }); drawFull(); };
          $$("[data-cam]", box).forEach((s) => s.onchange = () => { W.shots[Number(s.dataset.cam)].camera = s.value; });
          $$("[data-act]", box).forEach((s) => s.onchange = () => { const sh = W.shots[Number(s.dataset.act)]; sh.action = s.value; if (!CW_MOVE.has(s.value)) delete sh.to; });
          $("#cw-cast", box).onchange = (e) => { W.castAI = e.target.checked; };
          $("#cw-redirect", box).onclick = guard(async () => { W.shots = null; await STEPS[6](); });
        },
        // 8 - everything at a glance, then go
        async () => {
          const t = tpl(), scenes = W.scenes || [...new Set(W.shots.map((s) => s.set || W.set))].map((choice) => ({ choice }));
          const pill = (k, txt) => `<button class="cw-pill" data-goto="${k}">${txt}</button>`;
          const mus = W.music === "__default" ? "my usual music" : W.music === "__none" ? "no music" : W.music.split("/").pop();
          const amb = W.ambience === "__default" ? "usual ambience" : W.ambience === "__none" ? "no ambience" : W.ambience === "auto" ? "ambience per scene" : W.ambience;
          box.innerHTML = frame("Ready when you are!", `
            <div class="cw-sum-title">“${esc(W.title)}”</div>
            <div class="mw-sum cw-sum">
              ${pill(0, `${t.icon || "🎬"} ${esc(t.name || "")}`)}${pill(0, `⭐ ${esc(titleCase(W.character || META.settings.active_character))}${W.co_stars.length ? " + " + esc(W.co_stars.map(titleCase).join(", ")) : ""}`)}
              ${pill(1, `🎨 ${esc(W.look || "usual look")}`)}${pill(1, `🌐 ${esc(langName(W.language || META.settings.language))}`)}
              ${pill(2, `🎵 ${esc(mus)}`)}${pill(2, `🌿 ${esc(amb)}`)}
              ${pill(3, `💬 ${esc(CAP_STYLES[W.cap]?.label || "")}`)}
              ${pill(4, `✍️ ${W.script.split("\n").filter((l) => l.trim()).length} lines`)}
              ${pill(5, `🗺 ${scenes.map((s) => esc(String(s.choice).startsWith("new:") ? "✨ " + s.choice.slice(4) : setInfo(s.choice).name)).join(" → ")}`)}
              ${pill(6, `🎬 ${W.shots.length} shots`)}</div>
            <p class="muted small" style="text-align:center">Tap anything above to change it. Rendering takes a few minutes${scenes.some((s) => String(s.choice).startsWith("new:")) ? " (plus a few for each new set)" : ""} - follow it at the top right.</p>
            <div class="cw-extras">
              <label class="check"><input type="checkbox" id="cw-fresh" ${W.fresh ? "checked" : ""}> 🎙 Record the voice lines again (new takes)</label>
              ${(W.language || META.settings.language || "en") !== "en" ? `<button id="cw-trans" class="small-btn">🌐 Check the ${esc(langName(W.language || META.settings.language))} translation</button>` : ""}</div>
            <div class="cw-go">
              <button id="cw-render" class="primary cw-render">▶ ${W.editId ? "Render it again!" : "Render my video!"}</button>
              <div class="btns" style="justify-content:center"><button id="cw-save">💾 Save without rendering</button></div></div>`, "");
          wire();
          $("#cw-fresh", box).onchange = (e) => { W.fresh = e.target.checked; };
          const build = () => {
            const ep = { title: W.title, set: W.set, start: W.start, shots: W.shots, script: W.directScript, template: W.template,
              captions: { ...(CS.ep.captions || {}), ...CAP_STYLES[W.cap].caps } };
            if (W.character) ep.character = W.character;
            if (W.co_stars.length) ep.co_stars = W.co_stars;
            if (W.look) ep.look_preset = W.look;
            if (W.language) ep.language = W.language;
            if (W.music !== "__default") ep.music = W.music === "__none" ? "" : W.music;
            if (W.ambience !== "__default") ep.ambience = W.ambience === "__none" ? "" : W.ambience;
            if (W.cast && Object.keys(W.cast).length) ep.cast = W.cast;
            if (W.translations) ep.translations = W.translations;
            return ep;
          };
          const finish = (how) => {
            Object.assign(CS, { ep: build(), id: W.editId || "", keepId: !!W.editId, rendered: null, scriptDraft: W.directScript,
              beats: W.beats, wiz: null });
            close({ how, fresh: W.fresh });
          };
          if ($("#cw-trans", box)) $("#cw-trans", box).onclick = guard(async (e) => {
            const ep = build();
            await checkTranslation(ep, e.currentTarget, () => { W.translations = ep.translations; });
          });
          $("#cw-render", box).onclick = (e) => { sparkle(e.currentTarget, e); setTimeout(() => finish("render"), 250); };
          $("#cw-save", box).onclick = () => finish("save");
        },
      ];
      go(Math.min(W.step, W.max));
    },
  });
}

function showResult(video, sheet) {
  const box = $("#result");
  if (!box) return;
  if (!video) { box.innerHTML = ""; return; }
  box.innerHTML = `<video class="preview" src="${esc(video)}" controls playsinline></video>
    <div class="btns"><a class="btn" href="${esc(video.split("?")[0])}" download>⬇ Download mp4</a></div>
    ${sheet ? `<img class="sheet" src="${esc(sheet)}" alt="Shot sheet">` : ""}`;
}

// ---- the rest of the cast ("+name verb" in the script, or the 🎭 field on a shot)
const eventsText = (evs) => (evs || []).map((e) => [e.who, e.do, e.from ? "from_" + e.from : "", e.to || ""].filter(Boolean).join(" ")).join(", ");
function parseEvents(text, marks) {
  const cat = META.catalog, out = [];
  for (const part of String(text || "").split(",")) {
    const w = part.trim().toLowerCase().replace(/^\+/, "").split(/\s+/).filter(Boolean);
    if (!w.length) continue;
    const who = w[0].replace(/[^a-z0-9_]/g, "").slice(0, 24);
    if (!who) continue;
    const e = { who, do: "enter" };
    for (const t of w.slice(1)) {
      if (cat.cast_verbs[t] || cat.anims[t]) e.do = t;
      else if (t.startsWith("from_") && cat.from_sides.includes(t.slice(5))) e.from = t.slice(5);
      else if (marks.includes(t)) e.to = t;
    }
    out.push(e);
  }
  return out;
}
function syncCast(ep) {   // keep ep.cast in step with who appears in the shots
  const used = new Set(ep.shots.flatMap((s) => (s.events || []).map((e) => e.who)));
  ep.cast = ep.cast || {};
  for (const w of used) if (!ep.cast[w]) ep.cast[w] = { looks: w.replace(/_/g, " ") };
  for (const w of Object.keys(ep.cast)) if (!used.has(w)) delete ep.cast[w];
  if (!Object.keys(ep.cast).length) delete ep.cast;
}
function drawCast(box, ep, onChange) {
  if (!box) return;
  syncCast(ep);
  const cast = ep.cast || {};
  const names = Object.keys(cast);
  box.innerHTML = names.length ? `<div class="cast-panel"><h4>🎭 Cast <span class="muted small">— others in the scene (people speak lines written as “Name: …”)</span></h4>
    ${names.map((n) => `<div class="row cast-row" data-who="${esc(n)}">
      <label style="flex:0 0 120px">Name<input type="text" disabled value="${esc(n)}"></label>
      <label style="flex:0 0 130px">Is a<select data-c="type"><option value="">auto</option>${options(["person", "thing"], cast[n].type || "", { person: "🧍 person", thing: "📦 thing" })}</select></label>
      <label style="flex:3">Looks like<input type="text" data-c="looks" placeholder="e.g. tall man, grey hair, blue suit / small red car" value="${esc(cast[n].looks || "")}"></label></div>`).join("")}
    <p class="muted small" style="margin:4px 0 0">People get a simple low-poly body coloured from the description; things are designed by the AI prop maker when the video renders (and saved to the prop library).</p></div>` : "";
  $$(".cast-row", box).forEach((row) => $$("[data-c]", row).forEach((inp) => inp.addEventListener("change", () => {
    const c = cast[row.dataset.who];
    if (inp.value) c[inp.dataset.c] = inp.value; else delete c[inp.dataset.c];
    if (inp.dataset.c === "looks") delete c.def;   // re-design it from the new description
    onChange();
  })));
}

function sceneOptions(ep, cur) {
  const cat = META.catalog;
  const base = cat.sets[ep.set]?.name || ep.set;
  let html = `<option value="">Same as the video (${esc(base)})</option>`;
  if (cur && String(cur).startsWith("new:")) html += `<option value="${esc(cur)}" selected>✨ New: ${esc(cur.slice(4))}</option>`;
  html += Object.entries(cat.sets).map(([id, s]) => `<option value="${esc(id)}" ${id === cur ? "selected" : ""}>${esc(s.name)}</option>`).join("");
  return html + `<option value="__new">✨ Make a new set…</option>`;
}
function fxOptions(s) {
  const cat = META.catalog;
  const cur = Array.isArray(s.particles) ? s.particles : (s.particles ? [s.particles] : null);
  let html = `<option value="__auto" ${cur === null ? "selected" : ""}>from the set</option><option value="" ${cur && !cur.length ? "selected" : ""}>none</option>`;
  if (cur && cur.length > 1) html += `<option value="${esc(cur.join(","))}" selected>${esc(cur.join(" + "))}</option>`;
  return html + Object.entries(cat.particles || {}).map(([k, v]) => `<option value="${k}" ${cur && cur.length === 1 && cur[0] === k ? "selected" : ""}>✨ ${esc(v)}</option>`).join("");
}

const langName = (code) => (META.catalog.languages || {})[code || "en"] || code || "English";
// every translated line next to its English; your fixes are saved in the episode (ep.translations) and used at render
async function checkTranslation(ep, btn, onSaved) {
  const lang = ep.language || META.settings.language || "en";
  if (lang === "en") throw new Error("The video is in English - pick another language first");
  if (!ep.shots?.length) throw new Error("Direct the shots first");
  const r = await busy(btn, "🌐 Translating…", () => api("POST", "/api/translate", { episode: ep, language: lang }));
  const saved = await openModal({ title: `🌐 ${langName(lang)} - check the translation`, wide: true,
    body: `<p class="muted small" style="margin-top:0">The AI translated these. Fix anything that's wrong - what you save here is exactly what's said and shown.</p>
      ${r.lines.map((l, i) => `<label class="modal-field"><span class="muted small">${esc(l.en)}</span>
        <textarea rows="2" data-tr="${i}">${esc(l.out)}</textarea></label>`).join("")}`,
    buttons: [{ label: "Cancel", value: null },
      { label: "💾 Save translation", primary: true, onClick: (m) => Object.fromEntries(r.lines.map((l, i) => [l.en, $(`[data-tr="${i}"]`, m).value.trim() || l.out])) }] });
  if (!saved) return;
  ep.translations = { ...(ep.translations || {}), [lang]: saved };
  onSaved && onSaved();
  toast("Translation saved with this video");
}

// who can say a shot's line: the video's character, its co-stars and the people in its cast
const mainId = (ep) => (typeof ep.character === "string" && ep.character) || META.settings.active_character;
function speakersOf(ep) {
  const people = Object.entries(ep.cast || {}).filter(([, c]) => c && c.type !== "thing").map(([k]) => k);
  return [mainId(ep), ...(ep.co_stars || []), ...people.filter((p) => !(ep.co_stars || []).includes(p))];
}
function speakerPicker(ep, s) {
  const who = speakersOf(ep);
  if (who.length < 2) return "";
  return `<label>Says it<select data-k="speaker">${options(who, s.speaker || who[0], Object.fromEntries(who.map((c) => [c, titleCase(c)])))}</select></label>`;
}
// with more than one main character: what the others do while someone talks, and a two-shot of everyone
function othersPicker(ep, s, anims) {
  if (!(ep.co_stars || []).length) return "";
  const still = anims.filter((a) => !META.catalog.anims[a]?.moves && !["float_up", "land", "fall", "float"].includes(a));
  return `<div class="row"><label>The others while this is said<select data-k="listen">${options(["", ...still], s.listen || "",
      { "": "listen (idle, turned to the speaker)" })}</select></label>
    <label class="check" style="align-self:flex-end"><input type="checkbox" data-k="both" ${s.both ? "checked" : ""}> Everyone in the frame</label></div>`;
}

function drawShots(box, ep, marks, onChange) {
  const cat = META.catalog;
  const anims = Object.keys(cat.anims);
  box.innerHTML = ep.shots.map((s, i) => {
    const multi = Array.isArray(s.actions);
    const smarks = !s.set ? marks : (cat.sets[s.set]?.marks || ["center", "front", "left", "right", "back"]);
    const act = s.action || "idle";
    const moves = cat.anims[act]?.moves;
    const emo = s.voice?.exaggeration ?? "";
    return `<div class="shot" data-i="${i}">
      <div class="head"><span class="num">${i + 1}</span>
        <input type="text" data-k="line" placeholder="What she says (optional)" value="${esc(s.line || "")}">
        <div class="tools"><button data-do="up" title="Move up">↑</button><button data-do="down" title="Move down">↓</button>
        <button data-do="dup" title="Duplicate">⧉</button><button data-do="del" title="Delete">✕</button></div></div>
      <div class="row">
        <label>Camera<select data-k="camera">${options(Object.keys(cat.cameras), s.camera || "medium")}</select></label>
        <label>Camera move<select data-k="move">${options(Object.keys(cat.moves), s.move || "static")}</select></label>
        ${multi ? `<label>Action<input type="text" disabled value="${esc(s.actions.map((a) => a.anim).join(" → "))} (JSON)"></label>`
                : `<label>Action<select data-k="action">${options(anims, act)}</select></label>`}
        ${!multi && moves ? `<label>To<select data-k="to">${options(smarks, s.to || smarks[0])}</select></label>` : ""}
        ${speakerPicker(ep, s)}
        <label>Light<select data-k="light">${options(["", ...Object.keys(cat.lights || {})], s.light || "", { "": "no change", ...(cat.lights || {}) })}</select></label>
        <label>Scene<select data-k="set">${sceneOptions(ep, s.set || "")}</select></label>
        <label>Effects<select data-k="particles">${fxOptions(s)}</select></label>
        <label>Expression<select data-k="expression"><option value="">auto</option>${options(cat.expressions, s.expression || "")}</select></label>
        <label>Face<select data-k="face"><option value="">auto</option>${options(cat.facing, s.face || "")}</select></label>
        <label>Seconds<input type="number" data-k="duration" min="0.5" step="0.5" placeholder="auto" value="${esc(s.duration ?? "")}"></label>
        <label>Voice emotion<select data-k="emotion"><option value="">auto</option>${options(["0.3", "0.5", "0.7", "0.9", "1"], String(emo), { "0.3": "calm", "0.5": "normal", "0.7": "lively", "0.9": "intense", "1": "max" })}</select></label>
        <label>Sound effect<select data-k="sfx"><option value="__auto" ${"sfx" in s ? "" : "selected"}>auto</option><option value="" ${s.sfx === "" ? "selected" : ""}>none</option>${options(Object.keys(META.sfx).filter((k) => META.sfx[k].kind === "oneshot"), typeof s.sfx === "string" ? s.sfx : "", Object.fromEntries(Object.entries(META.sfx).map(([k, v]) => [k, "🔊 " + v.label])))}</select></label>
      </div>
      ${othersPicker(ep, s, anims)}
      <label class="others" title="Show something else instead of her - her line plays over it">📷 Cutaway <span class="muted small">(show this instead of her, e.g. "a plane flying past" - leave empty to show her)</span><input type="text" data-k="cutaway" placeholder="e.g. ants marching, a meteor falling" value="${esc(s.cutaway || "")}"></label>
      <label class="others" title="Who else is in this shot and what they do, e.g. mom enter, car crash_in from_left">🎭 Others in this shot <span class="muted small">(name + what they do: enter, exit, crash_in, fall, fly_by, appear, vanish, or an action like wave)</span><input type="text" data-k="events" placeholder="e.g. mom enter, car crash_in from_left" value="${esc(eventsText(s.events))}"></label></div>`;
  }).join("") || '<p class="muted">No shots yet - write or generate a script above and press “Direct shots”, or add one.</p>';

  $$(".shot", box).forEach((el) => {
    const i = +el.dataset.i, s = ep.shots[i];
    $$("[data-k]", el).forEach((inp) => inp.addEventListener("change", async () => {
      const k = inp.dataset.k, val = inp.value;
      if (k === "emotion") { s.voice = s.voice || {}; if (val) s.voice.exaggeration = Number(val); else delete s.voice.exaggeration; if (!Object.keys(s.voice).length) delete s.voice; }
      else if (k === "duration") { if (val) s.duration = Number(val); else delete s.duration; }
      else if (k === "sfx") { if (val === "__auto") delete s.sfx; else s.sfx = val; }
      else if (k === "particles") { if (val === "__auto") delete s.particles; else s.particles = val ? val.split(",") : []; }
      else if (k === "set") {
        let v = val;
        if (v === "__new") { const idea = await uiPrompt("✨ New place for this shot", { label: "Describe the place - a new set is made for it when the video renders", placeholder: "e.g. falling through the clouds, on the moon", ok: "Use this place" }); v = idea ? "new:" + idea : (s.set || ""); }
        // the scene carries on to the following shots that were in the same place
        const old = s.set || "";
        for (let j = i; j < ep.shots.length; j++) { if (j > i && (ep.shots[j].set || "") !== old) break; if (v) ep.shots[j].set = v; else delete ep.shots[j].set; }
        drawShots(box, ep, marks, onChange); onChange(); return;
      }
      else if (k === "events") { const ev = parseEvents(val, marks); if (ev.length) s.events = ev; else delete s.events; syncCast(ep); }
      else if (k === "both") { if (inp.checked) s.both = true; else delete s.both; }
      else if (k === "speaker") { if (!val || val === mainId(ep)) delete s.speaker; else s.speaker = val; }
      else if (val === "") delete s[k];
      else s[k] = val;
      if (k === "action") { if (META.catalog.anims[val]?.moves) s.to = s.to || marks[0]; else delete s.to; drawShots(box, ep, marks, onChange); }
      onChange();
    }));
    $$("[data-do]", el).forEach((b) => b.addEventListener("click", () => {
      const d = b.dataset.do;
      if (d === "del") ep.shots.splice(i, 1);
      if (d === "dup") ep.shots.splice(i + 1, 0, JSON.parse(JSON.stringify(s)));
      if (d === "up" && i > 0) [ep.shots[i - 1], ep.shots[i]] = [ep.shots[i], ep.shots[i - 1]];
      if (d === "down" && i < ep.shots.length - 1) [ep.shots[i + 1], ep.shots[i]] = [ep.shots[i], ep.shots[i + 1]];
      drawShots(box, ep, marks, onChange); onChange();
    }));
  });
}

/* ------------------------------------------------------------------ SETS */
// the theme picker: the options, then every theme (built-in and generated)
const themeOptions = (t, cur) => [...t.options, ...t.themes.map((x) => ({ id: x.id, name: x.name }))]
  .map((o) => `<option value="${esc(o.id)}" ${o.id === cur ? "selected" : ""}>${esc(o.name)}</option>`).join("");

async function pageSets() {
  const [sets, props, themes] = await Promise.all([api("GET", "/api/sets"), api("GET", "/api/props"), api("GET", "/api/themes")]);
  const mode = META.settings.comfy.mode;
  app.innerHTML = `
    <div class="panel" style="border-color:var(--accent)"><h3 style="margin-top:0">🖼 Scene from a picture</h3>
      <p class="muted small" style="margin-top:0">Upload a picture of a place and the studio rebuilds it as a low-poly set: the same kind of place, its colours and light, and the things it shows
        (the closest ready-made props, or new ones). Positions are approximate - the set follows the picture's layout in broad strokes.</p>
      <div class="row" style="align-items:end"><label style="flex:2">Extra note (optional)<input type="text" id="sp-idea" placeholder="e.g. make it night, add a fountain"></label>
        <div><button class="primary" id="sp-go">🖼 Choose a picture…</button><input type="file" id="sp-file" accept="image/png,image/jpeg,image/webp" hidden></div></div>
      <div class="inline-job" id="sp-job"></div></div>
    <div class="panel"><p class="muted small" style="margin-top:0">Every new set is made from scratch. With <b>Ollama</b> on, the AI invents the place (name, mood, colours, props, pools of water/lava/slime, pictures, background sound) and designs brand-new 3D props when the place needs something we don't have yet - give it an idea or leave it empty to be surprised. With <b>Pure random</b>, everything is rolled by dice.</p>
      <div class="row" style="align-items:end">
      <label style="flex:2">Idea (optional)<input type="text" id="g-idea" placeholder="e.g. haunted bakery, underwater office, cat café on the moon"></label>
      <label>Designer<select id="g-ai">${options(["auto", "off"], META.settings.sets.use_ollama ? "auto" : "off", { auto: "🤖 Ollama", off: "🎲 Pure random" })}</select></label>
      <label>Where<select id="g-where">${options(Object.keys(WHERE), "", WHERE)}</select></label>
      <label>Time<select id="g-light">${options(Object.keys(LIGHT), "", LIGHT)}</select></label></div>
      <div class="row" style="align-items:end;margin-top:8px">
      <label>Name (optional)<input type="text" id="g-name" placeholder="AI / random"></label>
      <label>Theme<select id="g-theme">${themeOptions(themes, "auto")}</select></label>
      <label>ComfyUI textures<select id="g-comfy">${options(["required", "auto", "off"], mode, COMFY_MODES)}</select></label>
      <button id="g-go" class="primary">🎲 Generate new set</button>
      <button id="g-starter">Generate 3 Starter Sets</button></div>
      <div class="inline-job" id="g-starter-job"></div>
      <p class="muted small" style="margin:8px 0 0">ComfyUI: <span id="g-comfy-st"><span class="pill">checking…</span></span>
        — <b>Required</b>: always textures the floor, walls or sky and every picture (fails if ComfyUI is off) ·
        <b>Only when needed</b>: just posters, signs, chalkboards and windows · <b>Off</b>: flat-colour art only.</p>
      <div id="g-job" class="inline-job"></div></div>
    <details class="panel" id="props-lib"><summary><b>🧱 ${props.length} AI-made props</b> <span class="muted small">— designed for earlier sets and reused by new ones</span></summary>
      ${props.length ? `<div class="chips">${props.map((p) => `<span class="chip" title="${esc(p.looks)} (${p.parts} parts, ${p.height} m tall)">${esc(p.kind.replace(/_/g, " "))}<button class="chip-x" data-pdel="${esc(p.kind)}" title="Remove from the library (sets that use it keep their copy)">✕</button></span>`).join("")}</div>`
        : `<p class="muted small">None yet - generate a set with Ollama and it will add props here.</p>`}</details>
    <h2>${sets.length} sets</h2>
    <div class="setgrid">${sets.map((s) => `
      <div class="setcard">
        ${s.preview ? `<img src="${esc(s.preview)}" alt="" loading="lazy" decoding="async">` : `<div class="noimg">no preview</div>`}
        <div class="title">${esc(s.name)}</div>
        <div class="muted small">${LIGHT_ICON[s.light] || ""} ${esc(s.where)}${s.props ? ` · ${s.props} props` : ""}${s.textures.length ? " · 🖼 textured" : ""}</div>
        <div class="muted small" title="Places she can walk to">📍 ${esc(s.marks.join(", "))}</div>
        <div class="btns"><button data-use="${esc(s.id)}">Use</button><button data-prev="${esc(s.id)}">↻ Preview</button>
          ${s.builtin ? "" : `<button data-regen="${esc(s.id)}" title="Build this set again with other settings">🔄 Regenerate</button>
          <button data-layout="${esc(s.id)}" title="Move the props around on a top-down map">🗺 Layout</button>
          <button data-view="${esc(s.id)}" title="Look around the scene in 3D">👁 3D view</button>`}
          <button data-del="${esc(s.id)}" title="Remove this set">🗑</button></div>
      </div>`).join("")}</div>`;
  api("GET", "/api/comfy/status").then((cs) => {
    const el = $("#g-comfy-st");
    if (el) el.innerHTML = cs.ok ? `<span class="pill ok">connected</span> ${esc((cs.checkpoints || []).join(", "))}` : `<span class="pill err">offline</span> ${esc(cs.error || "")}`;
  }).catch(() => {});
  $("#g-starter").onclick = guard(async () => {
    const job = await api("POST", "/api/sets/starter", {});
    watchJob(job, $("#g-starter-job"), guard(async (j) => {
      if (j.status !== "done") return toast("Starter sets failed - see the log", true);
      await refreshMeta(); toast("3 starter sets ready"); pageSets();
    }));
  });
  $("#g-go").onclick = guard(async () => {
    const job = await api("POST", "/api/sets/generate", { idea: $("#g-idea").value, ai: $("#g-ai").value, where: $("#g-where").value, light: $("#g-light").value, name: $("#g-name").value, comfy: $("#g-comfy").value, theme: $("#g-theme").value });
    watchJob(job, $("#g-job"), guard(async (j) => {
      if (j.status !== "done") return toast("Set generation failed", true);
      await refreshMeta(); toast("New set ready"); pageSets();
    }));
  });
  $$("[data-use]").forEach((b) => b.onclick = () => { CS.ep.set = b.dataset.use; CS.ep.start = "front"; location.hash = "#create"; });
  $$("[data-pdel]").forEach((b) => b.onclick = guard(async () => {
    if (!(await uiConfirm(`Remove “${b.dataset.pdel.replace(/_/g, " ")}” from the prop library? It goes to assets/props/.trash.`, { title: "Delete prop", ok: "🗑 Delete", danger: true }))) return;
    await api("DELETE", `/api/props/${b.dataset.pdel}`); await pageSets(); $("#props-lib").open = true;
  }));
  $$("[data-prev]").forEach((b) => b.onclick = guard(async () => {
    const job = await api("POST", `/api/sets/${b.dataset.prev}/preview`);
    watchJob(job, $("#g-job"), () => pageSets());
  }));
  $$("[data-del]").forEach((b) => b.onclick = guard(async () => {
    if (!(await uiConfirm("Episodes that use this set won't render until it's restored. Its files go to sets/.trash.", { title: "Remove this set?", ok: "🗑 Remove", danger: true }))) return;
    await api("DELETE", `/api/sets/${b.dataset.del}`); await refreshMeta(); pageSets();
  }));
}

/* ------------------------------------------------------------------ AUDIO (music + sound effects) */
let A_TAB = "music";
async function pageAudio() {
  return pageAssets(A_TAB === "sfx" ? "sfx" : "music");
}

async function saveSettingsPatch(fn) {
  const st = await api("GET", "/api/settings");
  fn(st);
  META.settings = await api("PUT", "/api/settings", st);
}

async function audioMusic(box) {
  const music = await api("GET", "/api/music");
  const st = META.settings;
  box.innerHTML = `
    <div class="panel"><h3>Add royalty-free music</h3>
      <div class="row"><label style="flex:2">Upload tracks (mp3, wav, ogg, m4a, flac) - they stay here for every episode
        <input type="file" id="m-up" accept=".mp3,.wav,.ogg,.m4a,.flac,audio/*" multiple></label></div>
      <div class="setting" style="margin-top:10px"><label style="color:var(--text)">Music volume</label>
        <input type="range" id="m-vol" min="0" max="0.5" step="0.01" value="${st.audio.music_volume}"><span class="val mono" id="m-volv">${Math.round(st.audio.music_volume * 100)}%</span>
        <div class="help muted small">Quiet background bed under the voice (5% recommended). Fades in and out automatically.</div></div>
      <p class="muted small" style="margin:8px 0 0">Only use music you have the rights to (royalty-free / licensed for social media).</p></div>
    <div class="panel"><h3>✨ Generate music</h3>
      <label>Style (genre, mood, instruments)<input type="text" id="mg-style" value="cheerful retro chiptune, video game, cute, upbeat"></label>
      <div class="chips" id="mg-chips">${["cheerful retro chiptune, video game, cute, upbeat", "lofi chill hip hop, soft piano, relaxed", "spooky halloween, music box, eerie", "epic orchestral adventure, heroic", "cute kawaii pop, bubbly synths", "funky bass groove, comedic", "dreamy ambient synth pads, calm", "fast 8-bit boss battle, intense"].map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>
      <div class="row" style="margin-top:10px">
        <label>Length (seconds)<input type="number" id="mg-sec" min="10" max="240" step="5" value="60"></label>
        <label>Engine<select id="mg-engine">${options(["auto", "ace", "synth"], "auto", { auto: "Auto (ACE-Step if available)", ace: "ACE-Step via ComfyUI", synth: "Retro chiptune synth (instant)" })}</select></label>
        <label>Name (optional)<input type="text" id="mg-name" placeholder="from style"></label>
        <button id="mg-go" class="primary">✨ Generate music</button></div>
      <p class="muted small">ACE-Step (in your ComfyUI) composes real instrumental music in ~20 s per 30 s of audio. The synth makes a simple 8-bit loop instantly and needs nothing.</p>
      <div id="mg-job" class="inline-job"></div></div>
    <div class="panel"><h3>${music.length} track${music.length === 1 ? "" : "s"}</h3>
      ${music.length ? music.map((m) => `
        <div class="row" style="align-items:center;padding:6px 0;border-bottom:1px dashed var(--line)">
          <div style="flex:2;min-width:180px">${m.default ? '<span class="badge">DEFAULT</span> ' : ""}${esc(m.name)}<div class="muted small">${(m.size / 1048576).toFixed(1)} MB</div></div>
          <audio controls preload="none" src="${esc(m.url)}" style="flex:3;min-width:220px"></audio>
          <button data-def="${esc(m.path)}" ${m.default ? "disabled" : ""}>★ Make default</button>
          <button data-del="${esc(m.name)}" title="Move to assets/music/.trash">🗑</button></div>`).join("")
        : '<p class="muted">No music yet - upload some tracks above.</p>'}
      ${music.some((m) => m.default) ? '<div class="btns"><button id="m-nodef">No default music</button></div>' : ""}</div>`;
  $("#m-up").onchange = guard(async (e) => {
    for (const f of e.target.files) {
      toast(`Uploading ${f.name}…`);
      await api("POST", "/api/music", undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    }
    toast("Music added"); audioMusic(box);
  });
  $$("#mg-chips .chip", box).forEach((c) => c.onclick = () => { $("#mg-style").value = c.textContent; });
  $("#mg-go").onclick = guard(async () => {
    const job = await api("POST", "/api/music/generate", { style: $("#mg-style").value, seconds: Number($("#mg-sec").value) || 60,
      engine: $("#mg-engine").value, name: $("#mg-name").value });
    watchJob(job, $("#mg-job"), (j) => {
      if (j.status === "done") { toast("New track added to the library"); setTimeout(() => audioMusic(box), 600); }
      else toast("Music generation failed - see the log", true);
    });
  });
  const vol = $("#m-vol");
  vol.oninput = () => { $("#m-volv").textContent = Math.round(vol.value * 100) + "%"; };
  vol.onchange = guard(async () => { await saveSettingsPatch((s) => { s.audio.music_volume = Number(vol.value); }); toast("Music volume saved"); });
  $$("[data-def]", box).forEach((b) => b.onclick = guard(async () => { await saveSettingsPatch((s) => { s.audio.default_music = b.dataset.def; }); toast("Default music set"); audioMusic(box); }));
  if ($("#m-nodef")) $("#m-nodef").onclick = guard(async () => { await saveSettingsPatch((s) => { s.audio.default_music = ""; }); audioMusic(box); });
  $$("[data-del]", box).forEach((b) => b.onclick = guard(async () => {
    if (!(await uiConfirm(`Remove ${b.dataset.del} from the library? It's moved to assets/music/.trash.`, { title: "Remove track", ok: "🗑 Remove", danger: true }))) return;
    await api("DELETE", `/api/music/${encodeURIComponent(b.dataset.del)}`); audioMusic(box);
  }));
}

async function audioSfx(box) {
  const lib = await api("GET", "/api/sfx");
  const st = META.settings;
  const ambs = lib.filter((s) => s.kind === "ambience");
  const row = (s) => `
    <div class="row" style="align-items:center;padding:6px 0;border-bottom:1px dashed var(--line)">
      <div style="flex:2;min-width:200px"><b>${esc(s.label)}</b> <code class="small">${esc(s.slot)}</code>
        ${s.generated ? `<span class="pill ok" title="${esc(s.description)}">generated</span>` : s.custom ? '<span class="pill ok">your upload</span>' : s.has_builtin ? '<span class="pill">built-in</span>' : '<span class="pill err">empty</span>'}
        ${s.words ? `<div class="muted small">triggers: ${esc(s.words)}</div>` : ""}</div>
      ${s.url ? `<audio controls preload="none" src="${esc(s.url)}?v=${Date.now()}" style="flex:2;min-width:200px"></audio>` : '<span style="flex:2"></span>'}
      <button data-gen="${esc(s.slot)}" data-desc="${esc(s.description || s.label.replace("Ambience: ", ""))}" title="Make a new version from a description">✨ Generate</button>
      <label class="btn" style="cursor:pointer">⬆ Upload<input type="file" accept="audio/*" data-up="${esc(s.slot)}" hidden></label>
      ${s.custom && s.has_builtin ? `<button data-reset="${esc(s.slot)}" title="Use the built-in sound again">↺ Built-in</button>` : ""}
      ${s.builtin ? "" : `<button data-rm="${esc(s.slot)}" title="Remove this sound">🗑</button>`}</div>`;
  box.innerHTML = `
    <div class="grid2"><div>
      <div class="panel"><h3>Sound effects</h3>
        <p class="muted small" style="margin-top:0">Built-in sounds are synthesised retro effects. Upload your own file to any slot to replace it.
          Effects are added automatically when a line contains a trigger word (or for jumps, surprises, celebrations), and you can pick or remove them per shot on the Create page - or write <code>[boom]</code> in the script.</p>
        ${lib.filter((s) => s.kind === "oneshot").map(row).join("")}</div>
      <div class="panel"><div class="row" style="align-items:center"><h3 style="margin:0;flex:1">Background ambience</h3>
          <button id="amb-new">✨ Generate new ambience</button></div>
        <p class="muted small">A quiet loop under the whole video, chosen to fit the set (arcade bleeps, waves, birds, wind…).</p>
        ${ambs.map(row).join("")}</div>
    </div><div class="side">
      <div class="panel"><h3>Mix</h3>
        <label class="check"><input type="checkbox" id="x-auto" ${st.sfx.auto ? "checked" : ""}> Add effects automatically</label>
        <div class="setting"><label style="color:var(--text)">Effects volume</label><input type="range" id="x-vol" min="0" max="1" step="0.05" value="${st.sfx.volume}"><span class="val mono">${Math.round(st.sfx.volume * 100)}%</span></div>
        <div class="setting"><label style="color:var(--text)">Ambience</label><select id="x-amb"><option value="">Off</option><option value="auto" ${st.sfx.ambience === "auto" ? "selected" : ""}>Auto from set theme</option>${options(ambs.map((a) => a.slot), st.sfx.ambience, Object.fromEntries(ambs.map((a) => [a.slot, a.label])))}</select><span></span></div>
        <div class="setting"><label style="color:var(--text)">Ambience volume</label><input type="range" id="x-avol" min="0" max="1" step="0.05" value="${st.sfx.ambience_volume}"><span class="val mono">${Math.round(st.sfx.ambience_volume * 100)}%</span></div>
        <div class="btns"><button class="primary" id="x-save">💾 Save mix</button></div></div>
      <div class="panel"><h3>Add new sound effects</h3>
        <label>Name<input type="text" id="n-label" placeholder="e.g. Fireworks"></label>
        <label style="margin-top:8px">Describe the sound (for generating)<input type="text" id="n-desc" placeholder="fireworks whistling up then crackling"></label>
        <label style="margin-top:8px">Trigger words in scripts (space separated)<input type="text" id="n-words" placeholder="fireworks sparkler celebration"></label>
        <div class="row" style="margin-top:8px"><label>Type<select id="n-kind"><option value="oneshot">Sound effect</option><option value="ambience">Ambience loop</option></select></label></div>
        <div class="btns"><button id="n-gen" class="primary">✨ Generate it</button>
          <label class="btn" style="cursor:pointer">⬆ Upload a file instead<input type="file" id="n-file" accept="audio/*" hidden></label></div>
        <p class="muted small">Generating uses Ollama (if enabled in Settings → AI tools) to design the sound, then synthesises it. You can regenerate or replace it any time from the list.</p></div>
      <div class="panel"><h3>Built-in sounds</h3><button id="x-regen">↻ Regenerate built-in sounds</button><div id="x-job" class="inline-job"></div></div>
    </div></div>`;
  $$("[data-up]", box).forEach((inp) => inp.onchange = guard(async () => {
    const f = inp.files[0]; if (!f) return;
    await api("POST", `/api/sfx/${inp.dataset.up}`, undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    toast(`Saved your sound for '${inp.dataset.up}'`); audioSfx(box);
  }));
  $$("[data-reset]", box).forEach((b) => b.onclick = guard(async () => { await api("DELETE", `/api/sfx/${b.dataset.reset}/custom`); audioSfx(box); }));
  $$("[data-rm]", box).forEach((b) => b.onclick = guard(async () => {
    if (!(await uiConfirm(`Remove the sound “${b.dataset.rm}”? Its file goes to assets/sfx/custom/.trash.`, { title: "Remove sound", ok: "🗑 Remove", danger: true }))) return;
    await api("DELETE", `/api/sfx/${b.dataset.rm}`); await refreshMeta(); audioSfx(box);
  }));
  $$("#x-vol, #x-avol", box).forEach((r) => r.oninput = () => { r.nextElementSibling.textContent = Math.round(r.value * 100) + "%"; });
  $("#x-save").onclick = guard(async () => {
    await saveSettingsPatch((s) => { s.sfx.auto = $("#x-auto").checked; s.sfx.volume = Number($("#x-vol").value); s.sfx.ambience = $("#x-amb").value; s.sfx.ambience_volume = Number($("#x-avol").value); });
    toast("Mix saved");
  });
  const newSlot = (generate) => ({ name: $("#n-label").value, label: $("#n-label").value, words: $("#n-words").value,
    kind: $("#n-kind").value, description: $("#n-desc").value || $("#n-label").value, generate });
  $("#n-gen").onclick = guard(async (e) => busy(e.currentTarget, "✨ Generating…", async () => {
    if (!$("#n-label").value.trim()) throw new Error("Give the sound a name first");
    const r = await api("POST", "/api/sfx/slots", newSlot(true));
    await refreshMeta(); toast(`Made '${r.slot}' - press play to hear it`); audioSfx(box);
  }));
  $("#n-file").onchange = guard(async (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (!$("#n-label").value.trim()) $("#n-label").value = f.name.replace(/\.[^.]+$/, "");
    const r = await api("POST", "/api/sfx/slots", newSlot(false));
    await api("POST", `/api/sfx/${r.slot}`, undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    await refreshMeta(); toast(`Added '${r.slot}'`); audioSfx(box);
  });
  $$("[data-gen]", box).forEach((b) => b.onclick = guard(async () => {
    const desc = await uiPrompt("✨ Generate a new sound", { label: "Describe the sound you want - a new version is made and the current one goes to the trash", value: b.dataset.desc, multiline: true, ok: "✨ Generate" });
    if (desc === null) return;
    await busy(b, "✨ …", () => api("POST", `/api/sfx/${b.dataset.gen}/generate`, { description: desc }));
    toast("New sound generated"); audioSfx(box);
  }));
  $("#amb-new").onclick = guard(async (e) => {
    const desc = await uiPrompt("✨ New background ambience", { label: "Describe the ambience", placeholder: "e.g. busy café chatter, rain on a tin roof, spaceship engine hum", ok: "✨ Generate" });
    if (!desc) return;
    const name = desc.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 22) || "ambience";
    await busy(e.currentTarget, "✨ Generating…", async () => {
      await api("POST", "/api/sfx/slots", { name, label: "Ambience: " + desc.slice(0, 40), words: "", kind: "ambience", description: desc, generate: true });
    });
    await refreshMeta(); toast("New ambience added"); audioSfx(box);
  });
  $("#x-regen").onclick = guard(async () => {
    const job = await api("POST", "/api/sfx/regenerate");
    watchJob(job, $("#x-job"), () => audioSfx(box));
  });
}

/* ------------------------------------------------------------------ VIDEOS */
async function pageVideos() {
  const vids = await api("GET", "/api/videos");
  app.innerHTML = `<h2>Videos</h2>${vids.length ? `<div class="cards">${vids.map((v) => `
    <div class="card"><video src="${esc(v.url)}" controls preload="none" playsinline></video>
      <div class="title">${v.previous ? '<span class="pill">Earlier version</span> ' : ""}${v.series ? `<span class="pill" title="Series: ${esc(v.series.idea || "")}">📺 ${esc(String(v.series.idea || "").slice(0, 24))} ${v.series.part}/${v.series.of}</span> ` : ""}${esc(v.title || v.name)}</div>
      <div class="muted small">${ago(v.updated)} · ${(v.size / 1048576).toFixed(1)} MB</div>
      <div class="btns"><a class="btn" href="${esc(v.url)}" download>⬇ Download</a>
        ${v.episode ? `<button data-redit="${esc(v.episode)}" class="primary">✏️ Edit</button>` : ""}
        ${META.settings.postiz?.url ? `<button data-pz="${esc(v.key)}">📤 Postiz</button>` : ""}
        ${v.sheet ? `<button data-sheet="${esc(v.sheet)}" title="One frame from every shot">🎞 Shots</button>` : ""}
        <button data-rename="${esc(v.key)}" data-title="${esc(v.title || v.name)}">✏️ Rename</button>
        <button data-delete="${esc(v.key)}" data-title="${esc(v.title || v.name)}" class="danger">🗑 Delete</button></div>
      <div class="pz-box" id="pz-${esc(v.key)}"></div></div>`).join("")}</div>`
    : '<p class="muted">No videos yet. Make one on the Create page.</p>'}`;
  $$("[data-sheet]").forEach((b) => b.onclick = () => {
    const card = b.closest(".card");
    const open = $(".sheet-strip", card);
    if (open) { open.remove(); return; }
    card.insertAdjacentHTML("beforeend", `<div class="sheet-strip" style="overflow-x:auto;margin-top:8px;border-radius:8px;background:#000">
      <img src="${esc(b.dataset.sheet)}?v=${Date.now()}" alt="One frame from every shot" style="height:220px;max-width:none;display:block;image-rendering:pixelated"></div>`);
  });
  $$("[data-pz]").forEach((b) => b.onclick = guard(async (e) => busy(e.currentTarget, "✍ Writing captions…", async () => {
    const video = b.dataset.pz, box = document.getElementById("pz-" + video);
    const r = await api("POST", "/api/postiz/captions", { video });
    if (!r.ok) throw new Error(r.error);
    const caps = r.captions;
    if (!Object.keys(caps).length) throw new Error("No channels ticked - choose them in Settings → 📤 Postiz");
    const icon = { instagram: "📸", tiktok: "🎵", youtube: "▶", discord: "💬" };
    box.innerHTML = `<div class="panel" style="margin-top:8px"><h4 style="margin:0 0 6px">📤 Drafts for Postiz <span class="muted small">— edit anything, then send</span></h4>
      ${Object.entries(caps).map(([id, c]) => `<div class="pz-cap"><b>${icon[c.platform] || "•"} ${esc(c.name || c.platform)}</b>
        ${"title" in c ? `<input type="text" data-pt="${esc(id)}" value="${esc(c.title)}" maxlength="${c.platform === "tiktok" ? 90 : 100}" placeholder="Title">` : ""}
        <textarea rows="${c.platform === "discord" ? 2 : 4}" data-pc="${esc(id)}">${esc(c.content)}</textarea></div>`).join("")}
      <div class="btns"><button class="primary" data-pzgo>📤 Create drafts</button><button data-pzx>Cancel</button></div><div class="inline-job" data-pzjob></div>
      <p class="muted small" style="margin:4px 0 0">They land in Postiz as drafts - nothing is posted until you schedule them there.</p></div>`;
    $("[data-pzx]", box).onclick = () => { box.innerHTML = ""; };
    $("[data-pzgo]", box).onclick = guard(async () => {
      $$("[data-pc]", box).forEach((t) => { caps[t.dataset.pc].content = t.value; });
      $$("[data-pt]", box).forEach((t) => { caps[t.dataset.pt].title = t.value; });
      const job = await api("POST", "/api/postiz/draft", { video, captions: caps });
      watchJob(job, $("[data-pzjob]", box), (j) => {
        if (j.status === "done") { toast("Drafts created in Postiz ✓"); box.innerHTML = `<p class="small" style="margin-top:6px"><span class="pill ok">drafts created</span> open Postiz to set the times.</p>`; }
        else toast("Postiz drafts failed - see the log", true);
      });
    });
  })));
}

/* ------------------------------------------------------------------ CHARACTERS */
let CHAR_SEL = null;
async function pageCharacters() {
  const chars = await api("GET", "/api/characters");
  CHAR_SEL = CHAR_SEL && chars.some((c) => c.profile.id === CHAR_SEL) ? CHAR_SEL : (chars.find((c) => c.active) || chars[0])?.profile.id;
  app.innerHTML = `<div class="grid2" style="grid-template-columns:260px 1fr">
    <div><div class="panel"><h3>Characters</h3><div class="chars">${chars.map((c) => `
      <button class="charbtn ${c.profile.id === CHAR_SEL ? "on" : ""}" data-id="${esc(c.profile.id)}">${esc(c.profile.name)}
        ${c.active ? '<span class="badge">ACTIVE</span>' : ""}<br><span class="muted small">${esc(c.profile.id)} · ${c.has_model ? "model ✓" : "placeholder"}</span></button>`).join("")}
      </div><div class="btns"><button id="new-char">+ New character</button></div></div></div>
    <div id="char-edit"></div></div>`;
  $$(".charbtn").forEach((b) => b.onclick = () => { CHAR_SEL = b.dataset.id; pageCharacters(); });
  $("#new-char").onclick = guard(async () => {
    const name = await uiPrompt("New character", { label: "Character name", placeholder: "e.g. Puppygirl", ok: "Create" });
    if (!name) return;
    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    if (!id) return;
    if (chars.some((c) => c.profile.id === id)) throw new Error("That character already exists");
    await api("PUT", `/api/characters/${id}`, { name, about: "", voice: {}, tail: false, camera_scale: 0.72 });
    await refreshMeta();
    CHAR_SEL = id; pageCharacters();
  });
  if (CHAR_SEL) drawCharacter(chars.find((c) => c.profile.id === CHAR_SEL));
}

function drawCharacter(info) {
  const p = JSON.parse(JSON.stringify(info.profile));
  p.voice = p.voice || {};
  const r = info.report;
  const box = $("#char-edit");
  box.innerHTML = `
    <div class="panel"><div class="row" style="align-items:center"><h2 style="flex:1;margin:0">${esc(p.name)}</h2>
      ${info.active ? '<span class="badge">ACTIVE</span>' : '<button id="activate">Make active</button>'}
      <button data-char-preview="${esc(p.id)}" ${info.has_model ? "" : "disabled"}>🖼 ${info.preview ? "Remake" : "Make"} preview</button>
      <button id="c-delete" class="danger" ${info.active ? 'disabled title="This is the active character - make another one active first"' : 'title="Move this character to the trash"'}>🗑 Delete</button></div>
      <div id="char-prev" style="margin:10px 0">${info.preview ? `<img src="${esc(info.preview)}?v=${Date.now()}" alt="${esc(p.name)} preview" style="max-width:216px;border-radius:8px;background:#000">`
        : `<p class="muted small">${info.has_model ? "No preview yet - make one to see the character here." : "Import a model first to make a preview."}</p>`}</div>
      <div class="inline-job" id="char-prev-job"></div>
      <div class="row" style="margin-top:12px"><label>Name<input type="text" id="c-name" value="${esc(p.name)}"></label>
        <label>ID<input type="text" value="${esc(p.id)}" disabled></label></div>
      <label style="margin-top:10px">About the character (personality, quirks, catchphrases - the AI script writer uses this)
        <textarea id="c-about" rows="4">${esc(p.about || "")}</textarea></label></div>

    <div class="panel"><h3>3D model</h3>
      ${info.has_model && r ? `<dl class="kv">
          <dt>Model</dt><dd class="mono">${esc(p.model)}</dd><dt>Imported from</dt><dd>${esc(r.source)}</dd>
          <dt>Height</dt><dd>${r.height_m} m</dd><dt>Triangles</dt><dd>${(r.tris || 0).toLocaleString()}</dd>
          <dt>Ear bones</dt><dd class="${r.ears.length ? "ok" : "warn"}">${r.ears.length ? esc(r.ears.join(", ")) : "none found (ears won't move)"}</dd>
          <dt>Tail bones</dt><dd>${r.tail_bones.length ? esc(r.tail_bones.join(", ")) : '<span class="muted">none (use the procedural tail below if wanted)</span>'}</dd>
          <dt>Face shapes</dt><dd class="${r.has_expressions ? "ok" : "warn"}">${r.face_shapes} ${r.has_expressions ? "(VRoid expressions ✓)" : "(no VRoid expressions found)"}</dd></dl>`
        : `<p class="warn">No model yet - episodes use the built-in placeholder.</p>`}
      <label style="margin-top:12px">Import / replace model (.vrm from VRoid Studio → Export → VRM)
        <input type="file" accept=".vrm" id="c-vrm"></label>
      <p class="help-box">The previous model and export are kept as timestamped backups. Command-line equivalent:<br>
        <code>blender -b --factory-startup --python pipeline/prepare_character.py -- assets/characters/${esc(p.id)}.vrm --out assets/characters/${esc(p.id)}.blend</code></p>
      <div id="c-import"></div></div>

    <div class="panel"><h3>Voice</h3><div id="c-voice"></div>
      <div class="row" style="margin-top:12px"><label style="flex:3">Test line<input type="text" id="c-say" value="Hi! I'm ${esc(p.name)}. Nice to meet you!"></label>
        <button id="c-test">🔊 Test voice</button></div>
      <div id="c-voice-job"></div></div>

    <div class="panel"><h3>Look &amp; framing</h3>
      <div class="row"><label class="check"><input type="checkbox" id="c-tail" ${p.tail ? "checked" : ""}> Add procedural tail</label>
        <label>Tail colour<input type="color" id="c-tailcol" value="${esc(p.tail_color || "#c9aed8")}"></label>
        <label class="check"><input type="checkbox" id="c-tailtip" ${p.tail_tip ? "checked" : ""}> White tail tip</label></div>
      <div class="row" style="margin-top:10px"><label>Camera distance (smaller = closer)
        <input type="number" id="c-cam" step="0.02" min="0.4" max="1.5" value="${esc(p.camera_scale ?? 0.72)}"></label></div></div>

    <div class="btns"><button class="primary" id="c-save">💾 Save character</button></div>`;

  voiceEditor($("#c-voice"), p.voice, () => {}, { charId: p.id });
  const collect = () => ({
    ...p, name: $("#c-name").value || p.id, about: $("#c-about").value, tail: $("#c-tail").checked,
    tail_color: $("#c-tailcol").value, tail_tip: $("#c-tailtip").checked, camera_scale: Number($("#c-cam").value) || 0.72,
  });
  const save = async () => { await api("PUT", `/api/characters/${p.id}`, collect()); };
  $("#c-save").onclick = guard(async () => { await save(); toast("Character saved"); pageCharacters(); });
  $("#c-delete").onclick = guard(async () => {
    if (!(await uiConfirm(`Delete ${p.name}? The profile, 3D model, preview, backups and reference voice move to assets/characters/.trash (nothing is destroyed). Videos already made keep their mp4; re-rendering one that used ${p.name} would use the active character instead.`,
      { title: "Delete character", ok: "🗑 Delete", danger: true }))) return;
    const r = await api("DELETE", `/api/characters/${p.id}`);
    await refreshMeta();
    CHAR_SEL = null;
    toast(`${p.name} moved to the trash (${r.moved.length} files)`);
    pageCharacters();
  });
  if ($("#activate")) $("#activate").onclick = guard(async () => { await save(); await api("POST", `/api/characters/${p.id}/activate`); await refreshMeta(); toast(`${p.name} is now the active character`); pageCharacters(); });
  $("#c-test").onclick = guard(async () => {
    await save();
    const job = await api("POST", `/api/characters/${p.id}/say`, { text: $("#c-say").value });
    watchJob(job, $("#c-voice-job"), (j) => {
      if (j.status === "done") $("#c-voice-job").insertAdjacentHTML("beforeend", `<audio controls autoplay src="${esc(j.result.audio)}" style="width:100%;margin-top:8px"></audio>`);
    });
  });
  $("#c-vrm").onchange = guard(async (e) => {
    const f = e.target.files[0]; if (!f) return;
    await save();
    toast(`Uploading ${f.name}…`);
    const job = await api("POST", `/api/characters/${p.id}/model`, undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    watchJob(job, $("#c-import"), (j) => {
      if (j.status === "done") { toast("Model imported!"); pageCharacters(); } else toast("Import failed - see the log", true);
    });
  });
}

/* ------------------------------------------------------------------ SETTINGS */
const S_TABS = {
  look: ["🎨 Look", [
    ["Pixels", [
      ["render.width", "Render width", "range", { min: 144, max: 432, step: 24 }, "Internal resolution. Lower = chunkier pixels (needs a full render)."],
      ["render.height", "Render height", "range", { min: 256, max: 768, step: 32 }, "Keep 9:16 with the width (216×384, 288×512…)."],
      ["look.sharp_pixels", "Razor-sharp pixels", "bool", {}, "Turns off the softness for crisp PS1-style pixels."],
      ["look.blur", "Pixel softness", "range", { min: 0, max: 4, step: 0.1 }, "Blur after the pixel upscale."],
      ["look.color_bits", "Colour depth (bits)", "range", { min: 2, max: 8, step: 1 }, "5 = N64-style 15-bit colour, 8 = full colour."],
      ["look.dither", "Dithering", "bool", {}, "Checkerboard dithering when reducing colours."],
    ]],
    ["Colour", [
      ["look.tint", "Colour tint", "select", { options: () => META.tints }],
      ["look.saturation", "Saturation", "range", { min: 0, max: 1.6, step: 0.02 }],
      ["look.contrast", "Contrast", "range", { min: 0.5, max: 1.5, step: 0.02 }],
      ["look.black", "Black level (R G B)", "triple", { min: 0, max: 0.5, step: 0.01 }, "Raises the darkest colour - washed-out VHS feel."],
      ["look.white", "White level (R G B)", "triple", { min: 0.5, max: 1, step: 0.01 }],
    ]],
    ["Effects", [
      ["look.fringe", "Colour fringing", "range", { min: 0, max: 12, step: 1 }, "Red/blue edge offset."],
      ["look.bloom", "Glow / bloom", "range", { min: 0, max: 1, step: 0.05 }],
      ["look.grain", "Film grain", "range", { min: 0, max: 30, step: 1 }],
      ["look.scanlines", "Scanlines", "bool"],
      ["look.vignette", "Vignette", "bool"],
    ]],
  ]],
  text: ["🔤 Text & branding", [
    ["Captions", [
      ["captions.mode", "Caption style", "select", { options: ["words", "line", "off"] }, "words = a few words at a time mid-screen (how many: the Create page's caption style), line = the whole line."],
      ["captions.font", "Font", "font", {}, "Any font installed in Windows."],
      ["captions.effect", "Entrance effect", "select", { options: () => META.effects }],
      ["captions.color", "Text colour", "color"],
      ["captions.shadow_color", "Shadow / outline colour", "color"],
      ["captions.outline", "Outline (0 = drop shadow)", "range", { min: 0, max: 3, step: 1 }],
      ["captions.size", "Caption size", "range", { min: 0.03, max: 0.12, step: 0.005 }],
      ["captions.position", "Caption height from bottom", "range", { min: 0.05, max: 0.7, step: 0.01 }],
      ["captions.uppercase", "UPPERCASE text", "bool"],
    ]],
    ["Title", [
      ["captions.title_color", "Title line 1 colour", "color"],
      ["captions.title_color2", "Title line 2 colour", "color"],
      ["captions.title_size", "Title size", "range", { min: 0.02, max: 0.08, step: 0.005 }],
      ["captions.title_seconds", "Title shown for (s)", "range", { min: 1, max: 10, step: 0.5 }],
    ]],
    ["Branding", [
      ["branding.watermark", "Watermark", "text", { placeholder: "@yourhandle" }, "Small text in a corner for the whole video."],
      ["branding.watermark_corner", "Watermark corner", "select", { options: ["bottom-right", "bottom-left", "top-right", "top-left"] }],
      ["branding.end_text", "End card text", "text", { placeholder: "FOLLOW FOR MORE" }, "Shown over the last seconds."],
      ["branding.end_seconds", "End card length (s)", "range", { min: 1, max: 5, step: 0.5 }],
    ]],
  ]],
  audio: ["🎵 Render & audio", [
    ["Render", [["language", "Video language", "select", { options: () => Object.keys(META.catalog.languages || { en: 1 }), labels: () => META.catalog.languages || {} },
        "The language of finished videos (voice, captions, title, end card). Scripts are still written in English. Each video can pick its own on the Create page."],
      ["render.fps", "Frame rate", "select", { options: [12, 15, 20, 24, 30] }, "30 = smooth; 15 = choppy retro."],
      ["render.crf", "Video file quality (CRF)", "range", { min: 16, max: 26, step: 1 }, "Lower = sharper but bigger files. 20 is a good balance for uploads; 18 was the old setting (about 1.5x bigger)."]]],
    ["Start & end", [
      ["audio.intro", "Intro before first line (s)", "range", { min: 0, max: 3, step: 0.1 }, "Calm moment at the start - she idles, the title shows."],
      ["audio.outro", "Hold after last line (s)", "range", { min: 0, max: 4, step: 0.1 }, "Lets the last reaction land before the video ends."],
      ["audio.fade", "Fade in/out (s)", "range", { min: 0, max: 1.5, step: 0.05 }, "Picture and sound fade at the very start and end."],
    ]],
    ["Audio", [
      ["audio.lead", "Pause before each line (s)", "range", { min: 0, max: 1, step: 0.05 }],
      ["audio.tail_pad", "Pause after each line (s)", "range", { min: 0, max: 2, step: 0.05 }],
      ["audio.default_music", "Default music", "music", {}, "Used when an episode doesn't pick its own. Manage tracks on Assets → Music."],
      ["audio.music_volume", "Music volume", "range", { min: 0, max: 0.5, step: 0.01 }, "0.05 = 5%."],
      ["audio.music_fade", "Music fade in/out (s)", "range", { min: 0, max: 4, step: 0.1 }],
      ["sfx.auto", "Automatic sound effects", "bool", {}, "Effects from trigger words and actions. Manage sounds on Assets → Sounds."],
      ["sfx.volume", "Sound effects volume", "range", { min: 0, max: 1, step: 0.05 }],
      ["sfx.ambience_volume", "Ambience volume", "range", { min: 0, max: 1, step: 0.05 }],
    ]],
  ]],
  voice: ["🗣 Default voice", null],
  phone: ["📱 Phone & network", [
    ["Access", [
      ["server.pin", "PIN for other devices", "text", { placeholder: "e.g. 2468 (empty = no PIN)" }, "Phones and tablets must enter this once. This PC never needs it."],
    ]],
  ]],
  postiz: ["📤 Postiz", [
    ["Your Postiz", [
      ["postiz.url", "Postiz address", "text", { placeholder: "https://social.example.com" }, "Your self-hosted Postiz (or https://api.postiz.com for Postiz Cloud)."],
      ["postiz.api_key", "API key", "password", {}, "Postiz → Settings → Developers. Stored only on this PC; never shown again here."],
    ]],
    ["Drafts", [
      ["postiz.extra_hashtags", "Always add these hashtags", "text", { placeholder: "#catgirl #animation" }, "Added to the AI's topic hashtags (plus each platform's trending ones like #fyp / #shorts)."],
      ["postiz.youtube_privacy", "YouTube visibility", "select", { options: ["public", "unlisted", "private"] }],
      ["postiz.made_with_ai", "Label as made with AI", "bool", {}, "Sets the platforms' AI-content label on the drafts."],
    ]],
  ]],
  ai: ["🤖 AI tools", [
    ["Ollama (script & title writing)", [
      ["ollama.url", "Server URL", "text"],
      ["ollama.model", "Default model", "ollamapick", { from: "ollama.url" }, "The models your Ollama has (🔄 after changing the address)."],
      ["ollama.design_url", "Big model server", "text", { placeholder: "empty = the server above" }, "Another Ollama with bigger models (e.g. a stronger computer on your network). If it can't be reached, the server above is used."],
      ["ollama.design_model", "Model on the big server", "ollamapick", { from: "ollama.design_url", big: true, first: "Same as the default model" }, "The models that server already has (🔄 after changing the address). Nothing is ever downloaded there."],
      ["ollama.design_scope", "Use the big server for", "select", { options: ["3d", "text"], labels: { "3d": "Only building 3D props & explainer models", text: "All the AI's writing too (scripts, titles, sets, cast, translations, captions)" } }, "Picture checks, drawings and voices always run on this PC."],
      ["ollama.temperature", "Creativity", "range", { min: 0.1, max: 1.5, step: 0.05 }, "Higher = wilder ideas."],
      ["sets.use_ollama", "Ollama designs new sets & sounds", "bool", {}, "Off = sets and generated sounds are rolled purely at random."],
      ["sets.look_check", "Check that new sets look like the place", "bool", {}, "The picture model looks at each new set and the AI fixes ones that read as another place (adds a few minutes)."],
      ["sets.prop_check", "Check that new props look right", "bool", {}, "Each new prop is looked at; one that fails is rebuilt, then drawn as a picture (about a minute per new prop)."],
    ]],
    ["ComfyUI (set textures, prop pictures, music)", [
      ["comfy.mode", "Use ComfyUI", "select", { options: ["required", "auto", "off"], labels: { required: "Required - always texture sets (floor, walls/sky, pictures)", auto: "Only when needed - just picture props", off: "Off - never" } }],
      ["comfy.url", "Server URL", "text", {}, "ComfyUI's address (ComfyUI Desktop uses port 8666; 8188 and others are tried too)."],
      ["comfy.checkpoint", "Checkpoint", "comfyckpt", {}, "Empty = first available."],
      ["comfy.steps", "Steps", "range", { min: 8, max: 40, step: 1 }, "For classic checkpoints. Z-Image Turbo always uses 8 steps."],
      ["comfy.cfg", "CFG", "range", { min: 2, max: 12, step: 0.5 }, "For classic checkpoints. Z-Image Turbo always uses CFG 1."],
      ["comfy.texture_size", "Texture size (px)", "select", { options: [64, 128, 256] }, "Smaller = more N64."],
      ["comfy.style", "Style words added to every prompt", "text"],
    ]],
  ]],
};
let S_TAB = "look";
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
const setPath = (o, p, v) => { const ks = p.split("."); const last = ks.pop(); ks.reduce((a, k) => (a[k] ??= {}), o)[last] = v; };

async function pageSettings() {
  const st = await api("GET", "/api/settings");
  const eps = (await api("GET", "/api/episodes")).filter((e) => e.video);
  app.innerHTML = `<div class="grid2"><div>
    <div class="tabs">${Object.entries(S_TABS).map(([k, [label]]) => `<button class="tab ${k === S_TAB ? "on" : ""}" data-stab="${k}">${label}</button>`).join("")}</div>
    <div id="s-body"></div>
    <div class="btns"><button class="primary" id="s-save">💾 Save settings</button><button id="s-reset">Reset to defaults</button></div>
    </div><div class="side">
    <div class="panel"><h3>Free up disk space</h3><div id="s-disk" class="small"><span class="muted">Measuring…</span></div></div>
    <div class="panel"><h3>Restart the app</h3><p class="muted small">Starts the app again with the same settings and loads new code. Anything still running stops.</p>
      <button id="s-restart">🔄 Restart the app</button><div id="s-restart-msg" class="muted small" style="margin-top:6px"></div></div>
    <div class="panel"><h3>Preview the look</h3><p class="muted small">Saves settings, then re-applies the look, captions and branding to an already-rendered episode (fast - no 3D render). Render size and frame rate need a full render.</p>
      <div class="row"><label>Episode<select id="s-ep">${eps.map((e) => `<option value="${esc(e.id)}">${esc(e.title || e.id)}</option>`).join("")}</select></label>
      <button id="s-preview" ${eps.length ? "" : "disabled"}>▶ Preview</button></div>
      <div id="s-job"></div><div id="s-result" style="margin-top:10px"></div></div></div></div>`;
  $$("[data-stab]").forEach((b) => b.onclick = () => { S_TAB = b.dataset.stab; $$("[data-stab]").forEach((x) => x.classList.toggle("on", x === b)); drawSettingsTab(st); });
  drawDisk();
  drawSettingsTab(st);
  const save = async () => { META.settings = await api("PUT", "/api/settings", st); };
  $("#s-save").onclick = guard(async () => { await save(); toast("Settings saved"); });
  $("#s-restart").onclick = guard(async () => {
    const msg = $("#s-restart-msg");
    try { await api("POST", "/api/server/restart", {}); }
    catch (e) {                                    // jobs still running: ask before stopping them
      if (!(await uiConfirm(`${e.message}`, { title: "Restart the app", ok: "Restart anyway", danger: true }))) return;
      await api("POST", "/api/server/restart", { force: true });
    }
    msg.textContent = "Restarting… this page reloads when the app is back.";
    await new Promise((res) => setTimeout(res, 3000));     // give the old copy time to stop
    for (let i = 0; i < 60; i++) {
      try { const m = await fetch("/api/meta", { cache: "no-store" }); if (m.ok) { location.reload(); return; } } catch { /* not back yet */ }
      await new Promise((res) => setTimeout(res, 1000));
    }
    msg.textContent = "The app didn't come back - start it again by hand (start-studio.bat).";
  });
  $("#s-reset").onclick = guard(async () => {
    if (!(await uiConfirm("Every setting goes back to its default. Your active character, the Postiz connection and the phone PIN are kept.", { title: "Reset ALL settings?", ok: "Reset everything", danger: true }))) return;
    const d = { ...JSON.parse(JSON.stringify(META.defaults)), active_character: st.active_character,
      postiz: st.postiz, server: st.server };
    META.settings = await api("PUT", "/api/settings", d); toast("Defaults restored"); pageSettings();
  });
  $("#s-preview").onclick = guard(async () => {
    await save();
    const job = await api("POST", "/api/render", { id: $("#s-ep").value, reuse_frames: true });
    watchJob(job, $("#s-job"), (j) => {
      if (j.status === "done") $("#s-result").innerHTML = `<video class="preview" src="${esc(j.result.video)}?t=${Date.now()}" controls autoplay muted playsinline></video>`;
    });
  });
}

const fmtBytes = (b) => b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${Math.round(b / 1e6)} MB` : `${Math.round(b / 1e3)} KB`;
const DISK_ACTION = { delete: ["🗑 Delete", "Delete these for good?"], trash: ["Move to trash", "Move these to the trash?"],
  empty: ["🗑 Empty the trash", "Empty every trash folder for good?"] };
async function drawDisk() {
  const box = $("#s-disk");
  if (!box) return;
  let d;
  try { d = await api("GET", "/api/storage"); } catch (e) { box.innerHTML = `<span class="err">${esc(e.message)}</span>`; return; }
  box.innerHTML = d.groups.map((g) => `<div style="padding:6px 0;border-bottom:1px dashed var(--line)">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b style="flex:1">${esc(g.label)}</b>
        <span class="mono">${fmtBytes(g.bytes)}</span>
        ${g.action && g.bytes ? `<button data-clean="${g.key}" class="${g.action === "trash" ? "" : "danger"}">${DISK_ACTION[g.action][0]}</button>` : ""}</div>
      <div class="muted">${esc(g.note)}${(g.parts || []).length ? "<br>" + g.parts.map((p) => `${esc(p.path)}: ${fmtBytes(p.bytes)}`).join(" · ") : ""}</div></div>`).join("")
    + `<p class="muted" style="margin:6px 0 0">Total: ${fmtBytes(d.total)}</p>`;
  $$("[data-clean]", box).forEach((b) => b.onclick = guard(async () => {
    const g = d.groups.find((x) => x.key === b.dataset.clean);
    if (!(await uiConfirm(`${g.label}: ${fmtBytes(g.bytes)} (${g.files} files).\n\n${g.note}`,
      { title: DISK_ACTION[g.action][1], ok: DISK_ACTION[g.action][0], danger: g.action !== "trash" }))) return;
    const r = await busy(b, "Working…", () => api("POST", "/api/storage/clean", { what: g.key }));
    toast(g.action === "trash" ? "Moved to the trash" : `Freed ${fmtBytes(r.freed)}`);
    drawDisk();
  }));
}

function phoneHelp() {
  const n = META.network || {};
  const urls = (n.urls || []).map((u) => `<code style="font-size:15px">${esc(u)}</code>`).join("<br>");
  return `<div class="panel"><h3>Use it on your phone</h3>
    ${n.lan ? `<p>On your phone (same Wi-Fi), open:<br>${urls || "<span class='warn'>no network address found</span>"}</p>`
            : `<p class="warn">The app is only open to this PC right now. Start it with <code>python web/server.py --lan</code> to reach it from your phone.</p>`}
    <h3 style="margin-top:14px">Add it to your home screen (iPhone)</h3>
    <ol class="small" style="padding-left:18px;margin:0;line-height:1.7">
      <li>Open the address above in <b>Safari</b>.</li>
      <li>Tap the <b>Share</b> button (square with an arrow).</li>
      <li>Choose <b>Add to Home Screen</b> → <b>Add</b>.</li>
      <li>It opens full screen with the Low Poly icon, like an app.</li></ol>
    <p class="muted small" style="margin-top:10px">Android/Chrome: menu ⋮ → <b>Add to Home screen</b> / <b>Install app</b>.
      If the phone can't connect, allow Python through the Windows firewall for this network (see the README).</p></div>`;
}

function drawSettingsTab(st) {
  const body = $("#s-body");
  const [, groups] = S_TABS[S_TAB];
  if (!groups) {   // default voice
    body.innerHTML = `<div class="panel"><h3>Default voice</h3><p class="muted small">Used by characters that don't set their own voice.</p><div id="s-voice"></div></div>`;
    voiceEditor($("#s-voice"), st.voice, () => {});
    return;
  }
  const row = ([key, label, type, o = {}, help]) => {
    const v = getPath(st, key);
    let input = "", val = "<span></span>";
    const opts = typeof o.options === "function" ? o.options() : o.options;
    if (type === "range") { input = `<input type="range" data-key="${key}" min="${o.min}" max="${o.max}" step="${o.step}" value="${v}">`; val = `<span class="val mono">${v}</span>`; }
    else if (type === "bool") input = `<label class="check"><input type="checkbox" data-key="${key}" ${v ? "checked" : ""}> on</label>`;
    else if (type === "select") input = `<select data-key="${key}">${options(opts.map(String), String(v), (typeof o.labels === "function" ? o.labels() : o.labels) || {})}</select>`;
    else if (type === "text") input = `<input type="text" data-key="${key}" value="${esc(v)}" placeholder="${esc(o.placeholder || "")}">`;
    else if (type === "password") input = `<input type="password" data-key="${key}" value="${esc(v || "")}" autocomplete="off" placeholder="${v ? "" : "paste your key"}">${v === "__saved__" ? '<span class="pill ok">saved</span>' : ""}`;
    else if (type === "color") { input = `<input type="color" data-key="${key}" value="${esc(v)}">`; val = `<span class="val mono">${esc(v)}</span>`; }
    else if (type === "font") input = `<input type="text" data-key="${key}" list="font-list" value="${esc(v)}"><datalist id="font-list"></datalist>`;
    else if (type === "music") input = `<select data-key="${key}" data-async="music"><option value="${esc(v)}">${esc(v || "None")}</option></select>`;
    else if (type === "ollama") input = `<select data-key="${key}" data-async="ollama"><option>${esc(v)}</option></select>`;
    else if (type === "ollamapick") input = `<div class="om-pick"><div class="row" style="gap:6px;align-items:center">
        <select data-key="${key}" data-async="ollamapick" data-from="${esc(o.from)}" ${o.big ? 'data-big="1"' : ""} data-first="${esc(o.first || "")}" style="flex:1"><option value="${esc(v)}">${esc(v || o.first || "")}</option></select>
        <button type="button" class="om-refresh" title="Look again at the server's models">🔄</button></div><div class="om-status small" style="margin-top:4px"></div></div>`;
    else if (type === "comfyckpt") input = `<select data-key="${key}" data-async="ckpt"><option value="${esc(v)}">${esc(v || "First available")}</option></select>`;
    else if (type === "triple") input = `<div class="triple">${[0, 1, 2].map((i) => `<input type="number" data-key="${key}" data-idx="${i}" min="${o.min}" max="${o.max}" step="${o.step}" value="${v[i]}">`).join("")}</div>`;
    return `<div class="setting"><label style="color:var(--text);font-size:13px">${esc(label)}</label>${input}${val}${help ? `<div class="help muted small">${esc(help)}</div>` : ""}</div>`;
  };
  body.innerHTML = (S_TAB === "look" ? `<div class="panel"><h3>Presets</h3><div class="presets">${Object.keys(META.presets).map((p) => `<button data-preset="${esc(p)}">${esc(p)}</button>`).join("")}</div>
      <p class="muted small" style="margin:0">A preset fills in the values below - tweak anything, then Save. Episodes can also pick a preset on the Create page.</p></div>` : "")
    + groups.map(([g, rows]) => `<div class="panel"><h3>${esc(g)}</h3>${rows.map(row).join("")}</div>`).join("")
    + (S_TAB === "ai" ? `<div class="panel"><div class="btns" style="margin:0"><button id="t-ollama">Test Ollama</button><button id="t-comfy">Check ComfyUI</button></div><div id="t-out" class="small" style="margin-top:8px"></div></div>` : "")
    + (S_TAB === "phone" ? phoneHelp() : "")
    + (S_TAB === "postiz" ? `<div class="panel"><h3>Channels</h3><p class="muted small" style="margin-top:0">Tick where drafts should go. Save your address and key first, then load the channels.</p>
        <div class="btns" style="margin:0"><button id="pz-load">🔄 Load channels from Postiz</button></div><div id="pz-chans" style="margin-top:8px"></div></div>` : "");

  $$("[data-preset]", body).forEach((b) => b.onclick = () => { st.look = { ...st.look, ...JSON.parse(JSON.stringify(META.presets[b.dataset.preset])) }; drawSettingsTab(st); toast(`${b.dataset.preset} applied - Save to keep it`); });
  $$("[data-key]", body).forEach((el) => el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", () => {
    const key = el.dataset.key;
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "range" || el.type === "number" || ["render.fps", "comfy.texture_size"].includes(key)) v = Number(v);
    if (el.dataset.idx !== undefined) { const arr = [...getPath(st, key)]; arr[+el.dataset.idx] = v; v = arr; }
    setPath(st, key, v);
    const val = el.closest(".setting")?.querySelector(".val");
    if (val) val.textContent = el.value;
  }));
  // Postiz channels
  const pzl = $("#pz-load", body);
  if (pzl) {
    const draw = (r) => {
      const box = $("#pz-chans", body);
      if (!r.ok) { box.innerHTML = `<p class="small"><span class="pill err">not connected</span> ${esc(r.error || "")}</p>`; return; }
      st.postiz.channels = st.postiz.channels || {};
      box.innerHTML = r.channels.map((c) => {
        const cur = st.postiz.channels[c.id] || {};
        return `<div class="pz-chan"><label class="check"><input type="checkbox" data-pz="${esc(c.id)}" ${cur.enabled ? "checked" : ""} ${c.disabled ? "disabled" : ""}>
          ${c.picture ? `<img src="${esc(c.picture)}" alt="">` : ""} <b>${esc(c.name)}</b> <span class="muted small">${esc(c.identifier)}${c.disabled ? " · disabled in Postiz" : ""}</span></label>
          ${c.platform === "discord" ? `<input type="text" data-pzdc="${esc(c.id)}" placeholder="Discord channel ID (right-click the channel → Copy Channel ID)" value="${esc(cur.discord_channel || "")}">` : ""}</div>`;
      }).join("") || '<p class="muted small">No channels connected in Postiz yet.</p>';
      $$("[data-pz]", box).forEach((cb) => cb.onchange = () => { const k = cb.dataset.pz; st.postiz.channels[k] = { ...(st.postiz.channels[k] || {}), enabled: cb.checked }; });
      $$("[data-pzdc]", box).forEach((inp) => inp.oninput = () => { const k = inp.dataset.pzdc; st.postiz.channels[k] = { ...(st.postiz.channels[k] || {}), discord_channel: inp.value.trim() }; });
    };
    pzl.onclick = guard(async (e) => busy(e.currentTarget, "Loading…", async () => {
      await api("PUT", "/api/settings", st);           // the server needs the address/key to ask Postiz
      draw(await api("GET", "/api/postiz/channels"));
    }));
    if (st.postiz?.url && st.postiz?.api_key) api("GET", "/api/postiz/channels").then(draw);
  }
  // async option lists
  const fl = $("#font-list", body);
  if (fl) api("GET", "/api/fonts").then((fs) => { fl.innerHTML = fs.map((f) => `<option value="${esc(f)}">`).join(""); });
  const ms = $("[data-async=music]", body);
  if (ms) api("GET", "/api/music").then((list) => { ms.innerHTML = `<option value="">None</option>` + options(list.map((m) => m.path), getPath(st, ms.dataset.key), Object.fromEntries(list.map((m) => [m.path, m.name]))); });
  const oms = [...body.querySelectorAll("[data-async=ollama]")];
  if (oms.length) api("GET", "/api/ollama/models").then((r) => {
    if (!r.ok) return;
    for (const om of oms) {
      const first = om.dataset.key === "ollama.model" ? "" : `<option value="">Same as the default model</option>`;
      om.innerHTML = first + options(r.models.map((m) => m.name), getPath(st, om.dataset.key));
    }
  });
  // the models a server already has (the address typed in its box, saved or not), with a plain
  // "connected" / "why not" line under them and 🔄 to look again - for this PC's Ollama and the big model server
  for (const pk of $$("[data-async=ollamapick]", body)) {
    const wrap = pk.closest(".om-pick"), stat = $(".om-status", wrap);
    const load = async () => {
      const cur = pk.value, url = ($(`[data-key="${pk.dataset.from}"]`, body)?.value || "").trim();
      stat.innerHTML = url ? '<span class="muted">Looking…</span>' : '<span class="muted">Type the server&#39;s address above to see its models.</span>';
      if (!url) return;
      const r = await api("GET", `/api/ollama/models${pk.dataset.big ? "/big" : ""}?url=` + encodeURIComponent(url)).catch((e) => ({ ok: false, error: e.message }));
      const names = r.ok ? r.models.map((m) => m.name) : [];
      const extra = cur && !names.includes(cur) ? `<option value="${esc(cur)}" selected>⚠ ${esc(cur)}${r.ok ? " (not on that server)" : ""}</option>` : "";
      pk.innerHTML = (pk.dataset.first ? `<option value="">${esc(pk.dataset.first)}</option>` : "") + extra
        + options(names, cur, Object.fromEntries((r.models || []).map((m) => [m.name, `${m.name}  (${m.params || m.size_gb + " GB"})`])));
      stat.innerHTML = r.ok ? `<span class="ok">✓ Connected - ${names.length} model${names.length === 1 ? "" : "s"}</span>`
        + (extra && r.ok ? ' <span class="err">- pick one of its models</span>' : "")
        : `<span class="err">✗ ${esc(r.error)}</span>`;
    };
    load();
    $(".om-refresh", wrap).onclick = guard(load);
    $(`[data-key="${pk.dataset.from}"]`, body)?.addEventListener("change", load);
  }
  const ck = $("[data-async=ckpt]", body);
  if (ck) api("GET", "/api/comfy/status").then((r) => { if (r.ok) ck.innerHTML = `<option value="">First available</option>` + options(r.checkpoints, getPath(st, "comfy.checkpoint")); });
  if ($("#t-ollama")) {
    $("#t-ollama").onclick = guard(async () => {
      await api("PUT", "/api/settings", st);
      const r = await api("GET", "/api/ollama/models");
      $("#t-out").innerHTML = r.ok ? `<span class="ok">Ollama OK - ${r.models.length} chat models.</span>` : `<span class="err">${esc(r.error)}</span>`;
    });
    $("#t-comfy").onclick = guard(async () => {
      await api("PUT", "/api/settings", st);
      const r = await api("GET", "/api/comfy/status");
      $("#t-out").innerHTML = r.ok ? `<span class="ok">ComfyUI OK - ${esc((r.devices || []).join(", "))}; ${r.checkpoints.length} checkpoints.</span>` : `<span class="err">${esc(r.error)}</span> <span class="muted">Start ComfyUI, then check again. Sets still generate fine without it.</span>`;
    });
  }
}


/* ------------------------------------------------------------------ dialogs (used site-wide instead of prompt/confirm) */
function openModal({ title, body = "", wide = false, buttons = [], onOpen } = {}) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head"><h3>${esc(title)}</h3><button class="modal-x" aria-label="Close" title="Close (Esc)">✕</button></div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot">${["left", "right"].map((side) => `<div class="foot-${side}">${buttons.map((b, i) => ((side === "left") === !!b.left)
        ? `<button data-mb="${i}" class="${b.primary ? "primary" : ""} ${b.danger ? "danger" : ""}">${b.label}</button>` : "").join("")}</div>`).join("")}</div></div>`;
    document.body.appendChild(wrap);
    document.body.classList.add("modal-open");
    const m = $(".modal", wrap);
    let done = false;
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(null); }
      if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "range") {
        const p = buttons.findIndex((b) => b.primary);
        if (p >= 0) { e.preventDefault(); $(`[data-mb="${p}"]`, wrap).click(); }
      }
    };
    function close(value) {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", onKey);
      wrap.classList.add("closing");
      setTimeout(() => { wrap.remove(); if (!$(".modal-wrap")) document.body.classList.remove("modal-open"); }, 140);
      resolve(value);
    }
    document.addEventListener("keydown", onKey);
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(null); });
    $(".modal-x", wrap).onclick = () => close(null);
    buttons.forEach((b, i) => {
      $(`[data-mb="${i}"]`, wrap).onclick = async (ev) => {
        if (!b.onClick) return close(b.value === undefined ? i : b.value);
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          const r = await b.onClick(m, close);
          if (r !== false && !done && b.closes !== false) close(r === undefined ? (b.value === undefined ? i : b.value) : r);
        } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
      };
    });
    if (onOpen) onOpen(m, close);
    setTimeout(() => (m.querySelector("[autofocus]") || m.querySelector(".modal-body input:not([type=range]):not([type=color]), .modal-body textarea") || m.querySelector(".primary"))?.focus(), 40);
  });
}
const uiConfirm = (message, { title = "Are you sure?", ok = "OK", danger = false } = {}) =>
  openModal({ title, body: `<p class="modal-msg">${esc(message).replace(/\n/g, "<br>")}</p>`,
    buttons: [{ label: "Cancel", value: false }, { label: ok, primary: !danger, danger, value: true }] }).then((v) => v === true);
const uiPrompt = (title, { label = "", value = "", placeholder = "", multiline = false, ok = "Save" } = {}) =>
  openModal({ title,
    body: `<label class="modal-field">${esc(label)}${multiline
      ? `<textarea rows="3" data-pv placeholder="${esc(placeholder)}">${esc(value)}</textarea>`
      : `<input type="text" data-pv value="${esc(value)}" placeholder="${esc(placeholder)}">`}</label>`,
    buttons: [{ label: "Cancel", value: null }, { label: ok, primary: true, onClick: (m) => $("[data-pv]", m).value.trim() || null }] });

/* ------------------------------------------------------------------ ASSETS */
let AS_TAB = "props", AS_Q = "", AS_FILTER = "all";
const ON_ICON = { floor: "🧍 floor", table: "🍽 table", wall: "🖼 wall" };

async function pageAssets(tab) {
  if (tab) AS_TAB = tab;
  const [props, fx, music, imp, actors, anims] = await Promise.all([api("GET", "/api/assets/props"), api("GET", "/api/assets/fx"), api("GET", "/api/music"), api("GET", "/api/imported"), api("GET", "/api/actors"), api("GET", "/api/anims")]);
  const nSfx = Object.keys(META.sfx || {}).length;
  const nImp = imp.packs.reduce((n, p) => n + p.models.length, 0);
  // a made prop is a 3D model OR a 2D sprite, never both (propgen.shown_as_sprite): two tabs
  const props3d = props.filter((p) => p.form === "3d"), sprites = props.filter((p) => p.form === "sprite");
  const tabs = [["props", "🧊", "Props (3D)", props3d.length], ["sprites", "🖼", "Sprites (2D)", sprites.length], ["imported", "📦", "Imported", nImp], ["actors", "🧍", "Actors", actors.actors.length],
                ["anims", "🕺", "Animations", anims.filter((a) => !a.builtin).length], ["fx", "✨", "Effects", fx.length], ["music", "🎵", "Music", music.length], ["sfx", "🔊", "Sounds", nSfx]];
  app.innerHTML = `
    <div class="assets-head">
      <div><h2>Assets</h2><p class="muted small">Everything the studio made for you or you added - 3D props and 2D sprites for your sets and scripts, particle effects, music and sounds.</p></div>
    </div>
    <div class="seg" role="tablist">${tabs.map(([k, ic, label, n]) => `<button role="tab" class="seg-btn ${k === AS_TAB ? "on" : ""}" data-astab="${k}"><span class="seg-ic">${ic}</span>${label}<span class="seg-n">${n}</span></button>`).join("")}</div>
    <div id="as-body"></div>`;
  $$("[data-astab]").forEach((b) => b.onclick = () => { AS_TAB = b.dataset.astab; location.hash = "#assets"; pageAssets(); });
  const body = $("#as-body");
  if (AS_TAB === "props") return assetsProps(body, props3d, "3d");
  if (AS_TAB === "sprites") return assetsProps(body, sprites, "sprite");
  if (AS_TAB === "imported") return assetsImported(body);
  if (AS_TAB === "actors") return assetsActors(body, actors);
  if (AS_TAB === "anims") return assetsAnims(body, anims);
  if (AS_TAB === "fx") return assetsFx(body, fx);
  A_TAB = AS_TAB === "sfx" ? "sfx" : "music";
  return A_TAB === "music" ? audioMusic(body) : audioSfx(body);
}

/* ---- animations (pipeline/animlib.py + animgen.py): made by the AI when a script asks for one, or here */
JOB_ICON.anim = "🕺";
function assetsAnims(box, anims) {
  const own = anims.filter((a) => !a.builtin);
  const card = (a) => {
    const st = a.checked ? `<span class="chip good">✓ ${a.score ? a.score + "/10" : "checked"}</span>`
      : a.checked === false ? `<span class="chip warn" title="${esc(a.problem || "")}">⚠ ${a.score ? a.score + "/10" : "not confirmed"}</span>`
      : `<span class="chip dim">unchecked</span>`;
    return `<div class="asset-card" style="cursor:default">
      <div class="asset-thumb checker" style="aspect-ratio:9/4">${a.picture ? `<img src="${esc(a.picture)}" alt="${esc(a.name)}" loading="lazy" style="max-width:100%;max-height:100%">` : `<div class="asset-noimg"><span>🕺</span><small>no picture</small></div>`}</div>
      <div class="asset-actions"><button data-an-del="${esc(a.name)}" title="Delete">🗑</button></div>
      <div class="asset-info"><div class="asset-name">${esc(a.name.replace(/_/g, " "))}</div>
        <div class="asset-meta">${st}<span class="chip">${a.length}s${a.loop ? " · loops" : ""}</span>${a.by === "ai" ? '<span class="chip">AI</span>' : ""}</div>
        <div class="muted small">${esc(a.description)}</div>
        ${a.checked === false && a.problem ? `<div class="muted small">Checker: ${esc(a.problem)}</div>` : ""}</div></div>`;
  };
  box.innerHTML = `
    <div class="asset-toolbar"><p class="muted small" style="margin:0;flex:1">Actions she learned. When a script asks for one she can't do yet
      (<code>[salute]</code> or <code>[do:salute]</code>), the AI makes it from poses that are known to look right, renders a quick check and has the
      picture model look at it - about half a minute to two minutes, then every video reuses it. Write <code>[salute]</code> in a script to use one.</p></div>
    <div class="panel"><h3 style="margin-top:0">Make an animation</h3>
      <div class="row" style="align-items:end">
        <label style="flex:1">Name<input type="text" id="an-name" placeholder="e.g. salute"></label>
        <label style="flex:3">What she does (optional)<input type="text" id="an-desc" placeholder="e.g. salutes like a soldier, right hand to the forehead"></label>
      </div>
      <div class="btns"><button class="primary" id="an-go">🕺 Make it</button></div>
      <div class="inline-job" id="an-job"></div></div>
    <div class="asset-grid" style="margin-top:12px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">
      ${own.length ? own.map(card).join("") : '<div class="empty"><div class="empty-ic">🕺</div>No animations yet - they appear here when a script asks for one, or make one above.</div>'}</div>`;
  $("#an-go").onclick = guard(async () => {
    const name = $("#an-name").value.trim();
    if (!name) throw new Error("Give it a name first");
    const job = await api("POST", "/api/anims/make", { name, description: $("#an-desc").value.trim() });
    toast("Making it - this takes a minute or two");
    watchJob(job, $("#an-job"), async (j) => {
      if (j.status !== "done") return toast("Couldn't make it - see the log", true);
      toast("Animation ready ✓");
      await pageAssets("anims");
    });
  });
  $$("[data-an-del]").forEach((b) => b.onclick = guard(async () => {
    if (!(await uiConfirm(`Delete the "${b.dataset.anDel}" animation? It moves to the animations trash folder.`, { title: "Delete animation", ok: "Delete", danger: true }))) return;
    await api("DELETE", `/api/anims/${encodeURIComponent(b.dataset.anDel)}`);
    toast("Deleted");
    await pageAssets("anims");
  }));
}

/* ---- props */
const propPic = (p) => (p.form === "sprite" ? p.sprite : p.preview3d);
function propCard(p) {
  const used = p.used_in.length;
  return `<div class="asset-card" data-prop="${esc(p.kind)}" tabindex="0" title="${esc(p.looks)}">
    <div class="asset-thumb checker">${propPic(p) ? `<img src="${esc(propPic(p))}" alt="${esc(p.name)}" loading="lazy">`
      : `<div class="asset-noimg"><span>${p.form === "3d" ? "🧊" : "🖼"}</span><small>${p.form === "3d" ? "3D model - picture after its next look check" : "not drawn yet"}</small></div>`}</div>
    <div class="asset-info">
      <div class="asset-name">${esc(titleCase(p.name))}</div>
      <div class="asset-meta">
        ${p.height ? `<span class="chip">↕ ${(+p.height).toFixed(p.height < 1 ? 2 : 1)} m</span>` : ""}
        <span class="chip">${ON_ICON[p.on] || p.on}</span>
        ${used ? `<span class="chip good">in ${used} set${used > 1 ? "s" : ""}</span>` : `<span class="chip dim">not in a set</span>`}
      </div>
    </div>
    <div class="asset-actions">
      <button data-pa="edit" title="View & edit">✏️</button>
      ${p.form === "sprite" ? '<button data-pa="redraw" title="Draw it again">🎨</button>' : ""}
      <button data-pa="del" class="danger" title="Delete">🗑</button>
    </div></div>`;
}

function assetsProps(box, props, form) {
  const filters = { all: "All", unused: "Not in a set" };
  if (!filters[AS_FILTER]) AS_FILTER = "all";
  const keep = (p) => (!AS_Q || `${p.kind} ${p.looks}`.toLowerCase().includes(AS_Q.toLowerCase()))
    && (AS_FILTER === "all" || (AS_FILTER === "unused" && !p.used_in.length));
  const missing = form === "sprite" ? props.filter((p) => !p.sprite).length : 0;
  box.innerHTML = `
    ${missing ? `<div class="panel" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
      <span style="flex:1">${missing} sprite${missing > 1 ? "s aren't" : " isn't"} drawn yet. New sprites get theirs automatically; this draws the rest.</span>
      <button class="primary" id="pr-missing">🎨 Draw ${missing} missing picture${missing > 1 ? "s" : ""}</button><div class="inline-job" id="pr-missing-job" style="width:100%"></div></div>` : ""}
    <div class="asset-toolbar">
      <div class="search"><span>🔍</span><input type="text" id="as-q" placeholder="Search ${form === "3d" ? "props" : "sprites"}…" value="${esc(AS_Q)}"></div>
      <div class="chips-row">${Object.entries(filters).map(([k, v]) => `<button class="chip-btn ${k === AS_FILTER ? "on" : ""}" data-af="${k}">${v}</button>`).join("")}</div>
      <span class="muted small" id="as-count"></span>
    </div>
    <div class="asset-grid" id="as-grid"></div>
    <p class="muted small asset-foot">${form === "3d"
      ? "3D props are built by the AI from simple shapes when a set or script needs one (your imported models are used first), then reused. Each is looked at by the picture model; one that doesn't look like the real thing becomes a 2D sprite."
      : "Sprites are flat 2D pictures drawn by ComfyUI - used only for things a 3D prop couldn't show well, or that you chose to draw."} Edits here apply to every set that uses it on its next render.</p>`;
  const draw = () => {
    const list = props.filter(keep);
    $("#as-count").textContent = `${list.length} of ${props.length}`;
    $("#as-grid").innerHTML = list.map(propCard).join("") || `<div class="empty"><div class="empty-ic">${form === "3d" ? "🧊" : "🖼"}</div><p>${props.length ? "Nothing matches."
      : form === "3d" ? "No 3D props yet - generate a set with an idea, or bring something into a script with +name." : "No sprites - every made prop is a 3D model so far."}</p></div>`;
    $$(".asset-card", $("#as-grid")).forEach((card) => {
      const p = props.find((x) => x.kind === card.dataset.prop);
      card.onclick = (e) => { if (!e.target.closest("button")) editProp(p); };
      card.onkeydown = (e) => { if (e.key === "Enter") editProp(p); };
      $("[data-pa=edit]", card).onclick = () => editProp(p);
      if ($("[data-pa=redraw]", card)) $("[data-pa=redraw]", card).onclick = () => redrawProp(p);
      $("[data-pa=del]", card).onclick = guard(() => deleteProp(p));
    });
  };
  $("#as-q").oninput = (e) => { AS_Q = e.target.value; draw(); };
  $$("[data-af]").forEach((b) => b.onclick = () => { AS_FILTER = b.dataset.af; $$("[data-af]").forEach((x) => x.classList.toggle("on", x === b)); draw(); });
  draw();
}

async function deleteProp(p) {
  const msg = p.used_in.length
    ? `“${titleCase(p.name)}” is used in ${p.used_in.length} set(s): ${p.used_in.map((s) => s.name).join(", ")}.\nThose sets keep their own copy, but new sets won't reuse it. It goes to assets/props/.trash.`
    : `Remove “${titleCase(p.name)}” from the prop library? It goes to assets/props/.trash.`;
  if (!(await uiConfirm(msg, { title: "Delete prop", ok: "🗑 Delete", danger: true }))) return false;
  await api("DELETE", `/api/props/${p.kind}`);
  toast(`Deleted ${titleCase(p.name)}`);
  pageAssets();
}

async function redrawProp(p, looks) {
  const desc = looks ?? await uiPrompt(`Redraw “${titleCase(p.name)}”`, { label: "Describe how it should look", value: p.looks, multiline: true, ok: "🎨 Redraw" });
  if (!desc) return false;
  const job = await api("POST", `/api/assets/props/${p.kind}/redraw`, { looks: desc });
  await openModal({ title: `Drawing ${titleCase(p.name)}…`, body: `<div class="inline-job" data-rj></div>`,
    buttons: [{ label: "Close", primary: true }],
    onOpen: (m, close) => watchJob(job, $("[data-rj]", m), (j) => {
      toast(j.status === "done" ? `${titleCase(p.name)} redrawn` : "Redraw failed - see the log", j.status !== "done");
      if (j.status === "done") { close(); pageAssets("sprites"); }      // a drawing makes it a 2D sprite
    }) });
}

function editProp(p) {
  const used = p.used_in.length ? p.used_in.map((s) => `<span class="chip">${esc(s.name)}</span>`).join("") : `<span class="muted small">Not used in a saved set yet.</span>`;
  return openModal({ title: titleCase(p.name), wide: true,
    body: `<div class="prop-edit">
      <div class="prop-big checker">${propPic(p) ? `<img src="${esc(propPic(p))}" alt="">` : `<div class="asset-noimg"><span>${p.form === "3d" ? "🧊" : "🖼"}</span><small>${p.form === "3d" ? "A 3D model built from shapes - its picture appears after its next look check." : "Not drawn yet - press 🎨 Redraw."}</small></div>`}</div>
      <div class="prop-form">
        <label class="modal-field">Description <span class="muted">(what it looks like - used when it's drawn)</span>
          <textarea rows="3" data-f="looks">${esc(p.looks)}</textarea></label>
        <div class="row">
          <label class="modal-field">Height (m)<input type="number" step="0.05" min="0.05" max="12" data-f="height" value="${esc(p.height ?? "")}"></label>
          <label class="modal-field">Width (m)<input type="number" step="0.05" min="0.03" max="15" data-f="width" value="${esc(p.width ?? "")}" placeholder="auto"></label>
          <label class="modal-field">Sits on<select data-f="on">${options(["floor", "table", "wall"], p.on, ON_ICON)}</select></label>
        </div>
        <div class="modal-field"><span class="label">Used in</span><div class="chips-row">${used}</div></div>
        <p class="muted small">ID <code>${esc(p.kind)}</code> · ${p.form === "sprite" ? "🖼 2D sprite" : "🧊 3D model"} · ${p.parts} shape parts${p.created ? " · made " + ago(p.created) : ""}</p>
      </div></div>`,
    buttons: [
      { label: "🗑 Delete", danger: true, left: true, onClick: () => deleteProp(p) },
      ...(p.form === "sprite" ? [{ label: "🎨 Redraw", left: true, onClick: (m) => redrawProp(p, $("[data-f=looks]", m).value.trim() || p.looks) }] : []),
      ...(p.form === "sprite" && p.parts ? [{ label: "🧊 Use the 3D model", left: true, onClick: async () => {
        await api("PUT", `/api/assets/props/${p.kind}`, { form: "3d" });
        toast(`${titleCase(p.name)} is a 3D prop again`); pageAssets("props"); } }] : []),
      ...(p.form === "3d" && !p.explainer ? [{ label: "🖼 Make it a sprite", left: true, onClick: async (m) => {
        if (!(await uiConfirm("Draw it as a flat 2D picture instead of its 3D shapes? You can switch back any time.", { title: "Make it a sprite", ok: "🖼 Draw it" }))) return false;
        return redrawProp(p, $("[data-f=looks]", m).value.trim() || p.looks); } }] : []),
      { label: "Cancel", value: null },
      { label: "💾 Save", primary: true, onClick: async (m) => {
          const val = (k) => $(`[data-f=${k}]`, m).value;
          await api("PUT", `/api/assets/props/${p.kind}`, { looks: val("looks"), height: val("height"), width: val("width"), on: val("on") });
          toast(`Saved ${titleCase(p.name)}`);
          pageAssets();
        } },
    ] });
}

/* ---- effects */
function fxCard(f) {
  return `<div class="asset-card fx-card" data-fx="${esc(f.name)}" tabindex="0">
    <div class="asset-thumb fx-thumb">${f.video ? `<video src="${esc(f.video)}" poster="${esc(f.poster || "")}" muted loop playsinline preload="none"></video>`
      : `<div class="asset-noimg"><span>✨</span><small>no preview yet</small></div>`}
      ${f.edited ? `<span class="badge-corner">edited</span>` : ""}</div>
    <div class="asset-info">
      <div class="asset-name">${esc(f.label)}</div>
      <div class="asset-meta"><span class="swatches">${f.colors.map((c) => `<i style="background:${esc(c)}"></i>`).join("")}</span>
        <span class="chip">${f.count} bits</span>${f.stale ? `<span class="chip warn" title="Changed since the preview was made">preview outdated</span>` : ""}</div>
      <div class="muted small mono">${esc(f.name)}</div>
    </div>
    <div class="asset-actions"><button data-fa="edit" title="Edit">✏️</button></div></div>`;
}

function assetsFx(box, fx) {
  const missing = fx.filter((f) => !f.video || f.stale).map((f) => f.name);
  box.innerHTML = `
    <div class="asset-toolbar">
      <p class="muted small" style="margin:0;flex:1">Effects play in shots that ask for them (<code>[rain]</code>, the shot's Effects picker) or by default in some sets. Tweak colours, amount, speed and size - every video uses your version.</p>
      <button id="fx-all">🎬 ${missing.length ? `Render ${missing.length} missing preview${missing.length > 1 ? "s" : ""}` : "Re-render all previews"}</button>
    </div>
    <div class="inline-job" id="fx-job"></div>
    <div class="asset-grid fx-grid">${fx.map(fxCard).join("")}</div>`;
  $$(".fx-card", box).forEach((card) => {
    const f = fx.find((x) => x.name === card.dataset.fx);
    const v = $("video", card);
    if (v) {
      card.onmouseenter = () => v.play().catch(() => {});
      card.onmouseleave = () => { v.pause(); };
    }
    card.onclick = (e) => { if (!e.target.closest("button") || e.target.closest("[data-fa]")) editFx(f); };
    card.onkeydown = (e) => { if (e.key === "Enter") editFx(f); };
  });
  // on phones there's no hover: play the clips that are on screen
  if ("IntersectionObserver" in window && matchMedia("(hover: none)").matches) {
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting ? e.target.play().catch(() => {}) : e.target.pause()), { threshold: 0.6 });
    $$(".fx-card video", box).forEach((v) => io.observe(v));
  }
  $("#fx-all").onclick = guard(async () => {
    const job = await api("POST", "/api/assets/fx/preview", { names: missing.length ? missing : [] });
    watchJob(job, $("#fx-job"), (j) => { toast(j.status === "done" ? "Previews ready" : "Preview render failed", j.status !== "done"); if (j.status === "done") pageAssets(); });
  });
}

function editFx(f) {
  const st = { colors: [...f.colors], amount: f.amount, speed: f.speed, size: f.size };
  const slider = (k, label, help) => `<label class="modal-field">${label} <b class="mono" data-v="${k}">${(+st[k]).toFixed(2)}×</b>
      <input type="range" min="0.25" max="3" step="0.05" data-s="${k}" value="${st[k]}"><span class="muted small">${help}</span></label>`;
  const save = async (m, render) => {
    await api("PUT", `/api/assets/fx/${f.name}`, st);
    if (render) {
      const job = await api("POST", "/api/assets/fx/preview", { names: [f.name] });
      toast(`Saved - rendering a new ${f.label.toLowerCase()} preview`);
      AS_TAB = "fx"; await pageAssets();
      watchJob(job, $("#fx-job"), (j) => { if (j.status === "done") pageAssets(); });
    } else { toast(`Saved ${f.label}`); pageAssets(); }
  };
  return openModal({ title: `✨ ${f.label}`, wide: true,
    body: `<div class="prop-edit">
      <div class="prop-big fx-big">${f.video ? `<video src="${esc(f.video)}" poster="${esc(f.poster || "")}" autoplay muted loop playsinline></video>` : `<div class="asset-noimg"><span>✨</span><small>No preview yet</small></div>`}</div>
      <div class="prop-form">
        <div class="modal-field"><span class="label">Colours</span><div class="color-list" data-colors></div></div>
        ${slider("amount", "Amount", "How many bits are in the air")}
        ${slider("speed", "Speed", "How fast they fall, rise or drift")}
        ${slider("size", "Size", "How big each bit is")}
        <p class="muted small">Previews show the saved version - use <b>Save &amp; preview</b> to see your change.</p>
      </div></div>`,
    buttons: [
      { label: "↺ Reset to default", left: true, onClick: async () => { await api("DELETE", `/api/assets/fx/${f.name}`); toast(`${f.label} reset`); pageAssets(); } },
      { label: "Cancel", value: null },
      { label: "💾 Save", onClick: (m) => save(m, false) },
      { label: "🎬 Save & preview", primary: true, onClick: (m) => save(m, true) },
    ],
    onOpen: (m) => {
      const drawColors = () => {
        const box = $("[data-colors]", m);
        box.innerHTML = st.colors.map((c, i) => `<span class="color-pill"><input type="color" value="${esc(c)}" data-ci="${i}"><button data-cx="${i}" title="Remove" ${st.colors.length < 2 ? "disabled" : ""}>✕</button></span>`).join("")
          + (st.colors.length < 8 ? `<button class="color-add" data-cadd title="Add a colour">＋</button>` : "");
        $$("[data-ci]", box).forEach((inp) => inp.oninput = () => { st.colors[+inp.dataset.ci] = inp.value; });
        $$("[data-cx]", box).forEach((b) => b.onclick = () => { st.colors.splice(+b.dataset.cx, 1); drawColors(); });
        const add = $("[data-cadd]", box);
        if (add) add.onclick = () => { st.colors.push(st.colors[st.colors.length - 1] || "#ffffff"); drawColors(); };
      };
      drawColors();
      $$("[data-s]", m).forEach((r) => r.oninput = () => { st[r.dataset.s] = +r.value; $(`[data-v=${r.dataset.s}]`, m).textContent = (+r.value).toFixed(2) + "×"; });
    } });
}

/* ------------------------------------------------------------------ router */
const PAGES = { create: pageCreate, sets: pageSets, assets: () => pageAssets(), audio: pageAudio, videos: pageVideos, characters: pageCharacters, settings: pageSettings };
async function route() {
  const page = (location.hash || "#create").slice(1);
  $$("nav a").forEach((a) => a.classList.toggle("on", a.dataset.page === (page === "audio" ? "assets" : page)));
  try { await (PAGES[page] || pageCreate)(); } catch (e) { app.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
window.addEventListener("hashchange", route);
(async () => {
  try { await refreshMeta(); } catch (e) { app.innerHTML = `<p class="err">Can't reach the server: ${esc(e.message)}</p>`; return; }
  route();
  updateQueue();          // reschedules itself: every second while something runs, every 5 s when idle
})();

/* ------------------------------------------------------------------ GIF (video -> high-quality GIF)
   Added after the rest of the app: web/gif_web.py makes the API, pipeline/gif.py does the encoding. */
JOB_ICON.gif = "🎞";
PAGES.gif = pageGif;

const GIF_LABELS = {
  width: { 0: "Original size (best)", 720: "720 px wide", 540: "540 px wide", 360: "360 px wide" },
  fps: { 0: "Same as the video (max 50)", 30: "30 fps", 24: "24 fps", 15: "15 fps" },
  colors: { 256: "256 colours (best)", 128: "128 colours", 64: "64 colours" },
  dither: { sierra2_4a: "Sierra 2-4A (smoothest)", floyd_steinberg: "Floyd–Steinberg", bayer: "Bayer (crisp pattern)", none: "None (visible banding)" },
};

function gifSourceOptions(list) {
  return list.length
    ? list.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")
    : '<option value="">No videos yet - make one or upload a clip</option>';
}

function drawGifGallery(made) {
  const box = $("#gf-list");
  if (!box) return;
  box.innerHTML = made.length ? `<div class="cards">${made.map((g) => `
    <div class="card"><img src="${esc(g.url)}?v=${Math.round(g.updated)}" loading="lazy" alt="" style="width:100%;border-radius:8px;background:#000">
      <div class="title small">${esc(g.name)}</div>
      <div class="muted small">${ago(g.updated)} · ${(g.size / 1048576).toFixed(1)} MB</div>
      <div class="btns"><a class="btn" href="${esc(g.url)}" download="${esc(g.name)}">⬇ Download</a></div></div>`).join("")}</div>`
    : '<p class="muted">No GIFs yet.</p>';
}

async function pageGif() {
  const d = await api("GET", "/api/gif");
  const sources = new Map(d.sources.map((s) => [s.id, s]));
  app.innerHTML = `
    <h2>Video → GIF</h2>
    <div class="panel">
      <p class="muted small" style="margin-top:0">Full quality: every frame at the video's own size and frame rate, one 256-colour palette
        worked out from the whole clip, and Sierra dithering so gradients stay smooth. Every GIF is kept under <b>10 MB</b>: if the best
        version would be bigger, the frame rate, then the size, then the colours are lowered just enough to fit.</p>
      <div class="row" style="align-items:end">
        <label style="flex:2">Video<select id="gf-src">${gifSourceOptions(d.sources)}</select></label>
        <div><button id="gf-up" type="button">⬆ Upload a clip</button>
          <input type="file" id="gf-file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm" hidden></div>
      </div>
      <div class="row">
        <label>Size<select id="gf-w">${options(["0", "720", "540", "360"], "0", GIF_LABELS.width)}</select></label>
        <label>Frame rate<select id="gf-fps">${options(["0", "30", "24", "15"], "0", GIF_LABELS.fps)}</select></label>
        <label>Colours<select id="gf-col">${options(["256", "128", "64"], "256", GIF_LABELS.colors)}</select></label>
        <label style="flex:2">Dithering<select id="gf-dit">${options(["sierra2_4a", "floyd_steinberg", "bayer", "none"], "sierra2_4a", GIF_LABELS.dither)}</select></label>
      </div>
      <div id="gf-prev"></div>
      <div class="btns"><button class="primary" id="gf-go" ${sources.size ? "" : "disabled"}>🎞 Make GIF</button></div>
      <div class="inline-job" id="gf-job"></div>
    </div>
    <h3>Made so far</h3>
    <div id="gf-list"></div>`;

  const src = $("#gf-src"), prev = $("#gf-prev");
  const showPreview = () => {
    const s = sources.get(src.value);
    prev.innerHTML = s && s.url ? `<video src="${esc(s.url)}#t=0.5" controls preload="metadata" playsinline
      style="width:100%;max-width:260px;aspect-ratio:9/16;background:#000;border-radius:8px;margin-top:10px"></video>` : "";
  };
  src.onchange = showPreview;
  showPreview();
  drawGifGallery(d.gifs);

  $("#gf-up").onclick = () => $("#gf-file").click();
  $("#gf-file").onchange = guard(async () => {
    const f = $("#gf-file").files[0];
    if (!f) return;
    toast("Uploading clip…");
    const r = await api("POST", "/api/gif/upload", undefined, { body: f, headers: { "X-Filename": encodeURIComponent(f.name) } });
    toast("Clip uploaded");
    await pageGif();                       // rebuild the page so the new clip is in the list and selected
    $("#gf-src").value = r.id;
    $("#gf-src").dispatchEvent(new Event("change"));
  });

  $("#gf-go").onclick = guard(async () => {
    if (!src.value) throw new Error("pick a video first");
    const job = await api("POST", "/api/gif/convert", {
      source: src.value, width: +$("#gf-w").value, fps: +$("#gf-fps").value,
      colors: +$("#gf-col").value, dither: $("#gf-dit").value,
    });
    watchJob(job, $("#gf-job"), async (j) => {
      if (j.status !== "done") return toast("GIF failed - see the log", true);
      const url = j.result.gif;
      $("#gf-job").innerHTML = `<div class="panel" style="margin-top:10px"><h4 style="margin:0 0 8px">🎞 Done <span class="muted small">${esc(j.result.name)}</span></h4>
        <img src="${esc(url)}?v=${Date.now()}" alt="" style="width:100%;max-width:320px;border-radius:8px;background:#000">
        <div class="btns"><a class="btn primary" href="${esc(url)}" download="${esc(j.result.name)}">⬇ Download GIF</a></div></div>`;
      toast("GIF ready ✓");
      const fresh = await api("GET", "/api/gif");
      drawGifGallery(fresh.gifs);
    });
  });
}

/* ------------------------------------------------------------------ IMPORTED real assets (free model packs)
   Added at the end: pipeline/imported.py does the work, web/imported_web.py is the API. */
JOB_ICON.import = "📦";
const IMP_FORMAT = { obj: "OBJ", fbx: "FBX", blend: "BLEND", mdl: "MDL" };
const IMP_STATUS = { ok: ["ok", "ready"], needs_conversion: ["err", "needs conversion"], failed: ["err", "failed"] };


// Imported tab: models grouped by a category made from their own names (not by the zip they came in), with
// search, category chips, a delete button on each card and "Select" mode to delete several at once.
// Deleted models' files move to assets/imported/packs/.trash (nothing is deleted for good).
const IMP = { cat: "all", q: "", select: false, picked: new Set() };

function impModelCard(m) {
  const [cls, label] = IMP_STATUS[m.status] || ["err", m.status];
  const hh = m.real_height || m.height;
  const h = hh ? `↕ ${(+hh).toFixed(hh < 1 ? 2 : 1)} m` : "";
  const on = IMP.picked.has(m.id);
  return `<div class="asset-card ${on ? "pick-on" : ""}" data-imp-card="${esc(m.id)}" title="${esc(m.pack)} · ${esc(m.folder || "")}">
    <div class="asset-thumb checker">${m.preview ? `<img src="${esc(m.preview)}?v=${m.preview_v || 1}" alt="${esc(m.name)}" loading="lazy">`
      : `<div class="asset-noimg"><span>📦</span><small>no picture</small></div>`}
      ${IMP.select ? `<span class="badge-corner" style="background:${on ? "var(--accent)" : "rgba(23,20,31,.85)"};color:${on ? "#1b1524" : "var(--muted)"}">${on ? "✓ picked" : "pick"}</span>` : ""}</div>
    ${IMP.select ? "" : `<div class="asset-actions"><button data-imp-rm="${esc(m.id)}" title="Delete this model">🗑</button></div>`}
    <div class="asset-info"><div class="asset-name">${esc(m.name)}</div>
      <div class="asset-meta"><span class="chip">${esc(IMP_FORMAT[m.format] || m.format)}</span>${h ? `<span class="chip">${h}</span>` : ""}
        <span class="pill ${cls}" title="${esc(m.note || "")}">${label}</span></div>
      ${m.description ? `<div class="muted small" title="was: ${esc(m.original_name || "")}">${esc(m.description)}</div>` : ""}
      <div class="muted small">${esc(m.pack)}</div></div></div>`;
}

async function assetsImported(box) {
  const data = await api("GET", "/api/imported/all");
  const models = data.models;
  const cats = {};
  models.forEach((m) => { cats[m.category] = (cats[m.category] || 0) + 1; });
  const catNames = Object.keys(cats).sort((a, b) => cats[b] - cats[a]);
  if (IMP.cat !== "all" && !cats[IMP.cat]) IMP.cat = "all";
  const q = IMP.q.trim().toLowerCase();
  const shown = models.filter((m) => (IMP.cat === "all" || m.category === IMP.cat)
    && (!q || `${m.name} ${m.pack} ${m.category}`.toLowerCase().includes(q)));
  for (const id of [...IMP.picked]) if (!models.some((m) => m.id === id)) IMP.picked.delete(id);
  const groups = catNames.filter((c) => shown.some((m) => m.category === c));
  box.innerHTML = `
    <div class="asset-toolbar">
      <p class="muted small" style="margin:0;flex:1">Real models from packs you downloaded, sorted by what they are. When a scene or script needs a prop, the studio checks these <b>first</b> -
        a model named after the thing, or the closest one there is (an ambulance for a mail van). Only when nothing fits does the studio make its own.</p>
    </div>
    <div class="panel">
      <h3 style="margin-top:0">Import a pack</h3>
      <p class="muted small" style="margin-top:0">A .zip with OBJ, FBX, BLEND or MDL models. Folders inside the zip are fine; textures are kept next to their models. Anything else in the zip is ignored.</p>
      <div class="row" style="align-items:end">
        <label style="flex:2">Pack name (optional)<input type="text" id="ip-name" placeholder="defaults to the zip's name"></label>
        <label style="flex:2">License<input type="text" id="ip-lic" value="Free for commercial use"></label>
      </div>
      <div class="btns"><button class="primary" id="ip-go">📦 Choose a .zip and import</button>
        <input type="file" id="ip-file" accept=".zip,application/zip" hidden></div>
      <div class="inline-job" id="ip-job"></div>
    </div>
    ${models.length ? `
    <div class="panel" style="margin-top:12px">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <label class="search" style="flex:1;min-width:180px">🔎<input type="text" id="imp-q" placeholder="Search ${models.length} models" value="${esc(IMP.q)}"></label>
        <button id="imp-cat" title="Let the AI sort models whose names the studio doesn't recognise (also happens on every import)">🏷 Categorize</button>
        <button id="imp-name" title="The picture model looks at each model and gives it a clear name and a description (a generic 'fence' becomes 'Wooden Farm Fence')">✏️ Name &amp; describe</button>
        <button id="imp-dupes" title="Models imported twice, or the same model saved in several formats: keep one">🧹 Remove duplicates</button>
        <button id="imp-sel">${IMP.select ? "Done" : "☑ Select"}</button>
        ${IMP.select ? `<button id="imp-all">Pick all shown (${shown.length})</button><button id="imp-none">Clear</button>
          <button class="danger" id="imp-del" ${IMP.picked.size ? "" : "disabled"}>🗑 Delete ${IMP.picked.size || ""} picked</button>` : ""}
      </div>
      <div class="chips-row" style="margin-top:10px">
        <button class="chip-btn ${IMP.cat === "all" ? "on" : ""}" data-imp-cat="all">All · ${models.length}</button>
        ${catNames.map((c) => `<button class="chip-btn ${IMP.cat === c ? "on" : ""}" data-imp-cat="${esc(c)}">${esc(c)} · ${cats[c]}</button>`).join("")}
      </div>
    </div>
    ${groups.map((c) => `<h3 style="margin:18px 0 8px">${esc(c)} <span class="muted small">${shown.filter((m) => m.category === c).length}</span></h3>
      <div class="asset-grid">${shown.filter((m) => m.category === c).map(impModelCard).join("")}</div>`).join("")
      || '<p class="muted" style="margin-top:12px">No models match.</p>'}
    <details class="panel" style="margin-top:18px"><summary><b>Packs</b> <span class="muted small">(${data.packs.length} - where the models came from)</span></summary>
      ${data.packs.map((p) => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px">
        <span style="flex:1">${esc(p.name)} <span class="muted small">· ${p.count} models · from ${esc(p.source || "")} · ${ago(p.added)}</span></span>
        <span class="pill ok">${esc(p.license || "")}</span><button class="danger" data-imp-pack="${esc(p.id)}">Remove pack</button></div>`).join("")}
    </details>` : '<p class="muted" style="margin-top:12px">No imported packs yet.</p>'}`;

  const redraw = () => assetsImported(box);
  $("#ip-go").onclick = () => $("#ip-file").click();
  $("#ip-file").onchange = guard(async () => {
    const f = $("#ip-file").files[0];
    if (!f) return;
    const name = $("#ip-name").value.trim(), lic = $("#ip-lic").value.trim();
    toast("Uploading pack…");
    const job = await api("POST", "/api/imported/upload", undefined, { body: f, headers: {
      "X-Filename": encodeURIComponent(f.name), "X-Pack-Name": encodeURIComponent(name), "X-License": encodeURIComponent(lic) } });
    watchJob(job, $("#ip-job"), async (j) => {
      if (j.status !== "done") return toast("Import failed - see the log", true);
      toast("Pack imported ✓");
      await pageAssets("imported");
    });
  });
  if (!models.length) return;
  const qBox = $("#imp-q");
  qBox.oninput = () => { IMP.q = qBox.value; clearTimeout(IMP.t); IMP.t = setTimeout(async () => {
    await redraw(); const nq = $("#imp-q"); nq.focus(); nq.setSelectionRange(nq.value.length, nq.value.length); }, 250); };
  $$("[data-imp-cat]").forEach((b) => b.onclick = () => { IMP.cat = b.dataset.impCat; redraw(); });
  $("#imp-cat").onclick = guard(async () => {
    const job = await api("POST", "/api/imported/categorize", {});
    toast("Sorting models into categories…");
    watchJob(job, $("#ip-job"), async (j) => {
      if (j.status !== "done") return toast("Sorting failed - see the log (is Ollama running?)", true);
      toast("Categories updated ✓");
      await pageAssets("imported");
    });
  });
  $("#imp-name").onclick = guard(async () => {
    const todo = models.filter((m) => m.status === "ok" && !m.description).length;
    if (!(await uiConfirm(`Name and describe ${todo} model${todo === 1 ? "" : "s"} from their pictures? It runs in the background, a few seconds per model (${Math.max(1, Math.round(todo * 4 / 60))} min or so). Their file names are kept as "original name".`,
      { title: "Name & describe", ok: "Start" }))) return;
    const job = await api("POST", "/api/imported/describe", {});
    watchJob(job, $("#ip-job"), async (j) => {
      if (j.status !== "done") return toast("Naming stopped - see the log (is Ollama running?)", true);
      toast("Models named ✓");
      await pageAssets("imported");
    });
  });
  $("#imp-dupes").onclick = guard(async () => {
    const d = await api("GET", "/api/imported/duplicates");
    if (!d.extra) return toast("No duplicates found ✓");
    const ex = d.examples.slice(0, 4).map((g) => `${g[0].name} (${g.length}×)`).join(", ");
    if (!(await uiConfirm(`${d.extra} duplicate cop${d.extra === 1 ? "y" : "ies"} of ${d.groups} model${d.groups === 1 ? "" : "s"} - e.g. ${ex}. Keep one of each (OBJ when the same model came in several formats) and move the others to the trash folder?`,
      { title: "Remove duplicates", ok: `Remove ${d.extra}`, danger: true }))) return;
    const r = await api("POST", "/api/imported/dedupe", {});
    toast(`${r.removed} duplicate${r.removed === 1 ? "" : "s"} removed`);
    await pageAssets("imported");
  });
  $("#imp-sel").onclick = () => { IMP.select = !IMP.select; if (!IMP.select) IMP.picked.clear(); redraw(); };
  if (IMP.select) {
    $("#imp-all").onclick = () => { shown.forEach((m) => IMP.picked.add(m.id)); redraw(); };
    $("#imp-none").onclick = () => { IMP.picked.clear(); redraw(); };
    $("#imp-del").onclick = guard(async () => {
      const n = IMP.picked.size;
      if (!n || !(await uiConfirm(`Delete ${n} model${n > 1 ? "s" : ""}? Their files move to the imported trash folder - nothing is deleted for good.`,
        { title: "Delete models", ok: `Delete ${n}`, danger: true }))) return;
      const r = await api("POST", "/api/imported/delete", { ids: [...IMP.picked] });
      IMP.picked.clear(); IMP.select = false;
      toast(`${r.deleted} model${r.deleted === 1 ? "" : "s"} deleted`);
      await pageAssets("imported");
    });
    $$("[data-imp-card]").forEach((c) => c.onclick = () => {
      const id = c.dataset.impCard;
      if (IMP.picked.has(id)) IMP.picked.delete(id); else IMP.picked.add(id);
      redraw();
    });
  }
  $$("[data-imp-rm]").forEach((b) => b.onclick = guard(async (e) => {
    e.stopPropagation();
    const m = models.find((x) => x.id === b.dataset.impRm);
    if (!(await uiConfirm(`Delete "${m.name}"? Its files move to the imported trash folder - nothing is deleted for good.`,
      { title: "Delete model", ok: "Delete", danger: true }))) return;
    await api("DELETE", `/api/imported/model/${encodeURIComponent(m.id)}`);
    toast(`"${m.name}" deleted`);
    await pageAssets("imported");
  }));
  $$("[data-imp-pack]").forEach((b) => b.onclick = guard(async () => {
    const p = data.packs.find((x) => x.id === b.dataset.impPack);
    if (!(await uiConfirm(`Remove the whole "${p.name}" pack (${p.count} models)? Its files move to the pack trash folder - nothing is deleted for good.`,
      { title: "Remove pack", ok: "Remove", danger: true }))) return;
    await api("DELETE", `/api/imported/pack/${p.id}`);
    toast("Pack removed");
    await pageAssets("imported");
  }));
}

/* ------------------------------------------------------------------ VIDEO EDITOR (Videos page: ✏️ Edit & re-render)
   One place to change a saved video: scenes, shots, look & filters, text, watermark, music & sound, things.
   Saves the episode (web/episode_edit.py) and renders it again. The video being replaced is kept in output/previous/. */
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-redit]");
  if (!b || document.querySelector(".modal-wrap")) return;           // one editor at a time
  openVideoEditor(b.dataset.redit).catch((err) => toast(err.message, true));
});

// Sets page: regenerate a set with other settings (the old files are backed up first)
function openRegenerate(s, themes) {
  const opt = (pairs, cur) => pairs.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("");
  const body = `
    <label>Describe the place<textarea id="rg-idea" rows="3" placeholder="e.g. a cosy cafe with wooden tables and a counter">${esc(s.description || "")}</textarea></label>
    <div class="row">
      <label>Name<input type="text" id="rg-name" value="${esc(s.name)}"></label>
      <label>Inside or outside<select id="rg-where">${opt([["any", "Let the AI decide"], ["inside", "Inside"], ["outside", "Outside"], ["air", "In the air"]], "any")}</select></label>
    </div>
    <div class="row">
      <label>Theme<select id="rg-theme">${themeOptions(themes, s.theme || "auto")}</select></label>
      <label>Room size (inside)<select id="rg-room">${opt([["auto-room", "Let the AI decide"], ["small", "Small (bathroom, closet)"], ["medium", "Medium (bedroom, kitchen)"], ["large", "Large (hall, living room)"]], "auto-room")}</select></label>
      <label>Ground (outside)<select id="rg-floor">${opt([["", "Let the AI decide"], ["grass", "Grass"], ["sand", "Sand"], ["snow", "Snow"], ["road", "Road"], ["stone", "Stone"], ["dirt", "Dirt"]], "")}</select></label>
    </div>
    <div class="row">
      <label>Light<select id="rg-light">${opt([["any", "Let the AI decide"], ["day", "Day"], ["sunset", "Sunset"], ["night", "Night"]], "any")}</select></label>
      <label>Built with the AI<select id="rg-ai">${opt([["auto", "Yes (Ollama)"], ["off", "No - random"]], "auto")}</select></label>
      <label>Textures (ComfyUI)<select id="rg-comfy">${opt([["auto", "When available"], ["off", "Off - flat colours"], ["required", "Required"]], "auto")}</select></label>
    </div>
    <label>Seed (optional - the same seed gives the same layout)<input type="number" id="rg-seed" placeholder="random"></label>
    <p class="muted small">The old set is backed up in sets/.trash before it's rebuilt, so nothing is lost if the new one isn't right.</p>
    <div class="inline-job" id="rg-job"></div>`;
  openModal({
    title: `🔄 Regenerate “${s.name}”`, wide: true, body,
    buttons: [
      { label: "Cancel", value: null },
      { label: "🔄 Regenerate", primary: true, closes: false, onClick: async (m) => {
        const val = (id) => $(`#${id}`, m).value;
        const job = await api("POST", `/api/sets/${s.id}/regenerate`, {
          idea: val("rg-idea"), name: val("rg-name"), where: val("rg-where"), room: val("rg-room"),
          floor: val("rg-floor"), theme: val("rg-theme"), light: val("rg-light"), ai: val("rg-ai"), comfy: val("rg-comfy"), seed: val("rg-seed") });
        watchJob(job, $("#rg-job", m), (j) => {
          if (j.status === "done") { toast("Set regenerated ✓"); pageSets(); }
          else toast("Regeneration failed - the old set is backed up in sets/.trash", true);
        });
        return false;
      } },
    ],
  });
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-regen]");
  if (!b) return;
  Promise.all([api("GET", "/api/sets"), api("GET", "/api/themes")]).then(([list, themes]) => {
    const set = list.find((x) => x.id === b.dataset.regen);
    if (set) openRegenerate(set, themes);
  }).catch((err) => toast(err.message, true));
});

// Sets page: a top-down map of the scene. Drag props, turn and scale them, add or delete; then save and preview.
const LAY_S = 520;                                    // the map is 520 px square
const LAY_GROUP = { "built-in": "Shape", made: "Made", imported: "Imported" };
function openLayoutEditor(sid) {
  Promise.all([api("GET", `/api/sets/${sid}/layout`), api("GET", "/api/sets")]).then(([L, sets]) => {
    const st = { props: L.props.map((p) => ({ ...p, pos: [...p.pos] })), sel: null, drag: null,
                 pick: null, pq: "", pg: "all" };          // pick = {title, onPick} while the prop picker is open
    const labelOf = (p) => p.label || p.kind.replace(/_/g, " ");
    const bounds = L.indoor && L.room
      ? { x0: -L.room[0] / 2 - 1, x1: L.room[0] / 2 + 1, y0: -L.room[1] / 2 - 2, y1: L.room[1] / 2 + 1 }
      : { x0: -12, x1: 12, y0: -12, y1: 12 };
    const toPx = (x, y) => [(x - bounds.x0) / (bounds.x1 - bounds.x0) * LAY_S, LAY_S - (y - bounds.y0) / (bounds.y1 - bounds.y0) * LAY_S];
    const perM = LAY_S / (bounds.x1 - bounds.x0);
    const save = async () => {
      const body = { props: st.props.map((p) => ({ i: p.i, kind: p.kind, pos: p.pos, rot: p.rot, scale: p.scale })) };
      await api("PUT", `/api/sets/${sid}/layout`, body);
    };
    openModal({
      title: `🗺 Layout: ${L.name}`, wide: true,
      body: `<div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start">
        <div style="flex:1 1 300px;max-width:${LAY_S}px"><svg id="lay-svg" width="${LAY_S}" height="${LAY_S}" viewBox="0 0 ${LAY_S} ${LAY_S}" style="width:100%;max-width:${LAY_S}px;background:${L.indoor ? "#f3ead8" : "#9fcf7a"};border-radius:10px;touch-action:none;user-select:none"></svg>
          <p class="muted small" style="margin:6px 0 0">Top-down: the bottom of the map is the camera side. Drag a prop to move it.</p></div>
        <div id="lay-side" style="flex:1 1 220px;min-width:220px"></div></div>
        <div class="inline-job" id="lay-job"></div>`,
      buttons: [
        { label: "Cancel", value: null },
        { label: "💾 Save layout", onClick: async (m) => { await save(m); toast("Layout saved"); } },
        { label: "💾 Save & preview", primary: true, closes: false, onClick: async (m) => {
          await save(m);
          const job = await api("POST", `/api/sets/${sid}/preview`, {});
          watchJob(job, $("#lay-job", m), (j) => {
            toast(j.status === "done" ? "Preview updated ✓" : "Preview failed - see the log", j.status !== "done");
            if (j.status === "done") $("#lay-job", m).innerHTML = `<img src="/setimg/${sid}.png?v=${Date.now()}" alt="" style="max-width:216px;border-radius:8px;margin-top:8px">`;
          });
          return false;
        } },
      ],
      onOpen: (m) => {
        const svg = $("#lay-svg", m);
        const draw = () => {
          svg.innerHTML = st.props.map((p, i) => {
            const [px, py] = toPx(p.pos[0], p.pos[1]);
            const r = Math.max(7, p.radius * p.scale * perM);
            const a = p.rot;
            const sel = st.sel === i;
            // a picture of the prop stands on its spot, scaled to its real height (the circle is the grab area)
            const h = p.preview && !p.liquid ? Math.max(16, (p.height || 1) * p.scale * perM) : 0;
            const pic = h ? `<image href="${esc(p.preview)}" x="${px - h / 2}" y="${py - h}" width="${h}" height="${h}" preserveAspectRatio="xMidYMax meet" style="image-rendering:pixelated;pointer-events:none"/>` : "";
            return `<g data-i="${i}" style="cursor:grab">
              <circle cx="${px}" cy="${py}" r="${r}" fill="${p.liquid ? "#7fd0ff" : "#fff"}" fill-opacity="${h ? 0.25 : 0.85}" stroke="${sel ? "#ff3b4e" : "#333"}" stroke-width="${sel ? 3 : 1.2}"/>
              ${pic}
              <line x1="${px}" y1="${py}" x2="${px + Math.cos(a) * r}" y2="${py - Math.sin(a) * r}" stroke="#333" stroke-width="2"/>
              <text x="${px}" y="${py + r + 11}" font-size="11" text-anchor="middle" fill="#222" paint-order="stroke" stroke="#fff" stroke-width="3">${esc(labelOf(p))}</text></g>`;
          }).join("") + Object.entries(L.marks || {}).map(([k, v]) => {
            const [mx, my] = toPx(v[0], v[1]);
            return `<text x="${mx}" y="${my}" font-size="10" text-anchor="middle" fill="#3a3a3a" opacity="0.7">✕ ${esc(k)}</text>`;
          }).join("");
          side();
        };
        // the prop picker: thumbnails, search and groups, shown in the side panel (same cards as the Assets page)
        const pickCards = () => {
          const list = L.choices.filter((c) => (st.pg === "all" || c.group === st.pg)
            && (!st.pq || `${c.label} ${c.pack}`.toLowerCase().includes(st.pq.toLowerCase())));
          $("#pk-count", m).textContent = `${list.length} of ${L.choices.length}`;
          $("#pk-grid", m).innerHTML = list.map((c) => `<div class="asset-card" tabindex="0" data-pk="${esc(c.key)}"
              title="${esc(c.pack ? `${c.label} · ${c.pack}` : c.label)}">
              <div class="asset-thumb checker">${c.preview ? `<img src="${esc(c.preview)}" alt="" loading="lazy">`
                : `<div class="asset-noimg"><span>${c.group === "built-in" ? "◻️" : "🧱"}</span><small>${c.group === "built-in" ? "shape" : "shapes only"}</small></div>`}</div>
              <div class="asset-info"><div class="asset-name">${esc(c.label)}</div>
                <div class="asset-meta">${c.height ? `<span class="chip">↕ ${(+c.height).toFixed(c.height < 1 ? 2 : 1)} m</span>` : ""}
                  <span class="chip">${esc(LAY_GROUP[c.group] || c.group)}</span></div>${c.pack ? `<div class="muted small">${esc(c.pack)}</div>` : ""}</div></div>`).join("")
            || `<div class="empty" style="grid-column:1/-1"><p>${L.choices.length ? "Nothing matches." : "No props yet."}</p></div>`;
          $$("[data-pk]", m).forEach((card) => {
            const pick = () => {
              const c = L.choices.find((x) => x.key === card.dataset.pk);
              const onPick = st.pick.onPick;
              st.pick = null;
              if (c) onPick(c);
              draw();
            };
            card.onclick = pick;
            card.onkeydown = (e) => { if (e.key === "Enter") pick(); };
          });
        };
        const side = () => {
          const el = $("#lay-side", m);
          if (st.pick) {
            el.innerHTML = `<div class="panel">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b style="flex:1">${esc(st.pick.title)}</b>
                <button id="pk-cancel">✕ Cancel</button></div>
              <div class="asset-toolbar" style="margin:10px 0 6px">
                <div class="search"><span>🔍</span><input type="text" id="pk-q" placeholder="Search props…" value="${esc(st.pq)}"></div>
                <div class="chips-row">${Object.entries({ all: "All", "built-in": "Shapes", made: "Made", imported: "Imported" })
                  .map(([k, v]) => `<button class="chip-btn ${k === st.pg ? "on" : ""}" data-pg="${k}">${v}</button>`).join("")}</div>
                <span class="muted small" id="pk-count"></span></div>
              <div class="asset-grid" id="pk-grid" style="grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;max-height:420px;overflow:auto;padding:2px"></div></div>`;
            $("#pk-cancel", m).onclick = () => { st.pick = null; draw(); };
            $("#pk-q", m).oninput = (e) => { st.pq = e.target.value; pickCards(); };
            $$("[data-pg]", m).forEach((b) => b.onclick = () => { st.pg = b.dataset.pg; $$("[data-pg]", m).forEach((x) => x.classList.toggle("on", x === b)); pickCards(); });
            pickCards();
            return;
          }
          const p = st.sel !== null ? st.props[st.sel] : null;
          el.innerHTML = `
            ${p ? `<div class="panel" style="margin-bottom:10px">
              <div style="display:flex;gap:10px;align-items:center">
                <div class="asset-thumb checker" style="width:76px;flex:none;border-radius:10px">${p.preview ? `<img src="${esc(p.preview)}" alt="">`
                  : `<div class="asset-noimg"><span>🧱</span></div>`}</div>
                <div style="min-width:0;flex:1"><b style="display:block;overflow-wrap:anywhere">${esc(labelOf(p))}</b>
                  <span class="muted small">${esc(LAY_GROUP[p.group] || "Shape")}${p.height ? ` · ↕ ${(+p.height).toFixed(p.height < 1 ? 2 : 1)} m` : ""}</span></div></div>
              <label style="margin-top:10px">Turn: <span id="lay-rot-v">${Math.round(p.rot * 180 / Math.PI)}</span>°<input type="range" id="lay-rot" min="0" max="360" value="${Math.round(((p.rot * 180 / Math.PI) % 360 + 360) % 360)}"></label>
              <label>Size: <span id="lay-sc-v">${p.scale.toFixed(2)}</span>×<input type="range" id="lay-sc" min="0.3" max="2.5" step="0.05" value="${p.scale}"></label>
              <div class="btns"><button id="lay-swap" ${p.liquid ? "disabled" : ""}>🔁 Swap…</button><button class="danger" id="lay-del">🗑 Remove</button></div></div>`
              : '<p class="muted small">Click a prop on the map to select it, then turn, size, swap or remove it.</p>'}
            <div class="panel"><b>Add a prop</b>
              <p class="muted small" style="margin:4px 0 8px">Shapes, the props you made and the imported models. New props appear at the centre of the map.</p>
              <button class="primary" id="lay-add-go" style="width:100%">＋ Add a prop…</button></div>`;
          if (p) {
            $("#lay-rot", m).oninput = (e) => { p.rot = Number(e.target.value) * Math.PI / 180; $("#lay-rot-v", m).textContent = e.target.value; draw(); };
            $("#lay-sc", m).oninput = (e) => { p.scale = Number(e.target.value); $("#lay-sc-v", m).textContent = p.scale.toFixed(2); draw(); };
            $("#lay-del", m).onclick = () => { st.props.splice(st.sel, 1); st.sel = null; draw(); };
            if (!p.liquid) $("#lay-swap", m).onclick = () => {
              st.pq = ""; st.pg = "all";
              st.pick = { title: `Swap “${labelOf(p)}” for…`, onPick: (c) => Object.assign(p, { kind: c.key, label: c.label, preview: c.preview,
                height: c.height, radius: c.radius, group: c.group }) };
              draw();
            };
          }
          $("#lay-add-go", m).onclick = () => {
            st.pq = ""; st.pg = "all";
            st.pick = { title: "Add a prop", onPick: (c) => {
              st.props.push({ i: null, kind: c.key, label: c.label, pos: [0, 0], rot: 0, scale: 1, radius: c.radius, liquid: false,
                preview: c.preview, height: c.height, group: c.group });
              st.sel = st.props.length - 1;
            } };
            draw();
          };
        };
        const toWorld = (e) => {
          const r = svg.getBoundingClientRect();
          const px = (e.clientX - r.left) * (LAY_S / r.width), py = (e.clientY - r.top) * (LAY_S / r.height);
          return [bounds.x0 + px / LAY_S * (bounds.x1 - bounds.x0), bounds.y0 + (LAY_S - py) / LAY_S * (bounds.y1 - bounds.y0)];
        };
        svg.addEventListener("pointerdown", (e) => {
          const g = e.target.closest("g[data-i]");
          if (!g) { st.sel = null; draw(); return; }
          st.sel = Number(g.dataset.i); st.drag = st.sel;
          svg.setPointerCapture(e.pointerId); draw();
        });
        svg.addEventListener("pointermove", (e) => {
          if (st.drag === null) return;
          const [x, y] = toWorld(e), p = st.props[st.drag];
          p.pos = [Math.max(-30, Math.min(30, x)), Math.max(-30, Math.min(30, y))];
          draw();
        });
        svg.addEventListener("pointerup", () => { st.drag = null; });
        draw();
      },
    });
  }).catch((err) => toast(err.message, true));
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-layout]");
  if (b) openLayoutEditor(b.dataset.layout);
});

// Sets page: look around the scene in 3D (web/viewer.html shows the exported scene, made by pipeline/set_export.py)
function openThreeD(s) {
  const frame = (id) => `<iframe src="/static/viewer.html?set=${encodeURIComponent(id)}&v=${Date.now()}" title="3D view"
    style="width:100%;height:520px;border:0;border-radius:10px;background:#1b1726"></iframe>`;
  openModal({
    title: `👁 3D view: ${s.name}`, wide: true,
    body: `<div id="v3-box">${s.has_3d ? frame(s.id)
      : '<p class="muted">The 3D view isn\'t made yet. Drag to look around and scroll to zoom once it is. Making it takes about a minute.</p>'}</div>
      <div class="inline-job" id="v3-job"></div>`,
    buttons: [
      { label: "Close", value: null },
      { label: s.has_3d ? "🔄 Remake 3D view" : "👁 Make 3D view", primary: true, closes: false, onClick: async (m) => {
        const job = await api("POST", `/api/sets/${s.id}/3d`, {});
        watchJob(job, $("#v3-job", m), (j) => {
          if (j.status === "done") { $("#v3-box", m).innerHTML = frame(s.id); $("[data-mb=\"1\"]", m).textContent = "🔄 Remake 3D view"; toast("3D view ready ✓"); pageSets(); }
          else toast("3D view failed - see the log", true);
        });
        return false;
      } },
    ],
  });
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-view]");
  if (!b) return;
  api("GET", "/api/sets").then((list) => {
    const s = list.find((x) => x.id === b.dataset.view);
    if (s) openThreeD(s);
  }).catch((err) => toast(err.message, true));
});

// Assets, props: draw a picture for every prop that has none (pipeline/propgen.py missing)
document.addEventListener("click", guard(async (e) => {
  const b = e.target.closest && e.target.closest("#pr-missing");
  if (!b) return;
  const job = await api("POST", "/api/assets/props/missing", {});
  watchJob(job, $("#pr-missing-job"), (j) => {
    toast(j.status === "done" ? "Pictures drawn ✓" : "Drawing failed - see the log", j.status !== "done");
    if (location.hash === "#assets") pageAssets("props");
  });
}));

// Sets page: a scene copied from a picture (pipeline/make_set.py --image)
document.addEventListener("click", (e) => { if (e.target.closest && e.target.closest("#sp-go")) $("#sp-file")?.click(); });
document.addEventListener("change", guard(async (e) => {
  if (e.target.id !== "sp-file") return;
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  const idea = ($("#sp-idea")?.value || "").trim();
  toast("Uploading picture…");
  const job = await api("POST", "/api/sets/from-image", undefined, { body: f, headers: {
    "X-Filename": encodeURIComponent(f.name), "X-Idea": encodeURIComponent(idea) } });
  watchJob(job, $("#sp-job"), (j) => {
    if (j.status === "done") { toast("Scene ready ✓"); pageSets(); }
    else toast("Scene failed - see the log", true);
  });
}));

// Characters page: make a still preview of the character (pipeline/character_preview.py)
document.addEventListener("click", guard(async (e) => {
  const b = e.target.closest && e.target.closest("[data-char-preview]");
  if (!b) return;
  const job = await api("POST", `/api/characters/${b.dataset.charPreview}/preview`);
  watchJob(job, $("#char-prev-job"), (j) => {
    if (j.status === "done") { toast("Preview ready ✓"); pageCharacters(); }
    else toast("Preview failed - see the log", true);
  });
}));

// Videos page: rename (the name in the list only) and delete (moves the file to output/.trash, keeps the script)
document.addEventListener("click", async (e) => {
  const rn = e.target.closest && e.target.closest("[data-rename]");
  const del = e.target.closest && e.target.closest("[data-delete]");
  if (rn) {
    const title = await uiPrompt("Rename video", { label: "The name shown in the Videos list (the video itself is not changed)",
      value: rn.dataset.title || "", ok: "Rename" });
    if (!title || !title.trim()) return;
    try { await api("PUT", `/api/videos/${rn.dataset.rename}`, { title: title.trim() }); }
    catch (err) { return toast(err.message, true); }
    toast("Renamed ✓");
    pageVideos();
  }
  if (del) {
    const name = del.dataset.title || del.dataset.delete;
    if (!(await uiConfirm(`Delete "${name}"? The video file moves to output/.trash. Its script stays, so you can render it again.`,
      { title: "Delete video", ok: "Delete", danger: true }))) return;
    try { await api("DELETE", `/api/videos/${del.dataset.delete}`); }
    catch (err) { return toast(err.message, true); }
    toast("Video moved to the trash");
    pageVideos();
  }
});

const VE_TABS = [["scenes", "🎬 Scenes"], ["shots", "🎞 Shots"], ["look", "🎨 Look & filters"], ["text", "🔤 Text"],
  ["brand", "🏷 Watermark & end"], ["sound", "🎵 Music & sound"], ["things", "🧍 Things"]];
const VE_CORNERS = ["top-left", "top-right", "bottom-left", "bottom-right"];
const VE_MODES = ["words", "line"];
const VE_HEX = (c) => "#" + c.map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
const VE_RGB = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const VE_GRID = "display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px";

async function openVideoEditor(id) {
  // the episode is needed; the lists fall back to empty so one failing request can't stop the editor opening
  const soft = (p, fallback) => p.catch(() => fallback);
  const [ep, models, music, fonts] = await Promise.all([
    api("GET", `/api/episodes/${id}`), soft(api("GET", "/api/imported/models"), []),
    soft(api("GET", "/api/music"), []), soft(api("GET", "/api/fonts"), [])]);
  const D = META.defaults;
  const setsNow = () => META.catalog.sets;
  const sfxKind = (kind) => Object.keys(META.sfx).filter((k) => META.sfx[k].kind === kind);
  const fontNames = (fonts || []).map((f) => (typeof f === "string" ? f : f.name)).filter(Boolean);
  const sceneOf = (s) => s.set || ep.set;
  const marksOf = (sid) => setsNow()[sid]?.marks || ["center"];
  const pairOpts = (pairs, cur) => pairs.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(l)}</option>`).join("");
  const sceneOpts = (cur, blank) => {
    const sets = setsNow(), ids = Object.keys(sets);
    if (cur && !sets[cur]) ids.unshift(cur);                  // e.g. a "new:..." scene that isn't in the list yet
    return pairOpts([...(blank !== undefined ? [["", blank]] : []), ...ids.map((k) => [k, sets[k]?.name || k])], cur);
  };
  const castChoice = {};                                      // thing name -> "imp:<id>" | "generate"

  // runs of shots in the same place = scenes
  const runs = () => {
    const out = [];
    ep.shots.forEach((s, i) => {
      const sid = sceneOf(s), last = out[out.length - 1];
      if (last && last.sid === sid) last.idx.push(i); else out.push({ sid, idx: [i] });
    });
    return out;
  };

  // settings: a field per default; ticked = changed for this video only
  const choicesFor = (obj, k) => {
    if (obj === "look" && k === "tint") return META.tints;
    if (obj === "captions" && k === "mode") return VE_MODES;
    if (obj === "captions" && k === "effect") return META.effects;
    if (obj === "captions" && k === "font" && fontNames.length) return fontNames;
    if (obj === "branding" && k === "watermark_corner") return VE_CORNERS;
    return null;
  };
  const fieldRows = (obj, defs, cur) => Object.keys(defs).map((k) => {
    const has = k in cur, base = defs[k], val = has ? cur[k] : base, dis = has ? "" : "disabled";
    const choices = choicesFor(obj, k);
    let ctl;
    if (choices) ctl = `<select data-act="val" data-obj="${obj}" data-k="${k}" ${dis}>${pairOpts(choices.map((c) => [c, c]), val)}</select>`;
    else if (typeof base === "boolean") ctl = `<input type="checkbox" data-act="val" data-type="bool" data-obj="${obj}" data-k="${k}" ${val ? "checked" : ""} ${dis}>`;
    else if (Array.isArray(base)) ctl = `<input type="color" data-act="val" data-type="color" data-obj="${obj}" data-k="${k}" value="${VE_HEX(val)}" ${dis}>`;
    else if (typeof base === "number") ctl = `<input type="number" step="any" data-act="val" data-type="num" data-obj="${obj}" data-k="${k}" value="${esc(val)}" ${dis}>`;
    else ctl = `<input type="text" data-act="val" data-obj="${obj}" data-k="${k}" value="${esc(val)}" ${dis}>`;
    return `<label style="display:flex;flex-direction:column;gap:4px"><span><input type="checkbox" data-act="ovr" data-obj="${obj}" data-k="${k}" ${has ? "checked" : ""}> ${esc(titleCase(k))}</span>${ctl}</label>`;
  }).join("");
  const setObj = (obj, k, v) => { ep[obj] = ep[obj] || {}; ep[obj][k] = v; };
  const toggleOvr = (obj, k, on) => {
    if (on) return setObj(obj, k, JSON.parse(JSON.stringify(D[obj][k])));
    if (ep[obj]) { delete ep[obj][k]; if (!Object.keys(ep[obj]).length) delete ep[obj]; }
  };
  const readVal = (el) => {
    const t = el.dataset.type;
    if (t === "bool") return el.checked;
    if (t === "num") return el.value === "" ? 0 : Number(el.value);
    if (t === "color") return VE_RGB(el.value);
    return el.value;
  };

  const shotRow = (s, i) => {
    const multi = Array.isArray(s.actions);
    return `<div class="shot" data-i="${i}" style="border-top:1px solid var(--line);padding:8px 0">
      <div style="display:flex;gap:6px;align-items:center">
        <span class="num">${i + 1}</span>
        <input type="text" data-act="shot" data-k="line" placeholder="What she says (empty = silent)" value="${esc(s.line || "")}" style="flex:1">
        <button data-mv="up" title="Move up">↑</button><button data-mv="down" title="Move down">↓</button>
        <button data-mv="del" class="danger" title="Remove this shot">✕</button></div>
      <div class="row">
        <label>Scene (place)<select data-act="shot" data-k="set">${sceneOpts(s.set || "", "same as the video")}</select></label>
        <label>Camera<select data-act="shot" data-k="camera">${options(Object.keys(cat().cameras), s.camera || "medium")}</select></label>
        ${multi ? `<label>Action<input type="text" disabled value="several actions (edit on the Create page)"></label>`
          : `<label>Action<select data-act="shot" data-k="action">${options(Object.keys(cat().anims), s.action || "idle")}</select></label>`}
        <label>Seconds<input type="number" data-act="shot" data-k="duration" min="0.5" step="0.5" placeholder="auto" value="${esc(s.duration ?? "")}"></label>
        <label>Sound effect<select data-act="shot" data-k="sfx"><option value="__auto" ${"sfx" in s ? "" : "selected"}>auto</option>
          <option value="" ${s.sfx === "" ? "selected" : ""}>none</option>${pairOpts(sfxKind("oneshot").map((k) => [k, META.sfx[k].label]), typeof s.sfx === "string" ? s.sfx : "")}</select></label>
        <label>Light<select data-act="shot" data-k="light">${pairOpts([["", "no change"], ...Object.entries(cat().lights || {})], s.light || "")}</select></label>
        ${speakersOf(ep).length > 1 ? `<label>Says it<select data-act="shot" data-k="speaker">${pairOpts(speakersOf(ep).map((c) => [c, titleCase(c)]), s.speaker || mainId(ep))}</select></label>` : ""}
      </div>
      ${(ep.co_stars || []).length ? `<div class="row">
        <label>The others while this is said<select data-act="shot" data-k="listen">${pairOpts([["", "listen (idle, turned to the speaker)"],
          ...Object.keys(cat().anims).filter((a) => !cat().anims[a].moves && !["float_up", "land", "fall", "float"].includes(a)).map((a) => [a, a])], s.listen || "")}</select></label>
        <label class="check" style="align-self:flex-end"><input type="checkbox" data-act="shot" data-k="both" ${s.both ? "checked" : ""}> Everyone in the frame</label></div>` : ""}</div>`;
  };
  const cat = () => META.catalog;

  const drawScenes = () => {
    const rs = runs();
    const cards = rs.map((r, n) => `<div class="panel" style="margin-bottom:10px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <b>Scene ${n + 1}</b><span class="muted small">shots ${r.idx[0] + 1}${r.idx.length > 1 ? "–" + (r.idx[r.idx.length - 1] + 1) : ""} (${r.idx.length})</span>
          <select data-act="run-scene" data-run="${n}" style="flex:1;min-width:170px">${sceneOpts(r.sid)}</select>
          <button data-act="run-gen" data-run="${n}">✨ Make a new place for these shots</button></div>
        <ul class="small" style="margin:8px 0 0;padding-left:18px">${r.idx.map((i) => `<li>${i + 1}. ${esc(ep.shots[i].line || "(no line)")}</li>`).join("")}</ul></div>`).join("");
    return `<p class="muted small" style="margin-top:0">Each card is one scene: the shots in the same place. Change the place for a whole card, or make a new place
        from a description (it's made now and shown here). Shots can also get their own place on the Shots tab.</p>
      ${cards || '<p class="muted">No shots yet - add some on the Shots tab.</p>'}`;
  };
  const drawShots = () => `${ep.shots.map(shotRow).join("") || '<p class="muted">No shots.</p>'}
    <div class="btns"><button data-act="add-shot">＋ Add shot</button></div>`;
  const drawLook = () => `<label>Look preset<select data-act="look-preset">${pairOpts([["", "Global look (your settings)"],
      ...Object.keys(META.presets).map((k) => [k, k])], ep.look_preset || "")}</select></label>
    <p class="muted small">Tick a setting to change it for this video only. Everything else comes from the preset.</p>
    <div style="${VE_GRID}">${fieldRows("look", D.look, ep.look || {})}</div>`;
  const drawText = () => `<label>Video language<select data-act="lang">${pairOpts([["", `Settings default (${langName(META.settings.language)})`],
      ...Object.entries(cat().languages || {})], ep.language || "")}</select></label>
    ${(ep.language || META.settings.language || "en") !== "en" ? `<div class="btns"><button data-act="trans">🌐 Check translation</button></div>` : ""}
    <p class="muted small" style="margin-top:0">Subtitles and the title card. Tick to change for this video.</p>
    <div style="${VE_GRID}">${fieldRows("captions", D.captions, ep.captions || {})}</div>`;
  const drawBrand = () => `<p class="muted small" style="margin-top:0">Watermark in a corner of every frame, and the end card (leave the text empty for none).</p>
    <div style="${VE_GRID}">${fieldRows("branding", D.branding, ep.branding || {})}</div>`;
  const drawSound = () => {
    const musicCur = ep.music === undefined ? "__default" : ep.music;
    const track = music.find((t) => t.path === ep.music);
    const ambCur = ep.ambience === undefined ? "auto" : ep.ambience;
    return `<h4 style="margin:0 0 4px">Background music</h4>
      <select data-act="music">${pairOpts([["__default", "Default music (from your settings)"], ["", "No music"],
        ...music.map((t) => [t.path, t.name])], musicCur)}</select>
      ${track ? `<audio controls src="${esc(track.url)}" style="width:100%;margin-top:6px"></audio>` : ""}
      <h4 style="margin:16px 0 4px">Background sound</h4>
      <select data-act="ambience">${pairOpts([["auto", "Automatic (by place)"], ["", "No background sound"],
        ...sfxKind("ambience").map((k) => [k, META.sfx[k].label])], ambCur)}</select>
      <p class="muted small">Sound effects are chosen per shot on the Shots tab.</p>`;
  };
  const drawThings = () => {
    const things = Object.entries(ep.cast || {}).filter(([, info]) => info && info.type !== "person");
    if (!things.length) return '<p class="muted">Nothing else is in this video. Other people keep their looks.</p>';
    return things.map(([name, info]) => {
      const cur = castChoice[name] !== undefined ? castChoice[name]
        : info.generated ? "generate" : info.def?.by === "imported" ? "imp:" + info.def.model.id : "";
      return `<label style="display:block;margin-bottom:8px">${esc(titleCase(name))} <span class="muted small">(${esc(info.type || "thing")})</span>
        <select data-act="castm" data-name="${esc(name)}">${pairOpts([["", "Keep as it is"], ["generate", "✨ Generate its own (AI)"],
          ...models.map((m) => ["imp:" + m.id, `📦 ${m.name} · ${m.pack}`])], cur)}</select></label>`;
    }).join("");
  };
  const DRAW = { scenes: drawScenes, shots: drawShots, look: drawLook, text: drawText, brand: drawBrand, sound: drawSound, things: drawThings };

  let tab = "scenes";
  const draw = (m) => {
    $$("#ve-tabs .tab", m).forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    $("#ve-body", m).innerHTML = DRAW[tab]();
  };

  const save = (m) => api("POST", `/api/episodes/${id}/apply`, { episode: ep, cast_models: { ...castChoice } });
  const generateScene = async (m, idx, idea) => {
    const job = await api("POST", "/api/sets/generate", { idea });
    watchJob(job, $("#ve-job", m), async (j) => {
      if (j.status !== "done" || !j.result?.set) return toast("The new place wasn't made - see the log", true);
      for (const i of idx) ep.shots[i].set = j.result.set;
      await refreshMeta();                                   // the new place is now in the scene lists
      toast("New place ready ✓");
      draw(m);
    });
  };

  openModal({
    title: "✏️ Edit video", wide: true,
    body: `<label>Title<input type="text" id="ve-title" value="${esc(ep.title || "")}"></label>
      <div class="tabs" id="ve-tabs" style="margin-top:10px">${VE_TABS.map(([k, l]) => `<button class="tab" data-tab="${k}">${l}</button>`).join("")}</div>
      <div id="ve-body" style="min-height:240px;margin-top:10px"></div>
      <div class="inline-job" id="ve-job"></div>
      <p class="muted small" style="margin-top:10px">Rendering draws every frame again, so it takes as long as the first render.
        The video being replaced is kept in output/previous/.</p>`,
    buttons: [
      { label: "Cancel", value: null },
      { label: "🪄 Open in Custom Video", left: true, onClick: async () => {
        CS.wiz = cwFromEpisode(await api("GET", `/api/episodes/${id}`), id); CS.openWiz = true;
        if (location.hash === "#create") pageCreate(); else location.hash = "#create";
      } },
      { label: "💾 Save", onClick: async (m) => {
        const r = await save(m);
        toast(r.moved_marks?.length ? `Saved - shot ${r.moved_marks.join(", ")} moved to the scene's first place` : "Saved");
      } },
      { label: "🎬 Save & re-render", primary: true, closes: false, onClick: async (m) => {
        const r = await save(m);
        if (r.moved_marks?.length) toast(`Shot ${r.moved_marks.join(", ")} moved to the scene's first place`);
        const job = await api("POST", "/api/render", { id, fresh_voice: false });
        watchJob(job, $("#ve-job", m), (j) => {
          toast(j.status === "done" ? "Video re-rendered ✓" : "Render failed - see the log", j.status !== "done");
          if (location.hash === "#videos") pageVideos();
        });
        return false;
      } },
    ],
    onOpen: (m) => {
      $("#ve-title", m).oninput = (e) => { ep.title = e.target.value; };
      $("#ve-tabs", m).onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) { tab = b.dataset.tab; draw(m); } };
      const box = $("#ve-body", m);
      box.addEventListener("click", async (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.dataset.act === "trans") { await checkTranslation(ep, b).catch((err) => toast(err.message, true)); return; }
        if (b.dataset.act === "add-shot") {
          const last = ep.shots[ep.shots.length - 1] || {};
          ep.shots.push({ action: "idle", camera: "medium", move: "static", expression: "neutral", line: "", ...(last.set ? { set: last.set } : {}) });
          return draw(m);
        }
        if (b.dataset.act === "run-gen") {
          const r = runs()[+b.dataset.run];
          const idea = await uiPrompt("✨ A new place for these shots", { label: "Describe the place - it's made now (it can take a few minutes)",
            placeholder: "e.g. a rainy rooftop at night, a candy shop, the moon", ok: "Make it" });
          if (idea) await generateScene(m, r.idx, idea);
          return;
        }
        if (b.dataset.mv) {
          const i = +b.closest(".shot").dataset.i, d = b.dataset.mv;
          if (d === "del") ep.shots.splice(i, 1);
          if (d === "up" && i > 0) [ep.shots[i - 1], ep.shots[i]] = [ep.shots[i], ep.shots[i - 1]];
          if (d === "down" && i < ep.shots.length - 1) [ep.shots[i + 1], ep.shots[i]] = [ep.shots[i], ep.shots[i + 1]];
          draw(m);
        }
      });
      box.addEventListener("change", (e) => {
        const el = e.target, act = el.dataset.act;
        if (act === "shot") {
          const i = +el.closest(".shot").dataset.i, s = ep.shots[i], k = el.dataset.k, v = el.value;
          if (k === "duration") { if (v) s.duration = +v; else delete s.duration; }
          else if (k === "set") { if (v) s.set = v; else delete s.set; }
          else if (k === "sfx") { if (v === "__auto") delete s.sfx; else s.sfx = v; }
          else if (k === "both") { if (el.checked) s.both = true; else delete s.both; }
          else if (k === "speaker") { if (!v || v === mainId(ep)) delete s.speaker; else s.speaker = v; }
          else if (v === "") delete s[k];
          else s[k] = v;
          if (k === "action") { if (cat().anims[v]?.moves) s.to = s.to || marksOf(sceneOf(s))[0]; else delete s.to; }
          if (k === "set" && s.to && !marksOf(sceneOf(s)).includes(s.to)) s.to = marksOf(sceneOf(s))[0];
          return draw(m);
        }
        if (act === "run-scene") {
          const r = runs()[+el.dataset.run];
          for (const i of r.idx) { if (el.value === ep.set) delete ep.shots[i].set; else ep.shots[i].set = el.value; }
          return draw(m);
        }
        if (act === "ovr") { toggleOvr(el.dataset.obj, el.dataset.k, el.checked); return draw(m); }
        if (act === "val") { if (!el.disabled) setObj(el.dataset.obj, el.dataset.k, readVal(el)); return; }
        if (act === "lang") { if (el.value) ep.language = el.value; else delete ep.language; return draw(m); }
        if (act === "look-preset") {          // the saved copy of the look would hide the preset completely
          if (el.value) ep.look_preset = el.value; else delete ep.look_preset;
          delete ep.look; return draw(m); }
        if (act === "music") { if (el.value === "__default") delete ep.music; else ep.music = el.value; return draw(m); }
        if (act === "ambience") { ep.ambience = el.value; return; }
        if (act === "castm") { if (el.value) castChoice[el.dataset.name] = el.value; else delete castChoice[el.dataset.name]; }
      });
      box.addEventListener("input", (e) => {
        const el = e.target;
        if (el.dataset.act === "shot" && el.dataset.k === "line") {
          const s = ep.shots[+el.closest(".shot").dataset.i];
          if (el.value) s.line = el.value; else delete s.line;
        }
        if (el.dataset.act === "val" && el.type === "text" && !el.disabled) setObj(el.dataset.obj, el.dataset.k, el.value);
      });
      draw(m);
    },
  });
}
