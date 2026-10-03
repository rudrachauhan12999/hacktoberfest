// Entry point: navigation and the Home, Progress, Profile and About pages.

import {
  $, $$, api, bindPagers, dayLabel, esc, icon, isDesktop, isoDay, mid, NUTRIENTS, num, pager,
  rangeText, ring, timeLabel, toast,
} from "./ui.js";
import { closeDetail, detailLogId, hasDetail, initDetail, openDetail } from "./detail.js";
import { initScan, openScan } from "./scan.js";

const NAV = { home: ["Home", "home"], progress: ["Progress", "chart"], profile: ["Profile", "user"], about: ["About", "info"] };
const EMPTY_TODAY = "Nothing logged yet. Scan a nutrition label or photograph a meal.";
const GOALS = { lose_fat: "Lose fat", maintain: "Maintain weight", build_muscle: "Build muscle" };
const DIETS = { none: "No restriction", vegetarian: "Vegetarian", eggetarian: "Eggetarian", vegan: "Vegan", jain: "Jain", halal: "Halal" };
const TARGET_FIELDS = [
  ["calories", "Daily calories (kcal)"], ["protein_g", "Protein (g)"], ["carbs_g", "Carbs (g)"],
  ["fat_g", "Fat (g)"], ["sugar_g_max", "Maximum sugar (g)"], ["sodium_mg_max", "Maximum sodium (mg)"],
];
const PIPELINE = [
  ["Prepare the photo", "Rotation is fixed and the image is resized on this computer."],
  ["Read with Gemma", "The local model fills a fixed JSON form. It copies what is printed or gives a range."],
  ["Check the numbers", "Plain arithmetic looks for impossible values, such as sugar above carbohydrate."],
  ["Ask again if needed", "The model is shown its exact errors and gets up to two more tries."],
  ["Convert to one serving", "kJ, salt and per-100 g values are converted in code."],
  ["Apply your rules", "Budgets, allergens and diet are decided by code, never by the model."],
  ["Explain", "The model rephrases the rule results in two sentences. It sees nothing else."],
];

const state = { view: "home", day: isoDay(), page: 0, profile: null, log: null, week: null };

// ------------------------------------------------------------------- data

async function refresh() {
  const [profile, week, log] = await Promise.all([
    api("/api/profile"), api("/api/week"), api(`/api/log?day=${state.day}`),
  ]);
  Object.assign(state, { profile, week, log });
}

function openEntry(entry) {
  openDetail({
    item: entry.item, servings: entry.servings, evaluation: entry.evaluation,
    explanation: entry.explanation, thumbnail: entry.thumbnail, logId: entry.id, loggedAt: entry.logged_at,
  });
  markCurrent();
}

function markCurrent() {
  const current = detailLogId();
  $$("[data-entry]").forEach((card) =>
    card.setAttribute("aria-current", String(Number(card.dataset.entry) === current)));
}

// ------------------------------------------------------------------- home

function weekStrip() {
  const target = state.week.targets.calories;
  return state.week.days.map((day) => {
    const inner = `<span>${day.date}</span>`;
    let circle, meaning;
    if (day.is_today) {
      const eaten = target ? day.totals.calories / target : 0;
      circle = ring(Math.max(0.3, Math.min(1, eaten)), { width: 8, inner });
      meaning = "today";
    } else if (day.status === "on") {
      circle = ring(1, { color: "var(--green)", width: 8, inner, track: false }); meaning = "on goal";
    } else if (day.status === "off") {
      circle = ring(1, { color: "var(--red)", width: 8, inner, track: false }); meaning = "over goal";
    } else {
      circle = ring(0, { width: 6, inner, dashed: true }); meaning = "nothing logged";
    }
    return `<button type="button" data-day="${day.day}" class="${day.is_future ? "future" : ""}"
      aria-pressed="${day.day === state.day}" aria-label="${dayLabel(day.day)}, ${meaning}" ${day.is_future ? "disabled" : ""}>
      <span>${day.weekday}</span>${circle}</button>`;
  }).join("");
}

