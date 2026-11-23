/* Stroke icons on a 24px grid. */

const PATHS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8m-4-4v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v0a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z"/>',
  shield: '<path d="M12 3 5 6v5c0 4.4 2.9 8.3 7 9.5 4.1-1.2 7-5.1 7-9.5V6l-7-3Z"/>',
  library: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H9v16H5.5A1.5 1.5 0 0 1 4 18.5v-13ZM9 4h4v16H9zM13 4.6 17.8 6l-3 14L13 18.6z"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Z"/><path d="M4 19a2 2 0 0 1 2-2h13"/>',
  bookOpen: '<path d="M12 6.5C10.6 5.2 8.6 4.6 6 4.6c-1 0-1.6.1-2 .3v13.6c.4-.2 1-.3 2-.3 2.6 0 4.6.6 6 1.8 1.4-1.2 3.4-1.8 6-1.8 1 0 1.6.1 2 .3V4.9c-.4-.2-1-.3-2-.3-2.6 0-4.6.6-6 1.9Z"/><path d="M12 6.5v14"/>',
  arrowLeft: '<path d="M19 12H5m6-6-6 6 6 6"/>',
  arrowRight: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  chevronLeft: '<path d="m15 5-7 7 7 7"/>',
  chevronRight: '<path d="m9 5 7 7-7 7"/>',
  chevronUp: '<path d="m5 15 7-7 7 7"/>',
  chevronDown: '<path d="m5 9 7 7 7-7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13"/>',
  edit: '<path d="m4 20 4.5-1L20 7.5a2.1 2.1 0 0 0-3-3L5.5 16 4 20Z"/><path d="m14.5 6 3 3"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
  folderOpen: '<path d="M3 8a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H6.6a2 2 0 0 0-1.9 1.4L3 19V8Z"/><path d="M3 19 6 10h16l-3 9H3Z"/>',
  file: '<path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-6-6Z"/><path d="M13 3v6h6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 6.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  maximize: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  minimize: '<path d="M9 4v4a1 1 0 0 1-1 1H4m11-5v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4m11 5v-4a1 1 0 0 1 1-1h4"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3m8 0h3a1 1 0 0 1 1 1v3m0 8v3a1 1 0 0 1-1 1h-3m-8 0H5a1 1 0 0 1-1-1v-3"/><path d="M4 12h16"/>',
  database: '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13"/><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m21 16-5-5L6 20"/>',
  single: '<rect x="7" y="3" width="10" height="18" rx="1.5"/>',
  double: '<rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/>',
  split: '<path d="M12 3v18"/><rect x="3" y="4" width="18" height="16" rx="2"/>',
  vertical: '<rect x="6" y="3" width="12" height="7" rx="1.5"/><rect x="6" y="14" width="12" height="7" rx="1.5"/>',
  flip: '<path d="M12 4v16"/><path d="M9 6 4 12l5 6V6ZM15 6l5 6-5 6V6Z"/>',
  slide: '<path d="M4 12h13m-5-5 5 5-5 5"/><path d="M20 5v14"/>',
  scroll: '<path d="M12 4v13m-5-5 5 5 5-5"/><path d="M5 20h14"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.7 3.6-5.5 7-5.5s6.2 1.8 7 5.5"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  cloud: '<path d="M7 18a4.5 4.5 0 0 1-.4-9A6 6 0 0 1 18 8.5a4 4 0 0 1-.5 9H7Z"/>',
  hardDrive: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5.5 13 8 5h8l2.5 8"/><path d="M7 16.5h.01M11 16.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-9.5v.01"/>',
  external: '<path d="M14 4h6v6m0-6-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  play: '<path d="M8 5.5v13l11-6.5-11-6.5Z"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.7 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.7-3.8-9S9.5 5.5 12 3Z"/>',
  lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  alert: '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10v4m0 3v.01"/>',
  home: '<path d="m4 11 8-7 8 7"/><path d="M6 9.5V20h12V9.5"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18Z" fill="currentColor" stroke="none"/>',
  rotate: '<path d="M20 8a8 8 0 1 0 1 6"/><path d="M20 3v5h-5"/>',
};

export function icon(name, className = "") {
  const path = PATHS[name] || PATHS.info;
  return (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    (className ? ' class="' + className + '"' : "") +
    ">" +
    path +
    "</svg>"
  );
}

export function iconEl(name, className = "") {
  const span = document.createElement("span");
  span.style.display = "contents";
  span.innerHTML = icon(name, className);
  return span.firstElementChild;
}
