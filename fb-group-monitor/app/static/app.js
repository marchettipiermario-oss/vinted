"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const SECRET_KEYS = ["discord_webhook_url", "telegram_bot_token", "whatsapp_apikey"];
let groupsCache = [];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Errore ${res.status}`);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

async function run(fn) {
  try { await fn(); } catch (e) { toast(e.message); }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
}

function fmtPrice(p) {
  return p == null ? "" : p.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

// ---------- tab ----------
$$("#tabs button").forEach(b => b.addEventListener("click", () => {
  $$("#tabs button").forEach(x => x.classList.toggle("active", x === b));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
  const loaders = { matches: loadMatches, groups: loadGroups, rules: loadRules, settings: loadSettings };
  if (loaders[b.dataset.tab]) run(loaders[b.dataset.tab]);
}));

// ---------- stato ----------
async function loadStatus() {
  const s = await api("/api/status");
  $("#st-phase").textContent = s.paused ? "In pausa" : s.phase;
  $("#st-login").innerHTML = s.logged_in === null
    ? '<span class="warn-text">browser non avviato</span>'
    : s.logged_in ? '<span class="ok-text">collegato</span>' : '<span class="err-text">non collegato</span>';
  $("#st-group").textContent = s.current_group || "—";
  $("#st-next").textContent = s.paused ? "—" : fmtDate(s.next_cycle_at);
  $("#st-counts").textContent = `${s.groups} · ${s.rules}`;
  $("#st-posts").textContent = s.posts_seen;
  $("#st-channels").innerHTML = s.channels.length
    ? esc(s.channels.join(", "))
    : '<span class="warn-text">nessuna configurata</span>';
  $("#btn-resume").classList.toggle("hidden", !s.paused);
  $("#btn-pause").classList.toggle("hidden", s.paused);
  const alert = $("#alert");
  alert.textContent = s.last_error || "";
  alert.classList.toggle("hidden", !s.last_error);
}

$("#btn-login").addEventListener("click", () => run(async () => {
  toast("Apro Chrome… accedi a Facebook nella finestra.");
  await api("/api/browser/login", { method: "POST" });
  loadStatus();
}));
$("#btn-resume").addEventListener("click", () => run(async () => {
  await api("/api/monitor/resume", { method: "POST" });
  toast("Monitor avviato");
  loadStatus();
}));
$("#btn-pause").addEventListener("click", () => run(async () => {
  await api("/api/monitor/pause", { method: "POST" });
  toast("Monitor in pausa");
  loadStatus();
}));
$("#btn-run").addEventListener("click", () => run(async () => {
  await api("/api/monitor/run-now", { method: "POST" });
  toast("Controllo avviato");
}));

// ---------- post trovati ----------
async function loadMatches() {
  const rows = await api("/api/matches");
  const list = $("#matches-list");
  if (!rows.length) {
    list.innerHTML = '<p class="empty">Ancora nessun post trovato.</p>';
    return;
  }
  list.innerHTML = rows.map(m => {
    const notify = m.notified
      ? '<span class="ok-text">notificato</span>'
      : `<span class="warn-text">${esc(m.notify_error || "non notificato")}</span>`;
    return `<article class="item">
      <div class="meta">
        <span>${fmtDate(m.created_at)}</span>
        <span>${esc(m.group_name || m.group_url || "")}</span>
        <span>Regola: ${esc(m.rule_name || "—")}</span>
        ${m.author ? `<span>${esc(m.author)}</span>` : ""}
        ${notify}
      </div>
      ${m.price != null ? `<div class="price">${fmtPrice(m.price)}</div>` : ""}
      <div class="text">${esc((m.text || "").slice(0, 600))}</div>
      ${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">Apri il post</a>` : ""}
    </article>`;
  }).join("");
}
$("#btn-refresh-matches").addEventListener("click", () => run(loadMatches));

// ---------- gruppi ----------
async function loadGroups() {
  groupsCache = await api("/api/groups");
  const body = $("#groups-body");
  if (!groupsCache.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">Nessun gruppo. Aggiungi il link di un gruppo di cui fai parte.</td></tr>';
  } else {
    body.innerHTML = groupsCache.map(g => `<tr>
      <td><input type="checkbox" data-toggle="${g.id}" ${g.enabled ? "checked" : ""}></td>
      <td><strong>${esc(g.name || "(nome alla prima lettura)")}</strong><br>
          <a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.url)}</a></td>
      <td>${fmtDate(g.last_checked_at)}</td>
      <td>${g.last_error ? `<span class="err-text">${esc(g.last_error)}</span>` : (g.last_checked_at ? '<span class="ok-text">ok</span>' : "in attesa")}</td>
      <td><button class="small danger" data-del="${g.id}">Rimuovi</button></td>
    </tr>`).join("");
  }
  fillGroupSelect();
}

$("#groups-body").addEventListener("change", e => {
  const id = e.target.dataset.toggle;
  if (id) run(() => api(`/api/groups/${id}`, { method: "PATCH", body: { enabled: e.target.checked } }));
});
$("#groups-body").addEventListener("click", e => {
  const id = e.target.dataset.del;
  if (id && confirm("Rimuovere questo gruppo?")) {
    run(async () => { await api(`/api/groups/${id}`, { method: "DELETE" }); loadGroups(); });
  }
});
$("#group-form").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  run(async () => {
    await api("/api/groups", { method: "POST", body: { url: f.url.value, name: f.name.value } });
    f.reset();
    toast("Gruppo aggiunto");
    loadGroups();
  });
});
$("#btn-bulk").addEventListener("click", () => run(async () => {
  const lines = $("#bulk-groups").value.split("\n").map(l => l.trim()).filter(Boolean);
  let ok = 0; const bad = [];
  for (const url of lines) {
    try { await api("/api/groups", { method: "POST", body: { url } }); ok++; }
    catch { bad.push(url); }
  }
  $("#bulk-groups").value = bad.join("\n");
  toast(`${ok} gruppi aggiunti${bad.length ? `, ${bad.length} link non validi (rimasti nel riquadro)` : ""}`);
  loadGroups();
}));

// ---------- regole ----------
function fillGroupSelect(selected = null) {
  const sel = $("#rule-form select[name=group_ids]");
  const keep = selected ?? $$("option:checked", sel).map(o => Number(o.value));
  sel.innerHTML = groupsCache.map(g =>
    `<option value="${g.id}" ${keep.includes(g.id) ? "selected" : ""}>${esc(g.name || g.url)}</option>`).join("");
}

async function loadRules() {
  if (!groupsCache.length) groupsCache = await api("/api/groups");
  fillGroupSelect();
  const rules = await api("/api/rules");
  const names = Object.fromEntries(groupsCache.map(g => [g.id, g.name || g.url]));
  const list = $("#rules-list");
  if (!rules.length) {
    list.innerHTML = '<p class="empty">Nessuna regola. Senza regole il monitor legge i post ma non notifica nulla.</p>';
    return;
  }
  list.innerHTML = rules.map(r => {
    const price = [r.min_price != null ? `da ${fmtPrice(r.min_price)}` : "", r.max_price != null ? `fino a ${fmtPrice(r.max_price)}` : ""].filter(Boolean).join(" ");
    return `<article class="item">
      <div class="row-between">
        <strong>${esc(r.name)} ${r.enabled ? "" : '<span class="warn-text">(disattivata)</span>'}</strong>
        <span>
          <button class="small" data-edit="${r.id}">Modifica</button>
          <button class="small" data-onoff="${r.id}">${r.enabled ? "Disattiva" : "Attiva"}</button>
          <button class="small danger" data-delrule="${r.id}">Elimina</button>
        </span>
      </div>
      <div class="meta">
        ${r.keywords ? `<span>Parole: ${esc(r.keywords)}</span>` : ""}
        ${r.exclude ? `<span>Escluse: ${esc(r.exclude)}</span>` : ""}
        ${price ? `<span>Prezzo ${price}</span>` : ""}
        ${r.require_price ? "<span>solo con prezzo</span>" : ""}
        <span>Gruppi: ${r.group_ids ? esc(r.group_ids.map(id => names[id] || `#${id}`).join(", ")) : "tutti"}</span>
      </div>
    </article>`;
  }).join("");
  list.dataset.rules = JSON.stringify(rules);
}

function ruleFromForm(f) {
  const num = v => (v === "" ? null : Number(v));
  const groupIds = $$("option:checked", f.group_ids).map(o => Number(o.value));
  return {
    name: f.name.value.trim(),
    keywords: f.keywords.value,
    exclude: f.exclude.value,
    min_price: num(f.min_price.value),
    max_price: num(f.max_price.value),
    require_price: f.require_price.checked,
    group_ids: groupIds.length ? groupIds : null,
    enabled: f.dataset.enabled !== "false",
  };
}

function resetRuleForm() {
  const f = $("#rule-form");
  f.reset();
  f.id.value = "";
  delete f.dataset.enabled;
  fillGroupSelect([]);
  $("#btn-rule-cancel").classList.add("hidden");
}

$("#rule-form").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  run(async () => {
    const id = f.id.value;
    await api(id ? `/api/rules/${id}` : "/api/rules", { method: id ? "PUT" : "POST", body: ruleFromForm(f) });
    toast("Regola salvata");
    resetRuleForm();
    loadRules();
  });
});
$("#btn-rule-cancel").addEventListener("click", resetRuleForm);

$("#rules-list").addEventListener("click", e => {
  const rules = JSON.parse($("#rules-list").dataset.rules || "[]");
  const find = id => rules.find(r => r.id === Number(id));
  const { edit, onoff, delrule } = e.target.dataset;
  if (edit) {
    const r = find(edit), f = $("#rule-form");
    f.id.value = r.id;
    f.name.value = r.name;
    f.keywords.value = r.keywords;
    f.exclude.value = r.exclude;
    f.min_price.value = r.min_price ?? "";
    f.max_price.value = r.max_price ?? "";
    f.require_price.checked = r.require_price;
    f.dataset.enabled = String(r.enabled);
    fillGroupSelect(r.group_ids || []);
    $("#btn-rule-cancel").classList.remove("hidden");
    f.scrollIntoView({ behavior: "smooth" });
  } else if (onoff) {
    const r = find(onoff);
    run(async () => { await api(`/api/rules/${r.id}`, { method: "PUT", body: { ...r, enabled: !r.enabled } }); loadRules(); });
  } else if (delrule && confirm("Eliminare questa regola?")) {
    run(async () => { await api(`/api/rules/${delrule}`, { method: "DELETE" }); loadRules(); });
  }
});

// ---------- impostazioni ----------
async function loadSettings() {
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const [k, v] of Object.entries(s)) {
    const el = f.elements[k];
    if (!el) continue;
    if (SECRET_KEYS.includes(k)) {
      el.value = "";
      el.placeholder = v ? "•••••• salvato (lascia vuoto per non cambiarlo)" : "";
    } else if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
  }
  updateEstimate();
}

async function updateEstimate() {
  const f = $("#settings-form");
  const n = groupsCache.length || (await api("/api/groups")).length;
  const per = Math.max(1, Number(f.groups_per_cycle.value) || 1);
  const avgDelay = (Number(f.delay_between_groups_min.value) + Number(f.delay_between_groups_max.value)) / 2;
  const cycleMin = Number(f.interval_minutes.value) * 1.05 + (per * (avgDelay + 20)) / 60;
  const cycles = Math.ceil(n / per);
  $("#cycle-estimate").textContent = n
    ? `Con ${n} gruppi attivi, ogni gruppo viene ricontrollato circa ogni ${Math.round(cycles * cycleMin)} minuti.`
    : "";
}
$("#settings-form").addEventListener("input", updateEstimate);

$("#settings-form").addEventListener("submit", e => {
  e.preventDefault();
  const f = e.target;
  const body = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") body[el.name] = el.checked;
    else if (el.type === "number") body[el.name] = Number(el.value);
    else if (SECRET_KEYS.includes(el.name) && !el.value) continue;
    else body[el.name] = el.value;
  }
  run(async () => { await api("/api/settings", { method: "PUT", body }); toast("Impostazioni salvate"); loadSettings(); });
});

$("#btn-test-notify").addEventListener("click", () => run(async () => {
  const res = await api("/api/notify/test", { method: "POST" });
  toast(Object.entries(res).map(([c, err]) => `${c}: ${err ? "errore " + err : "ok"}`).join(" · "));
}));

// ---------- avvio ----------
run(loadStatus);
setInterval(() => { if ($("#tab-status").classList.contains("active")) loadStatus().catch(() => {}); }, 5000);