function homeTile(key) {
  const meta = NUTRIENTS[key];
  const eaten = state.log.totals[key], target = state.log.targets[key];
  const centre = `<span style="color:${meta.color};display:inline-flex">${icon(meta.icon)}</span>`;
  return `<div class="tile">
    <p class="tile-val">${num(eaten)}<span>${target ? `/${num(target)}` : ""}${meta.unit}</span></p>
    <p class="muted">${meta.label} eaten</p>
    ${ring(target ? eaten / target : 0, { color: meta.color, width: 9, inner: centre })}</div>`;
}

function entryCard(entry) {
  const totals = entry.evaluation.totals;
  const meal = entry.kind === "meal";
  const thumb = entry.thumbnail
    ? `<span class="entry-thumb" style="background-image:url('${esc(entry.thumbnail)}')"></span>`
    : `<span class="entry-thumb">${icon(meal ? "thali" : "sugar")}</span>`;
  const macros = ["protein_g", "carbs_g", "fat_g"].map((key) =>
    `<span><span style="color:${NUTRIENTS[key].color};display:inline-flex">${icon(NUTRIENTS[key].icon)}</span>${num(mid(totals[key]))}g</span>`).join("");
  return `<li><button type="button" class="entry" data-entry="${entry.id}">
    ${thumb}
    <span class="entry-body">
      <span class="entry-top"><span class="entry-name">${esc(entry.name)}</span><span class="entry-time">${timeLabel(entry.logged_at)}</span></span>
      <span class="entry-kcal">${icon("flame")}${rangeText(totals.calories)} kcal
        ${meal ? `<span class="tag">estimate</span>` : ""}
        <span class="status-dot s-${entry.overall}" role="img" aria-label="Verdict: ${entry.overall}"></span></span>
      <span class="entry-macros">${macros}</span>
    </span></button></li>`;
}

function renderHome() {
  const { log, week, profile } = state;
  const target = log.targets.calories;
  const today = state.day === isoDay();
  const entries = log.entries.length
    ? `<ul class="entries">${log.entries.map(entryCard).join("")}</ul>`
    : `<div class="card empty">${icon("camera")}<p>${today ? EMPTY_TODAY : "Nothing was logged on this day."}</p></div>`;

  $("#view-home").innerHTML = `
    <header class="top">
      <h1 class="wordmark">${icon("thali")}My Thali</h1>
      <span class="streak" aria-label="${week.streak} day streak">${icon("flame")}${week.streak}</span>
    </header>
    ${profile.configured ? "" : `<div class="banner"><span>Set your goals and restrictions so the checks fit you.</span><a href="#profile">Set up profile</a></div>`}
    <div class="week" role="group" aria-label="This week">${weekStrip()}</div>
    <section class="card cal-card" aria-label="Calories">
      <div><p class="big">${num(log.totals.calories)}<span>${target ? `/${num(target)}` : ""}</span></p>
        <p class="muted">Calories eaten</p></div>
      ${ring(target ? log.totals.calories / target : 0, { width: 9, inner: icon("flame") })}
    </section>
    ${pager(homeTile, state.page)}
    <h2 class="section-title">Recently uploaded ${today ? "" : `<span class="muted">${dayLabel(state.day)}</span>`}</h2>
    ${entries}`;
  markCurrent();
}

async function selectDay(day) {
  state.day = day;
  try {
    state.log = await api(`/api/log?day=${day}`);
  } catch (error) { toast(error.message); return; }
  renderHome();
  $(`[data-day='${day}']`)?.focus();
  if (isDesktop()) {
    if (state.log.entries.length) openEntry(state.log.entries[0]); else if (hasDetail()) closeDetail();
  }
}

// --------------------------------------------------------------- progress

function chart(key, goal, barClass) {
  const days = state.week.days;
  const top = Math.max(goal || 0, ...days.map((day) => day.totals[key]), 1) * 1.12;
  const bars = days.map((day) => {
    const value = day.totals[key];
    const over = key === "calories" && day.status === "off";
    const kind = day.entries ? (over ? "over" : barClass) : "none";
    return `<div class="bar-col"><div class="bar ${kind}" style="height:${(value / top) * 100}%"></div>
      <span class="bar-label"><b>${day.entries ? num(value) : "–"}</b>${day.weekday}</span></div>`;
  }).join("");
  const line = goal
    ? `<div class="goal-line" style="bottom:${(goal / top) * 100}%"><span>Goal ${num(goal)}</span></div>` : "";
  return `<div class="chart">${line}<div class="bars">${bars}</div></div>`;
}

