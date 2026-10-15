# Fase 14 — Escritura offline y sincronización

**Estado:** **completada** (2026-10-14) salvo el tramo D, anotado abajo como trabajo
aparte. ADR-033 (idempotencia y cálculo sólo en el servidor) y ADR-034 (bloques de
numeración) en `DECISIONES.md`.

**Depende de:** 13 · **Criterio de salida:** captura offline idempotente, conflictos
registrados.

> Fase marcada **Opus** en `00_INDICE.md`: es sincronización de datos clínicos, donde un
> error no se ve en los tests y cuesta caro en la vida real (un valor que se pierde, un
> tubo mal identificado, un resultado validado sobrescrito). Se ejecuta en Opus a pedido
> de Darwin (2026-10-14), cambiando el modelo de la sesión en vez de abrir tarea nueva.

## Lo que ya venía decidido (diseño de la Fase 00)

`docs/00_ARQUITECTURA.md` §5 y `docs/01_MODELO_DATOS.md` §G ya fijaron la mecánica, y
esta fase la respeta: IndexedDB vía Dexie con un store `mutation_queue`,
`client_mutation_id` (UUID v4) por mutación con endpoint **idempotente** por ese id,
`sync_version` por registro, modelos `SyncQueueEntry`/`SyncConflict`, conflictos
registrados para revisión humana y **nunca** descarte silencioso en datos clínicos, y
TTL de 24 h para la caché offline.

Nada de eso estaba implementado (`Order` no tenía `client_mutation_id` ni
`sync_version`), con una excepción heredada de la Fase 10 que sí se aprovecha:
`ResultValue.Source.OFFLINE_SYNC` ya existía.

## Decisiones (Darwin, 2026-10-14)

- **Alcance de escritura offline:** tomar y rechazar muestras, capturar resultados, y
  **crear órdenes y pacientes**. Validar resultados, emitir PDF y cobrar siguen siendo
  sólo en línea (lo exige el diseño: requieren estado del servidor).
- **Sin cálculo en el dispositivo:** offline se guarda lo escrito en crudo. El motor de
  fórmulas, la resolución de rangos por sexo/edad/condición y las marcas
  (alto/bajo/crítico) corren en el servidor al sincronizar. No se replica lógica clínica
  en JavaScript: una sola fuente de verdad, sin riesgo de que las dos versiones
  diverjan y un valor crítico deje de marcarse.
- **Numeración de órdenes por bloques reservados:** cada dispositivo, mientras tiene
  conexión, reserva un rango de números del día (`OrderNumberBlock`) avanzando la misma
  `OrderNumberSequence` que usa la recepción en línea. El número es definitivo desde que
  la orden nace offline: no hay renumeración y una etiqueta impresa nunca queda con un
  código que no existe. Precio aceptado: pueden quedar huecos en la numeración del día
  si un dispositivo no consume todo su bloque.
- **Choque con un resultado ya validado:** la mutación se rechaza y queda registrada
  como conflicto con el valor del dispositivo y el del servidor. Un resultado validado
  no se toca nunca (regla no negociable de `CLAUDE.md`); corregir es una rectificación
  (Fase 15).
- **Pacientes duplicados al sincronizar:** si el tipo y número de documento coinciden
  exactamente con un paciente existente, se reutiliza ese paciente y la orden se le
  cuelga a él (no se crea duplicado). Sin documento, o con datos parecidos y documento
  distinto, se crea y queda marcado como posible duplicado en la pantalla de
  Sincronización — sin fusionar nada automáticamente.
- **Dónde se revisa:** pantalla propia de *Sincronización* (pendientes por subir, lo que
  falló, conflictos a resolver) más un contador en el aviso de "sin conexión" de la
  Fase 13.

## Plan por tramos

Esta fase es la más grande del roadmap hasta ahora, así que se entrega por partes
verificables con `pytest` en vez de un volcado único:

- **Tramo A — servidor (hecho y verificado, 2026-10-14):** app `apps.sync` (modelos),
  campos de idempotencia y versión en los modelos existentes, reserva de bloques de
  numeración, servicio de aplicación idempotente de mutaciones, endpoints, tests.
