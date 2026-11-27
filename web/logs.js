/* 🔎 Logs page: everything a job (a video, a set, a prop, music...) or the app itself did - every AI prompt and
   answer (with the pictures the AI was shown), image prompts sent to ComfyUI, each voice line, Blender and ffmpeg
   runs, the steps, the shots as directed, warnings and every log line - live while it runs.
   Loaded after app.js. API: web/trace_web.py; events: pipeline/studiotrace.py. */
"use strict";

const LOGKINDS = {
  ai: ["🧠", "AI"], image: ["🖼", "Pictures"], voice: ["🗣", "Voice"], blender: ["🎬", "Blender"],
  ffmpeg: ["🎞", "ffmpeg"], step: ["🪜", "Steps"], plan: ["📋", "Shots"], job: ["⚙", "Job"],
  warn: ["⚠️", "Warnings"], error: ["⛔", "Errors"], log: ["📜", "Log lines"],
};
const LV = { sel: null, events: [], next: 0, timer: null, filter: new Set(), q: "", follow: true, t0: null, live: null };

PAGES.logs = pageLogs;
(() => {      // the nav link (after Stats) and the job panel's "everything" button
  const stats = document.querySelector('nav a[data-page="stats"]');
  if (stats && !document.querySelector('nav a[data-page="logs"]')) {
    const a = document.createElement("a");
    a.href = "#logs"; a.dataset.page = "logs"; a.textContent = "Logs";
    stats.after(a);
  }
})();

