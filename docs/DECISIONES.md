# DECISIONES (ADR ligero)

**Append-only.** Nunca se edita ni se borra una entrada. Si una decisión se revierte, se
agrega una entrada nueva que la supersede y se marca la anterior con `SUPERSEDIDA POR ADR-NNN`.

Formato: contexto → decisión → consecuencias.

---

## ADR-001 — Multi-tenancy por esquemas de PostgreSQL
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** Biolife maneja historias clínicas de múltiples laboratorios independientes.
Se evaluaron tres estrategias: base de datos por tenant, esquema por tenant, y discriminador
`tenant_id` en tabla compartida.

**Decisión.** Esquema por tenant usando `django-tenants`, con enrutamiento por subdominio.

**Consecuencias.**
- Un `Model.objects.all()` sin filtro no puede exponer datos de otro laboratorio.
- Backup, exportación y eliminación por laboratorio son operaciones directas.
- Las migraciones corren N veces. Con muchos tenants requiere ventana de mantenimiento
  y `migrate_schemas --executor=multiprocessing`.
- **Restricción dura:** la conexión a PostgreSQL debe ser directa o en modo *session
  pooling*. Un pooler en modo *transaction* rompe el aislamiento silenciosamente.

---

## ADR-002 — El paquete del proyecto Django se llama `config`
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** `django-admin startproject biolife .` crearía un paquete homónimo del producto.

**Decisión.** El paquete se llama `config`.

**Consecuencias.** `from biolife import ...` deja de ser ambiguo porque no existe. Las apps
viven todas bajo `apps/`.

---

## ADR-003 — `auto_drop_schema = False` en el modelo Tenant
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** `django-tenants` permite borrar el esquema automáticamente al borrar el tenant.

**Decisión.** Queda en `False`. La eliminación de un esquema es un procedimiento manual
documentado, con respaldo previo obligatorio. La única excepción es código de pruebas
explícito que llama `tenant.delete(force_drop=True)` para limpiar tenants temporales de
test — nunca el flujo normal de la aplicación ni el admin.

**Consecuencias.** Un borrado accidental desde el admin de Django deja el esquema huérfano
en lugar de destruir historias clínicas. La limpieza de esquemas huérfanos es una tarea
operativa periódica.

---

## ADR-004 — `display_text` obligatorio en los rangos de referencia
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** Los formatos del laboratorio imprimen rangos con formato propio
("4.500 - 10.000/mm3"). Derivar ese texto desde los campos numéricos produce una cadena
distinta a la que el laboratorio espera ver.

**Decisión.** `ReferenceRange.display_text` es obligatorio y se imprime literal. Los campos
`low`/`high`/etc. sirven sólo para marcar alto/bajo y para graficar históricos.

**Consecuencias.** Duplicación controlada de información. A cambio, el informe reproduce
exactamente el formato actual del laboratorio, que es requisito de aceptación del cliente.

---

## ADR-005 — Congelado de referencias al validar un resultado
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** Los rangos de referencia cambian con el tiempo (nuevo lote de reactivo,
corrección de un error). Un informe reimpreso años después debe mostrar el rango vigente
al momento del examen.

**Decisión.** Al validar, `ResultValue.reference_used` y `reference_text` se copian desde
el rango resuelto. La impresión nunca vuelve a resolver el rango.

**Consecuencias.** Reimpresiones históricas correctas. Coste: dos columnas adicionales por
valor de resultado.

---

## ADR-006 — Python 3.13 en lugar de 3.12
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** La máquina de desarrollo de Darwin tiene Python 3.13 y 3.14 instalados, pero
no 3.12 (la versión originalmente fijada en `CLAUDE.md`). Django 5.1 soporta oficialmente
hasta Python 3.13; psycopg 3.2 también soporta 3.13. Python 3.14 se descarta por ser
demasiado reciente para confiar en la compatibilidad de `django-tenants` y del resto de
dependencias fijadas en `requirements/base.txt`.

**Decisión.** El proyecto usa **Python 3.13** en vez de 3.12, evitando instalar una versión
adicional. `django-admin startproject` y el venv se crean con `py -3.13`.

**Consecuencias.**
- `CLAUDE.md`, sección "Stack fijo", se actualiza a Python 3.13.
- Verificado en la Fase 01: `django-tenants==3.7.*`, `psycopg[binary]==3.2.*` y el resto de
  `requirements/base.txt` instalan y corren limpio en Python 3.13.7. El riesgo de
  compatibilidad anticipado no se materializó.
- Sin impacto conocido en PostgreSQL, Cloudinary, Railway ni el resto del stack.

---

## ADR-007 — `provision_tenant()` fuerza el esquema `public` internamente
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** `django-tenants` exige crear un `Tenant` únicamente con la conexión activa en
el esquema `public` — si se invoca desde cualquier otro esquema, `Tenant.save()` lanza
`Exception("Can't create tenant outside the public schema")`. Esto se manifestó al escribir
los tests de la Fase 01 (`pytest-django` no garantiza que la conexión esté en `public` al
llamar al service), y es un riesgo real también en producción si `provision_tenant()` llega
a invocarse alguna vez desde un contexto de request ya resuelto a un tenant.

**Decisión.** `provision_tenant()` envuelve toda su lógica en
`with schema_context(get_public_schema_name())`, sin importar el esquema activo del llamador.

**Consecuencias.**
- El service es seguro de invocar desde cualquier contexto.
- Cualquier código que borre un tenant de prueba (`tenant.delete(force_drop=True)`) debe
  hacer el mismo `schema_context(get_public_schema_name())` explícito — no lo hace el
  modelo `Tenant` por sí solo.

---

## ADR-008 — Tests que crean/borran esquemas de tenant requieren `transaction=True`
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** `@pytest.mark.django_db` (sin `transaction=True`) envuelve cada test en una
transacción que `pytest-django` revierte al final. Un `DROP SCHEMA ... CASCADE` ejecutado
dentro de esa transacción falla con `ObjectInUse: ... tiene eventos de disparador
pendientes`, porque los triggers de FK diferidos no se han resuelto todavía.

**Decisión.** Todo test que llame a `provision_tenant()` y luego borre el tenant
(`tenant.delete(force_drop=True)`) debe usar `@pytest.mark.django_db(transaction=True)`.
Los tests de aislamiento basados en `django_tenants.test.cases.TenantTestCase` no necesitan
este marcador — la clase ya maneja sus propias transacciones.

**Consecuencias.** Estos tests son más lentos (no hay rollback automático; cada uno limpia
su propio esquema explícitamente) pero son los únicos que reflejan correctamente el
comportamiento real de creación/eliminación de esquemas.

---

## ADR-009 — El esquema `public` necesita su propio `Tenant` + `Domain`
**Fecha:** 2026-09-19 · **Estado:** Aceptada

**Contexto.** `TenantMainMiddleware` busca un `Domain` para **cada** hostname entrante,
incluido `localhost` quien sirve el panel SuperAdmin y el admin de Django. Sin un `Tenant`
con `schema_name="public"` y un `Domain(domain="localhost")` asociado, cualquier request a
`localhost` devuelve 404 ("No tenant for hostname").

**Decisión.** Como parte del setup local (y del script de despliegue en Fase 17), se crea
explícitamente:
```python
tenant, _ = Tenant.objects.get_or_create(schema_name="public", defaults={"name": "Biolife Plataforma"})
Domain.objects.get_or_create(domain="localhost", tenant=tenant, defaults={"is_primary": True})
```
`Tenant.save()` no intenta crear el esquema `public` (ya existe) — es un caso especial que
`django-tenants` maneja internamente.

**Consecuencias.** Este paso debe repetirse (con el dominio real, no `localhost`) en cada
entorno nuevo — staging y producción — antes de que el panel SuperAdmin sea alcanzable.
Pendiente: automatizarlo como parte del script de despliegue de la Fase 17.


## ADR-010 — `User` personalizado (`accounts.User`) en vez de `auth.User`
**Fecha:** 2026-09-20 · **Estado:** Aceptada

**Contexto.** `docs/02_ESTRUCTURA_PROYECTO.md` lista `User` como modelo propio dentro de
`apps/accounts/`, pero la Fase 01 había migrado `django.contrib.auth` con su `User` por
defecto en los tenants demo. Adoptar un modelo propio permite campos específicos del
dominio (`phone`, `professional_license`) sin depender de un `Profile` aparte, y es
coherente con la documentación de arquitectura.

