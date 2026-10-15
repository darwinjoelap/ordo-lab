# HISTORIAL — Biolife

> Detalle de las fases cerradas y notas que salieron de `ESTADO.md` para mantenerlo corto.
> Se agrega al final; las decisiones de diseño siguen en `DECISIONES.md` (ADRs).

## Fases completadas (detalle, hasta 2026-09-28)

- [x] Fases 00–08b (hasta `53655ab`): diseño, multi-tenancy, usuarios y roles, configuración,
  pacientes, catálogo, rangos, fórmulas, perfiles, precios, ficha del examen (ADR-001–020).
- [x] Fases 08c, 08d y limpieza (`39a4491`, `7ad6be1`): provisión con catálogo, CI, sistema
  visual, baja de laboratorios demo (ADR-021–023). Verificado: 183 passed; CI en verde.
- [x] Fase 09 (`9919111`): órdenes, tubos, etiquetas, recepción (ADR-024). Verificado: 211.
- [x] Fase 10 (`f934aaf`, `bac4352`): captura con cálculo en vivo, marcas alto/bajo/crítico, aviso de
  críticos, validación que congela referencias, ISI por lote, observaciones por examen
  (ADR-025/026). Verificado por Darwin: 246 passed, ruff limpio.
- [x] Fase 11 (hasta `212bb7a`): informe PDF versionado desde contenido congelado,
  parciales, huella SHA-256, verificación pública por QR, bandeja *Informes*, entrega
  (ADR-027); firma y sello del bioanalista y QR en cada página, pie con firma de Biolife
  editable en `public`, Instagram/correo en la cabecera, recotizar órdenes con precio
  pendiente, avisos de examen sin parámetros, tomar tubo con resultados ya cargados
  (ADR-028). Verificado por Darwin: 259 passed, ruff limpio.
- [x] Ajuste de *Muestras por tomar* (`986b830`): etiquetas impresas atenuadas y al final
  con quién/cuándo, imprimir desde la fila, sin columna de pago, se actualiza sola cada
  20 s (roadmap 09, «Ajuste posterior»). Verificado por Darwin: 260 passed.
- [x] Fase 11b (`852c3f4`): datos del laboratorio, usuarios con clave temporal, varios
  roles por usuario, tabla de roles, mi perfil con firma y sello, rol Auxiliar de toma,
  menú según rol (ADR-029). Verificado por Darwin: accounts.0006, 269 passed, ruff limpio.
- [x] Fase 11c (`656ed95`): exámenes, parámetros, rangos/críticos con probador,
  observaciones, perfiles, precios en tabla editable, ajuste masivo, copia de listas y
  tasa de cambio, sin /admin; permisos por rol y nada se borra (ADR-030). Verificado
  por Darwin: 276 passed, ruff limpio.
- [x] Fase 11d (`9640297`): tablas auxiliares sin /admin (secciones, unidades, métodos,
  listas de opciones, observaciones generales, tubos, lotes, monedas, descuentos) con motor
  genérico en `core`; lotes también bioanalista y técnico, monedas y descuentos también
  facturación; moneda base fija (ADR-031). Verificado por Darwin: 287 passed, ruff limpio.
- [x] Fase 11e (`518ba38`): pacientes sin /admin (lista, ficha, representantes,
  historial), antecedentes con parámetros a vigilar, evolución con gráfico SVG propio,
  tendencias, PDF para el médico, variación del valor anterior al cargar (ADR-032).
  Verificado por Darwin: migraciones patients.0002/0003, 298 passed, ruff limpio.

## Advertencia sobre el fixture de localidades

`apps/masterdata/fixtures/localidades.json` tiene los 21 nombres exactos de
`04_HALLAZGOS_FORMATOS.md`, pero el estado/municipio de cada uno se completó por
conocimiento general de geografía venezolana, no por dato del laboratorio. Cantagallo, Dos
Caminos, Las Minas y Píritu quedaron sin municipio por falta de certeza. Confirmar con el
laboratorio antes de producción.

## Fase 14 — Escritura offline y sincronización (2026-10-14)

Ejecutada en Opus, como manda el índice del roadmap para esta fase. Respeta la mecánica
que ya fijaba `00_ARQUITECTURA.md` §5 y la completa.

- **App `apps.sync`**: `Device`, `OrderNumberBlock`, `SyncQueueEntry`, `SyncConflict`.
  Campos nuevos en los modelos existentes: `Order.client_mutation_id`/`sync_version`,
  `Result.sync_version`, `Patient.client_mutation_id` (migraciones `orders.0004`,
  `patients.0004`, `results.0003`, `sync.0001`).
- **Idempotencia** apoyada en el índice único de `client_mutation_id` (ADR-033): reenviar
  la cola nunca duplica. **Cálculo clínico sólo en el servidor**: el dispositivo guarda en
  crudo y `save_sheet()` resuelve fórmulas, rangos y marcas al sincronizar. Un resultado
  validado nunca se sobrescribe: queda conflicto para revisión humana.
- **Numeración por bloques reservados por dispositivo** (ADR-034): el número de una orden
  creada sin conexión es definitivo desde que nace, así ninguna etiqueta queda con un
  código de barras inexistente.
- **Cliente** (`static/js/sync.js` + Dexie 4.0.11 como vendor, sin build): cola en
  IndexedDB, interceptor de los formularios marcados con `data-offline`, reintento al
  reconectar, TTL de 24 h, y `data-online-only` para lo que exige servidor.
- **Pantalla** `/sincronizacion/`: cola del dispositivo, conflictos con el valor de cada
  lado, reintento de las fallidas, numeración reservada y últimas aplicadas.
- Verificado por Darwin: 350 passed, ruff limpio, migraciones aplicadas en `public` y
  `demo_uno`, y prueba sin conexión completa en el navegador (encolar, reconectar sin
  duplicar, marcas puestas por el servidor, y el choque contra un resultado validado).
- **Queda aparte (tramo D):** crear órdenes y pacientes offline *desde el navegador*. El
  servidor ya los acepta y está probado; falta el cliente, que exige precargar catálogo y
  pacientes en IndexedDB porque *Nueva orden* busca por htmx.
