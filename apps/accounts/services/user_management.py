from __future__ import annotations

import secrets

from django.core.management import call_command

from apps.accounts.models import Membership, Role, User

# Usuario con el que Ordo Lab da soporte dentro de un laboratorio (ADR-045). El nombre
# lleva el sufijo para que no choque con un «soporte» del propio laboratorio y para que
# quien lo vea en la lista sepa de quién es.
SUPPORT_USERNAME = "soporte-ordolab"


def seed_system_roles() -> None:
    """
    Siembra los 7 roles de tenant desde `apps/accounts/fixtures/roles.json`.
    Idempotente: `loaddata` hace upsert por PK, se puede llamar en cada
    provisionamiento sin duplicar ni fallar si ya existen.
    """
    call_command("loaddata", "roles", verbosity=0)


def create_initial_admin(*, email: str, password: str | None = None) -> tuple[User, str]:
    """
    Crea el usuario ADMIN_LAB inicial de un laboratorio recién provisionado y le
    asigna el rol. Debe llamarse dentro del `schema_context()` del tenant — no
    valida ni cambia el esquema activo.

    Devuelve `(user, password)`. Si `password` es `None`, se genera una temporal
    que el llamador decide si imprime o no (este service nunca la loguea).
    """
    seed_system_roles()

    if password is None:
        password = secrets.token_urlsafe(12)

    username = email.split("@")[0]
    user = User.objects.create_user(username=username, email=email, password=password)

    role = Role.objects.get(code=Role.Code.ADMIN_LAB)
    Membership.objects.create(user=user, role=role)

    return user, password


def create_support_user() -> User:
    """Crea el usuario de soporte de Ordo Lab en el laboratorio (ADR-045).

    Debe llamarse dentro del `schema_context()` del tenant. Es idempotente.

    **Nace sin contraseña utilizable.** No hay ninguna clave de soporte escrita en el
    código, en los ajustes ni en una variable de entorno: la pone el comando
    `clave_soporte`, que la escribe en todos los esquemas de una vez. Un laboratorio
    recién creado tiene el usuario pero nadie puede entrar con él hasta ese momento.
    """
    seed_system_roles()

    user, created = User.objects.get_or_create(
        username=SUPPORT_USERNAME,
        defaults={
            "first_name": "Soporte",
            "last_name": "Ordo Lab",
            "is_support": True,
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])

    role = Role.objects.get(code=Role.Code.ADMIN_LAB)
    Membership.objects.get_or_create(user=user, role=role)
    return user


def set_support_password(*, password: str) -> bool:
    """Pone la contraseña del usuario de soporte en el esquema activo.

    Devuelve `False` si el laboratorio no tiene usuario de soporte, y en ese caso **no
    lo crea**: si el laboratorio lo borró, volver a ponerlo en silencio sería
    exactamente la cuenta oculta que este diseño evita. El comando lo reporta y el
    laboratorio decide.
    """
    user = User.objects.filter(username=SUPPORT_USERNAME).first()
    if user is None:
        return False
    user.set_password(password)
    user.save(update_fields=["password"])
    return True
