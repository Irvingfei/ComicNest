/* HTTP client for the ComicNest JSON API.

The UI usually runs inside the TOS proxy iframe. The platform forwards the
session and CSRF cookies but not the user cookie, so the user name is echoed
from the cookie the page can read into a header of its own. Every JSON call and
every image is fetched with those headers; a plain <img src> would not carry
them and would be refused.
*/

function readCookie(name) {
  const prefix = name + "=";
  for (const part of (document.cookie || "").split(";")) {
    const chunk = part.trim();
    if (chunk.startsWith(prefix)) {
      try {
        return decodeURIComponent(chunk.slice(prefix.length));
      } catch {
        return chunk.slice(prefix.length);
      }
    }
  }
  return "";
}

function appBase() {
  const path = window.location.pathname || "/";
  const proxy = path.match(/^\/v2\/proxy\/([^/]+)/);
  if (proxy) return proxy[0] + "/";
  // Under TOS the page is served from /<appid>/ but the platform only proxies
  // API traffic through /v2/proxy/<appid>/. It is always shown in a TOS dialog
  // frame; the identity cookie is usually readable but not guaranteed, so the
  // frame itself is the reliable signal.
  if (window.self !== window.top) {
    return "/v2/proxy/comicnest/";
  }
  // A top-level document may still be under the platform on a future release.
  if (/(^|;\s*)tos_current_username=/.test(document.cookie || "")) {
    return "/v2/proxy/comicnest/";
  }
  if (path === "/" || path === "") return "/";
  const trimmed = path.replace(/\/index\.html?$/i, "");
  if (/\.[a-z0-9]+$/i.test(trimmed)) {
    return trimmed.slice(0, trimmed.lastIndexOf("/") + 1);
  }
  return trimmed.endsWith("/") ? trimmed : trimmed + "/";
}

const BASE = appBase();

export class ApiError extends Error {
  constructor(message, { code = 0, status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export function apiUrl(path) {
  return new URL(String(path).replace(/^\/+/, ""), window.location.origin + BASE).href;
}

export function authHeaders(extra) {
  const headers = Object.assign(
    {
      Accept: "application/json",
      "X-ComicNest-User": readCookie("tos_current_username"),
    },
    extra || {}
  );
  const token = readCookie("X-Csrf-Token");
  if (token) headers["X-Csrf-Token"] = token;
  return headers;
}

async function parseError(response) {
  let code = 0;
  let message = "";
  try {
    const payload = await response.json();
    code = Number(payload.code) || 0;
    message = payload.message || "";
  } catch {
    message = response.statusText || "";
  }
  return new ApiError(message || "HTTP " + response.status, {
    code,
    status: response.status,
  });
}

async function request(method, path, { query, body, signal } = {}) {
  const url = new URL(apiUrl(path));
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const headers = authHeaders(body !== undefined ? { "Content-Type": "application/json" } : {});
  let response;
  try {
    response = await fetch(url.href, {
      method,
      headers,
      credentials: "same-origin",
      signal,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError("network", { code: -1, status: 0 });
  }
  if (!response.ok) throw await parseError(response);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("invalid response", { code: -2, status: response.status });
  }
  if (payload.code !== 0) {
    throw new ApiError(payload.message || "request failed", {
      code: payload.code,
      status: response.status,
    });
  }
  return payload.data;
}

export const api = {
  get: (path, query, options) => request("GET", path, { query, ...options }),
  post: (path, body, options) => request("POST", path, { body: body === undefined ? {} : body, ...options }),
  put: (path, body, options) => request("PUT", path, { body: body === undefined ? {} : body, ...options }),
  patch: (path, body, options) => request("PATCH", path, { body: body === undefined ? {} : body, ...options }),
  del: (path, options) => request("DELETE", path, options),
};

/* --------------------------------------------------------------- binaries */

const blobCache = new Map();
const BLOB_LIMIT = 96;

let currentUser = "tester";

export function setApiUser(name) {
  currentUser = name || "tester";
}

export async function fetchBlob(path) {
  const href = /^https?:/i.test(path) ? path : apiUrl(path);
  let response;
  try {
    response = await fetch(href, {
      headers: authHeaders(),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("network", { code: -1, status: 0 });
  }
  if (!response.ok) throw await parseError(response);
  return response.blob();
}

export async function blobUrl(path) {
  const href = /^https?:/i.test(path) ? path : apiUrl(path);
  const cached = blobCache.get(href);
  if (cached) {
    blobCache.delete(href);
    blobCache.set(href, cached);
    return cached;
  }
  const blob = await fetchBlob(href);
  const url = URL.createObjectURL(blob);
  blobCache.set(href, url);
  while (blobCache.size > BLOB_LIMIT) {
    const oldest = blobCache.keys().next().value;
    const value = blobCache.get(oldest);
    blobCache.delete(oldest);
    try {
      URL.revokeObjectURL(value);
    } catch {
      /* already gone */
    }
  }
  return url;
}

export function peekBlobUrl(path) {
  const href = /^https?:/i.test(path) ? path : apiUrl(path);
  return blobCache.get(href) || "";
}

export function currentUserHint() {
  return currentUser;
}
