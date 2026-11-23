import { api, apiUrl, authHeaders, blobUrl } from "../api.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { store } from "../store.js";
import { errorText, esc } from "../ui.js";

const WIDE_RATIO = 1.25;
const PDF_CACHE_LIMIT = 40;

function isWide(page) {
  return Boolean(page && page.w && page.h && page.w / page.h >= WIDE_RATIO);
}

function buildSpreads(pages, mode, direction) {
  if (direction === "vertical") {
    return pages.map((_, index) => [{ page: index }]);
  }
  if (mode === "single") {
    return pages.map((_, index) => [{ page: index }]);
  }
  if (mode === "double") {
    const spreads = [];
    let index = 0;
    while (index < pages.length) {
      if (isWide(pages[index])) {
        spreads.push([{ page: index }]);
        index += 1;
      } else if (index + 1 < pages.length && !isWide(pages[index + 1])) {
        spreads.push([{ page: index }, { page: index + 1 }]);
        index += 2;
      } else {
        spreads.push([{ page: index }]);
        index += 1;
      }
    }
    return spreads;
  }
  /* split: wide pages become two portrait halves. Pair halves with the pages
     around them, never with their own other half - that would simply redraw
     the wide page as a spread and defeat the mode. */
  const slots = [];
  pages.forEach((page, index) => {
    if (isWide(page)) {
      slots.push({ page: index, half: "left" });
      slots.push({ page: index, half: "right" });
    } else {
      slots.push({ page: index });
    }
  });
  const spreads = [];
  let pending = null;
  for (const slot of slots) {
    if (!pending) {
      pending = slot;
      continue;
    }
    if (pending.half === "left" && slot.half === "right" && pending.page === slot.page) {
      spreads.push([pending]);
      pending = slot;
      continue;
    }
    spreads.push([pending, slot]);
    pending = null;
  }
  if (pending) spreads.push([pending]);
  return spreads;
}

function spreadForPage(spreads, page) {
  let index = spreads.findIndex((spread) => spread.some((slot) => slot.page === page));
  if (index < 0) {
    index = spreads.findIndex((spread) => spread[0] && spread[0].page >= page);
  }
  return index < 0 ? spreads.length - 1 : index;
}

