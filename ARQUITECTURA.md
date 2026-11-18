# Arquitectura del sistema (guía para reutilizar esta base)

Este documento resume cómo está hecho el sistema. Sirve para empezar otro proyecto sobre esta misma base: compártelo al inicio de la nueva conversación.

## Reglas para construir (leer antes de cada cambio)

El sistema sirve a varios tipos de negocio (tienda, restaurante, peluquería, academia…). Antes de agregar algo:

1. **¿Quién más lo usaría?** Pensar en todos los rubros, no solo en el que lo pidió.
2. **¿Es un dato común o propio del rubro?** Lo común va en la **base** y lo usan todos los módulos: negocio y usuarios (`core`), **personal** (`personal`), clientes, productos, ventas, caja, reportes. Lo propio de un rubro va en un **módulo opcional** que se apoya en la base (mesas, citas, cuotas, reservas). Nunca duplicar en un módulo un dato que ya existe en la base (ej.: el "profesional" de Citas es una Persona del Personal).
3. **¿Se puede apagar sin romper nada?** Lo avanzado empieza apagado: módulos en `MODULOS`, funciones en `core/rubros.FUNCIONES` (`Ajustes.usa_x`). En sistemas ya en uso, lo nuevo se apaga con una migración de datos.
4. **¿Cambian las palabras según el rubro?** Se resuelve con el glosario (`core/glosario.py`), no con pantallas duplicadas.
5. **Pantallas y reportes únicos que se adaptan**: una pantalla o un reporte muestra solo las columnas y campos de lo que el negocio usa (ej.: el reporte de Personal), en vez de un reporte por módulo.
6. **¿Qué pasa con los datos existentes?** Migración que los conserva (y prueba de migración con una base con datos).
7. Proponer siempre la opción recomendada con su porqué y las alternativas.

## Tecnología

- **Django 5.2** en Python 3.12, con **SQLite** en desarrollo y PostgreSQL recomendado en producción (`DATABASE_URL` en `.env`, vía django-environ).
- **Interfaz:** AdminLTE 4, Bootstrap 5, Bootstrap Icons y HTMX. Todo va guardado en `static/vendor`, sin depender de servicios externos.
- **Formularios:** django-crispy-forms con crispy-bootstrap5.
- **Excel:** openpyxl. **Imágenes:** Pillow.
- **Archivos estáticos:** whitenoise. **Servidor de producción:** gunicorn.
- **App para celular (PWA):** manifest dinámico (`core.views.manifest`) y un service worker que solo guarda en el celular los archivos estáticos y la página sin conexión. Nunca guarda datos.
- **Idioma:** español, `LANGUAGE_CODE="es"`, formatos propios en `config/formats/es` (decimal con punto, sin separador de miles en números). Para mostrar montos se usa el filtro `|soles` (S/ 1,234.50).

## Estructura

| Carpeta | Qué contiene |
| --- | --- |
| `config/` | settings (todo por `.env`), urls, formatos |
| `core/` | Base reutilizable: datos del negocio y rubro (`Ajustes`), usuarios, **roles y permisos**, **módulos activos**, inicio (`tablero.py`), archivos privados, PWA, utilidades |
| `personal/` | Base: **Personal** (quienes trabajan, con o sin usuario: color, comisión, reparte, atiende citas, servicios). Reporte único de Personal (`personal/reportes.py`) |
| `productos/` | Catálogo: categorías, productos y servicios, variantes (talla/color/tamaño), stock y kardex, importar y exportar Excel, catálogos de ejemplo por rubro |
| `ventas/` | Punto de venta, registro y anulación de ventas, ticket, lista y resumen del día, Excel |
| `caja/` | Turnos de caja: apertura, ingresos y egresos, cierre con arqueo por billetes, historial |
| `mesas/` | Restaurantes: zonas y mesas, cuentas abiertas, pedidos con notas, envío a cocina, precuenta, comanda, cambiar y juntar mesas, cobro total o dividido |
| `clientes/` | Clientes (DNI/RUC validados), ventas al fiado con límite, pagos de deudas, estado de cuenta, recordatorio por WhatsApp |
| `facturacion/` | Boletas, facturas y notas de crédito electrónicas: configuración, series, cálculo de IGV, conectores con el proveedor (Prueba y Nubefact), reenvío de pendientes |
| `reportes/` | Reportes sin tablas propias: resumen con comparación, por día/hora/semana, productos, categorías, personal, mesas, inventario, deudores y control; Excel |
| `templates/` | `base.html`, `partials/` (sidebar, navbar, mensajes, modal eliminar), `registration/` (login) y `core/` |

Las demás apps del negocio (ventas, caja, clientes, etc.) se crean como apps nuevas de Django, una por módulo.

## Facturación electrónica

