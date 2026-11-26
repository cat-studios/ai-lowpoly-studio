/* Assets, actors: the extra people for scenes (pipeline/actors.py, web/actors_web.py).
   Main characters are not here - they live on the Characters page. Loaded after app.js (uses its helpers). */
const ACT_KIND = { generic: "Body (the studio's own)", rigged: "Rigged model", imported: "Imported model" };
const ACT_KIND_SHORT = { generic: "Body", rigged: "Rigged", imported: "Imported" };
const ACT_LOOK = [["hair", "Hair"], ["skin", "Skin"], ["dress", "Top"], ["pants", "Trousers"], ["shoes", "Shoes"]];
const ACT_DEFAULT_LOOK = { hair: "#3a2d2a", skin: "#ffdcc6", dress: "#4a6fa5", pants: "#2b2f3a", shoes: "#2a2226" };
const ACT_ROLES = ["store clerk", "customer", "waiter", "teacher", "office worker", "police officer", "doctor",
  "chef", "delivery driver", "passer-by", "neighbour", "security guard"];
let AC_Q = "", AC_FILTER = "all";

// a simple standing figure in the actor's colours - the picture of a generic body
function actorFigure(look) {
  const L = { ...ACT_DEFAULT_LOOK, ...(look || {}) };
  return `<svg viewBox="0 0 60 120" width="84" height="168" aria-hidden="true" style="filter:drop-shadow(0 6px 8px rgba(0,0,0,.35))">
    <ellipse cx="30" cy="114" rx="16" ry="3.5" fill="#000" opacity=".25"/>
    <rect x="22" y="58" width="7" height="46" rx="3" fill="${esc(L.pants)}"/>
    <rect x="31" y="58" width="7" height="46" rx="3" fill="${esc(L.pants)}"/>
    <ellipse cx="25.5" cy="106" rx="5" ry="3" fill="${esc(L.shoes)}"/>
    <ellipse cx="34.5" cy="106" rx="5" ry="3" fill="${esc(L.shoes)}"/>
    <rect x="16" y="34" width="28" height="30" rx="8" fill="${esc(L.dress)}"/>
    <rect x="9" y="36" width="8" height="26" rx="4" fill="${esc(L.dress)}"/>
    <rect x="43" y="36" width="8" height="26" rx="4" fill="${esc(L.dress)}"/>
    <circle cx="13" cy="64" r="3.5" fill="${esc(L.skin)}"/>
    <circle cx="47" cy="64" r="3.5" fill="${esc(L.skin)}"/>
    <rect x="26" y="26" width="8" height="10" fill="${esc(L.skin)}"/>
    <circle cx="30" cy="18" r="13" fill="${esc(L.skin)}"/>
    <path d="M16 18 Q16 3 30 4 Q44 3 44 18 Q40 9 30 9 Q20 9 16 18Z" fill="${esc(L.hair)}"/>
  </svg>`;
}

function actorPicture(a) {
  if (a.kind === "generic" || !a.picture) return actorFigure(a.look);
  return `<img src="${esc(a.picture)}" alt="" loading="lazy">`;
}

function assetsActors(box, data) {
  const filters = { all: "All", generic: "Bodies", rigged: "Rigged", imported: "Imported" };
  const keep = (a) => (!AC_Q || `${a.name} ${a.role} ${a.description}`.toLowerCase().includes(AC_Q.toLowerCase()))
    && (AC_FILTER === "all" || a.kind === AC_FILTER);
  box.innerHTML = `
    <div class="asset-toolbar">
      <div class="search"><span>🔍</span><input type="text" id="ac-q" placeholder="Search actors…" value="${esc(AC_Q)}"></div>
      <div class="chips-row">${Object.entries(filters).map(([k, v]) => `<button class="chip-btn ${k === AC_FILTER ? "on" : ""}" data-af="${k}">${v}</button>`).join("")}</div>
      <button class="primary" id="ac-new">＋ New actor</button>
      <span class="muted small" id="ac-count"></span>
    </div>
    <p class="muted small" style="margin:0 0 10px">Actors play the extra people in scenes: a store clerk behind the counter, a customer, a passer-by.
      A scene that names one (<code>+clerk</code>, <code>+store clerk</code>) gets the actor whose role matches; anyone unmatched gets the generic human.
      Main characters live on the Characters page.</p>
    <div class="asset-grid" id="ac-grid"></div>`;
  const draw = () => {
    const list = data.actors.filter(keep);
    $("#ac-count").textContent = `${list.length} of ${data.actors.length}`;
    $("#ac-grid").innerHTML = list.map((a) => `<div class="asset-card" tabindex="0" data-ac="${esc(a.id)}" title="${esc(a.description)}">
        <div class="asset-thumb checker">${actorPicture(a)}</div>
        <div class="asset-info"><div class="asset-name">${esc(a.name)}</div>
          <div class="asset-meta">${a.regular ? '<span class="chip" title="A regular: offered in Custom Video">⭐</span>' : ""}<span class="chip">${esc(a.role || "no role")}</span><span class="chip dim">${ACT_KIND_SHORT[a.kind] || a.kind}</span></div></div></div>`).join("")
      || `<div class="empty"><div class="empty-ic">🧍</div><p>${data.actors.length ? "Nothing matches." : "No actors yet."}</p></div>`;
    $$("[data-ac]", $("#ac-grid")).forEach((card) => {
      const open = () => actorEditor(data.actors.find((x) => x.id === card.dataset.ac), data);
      card.onclick = open;
      card.onkeydown = (e) => { if (e.key === "Enter") open(); };
    });
  };
  $("#ac-q").oninput = (e) => { AC_Q = e.target.value; draw(); };
  $("#ac-new").onclick = () => actorEditor(null, data);
  $$("[data-af]", box).forEach((b) => b.onclick = () => { AC_FILTER = b.dataset.af; $$("[data-af]", box).forEach((x) => x.classList.toggle("on", x === b)); draw(); });
  draw();
}