- **Tramo B — cliente (hecho, 2026-10-14):** Dexie como estático *vendor* (sin build,
  igual que htmx y Alpine), cola en IndexedDB, interceptar los formularios habilitados
  para offline, reintento al volver la conexión, TTL de 24 h.
- **Tramo C — pantalla (hecho, 2026-10-14):** *Sincronización* (pendientes, errores,
  conflictos con revisión humana) y los contadores en el menú y en el aviso de sin
  conexión.
- **Tramo D — pendiente:** crear **órdenes y pacientes** sin conexión *desde el
  navegador*. El servidor ya los acepta y está probado; lo que falta es el cliente, y no
  sale de interceptar el formulario actual: *Nueva orden* busca pacientes y exámenes por
  htmx contra el servidor, así que offline no hay con qué llenarlo. Requiere precargar
  catálogo y pacientes en IndexedDB y una variante offline de esa pantalla, además de
  consumir el bloque de numeración ya reservado. Es un trabajo propio, no un pegote.

## Qué se hizo

### Tramo A — servidor

- [x] `apps.sync` (TENANT_APP nueva, agregada a `TENANT_APPS` en
  `config/settings/base.py`):
  - `Device` — un dispositivo del laboratorio, identificado por un UUID que genera el
    navegador y guarda localmente. Es lo que permite reservar numeración "por
    dispositivo" y saber de dónde vino cada mutación.
  - `OrderNumberBlock` — el rango de números del día reservado a un dispositivo
    (`from_value`–`to_value`, inclusive), uno por dispositivo y día.
  - `SyncQueueEntry` — una mutación recibida: `client_mutation_id` **único** (la
    idempotencia vive en ese índice, no en código), `kind`, `payload`,
    `client_created_at` (cuándo ocurrió de verdad en el dispositivo), `status`
    (PENDIENTE/APLICADO/CONFLICTO/ERROR) y a qué objeto afectó.
  - `SyncConflict` — qué chocó, con el valor del cliente y el del servidor, el motivo
    (resultado validado, versión vieja, paciente duplicado…) y su resolución.
- [x] Campos nuevos en modelos existentes (sin tocar su lógica):
  `Order.client_mutation_id` + `Order.sync_version`, `Result.sync_version`,
  `Patient.client_mutation_id`.
- [x] `services/number_blocks.py`: `reserve_block()` (avanza `OrderNumberSequence`, así
  los números del bloque no se le dan a nadie más), `number_from_block()` — que es la
  defensa contra un número inventado: si el número no sale de un bloque **de ese**
  dispositivo, la mutación se rechaza — y `parse_order_number()`.
- [x] `services/apply.py`: `receive()` encola y aplica un lote; cada mutación en su
  propia transacción, así una que falla no tumba el resto. Los cinco tipos:
  paciente nuevo, orden nueva, muestra tomada, muestra rechazada, resultado capturado.
  Todo lo clínico se resuelve aquí (`save_sheet()`), con `source=OFFLINE_SYNC` y la hora
  real del dispositivo.
- [x] **Control de acceso por tipo de mutación** (`ROLES_BY_KIND`): la cola es una puerta
  de entrada más al dominio, así que repite los permisos de las pantallas. Un auxiliar de
  toma puede marcar tubos por la cola pero no capturar resultados ni registrar órdenes,
  aunque arme el JSON a mano.
- [x] Endpoints en `/sincronizacion/` (`apps.sync.urls`, montado en
  `config/urls_tenant.py`): `mutaciones/` (lote, idempotente), `bloque/` y
  `bloque/consumido/`, `estado/`. Sesión y CSRF normales, sin tokens de dispositivo:
  `device_id` dice de dónde vino la mutación, no autentica.
- [x] Parches **aditivos** a servicios existentes, sin cambiar su comportamiento en
  línea: `create_order(number=, ordered_at=, client_mutation_id=)` — la cotización se
  congela con los precios del día en que se registró la orden, no los de la
  sincronización; `collect_sample(at=)` / `reject_sample(at=)`; `save_sheet(source=, at=)`
  y `Result.sync_version` que sube en cada guardado con cambios reales.