export async function render(host, ctx) {
  const chapterId = Number(ctx.params[0] || 0);
  if (!chapterId) {
    ctx.navigate("#/");
    return {};
  }

  const settings = store.settings;
  const state = {
    chapterId,
    meta: null,
    seriesId: 0,
    format: "images",
    pages: [],
    pdfDoc: null,
    pdfTask: null,
    pdfCache: new Map(),
    objectUrls: new Set(),
    pinned: new Set(),
    mode: settings.mode,
    direction: settings.direction,
    lastHorizontal: settings.direction === "vertical" ? "rtl" : settings.direction,
    animation: settings.animation,
    brightness: settings.brightness,
    zoom: settings.zoom,
    spreads: [],
    spreadIndex: 0,
    page: 0,
    offsets: [],
    disposed: false,
    ready: false,
    dragging: null,
    pan: { x: 0, y: 0 },
    saveTimer: null,
    lastSavedKey: "",
    chromeTimer: null,
    wheelLock: false,
    scrollFrame: 0,
    resizeTimer: 0,
    verticalObserver: null,
    fullscreen: false,
    overlayVisible: false,
    menuOpen: false,
  };

  host.innerHTML =
    '<div class="reader" data-reader>' +
    '<div class="reader-stage" data-stage>' +
    '<div class="reader-pages" data-pages></div>' +
    '<div class="reader-vertical" data-vertical hidden></div>' +
    "</div>" +
    '<div class="reader-dim" data-dim></div>' +
    '<header class="reader-chrome top"><div class="reader-top">' +
    '<button class="reader-icon-btn" data-close title="' + esc(t("reader.close")) + '">' + icon("arrowLeft") + "</button>" +
    '<div class="reader-title"><strong data-series>ComicNest</strong><span data-chapter></span></div>' +
    '<span class="reader-page-count" data-count></span>' +
    '<button class="reader-icon-btn" data-fullscreen title="' + esc(t("reader.fullscreen") || "Fullscreen") + '">' + icon("maximize") + "</button>" +
    "</div></header>" +
    '<footer class="reader-chrome bottom"><div class="reader-progress-row">' +
    '<button class="reader-nav-btn" data-prev-page title="' + esc(t("reader.prev")) + '">' + icon("chevronLeft") + "</button>" +
    '<div class="reader-slider-wrap"><input type="range" min="1" max="1" value="1" step="1" data-slider aria-label="' + esc(t("reader.page")) + '"></div>' +
    '<button class="reader-nav-btn" data-next-page title="' + esc(t("reader.next")) + '">' + icon("chevronRight") + "</button></div>" +
    '<div class="reader-tools">' +
    '<div class="reader-tool"><label>' + esc(t("settings.mode")) + "</label>" +
    '<div class="reader-seg" data-seg="mode">' +
    ["single", "double", "split"].map((value) =>
      '<button type="button" data-value="' + value + '">' + esc(t("reader." + value)) + "</button>"
    ).join("") + "</div></div>" +
    '<div class="reader-tool"><label>' + esc(t("settings.direction")) + '</label>' +
    '<div class="reader-menu" data-menu="direction">' +
    '<button type="button" class="reader-select" data-menu-toggle aria-haspopup="listbox" aria-expanded="false">' +
    '<span data-menu-label></span>' + icon("chevronDown") + "</button>" +
    '<div class="reader-menu-list" data-menu-list role="listbox" hidden></div></div></div>' +
    '<div class="reader-tool"><label>' + esc(t("settings.animation")) + '</label>' +
    '<div class="reader-menu" data-menu="animation">' +
    '<button type="button" class="reader-select" data-menu-toggle aria-haspopup="listbox" aria-expanded="false">' +
    '<span data-menu-label></span>' + icon("chevronDown") + "</button>" +
    '<div class="reader-menu-list" data-menu-list role="listbox" hidden></div></div></div>' +
    '<div class="reader-tool"><label>' + esc(t("reader.brightness")) + '</label>' +
    '<input type="range" min="30" max="100" step="1" data-ctl="brightness"></div>' +
    '<div class="reader-tool"><label>' + esc(t("reader.zoom")) + '</label>' +
    '<input type="range" min="100" max="300" step="5" data-ctl="zoom"><span data-zoom-value></span></div>' +
    '<span class="spacer"></span>' +
    '<button class="reader-select" data-prev-chapter>' + icon("chevronLeft") + '<span>' + esc(t("reader.prevChapter")) + "</span></button>" +
    '<button class="reader-select" data-next-chapter><span>' + esc(t("reader.nextChapter")) + "</span>" + icon("chevronRight") + "</button>" +
    "</div></footer>" +
    '<div class="reader-overlay" data-overlay><div class="inner"></div></div>' +
    "</div>";

  const reader = host.querySelector("[data-reader]");
  const stage = host.querySelector("[data-stage]");
  const pagesHost = host.querySelector("[data-pages]");
  const vertical = host.querySelector("[data-vertical]");
  const overlay = host.querySelector("[data-overlay]");
  const countEl = host.querySelector("[data-count]");
  const slider = host.querySelector("[data-slider]");
  const prevButton = host.querySelector("[data-prev-page]");
  const nextButton = host.querySelector("[data-next-page]");
  const prevChapter = host.querySelector("[data-prev-chapter]");
  const nextChapter = host.querySelector("[data-next-chapter]");
  const zoomValue = host.querySelector("[data-zoom-value]");
  const seriesEl = host.querySelector("[data-series]");
  const chapterEl = host.querySelector("[data-chapter]");
  const brightnessInput = host.querySelector('[data-ctl="brightness"]');
  const zoomInput = host.querySelector('[data-ctl="zoom"]');
  const modeSeg = host.querySelector('[data-seg="mode"]');

  /* --------------------------------------------------------------- menus */

  function menuControl(name, values, onChange) {
    const root = reader.querySelector('[data-menu="' + name + '"]');
    const toggle = root.querySelector("[data-menu-toggle]");
    const label = root.querySelector("[data-menu-label]");
    const list = root.querySelector("[data-menu-list]");
    let current = values[0];

    list.innerHTML = values
      .map((value) => '<button type="button" role="option" data-value="' + value + '">' + esc(t("reader." + value)) + "</button>")
      .join("");

    function setOpen(open) {
      root.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      list.hidden = !open;
      state.menuOpen = open;
      if (!open) return;
      /* fixed positioning so the menu is not clipped by the scrollable
         tool row on narrow windows */
      const rect = toggle.getBoundingClientRect();
      const width = Math.max(136, Math.round(rect.width));
      list.style.minWidth = width + "px";
      list.style.left = Math.max(8, Math.min(Math.round(rect.left), window.innerWidth - width - 8)) + "px";
      list.style.bottom = Math.round(window.innerHeight - rect.top + 8) + "px";
      showChrome(false);
    }

    function setValue(value, notify) {
      if (!values.includes(value)) return;
      current = value;
      label.textContent = t("reader." + value);
      list.querySelectorAll("[data-value]").forEach((button) => {
        const active = button.dataset.value === value;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      if (notify) onChange(value);
    }

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      setOpen(!root.classList.contains("open"));
    });
    list.addEventListener("click", (event) => {
      const option = event.target.closest("[data-value]");
      if (!option) return;
      setOpen(false);
      setValue(option.dataset.value, true);
    });

    return {
      setValue,
      close: () => setOpen(false),
      isOpen: () => root.classList.contains("open"),
    };
  }

  const directionMenu = menuControl("direction", ["rtl", "ltr", "vertical"], (value) => applyDirection(value));
  const animationMenu = menuControl("animation", ["slide", "scroll", "flip"], (value) => applyAnimation(value));

  function closeMenus() {
    directionMenu.close();
    animationMenu.close();
  }

  /* ------------------------------------------------------------- overlay */

  function showOverlay({ title, text, spinner = false, primary, onPrimary, secondary, onSecondary }) {
    const inner = overlay.querySelector(".inner");
    inner.innerHTML =
      (spinner ? '<div class="reader-spinner"></div>' : "") +
      "<h3>" + esc(title || "") + "</h3>" +
      (text ? "<p>" + esc(text) + "</p>" : "") +
      (primary || secondary
        ? '<div class="row" style="justify-content:center">' +
          (primary ? '<button class="btn primary" data-primary>' + esc(primary) + "</button>" : "") +
          (secondary ? '<button class="btn" data-secondary>' + esc(secondary) + "</button>" : "") +
          "</div>"
        : "");
    overlay.style.display = "grid";
    state.overlayVisible = true;
    const primaryButton = inner.querySelector("[data-primary]");
    if (primaryButton && onPrimary) primaryButton.addEventListener("click", onPrimary);
    const secondaryButton = inner.querySelector("[data-secondary]");
    if (secondaryButton && onSecondary) secondaryButton.addEventListener("click", onSecondary);
  }

  function hideOverlay() {
    overlay.style.display = "none";
    state.overlayVisible = false;
  }

  function showError(err) {
    showOverlay({
      title: t("reader.errorTitle"),
      text: errorText(err),
      primary: t("reader.retry"),
      onPrimary: () => ctx.reload(),
      secondary: t("common.close"),
      onSecondary: () => closeReader(),
    });
  }

  /* --------------------------------------------------------------- chrome */

  function chromeBusy() {
    if (state.menuOpen) return true;
    const hovered = Array.from(reader.querySelectorAll(".reader-chrome")).some((element) => element.matches(":hover"));
    return hovered || Boolean(reader.querySelector(".reader-chrome :focus"));
  }

  function showChrome(autoHide = true) {
    reader.classList.remove("chrome-hidden");
    if (state.chromeTimer) clearTimeout(state.chromeTimer);
    if (autoHide) {
      state.chromeTimer = window.setTimeout(() => {
        if (state.dragging || chromeBusy()) return;
        reader.classList.add("chrome-hidden");
      }, 2800);
    }
  }

  function toggleChrome() {
    if (reader.classList.contains("chrome-hidden")) showChrome();
    else {
      closeMenus();
      reader.classList.add("chrome-hidden");
      if (state.chromeTimer) clearTimeout(state.chromeTimer);
    }
  }

  /* -------------------------------------------------------------- storage */

  function totalPages() {
    return state.pages.length;
  }

  function progressBody() {
    return {
      page: state.page,
      total_pages: totalPages() || null,
      mode: state.mode,
      direction: state.direction,
      animation: state.animation,
    };
  }

  function progressKey(body) {
    return [body.page, body.total_pages, body.mode, body.direction, body.animation].join("|");
  }

  function scheduleSave() {
    if (state.saveTimer) clearTimeout(state.saveTimer);
    state.saveTimer = window.setTimeout(saveProgress, 900);
  }

  async function saveProgress() {
    if (!state.ready || !totalPages()) return;
    const body = progressBody();
    const key = progressKey(body);
    if (key === state.lastSavedKey) return;
    state.lastSavedKey = key;
    try {
      await api.put("api/progress/" + chapterId, body);
    } catch {
      /* progress is best effort; the page itself must not fail because of it */
    }
  }

  function saveOnExit() {
    if (!state.ready || !totalPages()) return;
    const body = progressBody();
    const key = progressKey(body);
    if (key === state.lastSavedKey) return;
    state.lastSavedKey = key;
    try {
      fetch(apiUrl("api/progress/" + chapterId), {
        method: "PUT",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    } catch {
      /* ignore */
    }
  }

  /* ----------------------------------------------------------------- pdf */

  async function loadPdf(url) {
    const pdfjs = await import("../../vendor/pdfjs/pdf.min.mjs");
    pdfjs.GlobalWorkerOptions.workerSrc = new URL("../../vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).href;
    const headers = authHeaders();
    delete headers.Accept;
    const task = pdfjs.getDocument({
      url: apiUrl(url),
      httpHeaders: headers,
      cMapUrl: new URL("../../vendor/pdfjs/cmaps/", import.meta.url).href,
      cMapPacked: true,
      standardFontDataUrl: new URL("../../vendor/pdfjs/standard_fonts/", import.meta.url).href,
    });
    state.pdfTask = task;
    const doc = await task.promise;
    if (state.disposed) {
      try {
        await doc.destroy();
      } catch {
        /* ignore */
      }
      return [];
    }
    state.pdfDoc = doc;
    const count = doc.numPages;
    const dims = new Array(count);
    let cursor = 0;
    const worker = async () => {
      while (cursor < count) {
        const index = cursor;
        cursor += 1;
        try {
          const page = await doc.getPage(index + 1);
          const viewport = page.getViewport({ scale: 1 });
          dims[index] = { w: viewport.width, h: viewport.height };
        } catch {
          dims[index] = { w: 1000, h: 1400 };
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(6, count) }, worker));
    return dims;
  }

  async function renderPdfPage(index) {
    const doc = state.pdfDoc;
    if (!doc) throw new Error("pdf not ready");
    const page = await doc.getPage(index + 1);
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(3, 2300 / Math.max(base.width, base.height));
    const viewport = page.getViewport({ scale: Math.max(1, scale) });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: context, viewport }).promise;
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    canvas.width = 0;
    canvas.height = 0;
    if (!blob) throw new Error("pdf render failed");
    return URL.createObjectURL(blob);
  }

  function pdfUrl(index) {
    const cached = state.pdfCache.get(index);
    if (cached) {
      state.pdfCache.delete(index);
      state.pdfCache.set(index, cached);
      return cached;
    }
    const promise = renderPdfPage(index).then((url) => {
      state.objectUrls.add(url);
      return url;
    });
    state.pdfCache.set(index, promise);
    promise.catch(() => {
      if (state.pdfCache.get(index) === promise) state.pdfCache.delete(index);
    });
    trimPdfCache();
    return promise;
  }

  function trimPdfCache() {
    /* Vertical mode keeps every rendered page: they stay on screen as the
       reader scrolls back up, so revoking one would leave a broken image. */
    if (state.direction === "vertical") return;
    if (state.pdfCache.size <= PDF_CACHE_LIMIT) return;
    for (const [index, promise] of Array.from(state.pdfCache.entries())) {
      if (state.pdfCache.size <= PDF_CACHE_LIMIT) break;
      if (state.pinned.has(index)) continue;
      state.pdfCache.delete(index);
      Promise.resolve(promise)
        .then((url) => {
          state.objectUrls.delete(url);
          try {
            URL.revokeObjectURL(url);
          } catch {
            /* ignore */
          }
        })
        .catch(() => {});
    }
  }

  function loadUrl(index) {
    if (state.format === "pdf") return pdfUrl(index);
    const page = state.pages[index];
    if (!page || !page.url) return Promise.reject(new Error("page has no image"));
    return blobUrl(page.url);
  }

  function pin(indices) {
    state.pinned = new Set(indices);
    trimPdfCache();
  }

  /* ------------------------------------------------------------- rendering */

  function setTurn(wrap, forward) {
    if (!state.animation) return;
    const sign = (state.direction === "rtl" ? -1 : 1) * (forward ? 1 : -1);
    wrap.style.setProperty("--enter-x", sign * 18 + "%");
    wrap.style.setProperty("--enter-y", (forward ? 72 : -72) + "px");
    wrap.style.setProperty("--flip-angle", sign * 52 + "deg");
    wrap.style.setProperty("--flip-origin", state.direction === "rtl" ? "right center" : "left center");
    wrap.classList.add("turn-" + state.animation);
  }

  function makeSlot(slot, slotCount) {
    const element = document.createElement("div");
    element.className = "reader-slot";

    const page = state.pages[slot.page];
    if (slot.half) {
      const half = document.createElement("div");
      half.className = "reader-half" + (slot.half === "right" ? " right" : "");
      element.appendChild(half);
      loadUrl(slot.page)
        .then((url) => {
          if (state.disposed) return;
          half.style.backgroundImage = "url(\"" + url + "\")";
          const w = (page && page.w) || 1000;
          const h = (page && page.h) || 1400;
          const availableWidth = (stage.clientWidth - 8) / Math.max(1, slotCount);
          const availableHeight = stage.clientHeight - 8;
          const halfWidth = w / 2;
          const scale = Math.min(availableWidth / halfWidth, availableHeight / h);
          half.style.width = Math.max(1, Math.round(halfWidth * scale)) + "px";
          half.style.height = Math.max(1, Math.round(h * scale)) + "px";
        })
        .catch((err) => {
          if (!state.disposed) showError(err);
        });
    } else {
      const img = document.createElement("img");
      img.alt = "";
      img.draggable = false;
      element.appendChild(img);
      loadUrl(slot.page)
        .then((url) => {
          if (state.disposed) return;
          img.src = url;
          if (page && (!page.w || !page.h) && img.naturalWidth) {
            page.w = img.naturalWidth;
            page.h = img.naturalHeight;
          }
        })
        .catch((err) => {
          if (!state.disposed) showError(err);
        });
    }
    return element;
  }

  function renderSpread(animate = false, forward = true) {
    const spread = state.spreads[state.spreadIndex] || [];
    if (!spread.length) return;
    const previous = pagesHost.querySelector(".reader-spread:not(.reader-spread-ghost)");
    pagesHost.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "reader-spread" + (state.direction === "rtl" ? " rtl" : "");
    spread.forEach((slot) => wrap.appendChild(makeSlot(slot, spread.length)));
    /* keep the page being left underneath so motion reads as a page turn
       instead of the new page fading in from black */
    let ghost = null;
    if (animate && previous) {
      previous.classList.remove("turn-slide", "turn-scroll", "turn-flip");
      previous.classList.add("reader-spread-ghost");
      pagesHost.appendChild(previous);
      ghost = previous;
    }
    pagesHost.appendChild(wrap);
    state.page = spread[0].page;
    pin(spread.map((slot) => slot.page));
    if (animate) {
      setTurn(wrap, forward);
      if (ghost) {
        const drop = () => ghost.remove();
        wrap.addEventListener("animationend", drop, { once: true });
        window.setTimeout(() => {
          if (ghost.isConnected) ghost.remove();
        }, 700);
      }
    }
    updateChrome();

    const upcoming = state.spreads[state.spreadIndex + 1];
    if (upcoming) {
      upcoming.forEach((slot) => {
        loadUrl(slot.page).catch(() => {});
      });
    }
  }

  function renderVertical() {
    pagesHost.innerHTML = "";
    vertical.hidden = false;
    vertical.innerHTML = "";
    const fragment = document.createDocumentFragment();
    state.pages.forEach((page, index) => {
      const item = document.createElement("div");
      item.className = "vertical-item";
      item.dataset.index = String(index);
      if (page.w && page.h) item.style.aspectRatio = page.w + " / " + page.h;
      const img = document.createElement("img");
      img.alt = "";
      img.draggable = false;
      img.loading = "lazy";
      item.appendChild(img);
      fragment.appendChild(item);
    });
    vertical.appendChild(fragment);
    if (state.verticalObserver) state.verticalObserver.disconnect();
    state.verticalObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          state.verticalObserver.unobserve(entry.target);
          const index = Number(entry.target.dataset.index);
          const img = entry.target.querySelector("img");
          loadUrl(index)
            .then((url) => {
              if (state.disposed) return;
              img.src = url;
              img.classList.add("turn-scroll");
            })
            .catch((err) => {
              if (!state.disposed) showError(err);
            });
        }
      },
      { root: vertical, rootMargin: "1600px 0px" }
    );
    Array.from(vertical.children).forEach((item) => state.verticalObserver.observe(item));
    measureVertical();
    window.requestAnimationFrame(() => scrollToPage(state.page, false));
    updateChrome();
  }

  function measureVertical() {
    state.offsets = Array.from(vertical.querySelectorAll(".vertical-item")).map((item) => ({
      top: item.offsetTop,
      height: item.offsetHeight,
    }));
  }

  function pageAtScroll() {
    if (!state.offsets.length) return 0;
    const probe = vertical.scrollTop + vertical.clientHeight * 0.35;
    let low = 0;
    let high = state.offsets.length - 1;
    let found = 0;
    while (low <= high) {
      const mid = (low + high) >> 1;
      const item = state.offsets[mid];
      if (item.top <= probe) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  function onVerticalScroll() {
    if (state.scrollFrame) return;
    state.scrollFrame = window.requestAnimationFrame(() => {
      state.scrollFrame = 0;
      if (state.direction !== "vertical" || !state.offsets.length) return;
      const page = pageAtScroll();
      if (page !== state.page) {
        state.page = page;
        updateChrome();
        scheduleSave();
      }
      const pinned = [];
      for (let offset = -2; offset <= 4; offset += 1) {
        const index = page + offset;
        if (index >= 0 && index < state.pages.length) pinned.push(index);
      }
      pin(pinned);
    });
  }

  function scrollToPage(page, smooth) {
    const index = Math.max(0, Math.min(state.pages.length - 1, Number(page) || 0));
    if (!state.offsets[index]) {
      const item = vertical.querySelector('.vertical-item[data-index="' + index + '"]');
      if (item) vertical.scrollTop = item.offsetTop;
    } else {
      vertical.scrollTo({ top: Math.max(0, state.offsets[index].top), behavior: smooth ? "smooth" : "auto" });
    }
    state.page = index;
    updateChrome();
  }

  /* ------------------------------------------------------------ navigation */

  function updateChrome() {
    if (!state.ready && !state.pages.length) return;
    const total = totalPages();
    countEl.textContent = total ? t("reader.page", { page: state.page + 1, total }) : "";
    slider.max = String(Math.max(1, total));
    slider.value = String(Math.min(total || 1, state.page + 1));
    slider.disabled = total <= 1;
    prevButton.disabled = state.direction === "vertical" ? state.page <= 0 : state.spreadIndex <= 0;
    nextButton.disabled = false;
    modeSeg.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button.dataset.value === state.mode);
    });
    directionMenu.setValue(state.direction);
    animationMenu.setValue(state.animation);
    brightnessInput.value = String(state.brightness);
    zoomInput.value = String(state.zoom);
    zoomValue.textContent = t("reader.zoomValue", { n: state.zoom });
    prevChapter.disabled = !state.meta || !state.meta.prev_chapter_id;
    nextChapter.disabled = !state.meta || !state.meta.next_chapter_id;
    reader.style.setProperty("--dim", String(((100 - state.brightness) / 100) * 0.72));
    reader.style.setProperty("--zoom", String(state.zoom / 100));
    reader.classList.toggle("pannable", state.zoom > 100 && state.direction !== "vertical");
    vertical.classList.toggle("zoomed", state.zoom > 100);
  }

  function goToSpread(index, animate = true) {
    if (!state.spreads.length) return;
    const clamped = Math.max(0, Math.min(state.spreads.length - 1, index));
    const forward = clamped > state.spreadIndex;
    state.spreadIndex = clamped;
    state.pan = { x: 0, y: 0 };
    pagesHost.style.setProperty("--pan-x", "0px");
    pagesHost.style.setProperty("--pan-y", "0px");
    renderSpread(animate, forward);
    scheduleSave();
  }

  function goToPage(page, animate = true) {
    if (!state.pages.length) return;
    const target = Math.max(0, Math.min(state.pages.length - 1, page));
    if (state.direction === "vertical") {
      scrollToPage(target, animate);
      scheduleSave();
      return;
    }
    const index = spreadForPage(state.spreads, target);
    goToSpread(index, animate);
  }

  function nextPage() {
    if (!state.pages.length) return;
    if (state.direction === "vertical") {
      if (state.page + 1 < state.pages.length) scrollToPage(state.page + 1, true);
      return;
    }
    if (state.spreadIndex + 1 < state.spreads.length) {
      goToSpread(state.spreadIndex + 1, true);
      return;
    }
    showOverlay({
      title: t("reader.endTitle"),
      text: t("reader.endDesc"),
      primary: state.meta && state.meta.next_chapter_id ? t("reader.nextChapter") : null,
      onPrimary: () => goChapter(state.meta && state.meta.next_chapter_id),
      secondary: t("reader.close"),
      onSecondary: () => closeReader(),
    });
    if (state.meta && state.meta.next_chapter_id) {
      const extra = overlay.querySelector(".inner");
      const restart = document.createElement("button");
      restart.className = "btn";
      restart.style.marginLeft = "8px";
      restart.textContent = t("reader.restart");
      restart.addEventListener("click", () => {
        hideOverlay();
        goToPage(0);
      });
      extra.querySelector(".row").appendChild(restart);
    }
  }

  function prevPage() {
    if (!state.pages.length) return;
    if (state.direction === "vertical") {
      if (state.page > 0) scrollToPage(state.page - 1, true);
      return;
    }
    if (state.spreadIndex > 0) goToSpread(state.spreadIndex - 1, true);
  }

  function goChapter(id) {
    if (!id || Number(id) === chapterId) return;
    saveProgress();
    ctx.navigate("#/read/" + Number(id));
  }

  function closeReader() {
    saveOnExit();
    ctx.navigate(state.seriesId ? "#/series/" + state.seriesId : "#/");
  }

  /* ------------------------------------------------------------- controls */

  function applyMode(value) {
    state.mode = value;
    store.update({ mode: value });
    closeMenus();
    if (state.direction === "vertical") {
      /* page layout belongs to paged reading: leave continuous mode so the
         click has a visible effect instead of being ignored */
      applyDirection(state.lastHorizontal);
      return;
    }
    state.spreads = buildSpreads(state.pages, state.mode, state.direction);
    state.spreadIndex = spreadForPage(state.spreads, state.page);
    renderSpread(false);
    updateChrome();
    scheduleSave();
  }

  function applyDirection(value) {
    state.direction = value;
    if (value !== "vertical") state.lastHorizontal = value;
    store.update({ direction: value });
    closeMenus();
    pagesHost.innerHTML = "";
    state.spreads = buildSpreads(state.pages, state.mode, state.direction);
    state.spreadIndex = spreadForPage(state.spreads, state.page);
    if (value === "vertical") {
      renderVertical();
    } else {
      vertical.hidden = true;
      renderSpread(false);
    }
    showChrome();
    scheduleSave();
  }

  function applyAnimation(value) {
    state.animation = value;
    store.update({ animation: value });
    closeMenus();
    updateChrome();
    scheduleSave();
  }

  function applyBrightness(value) {
    state.brightness = Math.max(30, Math.min(100, Number(value) || 100));
    store.update({ brightness: state.brightness });
    updateChrome();
  }

  function applyZoom(value) {
    state.zoom = Math.max(100, Math.min(300, Number(value) || 100));
    store.update({ zoom: state.zoom });
    if (state.zoom === 100) {
      state.pan = { x: 0, y: 0 };
      pagesHost.style.setProperty("--pan-x", "0px");
      pagesHost.style.setProperty("--pan-y", "0px");
    }
    updateChrome();
    if (state.direction === "vertical") {
      window.requestAnimationFrame(() => {
        if (!state.disposed) measureVertical();
      });
    }
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      reader.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }

  /* --------------------------------------------------------------- events */

  function onSegmentClick(event) {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    applyMode(button.dataset.value);
  }

  function onSlider(event) {
    const value = Number(event.target.value) - 1;
    if (state.direction === "vertical") scrollToPage(value, false);
    else goToPage(value, false);
  }

  function onStagePointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    if (state.zoom > 100 && state.direction !== "vertical") {
      state.dragging = {
        x: event.clientX,
        y: event.clientY,
        panX: state.pan.x,
        panY: state.pan.y,
        moved: false,
      };
      stage.setPointerCapture(event.pointerId);
      showChrome(false);
      return;
    }
    state.dragging = {
      x: event.clientX,
      y: event.clientY,
      panX: state.pan.x,
      panY: state.pan.y,
      moved: false,
      swipe: state.direction !== "vertical",
    };
  }

  function onStagePointerMove(event) {
    if (!state.dragging) return;
    const dx = event.clientX - state.dragging.x;
    const dy = event.clientY - state.dragging.y;
    if (Math.abs(dx) > 6 || Math.abs(dy) > 6) state.dragging.moved = true;
    if (state.zoom > 100 && state.direction !== "vertical") {
      const maxX = (stage.clientWidth * (state.zoom / 100 - 1)) / 2;
      const maxY = (stage.clientHeight * (state.zoom / 100 - 1)) / 2;
      state.pan.x = Math.max(-maxX, Math.min(maxX, state.dragging.panX + dx));
      state.pan.y = Math.max(-maxY, Math.min(maxY, state.dragging.panY + dy));
      pagesHost.style.setProperty("--pan-x", state.pan.x + "px");
      pagesHost.style.setProperty("--pan-y", state.pan.y + "px");
    }
  }

  function onStagePointerUp(event) {
    const drag = state.dragging;
    state.dragging = null;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (state.zoom > 100) {
      showChrome();
      return;
    }
    if (state.direction === "vertical") {
      if (!drag.moved) toggleChrome();
      return;
    }
    if (drag.moved && Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy)) {
      const forward = state.direction === "rtl" ? dx > 0 : dx < 0;
      if (forward) nextPage();
      else prevPage();
      return;
    }
    if (!drag.moved) {
      const width = stage.clientWidth;
      if (event.clientX < width * 0.28) {
        if (state.direction === "rtl") nextPage();
        else prevPage();
      } else if (event.clientX > width * 0.72) {
        if (state.direction === "rtl") prevPage();
        else nextPage();
      } else {
        toggleChrome();
      }
    }
  }

  function onWheel(event) {
    if (event.ctrlKey) {
      event.preventDefault();
      applyZoom(state.zoom + (event.deltaY < 0 ? 20 : -20));
      return;
    }
    if (state.direction === "vertical" || Math.abs(event.deltaY) < 24) return;
    if (state.wheelLock) return;
    state.wheelLock = true;
    window.setTimeout(() => {
      state.wheelLock = false;
    }, 360);
    event.preventDefault();
    if (event.deltaY > 0) nextPage();
    else prevPage();
  }

  function onKey(event) {
    if (event.defaultPrevented) return;
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    switch (event.key) {
      case "Escape":
        if (state.menuOpen) closeMenus();
        else if (state.overlayVisible) hideOverlay();
        else closeReader();
        break;
      case "ArrowRight":
        if (state.direction === "rtl") prevPage();
        else if (state.direction === "ltr") nextPage();
        break;
      case "ArrowLeft":
        if (state.direction === "rtl") nextPage();
        else if (state.direction === "ltr") prevPage();
        break;
      case "ArrowDown":
        if (state.direction === "vertical") return;
        event.preventDefault();
        nextPage();
        break;
      case "ArrowUp":
        if (state.direction === "vertical") return;
        event.preventDefault();
        prevPage();
        break;
      case " ":
      case "PageDown":
        if (state.direction === "vertical") return;
        event.preventDefault();
        nextPage();
        break;
      case "PageUp":
        if (state.direction === "vertical") return;
        event.preventDefault();
        prevPage();
        break;
      case "Home":
        event.preventDefault();
        goToPage(0);
        break;
      case "End":
        event.preventDefault();
        goToPage(state.pages.length - 1);
        break;
      case "f":
      case "F":
        toggleFullscreen();
        break;
      default:
        return;
    }
    showChrome();
  }

  function onFullscreenChange() {
    state.fullscreen = Boolean(document.fullscreenElement);
    const button = host.querySelector("[data-fullscreen]");
    if (button) button.innerHTML = icon(state.fullscreen ? "minimize" : "maximize");
    showChrome();
  }

  function onResize() {
    if (state.resizeTimer) clearTimeout(state.resizeTimer);
    state.resizeTimer = window.setTimeout(() => {
      if (state.disposed || !state.ready) return;
      if (state.direction === "vertical") {
        measureVertical();
      } else {
        renderSpread(false);
      }
    }, 180);
  }

  function onVisibility() {
    if (document.visibilityState === "hidden") saveOnExit();
  }

  function onDocumentPointerDown(event) {
    if (state.menuOpen && !(event.target.closest && event.target.closest(".reader-menu"))) closeMenus();
  }

  /* ----------------------------------------------------------------- boot */

  let metaData;
  let pagesData;
  try {
    [metaData, pagesData] = await Promise.all([
      api.get("api/chapter/" + chapterId),
      api.get("api/chapter/" + chapterId + "/pages"),
    ]);
  } catch (err) {
    if (ctx.isCurrent()) showError(err);
    const dispose = () => {};
    return { dispose };
  }
  if (!ctx.isCurrent() || state.disposed) return {};

  state.meta = metaData;
  state.seriesId = metaData.series ? metaData.series.id : 0;
  state.format = pagesData.format;
  const seriesTitle = (metaData.series && metaData.series.title) || "ComicNest";
  const chapterTitle = (metaData.chapter && metaData.chapter.title) || "";
  seriesEl.textContent = seriesTitle;
  chapterEl.textContent = chapterTitle;
  document.title = (chapterTitle ? chapterTitle + " · " : "") + seriesTitle + " · ComicNest";

  const progress = pagesData.progress;
  if (progress) {
    if (["single", "double", "split"].includes(progress.mode)) state.mode = progress.mode;
    if (["rtl", "ltr", "vertical"].includes(progress.direction)) state.direction = progress.direction;
    if (["slide", "scroll", "flip"].includes(progress.animation)) state.animation = progress.animation;
  }
  if (state.direction !== "vertical") state.lastHorizontal = state.direction;

  showOverlay({
    title: t("reader.loading"),
    text: (metaData.series && metaData.series.title) || "",
    spinner: true,
  });

  try {
    if (state.format === "pdf") {
      showOverlay({ title: t("reader.pdfLoading"), spinner: true });
      const dims = await loadPdf(pagesData.pdf_url);
      if (state.disposed || !ctx.isCurrent()) {
        state.disposed = true;
        if (state.pdfTask) state.pdfTask.destroy().catch(() => {});
        return {};
      }
      state.pages = dims.map((dim, index) => ({ index, w: dim.w, h: dim.h, url: "" }));
    } else {
      state.pages = (pagesData.pages || []).map((page) => ({
        index: page.index,
        w: page.w,
        h: page.h,
        url: page.url,
      }));
    }
  } catch (err) {
    if (!state.disposed) showError(err);
    return {
      dispose() {
        saveOnExit();
        if (state.pdfTask) state.pdfTask.destroy().catch(() => {});
      },
    };
  }

  if (!state.pages.length) {
    showOverlay({
      title: t("reader.errorTitle"),
      text: t("reader.errorDesc"),
      secondary: t("common.close"),
      onSecondary: () => closeReader(),
    });
    return {
      dispose() {
        saveOnExit();
        if (state.pdfTask) state.pdfTask.destroy().catch(() => {});
      },
    };
  }

  if (typeof pagesData.page_count === "number" && pagesData.page_count > state.pages.length) {
    /* a stale index row; the real page list wins */
  }

  const startPage = Math.max(0, Math.min(state.pages.length - 1, Number(progress && progress.page) || 0));
  state.page = startPage;
  state.spreads = buildSpreads(state.pages, state.mode, state.direction);
  state.spreadIndex = Math.max(0, Math.min(state.spreads.length - 1, spreadForPage(state.spreads, startPage)));
  state.ready = true;

  updateChrome();
  if (state.direction === "vertical") {
    renderVertical();
  } else {
    vertical.hidden = true;
    renderSpread(false);
  }
  hideOverlay();
  showChrome();
  saveProgress();

  /* events */
  reader.querySelector("[data-close]").addEventListener("click", closeReader);
  host.querySelector("[data-fullscreen]").addEventListener("click", toggleFullscreen);
  prevButton.addEventListener("click", prevPage);
  nextButton.addEventListener("click", nextPage);
  slider.addEventListener("input", onSlider);
  modeSeg.addEventListener("click", onSegmentClick);
  brightnessInput.addEventListener("input", () => applyBrightness(brightnessInput.value));
  zoomInput.addEventListener("input", () => applyZoom(zoomInput.value));
  prevChapter.addEventListener("click", () => goChapter(state.meta && state.meta.prev_chapter_id));
  nextChapter.addEventListener("click", () => goChapter(state.meta && state.meta.next_chapter_id));

  stage.addEventListener("pointerdown", onStagePointerDown);
  stage.addEventListener("pointermove", onStagePointerMove);
  stage.addEventListener("pointerup", onStagePointerUp);
  stage.addEventListener("pointercancel", onStagePointerUp);
  stage.addEventListener("wheel", onWheel, { passive: false });
  vertical.addEventListener("scroll", onVerticalScroll, { passive: true });

  reader.addEventListener("pointermove", () => showChrome());
  reader.addEventListener("pointerleave", () => {
    if (!state.dragging && !state.overlayVisible) reader.classList.add("chrome-hidden");
  });

  document.addEventListener("keydown", onKey);
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("fullscreenchange", onFullscreenChange);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("resize", onResize);
  window.addEventListener("beforeunload", saveOnExit);

  updateChrome();

  return {
    dispose() {
      if (state.disposed) return;
      state.disposed = true;
      saveOnExit();
      if (state.saveTimer) clearTimeout(state.saveTimer);
      if (state.chromeTimer) clearTimeout(state.chromeTimer);
      if (state.resizeTimer) clearTimeout(state.resizeTimer);
      if (state.scrollFrame) cancelAnimationFrame(state.scrollFrame);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDocumentPointerDown);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("beforeunload", saveOnExit);
      if (state.verticalObserver) state.verticalObserver.disconnect();
      state.pdfCache.forEach((promise) => {
        Promise.resolve(promise).catch(() => {});
      });
      state.pdfCache.clear();
      state.objectUrls.forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          /* ignore */
        }
      });
      state.objectUrls.clear();
      if (state.pdfTask) {
        state.pdfTask.destroy().catch(() => {});
      }
      if (document.fullscreenElement === reader) {
        document.exitFullscreen().catch(() => {});
      }
    },
  };
}