function renderProgress() {
  const { days, targets, streak } = state.week;
  const logged = days.filter((day) => day.entries);
  const average = logged.length ? logged.reduce((sum, day) => sum + day.totals.calories, 0) / logged.length : null;
  $("#view-progress").innerHTML = `
    <h1 class="page-title">Progress</h1>
    <div class="stat-row">
      <div class="tile"><b>${streak}</b><span class="muted small">Day streak</span></div>
      <div class="tile"><b>${days.filter((day) => day.status === "on").length}/${logged.length}</b><span class="muted small">Days on goal</span></div>
      <div class="tile"><b>${num(average)}</b><span class="muted small">Average kcal</span></div>
    </div>
    <div class="stack">
      <section class="card"><h2 class="section-title" style="margin-top:0">Calories this week <span class="muted">kcal per day</span></h2>
        ${chart("calories", targets.calories, "")}</section>
      <section class="card"><h2 class="section-title" style="margin-top:0">Protein this week <span class="muted">grams per day</span></h2>
        ${chart("protein_g", targets.protein_g, "protein")}</section>
    </div>
    ${logged.length ? "" : `<p class="empty">${EMPTY_TODAY}</p>`}`;
}

// ---------------------------------------------------------------- profile

function renderProfile() {
  const p = state.profile;
  const options = (map, selected) => Object.entries(map).map(([value, label]) =>
    `<option value="${value}" ${value === selected ? "selected" : ""}>${label}</option>`).join("");
  const targets = TARGET_FIELDS.map(([name, label]) =>
    `<div class="field"><label for="p-${name}">${label}</label>
      <input type="number" id="p-${name}" name="${name}" min="1" step="any" inputmode="decimal" value="${p[name] ?? ""}"></div>`).join("");
  $("#view-profile").innerHTML = `
    <h1 class="page-title">Profile</h1>
    <form class="card" id="profile-form" novalidate>
      <div class="field" style="margin-top:0"><label for="p-name">Name</label>
        <input type="text" id="p-name" name="name" maxlength="80" autocomplete="given-name" value="${esc(p.name)}"></div>
      <div class="grid-2">
        <div class="field"><label for="p-goal">Goal</label><select id="p-goal" name="goal">${options(GOALS, p.goal)}</select></div>
        <div class="field"><label for="p-diet">Diet</label><select id="p-diet" name="diet">${options(DIETS, p.diet)}</select></div>
      </div>
      <div class="field"><label for="p-allergens">Allergens</label>
        <input type="text" id="p-allergens" name="allergens" value="${esc(p.allergens.join(", "))}" aria-describedby="p-allergens-hint">
        <p class="hint" id="p-allergens-hint">Separate with commas, for example: peanut, milk, gluten.</p></div>
      <div class="field"><label for="p-meals">Meals per day</label>
        <input type="number" id="p-meals" name="meals_per_day" min="1" max="12" step="1" inputmode="numeric" value="${p.meals_per_day}" aria-describedby="p-meals-hint">
        <p class="hint" id="p-meals-hint">Each meal gets an equal share of the daily targets below.</p></div>
      <h2 class="section-title">Daily targets</h2>
      <p class="small muted">Leave a target empty to switch its check off.</p>
      <div class="grid-2">${targets}</div>
      <p class="error" id="profile-error" role="alert" style="margin-top:14px" hidden></p>
      <div class="form-actions"><button type="submit" class="btn">Save profile</button></div>
    </form>`;
}

async function saveProfile(form) {
  const data = new FormData(form);
  const number = (name) => (String(data.get(name)).trim() === "" ? null : Number(data.get(name)));
  const body = {
    name: data.get("name"), goal: data.get("goal"), diet: data.get("diet"),
    allergens: String(data.get("allergens")), meals_per_day: number("meals_per_day") ?? 3,
  };
  for (const [name] of TARGET_FIELDS) body[name] = number(name);
  const box = $("#profile-error");
  try {
    await api("/api/profile", { method: "PUT", json: body });
    await refresh();
    renderProfile();
    toast("Profile saved");
  } catch (error) {
    box.textContent = error.message;
    box.hidden = false;
  }
}

// ------------------------------------------------------------------ about

