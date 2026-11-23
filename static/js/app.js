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
// En la PC el ticket se trae y se imprime desde esta misma página (en una zona aislada con Shadow DOM), con la hoja
// del tamaño del rollo. No se usa un marco oculto porque Chrome ignora el tamaño de hoja de un marco y sale en A4.
// En el celular se abre en otra pestaña y se imprime solo.
window.imprimir = function (url) {
  var movil = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (movil) { window.open(url + (url.indexOf("?") >= 0 ? "&" : "?") + "auto=1", "_blank"); return; }
  fetch(url, {credentials: "same-origin"}).then(function (r) {
    if (!r.ok || r.url.indexOf("/ingresar/") >= 0) throw new Error("sin ticket");
    return r.text();
  }).then(function (html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var papel = doc.querySelector(".papel");
    if (!papel) throw new Error("sin ticket");
    var css = Array.prototype.map.call(doc.querySelectorAll("style"), function (s) { return s.textContent; }).join("\n").replace(/:root/g, ":host");
    var viejo = document.getElementById("zona-impresion");
    if (viejo) viejo.remove();
    var zona = document.createElement("div");
    zona.id = "zona-impresion";
    var sombra = zona.attachShadow({mode: "open"});
    var hoja = papel.dataset.hoja === "1";  // impresora normal (A4 / carta): el ticket centrado en la hoja
    sombra.innerHTML = "<style>" + css + (hoja ? " @media print { .papel { margin: 0 auto; } }" : " @media print { .papel { width: 100%; } }") + "</style>";
    sombra.appendChild(document.importNode(papel, true));
    zona.style.cssText = "display:block;position:absolute;left:-10000px;top:0";  // fuera de la vista, solo para medir
    document.body.appendChild(zona);
    var imgs = Array.prototype.slice.call(sombra.querySelectorAll("img"));
    return Promise.race([
      Promise.all(imgs.map(function (i) { return i.complete ? 0 : new Promise(function (ok) { i.onload = i.onerror = ok; }); })),
      new Promise(function (ok) { setTimeout(ok, 1500); })
    ]).then(function () {
      var mm = Math.ceil(sombra.querySelector(".papel").getBoundingClientRect().height * 25.4 / 96 + 6);
      zona.style.cssText = "";
      var pagina = document.getElementById("pagina-impresion");
      if (!pagina) { pagina = document.createElement("style"); pagina.id = "pagina-impresion"; document.head.appendChild(pagina); }
      pagina.textContent = hoja ? "@page { size: auto; margin: 15mm; }" : "@page { size: " + (papel.dataset.ancho || 80) + "mm " + mm + "mm; margin: 0; }";
      document.body.classList.add("imprimiendo");
      var fin = function () {
        window.removeEventListener("afterprint", fin);
        document.body.classList.remove("imprimiendo");
        pagina.textContent = "";  // Ctrl+P en otras pantallas vuelve a ser hoja normal
      };
      window.addEventListener("afterprint", fin);
      window.print();
    });
  }).catch(function () { window.open(url, "_blank"); });
};
// En la pantalla de una venta, Ctrl+P imprime el ticket del rollo (no la pantalla en A4).
document.addEventListener("keydown", function (e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === "p" || e.key === "P")) {
    var b = document.getElementById("btn-imprimir");
    if (b && b.dataset.imprimir) { e.preventDefault(); window.imprimir(b.dataset.imprimir); }
  }
});
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
