# Tasks — Biolife

## Active

- [ ] **Fase 14 — tramo D: crear órdenes y pacientes offline desde el navegador** - el servidor ya los acepta y está probado (apps.sync); falta el cliente: *Nueva orden* busca pacientes y exámenes por htmx, así que hace falta precargar catálogo y pacientes en IndexedDB, una variante offline de esa pantalla y consumir el bloque de numeración reservado. Ver `docs/roadmap/14_sync_offline.md` → Tramo D
- [ ] **Fase 13 — PWA base y modo lectura offline (código verificado, falta probar en el navegador)** - service worker (Órdenes/Pacientes lista y detalle, sin acciones), manifest instalable, página `/offline/`, botón "Instalar app" dentro del popover del avatar; sin migraciones. `pytest` 315 passed y `ruff check .` limpio (2026-10-14). Checklist en `docs/roadmap/13_pwa_offline.md`:
  - [x] ~~`pytest -q` y `ruff check .`~~ (2026-10-14) — 315 passed, ruff limpio
  - [ ] Probar en el navegador: instalar, cortar conexión (DevTools), confirmar que Órdenes/Pacientes visitados abren igual y que login/panel no cambiaron
- [ ] **Cargar precios reales** en la lista GENERAL (Catálogo → Precios) y la tasa del día
- [ ] **Crear lote de tromboplastina vigente en demo_uno** - sólo cuando se pruebe PT/INR; Catálogo → Tablas auxiliares → Lotes de reactivos, con su ISI (sin él el INR queda vacío)
- [ ] **Revisión manual de la Fase 11** - firma/sello/título, logo, RIF; parcial → final; QR; entregar (checklist en `docs/roadmap/11_informe.md`)
- [ ] **Revisión manual de la Fase 11b** - crear Auxiliar de toma y entrar con él; firma/sello en Mi perfil (checklist en `docs/roadmap/11b_panel_laboratorio.md`)
- [ ] **Revisión manual de la Fase 11c** - examen de prueba completo, precios y tasa reales, entrar como bioanalista (checklist en `docs/roadmap/11c_catalogo.md`)
- [ ] **Revisión manual de la Fase 11d** - recorrer Tablas auxiliares, unidad de prueba creada y desactivada, entrar como técnico (checklist en `docs/roadmap/11d_tablas_auxiliares.md`)
- [ ] **Revisión manual de la Fase 11e** - ficha, evolución y PDF de un paciente con varios resultados validados; antecedente visible al crear su orden (checklist en `docs/roadmap/11e_pacientes.md`)
- [ ] **Unir pacientes duplicados** - p. ej. los «Sutil, Luis» de prueba en demo_uno; fase por definir
- [ ] **Fase 12 — SuperAdmin (código verificado, falta probar en el navegador)** - middleware de suspensión, servicios, panel sin /admin bajo `/panel/`, sin migraciones nuevas; `pytest` 311 passed y `ruff check .` limpio (2026-10-08); tu usuario ya tiene `is_superuser=True`. Checklist en `docs/roadmap/12_superadmin.md`:
  - [x] ~~`pytest -q` y `ruff check .`~~ (2026-10-08) — 311 passed, ruff limpio
  - [x] ~~Confirmar tu usuario en `public` con `is_superuser=True`~~ (2026-10-08)
  - [ ] Probar el panel: dashboard, crear/suspender/reactivar un laboratorio DEMO de prueba, planes
  - [ ] Borrar el laboratorio DEMO de prueba al terminar
- [ ] **Cargar firma, sello, título y colegiatura** - de cada bioanalista (admin → Usuarios → Datos de Biolife); razón social y RIF del laboratorio
- [ ] **Confirmar valores críticos propuestos** - con el laboratorio (ficha del examen → Valores críticos)
- [ ] **Caja** - abonos, métodos de pago (efectivo, pago móvil, transferencia, divisas), vuelto; fase propia (ADR-024)
- [ ] **Definir impresora de etiquetas** - modelo y tamaño real; ajustar ancho/alto en Laboratorio (hoy 50 × 25 mm)

## Waiting On

