"""Los dos comandos que mudan el dominio base (ADR-037).

Aquí no se aprovisionan laboratorios de verdad. `provision_tenant` crea un esquema y le
corre todas las migraciones, y lo que estos comandos tocan son filas de `Tenant` y
`Domain`, nada más. Con `auto_create_schema = False` el laboratorio es una fila y las
pruebas bajan de minutos a milisegundos.

Lo que se verifica no es el camino feliz —ése ya corrió en producción el 2026-10-27—
sino los dos resguardos del borrado, que son los que nadie ve hasta que fallan: no dejar
a un laboratorio sin ningún dominio, y ascender un primario cuando el que se quita lo era.
"""
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.tenants.models import Domain, Tenant


def _laboratorio(schema_name: str, dominio: str) -> Tenant:
    tenant = Tenant(name=f"Lab {schema_name}", schema_name=schema_name)
    tenant.auto_create_schema = False
    tenant.save()
    Domain.objects.create(tenant=tenant, domain=dominio, is_primary=True)
    return tenant


def _correr(comando: str, **opciones) -> str:
    salida = io.StringIO()
    call_command(comando, stdout=salida, stderr=salida, **opciones)
    return salida.getvalue()


def _dominios(tenant: Tenant) -> set[str]:
    return set(tenant.domains.values_list("domain", flat=True))


@pytest.fixture
def lab(db):
    return _laboratorio("lab_uno", "uno.viejo.com")


class TestAgregar:
    def test_conserva_el_subdominio_bajo_la_base_nueva(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com")
        assert _dominios(lab) == {"uno.viejo.com", "uno.nuevo.com"}

    def test_dry_run_no_escribe(self, lab):
        salida = _correr("agregar_dominio_base", base="nuevo.com", dry_run=True)
        assert "crearía uno.nuevo.com" in salida
        assert _dominios(lab) == {"uno.viejo.com"}

    def test_sin_primario_el_nuevo_no_lo_es(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com")
        assert lab.domains.get(domain="uno.viejo.com").is_primary is True
        assert lab.domains.get(domain="uno.nuevo.com").is_primary is False

    def test_con_primario_degrada_al_anterior(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com", primario=True)
        assert lab.domains.get(domain="uno.nuevo.com").is_primary is True
        assert lab.domains.get(domain="uno.viejo.com").is_primary is False

    def test_repetirlo_no_duplica(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com")
        salida = _correr("agregar_dominio_base", base="nuevo.com")
        assert "ya existe" in salida
        assert len(_dominios(lab)) == 2

    def test_una_base_sin_punto_se_rechaza(self, db):
        with pytest.raises(CommandError):
            _correr("agregar_dominio_base", base="noesundominio")


class TestEliminar:
    def test_borra_los_del_dominio_viejo(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com", primario=True)
        _correr("eliminar_dominio_base", base="viejo.com")
        assert _dominios(lab) == {"uno.nuevo.com"}

    def test_dry_run_no_borra(self, lab):
        _correr("agregar_dominio_base", base="nuevo.com")
        salida = _correr("eliminar_dominio_base", base="viejo.com", dry_run=True)
        assert "borraría uno.viejo.com" in salida
        assert _dominios(lab) == {"uno.viejo.com", "uno.nuevo.com"}

    def test_nunca_deja_a_un_laboratorio_sin_dominio(self, lab):
        """Primer resguardo. Sin él, correr el borrado antes de agregar deja al
        laboratorio inalcanzable: django-tenants resuelve contra esta tabla y un host
        ausente de ella devuelve 404."""
        salida = _correr("eliminar_dominio_base", base="viejo.com")
        assert "se quedaría sin ningún dominio" in salida
        assert _dominios(lab) == {"uno.viejo.com"}

    def test_asciende_un_primario_si_borro_el_que_lo_era(self, lab):
        """Segundo resguardo. django-tenants no lo hace solo, y un laboratorio sin
        dominio primario rompe la generación de enlaces."""
        _correr("agregar_dominio_base", base="nuevo.com")  # el nuevo NO entra como primario
        assert lab.domains.get(domain="uno.viejo.com").is_primary is True

        salida = _correr("eliminar_dominio_base", base="viejo.com")

        assert "pasa a primario" in salida
        assert lab.domains.get(domain="uno.nuevo.com").is_primary is True

    def test_no_toca_a_quien_no_cuelga_de_esa_base(self, lab):
        otro = _laboratorio("lab_dos", "dos.otracosa.com")
        _correr("agregar_dominio_base", base="nuevo.com", primario=True)
        _correr("eliminar_dominio_base", base="viejo.com")
        assert _dominios(otro) == {"dos.otracosa.com", "dos.nuevo.com"}

    def test_no_confunde_un_dominio_que_solo_termina_parecido(self, db):
        """`otroviejo.com` no cuelga de `viejo.com`: el sufijo se compara con el punto."""
        trampa = _laboratorio("lab_tres", "tres.otroviejo.com")
        _correr("agregar_dominio_base", base="nuevo.com")
        _correr("eliminar_dominio_base", base="viejo.com")
        assert "tres.otroviejo.com" in _dominios(trampa)