**Decisión.** `AUTH_USER_MODEL = "accounts.User"`, extendiendo `AbstractUser`. Como
consecuencia, hubo que **recrear la base de datos local completa** (`dropdb`/`createdb`)
porque `public`, `demo_uno` y `demo_dos` ya tenían el historial de migraciones de `auth`
aplicado con el `User` por defecto — no hay forma limpia de cambiar `AUTH_USER_MODEL`
sobre un historial de migraciones ya aplicado sin recrear el esquema. Al ser sólo datos
de prueba, no hubo pérdida real.

**Consecuencias.**
- Cualquier referencia a un usuario en el código usa `"accounts.User"` (string) o
  `django.contrib.auth.get_user_model()`, nunca `django.contrib.auth.models.User`
  directamente — esa tabla ya no se migra.
- `TenantBaseModel.created_by` apunta a `"accounts.User"` (Fase 02, Tarea 7).
- Cambiar `AUTH_USER_MODEL` de nuevo en el futuro, con datos reales en producción, sería
  una migración de datos mayor — **no se vuelve a tocar sin ADR nuevo**.

---

## ADR-011 — `apps.accounts` es SHARED_APP y TENANT_APP a la vez
**Fecha:** 2026-09-20 · **Estado:** Aceptada

**Contexto.** `django.contrib.admin` (SHARED_APP, vive en `public` para el panel de
Django admin) depende de `AUTH_USER_MODEL` a través de
`migrations.swappable_dependency(settings.AUTH_USER_MODEL)`. Con `apps.accounts` sólo en
`TENANT_APPS`, `public` nunca migra `accounts`, y `admin.0001_initial` no puede resolver
su dependencia — error real encontrado: `InconsistentMigrationHistory`.

**Decisión.** `apps.accounts` se agrega también a `SHARED_APPS`, exactamente el mismo
patrón que ya usan `auth`, `contenttypes`, `sessions` y `messages` en este proyecto: la
app migra tanto en `public` como en cada esquema de tenant, cada uno con su propia tabla
de usuarios independiente.

**Consecuencias.**
- `public` tiene su propia tabla `accounts_user`, hoy usada sólo por el superusuario de
  `/admin/` (`darwinjoelap`). No se cruza con los usuarios de los tenants — aislamiento
  intacto, es la misma garantía que ya vale para `auth` desde la Fase 01.
- El `PlatformUser` de la Fase 12 (`SUPERADMIN_PLATAFORMA`) seguirá siendo un modelo
  aparte, no reutiliza esta tabla — ver nota de alcance en
  `docs/roadmap/02_usuarios_roles_auditoria.md`.
- Cualquier app nueva que dependa de `AUTH_USER_MODEL` y deba ser visible desde `public`
  (paneles de superadmin, por ejemplo) debe seguir este mismo patrón dual, no asumir que
  "tenant app" basta.


---

## ADR-012 — `TenantTimezoneMiddleware` se muda de `apps.core` a `apps.settings_lab`
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** El middleware necesita leer la zona horaria real del laboratorio desde
`TenantSettings`, un modelo de `apps.settings_lab`. `CLAUDE.md` es explícito:
*"`core/` puede ser importado por todos; `core/` no importa a nadie."* Dejarlo en
`apps.core` habría forzado a `core` a importar `settings_lab`, rompiendo esa regla.

**Decisión.** `TenantTimezoneMiddleware` vive en `apps.settings_lab.middleware`.
`apps/core/middleware.py` queda vacío (con nota explicando la mudanza), y
`config/settings/base.py::MIDDLEWARE` apunta al nuevo path.

**Corrección real encontrada durante la implementación (no estaba en el roadmap
original de la Fase 03).** El middleware, tal como estaba especificado, llamaba a
`TenantSettings.get_solo()` incondicionalmente en cada request. Como `apps.settings_lab`
es `TENANT_APP` y no `SHARED_APP`, la tabla `settings_lab_tenantsettings` **no existe**
en el esquema `public` — el middleware habría roto con `relation does not exist` en
*cualquier* request al dominio `localhost` (incluido `/admin/`), ya que el `MIDDLEWARE`
corre para todos los esquemas, sin importar qué `ROOT_URLCONF`/`PUBLIC_SCHEMA_URLCONF`
se use después. Se agregó una guarda: si `request.tenant.schema_name ==
get_public_schema_name()`, el middleware activa `settings.TIME_ZONE` en vez de tocar
`TenantSettings`. Verificado en navegador: `/admin/` en `localhost` sigue funcionando
después del cambio, y cubierto por test (`test_middleware_usa_time_zone_por_defecto_en_public`).

**Consecuencias.**
- Cualquier middleware o vista que dependa de un modelo `TENANT_APP`-only debe aplicar la
  misma guarda de esquema `public` — no asumir que el request siempre trae un tenant real.
- El `MIDDLEWARE` en `base.py` debe actualizarse junto con cualquier mudanza futura de
  este tipo; verificar siempre con `manage.py check` **y** una visita real a `/admin/`
  en `localhost`, no solo al dominio de un tenant.

---

## ADR-013 — Cloudinary diferido a la Fase 17; storage local mientras tanto
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Darwin tiene credenciales de Cloudinary reutilizables de otros proyectos y
preguntó si convenía integrarlas ahora, o incluso adelantar el despliegue a Railway antes
de continuar con el roadmap. Se evaluaron las tres opciones (Cloudinary ahora, Railway
ahora, seguir el roadmap sin adelantos) y **Darwin decidió no adelantar ninguna de las
dos**: sin credenciales de producción reales ni un despliegue real donde probarlas, cablear
Cloudinary ahora sería trabajo especulativo.

**Decisión.** `TenantSettings.logo`/`banner` son `ImageField` con el storage local de
Django (`MEDIA_ROOT`/`MEDIA_URL`, servidos en `DEBUG` desde `urls_tenant.py`). La
integración real con Cloudinary queda para la **Fase 17** (despliegue), cuando haya
credenciales de producción y un entorno real donde validarlas. El despliegue a Railway
tampoco se adelanta — se sigue el orden del roadmap.

**Consecuencias.**
- Cambiar el storage de un `ImageField` más adelante no exige tocar el modelo ni generar
  una migración nueva — sólo `DEFAULT_FILE_STORAGE`/`STORAGES` en `production.py`
  (Fase 17).
- Mientras tanto, los logos/banners subidos en desarrollo viven en `media/` local y no
  sobreviven un `dropdb`/recreación de esquema del mismo modo que los datos de BD (son
  archivos en disco, no filas) — sin impacto real hoy porque son solo datos de prueba.
- No se instala `django-cloudinary-storage` ni se agregan sus credenciales a `.env`
  hasta la Fase 17 — evita dependencias y configuración sin uso real.


---

## ADR-014 — Formato de `internal_code`, contador con `select_for_update()` y ubicación de `lab_initials`
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Cada paciente necesita un código interno único, legible y corto que el
personal de recepción pueda usar en papel/etiquetas sin depender del UUID interno. Se
evaluaron con Darwin el formato exacto y el criterio de reinicio del correlativo.

**Decisión.**
- Formato `{YY}{iniciales_lab}{correlativo:06d}` — ej. `26LDU000001` (año con los dos
  últimos dígitos, siglas del laboratorio, correlativo de 6 dígitos con ceros a la
  izquierda). El correlativo **reinicia en 1 cada año** — el año va embebido en el propio
  código, así que dos años distintos nunca chocan aunque ambos empiecen en `000001`.
- El contador vive en `PatientCodeSequence` (`year` único + `last_value`), un modelo
  auxiliar plano — **no** hereda `TenantBaseModel`, mismo criterio ya usado para
  `Role`/`Membership`/`AuditLog` en `apps.accounts`: es plumbing interno, no un registro
  de dominio con auditoría/soft-delete propios.
- `generate_internal_code()` usa `select_for_update()` + `transaction.atomic()` sobre la
  fila de `PatientCodeSequence` del año actual, para que dos registros de paciente
  simultáneos (dos recepcionistas al mismo tiempo) nunca obtengan el mismo correlativo.