- **Módulo `facturacion`** (empieza apagado). Configuración en Configuración → Facturación (`facturacion.configurar`): proveedor, ruta y token, IGV (18 por defecto, editable), si los precios son gravados/exonerados/inafectos, series (B001, F001, BC01, FC01) y qué proponer al cobrar. Necesita RUC y razón social en Datos del negocio.
- **Al cobrar** (punto de venta y mesas) se elige Nota de venta / Boleta / Factura en el mismo cuadro (`cobro.js`: valida RUC con dígito verificador, razón social y dirección para factura, DNI en boletas de más de S/ 700). El servidor: `preparar()` revisa antes de vender; `registrar_venta` y `crear()` van en **una sola transacción** (si el comprobante no se puede armar, la venta no se guarda); `enviar_seguro()` va **fuera**: si no hay internet la venta queda hecha y el comprobante **pendiente**.
- **IGV por línea**, como lo valida SUNAT (precio con IGV / 1.18); el descuento de la venta se reparte entre las líneas; las cortesías (S/ 0) no van; la propina no es venta. Unidades: NIU, ZZ (servicios), KGM, LTR, MTR. Numeración con `Serie` bloqueada (`select_for_update`): sin números repetidos.
- **Conectores** (`conectores.py`): `Prueba` (simula a SUNAT; el ticket dice "PRUEBA - SIN VALOR TRIBUTARIO") y `Nubefact` (API JSON: `generar_comprobante`, `consultar_comprobante`; si responde "ya existe", consulta). Otro proveedor = otra clase con `emitir` y `consultar`.
- **Estados:** Pendiente (no se pudo enviar), Enviado (SUNAT confirma después, típico en boletas), Aceptado, Rechazado. Comprobantes → "Reenviar ahora" (o por cada uno, también desde la venta). Plazo de SUNAT: 3 días.
- **Anular una venta** emite su **nota de crédito** (motivo 01) por la señal `ventas.senales.venta_anulada`: ventas no depende de facturación.
- **Después de cobrar** con nota de venta, desde el ticket se puede emitir la boleta o factura (ventas de los últimos días).
- **Ticket** (`impresion/ticket.html`): nombre y número del comprobante, cliente, op. gravada, IGV, QR en SVG (librería `qrcode`), hash y leyenda de representación impresa.
- **Factura al crédito** (apagada: `Config.credito_activo`, plazo `credito_dias`). Si la factura lleva pagos Fiado, `crear()` guarda `forma_pago="CRE"`, `pendiente` y `cuotas` (`plan_cuotas`: cuotas iguales, la última absorbe el redondeo). `revisar_antes` exige que esté activada y una fecha de pago posterior a hoy. Nubefact recibe `medio_de_pago`, `condiciones_de_pago` y `venta_al_credito` (**verificar los nombres de campo en una prueba real con Nubefact**). La factura se envía a SUNAT al emitirse, no al cobrarse.
- **Excel para el contador** (`facturacion:excel?mes=AAAA-MM`): registro de ventas del mes (notas de crédito en negativo, forma de pago, vence, pendiente) y hoja de incobrables.
- **Series por caja**: `caja.PuntoCaja` puede tener series propias; `serie_para()` las usa (también para notas de crédito) y si están vacías usa las de Config.
- **Pendiente:** cortesías como transferencia gratuita, resumen de anulaciones por comunicación de baja.

## Módulos y menú

- **Base, siempre activa:** configuración (`core`), `productos` y el registro de `ventas`.
- **Módulos** (`core/permisos.MODULOS`: código, nombre, ícono, texto, módulo que necesita) = lo que el negocio **contrató**. Los enciende el superusuario en Configuración → Módulos: `mostrador` (pantalla Vender), `caja`, `mesas`, `cocina` (necesita mesas), `delivery` (independiente: sirve a tiendas), `clientes`, `reportes`, `facturacion`, `cobranzas` (necesita clientes), `reservas`, `citas`. `modulos_activos()` apaga solos los que necesitan uno apagado.
- **Datos del negocio** = **cómo lo usa** el dueño dentro de lo contratado: propina, nivel de detalle de los pedidos, costo de envío, ancho del ticket, impresión automática.
- Un permiso pertenece a un módulo (`PERMISOS`); con el módulo apagado nadie lo tiene. `ventas.vender` es del módulo `mostrador` y `mesas.cocina` del módulo `cocina`. Sin mostrador, el cajero igual ve sus ventas (la lista acepta `mesas.cobrar`).
- `NEGOCIO.cocina_pantalla` y `NEGOCIO.delivery_activo` siguen existiendo, pero ahora se leen de los módulos (migración `core/0008`).
- **Tipo de negocio** (`core/rubros.py`): `PERFILES` dice por rubro qué módulos vienen encendidos, cuáles se ofrecen y qué **funciones avanzadas** (`FUNCIONES`: variantes, combos, servicios, agotados) vienen visibles. `Ajustes.funciones_inactivas` guarda las ocultas (`NEGOCIO.usa_combos`, etc.); ocultar solo quita botones y opciones de creación, nunca datos, y lo que ya existe se sigue viendo (un producto con variantes las muestra). `aplicar()` ajusta al rubro sin apagar lo que está en uso (`en_uso`, `modulo_en_uso`): lo llama Datos del negocio al cambiar de rubro (solo funciones y nivel de pedidos) y Módulos → "Usar lo recomendado" (también módulos, solo el superusuario). Las instalaciones nuevas empiezan como tienda (solo variantes, pedidos simples); la migración `core/0012` deja todo visible en los sistemas que ya estaban en uso.
- **Palabras por rubro** (`core/glosario.py`, `{{ T.productos }}` en plantillas): menú, títulos y botones (Carta, Venta rápida, Mensualidades, Paquetes…). Un rubro nuevo solo agrega sus palabras ahí.
- **Menú lateral** por grupos: *Atención* (mesas y delivery, cocina, vender, caja), *Hoy* (menú del día, agotados), *Gestión* (ventas, clientes, productos, reportes), *Configuración*. Cada encabezado aparece solo si el usuario ve algo debajo.
- Las dependencias van en un solo sentido (mesas → ventas → productos). Para saber si algo está en uso, productos no pregunta a los demás módulos: `productos.servicios.en_uso()` revisa cualquier registro que apunte al objeto.

## Productos (cómo está pensado)

- **Producto** guarda lo común: tipo (producto o servicio), categoría, unidad, precio, costo, si controla stock y el stock mínimo. Un servicio nunca controla stock.
- **Variante** es lo que realmente se vende y se cuenta: tiene su código de barras, su stock y, si hace falta, su propio precio y costo (vacío = los del producto). Un producto sin tallas ni colores tiene **una sola variante sin nombre**, que la interfaz no muestra. Así, ventas siempre trabaja con variantes.
- **MovimientoStock** es el kardex. El stock **solo cambia** con `productos.servicios.mover_stock()` o `ajustar_a()`, que bloquean la fila y anotan el saldo. Las ventas usarán `mover_stock(variante, -cantidad, Tipo.VENTA, referencia="Venta 000123")`. Se permite stock negativo para no trabar la caja.
- **Combos** (`Producto.tipo = C`): no tienen stock propio. `ComboItem` guarda lo que traen fijo (variante + cantidad); lo que se elige (la gaseosa) es un grupo de opciones cuyas `Opcion.variante` apuntan a un producto. `foto_combo()` mete lo que trae en la foto del pedido/venta marcado `"c": True` (la cocina y la comanda lo ven; el ticket, `texto_opciones` y el reporte de opciones no) con `"v"` y `"q"`. Al vender y anular, `consumo(variante, cantidad, foto)` dice qué stock mover, a partir de la foto: si el combo cambia después, las ventas viejas se devuelven bien. Una opción con `variante` también descuenta stock fuera de los combos (ej.: adicional huevo). El costo del combo, si no se escribe, es la suma de lo que trae. Pantalla: tarjeta "Qué trae el combo" en el detalle del producto (`productos:combo`).
- `productos/rubros.py` tiene lo que cambia por rubro: categorías sugeridas, nombres de las variantes y valores por defecto.
- Permisos: `productos.ver`, `productos.editar`, `productos.stock` y `productos.costos`. Quien no tiene `productos.costos` no ve los costos en pantallas ni en el Excel.
- Pruebas: `python manage.py test productos ventas caja mesas`.

