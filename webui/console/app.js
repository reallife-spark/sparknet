const state = {
  surface: null,
  points: [],
  yaw: 0.6,
  pitch: -0.35,
  zoom: 1,
  hover: null,
  dragging: false,
  lastX: 0,
  lastY: 0,
  auto: true,
  collection: null,
};

const ZOOM_MIN = 0.35;
const ZOOM_MAX = 4;
const ZOOM_STEP = 1.12;

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) { node.replaceChildren(); }
function fmt(value) { return value === null || value === undefined ? "—" : String(value); }
function pct(value) { return typeof value === "number" ? `${Math.round(value * 100)}%` : "—"; }

function showError(message) {
  $("error").textContent = message || "";
  if (message) setTimeout(() => { if ($("error").textContent === message) $("error").textContent = ""; }, 7000);
}

async function api(path) {
  const headers = { Accept: "application/json" };
  const token = localStorage.getItem("token");
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { headers });
  if (response.status === 401) throw new Error("Open this page from Open WebUI while signed in, or configure the console token.");
  const data = await response.json().catch(() => ({}));
  if (!response.ok && !data.error) throw new Error(`HTTP ${response.status}`);
  return data;
}

function metric(label, value) {
  return el("div", { class: "metric" }, [
    el("span", { class: "k", text: label }),
    el("span", { class: "v", text: fmt(value) }),
  ]);
}

function initTabs() {
  const items = Array.isArray(state.surface.menu_items)
    ? state.surface.menu_items
    : (state.surface.menus || []).map((id) => ({ id, label: id, href: `#${id}` }));
  const menus = new Set(items.map((item) => item.id));
  const nav = $("tabs");
  clear(nav);
  for (const item of items) {
    nav.append(el("a", { href: item.href || `#${item.id}`, "data-tab": item.id, text: item.label || item.id }));
  }
  const route = () => {
    const tab = (location.hash || "#mesh").slice(1);
    const allowed = menus.has(tab) ? tab : "mesh";
    for (const section of document.querySelectorAll("main > .panel")) section.hidden = section.id !== allowed;
    for (const link of document.querySelectorAll("#tabs a")) link.classList.toggle("active", link.dataset.tab === allowed);
    if (allowed === "mesh") loadMesh();
    if (allowed === "vectors") loadVectors();
    if (allowed === "memory") loadMemory();
    if (allowed === "projects") loadProjects();
    if (allowed === "learning") loadLearning();
    if (allowed === "understand") loadUnderstand();
    if (allowed === "issues") loadIssues();
    if (allowed === "evals") loadEvals();
  };
  addEventListener("hashchange", route);
  route();
}

async function loadMesh() {
  try {
    const data = await api("api/mesh");
    $("mesh-node").textContent = `${data.node || ""} · ${data.role || ""}`;
    const cards = $("mesh-cards");
    clear(cards);
    cards.append(
      metric("Registry nodes", data.registry?.count ?? 0),
      metric("Ledger blocks", data.ledger?.blocks ?? "—"),
      metric("Shares", data.shares?.keys?.length ?? 0),
      metric("RFI files", data.rfi?.count ?? 0),
      metric("Admin events", data.admin_events?.length ?? 0),
    );
    const registry = $("registry-table");
    clear(registry);
    const nodes = data.registry?.nodes || [];
    if (!nodes.length) {
      registry.append(el("p", { class: "empty", text: "No registry entries visible. A fresh peer starts fail-closed." }));
    } else {
      const table = el("table");
      table.append(el("thead", {}, [el("tr", {}, ["Node", "Role", "Overlay", "Caps", "Dept", "Revoked"].map((h) => el("th", { text: h })))]));
      const body = el("tbody");
      for (const node of nodes) {
        body.append(el("tr", {}, [
          el("td", { text: fmt(node.node_id) }),
          el("td", { text: fmt(node.role) }),
          el("td", { text: fmt(node.overlay_ipv4) }),
          el("td", { text: (node.capabilities || []).join(", ") || "—" }),
          el("td", { text: fmt(node.department) }),
          el("td", { text: node.revoked ? "yes" : "no" }),
        ]));
      }
      table.append(body);
      registry.append(table);
    }
    const evidence = $("evidence-list");
    clear(evidence);
    const events = [...(data.telemetry || []).slice(-3), ...(data.admin_events || []).slice(-4)];
    if (!events.length) evidence.append(el("p", { class: "empty", text: "No recent telemetry or admin events." }));
    for (const event of events) {
      const line = event && typeof event === "object" ? JSON.stringify(event) : String(event);
      evidence.append(el("div", { class: "row" }, [el("span", { text: line.slice(0, 240) })]));
    }
    for (const error of data.errors || []) showError(error);
  } catch (error) { showError(error.message); }
}

