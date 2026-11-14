# Arquitectura del sistema (guía para reutilizar esta base)

Este documento resume cómo está hecho el sistema. Sirve para empezar otro proyecto sobre esta misma base: compártelo al inicio de la nueva conversación.

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
| `productos/` | Catálogo: categorías, productos y servicios, variantes (talla/color/tamaño), stock y kardex, importar y exportar Excel, catálogos de ejemplo por rubro |
| `ventas/` | Punto de venta, registro y anulación de ventas, ticket, lista y resumen del día, Excel |
| `caja/` | Turnos de caja: apertura, ingresos y egresos, cierre con arqueo por billetes, historial |
| `mesas/` | Restaurantes: zonas y mesas, cuentas abiertas, pedidos con notas, envío a cocina, precuenta, comanda, cambiar y juntar mesas, cobro total o dividido |
| `clientes/` | Clientes (DNI/RUC validados), ventas al fiado con límite, pagos de deudas, estado de cuenta, recordatorio por WhatsApp |
| `reportes/` | Reportes sin tablas propias: resumen con comparación, por día/hora/semana, productos, categorías, personal, mesas, inventario, deudores y control; Excel |
| `templates/` | `base.html`, `partials/` (sidebar, navbar, mensajes, modal eliminar), `registration/` (login) y `core/` |

Las demás apps del negocio (ventas, caja, clientes, etc.) se crean como apps nuevas de Django, una por módulo.

## Productos (cómo está pensado)

- **Producto** guarda lo común: tipo (producto o servicio), categoría, unidad, precio, costo, si controla stock y el stock mínimo. Un servicio nunca controla stock.
- **Variante** es lo que realmente se vende y se cuenta: tiene su código de barras, su stock y, si hace falta, su propio precio y costo (vacío = los del producto). Un producto sin tallas ni colores tiene **una sola variante sin nombre**, que la interfaz no muestra. Así, ventas siempre trabaja con variantes.
- **MovimientoStock** es el kardex. El stock **solo cambia** con `productos.servicios.mover_stock()` o `ajustar_a()`, que bloquean la fila y anotan el saldo. Las ventas usarán `mover_stock(variante, -cantidad, Tipo.VENTA, referencia="Venta 000123")`. Se permite stock negativo para no trabar la caja.
- `productos/rubros.py` tiene lo que cambia por rubro: categorías sugeridas, nombres de las variantes y valores por defecto.
- Permisos: `productos.ver`, `productos.editar`, `productos.stock` y `productos.costos`. Quien no tiene `productos.costos` no ve los costos en pantallas ni en el Excel.
- Pruebas: `python manage.py test productos ventas caja mesas`.

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

## Mesas (cómo está pensado)

- **Cuenta** es lo que va consumiendo una mesa (o un pedido para llevar, sin mesa). Solo puede haber una cuenta abierta por mesa. **ItemCuenta** guarda el plato, la cantidad, el precio de ese momento, la nota ("sin cebolla"), cuándo se envió a cocina, si se quitó (con motivo) y con qué venta se cobró.
- Flujo: abrir la mesa → agregar → **enviar a cocina** (la pantalla muestra "Díctale a cocina", y hay una comanda imprimible opcional) → precuenta → **cobrar**. Al cobrar se llama a `registrar_venta()` con los precios del pedido, y la venta guarda el mozo en `atendio`. Para dividir la cuenta se eligen ítems y se cobra varias veces. Cuando no queda nada por cobrar, la mesa se libera.
- El stock baja al cobrar (es una venta normal). Lo que no se envió a cocina se cambia libremente. Lo ya enviado solo se quita con `mesas.anular` y un motivo.
- El mapa se actualiza solo con HTMX cada 8 segundos, para varios mozos con celular.
- El cuadro de cobro es compartido: `templates/ventas/partials/modal_cobro.html` + `static/js/cobro.js` (lo usan el punto de venta y las mesas). La **propina** se activa en Datos del negocio: va en `Venta.propina`, no suma al total vendido y se cobra dentro de los pagos.
- El módulo Mesas empieza apagado y se activa solo al elegir el rubro Restaurante.

## Clientes y fiado (cómo está pensado)

- **Cliente**: tipo y número de documento (único), nombre o razón social, celular, dirección y límite de fiado (0 = sin límite). `clientes/documentos.py` valida el DNI (8 dígitos) y el RUC (dígito verificador módulo 11); no consulta a RENIEC ni a SUNAT.
- **Fiado** es un método de pago más (`MetodoPago.CREDITO`). La venta guarda `cliente`. `registrar_venta()` resuelve el cliente (el elegido, o lo busca o crea por su DNI/RUC, o por su nombre si se fía sin documento), exige `clientes.fiar` y respeta el límite salvo con `clientes.limite`.
- **Saldo** = fiado de ventas pagadas − pagos (`Abono`) no anulados. Se calcula siempre, no se guarda: anular una venta o un pago lo corrige solo. Para listas usa `clientes.servicios.con_saldo()`, que lo calcula en la base de datos.
- **Pagos de deudas** (`registrar_abono`): necesitan caja abierta. Si son en efectivo, suman al efectivo esperado de esa caja. El fiado no suma (no hay dinero). Anular un pago de una caja ya cerrada saca el efectivo de la caja abierta de quien anula.
- En el cuadro de cobro, el método "Fiado" solo aparece a quien puede fiar. Ahí mismo se busca el cliente (`clientes:buscar`) o se escribe uno nuevo.

## Reportes