## Opciones al pedir y agotados

- **GrupoOpciones** (por ejemplo "Término de la carne": mínimo 1, máximo 1; "Adicionales": mínimo 0, máximo 0 = sin límite) con sus **Opcion** (nombre y precio adicional). Un grupo se asigna a varios productos (`Producto.grupos`). Se administran en Productos → Opciones al pedir, con grupos sugeridos por rubro (`rubros.GRUPOS`).
- `productos.servicios.resolver_opciones()` valida lo elegido (que la opción sea de ese producto, mínimos y máximos, que no esté agotada) y devuelve una **foto** `[{"id", "g", "n", "p"}]` y el precio extra. La venta (`VentaItem.opciones`) y el pedido de mesa (`ItemCuenta.opciones`) guardan esa foto: si mañana cambian las opciones, lo pasado no cambia. El precio del ítem ya incluye los adicionales.
- En pantalla, `static/js/opciones.js` + `productos/partials/modal_opciones.html` muestran el cuadro de variante y opciones (punto de venta y mesas). Los grupos obligatorios van primero (`ordenar_grupos`).
- **Agotados**: `Producto.agotado_en` y `Opcion.agotada_en` valen solo por el día (`agotado_hoy`): al día siguiente vuelven solos. Pantalla `productos:agotados` (permiso `productos.agotar`: Cajero, Vendedor y Cocina). Lo agotado no se puede vender ni pedir, pero lo que ya estaba pedido en una mesa se cobra igual.
- Reportes: "Opciones y adicionales más pedidos", con lo cobrado aparte.

## Nivel de detalle de los pedidos

- `Ajustes.nivel_pedido` (Datos del negocio → Pedidos): **1 Simple** (producto + nota), **2 Con opciones** (grupos de opciones, incluidas, menú del día), **3 Detallado** (además "qué lleva"). Propiedades `usa_opciones` y `usa_lleva`; en plantillas `NEGOCIO.usa_opciones`.
- Se aplica en el servidor (`resolver_opciones` no pide ni guarda opciones en 1, ni quita componentes en 2) y en el catálogo (`_catalogo` no manda `g`/`k`). Las pantallas lo esconden; en el formulario del producto la tarjeta de opciones solo se oculta (sigue enviándose) para no borrar lo que ya estaba configurado.

## Menú del día

- El menú es un **producto normal** de precio fijo ("Menú ejecutivo S/ 15") con grupos de opciones marcados **"cambia cada día"** (`GrupoOpciones.diario`): por defecto "Entrada" y "Segundo", obligatorios.
- **Productos → Menú del día** (`productos:menu`, permiso `productos.menu`, Cajero y Cocina): cada mañana se ponen los platos de hoy. Sacar un plato lo desactiva (`Opcion.activa=False`) sin borrarlo: queda en "platos de otros días" para ponerlo con un toque. Un segundo puede costar más ("Pescado frito +S/ 3"). "Agotado" es el mismo de siempre (vuelve solo mañana).
- "Copiar para WhatsApp" arma el texto del menú (`menu_texto`).
- **Qué lleva el plato** (`Componente`: nombre, `quitable`, `cambiar_con` = grupo de alternativas), editable en el detalle del producto. Al pedir, el cuadro muestra "Lleva": lo fijo con candado, lo quitable en verde (tocar = "SIN …") y lo que se cambia con su grupo dentro del mismo bloque. Quitar viaja como id `"s<pk>"` junto a las opciones y `resolver_opciones` lo guarda en la foto como `{"id": "s12", "g": "Sin", "n": "SIN ENSALADA", "sin": true}`: así sale en la comanda, la cocina, el ticket y el reporte de opciones sin tocar nada más. Base para las recetas: cada componente tendrá luego su insumo y cantidad.
- **Opciones que vienen incluidas** (`Opcion.por_defecto`; en el formulario, un asterisco: «Papas fritas *»): ya aparecen elegidas al pedir y el mozo solo las cambia si el cliente quiere otra cosa. Si un grupo obligatorio llega sin elegir, el servidor pone lo incluido (`resolver_opciones`). Pedir **más** de algo va en Adicionales con precio. `leer_linea_opcion` lee el formato de las líneas (nombre, `| precio`, `*`).
- **Lo obligatorio no traba el pedido** (`minimo_disponible`): si hoy un grupo tiene menos opciones disponibles que su mínimo (no hay entradas, o todas agotadas), se pide solo lo que hay. Vale para todos los grupos, no solo el menú.

## Ventas (cómo está pensado)

- **Venta** (numerada con `Correlativo`, sin saltos), **VentaItem** (guarda nombre, precio de lista, precio cobrado y costo de ese momento) y **Pago** (uno por método; el de efectivo guarda lo que se queda el negocio, y la venta guarda `recibido` y `vuelto`).
- El punto de venta (`templates/ventas/pos.html`) carga el catálogo en JSON y arma el carrito en el navegador; al cobrar envía un JSON a `ventas:registrar`. **El servidor vuelve a validar todo** en `ventas.servicios.registrar_venta()`: precios del catálogo (salvo permiso `ventas.precio`), cantidades enteras si la unidad no es fraccionable, que los pagos cubran el total y que el vuelto salga solo del efectivo.
- Un `token` por carrito evita registrar dos veces la misma venta (doble clic o reintento sin internet).
- Las ventas descuentan stock con `mover_stock(..., VENTA)`. `anular_venta()` lo devuelve con un movimiento de DEVOLUCIÓN. Nada se borra.
- Quien solo tiene `ventas.vender` ve solo **sus** ventas. `ventas.ver` ve todas y los totales.
- El ticket es una "nota de venta" interna, imprimible en 80 mm y enviable por WhatsApp. La factura o boleta electrónica (SUNAT) queda pendiente.

