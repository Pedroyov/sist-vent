"""
Configuración del Sistema de Ventas.

Los valores sensibles o que cambian entre desarrollo y producción
se leen del archivo .env (ver .env.example).
"""
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
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# En Render la dirección pública llega en esta variable
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

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
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Contraseñas ------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
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

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
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
    }
}


# --- Sesiones ----------------------------------------------------------------

SESSION_COOKIE_AGE = env.int("SESSION_DIAS", default=7) * 24 * 3600  # luego hay que volver a ingresar
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
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
