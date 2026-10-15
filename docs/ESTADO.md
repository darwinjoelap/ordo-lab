# ESTADO DEL PROYECTO — Biolife

> Se actualiza al **cerrar cada sesión**. Es el primer archivo que se lee al abrir la siguiente.
> Mantener bajo 100 líneas: el detalle de cada fase vive en su `docs/roadmap/NN_*.md`, el de
> las cerradas en `HISTORIAL.md`, y las decisiones en `DECISIONES.md`.

**Última actualización:** 2026-10-14
**Fase actual:** ninguna en ejecución. La **14 quedó cerrada** (2026-10-14, ADR-033/034);
la 12 y la 13 siguen abiertas sólo por su prueba manual en navegador. La siguiente fase
la decide Darwin (el roadmap sugiere 15 — rectificaciones, o 17 — despliegue).
**Repositorio:** https://github.com/darwinjoelap/biolife (rama `main`, CI en GitHub Actions)
**Responsable:** Darwin

---

## Completado

- [x] Fases 00–11e (hasta `518ba38`, 2026-09-28): base multi-tenant, catálogo, rangos,
  fórmulas, precios, órdenes y tubos, resultados, informe PDF con QR, panel del
  laboratorio, catálogo y tablas auxiliares sin /admin, ficha del paciente con
  antecedentes y evolución (ADR-001–032). Verificado: 298 passed. Detalle en
  `docs/HISTORIAL.md`.
- [x] **Fase 14 — Escritura offline y sincronización** (2026-10-14, ADR-033/034): cola
  idempotente por `client_mutation_id`, cálculo clínico **sólo en el servidor**, un
  resultado validado nunca se sobrescribe, numeración por bloques reservados por
  dispositivo, cliente con Dexie sin build y pantalla de *Sincronización*. Verificado por
  Darwin: 350 passed, ruff limpio, migraciones aplicadas y prueba sin conexión completa
  en el navegador. **Sin commit todavía** (ver abajo). Queda aparte el *tramo D*: crear
  órdenes y pacientes offline desde el navegador.

## En curso — dos fases abiertas, sólo por su prueba manual

Ambas tienen el código verificado con `pytest` y `ruff`. No se cierran hasta esa prueba.

- **Fase 13** (`docs/roadmap/13_pwa_offline.md`) — PWA instalable y lectura offline de
  Órdenes y Pacientes. Falta probar instalación y modo offline en un navegador.
- **Fase 12** (`docs/roadmap/12_superadmin.md`) — panel SaaS en `/panel/` del esquema
  `public` (laboratorios, planes, suscripciones, métricas, suspensión con efecto real).
  Falta el recorrido manual del panel y borrar el laboratorio DEMO de prueba.

## Pendiente inmediato

1. **Commit de las Fases 12, 13 y 14** — el repo no tiene nada commiteado desde
   `518ba38` (2026-09-28): tres fases de trabajo sin versionar. Conviene hacerlo ya,
   aunque la 12 y la 13 queden pendientes de su prueba manual.
2. Probar la Fase 13 (instalar la app, cortar la conexión, confirmar que Órdenes y
   Pacientes ya visitados abren igual) y la Fase 12 (`/panel/`).
3. Revisión manual pendiente de las Fases 11 a 11e — checklist completo en el roadmap de
   cada una y en `TASKS.md`.
4. Cargar precios reales en la lista GENERAL (*Precios*): sin ellos las órdenes quedan
   con monto pendiente.
5. **No usar en un informe real** ningún `ReferenceRange`/parámetro marcado "PENDIENTE DE
   CONFIRMAR" o "NO CONFIRMADO" (ADR-015/016), ni el INR sin confirmar el ISI
   (ADR-017/019), hasta que el laboratorio responda.

## Bloqueos

Ninguno técnico. Las preguntas abiertas al laboratorio (abajo) siguen sin responder, pero
ya no bloquean avanzar de fase — el motor y la siembra de ejemplo se construyeron con
valores marcados como pendientes en vez de esperar la confirmación.

## Preguntas abiertas al laboratorio

> Angelus es laboratorio de **referencia**, no el alcance del producto (ADR-018). Estas
> respuestas alimentan sus datos de tenant; no bloquean decisiones de producto.

- [ ] Rangos de referencia correctos donde los formatos se contradicen:
      glicemia, urea, creatinina, ácido úrico, bilirrubinas, TGO/TGP
- [ ] "ÁCIDO ÚRICO: 3,4 - 70 mg/dL" — ¿es error de tipeo por 7,0?
- [ ] Rangos pediátricos y neonatales reales
- [ ] Rangos diferenciados por sexo (los formatos usan el mismo para ambos)
- [ ] Valores críticos / de pánico (umbrales por parámetro)
- [ ] Valor de ISI del lote de tromboplastina (necesario para el INR)
- [ ] INR: su hoja calcula con ISI vacío e imprime siempre 1 (ADR-019)
- [ ] LDH: 90–510 IU/L en unas hojas, por sexo (H 80–285 / M 103–227) en otras
- [ ] Insulina: unidad "U/mL" (¿µU/mL?) y rango post-carga "40 – 230"
- [ ] ¿La composición de perfiles sembrada coincide con lo que venden? (ADR-019)
- [ ] ¿Doble validación (técnico + bioanalista) o validación única?
- [ ] Marca y modelo de los analizadores del laboratorio
- [ ] Precios de exámenes y perfiles
- [ ] Estado/municipio de Cantagallo, Dos Caminos, Las Minas y Píritu (ver HISTORIAL)

## Notas

- **Antes de producción (Fase 17):** sacar `docs/`, `TASKS.md` y `CLAUDE.md` de git y
  poner el repo privado (datos del laboratorio de referencia). Decidido 2026-09-27.
- Los formatos originales están en el proyecto de Cowork. No re-analizarlos: el resumen
  completo está en `docs/04_HALLAZGOS_FORMATOS.md`.
- ADRs clave: 007–011 (esquemas, `User` propio), 017–020 (fórmulas, alcance, precios,
  rangos), 021–024 (provisión, visual, órdenes), 025–028 (resultados, informe, QR),
  029–031 (panel, catálogo y tablas sin /admin), 032 (paciente y evolución).
- "7 roles" del índice del roadmap = 6 roles de tenant + `SUPERADMIN_PLATAFORMA` como
  `PlatformUser` en `public` — **corregido en Fase 12**: no se creó `PlatformUser`; el
  panel reusa `accounts.User` de `public` con `is_superuser=True`.
- Idea anotada 2026-10-08: *worklist* por sección/examen para la operación interna (ver
  `TASKS.md` → Someday y el roadmap de la Fase 12).
- **Postgres local (Darwin):** la base `biolife` está en la instancia **16**, puerto
  **5434** (hay también 17 y 18). Si `manage.py` falla al conectar, revisar el servicio
  `postgresql-x64-16` y que `.env` apunte a `localhost:5434`.
