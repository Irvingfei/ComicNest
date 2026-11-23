/* Application shell: persistent header, hash router, page lifecycle. */

import { api, setApiUser } from "./api.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { resolvedTheme, store } from "./store.js";
import { errorText, esc } from "./ui.js";
import * as adminPage from "./pages/admin.js";
import * as detailPage from "./pages/detail.js";
import * as libraryPage from "./pages/library.js";
import * as readerPage from "./pages/reader.js";
import * as settingsPage from "./pages/settings.js";

const PAGES = {
  library: { module: libraryPage, nav: "library", title: () => t("library.title") },
  detail: { module: detailPage, nav: "library", title: () => "" },
  reader: { module: readerPage, nav: "library", title: () => "" },
  admin: { module: adminPage, nav: "admin", title: () => t("nav.admin") },
  settings: { module: settingsPage, nav: "settings", title: () => t("nav.settings") },
};

const shell = document.getElementById("app");
const view = document.getElementById("view");
const readerRoot = document.getElementById("reader-root");
const nav = document.querySelector("[data-nav]");
const searchInput = document.querySelector("[data-search]");
const searchIcon = document.querySelector("[data-search-icon]");
const adminButton = document.querySelector("[data-admin]");
const themeButton = document.querySelector("[data-theme-toggle]");
const settingsButton = document.querySelector("[data-settings]");

let token = 0;
let dispose = null;
let currentNav = "";
let bootFailed = false;

/* ---------------------------------------------------------------- topbar */

function paintTopbar() {
  if (!nav) return;
  nav.querySelector('[data-nav-link="library"]').textContent = t("nav.library");
  nav.querySelector('[data-nav-link="admin"]').textContent = t("nav.admin");
  nav.querySelector('[data-nav-link="settings"]').textContent = t("nav.settings");

  const isAdmin = Boolean(store.me && store.me.is_admin);
  nav.querySelector('[data-nav-link="admin"]').hidden = !isAdmin;
  adminButton.hidden = !isAdmin;

  nav.querySelectorAll("[data-nav-link]").forEach((link) => {
    link.classList.toggle("active", link.dataset.navLink === currentNav);
  });

  searchInput.placeholder = t("search.placeholder");
  searchInput.setAttribute("aria-label", t("search.placeholder"));
  searchIcon.innerHTML = icon("search");
  adminButton.innerHTML = icon("shield");
  adminButton.title = t("nav.admin");
  settingsButton.innerHTML = icon("settings");
  settingsButton.title = t("nav.settings");

  const dark = resolvedTheme(store.settings.theme) === "dark";
  themeButton.innerHTML = icon(dark ? "sun" : "moon");
  themeButton.title = dark ? t("settings.themeLight") : t("settings.themeDark");
}

function wireTopbar() {
  themeButton.addEventListener("click", () => {
    const next = resolvedTheme(store.settings.theme) === "dark" ? "light" : "dark";
    store.update({ theme: next });
    paintTopbar();
    document.dispatchEvent(new CustomEvent("comicnest:theme"));
  });
  settingsButton.addEventListener("click", () => {
    location.hash = "#/settings";
  });
  adminButton.addEventListener("click", () => {
    location.hash = "#/admin";
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const q = searchInput.value.trim();
    location.hash = q ? "#/?q=" + encodeURIComponent(q) : "#/";
    searchInput.blur();
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      searchInput.value = "";
      searchInput.blur();
    }
  });
}

/* ---------------------------------------------------------------- routing */

