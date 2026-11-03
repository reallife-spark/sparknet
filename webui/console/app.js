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
  const menus = new Set(state.surface.menus || []);
  for (const link of document.querySelectorAll("#tabs a")) {
    if (!menus.has(link.dataset.tab)) link.hidden = true;
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

function setupCanvas() {
  const canvas = $("map");
  const tooltip = $("map-tooltip");
  canvas.addEventListener("pointerdown", (event) => {
    state.dragging = true; state.lastX = event.clientX; state.lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (state.dragging) {
      state.yaw += (event.clientX - state.lastX) * 0.008;
      state.pitch += (event.clientY - state.lastY) * 0.008;
      state.lastX = event.clientX; state.lastY = event.clientY;
      drawMap();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * (canvas.width / rect.width);
    const y = (event.clientY - rect.top) * (canvas.height / rect.height);
    let best = null, bestDistance = 100;
    for (const point of state.points) {
      const p = rotate(point);
      const depth = 3.2 + p.z;
      if (depth <= 0.2) continue;
      const scale = 260 * state.zoom / depth;
      const px = canvas.width / 2 + p.x * scale, py = canvas.height / 2 + p.y * scale;
      const distance = (px - x) ** 2 + (py - y) ** 2;
      if (distance < bestDistance) { bestDistance = distance; best = point; }
    }
    state.hover = best;
    if (best) {
      tooltip.hidden = false;
      tooltip.textContent = `${best.label} · ${best.role} · ${best.node}${best.run_id ? " · " + best.run_id : ""}`;
      tooltip.style.left = `${event.clientX - rect.left + 12}px`;
      tooltip.style.top = `${event.clientY - rect.top + 12}px`;
    } else {
      tooltip.hidden = true;
    }
  });
  canvas.addEventListener("pointerup", () => { state.dragging = false; });
  canvas.addEventListener("pointerleave", () => { state.dragging = false; tooltip.hidden = true; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.zoom = Math.max(0.35, Math.min(4, state.zoom * (event.deltaY < 0 ? 1.12 : 0.89)));
    drawMap();
  }, { passive: false });
  setInterval(() => {
    if (!state.auto || state.dragging || !state.points.length) return;
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

async function init() {
  try {
    state.surface = await api("api/surface");
    $("title").textContent = state.surface.title || "Sparknet Console";
    $("subtitle").textContent = `${state.surface.node || ""} · read-only ${state.surface.role || ""} surface`;
    initTabs();
    setupCanvas();
  } catch (error) { showError(error.message); }
}

init();
