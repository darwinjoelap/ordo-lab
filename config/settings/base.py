"""
Configuración base de Ordo Lab. Compartida por local, staging y production.
No se ejecuta directamente: cada entorno la importa con `from .base import *`.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
BASE_DOMAIN = env("BASE_DOMAIN", default="localhost")

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",   # PRIMERO, sin excepción
    "apps.settings_lab.middleware.TenantTimezoneMiddleware",
    # Fase 12: bloquea TODO en un laboratorio SUSPENDIDO/MOROSO/CANCELADO, incluso el
    # login, con un aviso fijo. Nunca afecta al esquema public (panel de plataforma).
    "apps.tenants.middleware.TenantAccessMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

SHARED_APPS = [
    "django_tenants",
    "apps.tenants",
    "apps.masterdata",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "apps.accounts",
]

TENANT_APPS = [
    "django.contrib.contenttypes",
    # Admin también por tenant: su bitácora (django_admin_log) apunta a accounts.User, que
    # es por tenant. Sin esto, guardar en /admin/ de un laboratorio escribe en la bitácora
    # de `public` con el id de un usuario que allí no existe (ADR-020).
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "apps.core",
    "apps.accounts",
    "apps.settings_lab",
    "apps.patients",
    "apps.catalog",
    "apps.billing",
    "apps.orders",
    "apps.results",
    "apps.reports",
    "apps.sync",
]

INSTALLED_APPS = list(SHARED_APPS) + [
    a for a in TENANT_APPS if a not in SHARED_APPS
]

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"
# El admin de django-tenants pinta de verde las apps de tenant; choca con el estilo (ADR-022).
TENANT_COLOR_ADMIN_APPS = False

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "tenant-home"
LOGOUT_REDIRECT_URL = "accounts:login"

PUBLIC_SCHEMA_URLCONF = "config.urls_public"
ROOT_URLCONF = "config.urls_tenant"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.settings_lab.context_processors.tenant_settings",
                "apps.accounts.context_processors.ui",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ve"
TIME_ZONE = env("TIME_ZONE", default="America/Caracas")
USE_TZ = True
USE_I18N = True
USE_L10N = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# STORAGES y no STATICFILES_STORAGE: Django 5.1 eliminó ese ajuste y lo ignoraba en
# silencio, así que WhiteNoise nunca comprimía ni versionaba los estáticos (ADR-022).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