## Caja (cómo está pensado)

- **SesionCaja** es un turno por cajero: solo puede tener una abierta. Cada venta guarda en `sesion_caja` la caja abierta de quien cobra (`caja.servicios.sesion_para_vender`). Si el módulo Caja está activo y en Datos del negocio no se marcó "permitir vender sin caja abierta", sin caja no se cobra.
- **Efectivo esperado** = monto inicial + efectivo de ventas pagadas (el Pago en efectivo ya descuenta el vuelto) + ingresos − egresos. Yape, Plin y tarjeta se muestran, pero no cuentan para el cajón.
- Al **cerrar** se guarda una foto del resumen (`esperado`, `contado`, `diferencia`, `conteo`, `resumen`), así el cierre ya no cambia. Si luego se anula una venta de una caja cerrada, el efectivo devuelto sale como egreso automático de la caja abierta de quien anula.
- Permisos: `caja.usar` (su propia caja) y `caja.ver` (todas, historial, cerrar la de otro).

- **Cajas (puntos de cobro)**: `caja.PuntoCaja` (Caja 1, Barra) con series opcionales de boleta, factura y notas de crédito (vacías = las de `facturacion.Config`). `SesionCaja.punto` dice en cuál se abrió el turno: con varias cajas activas hay que elegir al abrir; con una sola se pone sola; sin ninguna, todo sigue como antes. `facturacion.servicios.serie_para(venta, campo, config)` toma la serie de la caja de la venta, también para la nota de crédito. Pantalla: `caja:puntos` (permiso `config.negocio`).

## Mesas (cómo está pensado)

- **Cuenta** es lo que va consumiendo una mesa (o un pedido para llevar, sin mesa). Solo puede haber una cuenta abierta por mesa. **ItemCuenta** guarda el plato, la cantidad, el precio de ese momento, la nota ("sin cebolla"), cuándo se envió a cocina, si se quitó (con motivo) y con qué venta se cobró.
- Flujo: abrir la mesa → agregar → **enviar a cocina** (la pantalla muestra "Díctale a cocina", y hay una comanda imprimible opcional) → precuenta → **cobrar**. Al cobrar se llama a `registrar_venta()` con los precios del pedido, y la venta guarda el mozo en `atendio`. Para dividir la cuenta se eligen ítems y se cobra varias veces. Cuando no queda nada por cobrar, la mesa se libera.
- El stock baja al cobrar (es una venta normal). Lo que no se envió a cocina se cambia libremente. Lo ya enviado solo se quita con `mesas.anular` y un motivo.
- El mapa se actualiza solo con HTMX cada 8 segundos, para varios mozos con celular.
- El cuadro de cobro es compartido: `templates/ventas/partials/modal_cobro.html` + `static/js/cobro.js` (lo usan el punto de venta y las mesas). La **propina** se activa en Datos del negocio: va en `Venta.propina`, no suma al total vendido y se cobra dentro de los pagos.
- **Pagar antes, al final o pagar y seguir pidiendo:** al cobrar, lo que no se había enviado a cocina se envía en ese momento (nunca se cobra algo que cocina no sabe; la cuenta muestra luego qué dictar o la comanda). El cuadro de cobro trae el interruptor "Liberar la mesa al cobrar": viene apagado si algo no salió de cocina (`falta_de_cocina`). Apagado, la cuenta queda abierta y **pagada** (`Cuenta.pagada()`: nada por cobrar y algo cobrado), en celeste en el mapa: se puede seguir pidiendo (lo nuevo se cobra en otra venta) y se cierra con "Liberar mesa" (`liberar_mesa`). Nunca se libera sola al servir: la gente sigue comiendo.
- **Delivery** (`Cuenta.tipo = DEL`; módulo propio, no necesita Mesas): permisos `delivery.atender`, `delivery.cobrar`, `delivery.anular`. Las vistas de la cuenta (`mesas/views.py`) piden los permisos de Delivery si la cuenta es un delivery y los de Mesas si es una mesa o para llevar (`_puede`, `_exigir`); El menú tiene la entrada **Delivery** (`mesas:pedidos`) siempre que hay permisos de delivery; `_lista(user, c)` devuelve un delivery a esa lista y una mesa al mapa. Desde **Vender**, "Enviar por delivery" manda el carrito en el campo `items` (JSON) del mismo formulario `delivery_nuevo`, que lo pasa al pedido con `_carrito_a_delivery` (precio cambiado solo con `ventas.precio`; en restaurante se envía a cocina) y la cuenta borra el carrito guardado del POS (`?desde_venta=1`). Sin Mesas no hay cocina (`sin_cocina`): lo agregado queda editable con + y − hasta que sale (`salio_delivery` lo marca enviado) y el cobro no manda nada a cocina.
  - Datos: cliente, celular, dirección, referencia y "paga con" (`vuelto_para` calcula el vuelto que lleva el repartidor). Al escribir el celular (`delivery_buscar`) se rellenan el nombre y la última dirección; con el módulo Clientes se crea o actualiza la ficha del cliente (`datos_delivery`).
  - El envío es una línea `ItemCuenta.es_envio` de un producto interno inactivo ("Costo de envío (delivery)", lo crea `_producto_envio`): se cobra y sale en el ticket y los reportes como cualquier venta, pero nace enviado/listo/servido y la cocina y la comanda lo excluyen. `poner_envio` lo cambia mientras no esté cobrado.
  - Estados `estado_envio`: Preparando → En camino (`salio_delivery`, con repartidor) → Entregado (`entregar_delivery`). El pedido se cierra cuando está entregado **y** cobrado, en el orden que sea (pago contra entrega o adelantado). En el cobro, "Ya se entregó el pedido" viene marcado solo si ya se entregó.
  - La precuenta de un delivery es la **hoja del repartidor** (dirección grande, celular, referencia, cuánto cobrar y el vuelto). Reportes → Delivery (sección propia, también sin Mesas) muestra pedidos, ingresos por envío y entregas y tiempo por repartidor.
