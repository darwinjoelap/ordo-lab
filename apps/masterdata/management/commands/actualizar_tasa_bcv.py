"""Tarea programada: trae la tasa oficial del BCV y la registra para hoy.

En Railway va en un servicio aparte, del mismo repositorio, con
`Settings → Cron Schedule` y este comando como `startCommand`. El proceso debe
terminar: si queda corriendo, Railway se salta la siguiente ejecución.

    python manage.py actualizar_tasa_bcv

Nunca lanza excepción: un cron que muere deja de correr, y una tasa que no se pudo
actualizar no es motivo para tumbar la tarea. El fallo queda en el log (y en Sentry).
La tasa anterior se conserva intacta: nunca se borra ni se pisa con un valor dudoso.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from apps.masterdata.services import bcv


class Command(BaseCommand):
    help = "Consulta la tasa USD del BCV y la registra como tasa oficial de hoy."

    def handle(self, *args, **options):
        try:
            # La tasa oficial es global: se escribe en `public`. El cambio de esquema va
            # aquí y no en el servicio, para no alterarle la conexión a quien lo llame
            # desde dentro de un laboratorio. `schema_context` lo devuelve como estaba.
            with schema_context(get_public_schema_name()):
                rate = bcv.update_from_bcv()
        except Exception as exc:  # noqa: BLE001 - el cron no debe caerse
            bcv.log.error("No se pudo actualizar la tasa del BCV: %s", exc)
            self.stderr.write(self.style.ERROR(f"Tasa BCV no actualizada: {exc}"))
            return
        self.stdout.write(self.style.SUCCESS(f"Tasa oficial registrada: {rate}"))
