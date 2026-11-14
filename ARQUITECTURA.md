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
| `templates/` | `base.html`, `partials/` (sidebar, navbar, mensajes, modal eliminar), `registration/` (login) y `core/` |

Las demás apps del negocio (ventas, caja, clientes, etc.) se crean como apps nuevas de Django, una por módulo.

## Productos (cómo está pensado)

- **Producto** guarda lo común: tipo (producto o servicio), categoría, unidad, precio, costo, si controla stock y el stock mínimo. Un servicio nunca controla stock.
- **Variante** es lo que realmente se vende y se cuenta: tiene su código de barras, su stock y, si hace falta, su propio precio y costo (vacío = los del producto). Un producto sin tallas ni colores tiene **una sola variante sin nombre**, que la interfaz no muestra. Así, ventas siempre trabaja con variantes.
- **MovimientoStock** es el kardex. El stock **solo cambia** con `productos.servicios.mover_stock()` o `ajustar_a()`, que bloquean la fila y anotan el saldo. Las ventas usarán `mover_stock(variante, -cantidad, Tipo.VENTA, referencia="Venta 000123")`. Se permite stock negativo para no trabar la caja.
- `productos/rubros.py` tiene lo que cambia por rubro: categorías sugeridas, nombres de las variantes y valores por defecto.
- Permisos: `productos.ver`, `productos.editar`, `productos.stock` y `productos.costos`. Quien no tiene `productos.costos` no ve los costos en pantallas ni en el Excel.
- Pruebas: `python manage.py test productos ventas`.

## Ventas (cómo está pensado)

- **Venta** (numerada con `Correlativo`, sin saltos), **VentaItem** (guarda nombre, precio de lista, precio cobrado y costo de ese momento) y **Pago** (uno por método; el de efectivo guarda lo que se queda el negocio, y la venta guarda `recibido` y `vuelto`).
- El punto de venta (`templates/ventas/pos.html`) carga el catálogo en JSON y arma el carrito en el navegador; al cobrar envía un JSON a `ventas:registrar`. **El servidor vuelve a validar todo** en `ventas.servicios.registrar_venta()`: precios del catálogo (salvo permiso `ventas.precio`), cantidades enteras si la unidad no es fraccionable, que los pagos cubran el total y que el vuelto salga solo del efectivo.
- Un `token` por carrito evita registrar dos veces la misma venta (doble clic o reintento sin internet).
- Las ventas descuentan stock con `mover_stock(..., VENTA)`. `anular_venta()` lo devuelve con un movimiento de DEVOLUCIÓN. Nada se borra.
- Quien solo tiene `ventas.vender` ve solo **sus** ventas. `ventas.ver` ve todas y los totales.
- El ticket es una "nota de venta" interna, imprimible en 80 mm y enviable por WhatsApp. La factura o boleta electrónica (SUNAT) queda pendiente.

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
- **HTMX:** el token CSRF va en `hx-headers` del `<body>`. Nunca poner `hx-post` en un `<a href>`, porque bloquea el enlace.
- **Datos de ejemplo:** `python manage.py datos_demo --rubro ROP` (TIE, RES, ROP, LIB o PEL; en `core/management/commands`) carga un negocio de ejemplo de ese rubro, los usuarios `admin`, `gerente`, `cajero` y `vendedor` (clave `demo1234`), su catálogo (`productos/demo.py`) y una semana de ventas (`ventas/demo.py`). `demo.bat` los carga en una base aparte.

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
