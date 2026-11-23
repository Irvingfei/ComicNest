/* DOM helpers, toasts and modal dialogs. */

import { blobUrl } from "./api.js";
import { t, messageForCode } from "./i18n.js";

export function esc(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function node(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

export function toast(message, kind = "") {
  let host = document.querySelector(".toast-host");
  if (!host) {
    host = document.createElement("div");
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const item = document.createElement("div");
  item.className = "toast" + (kind ? " " + kind : "");
  item.textContent = message;
  host.appendChild(item);
  window.setTimeout(() => {
    item.style.opacity = "0";
    item.style.transition = "opacity .2s ease";
    window.setTimeout(() => item.remove(), 220);
  }, kind === "error" ? 4200 : 2600);
}

export function errorText(err) {
  if (!err) return t("error.generic");
  if (err.code === -1 || err.message === "network") return t("error.network");
  return messageForCode(err.code, err.message || t("error.generic"));
}

export function fmtSize(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return Math.round(value) + " B";
  const units = ["KB", "MB", "GB", "TB"];
  let scaled = value / 1024;
  let index = 0;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  return (scaled >= 10 ? scaled.toFixed(0) : scaled.toFixed(1)) + " " + units[index];
}

export function pad(value) {
  return String(value).padStart(2, "0");
}

export function timeAgo(iso) {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return t("time.justNow");
  if (seconds < 3600) return t("time.minutesAgo", { n: Math.floor(seconds / 60) });
  if (seconds < 86400) return t("time.hoursAgo", { n: Math.floor(seconds / 3600) });
  return t("time.daysAgo", { n: Math.floor(seconds / 86400) });
}

export function percentOf(progress) {
  if (!progress) return 0;
  if (progress.percent !== undefined && progress.percent !== null) return progress.percent;
  const total = Number(progress.total_pages) || 0;
  if (!total) return 0;
  return Math.min(100, Math.round(((Number(progress.page) || 0) + 1) * 100 / total));
}

export function chapterState(chapter) {
  const progress = chapter.progress;
  if (!progress) return "unread";
  const total = Number(progress.total_pages) || Number(chapter.page_count) || 0;
  if (total && Number(progress.page) + 1 >= total) return "read";
  return "reading";
}

export function openModal({ title, subtitle = "", body, className = "", onMount, onClose }) {
  const backdrop = node(
    '<div class="modal-backdrop"><div class="modal ' + esc(className) + '" role="dialog" aria-modal="true">' +
      '<div class="modal-head"><div><h2 class="modal-title">' + esc(title) + "</h2>" +
      (subtitle ? '<p class="modal-sub">' + esc(subtitle) + "</p>" : "") +
      '</div><button class="icon-btn" data-close aria-label="' + esc(t("common.close")) + '">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button></div><div class=\"modal-body\"></div></div></div>"
  );
  const bodyHost = backdrop.querySelector(".modal-body");
  if (typeof body === "string") bodyHost.innerHTML = body;
  else if (body) bodyHost.appendChild(body);

  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
    if (onClose) onClose();
  }
  function onKey(event) {
    if (event.key === "Escape") close();
  }
  document.addEventListener("keydown", onKey);
  backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) close();
  });
  backdrop.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", close);
  });
  document.body.appendChild(backdrop);
  if (onMount) onMount(bodyHost, close);
  const focusable = bodyHost.querySelector("input, select, textarea, button");
  if (focusable) window.setTimeout(() => focusable.focus(), 30);
  return { root: backdrop, close };
}

export function confirmDialog({ title, message, confirmLabel, danger = true }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const modal = openModal({
      title,
      body:
        '<p class="hint" style="font-size:14px;line-height:1.6">' + esc(message) + "</p>" +
        '<div class="form-actions"><button class="btn" data-no>' + esc(t("common.cancel")) +
        '</button><button class="btn ' + (danger ? "danger" : "primary") + '" data-yes>' +
        esc(confirmLabel || t("common.delete")) + "</button></div>",
      onMount(host, close) {
        host.querySelector("[data-no]").addEventListener("click", () => {
          finish(false);
          close();
        });
        host.querySelector("[data-yes]").addEventListener("click", () => {
          finish(true);
          close();
        });
      },
      onClose() {
        finish(false);
      },
    });
    return modal;
  });
}

export function skeletonGrid(count = 8) {
  let html = '<div class="grid">';
  for (let index = 0; index < count; index += 1) {
    html += '<div class="card"><div class="cover skeleton"></div><div class="skeleton" style="height:13px;margin:12px 2px 0;width:82%"></div><div class="skeleton" style="height:11px;margin:7px 2px 0;width:52%"></div></div>';
  }
  html += "</div>";
  return html;
}

export function segmented(options, value, name) {
  return (
    '<div class="seg" data-seg="' + esc(name) + '">' +
    options
      .map(
        (option) =>
          '<button type="button" data-value="' + esc(option.value) + '"' +
          (option.value === value ? ' class="active"' : "") + ">" +
          esc(option.label) + "</button>"
      )
      .join("") +
    "</div>"
  );
}

export function wireSegmented(root, name, onChange) {
  const seg = root.querySelector('[data-seg="' + name + '"]');
  if (!seg) return;
  seg.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    seg.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    onChange(button.dataset.value);
  });
}

export function sourceIcon(kind) {
  if (kind === "webdav") return "cloud";
  if (kind === "smb") return "server";
  return "hardDrive";
}

/* Covers are authenticated binary responses, so they arrive as blobs. Only
   fetch the ones about to be seen; a library with a thousand series should not
   start a thousand requests because the page opened. */
export function hydrateCovers(root, margin = "500px") {
  const images = Array.from(root.querySelectorAll("img[data-cover]"));
  if (!images.length) return { disconnect() {} };

  const load = (img) => {
    if (img.dataset.state === "loading" || img.dataset.state === "done") return;
    img.dataset.state = "loading";
    blobUrl(img.dataset.cover)
      .then((url) => {
        img.onload = () => {
          img.dataset.state = "done";
          img.removeAttribute("hidden");
          const fallback = img.parentElement && img.parentElement.querySelector(".fallback");
          if (fallback) fallback.remove();
        };
        img.onerror = () => {
          img.dataset.state = "error";
          img.remove();
        };
        img.src = url;
      })
      .catch(() => {
        img.dataset.state = "error";
        img.remove();
      });
  };

  if (!("IntersectionObserver" in window)) {
    images.forEach(load);
    return { disconnect() {} };
  }
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          observer.unobserve(entry.target);
          load(entry.target);
        }
      }
    },
    { rootMargin: margin }
  );
  images.forEach((img) => observer.observe(img));
  return {
    disconnect() {
      observer.disconnect();
    },
  };
}