async function renderAbout() {
  const view = $("#view-about");
  const steps = PIPELINE.map(([title, text]) => `<li><div><b>${title}</b><span class="muted">${text}</span></div></li>`).join("");
  const page = (status) => `
    <h1 class="page-title">About</h1>
    <div class="stack">
      <section class="card"><h2 class="section-title" style="margin-top:0">Model status</h2>${status}
        <div class="form-actions"><button type="button" class="btn outline small-btn" id="recheck">Check again</button></div></section>
      <section class="card"><h2 class="section-title" style="margin-top:0">How a scan works</h2><ol class="steps">${steps}</ol></section>
      <section class="card"><h2 class="section-title" style="margin-top:0">Good to know</h2>
        <p>My Thali talks only to the Ollama address shown above. With a model that runs on this computer, your photos, profile and food log stay here and the app works without wifi.</p>
        <p style="margin-top:10px">Allergen checks flag risk from the printed ingredients. They do not certify food as safe. This is not medical advice.</p></section>
    </div>`;
  view.innerHTML = page(`<p class="muted">Checking…</p>`);
  const row = (ok, text) => `<li><span class="status-dot ${ok ? "s-green" : "s-red"}" role="img" aria-label="${ok ? "OK" : "Problem"}"></span>${text}</li>`;
  let status;
  try {
    const health = await api("/api/health");
    status = `<ul class="status-list">
      ${row(health.reachable, `Ollama ${health.reachable ? "is running" : "is not reachable"} at ${esc(health.host)}`)}
      ${row(health.model_installed, `Model ${esc(health.model)} ${health.model_installed ? "is installed" : "is not installed"}`)}
    </ul>${health.message ? `<p class="error" style="margin-top:10px">${esc(health.message)}</p>` : ""}`;
  } catch (error) {
    status = `<p class="error">${esc(error.message)}</p>`;
  }
  if (state.view === "about") view.innerHTML = page(status);
}

// ----------------------------------------------------------------- routing

const RENDER = { home: renderHome, progress: renderProgress, profile: renderProfile, about: renderAbout };

function route() {
  const wanted = location.hash.slice(1);
  state.view = wanted in NAV ? wanted : "home";
  for (const name of Object.keys(NAV)) $(`#view-${name}`).hidden = name !== state.view;
  $$("[data-nav]").forEach((link) => {
    if (link.dataset.nav === state.view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  $("#layout").classList.toggle("with-detail", state.view === "home");
  RENDER[state.view]();
  window.scrollTo(0, 0);
}

async function reload() {
  await refresh();
  RENDER[state.view]();
}

async function start() {
  $$("[data-nav]").forEach((link) => {
    const [label, glyph] = NAV[link.dataset.nav];
    link.innerHTML = `${icon(glyph)}<span>${label}</span>`;
  });
  $("#fab").innerHTML = icon("plus");
  $("#fab").addEventListener("click", openScan);

  initDetail({
    onSaved: (entry) => { state.day = entry.day; reload().catch((error) => toast(error.message)); },
    onDeleted: () => reload().catch((error) => toast(error.message)),
    onClosed: markCurrent,
  });
  initScan((result) => {
    if (state.view !== "home") location.hash = "#home";
    openDetail({
      item: result.item, evaluation: result.evaluation, explanation: result.explanation,
      thumbnail: result.thumbnail, photoUrl: result.photoUrl, harness: result.harness,
    });
    markCurrent();
  });

  const home = $("#view-home");
  bindPagers(home, (page) => { state.page = page; });
  home.addEventListener("click", (event) => {
    const day = event.target.closest("[data-day]");
    if (day) { selectDay(day.dataset.day); return; }
    const card = event.target.closest("[data-entry]");
    if (card) openEntry(state.log.entries.find((entry) => entry.id === Number(card.dataset.entry)));
  });
  document.addEventListener("submit", (event) => {
    if (event.target.id === "profile-form") { event.preventDefault(); saveProfile(event.target); }
  });
  document.addEventListener("click", (event) => { if (event.target.id === "recheck") renderAbout(); });
  window.addEventListener("hashchange", route);

  try {
    await refresh();
  } catch (error) {
    $("#view-home").innerHTML = `<p class="error">${esc(error.message)}</p>`;
    return;
  }
  route();
  if (state.view === "home" && isDesktop() && state.log.entries.length) openEntry(state.log.entries[0]);
}

start();
