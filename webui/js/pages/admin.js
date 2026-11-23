import { api } from "../api.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { store } from "../store.js";
import {
  confirmDialog,
  errorText,
  esc,
  fmtSize,
  openModal,
  sourceIcon,
  timeAgo,
  toast,
} from "../ui.js";

let pollTimer = null;

const KIND_LABEL = {
  local: "form.kindLocal",
  webdav: "form.kindWebdav",
  smb: "form.kindSmb",
};

function forbidden(host, ctx) {
  host.innerHTML =
    '<div class="empty"><h3>' + esc(t("admin.forbidden")) + "</h3><p>" + esc(t("admin.forbiddenDesc")) +
    '</p><a class="btn" href="#/">' + esc(t("detail.back")) + "</a></div>";
}

function head() {
  return (
    '<div class="page-head"><div><h1 class="page-title">' + esc(t("admin.title")) + "</h1>" +
    '<p class="page-subtitle">' + esc(t("admin.subtitle")) + "</p></div>" +
    '<div class="row"><span data-scan-state></span>' +
    '<button class="btn" data-scan-all>' + icon("scan") + esc(t("admin.scanAll")) + "</button>" +
    '<button class="btn primary" data-add>' + icon("plus") + esc(t("admin.addSource")) + "</button>" +
    "</div></div>"
  );
}

function statCells(stats) {
  const cell = (value, label) =>
    '<div class="capability"><span>' + esc(label) + '</span><strong>' + esc(value) + "</strong></div>";
  return (
    '<div class="panel"><div class="row" style="margin-bottom:16px">' +
    '<h2 class="panel-title" style="margin:0">' + esc(t("admin.sources")) + "</h2>" +
    '<span class="spacer"></span>' +
    '<span class="hint">' + esc(fmtSize(stats.cache_bytes)) + " / " + esc(fmtSize(stats.cache_limit)) + "</span>" +
    '<button class="btn small" data-cache-clear>' + icon("trash") + esc(t("admin.cacheClear")) + "</button>" +
    "</div>" +
    '<div class="capability-grid">' +
    cell(stats.series, t("admin.stats.series")) +
    cell(stats.chapters, t("admin.stats.chapters")) +
    cell(stats.pages, t("admin.stats.pages")) +
    cell(fmtSize(stats.cache_bytes), t("admin.stats.cache")) +
    "</div></div>"
  );
}

function sourceStatus(source, scan) {
  const active = scan && scan.state && scan.state.running && scan.state.source_id === source.id;
  if (!source.enabled) {
    return '<span class="status-pill">' + esc(t("admin.source.disabled")) + "</span>";
  }
  if (active) {
    return '<span class="status-pill scanning">' + esc(t("admin.source.scanning")) + "</span>";
  }
  if (source.last_scan_status === "error") {
    return '<span class="status-pill error">' + esc(t("admin.source.error")) + "</span>";
  }
  if (!source.last_scan_at) {
    return '<span class="status-pill">' + esc(t("admin.source.never")) + "</span>";
  }
  return '<span class="status-pill ok">' + esc(t("admin.source.ok")) + "</span>";
}

function sourceCard(source, scan) {
  const meta = [];
  if (source.last_scan_at) meta.push(esc(t("admin.source.lastScan", { time: timeAgo(source.last_scan_at) })));
  if (source.username) meta.push(esc(source.username));
  if (source.has_password) meta.push(esc(t("form.password")));
  const active = scan && scan.state && scan.state.running && scan.state.source_id === source.id;
  return (
    '<div class="source-card" data-source="' + Number(source.id) + '">' +
    "<div><div class=\"source-name\">" + icon(sourceIcon(source.kind), "") +
    esc(source.name) + '<span class="source-kind">' + esc(source.kind.toUpperCase()) + "</span></div>" +
    '<div class="source-path mono">' + esc(source.root) + "</div>" +
    '<div class="source-status">' + sourceStatus(source, scan) +
    meta.map((item) => "<span>" + item + "</span>").join("") + "</div>" +
    (source.last_scan_error
      ? '<div class="hint" style="margin-top:6px;color:var(--danger)">' + esc(source.last_scan_error) + "</div>"
      : "") +
    "</div>" +
    '<div class="source-actions">' +
    '<button class="btn small" data-act="scan"' + (active || !source.enabled ? " disabled" : "") + ">" +
    icon("refresh") + esc(t("admin.scan")) + "</button>" +
    '<button class="btn small" data-act="edit">' + icon("edit") + esc(t("admin.edit")) + "</button>" +
    '<button class="btn small danger" data-act="delete">' + icon("trash") + esc(t("admin.delete")) + "</button>" +
    "</div></div>"
  );
}

