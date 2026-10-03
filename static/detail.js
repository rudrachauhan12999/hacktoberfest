// The detail view: one scanned or logged food, its verdict, and the edit controls.

import {
  $, api, bindPagers, esc, icon, isDesktop, NUTRIENTS, num, pager, rangeText, timeLabel, toast,
} from "./ui.js";

const aside = $("#detail");
const VERDICTS = {
  green: ["Fits your goals", "check"],
  amber: ["Check a few things", "alert"],
  red: ["Does not fit your goals", "alert"],
};
const RANGE_KEYS = ["calories", "protein_g", "carbs_g", "fat_g"];

let S = null;        // the food on show, or null
let hooks = {};      // onSaved(entry), onDeleted(id), onClosed()
let sequence = 0;    // drops replies to requests that are no longer current
let timer = null;

export function initDetail(callbacks) {
  hooks = callbacks;
  aside.addEventListener("click", onClick);
  aside.addEventListener("submit", onSubmit);
  aside.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && S && !isDesktop()) closeDetail();
  });
  bindPagers(aside, (page) => { if (S) S.page = page; });
  renderEmpty();
}

export function openDetail(state) {
  sequence += 1;
  S = { page: 0, fixing: false, menu: false, logId: null, servings: 1, dirty: false, error: null, ...state };
  render();
  aside.classList.add("open");
  document.body.classList.add("detail-open");
  aside.scrollTop = 0;
  if (!isDesktop()) $("[data-act='back']", aside)?.focus();
}

export function closeDetail() {
  sequence += 1;
  S = null;
  aside.classList.remove("open");
  document.body.classList.remove("detail-open");
  renderEmpty();
  if (hooks.onClosed) hooks.onClosed();
}

export const detailLogId = () => (S ? S.logId : null);
export const hasDetail = () => S !== null;

function renderEmpty() {
  aside.innerHTML = `<div class="d-empty"><div class="empty">${icon("thali")}
    <p>Select an entry to see its details,<br>or press + to scan something.</p></div></div>`;
}

// ---------------------------------------------------------------- render

function tile(key) {
  const meta = NUTRIENTS[key];
  return `<div class="d-tile">
    <p><span style="color:${meta.color};display:inline-flex">${icon(meta.icon)}</span>${meta.label}</p>
    <p>${rangeText(S.evaluation.totals[key], meta.unit)}</p></div>`;
}

function ingredientsHtml(item) {
  if (item.source === "meal") {
    const rows = item.items.map((part) =>
      `<li><span>${esc(part.name)}</span><span>${esc(part.portion)}</span></li>`).join("");
    const likely = item.ingredients.length
      ? `<p class="small muted">Likely ingredients: ${esc(item.ingredients.join(", "))}</p>` : "";
    return rows || likely ? `<ul class="rows">${rows}</ul>${likely}` : `<p class="muted small">No items were listed.</p>`;
  }
  const rows = item.ingredients.map((name) => `<li><span>${esc(name)}</span></li>`).join("");
  const extra = [
    item.contains.length ? `Contains: ${esc(item.contains.join(", "))}` : "",
    item.may_contain.length ? `May contain: ${esc(item.may_contain.join(", "))}` : "",
  ].filter(Boolean).map((text) => `<p class="small muted">${text}</p>`).join("");
  return rows || extra
    ? `<ul class="rows">${rows}</ul>${extra}`
    : `<p class="muted small">No ingredient list was read from this photo.</p>`;
}

function verdictHtml() {
  const { evaluation, item } = S;
  const [title, glyph] = VERDICTS[evaluation.overall];
  const rules = evaluation.rules.map((rule) =>
    `<li><span class="status-dot s-${rule.status}" role="img" aria-label="${rule.status}"></span>
      <div><b>${esc(rule.label)}</b><span class="detail">${esc(rule.detail)}</span></div></li>`).join("");
  const notes = [...item.notes, ...evaluation.notes];
  if (S.harness && S.harness.attempts > 1) {
    notes.push(`The first reading failed a self-check, so it was read again (${S.harness.attempts} attempts).`);
  }
  return `
    <div class="verdict ${evaluation.overall}">${icon(glyph)}${title}</div>
    ${rules ? `<ul class="rules">${rules}</ul>` : `<p class="muted small" style="margin-top:10px">No targets are set, so nothing was checked.</p>`}
    ${S.explanation ? `<p class="explain">${esc(S.explanation)}</p>` : ""}
    <h3 class="section-title">Ingredients</h3>
    ${ingredientsHtml(item)}
    ${notes.length ? `<div class="notes">${notes.map((note) => `<p>${esc(note)}</p>`).join("")}</div>` : ""}
    ${evaluation.disclaimer ? `<p class="disclaimer">${esc(evaluation.disclaimer)}</p>` : ""}`;
}

