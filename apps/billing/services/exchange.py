"""Tasas de cambio y conversión entre monedas del tenant.

De dónde sale la tasa (ADR-035): el laboratorio puede cargar la suya en
`billing.ExchangeRate`, y además existe la **tasa oficial global**
(`masterdata.OfficialRate`) que el cron trae del BCV cada día y que ven todos los
laboratorios. Gana la de fecha más reciente; en empate manda la del laboratorio,
porque si la cargó a mano fue por algo.
"""
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.billing.models import Currency, ExchangeRate
from apps.core.exceptions import ApplicationError
from apps.masterdata.models import OfficialRate

# Prioridad en empate de fechas: el laboratorio por encima de la tasa global.
_TENANT, _GLOBAL = 1, 0

LABORATORIO = "laboratorio"
BCV = "BCV"
OFICIAL = "oficial"


@dataclass(frozen=True)
class RateInfo:
    """La tasa que se va a aplicar, con de dónde salió.

    Existe para que la pantalla de precios pueda mostrar **la misma** tasa que usan los
    montos. Antes leía sólo `ExchangeRate` y decía "sin registrar" aunque la oficial
    estuviera vigente, lo que invitaba a teclear una a mano y anular el automatismo.

    Los nombres `rate` y `effective_date` son deliberados: son los de `ExchangeRate` y
    `OfficialRate`, así la plantilla no distingue.
    """

    rate: Decimal
    effective_date: datetime.date
    origin: str


def _origin_of(official: OfficialRate) -> str:
    return BCV if official.source == OfficialRate.Source.BCV else OFICIAL


def _tenant_candidates(
    *, from_currency: Currency, to_currency: Currency, on_date: datetime.date
) -> list[tuple[datetime.date, int, Decimal]]:
    direct = (
        ExchangeRate.objects.filter(
            from_currency=from_currency, to_currency=to_currency,
            effective_date__lte=on_date, is_active=True,
        )
        .order_by("-effective_date")
        .first()
    )
    inverse = (
        ExchangeRate.objects.filter(
            from_currency=to_currency, to_currency=from_currency,
            effective_date__lte=on_date, is_active=True,
        )
        .order_by("-effective_date")
        .first()
    )
    candidates = []
    if direct:
        candidates.append((direct.effective_date, _TENANT, direct.rate, LABORATORIO))
    # La inversa sólo entra si no hay directa o es más reciente: con la misma fecha,
    # manda la directa (es el comportamiento que ya tenía y que los tests fijan).
    if inverse and (not direct or inverse.effective_date > direct.effective_date):
        candidates.append(
            (inverse.effective_date, _TENANT, Decimal(1) / inverse.rate, LABORATORIO)
        )
    return candidates


def _global_candidates(
    *, from_currency: Currency, to_currency: Currency, on_date: datetime.date
) -> list[tuple[datetime.date, int, Decimal]]:
    """La tasa oficial vive en `public`; se lee por código ISO, no por FK, porque
    `Currency` es un modelo de tenant y desde el esquema público no existe."""
    direct = (
        OfficialRate.objects.filter(
            from_code=from_currency.code, to_code=to_currency.code,
            effective_date__lte=on_date,
        )
        .order_by("-effective_date")
        .first()
    )
    if direct:
        return [(direct.effective_date, _GLOBAL, direct.rate, _origin_of(direct))]
    inverse = (
        OfficialRate.objects.filter(
            from_code=to_currency.code, to_code=from_currency.code,
            effective_date__lte=on_date,
        )
        .order_by("-effective_date")
        .first()
    )
    if inverse:
        return [
            (inverse.effective_date, _GLOBAL, Decimal(1) / inverse.rate,
             _origin_of(inverse))
        ]
    return []


def resolve_exchange_rate(
    *, from_currency: Currency, to_currency: Currency, on_date: datetime.date
) -> RateInfo | None:
    """La tasa que gana en `on_date`, con su fecha y su origen — o `None` si no hay.

    Es el único lugar donde se decide la precedencia. `get_exchange_rate` devuelve sólo
    el número; la pantalla de precios necesita además de dónde salió, y las dos tienen
    que coincidir siempre.
    """
    if from_currency.pk == to_currency.pk:
        return RateInfo(rate=Decimal(1), effective_date=on_date, origin=LABORATORIO)
    candidates = _tenant_candidates(
        from_currency=from_currency, to_currency=to_currency, on_date=on_date
    ) + _global_candidates(
        from_currency=from_currency, to_currency=to_currency, on_date=on_date
    )
    if not candidates:
        return None
    effective_date, _, rate, origin = max(candidates, key=lambda c: (c[0], c[1]))
    return RateInfo(rate=rate, effective_date=effective_date, origin=origin)


def get_exchange_rate(
    *, from_currency: Currency, to_currency: Currency, on_date: datetime.date
) -> Decimal:
    """Tasa vigente en `on_date` (la más reciente con fecha <= on_date), mirando la del
    laboratorio y la oficial. Si sólo existe la inversa, se usa 1/tasa. Lanza
    `ApplicationError` si no hay ninguna — nunca devuelve una tasa inventada."""
    info = resolve_exchange_rate(
        from_currency=from_currency, to_currency=to_currency, on_date=on_date
    )
    if info is None:
        raise ApplicationError(
            f"No hay tasa de cambio {from_currency.code} → {to_currency.code} vigente al "
            f"{on_date:%d/%m/%Y}."
        )
    return info.rate


def convert_amount(
    *, amount: Decimal, from_currency: Currency, to_currency: Currency,
    on_date: datetime.date,
) -> Decimal:
    """Convierte con precisión completa (el redondeo lo decide quien muestra)."""
    rate = get_exchange_rate(
        from_currency=from_currency, to_currency=to_currency, on_date=on_date
    )
    return amount * rate


def round_money(amount: Decimal, *, currency: Currency) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-currency.decimals), rounding=ROUND_HALF_UP)


def register_exchange_rate(
    *, from_currency: Currency, to_currency: Currency, rate: Decimal,
    effective_date: datetime.date, source: str = ExchangeRate.Source.MANUAL,
    notes: str = "",
) -> ExchangeRate:
    """Registra (o corrige) la tasa **del laboratorio** para una fecha. Una por par y
    fecha. La tasa oficial global se registra aparte, en `masterdata.services.bcv`."""
    if rate <= 0:
        raise ApplicationError("La tasa de cambio debe ser mayor que cero.")
    if from_currency.pk == to_currency.pk:
        raise ApplicationError("La tasa debe ser entre dos monedas distintas.")
    exchange_rate, _ = ExchangeRate.objects.update_or_create(
        from_currency=from_currency, to_currency=to_currency, effective_date=effective_date,
        defaults={"rate": rate, "source": source, "notes": notes, "is_active": True},
    )
    return exchange_rate
