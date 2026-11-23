/* Small persistent store: settings are per browser profile, progress is on the
   server per TOS user. */

import { deviceLanguage, setLanguage, getLanguage, watchSystemLanguage } from "./i18n.js";

const KEY = "comicnest.settings.v1";

const DEFAULTS = {
  theme: "auto",
  language: "auto",
  mode: "single",
  direction: "rtl",
  animation: "slide",
  brightness: 100,
  zoom: 100,
};

function clamp(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function sanitise(raw) {
  const value = Object.assign({}, DEFAULTS, raw || {});
  if (!["auto", "light", "dark"].includes(value.theme)) value.theme = "auto";
  if (!["single", "double", "split"].includes(value.mode)) value.mode = "single";
  if (!["rtl", "ltr", "vertical"].includes(value.direction)) value.direction = "rtl";
  if (!["slide", "scroll", "flip"].includes(value.animation)) value.animation = "slide";
  value.brightness = clamp(value.brightness, 30, 100, 100);
  value.zoom = clamp(value.zoom, 100, 300, 100);
  if (value.language !== "auto" && !getLanguageIsSupported(value.language)) {
    value.language = "auto";
  }
  return value;
}

function getLanguageIsSupported(code) {
  return ["zh-CN", "zh-TW", "en", "ja", "ko", "de", "fr", "es", "ru"].includes(code);
}

export function loadSettings() {
  try {
    const raw = localStorage.getItem(KEY);
    return sanitise(raw ? JSON.parse(raw) : null);
  } catch {
    return sanitise(null);
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* private mode, quota, … */
  }
}

const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function resolvedTheme(theme) {
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return media && media.matches ? "dark" : "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = resolvedTheme(theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", resolvedTheme(theme) === "dark" ? "#111214" : "#f4f1ea");
}

export function effectiveLanguage(settings) {
  return settings.language === "auto" ? deviceLanguage() : settings.language;
}

export function applyLanguage(settings) {
  return setLanguage(effectiveLanguage(settings));
}

export const store = {
  settings: loadSettings(),
  me: null,
  options: null,
  scanTimer: null,

  update(patch) {
    this.settings = sanitise(Object.assign({}, this.settings, patch));
    saveSettings(this.settings);
    applyTheme(this.settings.theme);
    activeLanguage = applyLanguage(this.settings);
    return this.settings;
  },

  reset() {
    this.settings = sanitise(null);
    saveSettings(this.settings);
    applyTheme(this.settings.theme);
    activeLanguage = applyLanguage(this.settings);
    return this.settings;
  },
};

applyTheme(store.settings.theme);
let activeLanguage = applyLanguage(store.settings);

watchSystemLanguage(() => {
  if (store.settings.language !== "auto") return;
  const next = applyLanguage(store.settings);
  if (next === activeLanguage) return;
  activeLanguage = next;
  document.dispatchEvent(new CustomEvent("comicnest:language"));
});

if (media && media.addEventListener) {
  media.addEventListener("change", () => {
    if (store.settings.theme === "auto") applyTheme("auto");
  });
}
