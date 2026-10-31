"""Pone la contraseña del usuario de soporte de Ordo Lab (ADR-045).

Una sola clave para todos los laboratorios, escrita en cada esquema. No vive en el
código, ni en los ajustes, ni en una variable de entorno: se teclea aquí y sólo queda
el hash en cada base.

    python manage.py clave_soporte
    python manage.py clave_soporte --schema angelus
"""
import getpass

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.accounts.services.user_management import SUPPORT_USERNAME, set_support_password
from apps.tenants.models import Tenant

MINIMO = 12


class Command(BaseCommand):
    help = f"Pone la contraseña de «{SUPPORT_USERNAME}» en uno o en todos los laboratorios."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=None, help="Sólo este laboratorio.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(schema_name=get_public_schema_name())
        if options["schema"]:
            tenants = tenants.filter(schema_name=options["schema"])
            if not tenants.exists():
                raise CommandError(f"No hay laboratorio con el esquema '{options['schema']}'.")

        password = getpass.getpass("Contraseña de soporte: ")
        if password != getpass.getpass("Repítala: "):
            raise CommandError("Las contraseñas no coinciden.")
        # Esta clave abre los datos clínicos de todos los laboratorios a la vez; el
        # mínimo de Django (8) es corto para lo que aquí está en juego.
        if len(password) < MINIMO:
            raise CommandError(f"Use al menos {MINIMO} caracteres: esta clave abre todos "
                               "los laboratorios.")

        puestas, sin_usuario = 0, []
        for tenant in tenants.order_by("schema_name"):
            with schema_context(tenant.schema_name):
                if set_support_password(password=password):
                    puestas += 1
                    self.stdout.write(self.style.SUCCESS(f"{tenant.schema_name}: puesta."))
                else:
                    sin_usuario.append(tenant.schema_name)
                    self.stdout.write(self.style.WARNING(
                        f"{tenant.schema_name}: no tiene usuario de soporte."))

        self.stdout.write(self.style.SUCCESS(f"Claves puestas: {puestas}."))
        if sin_usuario:
            self.stdout.write(self.style.WARNING(
                "Sin usuario de soporte (lo borraron, o se aprovisionaron antes de que "
                "existiera): " + ", ".join(sin_usuario) + ". No se crea solo a propósito: "
                "un laboratorio que lo quitó no debe recuperarlo sin saberlo."
            ))