async function loadProjects() {
  try {
    const data = await api("api/projects");
    $("projects-count").textContent = `${(data.projects || []).length} project(s)`;
    const cards = $("project-cards");
    clear(cards);
    cards.append(
      metric("Projects", (data.projects || []).length),
      metric("Active", (data.projects || []).filter((p) => p.status === "active").length),
      metric("Recent runs", (data.runs || []).length),
      metric("Vault", "06_Projects"),
    );
    const list = $("project-list");
    clear(list);
    if (!(data.projects || []).length) {
      list.append(el("p", { class: "empty", text: "No projects yet. Use make project-new." }));
    }
    for (const project of data.projects || []) {
      list.append(el("div", { class: "row" }, [
        el("div", {}, [
          el("strong", { text: project.title }),
          el("div", { class: "muted", text: `${project.project_id} · ${project.status}` }),
        ]),
        el("span", { class: "tag", text: project.path }),
      ]));
    }
    const runs = $("delegate-runs");
    clear(runs);
    if (!(data.runs || []).length) {
      runs.append(el("p", { class: "empty", text: "No delegate runs recorded." }));
    }
    for (const run of data.runs || []) {
      runs.append(el("div", { class: "row" }, [
        el("div", {}, [
          el("strong", { text: run.run_id }),
          el("div", { class: "muted", text: `${run.status} · ${run.harness} · ${(run.task || {}).description || ""}` }),
        ]),
      ]));
    }
    for (const error of data.errors || []) showError(error);
  } catch (error) { showError(error.message); }
}

async function loadMemory() {
  try {
    const data = await api("api/memory");
    const status = data.status || {};
    $("memory-vault").textContent = data.ok ? (data.vault || "vault") : "not configured";
    const cards = $("memory-cards");
    clear(cards);
    cards.append(
      metric("Records", status.records ?? "—"),
      metric("Stored bytes", status.bytes ?? "—"),
      metric("Vault", data.ok ? "yes" : "no"),
      metric("Schema", status.schema ?? "—"),
    );
    const types = $("memory-types");
    clear(types);
    if (!data.ok) {
      types.append(el("p", { class: "empty", text: data.error || "Memory service is not configured." }));
    } else {
      const byType = status.by_type || {};
      const byState = status.by_state || {};
      for (const name of ["episodic", "semantic", "procedural", "short_term", "shared"]) {
        const active = byType[name] ?? 0;
        types.append(el("div", { class: "row" }, [
          el("strong", { text: name }),
          el("span", { class: "muted", text: `${active} record(s)` }),
        ]));
      }
      types.append(el("p", { class: "muted", text: `active ${byState.active ?? 0} · suppressed ${byState.suppressed ?? 0} · deleted ${byState.deleted ?? 0}` }));
    }
    $("memory-policy").textContent = JSON.stringify(status.policy || {}, null, 2) || "{}";
    const fleet = $("memory-fleet");
    clear(fleet);
    if (Array.isArray(data.fleet) && data.fleet.length) {
      const table = el("table");
      table.append(el("thead", {}, [el("tr", {}, ["Node", "Records", "Bytes", "Capture", "Last write"].map((h) => el("th", { text: h })))]));
      const body = el("tbody");
      for (const row of data.fleet) {
        body.append(el("tr", {}, [
          el("td", { text: fmt(row.node) }),
          el("td", { text: fmt(row.records) }),
          el("td", { text: fmt(row.bytes) }),
          el("td", { text: row.capture ? "on" : "off" }),
          el("td", { text: fmt(row.last_write) }),
        ]));
      }
      table.append(body);
      fleet.append(table);
    } else {
      fleet.append(el("p", { class: "empty", text: "No fleet memory telemetry on this role yet." }));
    }
    for (const error of data.errors || []) showError(error);
  } catch (error) { showError(error.message); }
}