- **Partes iguales:** en el cuadro de cobro de una mesa (`Cobro.abrir({partes: {n}})`), el total se reparte entre N personas (redondeado a 10 céntimos; la última cuadra) y cada una elige su método y, en efectivo, con cuánto paga y su vuelto. Es **una sola venta** con varios pagos (el servidor los junta por método); la nota dice "pagado en N partes iguales". La precuenta muestra cuánto toca por persona.
- **Cortesías** (`mesas.servicios.cortesia`): un plato, o algunas de sus unidades (la línea se separa en dos), se marca `ItemCuenta.cortesia` con motivo y quién autorizó. Su `subtotal` es 0 y `valor` guarda lo que costaba. Al cobrar pasa a `VentaItem.cortesia` con precio 0 y `precio_lista` intacto (así el reporte sabe cuánto se regaló). Lo nuevo que se pide no se suma a una línea de cortesía.
- **Descuento al cobrar la mesa:** en el cuadro de cobro (S/ o %), con motivo obligatorio; se guarda en `Venta.descuento`, `descuento_motivo` y `descuento_por`.
- **Autorización en el momento** (`core/autorizacion.autorizar`): si quien opera tiene el permiso (`mesas.cortesia`, `ventas.precio`) autoriza él; si no, un supervisor escribe su usuario y clave en el mismo cuadro. 5 intentos fallidos bloquean 15 minutos. Sirve para cualquier acción futura que necesite visto bueno.
- **Mesas juntas** (familias, grupos): `Mesa.unida_a` apunta a la cuenta que la ocupa además de su mesa principal. Una mesa está ocupada si tiene su propia cuenta abierta o si está pegada a una cuenta abierta (`cuenta_de_mesa`). No hace falta "despegarlas" al cerrar: al cobrar o anular, la cuenta deja de estar abierta y todas quedan libres. `unir_mesas` pega mesas libres, `separar_mesa` devuelve una, `mover` cambia la mesa principal (las pegadas se sueltan) y `juntar` une dos cuentas abiertas dejando la mesa de origen pegada a la otra. El título de la cuenta es "Mesa 1 + 7 + 9". Pantalla: `mesas:cambiar` (pestañas Juntar / Cambiarse) y el interruptor "Juntaron varias mesas" al abrir.
- **Dónde se prepara** (`productos.Area`: Cocina, Barra, Lo sirve el mozo): se elige en la categoría y se puede cambiar en un producto (`Producto.area_efectiva`). Al pedir se copia en `ItemCuenta.area`. La pantalla de cocina y la comanda filtran por área (`?area=BAR` para la barra). Lo que sirve el mozo (gaseosas, agua, cerveza) no va a ningún lado: al enviar queda listo al instante, para llevar a la mesa. Las categorías nuevas toman un área sugerida por el nombre (`area_sugerida`).
- **Aviso al mozo:** el mapa compara cada 8 segundos cuántas cosas listas hay por mesa; si aumenta, muestra un aviso arriba, vibra y suena (botón Aviso, se recuerda en el celular).
- **Reglas de cobro** (Datos del negocio → Cobro): métodos de pago aceptados (`Ajustes.metodos_pago`, el efectivo siempre está), propina, descuentos y cortesías. El cuadro de cobro solo muestra lo activo y el servidor rechaza lo apagado (`registrar_venta`, `cortesia_vista`).
- **Cuadro de cobro en celular:** botones "Paga con" (un método por defecto; al elegir Yape, tarjeta… se pone el total), "Combinar pagos" para varios métodos, y Descuento / Propina / Partes iguales / Cliente plegados en botones pequeños.
- El módulo Mesas empieza apagado y se activa solo al elegir el rubro Restaurante.

## Clientes y fiado (cómo está pensado)

- **Cliente**: tipo y número de documento (único), nombre o razón social, celular, dirección y límite de fiado (0 = sin límite). `clientes/documentos.py` valida el DNI (8 dígitos) y el RUC (dígito verificador módulo 11); no consulta a RENIEC ni a SUNAT.
- **Fiado** es un método de pago más (`MetodoPago.CREDITO`). La venta guarda `cliente`. `registrar_venta()` resuelve el cliente (el elegido, o lo busca o crea por su DNI/RUC, o por su nombre si se fía sin documento), exige `clientes.fiar` y respeta el límite salvo con `clientes.limite`.
- **Saldo** = fiado de ventas pagadas − pagos (`Abono`) no anulados. Se calcula siempre, no se guarda: anular una venta o un pago lo corrige solo. Para listas usa `clientes.servicios.con_saldo()`, que lo calcula en la base de datos.
- **Pagos de deudas** (`registrar_abono`): necesitan caja abierta. Si son en efectivo, suman al efectivo esperado de esa caja. El fiado no suma (no hay dinero). Anular un pago de una caja ya cerrada saca el efectivo de la caja abierta de quien anula.
- En el cuadro de cobro, el método "Fiado" solo aparece a quien puede fiar. Ahí mismo se busca el cliente (`clientes:buscar`) o se escribe uno nuevo.
- **Cuenta corriente** (`clientes.servicios.deudas`): reparte lo pagado en orden FIFO entre las ventas al fiado y, si la venta tiene factura al crédito, usa sus cuotas para saber qué está vencido y con cuántos días de atraso. `validar_fiado` no deja fiar a quien tiene algo vencido salvo con `clientes.limite`.
- **Incobrable** (`marcar_incobrable`): un `Abono` con método `"INC"`, sin caja, que baja la deuda sin sumar dinero. Sale en el estado de cuenta y en el Excel del contador.

## Cobranzas (cómo está pensado)