- `lab_initials` vive en `TenantSettings` (config del laboratorio, `apps.settings_lab`) y
  no en `Tenant` (`apps.tenants`, esquema `public`): las siglas son un dato operativo del
  laboratorio que su propio personal administra desde el admin de su tenant, no un dato de
  plataforma/facturación que gestione Biolife. Consistente con por qué `TenantSettings` no
  tiene FK a `Tenant` (ADR de la Fase 03): ya vive aislado dentro del esquema del tenant.

**Consecuencias.**
- Un laboratorio sin `lab_initials` configurado no puede registrar pacientes:
  `generate_internal_code()` lanza `ApplicationError` explícito en vez de generar un
  código con siglas vacías o inventadas — obliga a completar la configuración primero.
- Cambiar las siglas de un laboratorio ya en producción no reescribe los `internal_code`
  ya emitidos (son inmutables, `editable=False`) — solo afecta a los pacientes nuevos.
- El límite de 999.999 pacientes nuevos por año por laboratorio se considera no
  alcanzable en la práctica para el tamaño de cliente objetivo; no se diseñó manejo de
  overflow.
- Cubierto por tests (`test_code_sequence.py`): correlativos consecutivos dentro del
  mismo año, y aislamiento entre años (un `PatientCodeSequence` de un año anterior con
  valor alto no afecta el correlativo del año actual).


---

## ADR-015 — Catálogo sembrado directo por tenant; Master*+copia pospuesto
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** `docs/01_MODELO_DATOS.md` (sección A) describe catálogos maestros
(`MasterSection`/`MasterUnit`/`MasterMethod`/`MasterAnalyte`) en el esquema `public` que se
"copiarían" a cada tenant nuevo al aprovisionarlo, además de las tablas `Section`/`Unit`/
`Method`/`Test`/`Parameter` propias de cada tenant. Con un solo laboratorio real (Angelus)
por ahora, construir el mecanismo completo de maestros + copia es trabajo especulativo: no
hay un segundo tenant real que lo necesite, y su diseño correcto (qué pasa si un tenant
personaliza un `Test` copiado y el maestro cambia después) depende de decisiones de producto
que no se han tomado.

**Decisión.** Se implementó únicamente el lado tenant del modelo (`apps.catalog`:
`Section`, `Unit`, `Method`, `Test`, `ParameterGroup`, `Parameter`, `CodedOptionSet`,
`CodedOption`), sembrado directo por tenant vía `services/seeding.py` + management command
(mismo patrón que `seed_system_roles()` en `apps.accounts`, Fase 02). El mecanismo
`Master*` + copia al aprovisionar queda **pospuesto** para cuando se incorpore un segundo
laboratorio real y haya un caso concreto que lo justifique.

**Decisión relacionada — cobertura de los 9 `value_type` en un solo examen.** El criterio
de salida de la fase ("Uroanálisis completo cargado con sus 9 tipos de valor") exige que
un único `Test` ejercite los 9 valores de `Parameter.value_type`. El uroanálisis real de
Angelus no trae de forma confirmada un parámetro `NUMERIC_CALCULATED` ni uno
`MULTI_CATALOG` (ese tipo sólo aparece en heces/parásitos en los formatos reales). Se
agregaron parámetros plausibles pero **no confirmados por el laboratorio** —
`PROTEÍNA EN ORINA`/`CREATININA EN ORINA`/`ÍNDICE PROTEÍNA/CREATININA` (numérico y
calculado) y `CRISTALES EN SEDIMENTO` (multi-catálogo), además de un `RECUENTO
BACTERIANO (screening)` ilustrativo para `TITER` (en la práctica parte de un urocultivo, no
del uroanálisis de rutina) — marcados explícitamente como tales en
`docs/roadmap/05_catalogo_examenes.md` y en el docstring de `seed_uroanalisis()`.

**Decisión relacionada — validación en `CheckConstraint`, no en el service.** A diferencia
de la regla de representante legal de pacientes (Fase 04, que depende de una relación que
aún no existe al validar), las reglas de `Parameter` sólo dependen de sus propios campos, así
que se expresan como `CheckConstraint` de base de datos: `option_set` obligatorio para
`CODED`/`SEMIQUANTITATIVE`/`QUALITATIVE`/`TITER`/`MULTI_CATALOG`, y `formula` obligatorio
para `NUMERIC_CALCULATED`.

**Consecuencias.**
- Cargar el catálogo completo de un segundo laboratorio real hoy significa escribir un
  nuevo `services/seeding.py` para ese tenant (o adaptar el de Angelus) — no hay
  reutilización automática entre tenants todavía. Aceptable con un solo cliente.
- Ningún parámetro marcado "no confirmado" debe imprimirse en un informe real hasta que
  Angelus lo confirme — queda como pendiente explícito en `docs/ESTADO.md`.
- `Parameter.depends_on` (M2M a sí mismo) se deja vacío: resolver automáticamente las
  dependencias a partir de `formula` es trabajo de la Fase 07 (motor de fórmulas).
- Cuando se decida construir Master*+copia, el trabajo de esta fase no se pierde: las
  tablas tenant (`Section`/`Unit`/.../`Parameter`) son exactamente las que un mecanismo de
  copia poblaría; sólo faltaría agregar el origen `Master*` en `public` y el paso de copia
  en `provision_tenant()`.


---

## ADR-016 — Rangos de referencia: 4 exámenes mínimos nuevos, 6 parámetros pendientes de confirmar
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** El criterio de salida de la Fase 06 exige que `ReferenceRange` demuestre
resolución por sexo y edad en días con los 6 `range_type` del modelo de datos (`CLOSED`,
`UPPER_BOUND`, `LOWER_BOUND`, `TOLERANCE`, `QUALITATIVE`, `INTERPRETIVE`). El Uroanálisis
sembrado en la Fase 05 sólo tiene datos naturales para `QUALITATIVE`; los demás tipos sí
tienen datos numéricos reales en `docs/04_HALLAZGOS_FORMATOS.md`, pero de exámenes que
todavía no existían en el catálogo (hematología, perfil lipídico, coagulación).

**Decisión — 4 exámenes nuevos, mínimos.** Se sembraron `HEM_COMP`, `PERFIL_LIPIDICO`,
`COAGUL` y `QUIM`, cada uno **sólo con los parámetros necesarios** para colgarles un
rango real (no la lista completa de cada examen — ver `services/seeding_reference_ranges.py`
y `docs/roadmap/06_rangos_de_referencia.md`). `QUALITATIVE` se resolvió reutilizando
`URO_NITRITOS` de la Fase 05, sin sembrar nada nuevo para ese tipo.

**Decisión — 6 parámetros con rango contradictorio, sembrados con un valor marcado
pendiente.** `docs/04_HALLAZGOS_FORMATOS.md` reporta GLICEMIA, ÚREA, CREATININA, ÁCIDO
ÚRICO, BILIRRUBINA TOTAL y BILIRRUBINA DIRECTA con dos valores distintos según la hoja del
formato. Angelus no ha confirmado cuál es el correcto (pregunta abierta, ver
`docs/ESTADO.md`). Se sembró un valor de cada par — el clínicamente más citado, o el que
no es un error de tipeo evidente (ácido úrico) — documentado con su justificación en
`docs/roadmap/06_rangos_de_referencia.md`. El `display_text` de cada uno incluye
"(PENDIENTE DE CONFIRMAR)" para que sea visible también en el admin, no sólo en el código.

**Decisión — sexo y edad, cada uno con su propio ejemplo.** HEMOGLOBINA demuestra
resolución por sexo con dos valores que el propio `04_HALLAZGOS_FORMATOS.md` documenta:
13,0-15,0 g/dL (lo que trae el formato actual de Angelus, incorrectamente para ambos
sexos) y 12,0-16,0 g/dL (el valor femenino que el mismo documento señala como el
clínicamente correcto). GLÓBULOS BLANCOS demuestra resolución por edad con una fila para
recién nacido (0-28 días) marcada explícitamente **no confirmada** (los rangos
neonatales/pediátricos reales son otra pregunta abierta al laboratorio) y una fila para el
resto con el valor confirmado (4.500-10.000/mm3).

**Decisión — validación por `CheckConstraint`.** Igual criterio que `Parameter` en la
Fase 05: cada `range_type` exige sus propios campos (`low`/`high` para `CLOSED`, `high`
para `UPPER_BOUND`, `low` para `LOWER_BOUND`, `center`+`tolerance` para `TOLERANCE`,
`expected_option` para `QUALITATIVE`, `bands` para `INTERPRETIVE`) validados con
`CheckConstraint` de base de datos, más `age_min_days <= age_max_days`.