async function loadVectors() {
  try {
    const data = await api("api/qdrant");
    $("qdrant-status").textContent = data.ok ? `Qdrant ${fmt(data.version)} · read-only` : "Qdrant unavailable";
    if (!data.ok) {
      showError(data.error);
      return;
    }
    const cards = $("qdrant-cards");
    clear(cards);
    cards.append(
      metric("Version", data.version),
      metric("Collections", data.collections?.length ?? 0),
      metric("API key", data.api_key),
      metric("Mode", "read-only"),
    );
    const list = $("collections");
    clear(list);
    if (!data.collections?.length) list.append(el("p", { class: "empty", text: "No collections in this surface." }));
    for (const collection of data.collections) {
      const tag = el("span", { class: "tag", text: `vector ${fmt(collection.vector_size)} · ${fmt(collection.distance)}` });
      const row = el("div", { class: "row" }, [
        el("div", {}, [el("strong", { text: collection.name }), el("div", { class: "muted", text: `${fmt(collection.points_count)} points · ${fmt(collection.status)}` }), tag]),
        el("button", { type: "button", text: "3D cloud" }),
      ]);
      row.querySelector("button").addEventListener("click", () => loadMap(collection.name));
      list.append(row);
    }
    const preferred = (data.map_collections || []).find((name) => data.collections.some((row) => row.name === name));
    if (preferred && !state.collection) loadMap(preferred);
  } catch (error) { showError(error.message); }
}

async function loadMap(collection) {
  state.collection = collection;
  const note = $("map-note");
  note.textContent = `Loading ${collection}…`;
  try {
    const data = await api(`api/map?collection=${encodeURIComponent(collection)}`);
    if (!data.ok) {
      state.points = [];
      note.textContent = data.error || "Map unavailable.";
      drawMap();
      return;
    }
    state.points = data.points || [];
    note.textContent = `${collection} · ${state.points.length} sampled points · ${data.note || data.projection}`;
    drawLegend();
    drawMap();
  } catch (error) { showError(error.message); }
}

function drawLegend() {
  const legend = $("map-legend");
  clear(legend);
  const roles = new Map();
  for (const point of state.points) roles.set(point.role, (roles.get(point.role) || 0) + 1);
  if (!roles.size) return;
  for (const [role, count] of roles) {
    const color = roleColor(role);
    legend.append(el("span", {}, [el("i", { style: `background:${color}` }), `${role} (${count})`]));
  }
}

function roleColor(role) {
  if (role === "teacher") return "#f59e0b";
  if (role === "student") return "#22d3ee";
  if (role === "prompt") return "#94a3b8";
  if (role === "knowledge") return "#a78bfa";
  return "#5eead4";
}

function rotate(point) {
  const cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
  const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
  const x1 = point.x * cy - point.z * sy;
  const z1 = point.x * sy + point.z * cy;
  const y1 = point.y * cp - z1 * sp;
  const z2 = point.y * sp + z1 * cp;
  return { x: x1, y: y1, z: z2 };
}

