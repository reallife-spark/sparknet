/* Sparknet sidebar group, injected into Open WebUI by nginx.
 *
 * The group sits directly under the pinned Notes/Workspace items and uses the
 * same row classes, so it behaves like a native sidebar section instead of a
 * floating overlay. The console validates the Open WebUI token and the role
 * scope; Learning is read-only on the peer (proxied from the Master's 4221
 * snapshot) and local on the Master.
 */
(function () {
  "use strict";
  if (location.pathname.startsWith("/sparknet-console")) return;
  var BASE = "/sparknet-console/";
  var GROUP_ID = "sparknet-menu-group";
  var ICONS = {
    mesh:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-4"><circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="18" r="2.2"/><path d="M10.7 6.8 6.2 15.8M13.3 6.8l4.5 9M7.2 18h9.6"/></svg>',
    vectors:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="M4 19V5M4 19h16"/><path d="m7 15 4-5 3 2 5-7"/><circle cx="7" cy="15" r="1.2" fill="currentColor"/><circle cx="11" cy="10" r="1.2" fill="currentColor"/><circle cx="14" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="5" r="1.2" fill="currentColor"/></svg>',
    learning:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="M12 3v3M12 18v3M4.2 7.5l2.6 1.5M17.2 15l2.6 1.5M4.2 16.5l2.6-1.5M17.2 9l2.6-1.5"/><circle cx="12" cy="12" r="4.2"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/></svg>'
  };

  function el(tag, cls, html) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html !== undefined) node.innerHTML = html;
    return node;
  }

  function row(item) {
    var wrap = el("div", "px-1 flex justify-center text-gray-700 dark:text-gray-300");
    wrap.dataset.sparknet = item.id;
    var link = el("a", "grow flex items-center space-x-2 rounded-xl px-2 py-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-900");
    link.href = item.href && item.href.charAt(0) === "#" ? BASE + item.href : item.href;
    link.draggable = false;
    link.setAttribute("aria-label", item.label);
    var icon = el("div", "self-center flex size-4 shrink-0 items-center justify-center", ICONS[item.icon || item.id] || "");
    var label = el("div", "flex self-center translate-y-[0.5px]");
    label.appendChild(el("div", "self-center text-[0.8125rem] leading-5", item.label || item.id));
    link.appendChild(icon);
    link.appendChild(label);
    wrap.appendChild(link);
    return wrap;
  }

  function build() {
    var group = el("div", "sparknet-sidebar-group");
    group.id = GROUP_ID;
    var heading = el("div", "px-1 pt-2 pb-1");
    heading.appendChild(el("div", "border-t border-gray-100 dark:border-gray-900"));
    heading.appendChild(
      el(
        "div",
        "px-2 pt-2 text-[0.6875rem] font-medium uppercase tracking-[0.12em] text-gray-500 dark:text-gray-500",
        "SPARKNET"
      )
    );
    group.appendChild(heading);
    return group;
  }

  function applySurface(group) {
    var token = localStorage.getItem("token");
    if (!token) return;
    fetch(BASE + "api/surface", { headers: { Authorization: "Bearer " + token, Accept: "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (surface) {
        if (!surface) return;
        var items = Array.isArray(surface.menu_items)
          ? surface.menu_items
          : (surface.menus || []).map(function (id) { return { id: id, label: id, href: "#" + id, icon: id }; });
        for (var i = 0; i < items.length; i++) group.appendChild(row(items[i]));
      })
      .catch(function () {});
  }

  function mount() {
    if (document.getElementById(GROUP_ID)) return;
    var pinned = document.getElementById("pinned-menu-items-list");
    if (!pinned || !pinned.parentNode) return;
    var group = build();
    pinned.insertAdjacentElement("afterend", group);
    applySurface(group);
  }

  function scheduleMount() {
    if (document.readyState === "loading") return;
    if (!document.getElementById(GROUP_ID)) mount();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleMount, { once: true });
  } else {
    scheduleMount();
  }

  if (document.body) {
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        scheduleMount();
      });
    }).observe(document.body, { childList: true, subtree: true });
  }
})();