**Consecuencias.**
- Ningún `ReferenceRange` marcado "PENDIENTE DE CONFIRMAR" o "NO CONFIRMADO" debe usarse
  en un informe real hasta que Angelus responda — queda explícito en `docs/ESTADO.md`.
- Si "PERFIL LIPÍDICO" termina siendo un `Profile` que agrupa `Test`s en vez de un `Test`
  único (decisión de la Fase 08), el `Test` `PERFIL_LIPIDICO` sembrado aquí puede
  renombrarse o descomponerse sin perder los `ReferenceRange` — éstos cuelgan de
  `Parameter`, no de `Test` ni `Profile`.
- `resolve_reference_range()` (en `services/reference_resolver.py`) es, desde ahora, el
  único punto permitido para resolver un rango — ninguna vista o service futuro debe
  filtrar `ReferenceRange` directamente (mismo criterio que `services/`, regla 3 de
  `docs/03_CONVENCIONES.md`: ninguna vista toca el ORM directo).
- La resolución de `bands` (`INTERPRETIVE`) a un texto según el valor medido, y el
  congelamiento de `reference_used`/`reference_text` en `ResultValue`, quedan para la
  Fase 10 (captura y validación de resultados) — aquí sólo se guarda el dato.


---

## ADR-017 — Motor de fórmulas: sintaxis `{CODIGO}`/`{@var}`, AST restringido, precisión completa, Mosteller
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** La Fase 07 implementa los parámetros `NUMERIC_CALCULATED`. `00_ARQUITECTURA.md`
fijaba la sintaxis `{HB}` / `{@peso}`, pero las 2 fórmulas sembradas en las Fases 05/06
(`URO_INDICE_PROT_CREAT`, `COAG_PTT_DIFERENCIA`) usaban códigos sueltos y `depends_on`
estaba vacío. Faltaba decidir el origen del ISI (INR) y la precisión de los intermedios, y
el criterio de salida exige reproducir los valores reales de `04_HALLAZGOS_FORMATOS.md`.

**Decisión — sintaxis y seguridad.** `{CODIGO}` referencia otro parámetro del tenant y
`{@variable}` un dato de la orden (lista cerrada `CONTEXT_VARIABLES`: `peso`, `talla`,
`volumen_orina_24h`, `isi`). Las llaves se traducen a identificadores y la expresión se
parsea con `ast` en modo `eval`, recorriendo una **lista blanca** de nodos (`+ - * / **`,
signo, literales numéricos, `round/sqrt/min/max/abs`). Nunca `eval()`. Exponente acotado a
|10|, fórmula ≤ 500 caracteres. La migración de datos `catalog.0004_formula_sintaxis_llaves`
reescribe las fórmulas existentes y puebla `depends_on`.

**Decisión — dónde viven las cosas.** `services/formula_engine.py` es puro (sin ORM): la
Fase 10 lo llama con `{código: fórmula}`, `{código: valor}` y el contexto de la orden.
`services/formula_validation.py::set_parameter_formula()` es el único camino para asignar
una fórmula: valida existencia y tipo numérico de las referencias, autorreferencia y
**ciclos al guardar** (orden topológico con `graphlib` sobre todas las fórmulas del
tenant), y sincroniza `depends_on`. El admin usa la misma validación.

**Decisión — ISI como `{@isi}`.** Angelus no ha confirmado el ISI del lote. El motor lo
recibe como variable de contexto; dónde se persiste (TenantSettings o por lote) se decide
en la Fase 10. Sin ISI, el INR queda vacío con motivo y el resto se calcula.

**Decisión — precisión completa.** Todo en `Decimal` (precisión 28). Los calculados que
alimentan a otros (VLDL→LDL, SC→depuración corregida) pasan sin redondear, como Excel. El
redondeo (mitad hacia arriba, `Parameter.decimals`) es sólo para mostrar/guardar.

**Decisión — superficie corporal con Mosteller.** `04_HALLAZGOS_FORMATOS.md` anotaba DuBois
y afirmaba que reproducía la hoja `DEPURACIÓN`. No es así: DuBois da 1,6819 m² y 67,76
mL/min; la hoja imprime 1,6857 m² y 67,61 mL/min, que es exactamente Mosteller
(`sqrt(talla × peso / 3600)`). Se sembró Mosteller y se agregó errata al documento de
hallazgos.

**Consecuencias.**
- Pregunta nueva a Angelus: ¿Mosteller (lo que usa su hoja) o DuBois?
- Sólo 3 de las 16 fórmulas tienen valor impreso real para comparar (las de depuración);
  las otras 13 se verificaron contra cálculos a mano. Validar con una orden real de
  Angelus cuando exista (Fase 10).
- Una fórmula inválida guardada por fuera de `set_parameter_formula()` (ORM directo) hace
  fallar la validación de las demás, porque la detección de ciclos parsea todas.
- `URO_INDICE_PROT_CREAT` (NO CONFIRMADO, Fase 05) multiplica por 100 con unidad `mg/g`;
  mg/dL ÷ mg/dL → mg/g requiere ×1000. Revisar cuando Angelus confirme ese parámetro.


---

## ADR-018 — Angelus es laboratorio de referencia, no el alcance del producto
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Varios documentos (índice del roadmap, hallazgos, preguntas abiertas) están
redactados como si el objetivo fuera reproducir el método de trabajo del Laboratorio
Angelus. Darwin aclaró al cerrar la Fase 07 que no es así: Angelus facilitó sus hojas de
trabajo como base para arrancar, y Biolife es un SaaS pensado para muchos laboratorios.

**Decisión.**
- Las hojas de Angelus (`docs/04_HALLAZGOS_FORMATOS.md`) son **material de referencia y
  datos de prueba reales**, no una especificación cerrada ni un techo de alcance.
- El producto busca ser **lo más completo posible**, por encima de lo que hoy usa Angelus.
  Cada fase tiene libertad creativa para agregar exámenes, fórmulas, tipos de rango,
  configuraciones o funciones útiles para laboratorios clínicos en general.
- Lo que varía entre laboratorios (rangos, fórmulas alternativas, formato del informe,
  precios, flujo de validación) se modela como **configuración por tenant**.
- Los criterios de salida que nombran a Angelus se interpretan como *demostración con
  datos reales*: el sistema debe poder representarlo, sin limitarse a eso.

**Consecuencias.**
- Las preguntas abiertas "al laboratorio" alimentan los datos del tenant Angelus (o de un
  tenant demo); **no bloquean** decisiones de producto. Ejemplo: Mosteller vs DuBois
  (ADR-017) no es "cuál usa Angelus" sino qué fórmula trae el catálogo por defecto — como
  las fórmulas son por tenant, cada laboratorio puede usar la suya.
- Los valores marcados "PENDIENTE DE CONFIRMAR"/"NO CONFIRMADO" siguen sin usarse en un
  informe real: la regla de no inventar datos clínicos no cambia.
- Futuro catálogo semilla (Master*+copia, ADR-015) puede incluir exámenes que Angelus no
  hace.


---

## ADR-019 — Perfiles como agrupación de exámenes individuales; precios multimoneda en `apps.billing`
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** La Fase 08 exige perfiles y lista de precios. Darwin definió que un perfil
(Lipídico, Perfil 20…) es una agrupación nombrada de exámenes y que los precios deben poder
ordenarse, ajustarse, tener moneda y descuentos por tenant. Las Fases 06/07 habían sembrado
exámenes agregados (`QUIM`, `PERFIL_LIPIDICO`, `COAGUL`) que no se pueden agrupar. Darwin
adjuntó los Excel del laboratorio de referencia, que se leyeron celda por celda.

**Decisión — granularidad.** Cada analito ordenable es un `Test` propio. Los parámetros de
las Fases 06/07 se mudan a su examen individual **conservando su código**, así que fórmulas,
`depends_on` y rangos no cambian. Los agregados viejos se desactivan (no se borran). La
siembra vive en una sola fuente declarativa (`seeding_base_catalog.py`).

