"""Consultas públicas del catálogo. Otras apps (billing, orders) leen el catálogo por
aquí, no importando modelos de `apps.catalog` directamente (CLAUDE.md, regla 3)."""
from collections.abc import Iterable

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.catalog.models import (
    CodedOption,
    ContainerType,
    ObservationTemplate,
    Parameter,
    Profile,
    ProfileTest,
    ReferenceRange,
    SampleRequirement,
    Section,
    Test,
)


def active_profiles() -> list[Profile]:
    """Perfiles activos con sus exámenes precargados, en orden de presentación."""
    return list(
        Profile.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                "profile_tests",
                queryset=ProfileTest.objects.select_related("test").order_by("order_index"),
            )
        )
    )


def profile_tests(*, profile: Profile) -> list[Test]:
    """Exámenes de un perfil, en el orden definido por el laboratorio."""
    return [
        pt.test
        for pt in profile.profile_tests.select_related("test", "test__section").order_by(
            "order_index"
        )
    ]


def tests_by_codes(*, codes: Iterable[str]) -> dict[str, Test]:
    return {t.code: t for t in Test.objects.filter(code__in=list(codes))}


def profiles_by_codes(*, codes: Iterable[str]) -> dict[str, Profile]:
    return {p.code: p for p in Profile.objects.filter(code__in=list(codes))}


def calculation_input_tests(*, tests: Iterable[Test]) -> set[Test]:
    """Exámenes que faltan para poder calcular los parámetros calculados de `tests`.

    Recorre `depends_on` transitivamente (LDL → VLDL → TRIGLICÉRIDOS) y devuelve los
    exámenes dueños de esos insumos que **no** están en `tests`. Vacío = el conjunto es
    autosuficiente. Las variables de la orden (`{@peso}`, `{@isi}`) no cuentan aquí."""
    test_ids = {t.id for t in tests}
    pending = list(
        Parameter.objects.filter(
            test_id__in=test_ids, value_type=Parameter.ValueType.NUMERIC_CALCULATED
        ).prefetch_related("depends_on")
    )
    seen: set = set()
    missing_test_ids: set = set()
    while pending:
        parameter = pending.pop()
        if parameter.id in seen:
            continue
        seen.add(parameter.id)
        for dependency in parameter.depends_on.all():
            if dependency.test_id not in test_ids:
                missing_test_ids.add(dependency.test_id)
            if dependency.value_type == Parameter.ValueType.NUMERIC_CALCULATED:
                pending.append(
                    Parameter.objects.prefetch_related("depends_on").get(pk=dependency.pk)
                )
    return set(Test.objects.filter(id__in=missing_test_ids))


def sample_requirements_by_test(*, tests: Iterable[Test]) -> dict:
    """{test_id: [SampleRequirement...]} con su tubo precargado (Fase 09)."""
    result: dict = {}
    requirements = (
        SampleRequirement.objects.filter(
            test_id__in=[t.id for t in tests], is_active=True,
            container_type__is_active=True,
        )
        .select_related("container_type")
        .order_by("order_index")
    )
    for requirement in requirements:
        result.setdefault(requirement.test_id, []).append(requirement)
    return result


def container_types() -> list[ContainerType]:
    return list(ContainerType.objects.filter(is_active=True))


def search_orderables(*, query: str, limit: int = 12) -> tuple[list[Profile], list[Test]]:
    """Perfiles y exámenes activos cuyo código o nombre contiene `query`."""
    query = query.strip()
    if not query:
        return [], []
    # `unaccent` en el nombre, no en el código: los códigos no llevan tildes y
    # normalizarlos sería trabajo de más en cada consulta. Nadie escribe las tildes con
    # un paciente delante, y medio catálogo las lleva (ADR-040).
    match = Q(code__icontains=query) | Q(name__unaccent__icontains=query)
    profiles = list(Profile.objects.filter(match, is_active=True)[:limit])
    tests = list(
        Test.objects.filter(match, is_active=True).select_related("section")
        .annotate(parameter_count=Count("parameters", filter=Q(parameters__is_active=True)))
        [:limit]
    )
    return profiles, tests


def tests_without_parameters(*, tests) -> list[str]:
    """Nombres de los exámenes sin parámetros activos: no se les puede cargar resultado."""
    return list(Test.objects.filter(id__in=[t.id for t in tests])
                .exclude(parameters__is_active=True).order_by("name")
                .values_list("name", flat=True).distinct())


def active_tests_by_ids(*, ids: Iterable) -> list[Test]:
    return list(Test.objects.filter(id__in=list(ids), is_active=True))