function drawMap() {
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2;
  const focal = 260 * state.zoom;
  const projected = [];
  for (const point of state.points) {
    const p = rotate(point);
    const depth = 3.2 + p.z;
    if (depth <= 0.2) continue;
    const scale = focal / depth;
    projected.push({ point, x: cx + p.x * scale, y: cy + p.y * scale, depth, scale });
  }
  projected.sort((a, b) => b.depth - a.depth);
  const cluster = new Map();
  for (const row of projected) {
    const radius = Math.max(1.2, Math.min(4.5, row.scale / 70));
    ctx.beginPath();
    ctx.fillStyle = roleColor(row.point.role);
    ctx.globalAlpha = Math.max(0.35, Math.min(0.95, 0.9 - row.depth / 12));
    ctx.arc(row.x, row.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    const key = row.point.role;
    const entry = cluster.get(key) || { x: 0, y: 0, n: 0 };
    entry.x += row.x; entry.y += row.y; entry.n += 1;
    cluster.set(key, entry);
  }
  ctx.font = "600 12px ui-sans-serif, system-ui, sans-serif";
  ctx.textAlign = "center";
  for (const [role, entry] of cluster) {
    if (entry.n < 3) continue;
    const x = entry.x / entry.n, y = entry.y / entry.n - 14;
    ctx.fillStyle = "rgba(5,7,11,.72)";
    const text = `${role} · ${entry.n}`;
    const width = ctx.measureText(text).width + 14;
    ctx.fillRect(x - width / 2, y - 12, width, 18);
    ctx.fillStyle = roleColor(role);
    ctx.fillText(text, x, y + 1);
  }
  if (!projected.length) {
    ctx.fillStyle = "#8792a6";
    ctx.font = "14px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText("No sampled vectors yet.", cx, cy);
  }
}

function updateZoomLabel() {
  const label = $("zoom-level");
  if (label) label.textContent = `${Math.round(state.zoom * 100)}%`;
}

function setZoom(value) {
  state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
  updateZoomLabel();
  drawMap();
}

function zoomBy(factor) {
  setZoom(state.zoom * factor);
}

function setupCanvas() {
  const canvas = $("map");
  const tooltip = $("map-tooltip");
  const wrap = canvas.closest(".map-wrap") || canvas;
  const pointers = new Map();
  let pinchDistance = null;

  function localPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function distance(a, b) {
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  }

  function handleWheel(event) {
    event.preventDefault();
    event.stopPropagation();
    const delta = event.deltaY || event.deltaX || 0;
    if (!delta) return;
    setZoom(state.zoom * Math.exp(-delta * 0.0015));
  }

  canvas.addEventListener("pointerdown", (event) => {
    canvas.focus({ preventScroll: true });
    pointers.set(event.pointerId, event);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinchDistance = distance(a, b);
      state.dragging = false;
      return;
    }
    state.dragging = true;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (pointers.has(event.pointerId)) pointers.set(event.pointerId, event);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const next = distance(a, b);
      if (pinchDistance && next > 0) {
        setZoom(state.zoom * (next / pinchDistance));
        pinchDistance = next;
      }
      return;
    }
    if (state.dragging) {
      state.yaw += (event.clientX - state.lastX) * 0.008;
      state.pitch += (event.clientY - state.lastY) * 0.008;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      drawMap();
      return;
    }
    const { x, y } = localPoint(event);
    let best = null;
    let bestDistance = 100;
    for (const point of state.points) {
      const p = rotate(point);
      const depth = 3.2 + p.z;
      if (depth <= 0.2) continue;
      const scale = (260 * state.zoom) / depth;
      const px = canvas.width / 2 + p.x * scale;
      const py = canvas.height / 2 + p.y * scale;
      const d = (px - x) ** 2 + (py - y) ** 2;
      if (d < bestDistance) {
        bestDistance = d;
        best = point;
      }
    }
    state.hover = best;
    if (best) {
      tooltip.hidden = false;
      tooltip.textContent = `${best.label} · ${best.role} · ${best.node}${best.run_id ? " · " + best.run_id : ""}`;
      tooltip.style.left = `${event.clientX - canvas.getBoundingClientRect().left + 12}px`;
      tooltip.style.top = `${event.clientY - canvas.getBoundingClientRect().top + 12}px`;
    } else {
      tooltip.hidden = true;
    }
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinchDistance = null;
    state.dragging = false;
  }

  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("pointerleave", (event) => {
    if (event.buttons === 0) {
      pointers.delete(event.pointerId);
      pinchDistance = null;
    }
    state.dragging = false;
    tooltip.hidden = true;
  });
  canvas.addEventListener("wheel", handleWheel, { passive: false });
  wrap.addEventListener("wheel", handleWheel, { passive: false });
  canvas.addEventListener("dblclick", () => setZoom(1));
  canvas.addEventListener("keydown", (event) => {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomBy(ZOOM_STEP);
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoomBy(1 / ZOOM_STEP);
    } else if (event.key === "0") {
      event.preventDefault();
      setZoom(1);
    }
  });

  const zoomIn = $("zoom-in");
  const zoomOut = $("zoom-out");
  const zoomReset = $("zoom-reset");
  if (zoomIn) zoomIn.addEventListener("click", () => zoomBy(ZOOM_STEP));
  if (zoomOut) zoomOut.addEventListener("click", () => zoomBy(1 / ZOOM_STEP));
  if (zoomReset) zoomReset.addEventListener("click", () => setZoom(1));
  updateZoomLabel();

  setInterval(() => {
    if (!state.auto || state.dragging || pointers.size || !state.points.length) return;
    state.yaw += 0.0035;
    drawMap();
  }, 60);
}