- **App `cobranzas`**, módulo apagado por defecto; necesita Clientes. Se enciende solo al elegir el rubro "Academia / gimnasio / taller". No depende del punto de venta: un negocio puede usar solo Cobranzas, Clientes y Caja.
- **Plan** (precio, frecuencia MEN/QUI/SEM/UNI, `num_cuotas` 0 = sin fin, matrícula) → **Inscripción** (cliente que paga, `alumno` opcional, precio propio, inicio, día de pago, estado ACT/TER/BAJ) → **Cuota** (número 0 = matrícula, concepto, vence, monto, mora, pagado, `anulada` = exonerada) ← **Pago** + **PagoCuota** (cuánto de cada pago fue a cada cuota).
- **Generación sin tareas programadas:** `servicios.al_dia()` se llama al abrir las pantallas de cobranza y el inicio. Crea las cuotas de los planes sin fin hasta hoy + días de aviso y pone la mora (si está activa) a las cuotas atrasadas pasados los días de gracia. Los planes con número fijo crean todas sus cuotas al inscribir. `generar()` es idempotente (restricción única inscripción + número).
- **Cobro** (`cobrar`): el pago se reparte entre las cuotas marcadas, la más antigua primero; puede ser menos que el total (a cuenta). Usa `sesion_para_vender`: entra a la caja abierta y `caja.servicios.calcular` lo suma (`cuotas`, `cuotas_efectivo`). Anular un recibo devuelve la deuda y, si su caja ya cerró y era efectivo, saca el dinero de la caja abierta de quien anula.
- **Baja:** quita (marca exoneradas con nota "Por baja") las cuotas que aún no vencen y no tienen pagos; lo vencido se sigue debiendo. Reactivar las devuelve. Un plan con número fijo pasa a Terminada cuando no queda nada por pagar.
- **Recordatorios:** `mensaje()` arma el texto y `enlace_whatsapp()` el enlace wa.me (no envía nada solo).
- **Pendiente:** boleta electrónica del pago de cuotas (hoy se entrega un recibo interno), congelar una membresía por unos días.

## Turnos: base común de lo que se agenda (reservas, citas…)

- `core/turnos.py`: modelo abstracto **`TurnoBase`** (nombre, celular, `cliente`, nota, quién lo tomó y cambió; `momento` según `CAMPO_HORA`, `activa`, `whatsapp`) y funciones comunes: `cambiar_estado`, `cerrar_pasadas` (lo de días anteriores sin marcar → «No vino»), `por_confirmar` (Inicio), y los textos `hora_texto`, `dia_texto` («mañana», «el jueves 19/11»), `dia_corto` («Jueves 19/11») y `negocio()`.
- Mismos códigos de estado: PEN, CON, NOV, CAN; el «hecho» lo pone cada módulo (Reserva: LLE «Llegó»; Cita: ATE «Atendida»).
- `reservas.Reserva` y `citas.Cita` heredan de `TurnoBase`; cada uno agrega a qué se reserva (mesa/s o persona y servicio) y sus pantallas. Un módulo nuevo de este tipo (canchas, salas, clases) parte de aquí y del cliente por celular.

## Reservas (cómo está pensado)

- **App `reservas`**, módulo apagado por defecto (también en sistemas que ya estaban en uso: migración `0002`). Se ofrece en el rubro restaurante. No necesita Mesas: sin ese módulo, «Llegaron» solo marca la reserva.
- **Reserva**: fecha + hora, personas, nombre, celular, `cliente` (con el módulo Clientes se busca o crea por celular), `mesa` opcional (principal) + `mesas_extra` (grupos grandes: se juntan con `unir_mesas` al llegar; `choques` y `para_mapa` miran todas), nota, estado PEN/CON/LLE/NOV/CAN y la `cuenta` que se abrió al llegar. **Config** (una fila): `antes` (min que la mesa se ve «Reservada» en el mapa), `tolerancia` (min que se guarda después de la hora) y `duracion` (para avisar choques de la misma mesa).
- `servicios.guardar` valida y avisa choques de mesa (`choques`, ± duración); se puede reservar igual con `permitir_choque`. `llego` abre la cuenta con `mesas.servicios.abrir_cuenta` (personas, nombre y cliente de la reserva). Sin tareas programadas: `cerrar_pasadas()` pasa a «No vino» lo activo de días anteriores al abrir la agenda o el inicio; las de hoy que pasaron la tolerancia salen como **atrasadas**.
- **Mapa:** `mesas.views._reservas_mapa` usa `para_mapa` (mesas que se ven «Reservada» ahora) y `proximas_hoy` (la tira de arriba). Una mesa reservada se puede ocupar igual (el modal avisa y ofrece «Llegó …»).
- Permisos: `reservas.ver` (ver; con `mesas.atender` también Llegaron / No vino) y `reservas.gestionar` (tomar, cambiar, confirmar, cancelar, configurar). WhatsApp con `mensaje()` / `enlace_whatsapp()`: confirmación si es otro día, recordatorio si es hoy.

## Citas (cómo está pensado)

- **App `citas`**, módulo apagado por defecto (también en sistemas ya en uso: migración `0002`, que además crea el rol **Profesional**). Se ofrece en el rubro peluquería.
- Quien atiende es una **Persona** del Personal (`personal.Persona` con `atiende_citas`; `servicios` = productos tipo Servicio, ninguno = hace todos). Los campos `profesional` de Citas apuntan a Persona → **Horario** (uno por día de la semana: entrada, salida, refrigerio) y **Ausencia** (desde/hasta; con horas = solo ese rato). **Cita**: fecha, inicio, fin, profesional, `servicio` (Variante) + `servicio_nombre`, cliente, estado PEN/CON/ATE/NOV/CAN. **Config**: intervalo (10/15/30), duración por defecto, días que se comparten.
- **Horarios libres** (`servicios.Dia`): carga una vez los horarios, ausencias y citas del día; `jornada` = horario − refrigerio − ausencias; `libres` = jornada − citas (PEN, CON, ATE) − lo ya pasado; `horarios_libres` = inicios cada `intervalo` donde cabe la duración. `proximos` busca los siguientes días (máx. 3 por día) y `a_esa_hora` a otros profesionales libres a esa hora o hasta 1 h después. `agendar` rechaza lo que no cabe salvo `forzar` (solo `citas.gestionar`).
- **Preferido:** `historial(celular)` cuenta con quién se atendió más (PEN/CON/ATE) y el formulario lo elige solo.
- **Por cobrar:** una cita ATENDIDA con `cobrada=False` está «por cobrar». `registrar_servicios` (cliente sin cita, `sin_cita=True`, o algo más en una cita) crea citas ya atendidas, una por servicio y seguidas. `por_cobrar()` las agrupa por cliente y día. Vender con `?citas=1,2` carga esos servicios y guarda los ids en el carrito (sessionStorage); `ventas.registrar` recibe `citas` y llama a `marcar_cobradas(ids, venta)`. «Ya cobrado» marca sin venta. Las ATE anteriores a esta versión se dieron por cobradas (migración 0003).
- **Precio:** `Cita.precio` guarda el del catálogo al agendar y `marcar_cobradas` lo cambia por el `precio_unitario` cobrado en la venta.
- **Reporte:** ya no hay uno propio: Citas aporta sus columnas (servicios, clientes, sin cita, no vino, ocupación, top, servicios por persona) al reporte único de Personal.
- Permisos: `citas.ver`, `citas.gestionar`, `citas.personal`, `citas.mi_agenda` (rol Profesional), `citas.agendar_propias` (apagado por defecto; solo con su propio profesional y sin forzar). Un profesional solo ve sus citas.
- **Mi agenda / compartir:** `mis_horarios` (rangos libres ≥ 30 min) y `mensaje_horarios` → enlace `wa.me/?text=` (elige a quién mandarlo).

