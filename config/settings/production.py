"""Producción: Railway + Postgres gestionado + Cloudinary para media (Fase 17).

Cada laboratorio entra por su propio subdominio (`angelus.midominio.com`) y el panel de
plataforma por el dominio raíz: así es como `django-tenants` sabe de qué laboratorio es
cada petición. Por eso `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` llevan el comodín del
dominio, no un host fijo.
"""
from .base import *  # noqa: F401,F403

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

DEBUG = False

# Railway termina el TLS en su proxy y habla HTTP con la aplicación. Sin esta línea,
# Django ve "http", `SECURE_SSL_REDIRECT` vuelve a redirigir a HTTPS y el navegador queda
# en un bucle de redirecciones infinito. Es el error clásico al desplegar detrás de un
# proxy, y va antes que cualquier otro ajuste de seguridad.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

sentry_sdk.init(
    dsn=env("SENTRY_DSN", default=""),
    integrations=[DjangoIntegration()],
    send_default_pii=False,  # datos clínicos: nunca al servicio de errores
)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # no se pide preload hasta tener el dominio definitivo

# El formulario de la recepción y el panel viajan por subdominios distintos: Django 4+
# exige el esquema en cada origen de confianza.
#
# Durante una mudanza de dominio conviven dos: `BASE_DOMAIN`, que es el que arma los
# enlaces nuevos, y el anterior, que sigue respondiendo mientras queden enlaces
# circulando. Los dos tienen que estar listados aquí: si falta el viejo, el dominio
# resuelve y la página carga, pero cualquier formulario enviado desde ahí —el login
# incluido— muere con 403 y el mensaje no explica por qué.
LEGACY_DOMAINS = env.list("LEGACY_DOMAINS", default=[])
CSRF_TRUSTED_ORIGINS = [
    origen
    for dominio in [BASE_DOMAIN, *LEGACY_DOMAINS]
    for origen in (f"https://{dominio}", f"https://*.{dominio}")
]

# --- Media en Cloudinary --------------------------------------------------------------
# Firmas, sellos y logos. `CLOUDINARY_URL` viene de la variable de entorno del mismo
# nombre (cloudinary://clave:secreto@nube), que es como la entrega Cloudinary.
INSTALLED_APPS = [*INSTALLED_APPS, "cloudinary", "cloudinary_storage"]
STORAGES = {
    **STORAGES,
    "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
}

# Los informes y las firmas no son públicos: se entregan por enlace firmado (ADR-027).
CLOUDINARY_STORAGE = {"SECURE": True}

# Sesión: el laboratorio trabaja toda la jornada; expira al cerrar el navegador igual.
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Correo: sin servicio configurado todavía (Fase 17 no incluye envío). Los errores van a
# Sentry, no por correo.
EMAIL_BACKEND = env("EMAIL_BACKEND",
                    default="django.core.mail.backends.console.EmailBackend")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"],
                               "propagate": False},
    },
}
