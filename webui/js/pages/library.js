import { api } from "../api.js";
import { icon } from "../icons.js";
import { sourceLabel, t } from "../i18n.js";
import { store } from "../store.js";
import {
  errorText,
  esc,
  hydrateCovers,
  percentOf,
  skeletonGrid,
} from "../ui.js";

let scanTimer = null;
let covers = null;

function head(q) {
  const admin = store.me && store.me.is_admin;
  return (
    '<div class="page-head"><div>' +
    '<h1 class="page-title">' + esc(t("library.title")) + "</h1>" +
    "</div>" +
    '<div class="row" data-scan-slot>' +
    (admin
      ? '<a class="btn" href="#/admin">' + icon("scan") + esc(t("library.manageSources")) + "</a>"
      : "") +
    "</div></div>"
  );
}

function scanBadge(scanning) {
  if (!scanning || !scanning.running) return "";
  return (
    '<span class="chip" title="' + esc(sourceLabel(scanning.source_name || "")) + '">' +
    '<span class="scan-dot"></span>' + esc(t("library.scanning")) +
    "</span>"
  );
}

function continueCard(item) {
  const series = item.series;
  const progress = item.progress || {};
  const percent = percentOf(progress);
  const chapter = progress.chapter_title || "";
  return (
    '<a class="continue-card" href="#/read/' + Number(progress.chapter_id) + '">' +
    '<span class="continue-cover"><span class="fallback">' + esc(series.title) + "</span>" +
    '<img data-cover="' + esc(series.cover_url) + '" alt=""></span>' +
    '<span class="continue-body">' +
    '<span class="continue-kicker">' + esc(t("library.continue")) + "</span>" +
    '<span class="continue-title">' + esc(series.title) + "</span>" +
    '<span class="continue-chapter">' + esc(chapter) + (percent ? " · " + percent + "%" : "") + "</span>" +
    '<span class="progress-line"><span style="width:' + percent + '%"></span></span>' +
    "</span></a>"
  );
}

function seriesCard(series) {
  const percent = percentOf(series.progress);
  const badge = percent ? percent + "%" : t("card.chapters", { n: series.chapter_count });
  const author = series.author
    ? '<span class="meta-author">' + esc(series.author) + '</span><span class="sep"></span>'
    : "";
  return (
    '<a class="card" href="#/series/' + Number(series.id) + '">' +
    '<span class="cover"><span class="fallback">' + esc(series.title) + "</span>" +
    '<img data-cover="' + esc(series.cover_url) + '" alt="" loading="lazy">' +
    '<span class="badge">' + esc(badge) + "</span></span>" +
    '<div class="card-title">' + esc(series.title) + "</div>" +
    '<div class="card-meta">' + author +
    '<span class="meta-source">' + esc(sourceLabel(series.source.name)) + "</span>" +
    '<span class="sep"></span><span class="meta-chapters">' + esc(t("card.chapters", { n: series.chapter_count })) + "</span></div>" +
    (percent
      ? '<div class="card-progress progress-line"><span style="width:' + percent + '%"></span></div>'
      : "") +
    "</a>"
  );
}

function toolbar(data, q, source) {
  const chips = [
    '<a class="chip' + (!source ? " active" : "") + '" href="#/' + (q ? "?q=" + encodeURIComponent(q) : "") + '">' +
      esc(t("library.sourceAll")) + "</a>",
  ];
  for (const item of data.sources || []) {
    const target = "#/?source=" + item.id + (q ? "&q=" + encodeURIComponent(q) : "");
    chips.push(
      '<a class="chip' + (Number(source) === item.id ? " active" : "") + '" href="' + target + '">' +
      esc(sourceLabel(item.name)) + "</a>"
    );
  }
  let note = "";
  if (q) {
    note = '<span class="result-note">' + esc(data.total ? t("library.total", { n: data.total }) : t("library.noResults", { q })) + "</span>";
  } else if (data.total) {
    note = '<span class="result-note">' + esc(t("library.total", { n: data.total })) + "</span>";
  }
  return '<div class="toolbar">' + chips.join("") + '<span class="spacer"></span>' + note + "</div>";
}