function fixHtml() {
  const { item } = S;
  const meal = item.source === "meal";
  const value = (v) => (v === null || v === undefined ? "" : v);
  const fields = Object.entries(NUTRIENTS).map(([key, meta]) => {
    const range = item.nutrients[key];
    const title = `${meta.label} (${meta.unit})`;
    if (meal && RANGE_KEYS.includes(key)) {
      return `<fieldset class="field" style="border:0;padding:0;margin-inline:0"><legend>${title}</legend><div class="fix-row">
        <input type="number" name="${key}.lo" min="0" step="any" inputmode="decimal" value="${value(range?.lo)}" aria-label="${meta.label} minimum" placeholder="Minimum">
        <input type="number" name="${key}.hi" min="0" step="any" inputmode="decimal" value="${value(range?.hi)}" aria-label="${meta.label} maximum" placeholder="Maximum">
      </div></fieldset>`;
    }
    return `<div class="field"><label for="fix-${key}">${title}</label>
      <input type="number" id="fix-${key}" name="${key}" min="0" step="any" inputmode="decimal" value="${value(range?.lo)}"></div>`;
  }).join("");
  return `<form id="fix-form" novalidate>
    <h3 class="section-title">Fix results</h3>
    <p class="small muted">Values are for one serving. Leave a field empty if it is unknown.</p>
    <div class="field"><label for="fix-name">Name</label>
      <input type="text" id="fix-name" name="name" maxlength="160" value="${esc(item.name)}"></div>
    ${fields}
    <p class="error" id="fix-error" role="alert" style="margin-top:14px" hidden></p>
  </form>`;
}

function render(focusAct) {
  const { item, evaluation } = S;
  const photo = S.photoUrl || S.thumbnail;
  const menu = S.menu
    ? `<div class="d-menu-list"><button type="button" data-act="delete">${icon("trash")}${S.logId ? "Delete" : "Discard"}</button></div>` : "";
  const footer = S.fixing
    ? `<button type="button" class="btn outline" data-act="cancel-fix">Cancel</button>
       <button type="submit" class="btn" form="fix-form">Apply</button>`
    : `<button type="button" class="btn outline" data-act="fix">${icon("sparkle")}Fix results</button>
       <button type="button" class="btn" data-act="done">Done</button>`;

  aside.innerHTML = `
    <div class="d-photo" ${photo ? `style="background-image:url('${esc(photo)}')"` : ""}>
      ${photo ? "" : icon(item.source === "meal" ? "thali" : "sugar")}
      <div class="d-bar">
        <button type="button" class="icon-btn" data-act="back" aria-label="Back">${icon("back")}</button>
        <span>Nutrition</span>
        <div class="d-menu">
          <button type="button" class="icon-btn" data-act="menu" aria-label="More options" aria-expanded="${S.menu}">${icon("dots")}</button>
          ${menu}
        </div>
      </div>
    </div>
    <div class="d-sheet">
      <span class="chip">${icon("clock")}${S.loggedAt ? timeLabel(S.loggedAt) : "Not saved yet"}</span>
      ${item.source === "meal" ? `<span class="tag">estimate</span>` : ""}
      <div class="d-title">
        <h2>${esc(item.name)}</h2>
        <div class="stepper" role="group" aria-label="Servings">
          <button type="button" data-act="minus" aria-label="Fewer servings" ${S.servings <= 0.5 ? "disabled" : ""}>${icon("minus")}</button>
          <output aria-live="polite">${num(S.servings)}</output>
          <button type="button" data-act="plus" aria-label="More servings" ${S.servings >= 50 ? "disabled" : ""}>${icon("plus")}</button>
        </div>
      </div>
      <div class="card d-cal">
        <span class="flame-box">${icon("flame")}</span>
        <div><p class="muted">Calories</p><p>${rangeText(evaluation.totals.calories)} <span>kcal</span></p></div>
      </div>
      ${pager(tile, S.page)}
      ${S.fixing ? fixHtml() : verdictHtml()}
      ${S.error ? `<p class="error" role="alert" style="margin-top:14px">${esc(S.error)}</p>` : ""}
    </div>
    <div class="d-footer">${footer}</div>`;

  if (focusAct) $(`[data-act='${focusAct}']`, aside)?.focus();
}

