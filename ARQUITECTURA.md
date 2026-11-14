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
| `core/` | Base reutilizable: año lectivo, periodos, secciones, usuarios, **roles y permisos**, **módulos activos**, datos de la empresa (`Ajustes`), inicio (`tablero.py`), archivos privados, PWA, utilidades |
| `alumnos/` | Personas (alumnos, apoderados), matrícula, importar y exportar Excel, pase de año |
| `cobranza/` | Conceptos, cargos (deudas), pagos y recibos, descuentos, mora, morosos, recordatorios por WhatsApp, caja |
| `asistencia/` | Sesiones (diaria o por curso), estados P/T/F/J, reportes, avisos |
| `academico/` | Programación del año: cursos, plan, docentes, jornada, horarios, carga docente (prefijo de URL `programacion/`) |
| `evaluacion/` | Notas, competencias, conducta, libretas, SIAGIE (prefijo de URL `notas/`) |
| `personal/` | Trabajadores, horarios, planilla estimada |
| `templates/` | `base.html`, `partials/` (sidebar, navbar, mensajes, modal eliminar) y una carpeta por app |

## Piezas clave para reutilizar

- **Permisos:** en `core/permisos.py`.
  - Lista de `PERMISOS` con el formato (código, módulo, texto, roles por defecto) y la lista `MODULOS`.
  - En las vistas: `@permiso_requerido("modulo.accion")`. En plantillas: `{% if P.modulo_accion %}`; para saber si un módulo está activo, `{% if P.mod_modulo %}`.
  - Dirección y el superusuario tienen todo. Los módulos solo los activa el superusuario (`/configuracion/modulos/`).
  - Los roles son grupos de Django más `PermisosRol`; se editan en `/configuracion/roles/`.
- **Datos de la empresa:** `core.models.Ajustes` (singleton, `Ajustes.cargar()`): nombre, logo (genera los íconos de la PWA), RUC, contacto y color. En plantillas está disponible como `COLEGIO`.
- **Inicio:** `core/tablero.py` arma atajos, pendientes y tarjetas según los permisos de cada usuario.
- **Archivos privados:** el `MEDIA_URL` es `/archivos/`, servido por `core.views.archivo` con control de permisos. Solo `colegio/` es público (el logo).
- **Seguridad:**
  - Login con bloqueo tras 5 intentos fallidos (`core/forms.LoginForm` y caché en archivos dentro de `privado/`).
  - Exportes a Excel sin fórmulas (`core/excel.a_bytes`).
  - Ids recibidos por GET/POST siempre pasan por `core.utils.entero`.
  - Límite de tamaño para archivos subidos (`TamanoMaximo`).
  - Modo demo (`DEMO=True`): bloquea cambios de clave, usuarios y admin (`core/middleware.py`).
- **WhatsApp:**
  - Enlaces `wa.me` con el mensaje ya armado.
  - Los botones que además anotan el aviso usan la clase `.btn-recordar` con `data-aviso-url` (en `static/js/app.js`).
- **HTMX:** el token CSRF va en `hx-headers` del `<body>`. Nunca poner `hx-post` en un `<a href>`, porque bloquea el enlace.
- **Datos de ejemplo:** `python manage.py datos_demo` (en `core/management/commands`). `demo.bat` los carga en una base aparte.

## Convenciones

- Textos y nombres de modelos y campos en español.
- Vistas por función, con plantillas por app.
- Mensajes con `django.contrib.messages`.
- Fechas en formato `d/m/Y`.
- Toda vista nueva lleva su `@permiso_requerido` y, si corresponde, un permiso nuevo agregado a `PERMISOS`.

## Para empezar un proyecto nuevo con esta base

1. Copiar la carpeta **sin** `.venv`, `.git`, `db*.sqlite3`, `.env`, `media`, `privado`, `staticfiles` ni `_to_delete`.
2. Crear un `.venv` nuevo, ejecutar `pip install -r requirements.txt`, copiar `.env.example` a `.env` con una `SECRET_KEY` nueva, y luego `migrate` y `createsuperuser`.
3. Quitar de `INSTALLED_APPS` y de `config/urls.py` las apps que no se usen, junto con sus módulos y permisos en `core/permisos.py` y su parte en `core/tablero.py`.
4. Renombrar textos ("colegio", "alumno", etc.) según el nuevo rubro.