function sourcesPanel(sources, scan) {
  if (!sources.length) {
    return (
      '<div class="empty"><h3>' + esc(t("admin.noSources")) + "</h3><p>" + esc(t("admin.noSourcesDesc")) +
      '</p><button class="btn primary" data-add>' + icon("plus") + esc(t("admin.addSource")) + "</button></div>"
    );
  }
  return '<div class="source-list">' + sources.map((item) => sourceCard(item, scan)).join("") + "</div>";
}

function scanChip(scan) {
  if (!scan || !scan.state || !scan.state.running) return "";
  const state = scan.state;
  return (
    '<span class="chip"><span class="scan-dot"></span>' +
    esc(state.source_name || t("admin.source.scanning")) +
    (state.chapters ? " · " + esc(t("admin.stats.chapters")) + " " + state.chapters : "") +
    "</span>"
  );
}

/* --------------------------------------------------------------- source form */

function rootHint(kind) {
  if (kind === "webdav") return t("form.rootWebdavHint");
  if (kind === "smb") return t("form.rootSmbHint");
  return t("form.rootLocalHint");
}

function rootLabel(kind) {
  if (kind === "webdav") return t("form.rootWebdav");
  if (kind === "smb") return t("form.rootSmb");
  return t("form.rootLocal");
}

function openSourceForm(source, onDone) {
  const editing = Boolean(source);
  const kind = source ? source.kind : "local";
  const body = document.createElement("div");
  body.innerHTML =
    '<form class="form-grid" novalidate>' +
    '<div class="field"><label>' + esc(t("form.name")) + "</label>" +
    '<input class="input" name="name" maxlength="80" placeholder="' + esc(t("form.namePlaceholder")) + '" value="' +
    esc(source ? source.name : "") + '"></div>' +
    '<div class="field"><label>' + esc(t("form.kind")) + "</label>" +
    '<select class="select" name="kind">' +
    Object.entries(KIND_LABEL)
      .map(
        ([value, key]) =>
          '<option value="' + value + '"' + (kind === value ? " selected" : "") + ">" + esc(t(key)) + "</option>"
      )
      .join("") +
    "</select></div>" +
    '<div class="field wide"><label data-root-label>' + esc(rootLabel(kind)) + "</label>" +
    '<div class="row" style="flex-wrap:nowrap"><input class="input" name="root" spellcheck="false" value="' +
    esc(source ? source.root : "") + '"><button type="button" class="btn" data-browse' +
    (kind === "local" ? "" : " hidden") + ">" + icon("folder") + esc(t("form.browse")) + "</button></div>" +
    '<span class="hint" data-root-hint>' + esc(rootHint(kind)) + "</span></div>" +
    '<div class="field wide" data-remote' + (kind === "local" ? " hidden" : "") + "><label>" +
    esc(t("form.username")) + '</label><input class="input" name="username" autocomplete="off" spellcheck="false" value="' +
    esc(source ? source.username : "") + '"></div>' +
    '<div class="field wide" data-remote' + (kind === "local" ? " hidden" : "") + "><label>" +
    esc(t("form.password")) + '</label><input class="input" name="password" type="password" autocomplete="new-password"' +
    ' placeholder="' + esc(source && source.has_password ? t("form.passwordKeep") : "") + '">' +
    '<span class="hint">' + esc(t("form.passwordHint")) + "</span></div>" +
    '<div class="field wide"><label class="row" style="gap:9px;text-transform:none;letter-spacing:0;font-size:13px;color:var(--ink);font-weight:500">' +
    '<input type="checkbox" name="enabled"' + (!source || source.enabled ? " checked" : "") + ">" +
    esc(t("form.enabled")) + "</label></div>" +
    '<div class="form-actions wide"><button type="button" class="btn" data-close>' + esc(t("form.cancel")) +
    '</button><button type="submit" class="btn primary" data-submit>' +
    esc(editing ? t("form.save") : t("form.addTitle")) + "</button></div></form>";

  const modal = openModal({
    title: editing ? t("form.editTitle") : t("form.addTitle"),
    subtitle: t("form.addSub"),
    body,
  });

  const form = body.querySelector("form");
  const kindSelect = form.querySelector('[name="kind"]');
  const rootLabelEl = form.querySelector("[data-root-label]");
  const rootHintEl = form.querySelector("[data-root-hint]");
  const browseButton = form.querySelector("[data-browse]");
  const remotes = form.querySelectorAll("[data-remote]");

  function syncKind() {
    const value = kindSelect.value;
    rootLabelEl.textContent = rootLabel(value);
    rootHintEl.textContent = rootHint(value);
    browseButton.hidden = value !== "local";
    remotes.forEach((element) => {
      element.hidden = value === "local";
    });
  }
  kindSelect.addEventListener("change", syncKind);

  browseButton.addEventListener("click", () => {
    const field = form.querySelector('[name="root"]');
    openBrowser(field.value.trim(), (path) => {
      field.value = path;
    });
  });

  form.querySelector("[data-close]").addEventListener("click", () => modal.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("[data-submit]");
    const payload = {
      name: form.querySelector('[name="name"]').value.trim(),
      kind: kindSelect.value,
      root: form.querySelector('[name="root"]').value.trim(),
      username: form.querySelector('[name="username"]').value.trim(),
      enabled: form.querySelector('[name="enabled"]').checked,
    };
    const password = form.querySelector('[name="password"]').value;
    if (!payload.root) {
      toast(t("error.generic"), "error");
      form.querySelector('[name="root"]').focus();
      return;
    }
    if (!editing || password) payload.password = password;
    submit.disabled = true;
    submit.textContent = t("form.saving");
    try {
      if (editing) await api.patch("api/admin/sources/" + source.id, payload);
      else await api.post("api/admin/sources", payload);
      modal.close();
      toast(t("toast.saved"));
      onDone();
    } catch (err) {
      toast(errorText(err), "error");
      submit.disabled = false;
      submit.textContent = editing ? t("form.save") : t("form.addTitle");
    }
  });
}