async function loadLearning() {
  try {
    const data = await api("api/learning");
    $("learning-node").textContent = data.node || "Master only";
    const cards = $("learning-cards");
    clear(cards);
    cards.append(
      metric("Runs", data.runs?.length ?? 0),
      metric("Teacher", data.config?.teacher_model_id || "unset"),
      metric("Student", data.config?.student_base_model || "unset"),
      metric("Method", data.config?.method || "unset"),
    );
    const runs = $("runs");
    clear(runs);
    if (!data.runs?.length) runs.append(el("p", { class: "empty", text: "No distillation runs yet." }));
    for (const run of data.runs) {
      const metrics = run.eval ? Object.entries(run.eval).map(([k, v]) => `${k}=${v}`).join(" · ") : "no evaluation";
      runs.append(el("div", { class: "row" }, [
        el("div", {}, [el("strong", { text: run.run_id }), el("div", { class: "muted", text: metrics })]),
        el("span", { class: "tag", text: run.signed ? "signed" : (run.approved === false ? "rejected" : "open") }),
      ]));
    }
    const models = $("learning-models");
    clear(models);
    for (const model of data.models || []) {
      models.append(el("div", { class: "row" }, [
        el("span", { text: model.id }),
        el("span", { class: `tag ${model.role}`, text: `${model.role} · ${model.status}` }),
      ]));
    }
    for (const error of data.errors || []) showError(error);
  } catch (error) { showError(error.message); }
}

/* --- Understand tab -------------------------------------------------------
   HTML/CSS-first: the panels, lists and details are ordinary HTML. The SVG is
   inline and rendered by this small module; no graph library and no Node build.
   The graph is derived data, never instructions and never authority. */

const SVG_NS = "http://www.w3.org/2000/svg";
const U = { graph: null, nodes: [], edges: [], byId: new Map(), layerOf: new Map(), layer: "", query: "", zoom: 100, bound: false };

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function understandNodeMatches(node) {
  if (!U.query) return true;
  const haystack = [node.id, node.name, node.summary, node.filePath, ...(node.tags || [])].join(" ").toLowerCase();
  return U.query.split(/\s+/).filter(Boolean).every((term) => haystack.includes(term));
}

async function loadUnderstand() {
  try {
    const data = await api("api/understand");
    U.graph = data.graph || null;
    U.nodes = (data.graph && data.graph.nodes) || [];
    U.edges = (data.graph && data.graph.edges) || [];
    U.byId = new Map(U.nodes.map((node) => [node.id, node]));
    U.layerOf = new Map();
    for (const layer of (data.graph && data.graph.layers) || []) {
      for (const id of layer.nodeIds || []) U.layerOf.set(id, layer.id);
    }
    U.layer = "";
    U.query = "";
    $("understand-search").value = "";
    $("understand-zoom").value = "100";
    U.zoom = 100;
    bindUnderstandControls();
    if (!data.available || !U.graph) {
      $("understand-status").textContent = "no graph";
      $("understand-note").textContent = data.error || "Run /understand to build the code-understanding graph.";
      clear($("understand-cards"));
      clear($("understand-detail"));
      $("understand-detail").append(el("p", { class: "empty", text: "No graph yet." }));
      clear($("understand-layers").querySelector("div"));
      clear($("understand-tour").querySelector("ol"));
      clear($("understand-nodes"));
      $("understand-graph").replaceChildren();
      clear($("understand-legend"));
      return;
    }
    renderUnderstandSummary(data);
    renderUnderstandLayers();
    renderUnderstandTour();
    renderUnderstandNodes();
    renderUnderstandGraph();
    renderUnderstandDetail(null);
  } catch (error) { showError(error.message); }
}

function renderUnderstandSummary(data) {
  const graph = U.graph;
  const project = graph.project || {};
  const cards = $("understand-cards");
  clear(cards);
  cards.append(
    metric("Nodes", U.nodes.length),
    metric("Edges", U.edges.length),
    metric("Layers", (graph.layers || []).length),
    metric("Tour steps", (graph.tour || []).length),
    metric("Languages", (project.languages || []).join(", ") || "—"),
    metric("Commit", String(project.gitCommitHash || "").slice(0, 12) || "—"),
  );
  $("understand-status").textContent = project.name || "graph";
  const built = project.analyzedAt || "—";
  $("understand-note").textContent = `Built ${built} · ${graph.kind || "codebase"} · ${data.path}`;
  const legend = $("understand-legend");
  clear(legend);
  const types = [
    ["file", "#5eead4"], ["class", "#a78bfa"], ["function", "#22d3ee"],
    ["endpoint", "#f59e0b"], ["module", "#94a3b8"], ["other", "#64748b"],
  ];
  for (const [name, color] of types) {
    legend.append(el("span", {}, [el("i", { class: "u-dot", style: `background:${color}` }), name]));
  }
}

