"""Usuarios del laboratorio gestionados por su administrador (Fase 11b, ADR-029).

- Alta con clave temporal: el usuario debe cambiarla en su primer ingreso.
- Los roles los define Ordo Lab; el laboratorio sólo los asigna (uno o varios por usuario).
- Nunca se borra un usuario (firma informes, cargó resultados): se desactiva.
- Siempre queda al menos un administrador activo, y nadie se quita a sí mismo el acceso.
- Cada cambio queda en la bitácora (`AuditLog`).
"""
from __future__ import annotations

import secrets
from collections.abc import Iterable

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Membership, Role, User
from apps.accounts.services.audit import log_action
from apps.core.exceptions import ApplicationError

ADMIN = Role.Code.ADMIN_LAB
PROFILE_FIELDS = ("first_name", "last_name", "email", "phone", "professional_title",
                  "professional_license")


def temporary_password() -> str:
    """Clave temporal legible (sin caracteres que se confunden al dictarla)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def role_codes(user: User) -> list[str]:
    return list(user.memberships.filter(is_active=True).values_list("role__code", flat=True))


def _active_admins_except(user: User) -> int:
    return (User.objects.filter(is_active=True, memberships__is_active=True,
                                memberships__role__code=ADMIN)
            .exclude(pk=user.pk).distinct().count())


def _check_roles(codes: Iterable[str]) -> list[str]:
    codes = sorted(set(codes))
    if not codes:
        raise ApplicationError("Asigne al menos un rol.")
    valid = set(Role.objects.filter(code__in=codes).values_list("code", flat=True))
    if valid != set(codes):
        raise ApplicationError("Rol no válido.")
    return codes


@transaction.atomic
def create_lab_user(*, username: str, first_name: str, last_name: str, email: str = "",
                    phone: str = "", roles: Iterable[str], password: str = "",
                    by: User | None = None) -> tuple[User, str]:
    """(usuario, clave temporal). Si no se indica clave, se genera una."""
    username = username.strip().lower()
    if not username:
        raise ApplicationError("Indique el nombre de usuario.")
    if User.objects.filter(username__iexact=username).exists():
        raise ApplicationError(f"El usuario «{username}» ya existe.")
    codes = _check_roles(roles)
    password = password or temporary_password()
    user = User(username=username, first_name=first_name.strip(),
                last_name=last_name.strip(), email=email.strip(), phone=phone.strip(),
                must_change_password=True)
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise ApplicationError(" ".join(exc.messages)) from exc
    user.set_password(password)
    user.save()
    for code in codes:
        Membership.objects.create(user=user, role=Role.objects.get(code=code))
    log_action(action="USUARIO_CREADO", user=by, model_name="accounts.User",
               object_id=str(user.pk), changes={"username": username, "roles": codes})
    return user, password


@transaction.atomic
def update_lab_user(*, user: User, data: dict, roles: Iterable[str],
                    by: User | None = None) -> User:
    """Datos básicos y roles. No permite dejar el laboratorio sin administrador ni que
    el administrador se quite a sí mismo ese rol."""
    codes = _check_roles(roles)
    current = set(role_codes(user))
    if ADMIN in current and ADMIN not in codes:
        if by is not None and by.pk == user.pk:
            raise ApplicationError("No puede quitarse a sí mismo el rol de administrador.")
        if not _active_admins_except(user):
            raise ApplicationError("El laboratorio debe tener al menos un administrador.")
    changes = {}
    for field in PROFILE_FIELDS:
        if field in data and getattr(user, field) != (data[field] or "").strip():
            changes[field] = [getattr(user, field), (data[field] or "").strip()]
            setattr(user, field, (data[field] or "").strip())
    user.save()
    for code in current - set(codes):
        Membership.objects.filter(user=user, role__code=code).delete()
    for code in set(codes) - current:
        Membership.objects.update_or_create(user=user, role=Role.objects.get(code=code),
                                            defaults={"is_active": True})
    if current != set(codes):
        changes["roles"] = [sorted(current), codes]
    if changes:
        log_action(action="USUARIO_MODIFICADO", user=by, model_name="accounts.User",
                   object_id=str(user.pk), changes=changes)
    return user


def set_active(*, user: User, active: bool, by: User | None = None) -> User:
    if not active:
        if by is not None and by.pk == user.pk:
            raise ApplicationError("No puede desactivar su propio usuario.")
        if ADMIN in role_codes(user) and not _active_admins_except(user):
            raise ApplicationError("El laboratorio debe tener al menos un administrador.")
    if user.is_active != active:
        user.is_active = active
        user.save(update_fields=["is_active"])
        log_action(action="USUARIO_ACTIVADO" if active else "USUARIO_DESACTIVADO", user=by,
                   model_name="accounts.User", object_id=str(user.pk))
    return user


def reset_password(*, user: User, by: User | None = None) -> str:
    """Nueva clave temporal (se muestra una sola vez al administrador)."""
    password = temporary_password()
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    log_action(action="CLAVE_RESTABLECIDA", user=by, model_name="accounts.User",
               object_id=str(user.pk))
    return password


# Mi perfil -------------------------------------------------------------------------------
def update_profile(*, form) -> User:
    """El propio usuario: nombre, contacto, datos profesionales, firma y sello (formulario
    ya validado). Una firma nueva se guarda como archivo nuevo: los informes ya emitidos
    conservan la anterior."""
    user = form.save()
    if form.changed_data:
        log_action(action="PERFIL_MODIFICADO", user=user, model_name="accounts.User",
                   object_id=str(user.pk), changes={"campos": form.changed_data})
    return user


def change_password(*, user: User, current: str, new: str) -> User:
    if not user.check_password(current):
        raise ApplicationError("La clave actual no es correcta.")
    if current == new:
        raise ApplicationError("La clave nueva debe ser distinta de la actual.")
    try:
        validate_password(new, user)
    except ValidationError as exc:
        raise ApplicationError(" ".join(exc.messages)) from exc
    user.set_password(new)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    log_action(action="CLAVE_CAMBIADA", user=user, model_name="accounts.User",
               object_id=str(user.pk))
    return user