**Decisión — perfiles.** `Profile` + `ProfileTest` (orden). `set_profile_tests()` rechaza
perfiles con parámetros calculados sin sus insumos (recorrido transitivo de `depends_on`).
Composición de 13 hojas (14 perfiles: el glicémico tiene variante post-prandial y
post-carga); agregados por Biolife: UROANÁLISIS en el Preeclámptico y un Perfil prenatal.

**Decisión — precios.** App `apps.billing` (nombre previsto en `02_ESTRUCTURA_PROYECTO.md`):
- `Currency` por tenant con una sola moneda base; `ExchangeRate` por fecha (1 origen = tasa
  destino; se usa la más reciente ≤ fecha, o la inversa).
- `PriceList` en una moneda, con vigencia, orden y una sola predeterminada.
- `PriceListItem`: examen **o** perfil; perfil en modo `FIXED` o `SUM_WITH_DISCOUNT`
  (suma de sus exámenes en la misma lista menos %).
- `Discount`: % o monto fijo (con moneda), alcance orden o ítem (con exámenes/perfiles
  destino), vigencia, acumulable o no, y `requires_authorization` (lo exige `quote()`; el rol
  que autoriza se conecta en la Fase 09).
- `Test.price` se elimina: una sola fuente de precio.
- `quote()` no guarda nada: la orden (Fase 09) congela el resultado.

**Reglas de cotización.** Un examen se cobra una vez (si viene suelto y en un perfil, sólo
cuenta el perfil; si dos perfiles lo comparten, el segundo recibe crédito por su precio
individual). Descuentos por línea y luego de orden: el mejor no acumulable + todos los
acumulables, con tope en el monto. Precisión completa, redondeo a los decimales de la
moneda por línea.

**Decisión — Mosteller confirmado.** La celda de la hoja DEPURACIÓN es
`=SQRT((K24*K25)/3600)`: la pregunta abierta de ADR-017 queda resuelta con el dato del
propio laboratorio. Las 17 fórmulas (16 de `04_HALLAZGOS` + HOMA-IR) reproducen valores
reales de las hojas.

**Consecuencias.**
- No hay precios sembrados: `seed_billing` crea USD (base), VES y la lista GENERAL vacía.
- La hoja de Angelus calcula el INR con ISI vacío → siempre 1. Biolife no reproduce eso.
- Rangos nuevos marcados "PENDIENTE DE CONFIRMAR": LDH por sexo (otras hojas usan 90–510),
  TGO/TGP <40 (otras hojas <35), insulina basal (unidad "U/mL" en la hoja). HbA1c con
  bandas ADA marcadas "PROPUESTO". Insulina post-carga sin rango.
- Los rangos de lípidos de la Fase 06 usan condición `AYUNO`; los nuevos usan `NINGUNA`.
  El resolver con condición por defecto no encuentra los de `AYUNO`: decidir en la Fase 10.
- Perfiles anidados y tasa BCV automática quedan fuera.


---

## ADR-020 — Ficha del examen: rangos por edad en años/meses/días, validación de cobertura, admin por tenant
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Darwin pidió que cada examen tenga una ficha donde el laboratorio ajuste los
rangos por sexo y edad. El modelo (`ReferenceRange`, ADR-004/016) ya lo soportaba, pero la
edad se editaba en días crudos y nada avisaba de solapes o huecos. Todavía no hay estilo
visual definido para las pantallas.

**Decisión.**
- La lógica vive en services independientes de la pantalla
  (`reference_range_management.py`); el admin de Django es la pantalla **provisional**.
- Edad en años/meses/días con año = 365,25 días y mes = 1/12 de año, redondeando al día
  (`core/utils/dates.py`). En el formulario, "Desde" es inclusiva y "Hasta" **exclusiva**
  ("0 a 1 año" = 0–364 días), para que tramos consecutivos encajen sin huecos ni solapes.
- Solape con misma prioridad y mismo ancho = ERROR (bloquea). Solape resuelto por el
  desempate o hueco de edad/sexo = AVISO (se guarda e informa).
- Un rango desactivado no se resuelve nunca (ajuste a `resolve_reference_range()`).
- `django.contrib.admin` también en `TENANT_APPS`, con la migración
  `accounts.0004_admin_log_por_tenant` para crear `django_admin_log` en los tenants
  existentes (sus migraciones de `admin` figuraban aplicadas sin tabla).

**Consecuencias.**
- La ficha definitiva (fase de estilo visual) reutiliza estos services sin cambios.
- Cualquier `app` compartida cuyo modelo apunte a `accounts.User` debe revisarse con el
  mismo criterio: si guarda datos por laboratorio, debe estar en `TENANT_APPS`.
- El probador hace visible el pendiente de ADR-019: los rangos de lípidos con condición
  `AYUNO` no aplican a un paciente con condición `NINGUNA`.


---

## ADR-021 — Consolidación: laboratorios nacen con catálogo, lípidos sin condición AYUNO, CI
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Revisión de estado antes de la Fase 09: un laboratorio nuevo nacía vacío (4
comandos manuales), los rangos de lípidos con condición AYUNO no aplicaban a ningún paciente,
los tests sólo corrían a mano y el script de aislamiento estaba roto desde la Fase 02.

**Decisión.**
- `provision_tenant(..., seed_catalog=True)` siembra catálogo base, perfiles, monedas y la
  lista GENERAL vacía. Todo es editable por el laboratorio; `--sin-catalogo` lo omite.
- El ayuno es un requisito del examen (`Test.requires_fasting`), no un rango distinto: los
  rangos de lípidos pasan a condición NINGUNA (migración `catalog.0006`). La condición AYUNO
  queda para parámetros cuyo valor de referencia realmente cambia con el ayuno.
- GitHub Actions corre ruff, migraciones, pytest y el script de aislamiento en cada push.

**Consecuencias.** Crear un laboratorio tarda unos segundos más. Los tests de provisión
también. Si el laboratorio no usa GitHub, el workflow simplemente no corre.

---

## ADR-022 — Sistema visual: CSS plano sin build, denso, con la paleta del logo
**Fecha:** 2026-09-26 · **Estado:** Aceptada (reemplaza "Tailwind vía CLI" de 03_CONVENCIONES)

**Contexto.** Antes de la primera pantalla real (Fase 09) hacía falta un estilo. Darwin pidió
algo moderno y minimalista, sin tener que desplazarse para ver todos los campos, con el logo
de Biolife. Las convenciones preveían Tailwind compilado por CLI.

**Decisión.**
- Un solo `static/css/biolife.css` con tokens en variables CSS y componentes de clases
  cortas. Sin Tailwind ni Node: nada que compilar en Windows ni en CI, un archivo cacheable,
  y la PWA (Fase 13) lo sirve offline.
- Paleta tomada del logo (navy `#0b2e63`, azul `#0d6dc9`, teal `#11ad9b`); `--brand` es el
  color primario de cada laboratorio (`TenantSettings.color_primary`).
- Densidad por diseño: controles de 32 px, texto de 13,5 px, grilla de formulario de 12
  columnas, tablas compactas, barra de acciones fija al pie.
- Inter autoalojada, íconos Lucide en sprite SVG, htmx y Alpine en `static/vendor/`: sin
  dependencias de CDN.
- Guía de estilo viva en `/estilo/` como referencia para las fases siguientes.
- `STORAGES` en lugar de `STATICFILES_STORAGE` (eliminado en Django 5.1: WhiteNoise estaba
  inactivo sin aviso). `TENANT_COLOR_ADMIN_APPS = False` y el admin con la identidad de Biolife.

**Consecuencias.**
- Las pantallas de las Fases 09+ usan `base_tenant.html`, `{% field %}` y los componentes de
  la guía; un componente nuevo se agrega primero a la guía.
- `color-mix()` exige navegadores de 2023 en adelante; en los más viejos sólo se pierden los
  fondos suaves del color del laboratorio.
- Sin modo oscuro por ahora.

---

## ADR-023 — Baja de laboratorios de demostración; un solo tenant demo
**Fecha:** 2026-09-26 · **Estado:** Aceptada

**Contexto.** Quedaban tres tenants de prueba (`demo_uno`, `demo_dos`, `demo_tres`). Sólo
`demo_uno` se usa para trabajar (usuario de Darwin, catálogo, precios). El aislamiento entre
laboratorios ya lo cubren las pruebas y `scripts/check_tenant_isolation.py`, que crean y
borran sus propios tenants. `Tenant.auto_drop_schema = False` (ADR-003) impide borrar un
esquema con un `delete()` común, y así debe seguir.

