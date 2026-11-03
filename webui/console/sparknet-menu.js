/* Sparknet launcher injected into Open WebUI by nginx.
 *
 * It is deliberately a same-origin link block, not a second app framework: the
 * console validates the user's Open WebUI token and the role scope. The launcher
 * hides Learning for a peer after asking the console for its surface.
 */
(function () {
  "use strict";
  if (location.pathname.startsWith("/sparknet-console")) return;
  var BASE = "/sparknet-console/";
  var mounted = false;

  function mount() {
    if (mounted || !document.body) return;
    if (document.getElementById("sparknet-launcher")) {
      mounted = true;
      return;
    }
    var box = document.createElement("div");
    box.id = "sparknet-launcher";
    box.setAttribute("aria-label", "Sparknet");
    box.innerHTML =
      '<div style="font:600 10px/1.2 ui-sans-serif,system-ui,sans-serif;letter-spacing:.12em;color:#5eead4;margin:0 6px 7px;">SPARKNET</div>' +
      '<a data-s="mesh" href="' + BASE + '#mesh">Mesh</a>' +
      '<a data-s="vectors" href="' + BASE + '#vectors">Vectors</a>' +
      '<a data-s="learning" href="' + BASE + '#learning">Learning</a>';
    box.style.cssText =
      "position:fixed;right:16px;bottom:72px;z-index:2147483646;display:flex;flex-direction:column;gap:2px;" +
      "padding:10px;border:1px solid #253041;border-radius:12px;background:rgba(9,12,18,.94);" +
      "box-shadow:0 12px 30px rgba(0,0,0,.35);backdrop-filter:blur(8px);";
    for (var a of box.querySelectorAll("a")) {
      a.style.cssText =
        "display:block;padding:5px 9px;border-radius:7px;color:#cbd5e1;text-decoration:none;" +
        "font:500 12px/1.4 ui-sans-serif,system-ui,sans-serif;";
      a.onmouseenter = function () { this.style.background = "#13201f"; this.style.color = "#5eead4"; };
      a.onmouseleave = function () { this.style.background = "transparent"; this.style.color = "#cbd5e1"; };
    }
    document.body.appendChild(box);
    mounted = true;

    var token = localStorage.getItem("token");
    if (!token) return;
    fetch(BASE + "api/surface", { headers: { Authorization: "Bearer " + token, Accept: "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (surface) {
        if (!surface || !Array.isArray(surface.menus)) return;
        var learning = box.querySelector('[data-s="learning"]');
        if (learning && surface.menus.indexOf("learning") === -1) learning.style.display = "none";
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
  if (document.body) {
    new MutationObserver(function () {
      if (document.body && !document.getElementById("sparknet-launcher")) {
        mounted = false;
        mount();
      }
    }).observe(document.body, { childList: true });
  }
})();