- `reportes/servicios.py` calcula todo a partir de lo ya registrado (ventas pagadas, cajas, cuentas de mesa, stock y fiado). No tiene tablas propias.
- Las secciones aparecen según los módulos activos: con Mesas, la parte de mozos y mesas (platos quitados tras enviarse, gasto por persona, tiempo en mesa); con Clientes, los deudores. La ganancia y el valor del inventario solo se muestran con `productos.costos`.
- La ganancia por producto es precio cobrado − costo guardado en la venta (antes del descuento general de la venta).
- Los gráficos son barras hechas con HTML y CSS (sin librerías), y también salen al imprimir. `?excel=1` exporta un libro con una hoja por sección.
- Permiso `reportes.ver`, que por defecto solo tiene Administración.

## Impresión (ticketera)

- Todo lo que se imprime hereda de `templates/impresion/base.html`: una página sin menús, del ancho del rollo (Datos del negocio → 80 o 58 mm). Un script calcula el alto del contenido y fija `@page` a ese tamaño, así no sale una hoja A4.
- `X_FRAME_OPTIONS = "SAMEORIGIN"`: las impresiones se arman en un marco oculto de la misma página. Con `DENY` no se podría imprimir en la PC.
- Para imprimir sin salir de la pantalla: `<a data-imprimir="/ruta/">` (o `window.imprimir(url)`, en `static/js/app.js`). En la PC imprime desde un marco oculto; en el celular abre otra pestaña con `?auto=1`.
- Impresiones: ticket (`ventas:imprimir`), precuenta y comanda (`mesas:precuenta`, `mesas:comanda`), cierre o corte de caja (`caja:imprimir`).
- Para imprimir **sin el cuadro de diálogo** (ticket automático o comandas en cocina), abre Chrome con `--kiosk-printing` y deja la ticketera como impresora predeterminada.

## Pantalla de cocina

- `mesas:cocina`, con el permiso `mesas.cocina` (rol base **Cocina**; quien solo tiene ese rol entra directo ahí). Muestra las comandas pendientes, se actualiza cada 5 segundos, suena al llegar una nueva (tras tocar "Activar sonido") y puede imprimir cada comanda nueva en la impresora de ese equipo.
- Cocina marca la comanda entera (LISTO) o un plato (tocándolo). `ItemCuenta.listo_en` → el mozo ve 🔔 en el mapa y "¡Listo!" en la cuenta → pulsa "Ya serví lo listo" (`servido_en`). Los platos quitados después de enviarse aparecen tachados en rojo para que cocina no los prepare.
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
  - Modo demo (`DEMO=True`): bloquea cambios de clave, usuarios y admin (`core/middleware.py`).
- **WhatsApp:**
  - Enlaces `wa.me` con el mensaje ya armado (`core.utils.numero_whatsapp` agrega el 51).
  - Los botones que además anotan el aviso usan la clase `.btn-recordar` con `data-aviso-url` (en `static/js/app.js`).
- **Redirecciones:** toda dirección de "volver" que llegue por GET pasa por `core.utils.url_segura` (no se puede mandar al usuario a otro sitio).
- **Respaldos:** `python manage.py respaldo` (o `respaldo.bat`). Guarda la base de datos y `media/` en un zip y conserva los últimos 30.
- **Pruebas:** `python manage.py test core productos ventas caja mesas clientes reportes`. `core/tests.py` recorre todas las pantallas con cada rol sobre la demo y falla si alguna da error.
- **HTMX:** el token CSRF va en `hx-headers` del `<body>`. Nunca poner `hx-post` en un `<a href>`, porque bloquea el enlace.
- **Datos de ejemplo:** `python manage.py datos_demo --rubro ROP` (TIE, RES, ROP, LIB o PEL; en `core/management/commands`) carga un negocio de ejemplo de ese rubro, los usuarios `admin`, `gerente`, `cajero` y `vendedor` (clave `demo1234`), su catálogo (`productos/demo.py`) una semana de ventas con sus cajas abiertas y cerradas (`ventas/demo.py`) y, en restaurante, mesas con algunas ocupadas (`mesas/demo.py`). `demo.bat` los carga en una base aparte.

## Convenciones

- Textos y nombres de modelos y campos en español.
- Vistas por función, con plantillas por app.
- Mensajes con `django.contrib.messages`.
- Fechas en formato `d/m/Y`.
- Toda vista nueva lleva su `@permiso_requerido` y, si corresponde, un permiso nuevo agregado a `PERMISOS`.

## Cómo agregar un módulo nuevo (por ejemplo, ventas)

1. `python manage.py startapp ventas` y agregarla a `LOCAL_APPS` en `config/settings.py` y a `config/urls.py`.
2. En `core/permisos.py`: agregar el módulo a `MODULOS` y sus permisos a `PERMISOS` (con los roles que los tienen por defecto). Si un rol base debe tenerlos ya creados, hacer una migración de datos que actualice su `PermisosRol`.
3. En `templates/partials/sidebar.html`: su entrada en el menú, con `{% if P.ventas_ver %}`.
4. En `core/tablero.py`: sus atajos, pendientes y tarjetas.
5. Datos de ejemplo en `datos_demo`.

## Historial

Esta base salió del sistema escolar. El commit `a4337f9 Base inicial` de git guarda las apps del colegio (alumnos, cobranza, asistencia, notas, programación, personal) por si se quiere consultar cómo se hizo algo, por ejemplo los recibos, la caja o los recordatorios por WhatsApp de `cobranza`.