// the create / edit dialog: name, role, description, and what the body is made of
function actorEditor(a, data) {
  const cur = a ? { ...a } : { name: "", role: "", description: "", personality: "", regular: true, kind: "generic", height: 1.0, look: {} };
  const look = { ...ACT_DEFAULT_LOOK, ...(cur.look || {}) };
  let model = cur.kind === "rigged" ? cur.model : cur.kind === "imported" ? cur.model_id : "";
  const kindOf = () => $("#ae-kind").value;
  const body = `<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start">
      <div style="flex:0 0 150px"><div id="ae-pic" class="asset-thumb checker" style="width:150px;border-radius:12px"></div></div>
      <div style="flex:1 1 280px;min-width:240px">
        <label class="modal-field">Name<input type="text" id="ae-name" value="${esc(cur.name)}" placeholder="Store clerk"></label>
        <label class="modal-field">Role <span class="muted">(what they are - cast names are matched against it)</span>
          <input type="text" id="ae-role" list="ae-roles" value="${esc(cur.role)}" placeholder="store clerk">
          <datalist id="ae-roles">${ACT_ROLES.map((r) => `<option value="${esc(r)}">`).join("")}</datalist></label>
        <label class="modal-field">About <span class="muted">(how they look and act - the script AI reads this)</span>
          <textarea rows="2" id="ae-desc">${esc(cur.description)}</textarea></label>
        <label class="modal-field">Personality <span class="muted">(how they talk and act - e.g. grumpy, says "back in my day")</span>
          <input type="text" id="ae-pers" value="${esc(cur.personality || "")}" placeholder="cheerful, always hungry"></label>
        ${a && a.builtin ? "" : `<label class="check"><input type="checkbox" id="ae-reg" ${cur.regular ? "checked" : ""}> ⭐ Regular - offered in Custom Video, and the script writer brings them back</label>`}
        <label class="modal-field">Kind<select id="ae-kind">${Object.entries(ACT_KIND).map(([k, v]) =>
          `<option value="${k}" ${k === cur.kind ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      </div></div>
    <div id="ae-box" style="margin-top:12px"></div>`;
  openModal({
    title: a ? `🧍 ${a.name}` : "🧍 New actor", wide: true, body,
    buttons: [
      { label: "Cancel", value: null },
      ...(a && !a.builtin ? [{ label: "🗑 Delete", danger: true, closes: false, left: true, onClick: async (m, close) => {
        if (!(await uiConfirm(`Delete the actor “${a.name}”? Its file goes to assets/actors/.trash.`, { title: "Delete actor", ok: "🗑 Delete", danger: true }))) return false;
        await api("DELETE", `/api/actors/${a.id}`);
        toast("Actor deleted");
        close(null);
        pageAssets("actors");
        return false;
      } }] : []),
      { label: "💾 Save", primary: true, onClick: async (m) => {
        const val = (id) => ($(`#${id}`, m)?.value ?? "").trim();
        const kind = kindOf();
        const payload = { name: val("ae-name"), role: val("ae-role"), description: val("ae-desc"), kind,
          personality: val("ae-pers"), regular: !!$("#ae-reg", m)?.checked,
          height: kind === "generic" ? Number(val("ae-height") || 1) : (cur.height || 1), look: {} };
        if (kind === "generic") ACT_LOOK.forEach(([k]) => { payload.look[k] = val(`ae-c-${k}`); });
        if (kind === "rigged") payload.model = model;
        if (kind === "imported") payload.model_id = model;
        const saved = a && !a.builtin ? await api("PUT", `/api/actors/${a.id}`, payload) : await api("POST", "/api/actors", payload);
        toast(`Saved ${saved.name} ✓`);
        pageAssets("actors");
        return true;
      } },
    ],
    onOpen: (m) => {
      const pic = () => {
        if (kindOf() === "generic") {
          const look2 = {};
          ACT_LOOK.forEach(([k]) => { look2[k] = $(`#ae-c-${k}`, m)?.value || look[k]; });
          $("#ae-pic", m).innerHTML = actorFigure(look2);
        } else if (kindOf() === "imported") {
          const it = data.models.imported.find((x) => x.id === model);
          $("#ae-pic", m).innerHTML = it?.preview ? `<img src="${esc(it.preview)}" alt="">` : `<div class="asset-noimg"><span>📦</span><small>pick a model</small></div>`;
        } else {
          const r = data.models.rigs.find((x) => x.path === model);
          $("#ae-pic", m).innerHTML = r?.preview ? `<img src="${esc(r.preview)}" alt="">` : `<div class="asset-noimg"><span>🧍</span><small>${r ? esc(r.name) : "pick a rig"}</small></div>`;
        }
      };
      const box = () => {
        const k = kindOf();
        const el = $("#ae-box", m);
        if (k === "generic") {
          el.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:10px">${ACT_LOOK.map(([key, label]) =>
              `<label style="flex:1 1 120px">${label}<input type="color" id="ae-c-${key}" value="${esc(look[key])}"></label>`).join("")}</div>
            <label style="display:block;margin-top:10px">Height: <span id="ae-h-v">${(cur.height || 1).toFixed(2)}</span>×
              <input type="range" id="ae-height" min="0.8" max="1.25" step="0.01" value="${cur.height || 1}"></label>
            <p class="muted small">Drawn by the studio's own body: she's the same build as the catgirl, dressed in these colours. A role like "chef" or "police" adds its outfit when no colour is set.</p>`;
          $("#ae-height", m).oninput = (e) => { $("#ae-h-v", m).textContent = Number(e.target.value).toFixed(2); };
          $$("input[type=color]", el).forEach((i) => i.oninput = pic);
        } else if (k === "rigged") {
          el.innerHTML = `<p class="muted small" style="margin:0 0 8px">A rigged model (a .blend made with the character tools). It walks, talks with gestures and poses like a main character, but its voice is not used.</p>
            <div class="asset-grid" style="grid-template-columns:repeat(auto-fill,minmax(120px,1fr));max-height:300px;overflow:auto">${data.models.rigs.map((r) =>
              `<div class="asset-card ${r.path === model ? "pick-on" : ""}" tabindex="0" data-pick="${esc(r.path)}"><div class="asset-info">
                <div class="asset-name">${esc(r.name)}</div><div class="asset-meta"><span class="chip">${esc(r.source)}</span></div></div></div>`).join("")
              || '<div class="empty"><p>No rigged models yet. Make one from a VRoid file on the Characters page, or add a .blend to assets/actors/rigs.</p></div>'}</div>`;
          bindPick(el);
        } else {
          el.innerHTML = `<input type="text" id="ae-search" placeholder="Search imported models…" style="margin-bottom:8px">
            <div class="asset-grid" id="ae-models" style="grid-template-columns:repeat(auto-fill,minmax(120px,1fr));max-height:300px;overflow:auto"></div>`;
          const draw = () => {
            const q = $("#ae-search", m).value.toLowerCase();
            const list = data.models.imported.filter((x) => !q || `${x.name} ${x.pack}`.toLowerCase().includes(q)).slice(0, 200);
            $("#ae-models", m).innerHTML = list.map((x) => `<div class="asset-card ${x.id === model ? "pick-on" : ""}" tabindex="0" data-pick="${esc(x.id)}">
              <div class="asset-thumb checker">${x.preview ? `<img src="${esc(x.preview)}" alt="" loading="lazy">` : `<div class="asset-noimg"><span>📦</span></div>`}</div>
              <div class="asset-info"><div class="asset-name">${esc(x.name)}</div><div class="muted small">${esc(x.pack)}</div></div></div>`).join("")
              || '<div class="empty"><p>No imported models match.</p></div>';
            bindPick(el);
          };
          $("#ae-search", m).oninput = draw;
          draw();
        }
        pic();
      };
      // clicking a card picks it (rigs and imported models)
      const bindPick = (root) => $$("[data-pick]", root).forEach((c) => {
        const pick = () => { model = c.dataset.pick; $$("[data-pick]", root).forEach((x) => x.classList.toggle("pick-on", x === c)); pic(); };
        c.onclick = pick;
        c.onkeydown = (e) => { if (e.key === "Enter") pick(); };
      });
      $("#ae-kind", m).onchange = () => { model = ""; box(); };
      box();
    },
  });
}