function logsTime(t) {
  if (!t) return "";
  const d = new Date(t * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function logsAgo(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(t * 1000).toLocaleDateString();
}

async function pageLogs() {
  clearTimeout(LV.timer);
  const [, kind, id] = location.hash.slice(1).split("/");      // #logs/job/<id> or #logs/app/<day>
  LV.filter = new Set();
  const list = await api("GET", "/api/trace");
  if (!kind) {                    // nothing picked: the running job, else the newest
    const run = list.jobs.find((j) => j.status === "running") || list.jobs[0];
    LV.sel = run ? { kind: "job", id: run.id } : list.days[0] ? { kind: "app", id: list.days[0] } : null;
  } else LV.sel = { kind, id };
  app.innerHTML = `<h2>🔎 Logs</h2>
    <p class="muted small">Everything that happens while a video, set, prop or anything else is made: every AI prompt and
    its answer (and the pictures it was shown), picture prompts sent to ComfyUI, each voice line, Blender and ffmpeg,
    the steps and every log line. Spot something odd? Tell Claude what you saw here.</p>
    <div class="lg-wrap">
      <aside class="lg-side">
        <div class="lg-h">Jobs</div>
        <div class="lg-jobs">${list.jobs.map((j) => `<a class="lg-job ${LV.sel?.kind === "job" && LV.sel.id === j.id ? "on" : ""}" href="#logs/job/${esc(j.id)}">
          <span class="lg-dot ${esc(j.status)}"></span><span class="lg-jt">${JOB_ICON[j.kind] || "⚙"} ${esc(j.title)}</span>
          <span class="lg-js muted">${esc(j.status === "running" ? (j.stage || "running") : j.status)} · ${esc(logsAgo(j.started))}</span></a>`).join("")
          || `<p class="muted small">No jobs yet.</p>`}</div>
        <div class="lg-h">The app itself <span class="muted small">(the Create page's AI calls)</span></div>
        <div class="lg-jobs">${list.days.map((d) => `<a class="lg-job ${LV.sel?.kind === "app" && LV.sel.id === d ? "on" : ""}" href="#logs/app/${esc(d)}">
          <span class="lg-dot app"></span><span class="lg-jt">🖥 ${esc(d)}</span></a>`).join("") || `<p class="muted small">Nothing yet.</p>`}</div>
      </aside>
      <section class="lg-main" id="lg-main">${LV.sel ? "" : `<p class="muted">Nothing to show yet - start a video or a set and come back.</p>`}</section>
    </div>`;
  if (LV.sel) openTrace();
}

function openTrace() {
  LV.events = []; LV.next = 0; LV.t0 = null; LV.live = null;
  const m = $("#lg-main");
  m.innerHTML = `<div id="lg-head"></div>
    <div class="lg-tools">
      <div class="lg-chips" id="lg-chips"></div>
      <input id="lg-q" type="search" placeholder="Search everything (prompts, answers, lines)…" value="${esc(LV.q)}">
      <label class="lg-follow"><input type="checkbox" id="lg-follow" ${LV.follow ? "checked" : ""}> Follow new</label>
      <button id="lg-open-all" class="small">Open all</button><button id="lg-close-all" class="small">Close all</button>
    </div>
    <div id="lg-steps" class="lg-steps"></div>
    <div id="lg-list" class="lg-list"></div>`;
  $("#lg-q").oninput = (e) => { LV.q = e.target.value.toLowerCase(); refilter(); };
  $("#lg-follow").onchange = (e) => { LV.follow = e.target.checked; };
  $("#lg-open-all").onclick = () => $$("#lg-list details:not([hidden])").forEach((d) => { d.open = true; fillEvent(d); });
  $("#lg-close-all").onclick = () => $$("#lg-list details").forEach((d) => d.open = false);
  pollTrace();
}

async function pollTrace() {
  clearTimeout(LV.timer);
  if (!location.hash.startsWith("#logs") || !$("#lg-list")) return;
  const sel = LV.sel;
  let r;
  try { r = await api("GET", `/api/trace/${sel.kind}/${encodeURIComponent(sel.id)}?after=${LV.next}`); }
  catch { LV.timer = setTimeout(pollTrace, 3000); return; }
  if (LV.sel !== sel) return;
  LV.live = r.job || null;
  if (r.events.length) {
    const list = $("#lg-list");
    const stick = LV.follow && (window.innerHeight + window.scrollY >= document.body.scrollHeight - 80);
    if (LV.t0 == null) LV.t0 = r.events[0].t;
    const frag = document.createDocumentFragment();
    for (const e of r.events) { LV.events.push(e); frag.appendChild(eventRow(e)); }
    list.appendChild(frag);
    LV.next = r.next;
    drawChips(); drawSteps(); refilter();
    if (stick) window.scrollTo(0, document.body.scrollHeight);
  }
  drawHead();
  const running = LV.live && (LV.live.status === "running" || LV.live.status === "queued");
  const today = sel.kind === "app" && sel.id === new Date().toISOString().slice(0, 10);
  LV.timer = setTimeout(pollTrace, running ? 1200 : today ? 4000 : 15000);
}

function drawHead() {
  const h = $("#lg-head");
  if (!h) return;
  const j = LV.live;
  const first = LV.events.find((e) => e.kind === "job");
  const title = j ? j.title : LV.sel.kind === "app" ? `The app on ${LV.sel.id}` : (first?.title || "").replace(/^Started: /, "") || LV.sel.id;
  const counts = (k) => LV.events.filter((e) => e.kind === k).length;
  const ai = LV.events.filter((e) => e.kind === "ai");
  const aiSecs = ai.reduce((a, e) => a + (e.data?.seconds || 0), 0);
  const end = j?.ended || (j?.status === "running" ? Date.now() / 1000 : LV.events.at(-1)?.t);
  const start = j?.started || LV.t0;
  h.innerHTML = `<div class="lg-title">${j ? `${JOB_ICON[j.kind] || "⚙"} ` : ""}${esc(title)}
      ${j ? `<span class="jp-status ${esc(j.status)}">${esc(j.status === "running" && jobPct(j) != null ? jobPct(j) + "%" : j.status)}</span>` : ""}</div>
    ${j && (j.status === "running" || j.status === "queued") ? `<div class="lg-now">${barHtml(j)}<span>${esc(jobLine(j))}</span></div>` : ""}
    <div class="lg-stats muted small">
      ${start ? `Started ${esc(logsTime(start))}` : ""}${start && end ? ` · ${fmtDur(end - start)}` : ""}
      · 🧠 ${ai.length} AI calls${ai.length ? ` (${fmtDur(aiSecs)} waiting on AI)` : ""} · 🖼 ${counts("image")} pictures
      · 🗣 ${counts("voice")} voice lines · ⚠️ ${counts("warn")} · ⛔ ${counts("error")}
      ${LV.sel.kind === "job" ? ` · <a href="#" id="lg-raw">raw log</a>` : ""}
    </div>`;
  const raw = $("#lg-raw");
  if (raw) raw.onclick = (e) => { e.preventDefault(); LV.filter = new Set(["log", "warn", "error"]); drawChips(); refilter(); };
}

function drawSteps() {
  const box = $("#lg-steps");
  if (!box) return;
  const steps = LV.events.filter((e) => e.kind === "step" || (e.kind === "job"));
  box.innerHTML = steps.length ? steps.map((e, k) => {
    const next = steps[k + 1]?.t || (LV.live?.status === "running" ? Date.now() / 1000 : null);
    return `<span class="lg-step ${k === steps.length - 1 && LV.live?.status === "running" ? "now" : ""}" title="${esc(logsTime(e.t))}">
      ${esc(e.title)}${next ? ` <b>${fmtDur(next - e.t)}</b>` : ""}</span>`;
  }).join("<span class='lg-arrow'>›</span>") : "";
}

function drawChips() {
  const box = $("#lg-chips");
  if (!box) return;
  const counts = {};
  for (const e of LV.events) counts[e.kind] = (counts[e.kind] || 0) + 1;
  box.innerHTML = `<button class="chip ${LV.filter.size ? "" : "on"}" data-k="">All ${LV.events.length}</button>` +
    Object.entries(LOGKINDS).filter(([k]) => counts[k]).map(([k, [ic, name]]) =>
      `<button class="chip ${LV.filter.has(k) ? "on" : ""}" data-k="${k}">${ic} ${name} ${counts[k]}</button>`).join("");
  $$("button", box).forEach((b) => b.onclick = () => {
    const k = b.dataset.k;
    if (!k) LV.filter.clear(); else if (LV.filter.has(k)) LV.filter.delete(k); else LV.filter.add(k);
    drawChips(); refilter();
  });
}

function evText(e) { return (e.title + " " + JSON.stringify(e.data || {})).toLowerCase(); }
function refilter() {
  for (const d of $$("#lg-list > details")) {
    const e = d._ev;
    d.hidden = !((!LV.filter.size || LV.filter.has(e.kind)) && (!LV.q || evText(e).includes(LV.q)));
  }
}

function evMeta(e) {
  const d = e.data || {};
  const bits = [];
  if (e.kind === "ai") bits.push(d.model, d.where, d.seconds != null ? `${d.seconds} s` : "", d.error ? "failed" : "");
  if (e.kind === "image") bits.push((d.models || []).join(", "));
  if (e.kind === "voice") bits.push(d.engine, d.cached ? "cached" : "new take");
  if (e.kind === "blender" && d.seconds != null) bits.push(`${d.seconds} s`);
  if (e.src) bits.push(e.src);
  return bits.filter(Boolean).join(" · ");
}

function eventRow(e) {
  const d = document.createElement("details");
  d.className = `lg-ev k-${e.kind}`;
  const rel = LV.t0 != null ? `+${fmtDur(e.t - LV.t0)}` : "";
  const [ic] = LOGKINDS[e.kind] || ["•"];
  const simple = e.kind === "log" || ((e.kind === "warn" || e.kind === "error" || e.kind === "step") && !e.data);
  d.innerHTML = `<summary><span class="lg-t" title="${esc(logsTime(e.t))}">${esc(rel)}</span><span class="lg-ic">${ic}</span>
    <span class="lg-tt">${esc(e.title)}</span><span class="lg-meta muted">${esc(evMeta(e))}</span></summary>`;
  if (simple) d.classList.add("simple");
  d.addEventListener("toggle", () => { if (d.open) fillEvent(d); });
  d._ev = e;
  return d;
}

function pre(label, text, cls = "") {
  if (text == null || text === "") return "";
  const t = typeof text === "string" ? text : JSON.stringify(text, null, 2);
  return `<div class="lg-block ${cls}"><div class="lg-bl">${esc(label)} <button class="lg-copy small" title="Copy">📋</button></div><pre>${esc(t)}</pre></div>`;
}

function fillEvent(d) {
  if (d.dataset.filled) return;
  d.dataset.filled = "1";
  const e = d._ev, x = e.data || {};
  let h = "";
  if (e.kind === "ai") {
    h += `<div class="lg-kv">${[["Asked by", x.caller], ["Model", x.model], ["Answered by", x.where], ["Fell back because", x.fell_back],
      ["Job", x.job_kind], ["Took", x.seconds != null ? `${x.seconds} s` : ""], ["Settings", x.options ? JSON.stringify(x.options) : ""],
      ["Answer format", x.format ? JSON.stringify(x.format) : ""], ["Cost", x.cost != null ? `$${x.cost}` : ""]]
      .filter(([, v]) => v).map(([k, v]) => `<span><b>${esc(k)}</b> ${esc(v)}</span>`).join("")}</div>`;
    for (const m of x.messages || []) {
      h += pre(m.role === "system" ? "Instructions (system)" : m.role === "user" ? "Prompt (user)" : m.role, m.content, `role-${m.role}`);
      if (m.images?.length) h += `<div class="lg-imgs">${m.images.map((n) => `<a href="/traceimg/${esc(n)}" target="_blank"><img src="/traceimg/${esc(n)}" alt="picture the AI was shown"></a>`).join("")}</div>`;
    }
    h += x.error ? pre("Error", x.error, "bad") : pre("Answer", x.answer, "answer");
  } else if (e.kind === "image") {
    h += pre("Prompt words", x.prompts) + pre("Models", (x.models || []).join("\n")) + pre("Settings", x.settings) + pre("Server", x.server);
  } else if (e.kind === "voice") {
    h += pre("Said", x.text) + pre("Voice", x.voice) + (x.ref ? pre("Reference voice", x.ref) : "") + pre("Cache file", x.cache_file);
  } else if (e.kind === "plan") {
    const shots = x.shots || [];
    if (Array.isArray(shots)) {
      const cols = ["line", "speaker", "camera", "move", "action", "expression", "set", "light", "particles", "fire", "cutaway", "events"];
      h += `<div class="lg-tablewrap"><table class="lg-table"><tr><th>#</th>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>
        ${shots.map((s, k) => `<tr><td>${k + 1}</td>${cols.map((c) => `<td>${esc(s[c] == null ? "" : typeof s[c] === "string" ? s[c] : JSON.stringify(s[c]))}</td>`).join("")}</tr>`).join("")}</table></div>`;
    }
    h += pre("Cast", x.cast) + pre("Render", x.render) + pre("Everything (JSON)", shots);
  } else if (e.kind === "blender") {
    h += pre("What Blender decided ([cast], [fire], [sets]... lines)", x.notes) + pre("Blender's log (the end)", x.log) + pre("Log file", x.log_file);
  } else if (e.kind === "ffmpeg") {
    h += pre("Filters", x.filters) + pre("Command", x.command) + pre("ffmpeg's errors", x.log, "bad");
  } else if (e.data) {
    h += pre("Details", x);
  } else {
    h += pre("Line", e.title);
  }
  const body = document.createElement("div");
  body.className = "lg-body";
  body.innerHTML = h;
  $$(".lg-copy", body).forEach((b) => b.onclick = (ev) => {
    ev.preventDefault();
    const t = b.closest(".lg-block").querySelector("pre").textContent;
    navigator.clipboard?.writeText(t).then(() => toast("Copied"), () => toast("Couldn't copy", true));
  });
  d.appendChild(body);
}