function parseRoute() {
  const raw = (location.hash || "").replace(/^#/, "");
  const [path, queryString] = raw.split("?");
  const query = new URLSearchParams(queryString || "");
  const parts = path.split("/").filter(Boolean);
  if (!parts.length) return { name: "library", params: [], query };
  if (parts[0] === "series" && parts[1]) return { name: "detail", params: [parts[1]], query };
  if (parts[0] === "read" && parts[1]) return { name: "reader", params: [parts[1]], query };
  if (parts[0] === "admin") return { name: "admin", params: [], query };
  if (parts[0] === "settings") return { name: "settings", params: [], query };
  return { name: "missing", params: [], query };
}

function errorPanel(err, retry) {
  return (
    '<div class="empty" style="margin-top:8vh"><h3>' + esc(t("error.generic")) + "</h3>" +
    "<p>" + esc(errorText(err)) + "</p>" +
    (retry
      ? '<button class="btn primary" data-retry>' + esc(t("common.retry")) + "</button>"
      : "") +
    "</div>"
  );
}

function missingPanel() {
  return (
    '<div class="empty" style="margin-top:8vh"><h3>' + esc(t("error.notFound")) + "</h3>" +
    '<p><a class="btn" href="#/">' + esc(t("nav.library")) + "</a></p></div>"
  );
}

function readerErrorPanel(err) {
  return (
    '<div class="reader"><div class="reader-overlay" style="display:grid"><div class="inner">' +
    "<h3>" + esc(t("reader.errorTitle")) + "</h3>" +
    "<p>" + esc(errorText(err)) + "</p>" +
    '<div class="row" style="justify-content:center">' +
    '<button class="btn primary" data-retry>' + esc(t("reader.retry")) + "</button>" +
    '<button class="btn" data-exit>' + esc(t("common.close")) + "</button>" +
    "</div></div></div></div>"
  );
}

async function handleRoute({ keepScroll = false } = {}) {
  if (bootFailed) return;
  const route = parseRoute();
  const def = PAGES[route.name];
  const routeToken = ++token;

  if (dispose) {
    try {
      dispose();
    } catch (err) {
      console.error(err);
    }
    dispose = null;
  }

  const isReader = route.name === "reader";
  if (isReader) {
    shell.hidden = true;
    readerRoot.hidden = false;
    document.body.classList.add("reader-open");
  } else {
    readerRoot.hidden = true;
    readerRoot.innerHTML = "";
    shell.hidden = false;
    document.body.classList.remove("reader-open");
    if (!keepScroll) window.scrollTo(0, 0);
  }

  currentNav = def ? def.nav : "";
  paintTopbar();
  searchInput.value = route.name === "library" ? (route.query.get("q") || "") : "";
  const pageTitle = def ? def.title() : "";
  document.title = pageTitle ? pageTitle + " · ComicNest" : "ComicNest";

  const host = isReader ? readerRoot : view;
  if (!isReader) host.innerHTML = "";

  if (!def) {
    host.innerHTML = missingPanel();
    return;
  }

  const ctx = {
    params: route.params,
    query: route.query,
    navigate(hash) {
      if (String(hash) === location.hash) return;
      location.hash = hash;
    },
    reload() {
      handleRoute();
    },
    refresh() {
      handleRoute({ keepScroll: true });
    },
    isCurrent() {
      return routeToken === token;
    },
  };

  try {
    const result = await def.module.render(host, ctx);
    if (routeToken !== token) {
      if (result && typeof result.dispose === "function") {
        try {
          result.dispose();
        } catch (err) {
          console.error(err);
        }
      }
      return;
    }
    dispose = result && typeof result.dispose === "function" ? result.dispose : null;
  } catch (err) {
    if (routeToken !== token) return;
    console.error(err);
    if (isReader) {
      readerRoot.innerHTML = readerErrorPanel(err);
      readerRoot.querySelector("[data-retry]").addEventListener("click", () => handleRoute());
      readerRoot.querySelector("[data-exit]").addEventListener("click", () => {
        location.hash = "#/";
      });
    } else {
      host.innerHTML = errorPanel(err, true);
      host.querySelector("[data-retry]").addEventListener("click", () => handleRoute());
    }
  }
}

/* ------------------------------------------------------------------- boot */

function bootSkeleton() {
  return (
    '<div class="stack"><div>' +
    '<div class="skeleton" style="height:40px;width:min(260px,60%);margin-bottom:14px"></div>' +
    '<div class="skeleton" style="height:16px;width:min(420px,80%)"></div>' +
    "</div>" +
    '<div class="grid">' +
    Array.from({ length: 8 }, () =>
      '<div class="card"><div class="cover skeleton"></div>' +
      '<div class="skeleton" style="height:13px;margin:12px 2px 0;width:82%"></div>' +
      '<div class="skeleton" style="height:11px;margin:7px 2px 0;width:52%"></div></div>'
    ).join("") +
    "</div></div>"
  );
}

function showBootError(err) {
  shell.hidden = false;
  readerRoot.hidden = true;
  view.innerHTML =
    '<div class="empty" style="margin-top:10vh"><h3>ComicNest</h3>' +
    "<p>" + esc(errorText(err)) + "</p>" +
    '<button class="btn primary" data-reload>' + esc(t("common.retry")) + "</button></div>";
  view.querySelector("[data-reload]").addEventListener("click", () => window.location.reload());
}

async function boot() {
  paintTopbar();
  wireTopbar();
  if (!location.hash) {
    history.replaceState(null, "", location.pathname + location.search + "#/");
  }
  view.innerHTML = bootSkeleton();
  try {
    const [me, options] = await Promise.all([api.get("api/me"), api.get("api/options")]);
    store.me = me;
    store.options = options;
    if (me && me.user) setApiUser(me.user);
  } catch (err) {
    bootFailed = true;
    showBootError(err);
    return;
  }
  paintTopbar();
  window.addEventListener("hashchange", () => handleRoute());
  document.addEventListener("comicnest:theme", paintTopbar);
  document.addEventListener("comicnest:language", () => {
    paintTopbar();
    if (parseRoute().name !== "reader") handleRoute({ keepScroll: true });
  });
  document.addEventListener("comicnest:refresh", () => handleRoute({ keepScroll: true }));
  await handleRoute();
}

boot();