function bindUnderstandControls() {
  if (U.bound) return;
  U.bound = true;
  $("understand-search").addEventListener("input", (event) => {
    U.query = event.target.value.trim().toLowerCase();
    renderUnderstandGraph();
  });
  $("understand-layer").addEventListener("change", (event) => {
    U.layer = event.target.value;
    renderUnderstandGraph();
  });
  $("understand-zoom").addEventListener("input", (event) => {
    U.zoom = Number(event.target.value) || 100;
    applyUnderstandZoom();
  });
  $("understand-graph").addEventListener("click", (event) => {
    const group = event.target.closest(".u-node");
    if (group) selectUnderstandNode(group.dataset.id);
  });
}

function renderUnderstandLayers() {
  const select = $("understand-layer");
  const previous = U.layer;
  clear(select);
  select.append(el("option", { value: "", text: "All layers" }));
  const container = $("understand-layers").querySelector("div");
  clear(container);
  for (const layer of U.graph.layers || []) {
    select.append(el("option", { value: layer.id, text: `${layer.name} (${(layer.nodeIds || []).length})` }));
    const button = el("button", { type: "button", text: `${layer.name} · ${(layer.nodeIds || []).length}` });
    button.addEventListener("click", () => {
      U.layer = layer.id;
      select.value = layer.id;
      renderUnderstandGraph();
    });
    container.append(el("div", { class: "row" }, [button]));
  }
  if (previous) select.value = previous;
}

function renderUnderstandTour() {
  const list = $("understand-tour").querySelector("ol");
  clear(list);
  for (const step of U.graph.tour || []) {
    const item = el("li", { text: `${step.order}. ${step.title}` });
    item.title = step.description || "";
    item.addEventListener("click", () => {
      if (step.nodeIds && step.nodeIds.length) selectUnderstandNode(step.nodeIds[0]);
    });
    list.append(item);
  }
  if (!list.children.length) list.append(el("li", { class: "muted", text: "No tour steps in this graph." }));
}

function renderUnderstandNodes() {
  const container = $("understand-nodes");
  clear(container);
  const nodes = [...U.nodes].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id))).slice(0, 300);
  for (const node of nodes) {
    const row = el("div", { class: "row understand-node-row", "data-id": node.id }, [
      el("span", { text: node.name || node.id }),
      el("span", { class: "tag", text: node.type || "node" }),
    ]);
    row.addEventListener("click", () => selectUnderstandNode(node.id));
    container.append(row);
  }
  if (U.nodes.length > nodes.length) {
    container.append(el("p", { class: "empty", text: `Showing ${nodes.length} of ${U.nodes.length} nodes; use search or the layer filter.` }));
  }
}

function renderUnderstandGraph() {
  const svg = $("understand-graph");
  clear(svg);
  if (!U.graph) return;
  const degree = new Map();
  for (const edge of U.edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  let candidates = U.nodes.filter((node) => ["file", "class", "function", "module", "endpoint", "concept", "document"].includes(node.type));
  if (U.layer) candidates = candidates.filter((node) => U.layerOf.get(node.id) === U.layer);
  if (U.query) candidates = candidates.filter(understandNodeMatches);
  if (!U.query) {
    candidates.sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0) || String(a.id).localeCompare(String(b.id)));
    candidates = candidates.slice(0, 260);
  }
  if (!candidates.length) {
    svg.append(svgEl("text", { x: 20, y: 30, fill: "#8792a6", "font-size": 13 }));
    svg.lastChild.textContent = "No nodes match the current filter.";
    svg.setAttribute("viewBox", "0 0 600 80");
    svg.dataset.baseWidth = "600";
    svg.dataset.baseHeight = "80";
    applyUnderstandZoom();
    return;
  }
  const drawn = new Map(candidates.map((node) => [node.id, node]));
  const layers = (U.graph.layers || []).map((layer) => layer.id);
  const groups = new Map();
  for (const node of candidates) {
    const layer = U.layerOf.get(node.id) || "layer:other";
    if (!groups.has(layer)) groups.set(layer, []);
    groups.get(layer).push(node);
  }
  const order = [...groups.keys()].sort((a, b) => {
    const ai = layers.indexOf(a);
    const bi = layers.indexOf(b);
    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.localeCompare(b);
  });
  const nodeWidth = 200;
  const nodeHeight = 22;
  const column = 236;
  const row = 28;
  const originX = 30;
  const originY = 40;
  const positions = new Map();
  let maxRows = 0;
  order.forEach((layer, columnIndex) => {
    const rowNodes = groups.get(layer) || [];
    maxRows = Math.max(maxRows, rowNodes.length);
    rowNodes.sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));
    rowNodes.forEach((node, rowIndex) => {
      positions.set(node.id, { x: originX + columnIndex * column, y: originY + rowIndex * row });
    });
  });
  const width = Math.max(780, originX * 2 + order.length * column);
  const height = Math.max(420, originY * 2 + maxRows * row);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.dataset.baseWidth = String(width);
  svg.dataset.baseHeight = String(height);
  for (const edge of U.edges) {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target || !drawn.has(edge.source) || !drawn.has(edge.target)) continue;
    const line = svgEl("line", {
      x1: source.x + nodeWidth, y1: source.y + nodeHeight / 2,
      x2: target.x, y2: target.y + nodeHeight / 2,
      class: `u-edge u-edge-${edge.type}`,
      "data-source": edge.source, "data-target": edge.target,
    });
    line.append(svgEl("title"));
    line.lastChild.textContent = edge.type;
    svg.append(line);
  }
  for (const [id, node] of drawn) {
    const position = positions.get(id);
    if (!position) continue;
    const group = svgEl("g", { class: `u-node u-node-${node.type}`, "data-id": id, transform: `translate(${position.x},${position.y})` });
    group.append(svgEl("rect", { width: nodeWidth, height: nodeHeight, rx: 4 }));
    const text = svgEl("text", { x: 6, y: 14 });
    text.textContent = String(node.name || node.id).slice(0, 32);
    group.append(text);
    const title = svgEl("title");
    title.textContent = `${node.type || "node"}: ${node.name || node.id}\n${node.summary || ""}`;
    group.append(title);
    svg.append(group);
  }
  applyUnderstandZoom();
}

