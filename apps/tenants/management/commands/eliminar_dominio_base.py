from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Retira un dominio base ya abandonado.

    Es la segunda mitad de `agregar_dominio_base`, y va mucho después: sólo
    cuando el dominio nuevo esté probado con un envío de formulario real, no
    con la página cargando. Un dominio borrado de aquí deja de resolver a
    laboratorio alguno y la aplicación devuelve 404 sin más explicación.

    Dos resguardos, porque esto corre contra producción:
    nunca deja a un laboratorio sin ningún dominio, y si lo que borró era el
    primario, asciende a primario alguno de los que quedan — django-tenants no
    lo hace solo, y un laboratorio sin primario rompe la generación de enlaces.
    """

    help = "Borra los dominios de los laboratorios que cuelgan de un dominio base."

    def add_arguments(self, parser):
        parser.add_argument("--base", required=True, help="Por ejemplo: biolifeve.com")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumera lo que haría sin borrar nada.",
        )

    def handle(self, *args, **options):
        base = options["base"].strip().lower().strip(".")
        if "." not in base:
            raise CommandError(f"'{base}' no parece un dominio.")

        sufijo = f".{base}"
        borrados = omitidos = 0

        with schema_context(get_public_schema_name()):
            for tenant in Tenant.objects.order_by("schema_name"):
                dominios = list(tenant.domains.all())
                condenados = [d for d in dominios if d.domain == base or d.domain.endswith(sufijo)]
                if not condenados:
                    continue

                sobrevivientes = [d for d in dominios if d not in condenados]
                if not sobrevivientes:
                    self.stdout.write(
                        self.style.ERROR(
                            f"{tenant.schema_name}: se quedaría sin ningún dominio. "
                            f"Se omite — corre antes `agregar_dominio_base`."
                        )
                    )
                    omitidos += 1
                    continue

                nombres = ", ".join(d.domain for d in condenados)
                if options["dry_run"]:
                    self.stdout.write(
                        f"{tenant.schema_name}: borraría {nombres} "
                        f"(quedaría {', '.join(d.domain for d in sobrevivientes)})."
                    )
                    continue

                for dominio in condenados:
                    dominio.delete()
                    borrados += 1

                if not tenant.domains.filter(is_primary=True).exists():
                    ascendido = tenant.domains.order_by("pk").first()
                    ascendido.is_primary = True
                    ascendido.save()
                    aviso = f"{tenant.schema_name}: {ascendido.domain} pasa a primario."
                    self.stdout.write(self.style.WARNING(aviso))

                self.stdout.write(self.style.SUCCESS(f"{tenant.schema_name}: borrado {nombres}."))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no se borró nada."))
        else:
            resumen = f"Dominios borrados: {borrados} — laboratorios omitidos: {omitidos}"
            self.stdout.write(self.style.SUCCESS(resumen))
