// Shared helpers: DOM, icons, rings, number formatting and the API client.

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

// ---------------------------------------------------------------- icons

const PATHS = {
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  protein: '<ellipse cx="14.5" cy="9" rx="6" ry="4.6" transform="rotate(-45 14.5 9)"/><path d="M10 13.6 6 17.6"/><circle cx="5" cy="19" r="1.7"/>',
  carbs: '<path d="M12 21V4"/><path d="M12 9c-2.6 0-4.4-1.6-4.4-4.2C10.2 4.8 12 6.4 12 9z"/><path d="M12 9c2.6 0 4.4-1.6 4.4-4.2C13.8 4.8 12 6.4 12 9z"/><path d="M12 15c-2.6 0-4.4-1.6-4.4-4.2C10.2 10.8 12 12.4 12 15z"/><path d="M12 15c2.6 0 4.4-1.6 4.4-4.2-2.6 0-4.4 1.6-4.4 4.2z"/>',
  fat: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.500 6-11 6-11z"/>',
  sugar: '<rect x="5" y="5" width="14" height="14" rx="3.5"/><path d="M9.500 10h.01M14.500 10h.01M9.500 14.500h.01M14.500 14.500h.01"/>',
  sodium: '<path d="M8 9h8l1 11a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1z"/><path d="M8 9a4 4 0 0 1 8 0"/><path d="M11 5.500h.01M13 5.500h.01"/>',
  fiber: '<path d="M5 19c0-8.500 5-14 14-14 0 9-5.500 14-14 14z"/><path d="M5 19l8-8"/>',
  home: '<path d="M3 10l9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V13h6v9"/>',
  chart: '<path d="M6 20V11M12 20V4M18 20v-6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  info: '<circle cx="12" cy="12" r="9.500"/><path d="M12 16.500v-5M12 8h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  back: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  dots: '<circle cx="5" cy="12" r="1.300"/><circle cx="12" cy="12" r="1.300"/><circle cx="19" cy="12" r="1.300"/>',
  sparkle: '<path d="M12 3l1.900 5.600L19.500 10.500l-5.600 1.900L12 18l-1.900-5.600L4.500 10.500l5.600-1.900z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
  camera: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3l2-3h6l2 3h3a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  close: '<path d="M18 6L6 18M6 6l12 12"/>',
  trash: '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="M5 12.500l4.500 4.500L19 7"/>',
  alert: '<path d="M12 8v5M12 16.500h.01"/><circle cx="12" cy="12" r="9.500"/>',
  thali: '<circle cx="12" cy="12" r="10"/><circle cx="8.200" cy="9" r="2.300"/><circle cx="15.800" cy="9" r="2.300"/><circle cx="12" cy="15.600" r="2.300"/>',
};
const FILLED = new Set(["flame"]);

export function icon(name, extra = "") {
  const fill = FILLED.has(name) ? " fill" : "";
  return `<svg class="icon${fill} ${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
}

// ------------------------------------------------------------ nutrients

export const NUTRIENTS = {
  calories: { label: "Calories", unit: "kcal", icon: "flame", color: "var(--ink)" },
  protein_g: { label: "Protein", unit: "g", icon: "protein", color: "var(--protein)" },
  carbs_g: { label: "Carbs", unit: "g", icon: "carbs", color: "var(--carbs)" },
  fat_g: { label: "Fat", unit: "g", icon: "fat", color: "var(--fat)" },
  sugar_g: { label: "Sugar", unit: "g", icon: "sugar", color: "var(--sugar)" },
  sodium_mg: { label: "Sodium", unit: "mg", icon: "sodium", color: "var(--sodium)" },
  fiber_g: { label: "Fiber", unit: "g", icon: "fiber", color: "var(--fiber)" },
};
export const TILE_PAGES = [["protein_g", "carbs_g", "fat_g"], ["sugar_g", "sodium_mg", "fiber_g"]];

export const num = (value) => {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const rounded = Math.abs(value) >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return String(rounded);
};
export const mid = (range) => (range ? (range.lo + range.hi) / 2 : null);
export function rangeText(range, unit = "") {
  if (!range) return "–";
  const lo = num(range.lo), hi = num(range.hi);
  return lo === hi ? `${lo}${unit}` : `${lo}–${hi}${unit}`;
}

// ---------------------------------------------------------------- rings

// A progress ring. fraction is 0 to 1; inner is HTML placed in the centre.
export function ring(fraction, { color = "var(--ink)", width = 9, inner = "", dashed = false, track = true } = {}) {
  const r = 50 - width / 2 - 1;
  const circumference = 2 * Math.PI * r;
  const part = Math.max(0, Math.min(1, fraction || 0)) * circumference;
  const trackAttrs = dashed ? 'stroke-dasharray="5 7" stroke="#C9C9D2"' : "";
  return `<span class="ring"><svg viewBox="0 0 100 100" aria-hidden="true">
    ${track ? `<circle class="ring-track" cx="50" cy="50" r="${r}" stroke-width="${width}" ${trackAttrs}/>` : ""}
    ${part > 0 ? `<circle class="ring-arc" cx="50" cy="50" r="${r}" stroke-width="${width}" stroke="${color}" stroke-dasharray="${part} ${circumference}" transform="rotate(-90 50 50)"/>` : ""}
  </svg><span class="ring-inner">${inner}</span></span>`;
}

// Tiles with a pager. render(key) returns one tile's HTML.
export function pager(render, page = 0) {
  const pages = TILE_PAGES.map((keys, index) =>
    `<div class="tiles" data-page="${index}" ${index === page ? "" : "hidden"}>${keys.map(render).join("")}</div>`).join("");
  const dots = TILE_PAGES.map((_, index) =>
    `<button type="button" data-goto="${index}" aria-pressed="${index === page}" aria-label="Show ${index === 0 ? "protein, carbs and fat" : "sugar, sodium and fiber"}"></button>`).join("");
  return `<div class="pager">${pages}<div class="dots">${dots}</div></div>`;
}

// One click handler for every pager on the page. onChange receives the new page index.
export function bindPagers(root, onChange) {
  root.addEventListener("click", (event) => {
    const dot = event.target.closest("[data-goto]");
    if (!dot || !root.contains(dot)) return;
    const box = dot.closest(".pager");
    const page = Number(dot.dataset.goto);
    $$(".tiles", box).forEach((tiles) => { tiles.hidden = Number(tiles.dataset.page) !== page; });
    $$("[data-goto]", box).forEach((d) => d.setAttribute("aria-pressed", String(d === dot)));
    if (onChange) onChange(page);
  });
}

// ----------------------------------------------------------------- time

export function isoDay(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
export const timeLabel = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
export const dayLabel = (day) =>
  new Date(`${day}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });

// ------------------------------------------------------------------ API

// Calls this app's own API. Throws an Error whose message can be shown to the user.
export async function api(path, { method = "GET", json, form } = {}) {
  const options = { method };
  if (json !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(json);
  } else if (form) {
    options.body = form;
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Cannot reach the MyThali server. Check that it is still running.");
  }
  let data = null;
  try { data = await response.json(); } catch { /* an empty or non-JSON body */ }
  if (!response.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return data;
}

let toastTimer;
export function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("show"), 2600);
}

export const isDesktop = () => window.matchMedia("(min-width: 1024px)").matches;
