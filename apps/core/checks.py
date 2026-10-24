from django.conf import settings
from django.core.checks import Warning, register

_TRANSACTION_POOLER_PORT = "6543"  # puerto convencional de PgBouncer en modo transaction
_HINT = (
    "Usa la conexión directa a PostgreSQL o un pooler configurado en modo "
    "session, no transaction."
)


@register()
def check_connection_pooling_mode(app_configs, **kwargs):
    """
    django-tenants cambia de esquema con SET search_path, que es estado de sesión.
    Un pooler de PostgreSQL en modo *transaction* rompe el aislamiento entre tenants
    de forma silenciosa e intermitente: funciona en desarrollo y falla bajo carga en
    producción, mezclando datos entre laboratorios. Es el peor bug posible en este
    sistema, así que se advierte en cada arranque.
    """
    errors = []

    db_config = settings.DATABASES.get("default", {})
    port = str(db_config.get("PORT") or "")
    options = db_config.get("OPTIONS", {}) or {}

    suspicious_port = port == _TRANSACTION_POOLER_PORT
    suspicious_options = any("pgbouncer" in str(v).lower() for v in options.values())

    if suspicious_port or suspicious_options:
        errors.append(
            Warning(
                "La configuración de base de datos parece apuntar a un pooler en modo "
                "'transaction' (puerto 6543 o una opción con 'pgbouncer' detectada). "
                "django-tenants requiere conexión directa o pooling en modo 'session'.",
                hint=_HINT,
                id="ordolab.W001",
            )
        )

    return errors
