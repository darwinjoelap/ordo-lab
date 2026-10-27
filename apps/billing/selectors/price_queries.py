import datetime

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.billing.models import Currency, Discount, PriceList, PriceListItem
from apps.billing.services.exchange import resolve_exchange_rate


def valid_price_lists(*, on_date: datetime.date) -> QuerySet[PriceList]:
    """Listas activas y vigentes en `on_date`, en el orden definido por el laboratorio."""
    return (
        PriceList.objects.filter(is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on_date))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .select_related("currency")
    )


def default_price_list(*, on_date: datetime.date) -> PriceList | None:
    return valid_price_lists(on_date=on_date).filter(is_default=True).first()


def price_list_by_code(*, code: str) -> PriceList | None:
    return PriceList.objects.select_related("currency").filter(code=code).first()


def currency_by_code(*, code: str) -> Currency | None:
    return Currency.objects.filter(code=code).first()


def price_list_items(*, price_list: PriceList) -> QuerySet[PriceListItem]:
    """Precios de una lista en el orden de presentación (`order_index`)."""
    return (
        price_list.items.filter(is_active=True)
        .select_related("test", "test__section", "profile")
        .order_by("order_index", "test__name", "profile__name")
    )


def usable_discounts(*, on_date: datetime.date) -> QuerySet[Discount]:
    """Descuentos activos y vigentes en `on_date`, para ofrecerlos al registrar una orden."""
    return (
        Discount.objects.filter(is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on_date))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .select_related("currency")
    )


def active_currencies() -> QuerySet[Currency]:
    return Currency.objects.filter(is_active=True)


def discounts_by_codes(*, codes) -> list[Discount]:
    return list(Discount.objects.filter(code__in=list(codes)))


# Pantalla de precios (Fase 11c) ----------------------------------------------------------
def all_price_lists() -> QuerySet[PriceList]:
    return PriceList.objects.filter(is_active=True).select_related("currency").order_by(
        "-is_default", "order_index", "name")


def price_list_by_id(*, pk) -> PriceList:
    return PriceList.objects.select_related("currency").get(pk=pk)


def items_by_target(*, price_list: PriceList) -> tuple[dict, dict]:
    """({test_id: item}, {profile_id: item}) con los precios activos de la lista."""
    tests, profiles = {}, {}
    for item in price_list.items.filter(is_active=True):
        if item.test_id:
            tests[item.test_id] = item
        else:
            profiles[item.profile_id] = item
    return tests, profiles


def base_currency() -> Currency | None:
    return Currency.objects.filter(is_active=True, is_base=True).first()


def latest_rates() -> list[dict]:
    """Tasa vigente hoy de la moneda base a cada otra moneda activa, con su origen.

    Delega en `resolve_exchange_rate` en vez de consultar `ExchangeRate` directamente,
    que es lo que hacía antes: así la tarjeta muestra **la misma** tasa con la que se
    calculan los montos. Leyendo sólo la tabla del laboratorio decía "sin registrar"
    aunque la tasa oficial del BCV estuviera vigente y aplicándose — y eso invita a
    cargar una a mano, que por ser de fecha igual o posterior pisa a la oficial y
    desactiva el automatismo sin que nadie lo note.
    """
    base = base_currency()
    if base is None:
        return []
    hoy = timezone.localdate()
    rows = []
    for currency in Currency.objects.filter(is_active=True).exclude(pk=base.pk):
        rows.append({
            "currency": currency,
            "rate": resolve_exchange_rate(
                from_currency=base, to_currency=currency, on_date=hoy
            ),
        })
    return rows
