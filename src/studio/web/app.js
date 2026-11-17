// Open Workbench Studio: home screen, search, one editor for every product (numbered steps, 3D preview, filament strip).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const norm = (s) => String(s ?? "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i");
const ICON = {
  home: '<path d="M3 11l9-7 9 7v9H3z"/>', yazi: '<path d="M5 20L12 4l7 16M8 14h8"/>', isik: '<circle cx="12" cy="10" r="5"/><path d="M9 20h6M10 17h4"/>',
  harita: '<path d="M2 19l7-11 4 6 3-4 6 9z"/>', atolye: '<rect x="4" y="4" width="16" height="16" rx="4"/><circle cx="12" cy="12" r="3"/>',
  isler: '<path d="M4 6h16M4 12h16M4 18h10"/>', donanim: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" class="ico">${ICON[k]}</svg>`;
const FILE_TR = { "3mf": "model.3mf", template: "Şablon PDF", cut_svg: "Kesim SVG", cut_dxf: "Kesim DXF", led_svg: "LED yolu SVG", led_dxf: "LED yolu DXF",
  assembly_pdf: "Montaj PDF", render_34: "Görsel", render_lit: "Görsel (ışıklı)", lit: "Görsel (ışıklı)", render_product: "Görsel", dims: "Ölçüler",
  render_top: "Üstten", glb: "3B (glb)", preview: "3B (glb)", sheet_pdf: "Levha şablonu", prompt_tr: "AI prompt", bom: "Malzeme listesi" };
const HOLE_TYPES = [["daire", "Daire"], ["dikdörtgen", "Dikdörtgen"], ["anahtar", "Anahtar deliği"]];

let CFG, PRODS = {}, RECENT = [], FIL = [];
let PROD = null, VALUES = {}, RESULT = null, MADE = null, VIEW = "34";
const api = async (url, opt) => {
  const r = await fetch(url, opt);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Hata ${r.status}`);
  return d;
};
const post = (url, body, method = "POST") => api(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
function toast(msg, ms = 3500) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms); }
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

// ------------------------------------------------------------------ filaments (printer slots)
function hexRgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function nearestSlot(color) {
  let best = null, bd = 1e9;
  for (const f of FIL) {
    const a = hexRgb(f.color), b = hexRgb(color);
    const d = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    if (d < bd) { bd = d; best = f; }
  }
  return bd <= 70 ? { slot: best, exact: bd < 1 } : null;
}
function renderSlots() {
  $("#slots").innerHTML = FIL.map((f) => `<i style="background:${f.color}" title="${f.slot}. yuva: ${esc(f.name)}"></i>`).join("");
  $("#ams").innerHTML = FIL.map((f) => `<div><i style="background:${f.color}"></i>${esc(f.name || f.color)}<small>${f.slot}. yuva · ${f.grams} g</small></div>`).join("");
}
function editFilaments() {
  $("#filRows").innerHTML = FIL.map((f, i) => `<div class="filrow"><b>${i + 1}.</b><input type="color" value="${f.color}" data-i="${i}" data-k="color">` +
    `<input value="${esc(f.name)}" data-i="${i}" data-k="name" placeholder="ör. Yeşil PLA"><input type="number" min="0" value="${f.grams}" data-i="${i}" data-k="grams" title="kalan gram"></div>`).join("");
  $("#filDlg").showModal();
}
$("#filSave").onclick = async (e) => {
  e.preventDefault();
  const items = FIL.map((f) => ({ ...f }));
  $$("#filRows [data-k]").forEach((el) => { items[+el.dataset.i][el.dataset.k] = el.type === "number" ? +el.value : el.value; });
  try { FIL = await post("/api/filaments", items, "PUT"); renderSlots(); renderStrip(); $("#filDlg").close(); toast("Filamentler kaydedildi."); }
  catch (err) { toast(err.message); }
};
$("#printer").onclick = editFilaments;
$("#editFil").onclick = editFilaments;

// ------------------------------------------------------------------ home
function famProducts(key) { return CFG.products.filter((p) => p.family === key); }
function renderHome() {
  const h = new Date().getHours();
  $("#hello").textContent = `${h < 12 ? "Günaydın" : h < 18 ? "İyi günler" : "İyi akşamlar"}, bugün ne üretiyoruz?`;
  $("#fams").innerHTML = CFG.families.map((f) => {
    const ps = famProducts(f.key);
    const chips = ps.slice(0, 4).map((p) => `<button data-p="${p.id}">${esc(p.label)}</button>`).join("") + (ps.length > 4 ? `<span>+${ps.length - 4}</span>` : "");
    return `<div class="fam" data-f="${f.key}"><div class="pic"><img src="${f.image}" alt=""></div><div class="body"><h3>${esc(f.label)}</h3>` +
      `<p>${esc(f.description)}</p><div class="chips">${chips}</div></div></div>`;
  }).join("");
  $("#recent").innerHTML = RECENT.length ? RECENT.slice(0, 8).map((j, i) => `<button class="job" data-j="${i}"><div class="th">${j.thumb ? `<img src="${j.thumb}" alt="" loading="lazy">` : ""}</div>` +
    `<b>${esc(j.name)}</b><small>${esc(CFG.families.find((f) => f.key === j.family)?.label || j.program)} · ${ago(j.when)}</small></button>`).join("")
    : `<p class="muted">Henüz iş yok. Yukarıdan bir ürün seçin.</p>`;
}
function ago(t) {
  const s = Date.now() / 1000 - t;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} dk önce`;
  if (s < 86400) return `${Math.round(s / 3600)} sa önce`;
  const d = Math.round(s / 86400);
  return d === 1 ? "dün" : `${d} gün önce`;
}
$("#fams").onclick = (e) => {
  const c = e.target.closest("[data-p]");
  if (c) { location.hash = `#/p/${c.dataset.p}`; return; }
  const f = e.target.closest(".fam");
  if (f) { const ps = famProducts(f.dataset.f); location.hash = ps.length === 1 ? `#/p/${ps[0].id}` : `#/aile/${f.dataset.f}`; }
};
$("#recent").onclick = (e) => { const b = e.target.closest(".job"); if (b) openJob(RECENT[+b.dataset.j]); };
function openJob(j) {
  if (j.product && PRODS[j.product]) {
    sessionStorage.setItem("studio.load", JSON.stringify(j.values || {}));
    location.hash = `#/p/${j.product}`;
  } else post("/api/open", { path: j.out_dir }).then(() => toast("Klasör açıldı.")).catch((e) => toast(e.message));
}

function renderFamily(key) {
  const f = CFG.families.find((x) => x.key === key);
  if (!f) return go("#/");
  $("#famTitle").textContent = f.label;
  $("#family .crumb").innerHTML = `<a href="#/">Ana sayfa</a> › ${esc(f.label)}`;
  $("#pgrid").innerHTML = famProducts(key).map((p) => `<button class="pcard" data-p="${p.id}">${p.group ? `<div class="grp">${esc(p.group)}</div>` : ""}` +
    `<h3>${esc(p.label)}</h3><p>${esc(p.description)}</p></button>`).join("") +
    (key === "isik" ? `<a class="pcard" href="#/donanim" style="text-decoration:none"><div class="grp">Ayarlar</div><h3>Donanım kataloğu</h3><p>LED şeritler, kontrolcüler ve difüzör malzemeleri: ölçüler, güç, fiyat.</p></a>` : "");
}
$("#pgrid").onclick = (e) => { const c = e.target.closest("[data-p]"); if (c) location.hash = `#/p/${c.dataset.p}`; };

// ------------------------------------------------------------------ search
let HITS = [], HIT = 0;
function search(q) {
  const words = norm(q).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const match = (s) => { const n = norm(s); return words.every((w) => n.includes(w)); };
  const ps = CFG.products.filter((p) => match(`${p.label} ${p.description} ${p.group || ""} ${CFG.families.find((f) => f.key === p.family).label}`))
    .slice(0, 8).map((p) => ({ kind: "p", p }));
  const js = RECENT.filter((j) => match(`${j.name} ${j.program}`)).slice(0, 5).map((j) => ({ kind: "j", j }));
  return [...ps, ...js];
}
function showHits() {
  const box = $("#results");
  if (!HITS.length) { box.hidden = !$("#q").value.trim(); box.innerHTML = `<div class="r muted">Sonuç yok.</div>`; return; }
  let html = "", last = "";
  HITS.forEach((h, i) => {
    const g = h.kind === "p" ? "Ürünler" : "Son işler";
    if (g !== last) { html += `<div class="g">${g}</div>`; last = g; }
    html += h.kind === "p"
      ? `<div class="r ${i === HIT ? "on" : ""}" data-i="${i}">${svg(h.p.family)}<div>${esc(h.p.label)}<small>${esc(h.p.description)}</small></div></div>`
      : `<div class="r ${i === HIT ? "on" : ""}" data-i="${i}">${h.j.thumb ? `<img src="${h.j.thumb}" alt="">` : svg("isler")}<div>${esc(h.j.name)}<small>${ago(h.j.when)}</small></div></div>`;
  });
  box.innerHTML = html;
  box.hidden = false;
}
function pick(i) {
  const h = HITS[i];
  if (!h) return;
  $("#q").value = ""; $("#results").hidden = true; $("#q").blur();
  if (h.kind === "p") location.hash = `#/p/${h.p.id}`; else openJob(h.j);
}
$("#q").oninput = () => { HITS = search($("#q").value); HIT = 0; showHits(); };
$("#q").onkeydown = (e) => {
  if (e.key === "ArrowDown") { HIT = Math.min(HIT + 1, HITS.length - 1); showHits(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { HIT = Math.max(HIT - 1, 0); showHits(); e.preventDefault(); }
  else if (e.key === "Enter") pick(HIT);
  else if (e.key === "Escape") { $("#results").hidden = true; $("#q").blur(); }
};
$("#results").onmousedown = (e) => { const r = e.target.closest("[data-i]"); if (r) { e.preventDefault(); pick(+r.dataset.i); } };
$("#q").onblur = () => setTimeout(() => ($("#results").hidden = true), 120);
document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#q").focus(); } });

// ------------------------------------------------------------------ form fields
function swatches(key, allowEmpty) {
  return `<div class="pal" data-pal="${key}">${allowEmpty ? `<button type="button" class="auto" data-c="">Otomatik</button>` : ""}` +
    CFG.palette.map(([h, n]) => `<button type="button" data-c="${h}" title="${esc(n)}" style="background:${h}"></button>`).join("") + "</div>";
}
function colorWidget(key, v, allowEmpty) {
  return `<div class="cp"><span class="chip ${v ? "" : "auto"}" data-open="${key}" style="${v ? `background:${v}` : ""}"></span>` +
    `<input class="hex" data-hex="${key}" value="${esc(v || "")}" placeholder="${allowEmpty ? "otomatik" : "#RRGGBB"}" maxlength="7" spellcheck="false">` +
    `<button type="button" class="ghost cap" data-capture="${key}" title="Fotoğraftan renk yakala">📷</button></div>${swatches(key, allowEmpty)}`;
}
function field(p) {
  const v = VALUES[p.key], id = `f_${p.key}`;
  const lbl = (extra = "") => `<div class="lbl"><label for="${id}">${esc(p.label)}</label><span>${extra}</span></div>`;
  let body;
  switch (p.type) {
    case "number": case "int": {
      const step = p.step ?? (p.type === "int" ? 1 : "any");
      if (p.min != null && p.max != null)
        body = lbl(esc(p.unit)) + `<div class="rng"><input type="range" data-k="${p.key}" min="${p.min}" max="${p.max}" step="${step === "any" ? (p.max - p.min) / 100 : step}" value="${v}">` +
          `<input type="number" id="${id}" data-k="${p.key}" min="${p.min}" max="${p.max}" step="${step}" value="${v}"></div>`;
      else body = lbl(esc(p.unit)) + `<input type="number" id="${id}" data-k="${p.key}" step="${step}" value="${v}">`;
      break;
    }
    case "bool":
      return `<div class="field" data-f="${p.key}"><label class="tg">${esc(p.label)}<input type="checkbox" data-k="${p.key}" ${v ? "checked" : ""}><span class="sw2"></span></label>${p.help ? `<div class="help">${esc(p.help)}</div>` : ""}</div>`;
    case "choice":
      body = lbl() + (p.options.length <= 4 && p.options.every(([, l]) => String(l).length < 26)
        ? `<div class="seg" data-seg="${p.key}">${p.options.map(([k, l]) => `<button type="button" data-v="${esc(k)}" class="${String(k) === String(v) ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`
        : `<select id="${id}" data-k="${p.key}">${p.options.map(([k, l]) => `<option value="${esc(k)}" ${String(k) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`);
      break;
    case "multi":
      body = lbl() + `<div class="seg" data-multi="${p.key}">${p.options.map(([k, l]) => `<button type="button" data-v="${esc(k)}" class="${(v || []).includes(k) ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`;
      break;
    case "font":
      body = lbl() + `<select id="${id}" data-k="${p.key}">${CFG.fonts.map(([k, l]) => `<option value="${esc(k)}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
      break;
    case "sheet":
      body = lbl() + `<select id="${id}" data-k="${p.key}">${CFG.sheets.sheets.map((s) => `<option value="${s.id}" ${s.id === (v || CFG.sheets.default) ? "selected" : ""}>${esc(s.label)}</option>`).join("")}</select>`;
      break;
    case "textarea":
      body = lbl() + `<textarea id="${id}" data-k="${p.key}" rows="2">${esc(v)}</textarea>`;
      break;
    case "color":
      body = lbl() + colorWidget(p.key, v, p.allow_empty);
      break;
    case "colors":
      body = lbl(`en çok ${p.max || 4}`) + `<div class="clist" data-colors="${p.key}">` + (v || []).map((c, i) =>
        `<span class="chip" data-ci="${i}" style="background:${c};width:30px;height:30px;border-radius:9px;border:1px solid rgba(0,0,0,.15);cursor:pointer" title="${c} — tıklayın: değiştir"></span>`).join("") +
        ((v || []).length < (p.max || 4) ? `<button type="button" class="add" data-add="${p.key}" title="renk ekle">+</button>` : "") +
        ((v || []).length > 1 ? `<button type="button" class="rm" data-rm="${p.key}" title="son rengi sil">−</button>` : "") +
        `<button type="button" class="ghost cap" data-capture="${p.key}" title="Fotoğraftan renk yakala (listeye ekler)">📷</button></div>` + swatches(p.key, false);
      break;
    case "file":
      body = lbl() + `<div class="filebox"><label>Dosya seç<input type="file" data-file="${p.key}" accept=".svg,.png,.jpg,.jpeg,.webp,.bmp" hidden></label>` +
        `<span>${esc(v ? String(v).split("/").pop().replace(/^[0-9a-f]{8}_/, "") : "seçilmedi")}</span>${v ? `<button type="button" class="x" data-clear="${p.key}">✕</button>` : ""}</div>`;
      break;
    case "logocolors": {
      if (!VALUES[p.source]) return `<div class="field" data-f="${p.key}" hidden></div>`;
      const lm = v && v.orig ? v : { orig: [], new: [], light: [] };
      body = lbl() + (lm.orig.length ? lm.orig.map((o, i) => `<div class="lcrow"><span class="chip" style="background:${o}" title="logodaki renk ${o}"></span>→` +
        `<span class="chip" style="background:${lm.new[i] || o}"></span><input class="hex" data-lc="${p.key}" data-i="${i}" value="${esc(lm.new[i] || o)}" maxlength="7">` +
        `<label class="tg mini"><input type="checkbox" data-lcl="${p.key}" data-i="${i}" ${(lm.light || []).includes(o) ? "checked" : ""}><span class="sw2"></span>ışık</label></div>`).join("")
        : `<div class="help">Renkler bulunuyor…</div>`);
      break;
    }
    case "holes":
      body = lbl() + `<div class="holes">${(v || []).map((h, i) => `<div class="hrow"><select data-hole="${p.key}" data-i="${i}" data-hk="type">` +
        HOLE_TYPES.map(([k, l]) => `<option value="${k}" ${k === h.type ? "selected" : ""}>${l}</option>`).join("") + `</select>` +
        ["w", "h", "x", "y"].map((k) => `<input type="number" step="0.5" data-hole="${p.key}" data-i="${i}" data-hk="${k}" value="${h[k] ?? ""}" title="${{ w: "genişlik", h: "yükseklik", x: "X", y: "Y" }[k]} (mm)" placeholder="${k.toUpperCase()}">`).join("") +
        `<button type="button" class="x" data-holerm="${p.key}" data-i="${i}" title="sil">✕</button></div>`).join("")}` +
        `<div class="hhead"><span>tür</span><span>gen.</span><span>yük.</span><span>X</span><span>Y</span></div>` +
        `<button type="button" class="ghost" data-holeadd="${p.key}">+ Delik ekle</button></div>`;
      break;
    case "theme":
      body = lbl() + `<div class="themes">${p.options.map((t) => `<button type="button" class="theme ${t.name === v ? "on" : ""}" data-theme="${esc(t.name)}">` +
        `<div class="swb">${[...new Set(Object.values(t.colors))].slice(0, 4).map((c) => `<i style="background:${c}"></i>`).join("")}</div>${esc(t.name)}</button>`).join("")}</div>`;
      break;
    case "place":
      body = lbl() + `<div class="place"><input data-placeq="${p.key}" placeholder="Yer ara ve Enter'a basın" value=""><div class="hits" data-hits="${p.key}"></div>` +
        `<div class="sel">${v && v.name ? `✓ ${esc(v.name)}` : ""}</div></div>`;
      break;
    case "route":
      body = lbl() + `<div class="place"><div class="filebox"><label>GPX yükle<input type="file" data-gpx="${p.key}" accept=".gpx" hidden></label><span>ya da</span></div>` +
        `<input data-routeq="${p.key}" placeholder="OpenStreetMap'te rota ara (ör. Likya Yolu)" style="margin-top:6px"><div class="hits" data-hits="${p.key}"></div>` +
        `<div class="sel">${v && v.name ? `✓ ${esc(v.name)}` : ""}</div></div>`;
      break;
    default:
      body = lbl() + `<input id="${id}" data-k="${p.key}" value="${esc(v)}">`;
  }
  return `<div class="field" data-f="${p.key}">${body}${p.help && p.type !== "bool" ? `<div class="help">${esc(p.help)}</div>` : ""}</div>`;
}
function sections() {
  const out = [];
  for (const p of PROD.params) {
    let s = out.find((x) => x.name === p.section);
    if (!s) out.push((s = { name: p.section, params: [] }));
    s.params.push(p);
  }
  return out;
}
function summary(s) {
  const bits = [];
  for (const p of s.params) {
    if (!visible(p)) continue;
    const v = VALUES[p.key];
    if (p.type === "place" || p.type === "route") { if (v && v.name) bits.push(v.name.split(",")[0]); }
    else if (p.type === "theme" || p.type === "font") bits.push(v);
    else if ((p.type === "number" || p.type === "int") && bits.length < 2) bits.push(`${v}${p.unit ? " " + p.unit : ""}`);
    else if ((p.type === "text" || p.type === "textarea") && v && bits.length < 2) bits.push(String(v).split("\n")[0]);
    if (bits.length >= 2) break;
  }
  return bits.join(" · ");
}
function visible(p) {
  return Object.entries(p.show_if || {}).every(([k, want]) => [].concat(want).map(String).includes(String(VALUES[k])));
}
function renderForm() {
  const open = store.get(`studio.open.${PROD.id}`, [0]);
  $("#form").innerHTML = sections().map((s, i) => `<div class="sec ${open.includes(i) ? "open" : ""}" data-s="${i}"><header><i>${i + 1}</i>${esc(s.name)}<em>${esc(summary(s))}</em></header>` +
    `<div class="in">${s.params.map(field).join("")}</div></div>`).join("");
  applyVisibility();
}
function applyVisibility() {
  for (const p of PROD.params) { const el = $(`[data-f="${p.key}"]`); if (el) el.hidden = !visible(p); }
  sections().forEach((s, i) => { const em = $(`.sec[data-s="${i}"] em`); if (em) em.textContent = summary(s); });
}
function setValue(k, v, rerender = false) {
  VALUES[k] = v;
  store.set(`studio.values.${PROD.id}`, VALUES);
  if (rerender) { const p = PROD.params.find((x) => x.key === k); const el = $(`[data-f="${k}"]`); if (p && el) el.outerHTML = field(p); }
  applyVisibility();
  changed();
}
function themeApply(name) {  // a Topo theme switches its own layers on/off
  const t = PROD.params.find((p) => p.type === "theme")?.options.find((x) => x.name === name);
  if (!t) return;
  for (const [k, on] of Object.entries(t.layers || {})) if (`layer_${k}` in VALUES) VALUES[`layer_${k}`] = !!on;
}

const form = $("#form");
form.addEventListener("click", (e) => {
  const h = e.target.closest(".sec > header");
  if (h) {
    h.parentElement.classList.toggle("open");
    store.set(`studio.open.${PROD.id}`, $$(".sec.open").map((s) => +s.dataset.s));
    return;
  }
  const seg = e.target.closest("[data-seg] button");
  if (seg) { const k = seg.parentElement.dataset.seg; $$("button", seg.parentElement).forEach((b) => b.classList.toggle("on", b === seg)); setValue(k, seg.dataset.v); return; }
  const mul = e.target.closest("[data-multi] button");
  if (mul) {
    const k = mul.parentElement.dataset.multi; mul.classList.toggle("on");
    setValue(k, $$("button.on", mul.parentElement).map((b) => b.dataset.v)); return;
  }
  const th = e.target.closest("[data-theme]");
  if (th) { themeApply(th.dataset.theme); VALUES.theme = th.dataset.theme; renderForm(); setValue("theme", th.dataset.theme); return; }
  const op = e.target.closest("[data-open]");
  if (op) { $(`[data-pal="${op.dataset.open}"]`).classList.toggle("open"); return; }
  const ci = e.target.closest("[data-ci]");
  if (ci) { const pal = $(`[data-pal="${ci.parentElement.dataset.colors}"]`); pal.dataset.target = ci.dataset.ci; pal.classList.add("open"); return; }
  const sw = e.target.closest(".pal button");
  if (sw) {
    const pal = sw.parentElement, k = pal.dataset.pal, p = PROD.params.find((x) => x.key === k);
    if (p.type === "colors") {
      const arr = [...(VALUES[k] || [])];
      const t = pal.dataset.target;
      if (t === "add") arr.push(sw.dataset.c); else arr[+(t ?? 0)] = sw.dataset.c;
      setValue(k, arr, true);
    } else setValue(k, sw.dataset.c, true);
    return;
  }
  const add = e.target.closest("[data-add]");
  if (add) { const pal = $(`[data-pal="${add.dataset.add}"]`); pal.dataset.target = "add"; pal.classList.add("open"); return; }
  const rm = e.target.closest("[data-rm]");
  if (rm) { const k = rm.dataset.rm; setValue(k, (VALUES[k] || []).slice(0, -1), true); return; }
  const cap = e.target.closest("[data-capture]");
  if (cap) { openCapture(cap.dataset.capture); return; }
  const ha = e.target.closest("[data-holeadd]");
  if (ha) { const k = ha.dataset.holeadd; setValue(k, [...(VALUES[k] || []), { type: "daire", w: 8, h: 8, x: 0, y: 0 }], true); return; }
  const hr = e.target.closest("[data-holerm]");
  if (hr) { const k = hr.dataset.holerm; setValue(k, (VALUES[k] || []).filter((_, i) => i !== +hr.dataset.i), true); return; }
  const clr = e.target.closest("[data-clear]");
  if (clr) {
    setValue(clr.dataset.clear, "", true);
    const lc = PROD.params.find((x) => x.type === "logocolors" && x.source === clr.dataset.clear);
    if (lc) setValue(lc.key, {}, true);
    return;
  }
  const hit = e.target.closest("[data-hit]");
  if (hit) { const k = hit.parentElement.dataset.hits; const val = JSON.parse(hit.dataset.hit); if (val.width_km && "width_km" in VALUES && val.width_km > VALUES.width_km) VALUES.width_km = Math.min(Math.round(val.width_km * 10) / 10, 30); setValue(k, val, true); return; }
});
form.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.k && t.type === "range") { const n = $(`input[type=number][data-k="${t.dataset.k}"]`); if (n) n.value = t.value; }
  if (t.dataset.k && t.type === "number") { const r = $(`input[type=range][data-k="${t.dataset.k}"]`); if (r) r.value = t.value; }
  if (t.dataset.hex !== undefined) {
    let h = t.value.trim(); if (/^[0-9a-f]{6}$/i.test(h)) h = "#" + h;
    const ok = /^#[0-9a-f]{6}$/i.test(h) || (h === "" && PROD.params.find((p) => p.key === t.dataset.hex).allow_empty);
    t.classList.toggle("bad", !ok);
  }
});
form.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.k) {
    const p = PROD.params.find((x) => x.key === t.dataset.k);
    const v = t.type === "checkbox" ? t.checked : (p.type === "number" || p.type === "int") ? Number(t.value) : t.value;
    setValue(t.dataset.k, v);
  } else if (t.dataset.hex !== undefined) {
    let h = t.value.trim().toUpperCase(); if (/^[0-9A-F]{6}$/.test(h)) h = "#" + h;
    if (/^#[0-9A-F]{6}$/.test(h) || h === "") setValue(t.dataset.hex, h, true);
  } else if (t.dataset.file || t.dataset.gpx) upload(t);
  else if (t.dataset.lc !== undefined || t.dataset.lcl !== undefined) {
    const k = t.dataset.lc || t.dataset.lcl, i = +t.dataset.i, lm = structuredClone(VALUES[k]);
    if (t.dataset.lc !== undefined) {
      let h = t.value.trim().toUpperCase(); if (/^[0-9A-F]{6}$/.test(h)) h = "#" + h;
      if (!/^#[0-9A-F]{6}$/.test(h)) { t.classList.add("bad"); return; }
      lm.new[i] = h;
    } else {
      const o = lm.orig[i];
      lm.light = (lm.light || []).filter((x) => x !== o).concat(t.checked ? [o] : []);
    }
    setValue(k, lm, true);
  } else if (t.dataset.hole !== undefined) {
    const k = t.dataset.hole, rows = structuredClone(VALUES[k] || []);
    rows[+t.dataset.i][t.dataset.hk] = t.dataset.hk === "type" ? t.value : (t.value === "" ? null : Number(t.value));
    setValue(k, rows);
  }
});
form.addEventListener("keydown", async (e) => {
  const t = e.target;
  if (e.key !== "Enter" || !(t.dataset.placeq || t.dataset.routeq)) return;
  e.preventDefault();
  const k = t.dataset.placeq || t.dataset.routeq, box = $(`[data-hits="${k}"]`);
  box.innerHTML = `<span class="muted">Aranıyor…</span>`;
  try {
    if (t.dataset.placeq) {
      const hits = await api(`/api/geocode?q=${encodeURIComponent(t.value)}`);
      box.innerHTML = hits.length ? hits.map((h) => `<button type="button" data-hit='${esc(JSON.stringify({ name: h.name, lat: h.lat, lon: h.lon, width_km: h.width_km }))}'>${esc(h.name)}</button>`).join("") : `<span class="muted">Bulunamadı.</span>`;
    } else {
      const hits = await api(`/api/routes?q=${encodeURIComponent(t.value)}`);
      box.innerHTML = hits.length ? hits.map((h) => `<button type="button" data-hit='${esc(JSON.stringify({ name: h.name, osm_relation: h.relation_id }))}'>${esc(h.name)} <span class="muted">${esc(h.type || "")}</span></button>`).join("") : `<span class="muted">Bulunamadı.</span>`;
    }
  } catch (err) { box.innerHTML = `<span class="muted">${esc(err.message)}</span>`; }
});
async function upload(input) {
  const f = input.files[0];
  if (!f) return;
  try {
    const r = await api(`/api/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f });
    if (input.dataset.gpx) {
      const g = await post("/api/gpx", { path: r.path });
      setValue(input.dataset.gpx, { gpx: r.path, name: g.name || f.name }, true);
    } else {
      setValue(input.dataset.file, r.path, true);
      const lc = PROD.params.find((x) => x.type === "logocolors" && x.source === input.dataset.file);
      if (lc) {
        VALUES[lc.key] = {};
        const fe = $(`[data-f="${lc.key}"]`); if (fe) fe.outerHTML = field(lc);
        try {
          const { colors } = await api(`/api/logo-colors?path=${encodeURIComponent(r.path)}`);
          setValue(lc.key, { orig: colors, new: [...colors], light: [] }, true);
        } catch (err) { toast(err.message); }
      }
    }
  } catch (err) { toast(err.message); }
}

// ------------------------------------------------------------------ 3D viewer (three.js; a server picture when WebGL is missing)
let T = null, renderer = null, scene, camera, controls, current = null, loader;
async function initThree() {
  if (T !== null) return !!renderer;
  try {
    const gl = document.createElement("canvas").getContext("webgl2") || document.createElement("canvas").getContext("webgl");
    if (!gl) throw new Error("no webgl");
    T = await import("three");
    const { OrbitControls } = await import("three/addons/controls/OrbitControls.js");
    const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
    const canvas = $("#three");
    renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    scene = new T.Scene();
    camera = new T.PerspectiveCamera(32, 1, 0.1, 10000);
    scene.add(new T.HemisphereLight(0xffffff, 0xd8c8b4, 1.1));
    const d1 = new T.DirectionalLight(0xffffff, 1.6); d1.position.set(-1, 2, 1.5); scene.add(d1);
    const d2 = new T.DirectionalLight(0xffffff, 0.5); d2.position.set(1.5, 0.5, -1); scene.add(d2);
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    loader = new GLTFLoader();
    new ResizeObserver(resize).observe($("#viewer"));
    resize();
    (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
    return true;
  } catch (e) {
    T = false; renderer = null;
    $$("#views button").forEach((b) => (b.hidden = b.dataset.v !== "img"));
    VIEW = "img";
    return false;
  }
}
function resize() {
  if (!renderer) return;
  const r = $("#viewer").getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(r.height, 1);
  camera.updateProjectionMatrix();
}
function frame(view) {
  if (!current) return;
  const box = new T.Box3().setFromObject(current), size = box.getSize(new T.Vector3()), c = box.getCenter(new T.Vector3());
  const r = size.length() / 2, dist = r / Math.sin((camera.fov * Math.PI) / 360) * 1.05;
  const dir = view === "front" ? new T.Vector3(0, 0, 1) : view === "top" ? new T.Vector3(0, 1, 0.0001) : new T.Vector3(-0.75, 0.75, 1.1);
  camera.position.copy(c).add(dir.normalize().multiplyScalar(dist));
  camera.near = dist / 100; camera.far = dist * 10; camera.updateProjectionMatrix();
  controls.target.copy(c); controls.update();
}
async function show(res) {
  $("#empty").hidden = true;
  const useImg = VIEW === "img" || !(await initThree()) || !res.glb;
  $("#prevImg").hidden = !useImg;
  $("#three").style.visibility = useImg ? "hidden" : "visible";
  if (res.png) $("#prevImg").src = res.png + `?t=${Date.now()}`;
  if (!renderer || !res.glb) return;
  loader.load(res.glb, (g) => {
    if (current) scene.remove(current);
    current = g.scene;
    current.traverse((o) => { if (o.isMesh) { o.material.side = T.DoubleSide; } });
    scene.add(current);
    frame(VIEW === "img" ? "34" : VIEW);
  }, undefined, () => { $("#prevImg").hidden = false; $("#three").style.visibility = "hidden"; });
}
$("#views").onclick = async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  VIEW = b.dataset.v;
  $$("#views button").forEach((x) => x.classList.toggle("on", x === b));
  if (RESULT) {
    if (VIEW === "img") { $("#prevImg").hidden = false; $("#three").style.visibility = "hidden"; }
    else if (renderer) { $("#prevImg").hidden = true; $("#three").style.visibility = "visible"; frame(VIEW); }
  }
};

// ------------------------------------------------------------------ jobs
let previewTimer = null, previewBusy = false, jobToken = 0;
const AUTO = (p) => p.program === "maker" || p.program === "kaligraf";
function changed() {
  $("#btnPreview").classList.add("dirty");
  clearTimeout(previewTimer);
  if (AUTO(PROD)) previewTimer = setTimeout(preview, 900);
}
async function runJob(kind, extra = {}) {
  const { id } = await post("/api/jobs", { kind, product: PROD.id, values: VALUES, ...extra });
  for (;;) {
    await new Promise((r) => setTimeout(r, 600));
    const st = await api(`/api/jobs/${id}`);
    $("#busyMsg").textContent = `${st.progress || "Hazırlanıyor…"} (${Math.round(st.seconds)} sn)`;
    if (st.status === "done") return st.result;
    if (st.status === "error") throw new Error(st.error);
  }
}
async function preview() {
  if (previewBusy) { clearTimeout(previewTimer); previewTimer = setTimeout(preview, 700); return; }
  previewBusy = true;
  const tok = ++jobToken;
  $("#busy").hidden = false; $("#busyMsg").textContent = "Önizleme hazırlanıyor…";
  try {
    const r = await runJob("preview");
    if (tok !== jobToken) return;
    RESULT = r; MADE = null;
    $("#btnPreview").classList.remove("dirty");
    await show(r);
    renderStrip(); renderSide();
  } catch (e) {
    if (tok === jobToken) { renderSide(e.message); }
  } finally { previewBusy = false; $("#busy").hidden = true; }
}
$("#btnPreview").onclick = () => { clearTimeout(previewTimer); preview(); };
$("#btnMake").onclick = async () => {
  const b = $("#btnMake");
  b.disabled = true; $("#busy").hidden = false; $("#busyMsg").textContent = "Dosyalar hazırlanıyor…";
  try {
    MADE = await runJob("make");
    if (MADE.filaments && MADE.filaments.length) RESULT = { ...(RESULT || {}), filaments: MADE.filaments, estimate: MADE.estimate };
    renderStrip(); renderSide();
    toast("Baskı dosyaları hazır.");
    api("/api/recent").then((r) => (RECENT = r));
  } catch (e) { renderSide(e.message); }
  finally { b.disabled = false; $("#busy").hidden = true; }
};
function renderStrip() {
  const fs = (RESULT && RESULT.filaments) || [];
  const el = $("#strip");
  el.hidden = !fs.length;
  if (!fs.length) return;
  el.innerHTML = `<h3>Filament</h3>` + fs.map((f, i) => {
    const m = nearestSlot(f.color);
    const low = m && f.grams != null && f.grams > m.slot.grams;
    const where = m ? `${m.exact ? "" : "≈ "}${m.slot.slot}. yuva` : "yazıcıda yok";
    const dark = (() => { const [r, g, b] = hexRgb(f.color); return 0.299 * r + 0.587 * g + 0.114 * b < 140; })();
    return `<div class="fil ${m ? "" : "miss"} ${low ? "low" : ""}" title="${f.color} · ${esc(where)}${low ? " · yetmeyebilir" : ""}">` +
      `<i style="background:${f.color};color:${dark ? "#fff" : "#3a2e28"}">${m ? m.slot.slot : "?"}</i>` +
      `<div><b>${esc((f.roles || []).join(", ") || f.color)}</b><small>${f.grams != null ? `${f.grams} g · ` : ""}${esc(where)}</small></div></div>`;
  }).join("");
}
function renderSide(error) {
  const r = MADE || RESULT || {};
  const e = r.estimate || {};
  const kv = [["Filament", e.grams != null ? `≈ ${Math.round(e.grams)} g` : "—"], ["Süre", e.text ? `≈ ${e.text}` : "—"]];
  if (e.colour_changes != null) kv.push(["Renk değişimi", e.colour_changes]);
  $("#est").innerHTML = kv.map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join("");
  let notes = "";
  if (error) notes += `<div class="note err">${esc(error)}</div>`;
  for (const i of r.info || []) notes += `<div class="note info">${esc(i)}</div>`;
  for (const w of r.warnings || []) notes += `<div class="note warn">${esc(w)}</div>`;
  const fs = r.filaments || [];
  const miss = fs.filter((f) => !nearestSlot(f.color));
  if (fs.length && !miss.length && !error) notes += `<div class="note ok">Bütün renkler yazıcıda yüklü.</div>`;
  if (miss.length) notes += `<div class="note warn">${miss.length} renk yazıcıda yüklü değil (sarı kesik çizgili). Filamentleri değiştirin ya da rengi yuvadakine yaklaştırın.</div>`;
  if (fs.length > 4) notes += `<div class="note err">${fs.length} renk var; yazıcı en çok 4 renk basar.</div>`;
  $("#notes").innerHTML = notes;
  if (MADE && MADE.files) {
    const links = Object.entries(MADE.files).filter(([k]) => FILE_TR[k]).map(([k, u]) => `<a href="${u}" target="_blank">${esc(FILE_TR[k])}</a>`).join("");
    const stlHtml = (MADE.stls && MADE.stls.length)
      ? `<h3 style="margin-top:10px">Harf / Parça STL Dosyaları (${MADE.stls.length} adet)</h3><div class="files">` +
        MADE.stls.map((u) => { const n = decodeURIComponent(u.split("/").pop()); return `<a href="${u}" download="${esc(n)}">📦 ${esc(n)}</a>`; }).join("") + `</div>`
      : "";
    $("#outputs").innerHTML = `<h3>Çıktılar</h3><div class="files">${links}<button type="button" id="openDir">Klasörü aç</button>` +
      `${MADE.files["3mf"] ? `<button type="button" id="check">Baskı yolunu kontrol et</button>` : ""}</div>${stlHtml}<div id="checkOut"></div>`;
    $("#openDir").onclick = () => post("/api/open", { path: MADE.out_dir }).catch((err) => toast(err.message));
    const c = $("#check");
    if (c) c.onclick = checkPrint;
  } else $("#outputs").innerHTML = "";
}
async function checkPrint() {
  const out = $("#checkOut");
  out.innerHTML = `<div class="note info">OrcaSlicer'da dilimleniyor… (yarım dakika kadar)</div>`;
  try {
    const { id } = await post("/api/check", { out_dir: MADE.out_dir });
    let st;
    for (;;) { await new Promise((r) => setTimeout(r, 1000)); st = await api(`/api/jobs/${id}`); if (st.status !== "running") break; }
    if (st.status === "error") throw new Error(st.error);
    const lv = { iyi: "ok", dikkat: "warn", sorun: "err" };
    out.innerHTML = st.result.plates.map((p) => `<h3 style="margin-top:10px">Tabla ${p.plate}: ${p.slicer_grams ?? ""} g · ${esc(p.time || "")}</h3>` +
      p.findings.map((f) => `<div class="note ${lv[f.seviye]}">${esc(f.mesaj)}</div>`).join("")).join("");
  } catch (err) { out.innerHTML = `<div class="note err">${esc(err.message)}</div>`; }
}

// ------------------------------------------------------------------ colour capture (pick a colour from a photo)
let CAP_KEY = null, CAP_HEX = null;
function openCapture(key) {
  CAP_KEY = key; CAP_HEX = null;
  $("#capInfo").textContent = "Bir fotoğraf seçin ya da yapıştırın, sonra renge tıklayın (7×7 piksel ortancası alınır).";
  $("#capUse").disabled = true;
  $("#capEye").hidden = !window.EyeDropper;
  $("#capDlg").showModal();
}
function capImage(blob) {
  const img = new Image();
  img.onload = () => {
    const c = $("#capCanvas"), k = Math.min(1, 640 / img.width, 420 / img.height);
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    c.hidden = false;
  };
  img.src = URL.createObjectURL(blob);
}
async function capPicked(hex) {
  CAP_HEX = hex.toUpperCase();
  $("#capSw").style.background = CAP_HEX;
  $("#capUse").disabled = false;
  $("#capInfo").textContent = CAP_HEX;
  try { const c2 = await api(`/api/color-name?hex=${encodeURIComponent(CAP_HEX)}`); $("#capInfo").textContent = `${c2.text} · ${c2.ral}`; } catch (err) {}
}
$("#capEye").onclick = async () => {
  try { const r = await new EyeDropper().open(); capPicked(r.sRGBHex.startsWith("#") ? r.sRGBHex : "#" + r.sRGBHex); } catch (e) {}
};
document.addEventListener("paste", (e) => {
  if (!$("#capDlg").open) return;
  const it = [...(e.clipboardData?.items || [])].find((x) => x.type.startsWith("image/"));
  if (it) { capImage(it.getAsFile()); e.preventDefault(); }
});
$("#capFile").onchange = (e) => { const f = e.target.files[0]; if (f) capImage(f); };
$("#capCanvas").onclick = async (e) => {
  const c = e.target, r = c.getBoundingClientRect();
  const x = Math.round((e.clientX - r.left) * c.width / r.width), y = Math.round((e.clientY - r.top) * c.height / r.height);
  const d = c.getContext("2d").getImageData(Math.max(0, x - 3), Math.max(0, y - 3), 7, 7).data;
  const med = (o) => { const v = []; for (let i = o; i < d.length; i += 4) v.push(d[i]); v.sort((a, b) => a - b); return v[v.length >> 1]; };
  capPicked("#" + [0, 1, 2].map((o) => med(o).toString(16).padStart(2, "0")).join(""));  // 7x7 median: one odd pixel is ignored
};
$("#capUse").onclick = (e) => {
  e.preventDefault();
  if (!CAP_HEX || !CAP_KEY) return;
  const p = PROD.params.find((x) => x.key === CAP_KEY);
  if (p.type === "colors") setValue(CAP_KEY, [...(VALUES[CAP_KEY] || []), CAP_HEX].slice(0, p.max || 4), true);
  else setValue(CAP_KEY, CAP_HEX, true);
  $("#capDlg").close();
};

// ------------------------------------------------------------------ Glow hardware catalogue
let HW = null, HWK = "leds";
async function openHardware() {
  try { HW = await api("/api/hardware"); } catch (e) { $("#hwMsg").innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
  $("#hwInfo").textContent = `LED, kontrolcü ve difüzör kayıtları. Değerler gerçek ürün ölçülene kadar varsayımdır (not sütununa bakın). ` +
    (HW.user ? `Kendi kaydınız kullanılıyor: ${HW.path}` : "Şu an varsayılan katalog kullanılıyor.");
  $("#hwMsg").innerHTML = "";
  renderHw();
}
function renderHw() {
  const cols = HW.cols[HWK], rows = HW.rows[HWK];
  $$("#hwTabs button").forEach((b) => b.classList.toggle("on", b.dataset.k === HWK));
  $("#hwTable").innerHTML = `<thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}<th></th></tr></thead><tbody>` + rows.map((r, i) => `<tr>` +
    r.map((v, j) => typeof HW.new[HWK][j] === "boolean"
      ? `<td><input type="checkbox" data-r="${i}" data-c="${j}" ${v ? "checked" : ""}></td>`
      : `<td><input data-r="${i}" data-c="${j}" value="${esc(v ?? "")}" ${typeof HW.new[HWK][j] === "number" ? 'inputmode="decimal"' : ""}></td>`).join("") +
    `<td class="act"><button class="x" data-dup="${i}" title="çoğalt">⧉</button><button class="x" data-del="${i}" title="sil">✕</button></td></tr>`).join("") + "</tbody>";
}
$("#hwTabs").onclick = (e) => { const b = e.target.closest("button"); if (b) { HWK = b.dataset.k; renderHw(); } };
$("#hwTable").addEventListener("change", (e) => {
  const t = e.target, r = +t.dataset.r, c = +t.dataset.c, proto = HW.new[HWK][c];
  HW.rows[HWK][r][c] = t.type === "checkbox" ? t.checked : (typeof proto === "number" || proto === null) && t.value.trim() !== "" && !isNaN(+t.value.replace(",", ".")) ? +t.value.replace(",", ".") : t.value;
});
$("#hwTable").onclick = (e) => {
  const d = e.target.closest("[data-dup]"), x = e.target.closest("[data-del]");
  const rows = HW.rows[HWK];
  if (d) { const src = rows[+d.dataset.dup], ids = new Set(rows.map((r) => String(r[0]))); let n = 2; while (ids.has(`${src[0]}_kopya${n}`)) n++;
    rows.push([`${src[0]}_kopya${n}`, `${src[1]} (kopya)`, ...src.slice(2)]); renderHw(); }
  if (x) { rows.splice(+x.dataset.del, 1); renderHw(); }
};
$("#hwNew").onclick = () => {
  const ids = new Set(HW.rows[HWK].map((r) => String(r[0]))); let n = 1; while (ids.has(`yeni_${n}`)) n++;
  HW.rows[HWK].push([`yeni_${n}`, ...HW.new[HWK].slice(1)]); renderHw();
};
$("#hwVal").onclick = async () => {
  try { const r = await post("/api/hardware/validate", { rows: HW.rows });
    $("#hwMsg").innerHTML = r.errors.length ? r.errors.map((x) => `<div class="note err">${esc(x)}</div>`).join("") : `<div class="note ok">Kayıtlar geçerli.</div>`; }
  catch (e) { $("#hwMsg").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
};
$("#hwSave").onclick = async () => {
  try { const r = await post("/api/hardware", { rows: HW.rows }, "PUT"); await reloadConfig();
    $("#hwMsg").innerHTML = `<div class="note ok">Kaydedildi: ${esc(r.path)}. Işıklı ürün formları yeni listeyi kullanıyor.</div>`; }
  catch (e) { $("#hwMsg").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
};
$("#hwReset").onclick = async () => {
  if (!confirm("Kendi donanım kaydınız silinip varsayılan katalog kullanılacak. Emin misiniz?")) return;
  await api("/api/hardware", { method: "DELETE" }); await reloadConfig(); await openHardware();
  $("#hwMsg").innerHTML = `<div class="note ok">Varsayılan katalog geri yüklendi.</div>`;
};
async function reloadConfig() { CFG = await api("/api/config"); PRODS = Object.fromEntries(CFG.products.map((p) => [p.id, p])); }

// ------------------------------------------------------------------ editor
function renderRail(fam) {
  const items = [["#/", "home", "Ana"], ...CFG.families.map((f) => [`#/aile/${f.key}`, f.key, f.label.split(" ")[0]]), ["#/donanim", "donanim", "Donanım"], ["#/isler", "isler", "İşler"]];
  $("#rail").innerHTML = items.map(([h, k, l], i) => `<a href="${h}" class="${k === fam ? "on" : ""}" ${i === items.length - 1 ? 'style="margin-top:auto;margin-bottom:14px"' : ""}>${svg(k)}${esc(l)}</a>`).join("");
}
function openEditor(id) {
  const p = PRODS[id];
  if (!p) return go("#/");
  PROD = p; RESULT = null; MADE = null;
  const fam = CFG.families.find((f) => f.key === p.family);
  renderRail(p.family);
  const sibs = famProducts(p.family);
  $("#crumb").innerHTML = `<a href="#/aile/${fam.key}">${esc(fam.label)}</a> › ` + (sibs.length > 1
    ? `<select class="prodsel" id="prodsel">${sibs.map((s) => `<option value="${s.id}" ${s.id === id ? "selected" : ""}>${esc(s.label)}</option>`).join("")}</select>` : esc(p.label));
  const ps = $("#prodsel");
  if (ps) ps.onchange = () => (location.hash = `#/p/${ps.value}`);
  $("#ptitle").textContent = p.label;
  $("#pdesc").textContent = p.description;
  const defaults = Object.fromEntries(p.params.map((x) => [x.key, x.default]));
  let loaded = null;
  try { loaded = JSON.parse(sessionStorage.getItem("studio.load") || "null"); } catch (e) {}
  sessionStorage.removeItem("studio.load");
  VALUES = { ...defaults, ...(loaded || store.get(`studio.values.${id}`, {})) };
  for (const k of Object.keys(VALUES)) if (!(k in defaults)) delete VALUES[k];
  renderForm();
  $("#strip").hidden = true; $("#prevImg").hidden = true; $("#empty").hidden = false;
  if (current && scene) { scene.remove(current); current = null; }
  renderSide();
  $("#btnPreview").classList.add("dirty");
  const ready = p.params.every((x) => !((x.type === "place" || x.type === "route") && !(VALUES[x.key] && VALUES[x.key].name)));
  $("#empty").innerHTML = `<span>${ready ? (AUTO(p) ? "Önizleme hazırlanıyor…" : "Ayarları yapıp <b>↻ Önizle</b>'ye basın.") : "Önce 1. adımda yeri ya da rotayı seçin."}</span>`;
  if (ready && AUTO(p)) preview();
}

// ------------------------------------------------------------------ routing
function go(h) { location.hash = h; }
function route() {
  const h = location.hash || "#/";
  $$(".view").forEach((v) => (v.hidden = true));
  if (h.startsWith("#/p/")) { $("#editor").hidden = false; openEditor(decodeURIComponent(h.slice(4))); return; }
  if (h.startsWith("#/aile/")) { $("#family").hidden = false; renderFamily(h.slice(7)); return; }
  if (h === "#/donanim") { $("#hw").hidden = false; openHardware(); return; }
  if (h === "#/isler") { $("#home").hidden = false; renderHome(); setTimeout(() => $("#recent").scrollIntoView({ behavior: "smooth" }), 50); return; }
  $("#home").hidden = false;
  renderHome();
}
window.addEventListener("hashchange", route);

[CFG, RECENT, FIL] = await Promise.all([api("/api/config"), api("/api/recent"), api("/api/filaments")]);
PRODS = Object.fromEntries(CFG.products.map((p) => [p.id, p]));
renderSlots();
const legacy = location.hash.slice(1);  // studio open --app <program> / #<product id>
if (legacy && !legacy.startsWith("/")) {
  const p = PRODS[legacy] || CFG.products.find((x) => x.program === legacy || x.id === `topo_${legacy}` || x.id === `maker_${legacy}`);
  location.hash = p ? `#/p/${p.id}` : "#/";
} else route();