// --------------------------------------------------------------- actions

function localTotals() {
  const totals = {};
  for (const key of Object.keys(NUTRIENTS)) {
    const range = S.item.nutrients[key];
    totals[key] = range ? { lo: range.lo * S.servings, hi: range.hi * S.servings } : null;
  }
  return totals;
}

// Ask the server for a fresh verdict. No model call is involved.
async function recompute() {
  const ticket = ++sequence;
  try {
    const result = await api("/api/evaluate", {
      method: "POST",
      json: { item: S.item, servings: S.servings, exclude_log_id: S.logId },
    });
    if (ticket !== sequence || !S) return;
    Object.assign(S, { item: result.item, evaluation: result.evaluation, explanation: result.explanation, error: null });
  } catch (error) {
    if (ticket !== sequence || !S) return;
    S.error = error.message;
  }
  const focused = document.activeElement?.dataset?.act;
  render(focused);
}

function changeServings(delta, act) {
  const next = Math.min(50, Math.max(0.5, S.servings + delta));
  if (next === S.servings) return;
  S.servings = next;
  S.dirty = true;
  S.evaluation = { ...S.evaluation, totals: localTotals() };  // numbers update at once
  render(act);
  clearTimeout(timer);
  timer = setTimeout(recompute, 250);                          // the verdict follows
}

async function save() {
  if (S.logId && !S.dirty) {
    if (isDesktop()) toast("No changes to save"); else closeDetail();
    return;
  }
  const body = { item: S.item, servings: S.servings, explanation: S.explanation };
  try {
    const entry = S.logId
      ? await api(`/api/log/${S.logId}`, { method: "PUT", json: body })
      : await api("/api/log", { method: "POST", json: { ...body, thumbnail: S.thumbnail || null } });
    Object.assign(S, { logId: entry.id, loggedAt: entry.logged_at, evaluation: entry.evaluation, dirty: false, error: null });
    toast("Saved to your log");
    hooks.onSaved(entry);
    if (isDesktop()) render("done"); else closeDetail();
  } catch (error) {
    S.error = error.message;
    render("done");
  }
}

async function remove() {
  if (!S.logId) { closeDetail(); return; }
  if (!window.confirm("Delete this entry from your log?")) return;
  try {
    const id = S.logId;
    await api(`/api/log/${id}`, { method: "DELETE" });
    toast("Entry deleted");
    closeDetail();
    hooks.onDeleted(id);
  } catch (error) {
    S.error = error.message;
    S.menu = false;
    render("menu");
  }
}

function onClick(event) {
  const button = event.target.closest("[data-act]");
  if (!button || !S) return;
  const act = button.dataset.act;
  if (act === "back") closeDetail();
  else if (act === "menu") { S.menu = !S.menu; render("menu"); }
  else if (act === "delete") remove();
  else if (act === "minus") changeServings(-0.5, "minus");
  else if (act === "plus") changeServings(0.5, "plus");
  else if (act === "fix") { S.fixing = true; S.menu = false; render(); $("#fix-name", aside)?.focus(); }
  else if (act === "cancel-fix") { S.fixing = false; S.error = null; render("fix"); }
  else if (act === "done") save();
}

function onSubmit(event) {
  if (event.target.id !== "fix-form") return;
  event.preventDefault();
  const data = new FormData(event.target);
  const read = (name) => {
    const text = String(data.get(name) ?? "").trim();
    if (text === "") return null;
    const value = Number(text);
    return Number.isFinite(value) && value >= 0 ? value : NaN;
  };
  const nutrients = {};
  for (const [key, meta] of Object.entries(NUTRIENTS)) {
    const ranged = data.has(`${key}.lo`);
    let lo = read(ranged ? `${key}.lo` : key);
    let hi = ranged ? read(`${key}.hi`) : lo;
    if (Number.isNaN(lo) || Number.isNaN(hi)) {
      // Shown in place, so the other fields keep what was typed.
      const box = $("#fix-error", aside);
      box.textContent = `${meta.label} must be a number that is zero or more.`;
      box.hidden = false;
      return;
    }
    if (lo === null) lo = hi;
    if (hi === null) hi = lo;
    nutrients[key] = lo === null ? null : { lo: Math.min(lo, hi), hi: Math.max(lo, hi) };
  }
  S.item = { ...S.item, name: String(data.get("name") || "").trim() || S.item.name, nutrients };
  S.evaluation = { ...S.evaluation, totals: localTotals() };
  Object.assign(S, { fixing: false, dirty: true, error: null });
  render("fix");
  recompute();
}
