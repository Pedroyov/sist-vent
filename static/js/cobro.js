/* Cuadro de cobro compartido (punto de venta y mesas).
   Cobro.abrir({total: centimos, titulo, detalle, nota, onConfirmar: function (datos, terminar) {}})
   datos = {pagos: [{metodo, monto}], propina: "0.00", cliente_nombre, cliente_documento, nota}
   terminar(mensajeError) vuelve a habilitar el botón y muestra el error (si lo hay). */
window.Cobro = (function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var modal = $("m-cobro");
  if (!modal) return null;
  var METODOS = JSON.parse(modal.dataset.metodos);
  var CON_PROPINA = modal.dataset.propina === "1";
  var BILLETES = [10, 20, 50, 100, 200];
  var cent = function (t) { var n = parseFloat(String(t).replace(",", ".")); return isFinite(n) && n > 0 ? Math.round(n * 100) : 0; };
  var soles = function (c) { return "S/ " + (c / 100).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
  var esc = function (s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
  var actual = null;

  function propina() { return CON_PROPINA ? cent($("c-propina").value) : 0; }
  function aCobrar() { return actual.total + propina(); }
  function pagos() {
    return Array.prototype.map.call(modal.querySelectorAll("[data-metodo]"), function (i) { return {metodo: i.dataset.metodo, c: cent(i.value)}; });
  }
  function billetes() {
    var t = aCobrar();
    var sugeridos = BILLETES.filter(function (b) { return b * 100 > t; }).slice(0, 3);
    $("c-billetes").innerHTML = '<span class="small text-body-secondary me-1 align-self-center">Efectivo:</span>' +
      '<button type="button" class="btn btn-sm btn-outline-success" data-billete="exacto">Exacto</button>' +
      sugeridos.map(function (b) { return '<button type="button" class="btn btn-sm btn-outline-success" data-billete="' + b * 100 + '">S/ ' + b + "</button>"; }).join("");
  }
  function estado() {
    var t = aCobrar(), ps = pagos();
    $("c-total").textContent = soles(t);
    $("c-detalle").textContent = propina() ? "Consumo " + soles(actual.total) + " + propina " + soles(propina()) : (actual.detalle || "Total a cobrar");
    var pagado = ps.reduce(function (a, p) { return a + p.c; }, 0);
    var efectivo = ps.filter(function (p) { return p.metodo === "EFE"; }).reduce(function (a, p) { return a + p.c; }, 0);
    var e = $("c-estado"), ok = false;
    if (pagado === 0) { e.className = "alert alert-secondary py-2 text-center mb-3"; e.innerHTML = "Escribe cuánto paga, o pulsa <strong>Confirmar</strong> si es efectivo exacto."; ok = true; }
    else if (pagado < t) { e.className = "alert alert-warning py-2 text-center fs-5 mb-3"; e.innerHTML = "Falta <strong>" + soles(t - pagado) + "</strong>"; }
    else if (pagado - t > efectivo) { e.className = "alert alert-danger py-2 text-center mb-3"; e.textContent = "El vuelto solo puede salir del efectivo: revisa los montos."; }
    else if (pagado > t) { e.className = "alert alert-success py-2 text-center fs-4 mb-3"; e.innerHTML = "Vuelto: <strong>" + soles(pagado - t) + "</strong>"; ok = true; }
    else { e.className = "alert alert-success py-2 text-center fs-5 mb-3"; e.innerHTML = '<i class="bi bi-check-circle"></i> Pago completo'; ok = true; }
    $("c-confirmar").disabled = !ok;
    return ok;
  }
  function boton(cargando) {
    var b = $("c-confirmar");
    b.disabled = cargando;
    b.innerHTML = cargando ? '<span class="spinner-border spinner-border-sm me-1"></span>Guardando…' : '<i class="bi bi-check-lg me-1"></i>Confirmar';
  }
  function abrir(opciones) {
    actual = opciones;
    $("c-titulo").textContent = opciones.titulo || "Cobrar";
    $("c-detalle").textContent = opciones.detalle || "Total a cobrar";
    $("c-propina-fila").classList.toggle("d-none", !CON_PROPINA);
    $("c-propina").value = "";
    $("c-nota").value = opciones.nota || "";
    $("c-metodos").innerHTML = METODOS.map(function (m) {
      return '<div class="input-group mb-2"><span class="input-group-text" style="width: 8.5rem">' + esc(m.n) + "</span>" +
        '<input type="number" class="form-control text-end fs-5" data-metodo="' + m.id + '" min="0" step="0.10" inputmode="decimal" placeholder="0.00">' +
        '<button type="button" class="btn btn-outline-secondary" data-todo="' + m.id + '">Todo</button></div>';
    }).join("");
    $("c-error").classList.add("d-none");
    boton(false);
    billetes();
    estado();
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }
  function poner(metodo, centimos) {
    modal.querySelectorAll("[data-metodo]").forEach(function (i) { i.value = i.dataset.metodo === metodo ? (centimos / 100).toFixed(2) : ""; });
    estado();
  }
  function confirmar() {
    if (!actual || !estado()) return;
    var ps = pagos();
    if (ps.every(function (p) { return p.c === 0; })) ps = [{metodo: "EFE", c: aCobrar()}];
    boton(true);
    actual.onConfirmar({
      pagos: ps.filter(function (p) { return p.c > 0; }).map(function (p) { return {metodo: p.metodo, monto: (p.c / 100).toFixed(2)}; }),
      propina: (propina() / 100).toFixed(2),
      cliente_nombre: $("c-nombre").value, cliente_documento: $("c-doc").value, nota: $("c-nota").value
    }, function (error) {
      boton(false);
      if (error) { $("c-error").textContent = error; $("c-error").classList.remove("d-none"); }
    });
  }

  modal.addEventListener("shown.bs.modal", function () { var i = modal.querySelector('[data-metodo="EFE"]'); if (i) i.focus(); });
  $("c-metodos").addEventListener("input", estado);
  $("c-propina").addEventListener("input", function () { billetes(); estado(); });
  $("c-propina-fila").addEventListener("click", function (e) {
    var b = e.target.closest("[data-pct]");
    if (!b) return;
    $("c-propina").value = (Math.round(actual.total * parseInt(b.dataset.pct, 10) / 100 / 10) / 10).toFixed(2);
    billetes(); estado();
  });
  $("c-metodos").addEventListener("click", function (e) { var b = e.target.closest("[data-todo]"); if (b) poner(b.dataset.todo, aCobrar()); });
  $("c-billetes").addEventListener("click", function (e) {
    var b = e.target.closest("[data-billete]");
    if (b) poner("EFE", b.dataset.billete === "exacto" ? aCobrar() : parseInt(b.dataset.billete, 10));
  });
  $("f-cobro").addEventListener("submit", function (e) { e.preventDefault(); confirmar(); });

  /* Envía un JSON con el token CSRF y devuelve la respuesta ya leída. */
  function enviar(url, cuerpo) {
    var csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
    return fetch(url, {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRFToken": csrf}, body: JSON.stringify(cuerpo)})
      .then(function (r) { return r.json().catch(function () { return {error: "Error del servidor (" + r.status + ")."}; }); })
      .catch(function () { return {error: "Sin conexión. Revisa el internet y vuelve a intentar: no se cobrará dos veces."}; });
  }
  return {abrir: abrir, enviar: enviar, cerrar: function () { bootstrap.Modal.getOrCreateInstance(modal).hide(); }};
})();