/* ------------------------------------------------------------------ browser */

function openBrowser(startPath, onPick) {
  const body = document.createElement("div");
  body.innerHTML =
    '<div class="browser"><div class="browser-head"><button class="icon-btn" data-up title="' + esc(t("browse.up")) +
    '" style="width:30px;height:30px">' + icon("chevronUp") + '</button><span class="browser-path mono" data-path></span></div>' +
    '<div class="browser-list" data-list></div></div>' +
    '<div class="form-actions"><button class="btn" data-close>' + esc(t("browse.cancel")) + "</button>" +
    '<button class="btn primary" data-select disabled>' + esc(t("browse.select")) + "</button></div>";

  let current = { path: "", parent: "" };
  const modal = openModal({
    title: t("browse.title"),
    body,
    className: "browser-modal",
  });
  const list = body.querySelector("[data-list]");
  const pathLabel = body.querySelector("[data-path]");
  const up = body.querySelector("[data-up]");
  const select = body.querySelector("[data-select]");

  async function navigate(path) {
    list.innerHTML = '<div style="padding:20px;color:var(--muted);font-size:13px">' + esc(t("browse.loading")) + "</div>";
    try {
      const data = await api.get("api/admin/browse", { path });
      current = data;
      pathLabel.textContent = data.path || "/";
      up.disabled = !data.parent;
      select.disabled = !data.path;
      if (!data.entries.length) {
        list.innerHTML = '<div style="padding:20px;color:var(--muted);font-size:13px">' + esc(t("browse.empty")) + "</div>";
      } else {
        list.innerHTML = data.entries
          .map(
            (entry) =>
              '<button type="button" class="browser-item" data-path="' + esc(entry.path) + '">' +
              icon("folder") + "<span>" + esc(entry.name) + "</span></button>"
          )
          .join("");
        list.querySelectorAll("[data-path]").forEach((button) => {
          button.addEventListener("click", () => navigate(button.dataset.path));
        });
      }
    } catch (err) {
      toast(errorText(err), "error");
      list.innerHTML = '<div style="padding:20px;color:var(--danger);font-size:13px">' + esc(errorText(err)) + "</div>";
    }
  }

  up.addEventListener("click", () => {
    if (current.parent) navigate(current.parent);
    else navigate("");
  });
  body.querySelector("[data-close]").addEventListener("click", () => modal.close());
  select.addEventListener("click", () => {
    if (!current.path) return;
    onPick(current.path);
    modal.close();
  });
  navigate(startPath || "");
}

/* -------------------------------------------------------------------- page */

