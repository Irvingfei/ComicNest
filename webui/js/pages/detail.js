import { api } from "../api.js";
import { icon } from "../icons.js";
import { sourceLabel, t } from "../i18n.js";
import {
  chapterState,
  errorText,
  esc,
  hydrateCovers,
  pad,
  percentOf,
  skeletonGrid,
} from "../ui.js";

let covers = null;

function metaItem(label, value) {
  if (!value) return "";
  return "<span>" + esc(label) + " <strong style=\"color:var(--ink);font-weight:550\">" + esc(value) + "</strong></span>";
}

function progressPanel(series) {
  const progress = series.progress;
  if (!progress) return "";
  const percent = percentOf(progress);
  const total = progress.total_pages || 0;
  return (
    '<div class="detail-progress">' +
    '<div class="meta"><span>' + esc(t("detail.progressTitle")) + "</span><span>" +
    esc(progress.chapter_title || "") + "</span></div>" +
    '<div class="progress-line"><span style="width:' + percent + '%"></span></div>' +
    '<div class="meta" style="margin-top:7px"><span>' +
    esc(total ? t("detail.progressText", { page: Number(progress.page) + 1, total }) : percent + "%") +
    "</span><span>" + percent + "%</span></div>" +
    "</div>"
  );
}

function chapterRow(chapter, index) {
  const state = chapterState(chapter);
  const percent = percentOf(chapter.progress);
  const label = chapter.number !== null && chapter.number !== undefined
    ? String(chapter.number)
    : pad(index + 1);
  const total = Number(chapter.progress && chapter.progress.total_pages) || Number(chapter.page_count) || 0;
  const pages = total ? t("chapter.pages", { n: total }) : "";
  const format = (chapter.format || "").replace(/^\./, "").toUpperCase();
  const readText =
    state === "read" ? t("chapter.read") : state === "reading" ? percent + "%" : "";
  return (
    '<a class="chapter-row" href="#/read/' + Number(chapter.id) + '">' +
    '<span class="chapter-index">' + esc(label) + "</span>" +
    '<span class="chapter-name"><strong>' + esc(chapter.title || t("common.untitled")) + "</strong>" +
    '<span class="chapter-sub"><span>' + esc(pages) + "</span>" +
    (format ? '<span class="sep" style="width:3px;height:3px;border-radius:50%;background:currentColor;opacity:.5"></span><span>' + esc(format) + "</span>" : "") +
    "</span></span>" +
    '<span class="chapter-right">' +
    (state === "reading" ? '<span class="chapter-progress"><span style="width:' + percent + '%"></span></span>' : "") +
    (readText ? '<span class="chapter-read">' + esc(readText) + "</span>" : "") +
    '<span class="arrow">' + icon("chevronRight") + "</span>" +
    "</span></a>"
  );
}

function renderSeries(series) {
  const chapters = series.chapters || [];
  const target = series.continue_chapter_id || (chapters[0] && chapters[0].id);
  const hasProgress = Boolean(series.progress);
  const author = series.author ? metaItem(t("detail.author"), series.author) : "";
  const year = series.year ? metaItem(t("detail.year"), series.year) : "";
  const source = series.source ? metaItem(t("detail.source"), sourceLabel(series.source.name)) : "";
  const count = metaItem(t("detail.chapters"), series.chapter_count);
  return (
    '<div class="row" style="margin-bottom:22px"><a class="btn ghost" href="#/">' +
    icon("arrowLeft") + esc(t("detail.back")) + "</a></div>" +
    '<div class="detail-hero">' +
    '<div class="detail-cover"><span class="fallback">' + esc(series.title) + "</span>" +
    '<img data-cover="' + esc(series.cover_url) + '" alt=""></div>' +
    '<div class="detail-info">' +
    '<div class="detail-kicker">' + esc(series.source ? sourceLabel(series.source.name) : "") + "</div>" +
    '<h1 class="detail-title">' + esc(series.title) + "</h1>" +
    '<div class="detail-meta">' + author + year + count + source + "</div>" +
    (series.description ? '<p class="detail-desc">' + esc(series.description) + "</p>" : "") +
    '<div class="detail-actions">' +
    (target
      ? '<a class="btn primary" href="#/read/' + Number(target) + '">' + icon("play") +
        esc(hasProgress ? t("detail.read") : t("detail.start")) + "</a>"
      : "") +
    (hasProgress && chapters[0]
      ? '<a class="btn" href="#/read/' + Number(chapters[0].id) + '">' + esc(t("detail.first")) + "</a>"
      : "") +
    "</div>" + progressPanel(series) +
    "</div></div>" +
    '<h2 class="section-title"><span>' + esc(t("detail.chapters")) +
    '</span><span class="count">' + (chapters.length ? esc(t("detail.chapterCount", { n: chapters.length })) : "") +
    "</span></h2>" +
    (chapters.length
      ? '<div class="chapter-list">' + chapters.map(chapterRow).join("") + "</div>"
      : '<div class="empty"><h3>' + esc(t("detail.noChapters")) + "</h3></div>")
  );
}

export async function render(host, ctx) {
  const id = Number(ctx.params[0] || 0);
  host.innerHTML =
    '<div class="row" style="margin-bottom:22px"><a class="btn ghost" href="#/">' +
    icon("arrowLeft") + esc(t("detail.back")) + "</a></div>" +
    '<div class="detail-hero"><div class="detail-cover skeleton"></div>' +
    '<div class="detail-info"><div class="skeleton" style="height:14px;width:120px;margin-bottom:16px"></div>' +
    '<div class="skeleton" style="height:48px;width:70%;margin-bottom:18px"></div>' +
    '<div class="skeleton" style="height:14px;width:50%"></div></div></div>' +
    skeletonGrid(4).replace('class="grid"', 'class="grid" style="display:none"');
  let series;
  try {
    series = await api.get("api/series/" + id);
  } catch (err) {
    if (!ctx.isCurrent()) return {};
    host.innerHTML =
      '<div class="row" style="margin-bottom:22px"><a class="btn ghost" href="#/">' +
      icon("arrowLeft") + esc(t("detail.back")) + "</a></div>" +
      '<div class="empty"><h3>' + esc(t("error.notFound")) + "</h3><p>" + esc(errorText(err)) +
      '</p><button class="btn" data-retry>' + esc(t("common.retry")) + "</button></div>";
    host.querySelector("[data-retry]").addEventListener("click", () => ctx.reload());
    return {};
  }
  if (!ctx.isCurrent()) return {};
  host.innerHTML = renderSeries(series);
  document.title = series.title + " · ComicNest";
  covers = hydrateCovers(host);
  return {
    dispose() {
      if (covers) covers.disconnect();
      covers = null;
    },
  };
}
