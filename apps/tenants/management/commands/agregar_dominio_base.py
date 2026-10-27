from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Mudanza de dominio base sin cortar nada.

    `BASE_DOMAIN` sólo se consulta al aprovisionar (provision_tenant), así que
    cambiarlo no toca a los laboratorios que ya existen: sus filas en `Domain`
    siguen apuntando al dominio viejo y cualquier otro host devuelve 404, porque
    es contra esa tabla que django-tenants resuelve la petición.

    Este comando le agrega a cada laboratorio un segundo dominio bajo la base
    nueva, conservando el subdominio que ya tenía. Los dos responden a la vez:
    el viejo se borra aparte, cuando no queden enlaces circulando.
    """

    help = "Agrega a cada laboratorio un dominio bajo un dominio base nuevo."

    def add_arguments(self, parser):
        parser.add_argument("--base", required=True, help="Por ejemplo: lab.ordove.com")
        parser.add_argument(
            "--primario",
            action="store_true",
            help="Deja el dominio nuevo como primario. El viejo sigue respondiendo; "
            "lo primario sólo decide qué host arma la aplicación cuando genera un enlace.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumera lo que haría sin escribir nada.",
        )

    def handle(self, *args, **options):
        base = options["base"].strip().lower().strip(".")
        if "." not in base:
            raise CommandError(f"'{base}' no parece un dominio.")

        creados = omitidos = 0

        # Domain vive en el esquema public, sin importar desde dónde se invoque.
        with schema_context(get_public_schema_name()):
            for tenant in Tenant.objects.order_by("schema_name"):
                primario = tenant.domains.filter(is_primary=True).first()
                if primario is None:
                    self.stdout.write(
                        self.style.WARNING(f"{tenant.schema_name}: sin dominio primario, se omite.")
                    )
                    omitidos += 1
                    continue

                subdominio = primario.domain.split(".")[0]
                nuevo = f"{subdominio}.{base}"

                if tenant.domains.filter(domain=nuevo).exists():
                    self.stdout.write(f"{tenant.schema_name}: {nuevo} ya existe.")
                    omitidos += 1
                    continue

                if options["dry_run"]:
                    self.stdout.write(f"{tenant.schema_name}: crearía {nuevo} (desde {primario.domain}).")
                    continue

                # Domain.save() de django-tenants degrada solo a los demás dominios
                # del laboratorio cuando éste entra como primario.
                tenant.domains.create(domain=nuevo, is_primary=options["primario"])
                creados += 1
                self.stdout.write(self.style.SUCCESS(f"{tenant.schema_name}: {nuevo} creado."))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no se escribió nada."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Dominios creados: {creados} — omitidos: {omitidos}"))