- [ ] **Confirmar LDH, TGO/TGP, unidad de insulina y composición de perfiles** - con el laboratorio de referencia (ADR-019)
- [ ] **Revisar factor ×100 de URO_INDICE_PROT_CREAT** - unidad mg/g requeriría ×1000 (ADR-017), cuando Angelus confirme el parámetro
- [ ] **No usar en un informe real los parámetros/rangos "no confirmados"** - Uroanálisis (ADR-015: proteína/creatinina en orina, índice, cristales, recuento bacteriano) y rangos de referencia (ADR-016: glicemia, úrea, creatinina, ácido úrico, bilirrubina total y directa, rango neonatal de glóbulos blancos) - hasta que Angelus confirme
- [ ] **Confirmar rangos de referencia contradictorios** - para el laboratorio Angelus: glicemia, urea, creatinina, ácido úrico, bilirrubinas, TGO/TGP
- [ ] **Confirmar "ÁCIDO ÚRICO: 3,4 - 70 mg/dL"** - para el laboratorio Angelus, ¿es error de tipeo por 7,0?
- [ ] **Confirmar rangos pediátricos/neonatales reales** - para el laboratorio Angelus
- [ ] **Confirmar rangos diferenciados por sexo** - para el laboratorio Angelus (los formatos actuales usan el mismo para ambos)
- [ ] **Confirmar valores críticos/de pánico** - para el laboratorio Angelus
- [ ] **Confirmar valor de ISI del lote de tromboplastina** - para el laboratorio Angelus (necesario para el INR)
- [ ] **Confirmar si es doble validación (técnico + bioanalista) o única** - para el laboratorio Angelus
- [ ] **Confirmar marca y modelo de los analizadores** - para el laboratorio Angelus
- [ ] **Confirmar precios de exámenes y perfiles** - para el laboratorio Angelus
- [ ] **Confirmar estado/municipio de localidades sin certeza** - Cantagallo, Dos Caminos, Las Minas, Píritu (`apps/masterdata/fixtures/localidades.json`)

## Someday

- [ ] **Invitación por correo y «olvidé mi clave»** - cuando haya envío de correos (Fase 17, ADR-029)

- [ ] **Enviar el informe por WhatsApp/correo** - hoy se copia el enlace de verificación (ADR-027)
- [ ] **Pantalla para que cada bioanalista suba su firma y sello** - hoy desde el admin

- [ ] **Worklist por sección/examen (operación interna)** - vista para ver todas las muestras pendientes de un tipo (ej. todas las hematologías de hoy) sin importar la orden/paciente, para procesarlas en lote; distinta del informe al paciente (que sigue por orden). El modelo ya está listo (`Test.section`, Fase 05): es un query nuevo, no un cambio de modelo. Encaja con la Fase 16 (gateway de instrumentos), anotado 2026-10-08
- [ ] **Privacidad antes de producción (Fase 17)** - sacar `docs/`, `TASKS.md` y `CLAUDE.md` de git (`git rm -r --cached` + `.gitignore`), repo privado, cambiar las menciones a Angelus en comentarios de `apps/catalog`; evaluar limpiar el historial
- [ ] **Automatizar creación del tenant `public` + dominio** - como parte del script de despliegue (Fase 17), ver ADR-009
- [ ] **Mecanismo Master*+copia al aprovisionar tenant** - pospuesto en Fase 05 (ADR-015), retomar cuando haya un segundo laboratorio real
- [ ] **Sembrar rangos de los nuevos calculados** (CHCM, globulinas, LDL, VLDL, Castelli, INR) - valores en 04_HALLAZGOS §1-2, cuando la Fase 10 los use
- [ ] **Tasa BCV automática y perfiles anidados** - posteriores, ADR-019
- [ ] **Pantalla propia para editar `Plan.features` (JSON)** - pospuesto en Fase 12, hoy se edita desde `/admin/`
- [ ] **MRR multimoneda** - `platform_metrics()` (Fase 12) suma `price_monthly` asumiendo USD; revisar si se agregan planes en otra moneda

## Done