- [x] Tests (`apps/sync/tests/`, 24 casos): bloques que no se solapan y número ajeno
  rechazado; reenviar un lote no repite efecto; una mutación mala no tumba el lote; la
  toma guarda la hora del dispositivo; el servidor marca el crítico de un valor que llegó
  en crudo; **un resultado validado no se sobrescribe nunca**; conflicto por versión
  vieja; documento repetido reutiliza el paciente; orden offline con el número de su
  bloque; y los límites de rol por tipo de mutación.

### Tramo B — cliente

- [x] `static/vendor/dexie-4.0.11.min.js` (94 KB, Apache-2.0, bajado del registro npm):
  se sirve como estático *vendor* igual que htmx y Alpine, sin build, como pide
  `03_CONVENCIONES.md` («la PWA necesita ser liviana: se usa en equipos viejos»).
- [x] `static/js/sync.js`: cola en IndexedDB vía Dexie.
  - La cola local guarda **sólo lo que todavía no llegó** al servidor. En cuanto el
    servidor acusa recibo (aplicada, en conflicto o con error), la entrada se borra de
    aquí: desde ese momento la verdad vive en el servidor y se consulta en la pantalla.
    Así no hay dos listas que puedan contradecirse.
  - `client_mutation_id` (UUID v4) por entrada, repetido en cada reintento; el
    `device_id` se genera y guarda en `localStorage` (y es efímero si el navegador lo
    bloquea, sin romper la cola).
  - Envío al cargar la página, al evento `online` y cada 60 s si queda algo. Un 4xx/5xx
    no borra nada: se reintenta.
  - **TTL de 24 h**: si pasaron más de 24 h desde la última vez con conexión, se niega a
    encolar más capturas y lo dice — evita trabajar sobre catálogos y precios vencidos.
  - `data-online-only`: validar, cobrar, recotizar, anular, actualizar datos clínicos y
    registrar avisos de crítico se **deshabilitan** sin conexión en vez de dejar que el
    POST falle en el vacío.
- [x] Formularios habilitados con `data-offline` (el contrato entre plantilla y cliente,
  cubierto por tests): tomar un tubo y «marcar todas tomadas» (una mutación por tubo,
  con los ids en `data-offline-samples`), rechazar un tubo con su motivo, y la captura de
  resultados completa — que viaja con `data-offline-versions`, la versión que tenía cada
  resultado al abrir la pantalla, para que el servidor detecte si otro lo cambió.
- [x] `templates/core/sw.js`: Dexie y `sync.js` entran al caché del "esqueleto". Sin eso,
  una página abierta sin conexión no podría encolar nada — justo cuando hace falta.

### Tramo C — pantalla

- [x] `/sincronizacion/` (`views.panel` + `templates/sync/panel.html`): lo que está en la
  cola de este dispositivo (con botón *Enviar ahora*), los conflictos por revisar con el
  valor del dispositivo y el del servidor lado a lado, las mutaciones pendientes o
  fallidas con su motivo, la numeración reservada del día y las últimas aplicadas.
- [x] `retry_entry()` + `/sincronizacion/<pk>/reintentar/`: reintenta sólo lo que está en
  ERROR (una aplicada no se repite; una en conflicto espera a una persona). Sirve para el
  caso típico de mutaciones que llegaron en desorden.
- [x] `/sincronizacion/conflictos/<pk>/revisado/`: marca quién revisó y qué decidió, con
  nota. **No aplica lo del cliente**: un resultado validado es inmutable, así que la
  corrección real es capturar de nuevo o rectificar (Fase 15). Resolver exige rol clínico
  (administrador o bioanalista); el técnico ve la pantalla pero no resuelve.
- [x] Entrada «Sincronización» en el menú con badge de lo que necesita revisión, y
  contador de pendientes en el aviso de sin conexión de la Fase 13.
