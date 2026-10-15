# Fase 12 — Panel SuperAdmin SaaS

**Estado:** en curso (iniciada 2026-10-08).

**Depende de:** 01 · **Criterio de salida:** planes, suscripciones, métricas y
suspensión con efecto real, gestionados sin `/admin` desde un panel propio en el
esquema `public`.

> Nota del índice (`00_INDICE.md`): esta fase es, a propósito, la que el roadmap pide
> resistir hasta tener el primer laboratorio en producción. Se adelanta por decisión
> explícita de Darwin (2026-10-08) durante una conversación sobre cómo organizar el
> trabajo del laboratorio por examen en vez de por orden (idea de *worklist* por
> sección, anotada para la Fase 16 — gateway de instrumentos). La Fase 11e ya cerró con
> 298 tests y queda revisión manual pendiente, pero el panel de plataforma no bloquea
> esa revisión: son partes independientes del sistema.

## Decisiones (Darwin, 2026-10-08)

- **Suspensión con efecto real:** un `Tenant` en `SUSPENDIDO`/`MOROSO`/`CANCELADO` no
  puede entrar a nada — ni siquiera al login: ve una pantalla fija de aviso en
  cualquier URL de su dominio. Sus datos no se tocan ni se ocultan.
- **Alcance del panel:** CRUD completo (laboratorios, planes, suscripciones) + métricas
  básicas. Sin cobros ni pagos reales todavía.
- **Acceso:** reusa `accounts.User` ya existente en `public` (SHARED_APP) con
  `is_superuser=True`. Sin modelo `PlatformUser` nuevo.

## Qué se hizo

- [x] `apps.tenants.middleware.TenantAccessMiddleware`: bloquea cualquier request de un
  tenant no-`public` cuyo `status` esté en `SUSPENDIDO`/`MOROSO`/`CANCELADO` con una
  página fija (`tenants/suspendido.html`, 403), salvo `/static/`, `/media/` y
  `/__debug__/`. Agregada al `MIDDLEWARE` justo después de `TenantTimezoneMiddleware`.
- [x] `apps.tenants.services.suspension`: `suspend_tenant()` / `reactivate_tenant()` —
  cambian `status` y anotan quién y por qué en `Tenant.notes` (sin modelo de auditoría
  nuevo: `notes` ya existía).
- [x] `apps.tenants.services.metrics.platform_metrics()`: total de laboratorios, conteo
  por `status`, pruebas (`trial_ends_at`) que vencen en 7 días, MRR estimado (suma de
  `plan.price_monthly` de suscripciones `ACTIVA`; **no distingue moneda del plan** —
  limitación conocida, los planes de ejemplo están en USD).
- [x] Panel en `apps.tenants` (`views.py`, `forms.py`, `urls.py`, `decorators.py`),
  montado en `config/urls_public.py` bajo `/panel/`:
  - *Resumen* — las métricas de arriba.
  - *Laboratorios* — lista con filtro por estado y buscador; ficha con editar datos,
    suspender/reactivar, y suscripciones (agregar una nueva, cancelar la activa).
  - *Nuevo laboratorio* — envuelve `provision_tenant()`; muestra la contraseña
    temporal una sola vez, igual que el comando `crear_laboratorio`.
  - *Planes* — lista y ficha (crear/editar).
  - `platform_required` (`apps.tenants.decorators`): exige sesión + `is_superuser`.
- [x] `apps.accounts.urls` (login/logout/perfil/clave) también montado en
  `config/urls_public.py` bajo `/cuenta/`: el panel usa el mismo login que ya existía,
  sin pantalla nueva, y de paso corrige que `accounts:password` no resolvía en
  `public` (lo usa `ForcePasswordChangeMiddleware`, global).
- [x] Sin migraciones: no se tocó ningún modelo — `Tenant`/`Plan`/`Subscription` ya
  tenían todo lo que esta fase necesitaba.
- [x] Tests: `test_suspension.py` (servicio), `test_metrics.py` (servicio),
  `test_middleware.py` (bloqueo real vía `TenantClient`, mismo patrón que el login de
  la Fase 02), `test_views_platform.py` (permisos: anónimo → redirige a login,
  no-superusuario → 403, superusuario → 200; vía `RequestFactory` + `urlconf` manual,
  porque esto corre contra `public`, no contra el dominio de un laboratorio).

## Limitaciones conocidas / no incluye

- El `features` (JSON) de `Plan` sigue sin pantalla propia — se edita desde `/admin/`.
- El MRR no distingue moneda (asume USD, como los planes de ejemplo).
- Cobros, pasarela de pago y facturación real: no son parte de esta fase.
- La raíz `""` del esquema `public` sigue sin landing pública (pendiente, ver el TODO
  en `config/urls_public.py`); el panel vive en `/panel/`.
- No se probó el caso de un `accounts.User` de `public` con `must_change_password=True`
  — hoy nadie en `public` tiene esa bandera. Ahora sí resolvería (`accounts:password`
  está montado en `public`), pero queda sin ejercitar.

## Verificación pendiente en la máquina de Darwin

- [ ] `pytest -q` y `ruff check .`
- [ ] Confirmar que tu propio usuario en `public` tiene `is_superuser=True` (ver
  instrucciones en el mensaje de cierre de la fase).
- [ ] Entrar a `/panel/`: ver el *Resumen*, crear un laboratorio DEMO de prueba,
  suspenderlo y confirmar que su dominio muestra el aviso en vez del login;
  reactivarlo.
- [ ] Borrar el laboratorio DEMO de prueba (`eliminar_laboratorio_demo`) cuando
  termines de probar.

## Idea anotada para más adelante (no de esta fase)

Durante la conversación que llevó a adelantar esta fase, surgió la idea de un
**worklist por sección/examen** para cuando se automatice la operación del
laboratorio: una vista donde el bioanalista ve, por fecha, todas las muestras
pendientes de un tipo (ej. todas las hematologías de hoy) sin importar a qué
orden/paciente pertenecen, para procesarlas en lote. El informe que recibe el
paciente sigue siendo por orden (Fase 11, sin cambios) — esto es una vista operativa
interna, distinta. El modelo ya está listo (`Test.section` existe desde la Fase 05):
es un query nuevo sobre datos existentes, no un cambio de modelo. Encaja naturalmente
antes o junto con la Fase 16 (gateway de instrumentos ASTM/HL7), que habla por tipo de
examen, no por orden. Anotado en `TASKS.md` → Someday.
