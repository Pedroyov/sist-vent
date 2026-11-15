/* Cuadro de cobro compartido (punto de venta y mesas).
   Cobro.abrir({total: centimos, titulo, detalle, nota, onConfirmar: function (datos, terminar) {}})
   datos = {pagos: [{metodo, monto}], propina: "0.00", cliente_nombre, cliente_documento, nota, liberar}
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
  var actual = null, cliente = null, buscando = null;
  var soloSoles = function (t) { return "S/ " + parseFloat(t || 0).toFixed(2); };

  // ---------- cliente ----------
  function mostrarCliente() {
    var hay = !!cliente, el = $("c-cli-elegido");
    if (!el) return;
    el.classList.toggle("d-none", !hay); el.classList.toggle("d-flex", hay);
    $("c-cli-buscar").classList.toggle("d-none", hay);
    $("c-cli-ayuda").classList.toggle("d-none", hay);
    $("c-nombre").closest(".col-8").classList.toggle("d-none", hay);
    $("c-doc").closest(".col-4").classList.toggle("d-none", hay);
    if (hay) {
      $("c-cli-nombre").textContent = cliente.n;
      $("c-cli-info").textContent = [cliente.doc, parseFloat(cliente.saldo) > 0 ? "debe " + soloSoles(cliente.saldo) : "",
        parseFloat(cliente.limite) > 0 ? "límite " + soloSoles(cliente.limite) : ""].filter(Boolean).join(" · ");
    }
  }
  function elegir(c) { cliente = c; $("c-cli-q").value = ""; $("c-cli-res").innerHTML = ""; mostrarCliente(); estado(); }
  if ($("c-cli-q")) {
    $("c-cli-q").addEventListener("input", function () {
      var q = this.value.trim(), url = this.dataset.url;
      clearTimeout(buscando);
      if (q.length < 2) { $("c-cli-res").innerHTML = ""; return; }
      buscando = setTimeout(function () {
        fetch(url + "?q=" + encodeURIComponent(q), {credentials: "same-origin"}).then(function (r) { return r.json(); }).then(function (d) {
          $("c-cli-res").innerHTML = (d.resultados || []).map(function (c, i) {
            return '<button type="button" class="list-group-item list-group-item-action py-2" data-i="' + i + '"><strong>' + esc(c.n) + "</strong>" +
              '<span class="small text-body-secondary ms-2">' + esc(c.doc) + "</span>" +
              (parseFloat(c.saldo) > 0 ? '<span class="badge text-bg-warning float-end">debe ' + soloSoles(c.saldo) + "</span>" : "") + "</button>";
          }).join("") || '<div class="list-group-item small text-body-secondary">No se encontró. Escríbelo abajo para registrarlo.</div>';
          $("c-cli-res").resultados = d.resultados || [];
        });
      }, 250);
    });
    $("c-cli-res").addEventListener("click", function (e) {
      var b = e.target.closest("[data-i]");
      if (b) elegir(this.resultados[parseInt(b.dataset.i, 10)]);
    });
    $("c-cli-quitar").addEventListener("click", function () { cliente = null; mostrarCliente(); estado(); });
  }
  function abrirCliente(enfocar) {
    bootstrap.Collapse.getOrCreateInstance($("c-cliente"), {toggle: false}).show();
    if (enfocar && $("c-cli-q") && !cliente) setTimeout(function () { $("c-cli-q").focus(); }, 250);
  }

  function descuento() {
    if (!actual || !actual.descuento) return 0;
    var v = parseFloat(String($("c-desc").value).replace(",", "."));
    if (!isFinite(v) || v <= 0) return 0;
    var c = $("c-desc-tipo").value === "P" ? Math.round(actual.total * Math.min(v, 100) / 100) : Math.round(v * 100);
    return Math.min(c, actual.total);
  }
  function neto() { return actual.total - descuento(); }
  function propina() { return CON_PROPINA ? cent($("c-propina").value) : 0; }
  function aCobrar() { return neto() + propina(); }
  // ---------- partes iguales (mesas): cada persona paga su parte con su método ----------
  var partes = {n: 0, filas: []};
  var CON_PARTES = METODOS.filter(function (m) { return m.id !== "CRE"; });
  function cuotas() {  // en céntimos; se redondea a 10 céntimos y la última parte cuadra la diferencia
    var t = aCobrar(), n = partes.n, base = Math.floor(t / n / 10) * 10, r = [];
    for (var i = 0; i < n; i++) r.push(i === n - 1 ? t - base * (n - 1) : base);
    return r;
  }
  function pagosPartes() {
    var q = cuotas();
    return partes.filas.slice(0, partes.n).map(function (f, i) { return {metodo: f.metodo, c: f.metodo === "EFE" && f.con ? f.con : q[i]}; });
  }
  function pintarPartes() {
    if (!partes.n) return;
    while (partes.filas.length < partes.n) partes.filas.push({metodo: "EFE", con: 0});
    $("c-np").value = partes.n;
    var q = cuotas();
    $("c-partes-lista").innerHTML = q.map(function (c, i) {
      var f = partes.filas[i];
      return '<div class="border-top py-2" data-parte="' + i + '">' +
        '<div class="d-flex align-items-center"><span class="fw-semibold">Persona ' + (i + 1) + '</span><span class="ms-auto fs-5 fw-bold">' + soles(c) + "</span></div>" +
        '<div class="d-flex flex-wrap gap-1 mt-1">' + CON_PARTES.map(function (m) {
          return '<button type="button" class="btn btn-sm ' + (f.metodo === m.id ? "btn-primary" : "btn-outline-secondary") + '" data-pmetodo="' + m.id + '">' + esc(m.n) + "</button>";
        }).join("") + "</div>" +
        (f.metodo === "EFE" ? '<div class="d-flex align-items-center gap-2 mt-1"><div class="input-group input-group-sm" style="max-width: 11rem"><span class="input-group-text">Paga con</span>' +
          '<input type="number" class="form-control text-end" data-pcon min="0" step="0.10" inputmode="decimal" placeholder="' + (c / 100).toFixed(2) + '" value="' + (f.con ? (f.con / 100).toFixed(2) : "") + '"></div>' +
          '<span class="small" data-pvuelto></span></div>' : "") +
        "</div>";
    }).join("");
    vueltosPartes();
  }
  function vueltosPartes() {
    var q = cuotas();
    $("c-partes-lista").querySelectorAll("[data-parte]").forEach(function (el) {
      var i = parseInt(el.dataset.parte, 10), f = partes.filas[i], v = el.querySelector("[data-pvuelto]");
      if (!v) return;
      if (!f.con) v.textContent = "";
      else if (f.con < q[i]) { v.className = "small text-danger"; v.textContent = "falta " + soles(q[i] - f.con); }
      else { v.className = "small text-success fw-semibold"; v.textContent = "vuelto " + soles(f.con - q[i]); }
    });
  }
  function modoPartes(n) {
    partes.n = n;
    if (!n) partes.filas = [];
    $("c-partes").classList.toggle("d-none", !n);
    $("c-partes-btn-fila").classList.toggle("d-none", !!n || !(actual && actual.partes));
    $("c-metodos").classList.toggle("d-none", !!n);
    $("c-billetes").classList.toggle("d-none", !!n);
    pintarPartes();
    estado();
  }

  function pagos() {
    if (partes.n) return pagosPartes();
    return Array.prototype.map.call(modal.querySelectorAll("[data-metodo]"), function (i) { return {metodo: i.dataset.metodo, c: cent(i.value)}; });
  }
  function billetes() {
    if (partes.n) pintarPartes();
    var t = aCobrar();
    var sugeridos = BILLETES.filter(function (b) { return b * 100 > t; }).slice(0, 3);
    $("c-billetes").innerHTML = '<span class="small text-body-secondary me-1 align-self-center">Efectivo:</span>' +
      '<button type="button" class="btn btn-sm btn-outline-success" data-billete="exacto">Exacto</button>' +
      sugeridos.map(function (b) { return '<button type="button" class="btn btn-sm btn-outline-success" data-billete="' + b * 100 + '">S/ ' + b + "</button>"; }).join("");
  }
  function estado() {
    var t = aCobrar(), ps = pagos(), e = $("c-estado");
    $("c-total").textContent = soles(t);
    var partes = [];
    if (descuento()) partes.push("Consumo " + soles(actual.total) + " − desc. " + soles(descuento()));
    if (propina()) partes.push((descuento() ? "" : "Consumo " + soles(actual.total)) + " + propina " + soles(propina()));
    $("c-detalle").textContent = partes.length ? partes.join(" ") : (actual.detalle || "Total a cobrar");
    if (actual.descuento) {
      $("c-desc-extra").classList.toggle("d-none", !descuento());
      $("c-desc-sup").classList.toggle("d-none", !descuento() || actual.descuento.puede);
    }
    var pagado = ps.reduce(function (a, p) { return a + p.c; }, 0);
    var efectivo = ps.filter(function (p) { return p.metodo === "EFE"; }).reduce(function (a, p) { return a + p.c; }, 0);
    if (descuento() && !$("c-desc-motivo").value.trim()) {
      e.className = "alert alert-warning py-2 text-center mb-3"; e.textContent = "Escribe el motivo del descuento."; $("c-confirmar").disabled = true; return false;
    }
    if (descuento() && !actual.descuento.puede && (!$("c-sup-usuario").value.trim() || !$("c-sup-clave").value)) {
      e.className = "alert alert-warning py-2 text-center mb-3"; e.innerHTML = '<i class="bi bi-shield-lock"></i> El descuento lo autoriza un supervisor con su clave.'; $("c-confirmar").disabled = true; return false;
    }
    var fiado = ps.filter(function (p) { return p.metodo === "CRE"; }).reduce(function (a, p) { return a + p.c; }, 0);
    var ok = false;
    if (fiado && !cliente && !$("c-nombre").value.trim()) { e.className = "alert alert-warning py-2 text-center mb-3"; e.innerHTML = '<i class="bi bi-person-exclamation"></i> Para fiar, elige o escribe el cliente.'; $("c-confirmar").disabled = true; return false; }
    if (fiado && cliente && parseFloat(cliente.limite) > 0 && (parseFloat(cliente.saldo) * 100 + fiado) > parseFloat(cliente.limite) * 100) {
      e.className = "alert alert-danger py-2 text-center mb-3"; e.textContent = "Supera su límite de fiado (" + soloSoles(cliente.limite) + "). Solo con permiso especial.";
      $("c-confirmar").disabled = false; return true;
    }
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
  function ayudaLiberar() {
    var l = actual && actual.liberar;
    if (!l) return;
    $("c-liberar-ayuda").textContent = $("c-liberar").checked ? l.si : l.no;
  }
  function abrir(opciones) {
    actual = opciones;
    // Mesas: ¿se libera al cobrar? {valor, texto, si, no}
    $("c-liberar-fila").classList.toggle("d-none", !opciones.liberar);
    if (opciones.liberar) { $("c-liberar").checked = !!opciones.liberar.valor; $("c-liberar-texto").textContent = opciones.liberar.texto; ayudaLiberar(); }
    $("c-titulo").textContent = opciones.titulo || "Cobrar";
    $("c-detalle").textContent = opciones.detalle || "Total a cobrar";
    $("c-propina-fila").classList.toggle("d-none", !CON_PROPINA);
    $("c-desc-fila").classList.toggle("d-none", !opciones.descuento);
    $("c-desc").value = ""; $("c-desc-motivo").value = ""; $("c-sup-usuario").value = ""; $("c-sup-clave").value = "";
    $("c-propina").value = "";
    $("c-nota").value = opciones.nota || "";
    $("c-nombre").value = ""; $("c-doc").value = "";
    cliente = opciones.cliente || null;
    mostrarCliente();
    $("c-metodos").innerHTML = METODOS.map(function (m) {
      return '<div class="input-group mb-2"><span class="input-group-text" style="width: 8.5rem">' + esc(m.n) + "</span>" +
        '<input type="number" class="form-control text-end fs-5" data-metodo="' + m.id + '" min="0" step="0.10" inputmode="decimal" placeholder="0.00">' +
        '<button type="button" class="btn btn-outline-secondary" data-todo="' + m.id + '">Todo</button></div>';
    }).join("");
    $("c-error").classList.add("d-none");
    partes = {n: 0, filas: []};
    modoPartes(0);
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
      descuento: (descuento() / 100).toFixed(2), descuento_motivo: $("c-desc-motivo").value,
      sup_usuario: $("c-sup-usuario").value, sup_clave: $("c-sup-clave").value,
      cliente_id: cliente ? cliente.id : null,
      cliente_nombre: cliente ? "" : $("c-nombre").value, cliente_documento: cliente ? "" : $("c-doc").value, nota: $("c-nota").value,
      liberar: actual.liberar ? $("c-liberar").checked : true,
      partes: partes.n
    }, function (error) {
      boton(false);
      if (error) { $("c-error").textContent = error; $("c-error").classList.remove("d-none"); }
    });
  }

  modal.addEventListener("shown.bs.modal", function () { var i = modal.querySelector('[data-metodo="EFE"]'); if (i) i.focus(); });
  $("c-metodos").addEventListener("input", estado);
  $("c-partes-btn").addEventListener("click", function () { modoPartes(Math.max(2, (actual.partes && actual.partes.n) || 2)); });
  $("c-partes-salir").addEventListener("click", function () { modoPartes(0); });
  $("c-partes").addEventListener("click", function (e) {
    var b = e.target.closest("[data-np]");
    if (b) { modoPartes(Math.min(30, Math.max(2, partes.n + parseInt(b.dataset.np, 10)))); return; }
    b = e.target.closest("[data-pmetodo]");
    if (b) {
      var f = partes.filas[parseInt(b.closest("[data-parte]").dataset.parte, 10)];
      f.metodo = b.dataset.pmetodo; f.con = 0;
      pintarPartes(); estado();
    }
  });
  $("c-partes").addEventListener("input", function (e) {
    if (!e.target.hasAttribute("data-pcon")) return;
    partes.filas[parseInt(e.target.closest("[data-parte]").dataset.parte, 10)].con = cent(e.target.value);
    vueltosPartes(); estado();
  });
  $("c-liberar").addEventListener("change", ayudaLiberar);
  $("c-propina").addEventListener("input", function () { billetes(); estado(); });
  ["c-desc", "c-desc-tipo", "c-desc-motivo", "c-sup-usuario", "c-sup-clave"].forEach(function (id) {
    $(id).addEventListener("input", function () { billetes(); estado(); });
    $(id).addEventListener("change", function () { billetes(); estado(); });
  });
  $("c-propina-fila").addEventListener("click", function (e) {
    var b = e.target.closest("[data-pct]");
    if (!b) return;
    $("c-propina").value = (Math.round(neto() * parseInt(b.dataset.pct, 10) / 100 / 10) / 10).toFixed(2);
    billetes(); estado();
  });
  $("c-metodos").addEventListener("click", function (e) {
    var b = e.target.closest("[data-todo]");
    if (!b) return;
    poner(b.dataset.todo, aCobrar());
    if (b.dataset.todo === "CRE") abrirCliente(true);
  });
  $("c-metodos").addEventListener("focusin", function (e) { if (e.target.dataset.metodo === "CRE") abrirCliente(false); });
  $("c-nombre").addEventListener("input", estado);
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