**Decisión.**
- `services/decommission.py::delete_demo_tenant()` y el comando
  `eliminar_laboratorio_demo --schema X --confirmar X`: única vía para borrar un esquema.
  Sólo acepta laboratorios en estado **DEMO**, exige repetir el esquema y rechaza `public`.
- Un laboratorio real (ACTIVO, SUSPENDIDO, MOROSO, CANCELADO) nunca se borra físicamente:
  se cancela.
- Se borran `demo_dos` y `demo_tres`; `demo_uno` (`demo1.localhost`) queda como único
  laboratorio de trabajo local.

**Consecuencias.** `migrate_schemas` corre más rápido. Si se necesita probar a mano el
aislamiento en el navegador, se crea un segundo laboratorio con `crear_laboratorio` y se
borra después con este comando.

---

## ADR-024 — Órdenes: número diario, tubos por aditivo y cotización congelada
**Fecha:** 2026-09-27 · **Estado:** Aceptada

**Contexto.** La Fase 09 abre el flujo clínico. Darwin planteó cómo se trabaja en la toma:
una etiqueta por tubo según su tipo (morado hematología, rojo química, azul coagulación),
con el mismo paciente y números de muestra distintos. La impresora de etiquetas aún no
está definida y el laboratorio no tiene precios cargados.

**Decisión.**
- **Numeración:** orden `AAMMDD-NNNN` con correlativo diario (`OrderNumberSequence`,
  `select_for_update`); muestra `AAMMDD-NNNN-SS`; código de barras = 12 dígitos (Code 128,
  sólo numérico, compatible con analizadores). Se eliminan `TenantSettings.order_number_*`.
- **Tubos por aditivo:** `catalog.ContainerType` (color, aditivo, orden de extracción CLSI,
  máximo de exámenes) y `SampleRequirement` (examen → tubo(s), toma por tiempo, tubo
  propio), en lugar del texto libre `Test.container`. La asignación es configuración de
  cada laboratorio. `Sample ↔ OrderItem` es M2M: un examen puede necesitar varios tubos.
- **Planificación pura** (`plan_tubes`): misma lógica para la vista previa y para guardar.
- **Cotización congelada** en la orden (`quote_snapshot` + totales + tasa). Si la lista no
  tiene precio para un examen, la orden se registra igual con `pricing_pending` y aviso; el
  paciente no espera por un precio sin cargar. No se puede marcar pagada así.
- **Nada se borra:** anular = estado + motivo; rechazar muestra = reemplazo con número
  nuevo que referencia a la rechazada; cada impresión de etiqueta queda registrada.
- **Etiquetas en PDF** (ReportLab, nueva dependencia) del tamaño configurado (50 × 25 mm
  por defecto), impresas desde el navegador: sirve para cualquier marca de impresora
  térmica sin instalar nada.
- `core` no importa otras apps: los indicadores de Inicio llegan por htmx desde `orders`.

**Consecuencias.**
- Las Fases 10 (resultados) y 16 (instrumentos) identifican la muestra por `barcode`.
- Laboratorios existentes: correr `seed_contenedores` una vez; los nuevos ya nacen con tubos.
- Una caja completa (abonos, métodos, vuelto) queda para una fase propia.
- Impresión ZPL directa exigiría un agente local; se evaluará si el PDF resulta lento.

---

## ADR-025 — Resultados: planilla única para vista previa y guardado, críticos con aviso, ISI por lote
**Fecha:** 2026-09-27 · **Estado:** Aceptada

**Contexto.** La Fase 10 carga y valida resultados. Hay que marcar alto/bajo/crítico según
el rango de cada paciente, calcular en vivo, congelar la referencia al validar y resolver
dos pendientes: dónde vive el ISI del INR y cómo se tratan los valores de pánico.

**Decisión.**
- `results.services.result_capture.build_sheet()` arma la planilla de la orden (valores,
  calculados, rango, marca, valor anterior) y la usan **igual** la vista previa en vivo
  (htmx, sin guardar) y el guardado: lo que se ve es lo que se guarda.
- `ResultValue` sólo existe si hay valor. Guarda marca, interpretación, rango y texto de
  referencia; al validar se recalcula con los rangos vigentes y queda congelado.
- Validado = inmutable, **incluidos los insumos** de un calculado ya validado. Corregir =
  rectificación (Fase 15).
- Críticos: `critical_low/high` por rango (sexo/edad). Un crítico no se valida sin un
  `CriticalNotification` con el valor confirmado y a quién se avisó; el aviso guarda el
  valor avisado y deja de servir si el valor cambia. Se siembran umbrales de literatura
  marcados «PROPUESTO» (no en rangos neonatales/pediátricos).
- ISI: `catalog.ReagentLot` con un único lote vigente por reactivo; el resultado copia
  lote e ISI (y peso, talla, orina y condición) en `calculation_context`.
- Condición del paciente en la orden (`NINGUNA`/`EMBARAZO`); si no hay rango para esa
  condición se usa el general.
- Doble validación configurable por laboratorio (`require_second_validation`): quien valida
  debe ser distinto de quien cargó.
- La bandeja vive en `orders.selectors` (por estado del examen), para que existan
  pendientes aunque nadie haya abierto la captura; la orden avanza vía
  `orders.services.order_progress`.
- Números con coma decimal y punto de miles (`150.000`, `13,4`); redondeo clínico mitad
  hacia arriba.

**Consecuencias.**
- Fase 11 imprime `reference_text` y la marca guardados, nunca los recalcula.
- Fase 16 (instrumentos) escribe con `source=INSTRUMENTO` por el mismo `save_sheet`.
- Los críticos propuestos deben confirmarse con cada laboratorio.
- `.content > * { min-width: 0 }` global: corrige desbordes en móvil de cualquier pantalla.

---

## ADR-026 — Observaciones por examen, no al final del informe
**Fecha:** 2026-09-27 · **Estado:** Aceptada

**Contexto.** Muchos sistemas ponen todas las observaciones al final del informe, lejos
del examen al que se refieren («SUERO LIPÉMICO» queda debajo de la serología). Darwin lo
considera poco práctico.

**Decisión.**
- `Result.observations` es **por examen** y el informe (Fase 11) la imprime debajo de ese
  examen. `Result.internal_note` es una nota de trabajo que nunca se imprime.
- `catalog.ObservationTemplate` con alcance: examen → sección → general. Al cargar se
  ofrecen en ese orden como botones; `__` marca un hueco que queda seleccionado para
  escribir («EUMÓRFICOS __ %»). Siembra desde `04_HALLAZGOS` §9 (`seed_observaciones`).
- Las observaciones se congelan al validar, como los valores.

**Consecuencias.** Fase 11 imprime cada observación bajo su examen. Si un laboratorio
quiere además una nota general de la orden, se agrega como campo de la orden, sin mover
estas.

---

## ADR-027 — Informe versionado desde contenido congelado, verificación por QR
**Fecha:** 2026-09-27 · **Estado:** Aceptada

**Contexto.** El informe es el documento legal del laboratorio. Debe verse igual siempre,
no sobrescribirse nunca, permitir parciales y poder verificarse. CLAUDE.md exige que el PDF
no sea una URL pública sino un token con expiración. `01_MODELO_DATOS` preveía
`ResultSignature` por resultado y `Report.pdf_url` en Cloudinary.

**Decisión.**
- `reports.Report` = una versión emitida. Guarda `payload` (todo lo que se imprime, en
  JSON) y `content_hash` = SHA-256 de su forma canónica; `previous_hash` encadena con la
  versión anterior. Mismo contenido → no se crea versión; distinto → versión N+1 y la
  anterior pasa a REEMPLAZADO. Constraint: una vigente por orden.
- El PDF se **genera siempre desde el payload** con ReportLab (no se guarda): mismo
  resultado en cualquier momento y ningún archivo clínico en almacenamiento público. Logo,
  firma y sello se referencian por ruta en el payload; subir una imagen nueva crea otro
  archivo, así un informe viejo conserva la firma con la que salió.
- Firma = quien validó cada examen (`Result.validated_by`) con su imagen de firma y sello
  (`accounts.User`), más la huella del informe. No se crea `ResultSignature`: la
  validación ya registra quién y cuándo, y la huella cubre el documento entero.