function applyUnderstandZoom() {
  const svg = $("understand-graph");
  const baseWidth = Number(svg.dataset.baseWidth || 780);
  const baseHeight = Number(svg.dataset.baseHeight || 420);
  svg.style.width = `${Math.round((baseWidth * U.zoom) / 100)}px`;
  svg.style.height = `${Math.round((baseHeight * U.zoom) / 100)}px`;
}

function renderUnderstandDetail(node) {
  const detail = $("understand-detail");
  clear(detail);
  if (!node) {
    detail.append(el("p", { class: "empty", text: "Select a node in the graph or the list." }));
    return;
  }
  const incoming = U.edges.filter((edge) => edge.target === node.id);
  const outgoing = U.edges.filter((edge) => edge.source === node.id);
  detail.append(
    el("div", {}, [
      el("strong", { text: node.name || node.id }),
      el("div", { class: "muted", text: `${node.type || "node"} · ${node.complexity || "moderate"}` }),
    ]),
    el("p", { class: "muted", text: node.summary || "No summary." }),
    el("dl", { class: "kv" }, [
      el("dt", { text: "File" }), el("dd", { text: node.filePath || "—" }),
      el("dt", { text: "Lines" }), el("dd", { text: (node.lineRange || []).join("–") || "—" }),
      el("dt", { text: "Tags" }), el("dd", { text: (node.tags || []).join(", ") || "—" }),
    ]),
  );
  if (incoming.length || outgoing.length) {
    const list = el("div", { class: "list" });
    for (const edge of [...outgoing, ...incoming].slice(0, 40)) {
      const otherId = edge.source === node.id ? edge.target : edge.source;
      const other = U.byId.get(otherId);
      const arrow = edge.source === node.id ? "→" : "←";
      const row = el("div", { class: "row" }, [
        el("span", { text: `${arrow} ${edge.type}` }),
        el("span", { text: other ? (other.name || other.id) : otherId }),
      ]);
      row.addEventListener("click", () => selectUnderstandNode(otherId));
      list.append(row);
    }
    detail.append(el("h3", { text: "Edges" }), list);
  }
}

function selectUnderstandNode(id) {
  const node = U.byId.get(id);
  if (!node) return;
  renderUnderstandDetail(node);
  const connected = new Set([id]);
  for (const edge of U.edges) {
    if (edge.source === id) connected.add(edge.target);
    if (edge.target === id) connected.add(edge.source);
  }
  for (const group of document.querySelectorAll("#understand-graph .u-node")) {
    group.classList.toggle("selected", group.dataset.id === id);
    group.classList.toggle("dim", !connected.has(group.dataset.id));
  }
  for (const line of document.querySelectorAll("#understand-graph .u-edge")) {
    line.classList.toggle("dim", line.dataset.source !== id && line.dataset.target !== id);
  }
  for (const row of document.querySelectorAll(".understand-node-row")) {
    row.classList.toggle("active", row.dataset.id === id);
  }
}