function emptyState(data, q, source) {
  if (q || source) {
    return (
      '<div class="empty"><h3>' + esc(t("library.noResults", { q: q || "…" })) + "</h3>" +
      '<p><a class="btn" href="#/">' + esc(t("library.sourceAll")) + "</a></p></div>"
    );
  }
  const admin = store.me && store.me.is_admin;
  return (
    '<div class="empty"><h3>' + esc(t("library.emptyTitle")) + "</h3>" +
    "<p>" + esc(admin ? t("library.emptyDesc") : t("library.emptyReader")) + "</p>" +
    (admin
      ? '<a class="btn primary" href="#/admin">' + icon("plus") + esc(t("admin.addSource")) + "</a>"
      : "") +
    "</div>"
  );
}

function body(data, q, source) {
  const cards = data.series || [];
  let html = "";
  if (!q && !source && data.continue && data.continue.length) {
    html +=
      '<section><h2 class="section-title">' + esc(t("library.continue")) +
      "</h2><div class=\"continue-strip\">" +
      data.continue.map(continueCard).join("") +
      "</div></section>";
  }
  html +=
    '<section><h2 class="section-title"><span>' + esc(t("library.allTitle")) +
    '</span><span class="count">' + (cards.length ? esc(t("library.total", { n: cards.length })) : "") +
    "</span></h2>" +
    toolbar(data, q, source);
  if (cards.length) {
    html += '<div class="grid">' + cards.map(seriesCard).join("") + "</div>";
  } else {
    html += emptyState(data, q, source);
  }
  html += "</section>";
  return '<div class="stack">' + html + "</div>";
}

async function refresh(host, ctx, data, q, source) {
  host.innerHTML = head(q) + body(data, q, source);
  if (covers) covers.disconnect();
  covers = hydrateCovers(host);
  const slot = host.querySelector("[data-scan-slot]");
  if (slot) slot.insertAdjacentHTML("afterbegin", scanBadge(data.scanning));
  wireScanPolling(host, ctx, data);
}

function wireScanPolling(host, ctx, data) {
  if (scanTimer) {
    clearTimeout(scanTimer);
    scanTimer = null;
  }
  if (!data.scanning || !data.scanning.running) return;
  scanTimer = window.setTimeout(async () => {
    if (!ctx.isCurrent()) return;
    try {
      const health = await api.get("api/health");
      if (!ctx.isCurrent()) return;
      if (health.scanning) {
        wireScanPolling(host, ctx, { scanning: { running: true } });
        return;
      }
      const query = ctx.query;
      const q = (query.get("q") || "").trim();
      const source = Number(query.get("source") || 0);
      const fresh = await api.get("api/library", { q, source: source || undefined });
      if (ctx.isCurrent()) refresh(host, ctx, fresh, q, source);
    } catch {
      /* a failed poll simply stops until the next page load */
    }
  }, 2600);
}

export async function render(host, ctx) {
  const q = (ctx.query.get("q") || "").trim();
  const source = Number(ctx.query.get("source") || 0);
  host.innerHTML = head(q) + skeletonGrid(10);
  let data;
  try {
    data = await api.get("api/library", { q, source: source || undefined });
  } catch (err) {
    if (!ctx.isCurrent()) return {};
    host.innerHTML =
      head(q) +
      '<div class="empty"><h3>' + esc(t("error.generic")) + "</h3><p>" + esc(errorText(err)) +
      '</p><button class="btn" data-retry>' + esc(t("common.retry")) + "</button></div>";
    host.querySelector("[data-retry]").addEventListener("click", () => ctx.reload());
    return {};
  }
  if (!ctx.isCurrent()) return {};
  await refresh(host, ctx, data, q, source);
  return {
    dispose() {
      if (scanTimer) clearTimeout(scanTimer);
      scanTimer = null;
      if (covers) covers.disconnect();
      covers = null;
    },
  };
}