- [x] Tests (`test_panel.py`): reintento, permisos de resolución, que marcar revisado no
  altere el resultado validado, y el **contrato de las plantillas** — que sigan
  publicando `data-offline`, `data-offline-order` y un `data-offline-versions` que sea
  JSON válido. Si alguien los quita al editar una pantalla, la captura offline se
  rompería en silencio; esto lo detecta.

**Gotcha anotado** (mismo patrón que el `Decimal` de la Fase 12): el
`client_mutation_id` llega como texto del JSON y Django no coacciona el atributo en
memoria al asignarlo, sólo al escribirlo en la base — así que `_enqueue()` lo castea a
`uuid.UUID` a propósito. Sin eso, el objeto en memoria quedaba con un `str` y cualquier
comparación en Python contra el UUID guardado fallaba (lo destapó un test).

## Limitaciones conocidas / no incluye

- **El JavaScript del tramo B no está cubierto por tests automáticos**: el proyecto no
  tiene infraestructura de tests de JS y no se montó una para esto. Lo que sí se prueba
  es el contrato que el cliente consume (los atributos `data-offline` de las plantillas)
  y todo el lado servidor. El comportamiento de la cola en sí hay que verificarlo en un
  navegador — está en la lista de abajo.
- **Sin cálculo en vivo offline**: la planilla de captura calcula por htmx contra el
  servidor, así que sin conexión no se ven calculados ni marcas hasta sincronizar. Es la
  consecuencia directa y buscada de no replicar el motor de fórmulas en el dispositivo.

- **Los tubos de una orden creada offline se generan al sincronizar.** El plan de tubos
  (`plan_tubes`) necesita el catálogo de envases y los requisitos por examen, y
  replicarlo en el dispositivo sería duplicar lógica igual que el motor de fórmulas. El
  número de la orden sí es definitivo offline (bloques), así que no hay re-rotulado: lo
  que falta hasta sincronizar es el desglose `-SS` de cada tubo y su etiqueta. Para el
  caso real de toma a domicilio esto no estorba: ahí la orden se registra en el
  laboratorio con conexión y el auxiliar sólo marca tomada/rechazada offline.
- **Autoría de la mutación offline:** se atribuye al usuario que la sincroniza. Si el
  auxiliar captura con su sesión y otro usuario sincroniza desde el mismo dispositivo,
  el `created_by` sería el del segundo. El `payload` guarda el usuario original para
  trazabilidad, pero no se suplanta la sesión.
- Validar resultados, emitir PDF y cobrar no funcionan offline (decisión del diseño).
- No hay resolución automática de duplicados de paciente sin documento: se marcan.
  Unirlos sigue siendo la tarea pendiente de `TASKS.md`.
- Sin sincronización en segundo plano del service worker (Background Sync API): el envío
  se dispara cuando la app está abierta y vuelve la conexión.

## Verificación pendiente en la máquina de Darwin

- [x] ~~`makemigrations sync orders results patients`~~ (2026-10-14)
- [x] ~~`pytest -q` y `ruff check .` del tramo A~~ (2026-10-14) — 339 passed, ruff limpio
- [x] ~~`pytest -q`, `ruff check .` y `manage.py check` con los tramos B y C~~
  (2026-10-14) — 350 passed, ruff limpio, sin issues
- [x] ~~Aplicar las migraciones en los tenants (`migrate_schemas`)~~ (2026-10-14) —
  `orders.0004`, `patients.0004`, `results.0003` y `sync.0001` en `public` y `demo_uno`.
- [x] ~~Service worker nuevo activo~~ (2026-10-14) — versión #609 en `demo1.localhost`.
- [x] ~~Prueba sin conexión completa~~ (2026-10-14, Darwin): marcar un tubo y capturar un
  resultado offline, reconectar y ver que suben una sola vez con las marcas puestas por
  el servidor; botones de validar/cobrar/anular deshabilitados sin conexión; y el choque
  contra un resultado validado en otra sesión, que no se alteró y quedó como conflicto
  en `/sincronizacion/`.