- [x] ~~Fase 14 — Escritura offline y sincronización~~ (2026-10-14) — cola idempotente por `client_mutation_id`, cálculo clínico sólo en el servidor, resultado validado nunca sobrescrito, numeración por bloques por dispositivo, cliente con Dexie sin build, pantalla de *Sincronización* (ADR-033/034); 350 passed, ruff limpio, migraciones aplicadas y prueba offline completa en el navegador. Falta el commit.

- [x] ~~Fase 11e — Pacientes: ficha, antecedentes y evolución~~ (2026-09-28) — lista, ficha, representantes, antecedentes, evolución con gráfico SVG, tendencias, PDF (ADR-032); 298 passed; commit `518ba38`

- [x] ~~Fase 11d — Tablas auxiliares sin /admin~~ (2026-09-28) — secciones, unidades, métodos, listas de opciones, observaciones generales, tubos, lotes, monedas y descuentos con motor genérico en core (ADR-031); 287 passed y ruff limpio; commit `9640297`

- [x] ~~Fase 11c — Catálogo sin /admin~~ (2026-09-28) — exámenes, parámetros, rangos y críticos con probador, observaciones, perfiles, precios y tasa (ADR-030); 276 passed; commit `656ed95`

- [x] ~~Fase 11b — Panel del laboratorio~~ (2026-09-28) — datos del laboratorio, usuarios con clave temporal, varios roles, tabla de roles, mi perfil, rol Auxiliar de toma (ADR-029); 269 passed; commit `852c3f4`

- [x] ~~Muestras por tomar para el auxiliar~~ (2026-09-28) — impresas atenuadas y al final, imprimir desde la fila, se actualiza sola; 260 passed; commit `986b830`

- [x] ~~Fase 11 — Informe PDF, firma y QR~~ (2026-09-28) — versiones desde contenido congelado, parciales, huella, verificación por QR, firma y sello en cada página, firma de Biolife editable, recotizar, tomar tubo con resultados (ADR-027/028); 259 passed y ruff limpio en la máquina de Darwin; commit `212bb7a`
- [x] ~~Anular la orden 260927-0001 y desactivar el examen HC~~ (2026-09-28) — creado a mano sin parámetros ni precio

- [x] ~~Fase 10 — Captura y validación de resultados~~ (2026-09-27) — cálculo en vivo, marcas y críticos con aviso, validación que congela referencias, ISI por lote, observaciones por examen (ADR-025/026); verificado en la máquina de Darwin (246 passed, ruff limpio); commits `f934aaf` y `bac4352`
- [x] ~~Fase 09 — Órdenes y muestras~~ (2026-09-27) — número diario, tubos por aditivo, etiquetas PDF con Code 128, toma/rechazo/reemplazo, cotización congelada, pantallas de recepción (ADR-024); 211 passed y flujo completo verificados en la máquina de Darwin; commit `9919111`
- [x] ~~Verificar Fases 08c/08d~~ (2026-09-26) — 180 passed, ruff limpio, pantallas revisadas en demo1.localhost; commit `39a4491`
- [x] ~~Borrar tenants demo_dos y demo_tres~~ (2026-09-26) — comando `eliminar_laboratorio_demo` (ADR-023); queda demo_uno; carpeta `Claude outputs/` borrada; 183 passed y ruff limpio en la máquina de Darwin; commit `7ad6be1`
- [x] ~~Subir el repo a GitHub~~ (2026-09-26) — https://github.com/darwinjoelap/biolife, rama main
- [x] ~~Revisar el primer run del CI~~ (2026-09-26) — runs #1 y #2 en verde (~2,5 min)
- [x] ~~Fase 08c — Consolidación~~ (2026-09-26) — provisión con catálogo, lípidos sin AYUNO, CI, script de aislamiento reparado, avisos eliminados (ADR-021)
- [x] ~~Fase 08d — Estilo visual y pantallas base~~ (2026-09-26) — biolife.css, base/base_tenant/base_auth, acceso, Inicio, /estilo/, admin con marca, STORAGES (ADR-022); 180/180 en el entorno de Claude — verificado en la máquina de Darwin

- [x] ~~Commits de las Fases 06 a 08b~~ (2026-09-26) — Fase 06 `d3475eb`; Fases 07, 08 y 08b en `53655ab` (63 archivos)

