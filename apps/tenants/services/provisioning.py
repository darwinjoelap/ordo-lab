import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.accounts.services.user_management import create_initial_admin, create_support_user
from apps.billing.services.seeding import seed_billing_defaults
from apps.catalog.services.seeding import seed_uroanalisis
from apps.catalog.services.seeding_containers import seed_containers
from apps.catalog.services.seeding_critical_values import seed_critical_values
from apps.catalog.services.seeding_observations import seed_observation_templates
from apps.catalog.services.seeding_profiles import seed_profiles
from apps.catalog.services.seeding_reference_ranges import seed_reference_ranges
from apps.core.exceptions import ApplicationError
from apps.patients.services.seeding_antecedents import seed_antecedents
from apps.settings_lab.services.branding import create_default_settings
from apps.tenants.models import Plan, Subscription, Tenant

_SCHEMA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
_RESERVED_PREFIXES = ("public", "pg_", "information_schema")


def provision_tenant(
    *,
    name: str,
    schema_name: str,
    subdomain: str,
    admin_email: str,
    admin_password: str | None = None,
    plan: Plan | None = None,
    rif: str | None = None,
    trial_days: int = 30,
    seed_catalog: bool = True,
) -> tuple[Tenant, str]:
    """
    Crea el laboratorio, su esquema, su dominio primario, su suscripción de prueba,
    su usuario ADMIN_LAB inicial y el usuario de soporte de Ordo Lab. Idempotente
    respecto al tenant: si el schema_name ya existe, levanta ApplicationError sin
    tocar nada.

    Devuelve `(tenant, admin_password)`. `admin_password` es la contraseña dada
    o, si no se dio ninguna, la temporal generada — el llamador decide si la
    imprime (el comando de management sí; nunca queda en un log).

    La creación del `Tenant` siempre se ejecuta en el esquema public, sin
    importar el esquema activo del llamador — django-tenants lo exige así.

    Con `seed_catalog=True` (por defecto) el laboratorio nace listo para trabajar:
    catálogo base con rangos y fórmulas, perfiles, tubos de toma, monedas y lista de precios vacía
    (ADR-021). Todo es editable después por el propio laboratorio.
    """
    if not _SCHEMA_NAME_RE.match(schema_name) or schema_name.startswith(_RESERVED_PREFIXES):
        raise ApplicationError(
            f"'{schema_name}' no es un nombre de esquema válido.",
            extra={"schema_name": schema_name},
        )

    with schema_context(get_public_schema_name()):
        if Tenant.objects.filter(schema_name=schema_name).exists():
            raise ApplicationError(
                f"Ya existe un laboratorio con el esquema '{schema_name}'.",
                extra={"schema_name": schema_name},
            )

        with transaction.atomic():
            tenant = Tenant(
                name=name,
                schema_name=schema_name,
                rif=rif,
                trial_ends_at=timezone.now() + timedelta(days=trial_days),
            )
            try:
                tenant.save()  # crea el esquema (auto_create_schema=True)
            except Exception:
                # Si el esquema quedó a medias, django-tenants no lo limpia solo.
                Tenant.objects.filter(schema_name=schema_name).delete()
                raise

            base_domain = getattr(settings, "BASE_DOMAIN", "localhost")
            tenant.domains.create(domain=f"{subdomain}.{base_domain}", is_primary=True)

            if plan is not None:
                Subscription.objects.create(
                    tenant=tenant,
                    plan=plan,
                    status=Subscription.Status.TRIAL,
                    current_period_start=timezone.now(),
                    current_period_end=timezone.now() + timedelta(days=trial_days),
                )

    # Fuera del transaction.atomic() de public: el esquema del tenant ya existe
    # (se creó en tenant.save()) y create_initial_admin corre dentro de su propia
    # conexión/esquema, no tiene sentido anidarlo en la transacción de public.
    with schema_context(schema_name):
        _, admin_password = create_initial_admin(email=admin_email, password=admin_password)
        # Usuario de soporte de Ordo Lab (ADR-045): nace visible en Configuración →
        # Usuarios y sin contraseña utilizable. Para que alguien pueda entrar con él hay
        # que correr `clave_soporte` después de crear el laboratorio.
        create_support_user()
        create_default_settings()
        if seed_catalog:
            seed_uroanalisis()
            seed_reference_ranges()
            seed_profiles()
            seed_containers()
            seed_critical_values()
            seed_observation_templates()
            seed_antecedents()
            seed_billing_defaults()

    return tenant, admin_password