## Cliente por celular (una sola forma para todo el sistema)

- `clientes.servicios`: `por_celular(tel)` (compara los últimos 9 dígitos), `recordar(nombre, tel, direccion, origen, cliente)` (con el módulo Clientes busca o registra al cliente y guarda su última dirección; sin el módulo no hace nada) e `historial(tel | cliente)` (pedidos de delivery, reservas, citas, «no vino» sumando reservas y citas, con quién suele atenderse, si debe). Funciona aunque Clientes esté apagado, buscando por celular en cada módulo.
- Un solo endpoint `clientes:celular` (JSON) para los formularios de delivery, reservas y citas. Lo que debe solo lo ve quien ve clientes o toma deliverys.
- Delivery (`mesas.servicios.datos_delivery`), Reservas y Citas usan `recordar`; la ficha del cliente muestra «En el negocio» con `historial`.

## Personal (cómo está pensado)

- **App `personal`, base del sistema** (siempre activa, en `MODULOS_BASE`; permiso `personal.editar`, por defecto solo Administración). `Persona`: nombre, celular, `usuario` opcional (uno a uno), color, `comision` %, `atiende_citas`, `reparte`, `servicios`. La ficha (`PersonaForm`) muestra solo lo de los módulos y funciones activos.
- **Quién usa el Personal:** Citas (agenda, horarios, ausencias), Delivery (`mesas.views._repartidores`: primero los que reparten), Vender (función **«Quién atendió»** → `Venta.atendio_persona`), Mesas (el mozo es un usuario; si tiene Persona, el reporte usa su nombre).
- **Reporte único** (`personal/reportes.reporte(desde, hasta, modulos, comisiones, atendio)`, sección «Personal» de Reportes y «Este mes» de Mi agenda): una fila por Persona (o por usuario si no está en el Personal). Columnas según el negocio: cobró en caja (`Venta.usuario`), atendió (`atendio_persona` o el mozo `atendio`; sin contar lo que ya cuenta como servicio), propinas (Mesas), servicios… (Citas), entregas (Delivery, por el nombre del repartidor), generó y **comisión** (función «Comisiones»: % sobre lo generado).
- Funciones nuevas apagadas por defecto: `atendio` y `comisiones` (migración `core.0013`). La migración `citas.0005` pasó los Profesional a Persona con el mismo id.

## Reportes

- `reportes/servicios.py` calcula todo a partir de lo ya registrado (ventas pagadas, cajas, cuentas de mesa, stock y fiado). No tiene tablas propias.
- Las secciones aparecen según los módulos activos: con Mesas, la parte de mozos y mesas (platos quitados tras enviarse, gasto por persona, tiempo en mesa); con Clientes, los deudores. En Control: diferencias de caja, anuladas y cortesías y descuentos (valor, motivo, quién atendió y quién autorizó). La ganancia y el valor del inventario solo se muestran con `productos.costos`.
- La ganancia por producto es precio cobrado − costo guardado en la venta (antes del descuento general de la venta).
- Los gráficos son barras hechas con HTML y CSS (sin librerías), y también salen al imprimir. `?excel=1` exporta un libro con una hoja por sección.
- Permiso `reportes.ver`, que por defecto solo tiene Administración.

## Impresión (ticketera)

- Todo lo que se imprime hereda de `templates/impresion/base.html`: una página sin menús, del ancho del rollo (Datos del negocio → 80 o 58 mm). Un script calcula el alto del contenido y fija `@page` a ese tamaño, así no sale una hoja A4.
- Para imprimir sin salir de la pantalla: `<a data-imprimir="/ruta/">` (o `window.imprimir(url)`, en `static/js/app.js`). En la PC trae el ticket con `fetch`, lo pone en `#zona-impresion` (aislado con Shadow DOM para que sus estilos no choquen con los de la pantalla), fija `@page` al ancho del rollo y al alto medido, imprime y al terminar (`afterprint`) quita ese `@page`. **No usar un marco oculto (iframe):** Chrome ignora el tamaño de hoja de un marco y sale en carta/A4 con encabezado y pie. En el celular abre otra pestaña con `?auto=1`.
- En la pantalla de una venta, Ctrl+P imprime el ticket del rollo.
- Impresiones: ticket (`ventas:imprimir`), precuenta y comanda (`mesas:precuenta`, `mesas:comanda`), cierre o corte de caja (`caja:imprimir`).
- Para imprimir **sin el cuadro de diálogo** (ticket automático o comandas en cocina), abre Chrome con `--kiosk-printing` y deja la ticketera como impresora predeterminada.

## Pantalla de cocina

- `mesas:cocina`, con el permiso `mesas.cocina` (rol base **Cocina**; quien solo tiene ese rol entra directo ahí). Muestra las comandas pendientes, se actualiza cada 5 segundos, suena al llegar una nueva (tras tocar "Activar sonido") y puede imprimir cada comanda nueva en la impresora de ese equipo.
- Cocina marca la comanda entera (LISTO) o un plato (tocándolo). `ItemCuenta.listo_en` → el mozo ve 🔔 en el mapa y "¡Listo!" en la cuenta → pulsa "Ya serví lo listo" (`servido_en`). Los platos quitados después de enviarse aparecen tachados en rojo para que cocina no los prepare.
- Si hay categorías o productos de **Barra**, la pantalla tiene pestañas Cocina | Barra: una tablet en la barra abre la pestaña Barra. "Todo listo" solo marca lo de su área.
- Datos del negocio → "la cocina usa la pantalla de cocina" cambia los textos del mozo ("Enviado a la pantalla de cocina" en vez de "Díctale a cocina").

