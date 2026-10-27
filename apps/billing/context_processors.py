"""La tasa del día, disponible en la barra superior de todas las pantallas.

Se calcula con `SimpleLazyObject`: si una plantilla no la nombra, no hay consulta. La
barra superior sí la nombra, así que en la práctica son dos consultas por página — una
por la moneda base y otra por la tasa. Si alguna vez pesa, el sitio para cachearla es
aquí, por esquema y por día.
"""
from django.utils.functional import SimpleLazyObject

from apps.billing.selectors.price_queries import base_currency, latest_rates


def _rate_of_the_day():
    """La primera moneda con tasa vigente, o `None`.

    Un laboratorio venezolano tiene una sola conversión que mirar —el dólar— así que la
    barra muestra la primera y no una lista. El detalle completo está en *Precios*.
    """
    base = base_currency()
    if base is None:
        return None
    for row in latest_rates():
        if row["rate"] is not None:
            return {"base": base, "currency": row["currency"], "info": row["rate"]}
    return None


def exchange_rate(request):
    tenant = getattr(request, "tenant", None)
    if tenant is None or tenant.schema_name == "public":
        return {}
    return {"topbar_rate": SimpleLazyObject(_rate_of_the_day)}