- Parcial: `kind=PARCIAL` si queda algún examen vigente sin validar; sólo se imprimen los
  validados y se listan los pendientes.
- QR → `/verificar/<verification_code>/`, código aleatorio de 22 caracteres por versión.
  Página pública sin valores clínicos ni nombres de exámenes (iniciales, últimos dígitos de
  la C.I., orden, versión, firmantes, huella). Descarga del PDF sólo para la versión
  vigente y hasta `report_link_days` (30 por defecto) desde la emisión: el código es el
  token y la expiración se controla en el servidor.
- Entregar = `orders.services.mark_delivered` (sólo con todo validado), que antes emite
  para que lo entregado sea lo último validado.
- Diseño propio con el contenido de §11 de los hallazgos; no se copia el formato de
  Angelus (ADR-018).

**Consecuencias.**
- Fase 15 (rectificaciones) reemite por `emit_report`: la versión anterior queda
  reemplazada y su QR lo avisa.
- Cambiar el diseño del PDF cambia cómo se ven también los informes viejos (el contenido
  no); si se necesitara el PDF exacto de un día, habría que guardarlo (evaluar en Fase 17
  con almacenamiento privado).
- `report_header_html` queda sin uso; `01_MODELO_DATOS` se actualiza (`Report`, sin
  `ResultSignature`).

---

## ADR-028 — Pie del informe: firma en cada página, firma de la plataforma y texto legal opcional
**Fecha:** 2026-09-27 · **Estado:** Aceptada

**Contexto.** Revisando el PDF de la Fase 11, Darwin pidió quitar del pie el texto «Los
resultados requieren firma y sello húmedo…», dejar la línea de verificación y agregar
debajo una firma de la plataforma («sistema elaborado por Biolife») editable desde el
administrador del SaaS, además de mostrar Instagram y correo del laboratorio bajo el
número de orden.

**Decisión.**
- El pie ya no trae texto legal por defecto: `TenantSettings.report_footer_text` se imprime
  sólo si el laboratorio lo configuró (sigue congelado en el contenido del informe).
- Pie: [texto del laboratorio, si hay] · enlace de verificación · ícono de Biolife + texto
  de la plataforma (el QR y la huella suben a la franja de firmas).
- `tenants.PlatformSettings` (esquema `public`, una fila): `report_brand_enabled`,
  `report_brand_text` (por defecto «Generado con Biolife · Sistema de gestión para
  laboratorios clínicos»), `report_brand_contact`. Se lee al **generar** el PDF (vía
  `tenants.services.platform.report_brand`), no se congela: cambiarla no crea versiones.
- Cabecera: Instagram y correo del laboratorio bajo «Orden N° / Versión»; el teléfono queda
  a la izquierda con los datos del laboratorio.
- **Firma en cada página:** la firma y el sello de quien validó (hasta 3 bioanalistas) van
  en una franja inferior de **todas** las páginas, a la derecha, y no al final del
  informe: una hoja suelta sigue firmada. En la misma franja, a la izquierda, el QR con
  «Verifique este informe» y la huella. Debajo de una línea fina: el enlace de
  verificación y, al final, el ícono de Biolife con su texto y «Página X de Y».
- Los modelos de `apps.tenants` (laboratorios, planes, suscripciones, plataforma) sólo se
  ven en el admin de `public` (`PublicOnlyAdmin`), aunque el usuario sea superusuario de
  un laboratorio.

**Consecuencias.** Los informes ya emitidos conservan el pie con que se congelaron (el
texto legal viejo sigue en la v1/v2 de las pruebas); al emitir de nuevo sale el pie nuevo.
La Fase 12 (SuperAdmin) moverá `PlatformSettings` a su propia pantalla.

---

## ADR-029 — Panel del laboratorio: roles fijos, varios por usuario, clave temporal
**Fecha:** 2026-09-28 · **Estado:** Aceptada

**Contexto.** Hasta la Fase 11 el laboratorio se configuraba en `/admin`: no apto para un
cliente. Hay que decidir cuánto controla cada laboratorio sobre roles y usuarios, y cómo
entra un usuario nuevo sin envío de correos configurado.

**Decisión.**
- Roles **definidos por Biolife** (fixture + tuplas de `accounts.permissions`); el
  laboratorio sólo los asigna. Un usuario puede tener varios (`Membership` ya lo permitía);
  sus permisos son la suma. La tabla «Roles» se genera de las mismas tuplas de las vistas.
- Nuevo rol `AUXILIAR_TOMA` (pk 7, creado por migración de datos en los laboratorios
  existentes): `COLLECTION_ROLES` (etiquetas, tomar, rechazar) y `VIEW_ORDER_ROLES`
  (lista de la toma y orden sin montos).
- Menú y botones según `can` (context processor `accounts.context_processors.ui`); las
  vistas siguen comprobando cada permiso con `role_required` (el menú no es seguridad).
- Alta con clave temporal (escrita o generada, 10 caracteres sin ambiguos, se muestra una
  vez) y `User.must_change_password` + `ForcePasswordChangeMiddleware` que sólo deja pasar
  `/cuenta/`, estáticos y `/verificar/` hasta cambiarla.
- Usuarios nunca se borran: se desactivan. Siempre queda un administrador activo; nadie se
  quita a sí mismo el acceso. Cambios en `AuditLog` (`USUARIO_*`, `CLAVE_*`,
  `LABORATORIO_MODIFICADO`, `PERFIL_MODIFICADO`).
- Razón social y RIF quedan en `tenants.Tenant` y sólo los edita el administrador del SaaS.

**Consecuencias.** Permisos por laboratorio o roles propios exigirían pasar las vistas de
tuplas de roles a permisos (`has_permission`); queda fuera. Invitación por correo y
recuperación de clave, cuando haya correo (Fase 17). La Fase 12 (SuperAdmin) tendrá la
pantalla para razón social/RIF.

---

## ADR-030 — Catálogo sin /admin: quién edita qué y nada se borra
**Fecha:** 2026-09-28 · **Estado:** Aceptada

**Contexto.** El catálogo (exámenes, parámetros, rangos, perfiles, precios) se editaba en
el `/admin` provisional (ADR-020). El laboratorio necesita pantallas propias y hay que
fijar quién puede cambiar qué, y qué pasa con lo que ya tiene historial.

**Decisión.**
- Pantallas en `apps.catalog` (`/catalogo/`) y `apps.billing` (`/precios/`) con la lógica
  existente: formularios de rangos de la Fase 08b (años/meses/días, solapes, huecos,
  probador), `validate_formula`/`sync_parameter_dependencies`, `set_profile_tests`,
  `set_price`/`adjust_prices`/`copy_price_list`/`register_exchange_rate`.
- Permisos: `CATALOG_EDIT_ROLES` (administrador) estructura; `CLINICAL_EDIT_ROLES`
  (administrador, bioanalista) rangos, críticos y observaciones; `PRICE_EDIT_ROLES`
  (administrador, facturación) precios y tasa; `VIEW_ROLES` consultan. Lo que el rol no
  puede cambiar se muestra deshabilitado y el servidor lo ignora/rechaza (403).
- **Nada se borra**: exámenes, parámetros, rangos y observaciones se desactivan; se
  pueden quitar filas de tubos requeridos y grupos sin parámetros. Un precio vacío
  desactiva el ítem de la lista.
- **Campos fijos por historial**: código del examen si ya se ordenó; código y tipo de
  valor del parámetro si tiene resultados (lo demás, p. ej. unidad o decimales, se puede
  corregir: los informes congelan lo impreso).
- Ediciones en `AuditLog` (`EXAMEN_GUARDADO`, `PARAMETRO_GUARDADO`, `RANGOS_GUARDADOS`,
  `OBSERVACIONES_GUARDADAS`, `PERFIL_GUARDADO`).
- Un perfil al que le falta un examen que alimenta sus cálculos se guarda con aviso
  (`allow_incomplete`): lo decide el laboratorio.

**Consecuencias.** Las tablas auxiliares siguen en `/admin` hasta la 11d. Los registros
de admin de exámenes/parámetros/perfiles/precios se conservan para soporte, pero ya no
están en el menú.

---

## ADR-031 — Tablas auxiliares sin /admin: motor genérico en core
**Fecha:** 2026-09-28 · **Estado:** Aceptada

