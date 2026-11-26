"""
Configuración del Sistema de Ventas.

Los valores sensibles o que cambian entre desarrollo y producción
se leen del archivo .env (ver .env.example).
"""
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
# Clave para cifrar los secretos guardados en la base (token de Nubefact, código del celular). Vacía = la SECRET_KEY.
CLAVE_CIFRADO = env("CLAVE_CIFRADO", default="")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# En Render la dirección pública llega en esta variable
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

# Panel /admin/ de Django: permite editar cualquier tabla sin dejar rastro (ventas, cierres de caja…). Todo se maneja
# desde las pantallas del sistema, así que en producción viene apagado; se enciende solo para una revisión puntual.
ADMIN_ACTIVO = env.bool("ADMIN_ACTIVO", default=DEBUG)

# Cuántos proxies de confianza hay delante (Render / DigitalOcean = 1). Con 0 se usa la IP de la conexión; con 1 o más,
# la que deja el proxy en X-Forwarded-For (para el bloqueo de ingresos y la bitácora). Nunca más de los que hay de verdad:
# si no, un atacante podría inventarse la IP.
PROXIES_CONFIABLES = env.int("PROXIES_CONFIABLES", default=0)

# Modo demostración: muestra un aviso y los usuarios de prueba, y no deja cambiar contraseñas
DEMO = env.bool("DEMO", default=False)

# Nombre del negocio que se muestra mientras no se llenen los Datos del negocio
NEGOCIO_NOMBRE = env("NEGOCIO_NOMBRE", default="Mi Negocio")
NEGOCIO_NOMBRE_CORTO = env("NEGOCIO_NOMBRE_CORTO", default="SisVentas")


# --- Aplicaciones -----------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "django_htmx",
]

LOCAL_APPS = [
    "core",
    "productos",
    "personal",
    "ventas",
    "caja",
    "mesas",
    "clientes",
    "reportes",
    "facturacion",
    "cobranzas",
    "reservas",
    "citas",
    "compras",
    "impresion",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "core.salud.SaludMiddleware",  # /salud/ para el hosting: primero de todo
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "core.middleware.ModoDemoMiddleware",
    "core.bitacora.BitacoraMiddleware",
    "core.dos_factor.SegundoFactorMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.negocio",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Base de datos ----------------------------------------------------------
# Por defecto SQLite (desarrollo). En producción, poner en .env por ejemplo:
# DATABASE_URL=postgres://usuario:clave@localhost:5432/sistventas

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    # Reusar la conexión entre peticiones (segundos) y comprobarla antes de usarla
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Contraseñas ------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "core.validadores.ClaveAdministracion"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:inicio"
LOGOUT_REDIRECT_URL = "login"


# --- Idioma y zona horaria --------------------------------------------------

LANGUAGE_CODE = "es"  # siempre en español, sin importar el idioma del navegador
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["config.formats"]
USE_THOUSAND_SEPARATOR = False  # evita "2 027" en los años; para montos usamos intcomma


# --- Archivos estáticos y subidos -------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/archivos/"  # se sirven con control de acceso (core.views.archivo), nunca públicos
MEDIA_ROOT = BASE_DIR / "media"
# Archivos temporales que nunca se publican (caché, importaciones)
ARCHIVOS_PRIVADOS = BASE_DIR / "privado"

# Fotos y logo en DigitalOcean Spaces (producción): basta con poner SPACES_BUCKET y sus claves en las variables de
# entorno. Un solo espacio para todas las empresas, cada una en su carpeta (SPACES_CARPETA). Es privado: las imágenes
# siempre pasan por /archivos/ con el permiso de quien las pide. Sin SPACES_BUCKET se guardan en la carpeta media/.
SPACES_BUCKET = env("SPACES_BUCKET", default="")
if SPACES_BUCKET:
    ALMACEN_ARCHIVOS = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": SPACES_BUCKET,
            "endpoint_url": env("SPACES_ENDPOINT", default="https://sfo3.digitaloceanspaces.com"),
            "region_name": env("SPACES_REGION", default="sfo3"),
            "access_key": env("SPACES_KEY"),
            "secret_key": env("SPACES_SECRET"),
            "location": env("SPACES_CARPETA", default="empresa"),
            "default_acl": "private",
            "file_overwrite": False,
            "querystring_auth": True,
        },
    }
else:
    ALMACEN_ARCHIVOS = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": ALMACEN_ARCHIVOS,
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}


# --- Formularios (crispy + Bootstrap 5) -------------------------------------

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"


# --- Mensajes con clases de Bootstrap ---------------------------------------

from django.contrib.messages import constants as messages  # noqa: E402

MESSAGE_TAGS = {
    messages.DEBUG: "secondary",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}


# --- Caché (también guarda los intentos fallidos de ingreso) ---------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "privado" / "cache",
    },
    # Intentos fallidos de ingreso: en la base (tabla creada por la migración core/0016), compartidos
    # entre todos los procesos y servidores de la empresa.
    "seguridad": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "core_cache_seguridad",
    },
}

# Código del celular (segundo factor) obligatorio para Administración: por defecto en producción;
# apagado en la PC local (DEBUG), en las demos y al correr las pruebas.
# Obligar a Administración a usar la app de códigos. Ahora lo decide cada negocio (Datos del negocio → «Pedir un código…»,
# por correo o app); esto queda solo para exigir la app desde el servidor.
DOS_FACTOR_OBLIGATORIO = env.bool("DOS_FACTOR_OBLIGATORIO", default=False) and "test" not in sys.argv[1:2]


# --- Sesiones ----------------------------------------------------------------

SESSION_COOKIE_AGE = env.int("SESSION_DIAS", default=7) * 24 * 3600  # luego hay que volver a ingresar
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "SAMEORIGIN"  # las impresiones se arman en un marco oculto de la misma página
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"


# --- Seguridad en producción ------------------------------------------------

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    if len(SECRET_KEY) < 40 or SECRET_KEY.startswith(("cambia", "django-insecure")):
        raise ImproperlyConfigured("Pon una SECRET_KEY larga y secreta en el .env antes de usar el sistema en producción.")
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]  # HSTS sin subdominios ni preload (a propósito)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True


# --- Avisos de errores ---------------------------------------------------------
# Si el sistema falla (error 500), se manda un correo con el detalle a ALERTAS_CORREO (separar con comas).
# El correo sale por EMAIL_URL, por ejemplo smtp+tls://usuario:clave@smtp.gmail.com:587 (Gmail con «contraseña de
# aplicación») o el SMTP de un servicio de correos. Sin EMAIL_URL no se envía nada; los errores igual quedan en el
# registro (logs) del hosting.
ADMINS = [("Soporte", c.strip()) for c in env.list("ALERTAS_CORREO", default=[]) if c.strip()]
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
SERVER_EMAIL = DEFAULT_FROM_EMAIL = env("CORREO_REMITENTE", default="sistema@localhost")
EMAIL_SUBJECT_PREFIX = f"[{NEGOCIO_NOMBRE_CORTO}] "
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "consola": {"class": "logging.StreamHandler"},
        "correo": {"class": "django.utils.log.AdminEmailHandler", "level": "ERROR", "include_html": False},
    },
    "root": {"handlers": ["consola"], "level": "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["consola"] + (["correo"] if ADMINS and not DEBUG else []), "level": "ERROR", "propagate": False},
    },
}