function renderContent(host, ctx, sources, stats, scan) {
  host.innerHTML =
    head() + '<div class="stack">' + statCells(stats) +
    '<section><h2 class="section-title">' + esc(t("admin.sources")) +
    '<span class="count">' + esc(String(sources.length)) + "</span></h2>" +
    sourcesPanel(sources, scan) + "</section></div>";

  const stateChip = host.querySelector("[data-scan-state]");
  if (stateChip) stateChip.innerHTML = scanChip(scan);

  host.querySelectorAll("[data-add]").forEach((button) => {
    button.addEventListener("click", () => openSourceForm(null, () => reload(host, ctx)));
  });

  const scanAll = host.querySelector("[data-scan-all]");
  if (scanAll) {
    scanAll.disabled = Boolean(scan && scan.state && scan.state.running);
    scanAll.addEventListener("click", async () => {
      try {
        await api.post("api/admin/scan");
        toast(t("toast.scanStarted"));
        reload(host, ctx);
      } catch (err) {
        toast(errorText(err), "error");
      }
    });
  }

  const clear = host.querySelector("[data-cache-clear]");
  if (clear) {
    clear.addEventListener("click", async () => {
      try {
        await api.post("api/admin/cache/clear");
        toast(t("toast.cacheCleared"));
        reload(host, ctx);
      } catch (err) {
        toast(errorText(err), "error");
      }
    });
  }

  host.querySelectorAll("[data-source]").forEach((card) => {
    const id = Number(card.dataset.source);
    const source = sources.find((item) => item.id === id);
    card.querySelector('[data-act="scan"]').addEventListener("click", async () => {
      try {
        await api.post("api/admin/sources/" + id + "/scan");
        toast(t("toast.scanStarted"));
        reload(host, ctx);
      } catch (err) {
        toast(errorText(err), "error");
      }
    });
    card.querySelector('[data-act="edit"]').addEventListener("click", () => {
      openSourceForm(source, () => reload(host, ctx));
    });
    card.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      const yes = await confirmDialog({
        title: t("form.deleteTitle"),
        message: t("form.deleteDesc", { name: source.name }),
        confirmLabel: t("common.delete"),
      });
      if (!yes) return;
      try {
        await api.del("api/admin/sources/" + id);
        toast(t("toast.deleted"));
        reload(host, ctx);
      } catch (err) {
        toast(errorText(err), "error");
      }
    });
  });

  schedulePoll(host, ctx, scan);
}

function schedulePoll(host, ctx, scan) {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
  const running = scan && scan.state && scan.state.running;
  if (!running) return;
  pollTimer = window.setTimeout(async () => {
    if (!ctx.isCurrent()) return;
    try {
      const fresh = await api.get("api/admin/scan");
      if (!ctx.isCurrent()) return;
      const chip = host.querySelector("[data-scan-state]");
      if (chip) chip.innerHTML = scanChip(fresh);
      if (fresh.state.running) {
        schedulePoll(host, ctx, fresh);
      } else {
        reload(host, ctx);
      }
    } catch {
      /* stop polling; the next action reloads */
    }
  }, 2200);
}

async function load(host, ctx) {
  const [sources, stats, scan] = await Promise.all([
    api.get("api/admin/sources"),
    api.get("api/admin/stats"),
    api.get("api/admin/scan"),
  ]);
  return { sources, stats, scan };
}

async function reload(host, ctx) {
  const scroll = window.scrollY;
  try {
    const data = await load(host, ctx);
    if (!ctx.isCurrent()) return;
    renderContent(host, ctx, data.sources, data.stats, data.scan);
    window.scrollTo(0, scroll);
  } catch (err) {
    if (!ctx.isCurrent()) return;
    toast(errorText(err), "error");
  }
}

export async function render(host, ctx) {
  if (!store.me || !store.me.is_admin) {
    forbidden(host, ctx);
    return {};
  }
  host.innerHTML = head() +
    '<div class="panel"><div class="skeleton" style="height:18px;width:110px;margin-bottom:16px"></div>' +
    '<div class="capability-grid">' +
    '<div class="capability skeleton" style="height:46px"></div><div class="capability skeleton" style="height:46px"></div>' +
    '<div class="capability skeleton" style="height:46px"></div><div class="capability skeleton" style="height:46px"></div>' +
    "</div></div>";
  let data;
  try {
    data = await load(host, ctx);
  } catch (err) {
    if (!ctx.isCurrent()) return {};
    host.innerHTML = head() + '<div class="empty"><h3>' + esc(t("error.generic")) + "</h3><p>" +
      esc(errorText(err)) + '</p><button class="btn" data-retry>' + esc(t("common.retry")) + "</button></div>";
    host.querySelector("[data-retry]").addEventListener("click", () => ctx.reload());
    const add = host.querySelector("[data-add]");
    if (add) add.addEventListener("click", () => openSourceForm(null, () => reload(host, ctx)));
    return {};
  }
  if (!ctx.isCurrent()) return {};
  renderContent(host, ctx, data.sources, data.stats, data.scan);

  return {
    dispose() {
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = null;
    },
  };
}
