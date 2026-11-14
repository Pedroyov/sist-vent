// JavaScript propio del sistema
(function () {
  "use strict";

  // --- Registro del service worker (PWA) ---
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function (err) {
        console.warn("No se pudo registrar el service worker:", err);
      });
    });
  }

  // --- Botón "Instalar app" (Chrome / Edge / Android) ---
  var promptInstalar = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    promptInstalar = e;
    var wrap = document.getElementById("btn-instalar-wrap");
    if (wrap) wrap.classList.remove("d-none");
  });

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#btn-instalar");
    if (!btn || !promptInstalar) return;
    promptInstalar.prompt();
    promptInstalar.userChoice.finally(function () {
      promptInstalar = null;
      var wrap = document.getElementById("btn-instalar-wrap");
      if (wrap) wrap.classList.add("d-none");
    });
  });

  // --- Tema claro / oscuro ---
  function aplicarIconoTema() {
    var btn = document.getElementById("btn-tema");
    if (!btn) return;
    var oscuro = document.documentElement.getAttribute("data-bs-theme") === "dark";
    btn.innerHTML = oscuro ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon-stars"></i>';
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#btn-tema");
    if (!btn) return;
    e.preventDefault();
    var actual = document.documentElement.getAttribute("data-bs-theme");
    var nuevo = actual === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-bs-theme", nuevo);
    try { localStorage.setItem("tema", nuevo); } catch (err) {}
    aplicarIconoTema();
  });

  document.addEventListener("DOMContentLoaded", aplicarIconoTema);

  // --- Modal de confirmación para eliminar ---
  document.addEventListener("show.bs.modal", function (e) {
    if (e.target.id !== "modalEliminar" || !e.relatedTarget) return;
    var origen = e.relatedTarget;
    document.getElementById("modalEliminarForm").action = origen.dataset.url;
    document.getElementById("modalEliminarMensaje").textContent =
      origen.dataset.mensaje || "¿Seguro que deseas eliminar este registro?";
  });
})();

// Botones de WhatsApp que además anotan el aviso en el sistema (por ejemplo, recordar una deuda a un cliente).
// El enlace abre WhatsApp normalmente; el registro va aparte para no bloquear esa apertura.
document.addEventListener("click", function (e) {
  var a = e.target.closest(".btn-recordar");
  if (!a || !window.htmx) return;
  var vals = a.dataset.avisoFecha ? {fecha: a.dataset.avisoFecha} : {};
  htmx.ajax("POST", a.dataset.avisoUrl, {source: a, target: a.dataset.avisoDestino, swap: "innerHTML", values: vals});
});

// Imprimir sin salir de la pantalla: <a data-imprimir="/ruta/de/impresion/">.
// En la PC se imprime desde un marco oculto; en el celular se abre en otra pestaña y se imprime solo.
window.imprimir = function (url) {
  var movil = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (movil) { window.open(url + (url.indexOf("?") >= 0 ? "&" : "?") + "auto=1", "_blank"); return; }
  var viejo = document.getElementById("marco-impresion");
  if (viejo) viejo.remove();
  var marco = document.createElement("iframe");
  marco.id = "marco-impresion";
  marco.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  marco.src = url;
  marco.onload = function () { setTimeout(function () { marco.contentWindow.focus(); marco.contentWindow.print(); }, 150); };
  document.body.appendChild(marco);
};
document.addEventListener("click", function (e) {
  var a = e.target.closest("[data-imprimir]");
  if (!a) return;
  e.preventDefault();
  window.imprimir(a.dataset.imprimir);
});

// Si la sesión venció mientras una pantalla se actualizaba sola (mesas, cocina), recarga para ir al ingreso
// en vez de meter la pantalla de ingreso dentro del mapa.
document.addEventListener("htmx:beforeSwap", function (e) {
  var xhr = e.detail.xhr;
  if (xhr && xhr.responseURL && xhr.responseURL.indexOf("/ingresar/") >= 0) { e.detail.shouldSwap = false; location.reload(); }
});