def active_profiles_by_ids(*, ids: Iterable) -> list[Profile]:
    return list(Profile.objects.filter(id__in=list(ids), is_active=True))


def orderable_tests() -> QuerySet[Test]:
    return Test.objects.filter(is_active=True)


def orderable_profiles() -> QuerySet[Profile]:
    return Profile.objects.filter(is_active=True)


def parameters_for_tests(*, tests: Iterable[Test]) -> list[Parameter]:
    """Parámetros activos de los exámenes, en orden de informe, con unidad, grupo y opciones
    precargados (captura de resultados, Fase 10)."""
    return list(
        Parameter.objects.filter(test_id__in=[t.id for t in tests], is_active=True)
        .select_related("test", "unit", "group", "option_set")
        .prefetch_related(Prefetch("option_set__options",
                                   queryset=CodedOption.objects.order_by("order_index")),
                          "depends_on")
        .order_by("test__section__order_index", "test__name", "group__order_index",
                  "order_index")
    )


def calculated_formulas(*, parameters: Iterable[Parameter]) -> dict[str, str]:
    return {p.code: p.formula for p in parameters
            if p.value_type == Parameter.ValueType.NUMERIC_CALCULATED and p.formula}


def parameters_by_codes(*, codes: Iterable[str]) -> dict[str, Parameter]:
    return {p.code: p for p in Parameter.objects.filter(code__in=list(codes))
            .select_related("test")}


def active_sections() -> QuerySet[Section]:
    return Section.objects.filter(is_active=True).order_by("order_index", "name")


def observation_templates_by_test(*, tests: Iterable[Test]) -> dict:
    """{test_id: [ObservationTemplate...]}: las del examen, luego las de su sección, luego
    las generales (Fase 10)."""
    tests = list(tests)
    templates = list(ObservationTemplate.objects.filter(is_active=True).filter(
        Q(test__in=tests) | Q(section_id__in={t.section_id for t in tests})
        | Q(test__isnull=True, section__isnull=True)))
    result = {}
    for test in tests:
        own = [t for t in templates if t.test_id == test.id]
        section = [t for t in templates if t.test_id is None and t.section_id == test.section_id]
        general = [t for t in templates if t.test_id is None and t.section_id is None]
        result[test.id] = own + section + general
    return result


# Pantallas del catálogo (Fase 11c) --------------------------------------------------------
def catalog_tests(*, query: str = "", section_id: str = "", show_inactive: bool = False):
    tests = (Test.objects.select_related("section", "method")
             .prefetch_related("sample_requirements__container_type")
             .annotate(parameter_count=Count("parameters",
                                             filter=Q(parameters__is_active=True))))
    if not show_inactive:
        tests = tests.filter(is_active=True)
    if section_id:
        tests = tests.filter(section_id=section_id)
    query = query.strip()
    if query:
        tests = tests.filter(Q(code__icontains=query) | Q(name__unaccent__icontains=query))
    return tests.order_by("-is_active", "section__order_index", "name")


def test_detail(*, pk) -> Test:
    return (Test.objects.select_related("section", "method")
            .prefetch_related(
                "sample_requirements__container_type", "parameter_groups",
                Prefetch("parameters", queryset=Parameter.objects.select_related(
                    "unit", "group", "option_set").prefetch_related(
                    Prefetch("reference_ranges",
                             queryset=ReferenceRange.objects.filter(is_active=True)
                             .order_by("condition", "sex", "age_min_days")))
                    .order_by("-is_active", "group__order_index", "order_index")),
                Prefetch("observation_templates",
                         queryset=ObservationTemplate.objects.filter(is_active=True)
                         .order_by("order_index", "text")))
            .get(pk=pk))


def parameter_detail(*, pk) -> Parameter:
    return Parameter.objects.select_related("test", "unit", "group", "option_set").get(pk=pk)


def test_in_use(*, test: Test) -> bool:
    """Ya se ordenó alguna vez: su código queda fijo."""
    return test.order_items.exists()


def parameter_in_use(*, parameter: Parameter) -> bool:
    """Ya tiene resultados: su código y tipo de valor quedan fijos."""
    return parameter.result_values.exists()


def catalog_profiles(*, show_inactive: bool = False):
    profiles = Profile.objects.annotate(test_count=Count("profile_tests"))
    if not show_inactive:
        profiles = profiles.filter(is_active=True)
    return profiles.order_by("-is_active", "order_index", "name")


def get_profile(*, pk) -> Profile:
    return Profile.objects.get(pk=pk)


def all_active_tests():
    return list(Test.objects.filter(is_active=True).select_related("section")
                .order_by("section__order_index", "name"))
