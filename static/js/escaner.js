/* Escanear un código de barras con la cámara (respaldo del lector USB o bluetooth).
   Cualquier <input data-escaner> recibe al lado un botón con una cámara. Al leer un código, lo escribe en el campo y
   simula un Enter (como hace un lector), así Vender lo agrega al carrito y el formulario de producto lo deja escrito.
   Usa el lector del navegador (BarcodeDetector, Chrome en Android) y, si no hay (iPhone, algunos PC), la librería ZXing
   guardada en el sistema (static/vendor/zxing), que solo se descarga la primera vez que se toca la cámara.
   La cámara solo funciona con https (o en la misma PC con localhost): si no, el botón no aparece. */
(function () {
  "use strict";
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.isSecureContext)) return;
  var FORMATOS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr_code"];
  var ZXING = (document.currentScript && document.currentScript.dataset.zxing) || "/static/vendor/zxing/zxing.min.js";
  var modal, video, aviso, detener = null;

  function crearModal() {
    if (modal) return;
    var div = document.createElement("div");
    div.innerHTML =
      '<div class="modal fade" id="m-escaner" tabindex="-1" aria-hidden="true"><div class="modal-dialog modal-dialog-centered modal-fullscreen-sm-down">' +
      '<div class="modal-content"><div class="modal-header py-2"><h5 class="modal-title fs-6"><i class="bi bi-camera me-1"></i> Escanear código</h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button></div>' +
      '<div class="modal-body p-0 bg-black position-relative"><video playsinline muted class="w-100 d-block" style="max-height: 70vh; object-fit: cover"></video>' +
      '<div class="position-absolute top-50 start-0 end-0 border-top border-2 border-danger opacity-75"></div></div>' +
      '<div class="modal-footer py-2 justify-content-center small text-body-secondary" id="escaner-aviso">Apunta al código de barras del producto.</div>' +
      "</div></div></div>";
    document.body.appendChild(div.firstChild);
    modal = document.getElementById("m-escaner");
    video = modal.querySelector("video");
    aviso = document.getElementById("escaner-aviso");
    modal.addEventListener("hidden.bs.modal", parar);
  }

  function parar() {
    if (detener) { try { detener(); } catch (e) {} detener = null; }
    if (video && video.srcObject) { video.srcObject.getTracks().forEach(function (t) { t.stop(); }); video.srcObject = null; }
  }

  function cargarZxing() {
    return new Promise(function (ok, mal) {
      if (window.ZXing) return ok(window.ZXing);
      var s = document.createElement("script");
      s.src = ZXING;
      s.onload = function () { ok(window.ZXing); };
      s.onerror = function () { mal(new Error("No se pudo cargar el lector.")); };
      document.head.appendChild(s);
    });
  }

  function leido(input, codigo) {
    if (navigator.vibrate) navigator.vibrate(80);
    bootstrap.Modal.getOrCreateInstance(modal).hide();
    input.value = codigo;
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true, cancelable: true}));
    input.focus();
  }

  function conNativo(input) {
    var det = new window.BarcodeDetector({formats: FORMATOS});
    var vivo = true;
    detener = function () { vivo = false; };
    (function mirar() {
      if (!vivo) return;
      det.detect(video).then(function (r) {
        if (vivo && r.length) { vivo = false; leido(input, r[0].rawValue); } else setTimeout(mirar, 150);
      }).catch(function () { setTimeout(mirar, 300); });
    })();
  }

  function conZxing(input) {
    return cargarZxing().then(function (Z) {
      var lector = new Z.BrowserMultiFormatReader();
      detener = function () { lector.reset(); };
      lector.decodeFromVideoElementContinuously(video, function (r) {
        if (r && detener) { detener(); detener = null; leido(input, r.getText()); }
      });
    });
  }

  function abrir(input) {
    crearModal();
    aviso.textContent = "Apunta al código de barras del producto.";
    bootstrap.Modal.getOrCreateInstance(modal).show();
    navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}, audio: false}).then(function (stream) {
      video.srcObject = stream;
      return video.play();
    }).then(function () {
      var nativo = window.BarcodeDetector && BarcodeDetector.getSupportedFormats ?
        BarcodeDetector.getSupportedFormats().then(function (f) { return f.indexOf("ean_13") >= 0; }) : Promise.resolve(false);
      return nativo.then(function (si) { return si ? conNativo(input) : conZxing(input); });
    }).catch(function (e) {
      parar();
      aviso.textContent = e && e.name === "NotAllowedError" ? "Permite el uso de la cámara para escanear (en el candado de la barra de direcciones)."
        : e && e.name === "NotFoundError" ? "Este equipo no tiene cámara." : "No se pudo abrir la cámara.";
    });
  }

  function poner(input) {
    if (input.dataset.escanerListo) return;
    input.dataset.escanerListo = "1";
    var b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-outline-secondary";
    b.title = "Escanear con la cámara";
    b.setAttribute("aria-label", "Escanear con la cámara");
    b.innerHTML = '<i class="bi bi-camera"></i>';
    b.addEventListener("click", function () { abrir(input); });
    var grupo = input.closest(".input-group");
    if (!grupo) {  // campo suelto (formulario): se envuelve en un grupo para poner el botón al lado
      grupo = document.createElement("div");
      grupo.className = "input-group";
      input.parentNode.insertBefore(grupo, input);
      grupo.appendChild(input);
    }
    grupo.appendChild(b);
  }

  function buscar() { document.querySelectorAll("input[data-escaner]").forEach(poner); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", buscar); else buscar();
  document.addEventListener("htmx:afterSwap", buscar);
  window.Escaner = {abrir: abrir};
})();
