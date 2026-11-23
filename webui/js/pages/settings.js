import { LANGUAGES, t } from "../i18n.js";
import { store } from "../store.js";
import {
  confirmDialog,
  esc,
  segmented,
  toast,
  wireSegmented,
} from "../ui.js";

function themeSection(settings) {
  return (
    '<div class="panel"><h2 class="panel-title">' + esc(t("settings.appearance")) + "</h2>" +
    '<p class="panel-sub">' + esc(t("settings.appearanceDesc")) + "</p>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.theme")) + "</strong></div>" +
    '<div class="setting-control">' +
    segmented(
      [
        { value: "auto", label: t("settings.themeAuto") },
        { value: "light", label: t("settings.themeLight") },
        { value: "dark", label: t("settings.themeDark") },
      ],
      settings.theme,
      "theme"
    ) +
    "</div></div>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.language")) +
    "</strong><span>" + esc(t("settings.languageDesc")) + "</span></div>" +
    '<div class="setting-control"><select class="select" data-language style="min-width:170px">' +
    '<option value="auto"' + (settings.language === "auto" ? " selected" : "") + ">" + esc(t("settings.languageAuto")) + "</option>" +
    LANGUAGES.map(
      (item) =>
        '<option value="' + item.code + '"' + (settings.language === item.code ? " selected" : "") + ">" +
        esc(item.label) + "</option>"
    ).join("") +
    "</select></div></div></div>"
  );
}

function readingSection(settings) {
  return (
    '<div class="panel"><h2 class="panel-title">' + esc(t("settings.reading")) + "</h2>" +
    '<p class="panel-sub">' + esc(t("settings.readingDesc")) + "</p>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.mode")) + "</strong></div>" +
    '<div class="setting-control">' +
    segmented(
      [
        { value: "single", label: t("reader.single") },
        { value: "double", label: t("reader.double") },
        { value: "split", label: t("reader.split") },
      ],
      settings.mode,
      "mode"
    ) + "</div></div>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.direction")) + "</strong></div>" +
    '<div class="setting-control">' +
    segmented(
      [
        { value: "rtl", label: t("reader.rtl") },
        { value: "ltr", label: t("reader.ltr") },
        { value: "vertical", label: t("reader.vertical") },
      ],
      settings.direction,
      "direction"
    ) + "</div></div>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.animation")) + "</strong></div>" +
    '<div class="setting-control">' +
    segmented(
      [
        { value: "slide", label: t("reader.slide") },
        { value: "scroll", label: t("reader.scroll") },
        { value: "flip", label: t("reader.flip") },
      ],
      settings.animation,
      "animation"
    ) + "</div></div>" +
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(t("settings.brightness")) + "</strong></div>" +
    '<div class="setting-control"><input type="range" min="30" max="100" step="1" value="' + settings.brightness +
    '" data-brightness style="width:180px;accent-color:var(--accent)"><span class="mono" data-brightness-value>' +
    esc(t("settings.brightnessValue", { n: settings.brightness })) + "</span></div></div></div>"
  );
}

function accountSection() {
  const me = store.me || {};
  const version = (store.options && store.options.version) || "";
  const row = (label, value) =>
    '<div class="setting-row"><div class="setting-copy"><strong>' + esc(label) +
    "</strong></div><div class=\"setting-control hint\">" + esc(value) + "</div></div>";
  return (
    '<div class="panel"><h2 class="panel-title">' + esc(t("settings.account")) + "</h2>" +
    row(t("settings.user"), me.user || "—") +
    row(t("settings.role"), me.is_admin ? t("common.admin") : t("common.user")) +
    row(t("settings.version"), version || "—") +
    "</div>" +
    '<div class="panel"><h2 class="panel-title">' + esc(t("settings.about")) + "</h2>" +
    '<p class="panel-sub" style="margin-bottom:0">' + esc(t("settings.aboutDesc")) + "</p>" +
    '<div class="row" style="margin-top:20px"><button class="btn danger" data-reset>' +
    esc(t("settings.reset")) + "</button></div></div>"
  );
}

export async function render(host, ctx) {
  const settings = store.settings;
  host.innerHTML =
    '<div class="page-head"><div><h1 class="page-title">' + esc(t("settings.title")) + "</h1>" +
    '<p class="page-subtitle">' + esc(t("settings.subtitle")) + "</p></div></div>" +
    '<div class="stack">' + themeSection(settings) + readingSection(settings) + accountSection() + "</div>";

  wireSegmented(host, "theme", (value) => {
    store.update({ theme: value });
    document.dispatchEvent(new CustomEvent("comicnest:theme"));
  });
  wireSegmented(host, "mode", (value) => store.update({ mode: value }));
  wireSegmented(host, "direction", (value) => store.update({ direction: value }));
  wireSegmented(host, "animation", (value) => store.update({ animation: value }));

  const language = host.querySelector("[data-language]");
  if (language) {
    language.addEventListener("change", () => {
      store.update({ language: language.value });
      ctx.refresh();
    });
  }

  const brightness = host.querySelector("[data-brightness]");
  const brightnessValue = host.querySelector("[data-brightness-value]");
  if (brightness) {
    brightness.addEventListener("input", () => {
      const value = Number(brightness.value);
      brightnessValue.textContent = t("settings.brightnessValue", { n: value });
      store.update({ brightness: value });
    });
  }

  const reset = host.querySelector("[data-reset]");
  if (reset) {
    reset.addEventListener("click", async () => {
      const yes = await confirmDialog({
        title: t("settings.reset"),
        message: t("settings.readingDesc"),
        confirmLabel: t("settings.reset"),
        danger: false,
      });
      if (!yes) return;
      store.reset();
      document.dispatchEvent(new CustomEvent("comicnest:theme"));
      toast(t("toast.saved"));
      ctx.refresh();
    });
  }
  return {};
}
