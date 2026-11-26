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
window.imprimir = function (url, opciones) {
  // Devuelve una promesa que se cumple al terminar de imprimir (la usa la estación de impresión para avisar al servidor).
  opciones = opciones || {};
  var movil = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (movil && !opciones.estacion) { window.open(url + (url.indexOf("?") >= 0 ? "&" : "?") + "auto=1", "_blank"); return Promise.resolve(); }
  return fetch(url, {credentials: "same-origin"}).then(function (r) {
    if (!r.ok || r.url.indexOf("/ingresar/") >= 0) throw new Error("No se pudo abrir lo que se imprime (" + r.status + ").");
    return r.text();
  }).then(function (html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var papel = doc.querySelector(".papel");
    if (!papel) throw new Error("La página no tiene nada que imprimir.");
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
      return new Promise(function (ok) {
        var listo = false;
        var fin = function () {
          if (listo) return;
          listo = true;
          window.removeEventListener("afterprint", fin);
          document.body.classList.remove("imprimiendo");
          pagina.textContent = "";  // Ctrl+P en otras pantallas vuelve a ser hoja normal
          zona.remove();
          ok();
        };
        window.addEventListener("afterprint", fin);
        window.print();
        setTimeout(fin, 15000);  // por si el navegador no avisa al terminar
      });
    });
  }).catch(function (e) {
    if (opciones.estacion) throw e;
    window.open(url, "_blank");
  });
};

// Con la impresión automática (estación en la PC de caja), «Imprimir» en otro equipo pregunta: a la ticketera de caja
// (por la cola) o a una impresora de este equipo (como siempre). En la estación imprime directo.
window.csrfToken = function () {
  try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || ""; } catch (e) { return ""; }
};
function esEstacion() { try { return localStorage.getItem("estacion_impresion") === "1"; } catch (e) { return false; } }
window.imprimirElegir = function (url) {
  if (document.body.dataset.cola !== "1" || esEstacion()) { window.imprimir(url); return; }
  var m = document.getElementById("m-imprimir");
  if (!m) {
    var div = document.createElement("div");
    div.innerHTML = '<div class="modal fade" id="m-imprimir" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-dialog-centered modal-sm"><div class="modal-content">' +
      '<div class="modal-header py-2"><h5 class="modal-title fs-6"><i class="bi bi-printer me-1"></i> Imprimir</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button></div>' +
      '<div class="modal-body d-grid gap-2"><button type="button" class="btn btn-primary" id="imp-caja"><i class="bi bi-receipt me-1"></i>Ticketera de caja</button>' +
      '<button type="button" class="btn btn-outline-secondary" id="imp-aqui"><i class="bi bi-phone me-1"></i>Elegir impresora en este equipo</button>' +
      '<div class="small text-body-secondary d-none" id="imp-msg"></div></div></div></div></div>';
    document.body.appendChild(div.firstChild);
    m = document.getElementById("m-imprimir");
  }
  var modal = bootstrap.Modal.getOrCreateInstance(m), msg = document.getElementById("imp-msg");
  msg.classList.add("d-none");
  document.getElementById("imp-aqui").onclick = function () { modal.hide(); window.imprimir(url); };
  document.getElementById("imp-caja").onclick = function () {
    fetch("/impresion/enviar/", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": window.csrfToken()},
      body: JSON.stringify({url: url})}).then(function (r) { return r.json(); }).then(function (d) {
      msg.classList.remove("d-none");
      if (d.error) { msg.className = "small text-danger"; msg.textContent = d.error; return; }
      msg.className = "small " + (d.estacion ? "text-success" : "text-warning-emphasis");
      msg.innerHTML = d.estacion ? '<i class="bi bi-check2-circle"></i> Enviado a la ticketera de caja.'
        : '<i class="bi bi-exclamation-triangle"></i> La PC de caja no está conectada: quedó en la cola y saldrá al prenderla. Puedes enviarlo por WhatsApp.';
      if (d.estacion) setTimeout(function () { modal.hide(); }, 1200);
    }).catch(function () { msg.classList.remove("d-none"); msg.className = "small text-danger"; msg.textContent = "Sin conexión: vuelve a intentar."; });
  };
  modal.show();
};
// En la pantalla de una venta, Ctrl+P imprime el ticket del rollo (no la pantalla en A4).
document.addEventListener("keydown", function (e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === "p" || e.key === "P")) {
    var b = document.getElementById("btn-imprimir");
    if (b && b.dataset.imprimir) { e.preventDefault(); window.imprimirElegir(b.dataset.imprimir); }
  }
});
document.addEventListener("click", function (e) {
  var a = e.target.closest("[data-imprimir]");
  if (!a) return;
  e.preventDefault();
  window.imprimirElegir(a.dataset.imprimir);
});

// Si la sesión venció mientras una pantalla se actualizaba sola (mesas, cocina), recarga para ir al ingreso
// en vez de meter la pantalla de ingreso dentro del mapa.
document.addEventListener("htmx:beforeSwap", function (e) {
  var xhr = e.detail.xhr;
  if (xhr && xhr.responseURL && xhr.responseURL.indexOf("/ingresar/") >= 0) { e.detail.shouldSwap = false; location.reload(); }
});

// Menú lateral: al cambiar de pantalla se queda donde estaba (si tocaste «Reportes», abajo, no vuelve arriba).
(function () {
  var barra = document.querySelector(".app-sidebar .sidebar-wrapper");
  if (!barra) return;
  try {
    var y = parseInt(sessionStorage.getItem("menu_scroll") || "", 10);
    if (y > 0) barra.scrollTop = y;
  } catch (e) {}
  var activo = barra.querySelector(".nav-link.active");
  if (activo) {  // si la opción actual quedó fuera de la vista (por ejemplo, se entró por un enlace), se acerca sola
    var b = barra.getBoundingClientRect(), a = activo.getBoundingClientRect();
    if (a.top < b.top || a.bottom > b.bottom) activo.scrollIntoView({block: "center"});
  }
  var guardar = function () { try { sessionStorage.setItem("menu_scroll", String(barra.scrollTop)); } catch (e) {} };
  barra.addEventListener("click", guardar);
  window.addEventListener("pagehide", guardar);
})();