## Rubros

`core.models.Rubro` guarda el tipo de negocio (tienda, restaurante, ropa, librería/útiles, peluquería, otro). Se elige en Datos del negocio y sirve para ajustar textos y opciones por rubro (mesas en restaurante, tallas y colores en ropa, servicios y citas en peluquería) sin hacer un sistema distinto para cada uno.

## Piezas clave para reutilizar

- **Permisos:** en `core/permisos.py`.
  - Lista de `PERMISOS` con el formato (código, módulo, texto, roles por defecto) y la lista `MODULOS`.
  - En las vistas: `@permiso_requerido("modulo.accion")`. En plantillas: `{% if P.modulo_accion %}`; para saber si un módulo está activo, `{% if P.mod_modulo %}`.
  - Los roles base son **Administración** (acceso total), **Cajero** y **Vendedor** (migración `core/0002_roles_iniciales`).
  - Administración y el superusuario tienen todo. Los módulos solo los activa el superusuario (`/configuracion/modulos/`).
  - Los roles son grupos de Django más `PermisosRol`; se editan en `/configuracion/roles/`.
- **Datos del negocio:** `core.models.Ajustes` (singleton, `Ajustes.cargar()`): rubro, nombre, logo (genera los íconos de la PWA), razón social, RUC, contacto, nota del ticket y color. En plantillas está disponible como `NEGOCIO` (y `NEGOCIO_NOMBRE`, `NEGOCIO_NOMBRE_CORTO`).
- **Inicio:** `core/tablero.py` arma atajos, pendientes y tarjetas según los permisos de cada usuario.
- **Archivos privados:** el `MEDIA_URL` es `/archivos/`, servido por `core.views.archivo` con control de permisos. Solo `negocio/` es público (el logo). Cada app que guarde imágenes agrega su carpeta y permiso en `reglas`.
- **Seguridad:**
  - Login con bloqueo tras 5 intentos fallidos (`core/forms.LoginForm` y caché en archivos dentro de `privado/`).
  - Exportes a Excel sin fórmulas (`core/excel.a_bytes`).
  - Ids recibidos por GET/POST siempre pasan por `core.utils.entero`.
  - Límite de tamaño para archivos subidos (`TamanoMaximo`).
  - Modo demo (`DEMO=True`): bloquea cambios de clave, usuarios y admin (`core/middleware.py`). La pantalla de ingreso lista solo los usuarios de prueba que sirven en ese negocio (`core.roles.usuarios_demo`, según su rol y los módulos activos).
- **WhatsApp:**
  - Enlaces `wa.me` con el mensaje ya armado: **todos** salen de `core.utils.enlace_whatsapp(telefono, texto)` (usa `numero_whatsapp`, que agrega el 51; devuelve "" si el número no sirve; con `telefono=None` abre WhatsApp para elegir a quién mandarlo). En plantillas: filtro `|wa_enlace`. No armar `wa.me` a mano en otro lugar.
  - Los botones que además anotan el aviso usan la clase `.btn-recordar` con `data-aviso-url` (en `static/js/app.js`).
- **Redirecciones:** toda dirección de "volver" que llegue por GET pasa por `core.utils.url_segura` (no se puede mandar al usuario a otro sitio).
- **Respaldos:** `python manage.py respaldo` (o `respaldo.bat`). Guarda la base de datos y `media/` en un zip y conserva los últimos 30.
- **Pruebas:** `python manage.py test core productos ventas caja mesas clientes reportes`. `core/tests.py` recorre todas las pantallas con cada rol sobre la demo y falla si alguna da error.
- **HTMX:** el token CSRF va en `hx-headers` del `<body>`. Nunca poner `hx-post` en un `<a href>`, porque bloquea el enlace.
- **Datos de ejemplo:** `python manage.py datos_demo --rubro ROP` (TIE, RES, ROP, LIB o PEL; en `core/management/commands`) carga un negocio de ejemplo de ese rubro, los usuarios `admin`, `gerente`, `cajero` y `vendedor` (clave `demo1234`), su catálogo (`productos/demo.py`) una semana de ventas con sus cajas abiertas y cerradas (`ventas/demo.py`) y, en restaurante, una carta de 47 productos con opciones, un segundo mozo (`mozo`), dos semanas de mesas cobradas (con propinas, cortesías, descuentos y platos quitados) y mesas ocupadas en distintos momentos (`mesas/demo.py`). Los agotados del día se marcan al final (`marcar_agotados_demo`). `demo.bat` los carga en una base aparte. `render.yaml` define una demo gratis en Render por cada rubro, con SQLite y sin despliegue automático (ver `DEMO_RENDER.md`).

## Convenciones

- Textos y nombres de modelos y campos en español.
- Vistas por función, con plantillas por app.
- Mensajes con `django.contrib.messages`.
- Fechas en formato `d/m/Y`.
- Toda vista nueva lleva su `@permiso_requerido` y, si corresponde, un permiso nuevo agregado a `PERMISOS`.

## Cómo agregar un módulo nuevo (por ejemplo, ventas)

1. `python manage.py startapp ventas` y agregarla a `LOCAL_APPS` en `config/settings.py` y a `config/urls.py`.
2. En `core/permisos.py`: agregar el módulo a `MODULOS` (con el módulo que necesita, si aplica) y sus permisos a `PERMISOS` (con los roles que los tienen por defecto). Si un rol base debe tenerlos ya creados, hacer una migración de datos que actualice su `PermisosRol`.
3. En `templates/partials/sidebar.html`: su entrada en el grupo que corresponda (Atención, Hoy, Gestión), con `{% if P.ventas_ver %}`, y agregar el permiso a la condición del encabezado.
4. En `core/tablero.py`: sus atajos, pendientes y tarjetas.
5. Datos de ejemplo en `datos_demo`.

## Historial

Esta base salió del sistema escolar. El commit `a4337f9 Base inicial` de git guarda las apps del colegio (alumnos, cobranza, asistencia, notas, programación, personal) por si se quiere consultar cómo se hizo algo, por ejemplo los recibos, la caja o los recordatorios por WhatsApp de `cobranza`.
