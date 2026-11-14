/* Elegir variante (tamaño, talla…) y opciones (término, acompañamiento, adicionales) de un producto del catálogo.
   Opciones.elegir(producto, function (sel) { sel = {vid, ops: [ids], extra: centimos, txt: "Término medio, + Huevo"} })
   Si el producto no tiene nada que elegir, llama de inmediato. */
window.Opciones = (function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var modal = $("m-opciones");
  var esc = function (s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; };
  var cent = function (t) { return Math.round(parseFloat(t || 0) * 100); };
  var soles = function (c) { return "S/ " + (c / 100).toFixed(2); };
  var actual = null, listo = null;

  function grupos(p) { return (p.g || []).filter(function (g) { return g.o && g.o.length; }); }

  function elegir(p, alListo) {
    if (p.ag) { alert(p.n + " está agotado hoy."); return; }
    var gs = grupos(p);
    var disponibles = p.v.filter(function (v) { return true; });
    if (disponibles.length === 1 && !gs.length) { alListo({vid: disponibles[0].id, ops: [], extra: 0, txt: ""}); return; }
    actual = p; listo = alListo;
    $("op-titulo").textContent = p.n;
    var html = "";
    if (p.v.length > 1) {
      html += '<div class="mb-3"><div class="fw-semibold mb-1">Elige una opción <span class="badge text-bg-secondary">obligatorio</span></div><div class="row g-2">';
      p.v.forEach(function (v, i) {
        var sinStock = v.st !== null && v.st !== undefined && parseFloat(v.st) <= 0;
        html += '<div class="col-6"><input type="radio" class="btn-check" name="op-var" id="op-v' + v.id + '" value="' + v.id + '"' + (i === 0 ? " checked" : "") + '>' +
          '<label class="btn btn-outline-primary w-100 py-2" for="op-v' + v.id + '"><div class="fw-semibold">' + esc(v.n) + "</div><div>" + soles(cent(v.p)) + "</div>" +
          (v.st !== null && v.st !== undefined ? '<div class="small ' + (sinStock ? "text-danger" : "opacity-75") + '">stock: ' + esc(v.st) + "</div>" : "") + "</label></div>";
      });
      html += "</div></div>";
    }
    gs.forEach(function (g) {
      var unico = g.max === 1;
      html += '<div class="mb-3" data-grupo="' + g.id + '" data-min="' + g.min + '" data-max="' + g.max + '">' +
        '<div class="fw-semibold mb-1">' + esc(g.n) + ' <span class="badge ' + (g.min ? "text-bg-danger" : "text-bg-light border") + '">' + esc(g.r) + "</span></div>" +
        '<div class="d-flex flex-wrap gap-2">';
      g.o.forEach(function (o) {
        html += '<input type="' + (unico ? "radio" : "checkbox") + '" class="btn-check" name="op-g' + g.id + '" id="op-o' + o.id + '" value="' + o.id + '"' + (o.ag ? " disabled" : "") + ">" +
          '<label class="btn btn-outline-secondary' + (o.ag ? " text-decoration-line-through" : "") + '" for="op-o' + o.id + '">' + esc(o.n) +
          (cent(o.p) ? ' <span class="small opacity-75">+' + soles(cent(o.p)) + "</span>" : "") + (o.ag ? ' <span class="small">(agotado)</span>' : "") + "</label>";
      });
      html += "</div></div>";
    });
    $("op-cuerpo").innerHTML = html;
    revisar();
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  function leer() {
    var p = actual, vEl = modal.querySelector("input[name=op-var]:checked");
    var v = vEl ? p.v.find(function (x) { return String(x.id) === vEl.value; }) : p.v[0];
    var ops = [], txt = [], extra = 0, falta = "";
    grupos(p).forEach(function (g) {
      var marcadas = Array.prototype.slice.call(modal.querySelectorAll('[data-grupo="' + g.id + '"] input:checked'));
      if (marcadas.length < g.min) falta = falta || ("Falta elegir: " + g.n.toLowerCase());
      if (g.max && marcadas.length > g.max) falta = falta || ("En " + g.n.toLowerCase() + " solo " + g.max);
      marcadas.forEach(function (m) {
        var o = g.o.find(function (x) { return String(x.id) === m.value; });
        ops.push(o.id); txt.push(o.n); extra += cent(o.p);
      });
    });
    return {v: v, ops: ops, txt: txt.join(", "), extra: extra, falta: falta};
  }

  function revisar(e) {
    // en grupos de varios con máximo, no deja marcar de más
    if (e && e.target.type === "checkbox") {
      var caja = e.target.closest("[data-grupo]"), max = parseInt(caja.dataset.max, 10);
      if (max && caja.querySelectorAll("input:checked").length > max) e.target.checked = false;
    }
    var s = leer();
    $("op-precio").textContent = soles(cent(s.v.p) + s.extra);
    $("op-falta").textContent = s.falta;
    $("op-agregar").disabled = !!s.falta;
  }

  if (modal) {
    modal.addEventListener("change", revisar);
    $("op-agregar").addEventListener("click", function () {
      var s = leer();
      if (s.falta) return;
      bootstrap.Modal.getInstance(modal).hide();
      listo({vid: s.v.id, ops: s.ops, extra: s.extra, txt: s.txt});
    });
  }
  return {elegir: elegir};
})();