**Contexto.** Tras la 11c quedaban en `/admin` nueve tablas pequeñas (secciones,
unidades, métodos, listas de opciones, observaciones generales, tubos, lotes de
reactivos, monedas, descuentos). Hacer lista y ficha a mano para cada una repetía el
mismo código nueve veces, y viven en dos apps (`catalog`, `billing`) que no pueden
importarse entre sí.

**Decisión.**
- `apps/core/aux_tables.py` define `AuxTable` y un registro; `core` pone el índice
  (`/tablas/`), la lista y la ficha sin importar ningún modelo. Cada app describe sus
  tablas (formulario, consulta, celdas de la lista, permisos, guardado) y las registra en
  `AppConfig.ready()`. Respeta la regla 3 (`core` no importa apps).
- Permisos: estructura (secciones, unidades, métodos, tubos) el administrador; listas de
  opciones y observaciones generales `CLINICAL_EDIT_ROLES`; lotes `LOT_EDIT_ROLES`
  (administrador, bioanalista, técnico); monedas y descuentos `PRICE_EDIT_ROLES`;
  consulta `VIEW_ROLES`.
- Nada se borra. Código fijo cuando el registro ya está en uso. Opciones de una lista con
  resultados conservan su texto (reemitir un informe no debe cambiar lo que dice).
- Lote vigente único por reactivo: el service desmarca el anterior en la misma
  transacción; el formulario excluye `is_current` de la validación de la restricción
  condicional para no bloquear el cambio.
- Moneda base fija desde pantallas; una moneda nueva nunca es base.
- Bitácora `TABLA_CREADA` / `TABLA_MODIFICADA` con los campos cambiados.

**Consecuencias.** Una tabla auxiliar nueva es una entrada `AuxTable` + su formulario, sin
vistas ni plantillas. Tablas con lógica propia (catálogo diario, precios, pacientes)
siguen con pantallas dedicadas. Gotcha: los modelos con UUID tienen `pk` antes de
guardarse, así que "¿es nuevo?" se pregunta con `instance._state.adding`, no con `pk`.
Otro: ninguna carpeta o archivo puede llamarse `aux` (nombre reservado de Windows); las
plantillas van en `templates/core/tablas/`.

---

## ADR-032 — Ficha del paciente, antecedentes y evolución con gráficos propios
**Fecha:** 2026-09-28 · **Estado:** Aceptada

**Contexto.** El paciente sólo se podía crear; para editarlo había que ir a `/admin`. El
laboratorio quiere ver la evolución de un paciente (p. ej. la glicemia de un diabético)
y entregarla al médico.

**Decisión.**
- Lista y ficha en `apps.patients`; el historial de órdenes y las series de resultados se
  piden a `orders` y `results` por sus selectors públicos.
- **Evolución sólo con resultados validados** y numéricos; fecha = la de la orden; banda =
  el rango de referencia guardado al validar (`ResultValue.reference_range`), así cambia
  con la edad o el sexo como el informe.
- **Gráfico propio**: `core/charts.py` calcula la geometría una vez; se dibuja en SVG
  (pantalla, colores por clases CSS) y con ReportLab (PDF) desde los mismos números. Sin
  librerías JS de gráficos.
- **Antecedentes** por laboratorio (`Antecedent` con `suggested_parameters`) como tabla
  auxiliar (ADR-031); `PatientAntecedent` guarda quién y cuándo, y se desactiva en lugar
  de borrarse. Se asignan con `RECEPTION_ROLES`; la tabla la editan administrador y
  bioanalista.
- El PDF de evolución no es un informe: sin firma ni QR, y lo dice.

**Consecuencias.** Si un rango se edita en el lugar, la banda de puntos viejos refleja el
rango editado (el texto impreso sí queda congelado). Parámetros codificados en la
evolución y la unión de pacientes duplicados quedan fuera.

---

## ADR-033 — Escritura offline: idempotencia por `client_mutation_id` y cálculo clínico sólo en el servidor
**Fecha:** 2026-10-14 · **Estado:** Aceptada

**Contexto.** La conexión se cae: en el domicilio del paciente, donde el auxiliar toma la
muestra, y en el propio laboratorio mientras el bioanalista carga resultados. El diseño de
la Fase 00 (`00_ARQUITECTURA` §5) ya fijaba la mecánica —cola en IndexedDB,
`client_mutation_id`, `sync_version`, conflictos registrados— pero no estaba construida.
La pregunta real era cuánto del dominio se replica en el dispositivo.

**Decisión.**
- **La idempotencia no vive en código sino en un índice único**: `SyncQueueEntry.
  client_mutation_id` (UUID v4 que genera el dispositivo y repite en cada reintento).
  Encolar es un `get_or_create` por ese id y una entrada ya resuelta no se vuelve a
  aplicar. Reenviar la cola completa diez veces deja un solo efecto.
- **El dispositivo no calcula nada clínico.** Guarda lo escrito en crudo; el motor de
  fórmulas, la resolución de rangos por sexo/edad/condición y las marcas alto/bajo/crítico
  corren en `save_sheet()` al sincronizar. No se replica esa lógica en JavaScript: dos
  implementaciones divergen con el tiempo y la divergencia aquí significa un valor crítico
  que no se marca. El precio aceptado es que sin conexión no se ven calculados ni marcas.
- **Un resultado validado nunca se sobrescribe** (regla de `CLAUDE.md`). La mutación queda
  en `CONFLICTO` con el valor del dispositivo y el del servidor, y decide una persona;
  corregir sigue siendo una rectificación (Fase 15). Igual con `sync_version`: si otro
  usuario cambió el resultado mientras tanto, se registra el conflicto en vez de pisarlo.
- **La cola es una puerta más al dominio**, así que repite el control de acceso de las
  pantallas por tipo de mutación (`ROLES_BY_KIND`): el auxiliar de toma marca tubos por la
  cola, pero no captura resultados ni registra órdenes aunque arme el JSON a mano.
- La cola **local** guarda sólo lo que todavía no llegó al servidor; en cuanto el servidor
  acusa recibo (aplicada, en conflicto o con error) la entrada se borra del dispositivo.
  Una sola lista de verdad, consultable en la pantalla de *Sincronización*.
- Validar, emitir PDF y cobrar siguen siendo sólo en línea; sus botones se deshabilitan
  sin conexión en vez de dejar que el POST falle en el vacío.

**Consecuencias.** La captura offline se ve "sin marcas" hasta sincronizar, lo que hay que
explicarle al laboratorio. Una mutación se atribuye a quien la sincroniza, no a quien la
capturó, si en el mismo dispositivo cambia el usuario. El JavaScript de la cola no tiene
tests automáticos (no hay infraestructura de JS en el proyecto); se cubre el contrato que
consume —los atributos `data-offline` de las plantillas— y todo el lado servidor.

---

## ADR-034 — Numeración de órdenes offline: bloques reservados por dispositivo
**Fecha:** 2026-10-14 · **Estado:** Aceptada

**Contexto.** El número de orden es `AAMMDD-NNNN` y el código de barras de cada tubo son
esos mismos dígitos (ADR-024). El diseño original preveía crear órdenes offline con un
número provisional y renumerar al sincronizar, pero entonces cualquier etiqueta impresa
antes de sincronizar queda con un código que el sistema no conoce: tubos no
identificables, que en un laboratorio es un problema clínico, no cosmético.

**Decisión.** Cada dispositivo, **mientras tiene conexión**, reserva un rango de números
del día (`OrderNumberBlock`) avanzando la misma `OrderNumberSequence` que usa la recepción
en línea, y lo consume sin conexión. El número es definitivo desde que la orden nace: no
hay renumeración. Un dispositivo puede pedir varios bloques el mismo día. El servidor
comprueba que el número recibido salga de un bloque **de ese** dispositivo y que no exista
ya, antes de crear la orden.

**Consecuencias.** Pueden quedar huecos en la numeración del día si un dispositivo no
consume todo su bloque — se acepta a cambio de que ninguna etiqueta mienta. Los **tubos**
de una orden creada offline se generan al sincronizar: planificarlos exige el catálogo de
envases y los requisitos por examen, y replicar eso en el dispositivo sería repetir el
error que ADR-033 evita. Hasta sincronizar sólo se tiene el número de la orden, no el
desglose `-SS` de cada tubo.