- [x] ~~Fase 08b — Ficha del examen (rangos)~~ (2026-09-26) — edad en años/meses/días, avisos de solapes y huecos, probador, admin por tenant (bug de bitácora), 171/171 en el entorno de Claude — verificado en la máquina de Darwin (171/171, ruff limpio)
- [x] ~~Verificar Fase 08~~ (2026-09-26) — 149/149, ruff limpio, 15 perfiles, seed_billing OK

- [x] ~~Fase 08 — Perfiles y precios~~ (2026-09-26) — exámenes individuales desde los Excel, Profile/ProfileTest, 15 perfiles, apps.billing multimoneda con descuentos y quote(), Mosteller confirmado por la celda, 149/149 tests en el entorno de Claude — pendiente verificación en la máquina de Darwin
- [x] ~~Decidir si "Perfil lipídico" es Test o Profile~~ (2026-09-26) — Profile que agrupa exámenes (ADR-019)

- [x] ~~Fase 07 — Motor de fórmulas~~ (2026-09-26) — formula_engine.py (AST restringido, Decimal, orden topológico), set_parameter_formula() con ciclos al guardar y depends_on, sintaxis {CODIGO}/{@var} + migración catalog.0004, 16 fórmulas sembradas (seed_formulas, examen DEPURACION), superficie corporal Mosteller (ADR-017), 107/107 tests y ruff limpio en el entorno de Claude — verificado en la máquina de Darwin (107/107, ruff limpio)

- [x] ~~Fase 00 — Diseño (arquitectura, modelo de datos, convenciones, roadmap de 18 fases)~~ (2026-09-19)
- [x] ~~Fase 01 — Setup y multi-tenancy~~ (2026-09-19) — Django+django-tenants, apps core/tenants/masterdata, provision_tenant(), tenant público, aislamiento verificado, 9/9 tests, ruff limpio
- [x] ~~Fase 02 — Usuarios, roles y auditoría~~ (2026-09-20) — User propio (accounts.User), Role/Membership (6 roles), AuditLog append-only, login por tenant, provision_tenant() crea admin inicial, 18/18 tests, ruff limpio
- [x] ~~Fase 03 — Configuración del laboratorio~~ (2026-09-26) — TenantSettings singleton por tenant, provision_tenant() crea la config por defecto, middleware de zona horaria movido a settings_lab (con guarda para public), base_tenant.html + branding, MEDIA_ROOT/URL local (Cloudinary diferido a Fase 17), admin singleton, 24/24 tests, ruff limpio
- [x] ~~Commit de Fases 02+03 en git~~ (2026-09-26) — commit combinado `6d001d6` (47 archivos), ver mensaje del commit para el detalle de cada fase
- [x] ~~Fase 04 — Pacientes y representantes~~ (2026-09-26) — commit `03a4f10` — Patient/Guardian/PatientGuardian + PatientCodeSequence, internal_code con correlativo anual (select_for_update), lab_initials en TenantSettings, services create_patient()/guardian_linking, selector de búsqueda, admin con inline, migraciones en los 3 tenants, 33/33 tests, ruff limpio
- [x] ~~Fase 05 — Catálogo: secciones, unidades, parámetros~~ (2026-09-26) — commit `c9ac6ab` — apps.catalog (Section/Unit/Method/Test/ParameterGroup/Parameter/CodedOptionSet/CodedOption), catálogo sembrado directo por tenant (Master*+copia pospuesto, ADR-015), seed_uroanalisis() cubre los 9 value_type, CheckConstraint para option_set/formula, migraciones en los 3 tenants, 42/42 tests, ruff limpio
- [x] ~~Fase 06 — Rangos de referencia~~ (2026-09-26) — ReferenceRange + reference_resolver.py::resolve_reference_range() (sexo/edad-en-días/condición), 4 exámenes mínimos nuevos (HEM_COMP/PERFIL_LIPIDICO/COAGUL/QUIM) cubren los 6 range_type (ADR-016), CheckConstraint por range_type, migraciones en los 3 tenants, 56/56 tests, ruff limpio