async function loadIssues() {
  try {
    const data = await api("api/issues");
    $("issues-status").textContent = data.ok ? `${data.counts?.total ?? 0} recorded` : "Master only";
    const cards = $("issues-cards");
    clear(cards);
    if (!data.ok) {
      cards.append(metric("Status", data.error || "unavailable"));
      return;
    }
    cards.append(
      metric("Total", data.counts?.total ?? 0),
      metric("Open", data.counts?.open ?? 0),
      metric("Needs triage", data.counts?.needs_triage ?? 0),
      metric("Ready for agent", data.counts?.ready_for_agent ?? 0),
    );
    const wrap = $("issues-list");
    clear(wrap);
    if (!data.issues?.length) {
      wrap.append(el("p", { class: "empty", text: "No peer work items recorded yet." }));
      return;
    }
    const table = el("table");
    table.append(el("thead", {}, [el("tr", {}, ["Node", "Issue", "Title", "Status", "Labels", "Updated"].map((h) => el("th", { text: h })))]));
    const body = el("tbody");
    for (const issue of data.issues) {
      const detail = el("details", {}, [
        el("summary", { text: issue.title || issue.issue_id }),
        el("p", { class: "muted", text: issue.body || "No body." }),
      ]);
      if (issue.triage?.note) {
        detail.append(el("p", { class: "muted", text: `Triage: ${issue.triage.note}` }));
      }
      body.append(el("tr", {}, [
        el("td", { text: issue.node_id || "—" }),
        el("td", { text: issue.issue_id || "—" }),
        el("td", {}, [detail]),
        el("td", { text: issue.effective_status || issue.status || "—" }),
        el("td", { text: (issue.effective_labels || issue.labels || []).join(", ") || "—" }),
        el("td", { text: issue.updated_at || issue.received_at || "—" }),
      ]));
    }
    table.append(body);
    wrap.append(table);
  } catch (error) { showError(error.message); }
}

async function loadEvals() {
  try {
    const data = await api("api/evals");
    $("evals-status").textContent = data.ok ? `${data.counts?.total ?? 0} verdict(s)` : "Unavailable";
    const cards = $("evals-cards");
    clear(cards);
    if (!data.ok) {
      cards.append(metric("Status", data.error || "unavailable"));
      return;
    }
    cards.append(
      metric("Evaluated", data.counts?.total ?? 0),
      metric("Pass", data.counts?.pass ?? 0),
      metric("Warn", data.counts?.warn ?? 0),
      metric("Fail", data.counts?.fail ?? 0),
      metric("Invalid", data.counts?.invalid ?? 0),
    );
    const wrap = $("evals-list");
    clear(wrap);
    if (!data.records?.length) {
      wrap.append(el("p", { class: "empty", text: "No skill-evaluation records on this node yet." }));
      return;
    }
    const table = el("table");
    table.append(
      el("thead", {}, [
        el("tr", {}, ["Verdict", "Skill", "Subject", "Evaluator", "Findings", "Created"].map((h) => el("th", { text: h }))),
      ]),
    );
    const body = el("tbody");
    for (const record of data.records) {
      const detail = el("details", {}, [
        el("summary", { text: `${record.findings_total || 0} finding(s)` }),
        ...(record.findings || []).map((finding) =>
          el("p", { class: "muted", text: `${fmt(finding.severity)} · ${fmt(finding.rule)} · ${fmt(finding.message)}` }),
        ),
      ]);
      body.append(el("tr", {}, [
        el("td", { text: fmt(record.verdict) }),
        el("td", { text: fmt(record.skill) }),
        el("td", { text: `${fmt(record.subject?.kind)} · ${fmt(record.subject?.ref)}` }),
        el("td", { text: fmt(record.evaluator?.id) }),
        el("td", {}, [detail]),
        el("td", { text: fmt(record.created_at) }),
      ]));
    }
    table.append(body);
    wrap.append(table);
  } catch (error) { showError(error.message); }
}

async function init() {
  try {
    state.surface = await api("api/surface");
    $("title").textContent = state.surface.title || "Sparknet Console";
    $("subtitle").textContent = `${state.surface.node || ""} · read-only ${state.surface.role || ""} surface`;
    initTabs();
  } catch (error) { showError(error.message); }
}

setupCanvas();
init();
