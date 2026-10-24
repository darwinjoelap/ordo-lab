"""Lectura del HTML del BCV y registro de la tasa oficial (ADR-035).

No se toca la red: el HTML es una muestra con la forma real de la página.
"""
import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.masterdata.models import OfficialRate
from apps.masterdata.services import bcv

HTML_BCV = """
<html><body>
  <div id="euro"><div class="centrado"><strong> 201,33 </strong></div></div>
  <div id="dolar"><div class="centrado"><strong> 1.234,56789012 </strong></div></div>
</body></html>
"""


def test_lee_la_tasa_con_formato_venezolano():
    """Punto de miles y coma decimal: 1.234,56789012 son mil doscientos treinta y cuatro."""
    assert bcv.read_rate_from_html(HTML_BCV) == Decimal("1234.56789012")


def test_no_confunde_el_dolar_con_el_euro():
    assert bcv.read_rate_from_html(HTML_BCV) != Decimal("201.33")


def test_falla_si_no_esta_el_bloque_del_dolar():
    with pytest.raises(ValueError, match="bloque del dólar"):
        bcv.read_rate_from_html("<html><body><p>mantenimiento</p></body></html>")


def test_falla_si_el_valor_no_es_numerico():
    html = '<div id="dolar"><strong>no disponible</strong></div>'
    with pytest.raises(ValueError, match="no numérico"):
        bcv.read_rate_from_html(html)


def test_rechaza_una_tasa_de_cero():
    html = '<div id="dolar"><strong>0,00</strong></div>'
    with pytest.raises(ValueError, match="mayor que cero"):
        bcv.read_rate_from_html(html)


@pytest.mark.django_db
def test_registrar_es_idempotente_por_fecha():
    """Dos corridas el mismo día dejan una sola fila, con el último valor."""
    dia = datetime.date(2026, 10, 20)
    bcv.register_official_rate(rate=Decimal("300"), effective_date=dia)
    bcv.register_official_rate(rate=Decimal("305.5"), effective_date=dia)
    filas = OfficialRate.objects.filter(effective_date=dia)
    assert filas.count() == 1
    assert filas.first().rate == Decimal("305.5")


@pytest.mark.django_db
def test_registrar_rechaza_tasa_no_positiva():
    with pytest.raises(ValueError, match="mayor que cero"):
        bcv.register_official_rate(rate=Decimal("0"))


@pytest.mark.django_db
def test_el_comando_no_revienta_si_el_bcv_falla(monkeypatch):
    """Un cron que lanza excepción deja de correr: el comando traga el error y sale."""
    def explota(*_args, **_kwargs):
        raise RuntimeError("el BCV no responde")

    monkeypatch.setattr(bcv, "download_bcv", explota)
    call_command("actualizar_tasa_bcv")  # no debe lanzar


@pytest.mark.django_db
def test_el_fallo_no_borra_ni_pisa_la_tasa_anterior(monkeypatch):
    ayer = datetime.date(2026, 10, 19)
    bcv.register_official_rate(rate=Decimal("300"), effective_date=ayer)

    def explota(*_args, **_kwargs):
        raise RuntimeError("el BCV no responde")

    monkeypatch.setattr(bcv, "download_bcv", explota)
    call_command("actualizar_tasa_bcv")

    assert OfficialRate.objects.get(effective_date=ayer).rate == Decimal("300")
