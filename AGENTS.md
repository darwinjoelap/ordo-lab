# AGENTS.md — Ordo Lab

## Proyecto y alcance

Ordo Lab es un SaaS independiente para laboratorios clínicos. Usa Python 3.13, Django 5.1, django-tenants y PostgreSQL 16 con un esquema por laboratorio. La interfaz usa Django Templates, HTMX y Alpine. Mantén el español de la interfaz y las convenciones de fecha, hora y zona horaria del proyecto.

Ordo Salud, Ordo y BioLifeLab son proyectos separados. No presupongas equivalencia funcional, linaje ni compatibilidad. Solicita autorización antes de inspeccionar esos repositorios, ejecutar su código o incorporar su arquitectura o componentes.

Al comenzar, confirma la raíz, la rama y el estado de Git. Usa el código y la configuración versionados para comprobar el comportamiento. La documentación local ignorada, cuando exista, sirve como contexto adicional. Edita archivos directamente solo dentro de una tarea autorizada. Conserva los cambios preexistentes del usuario, incluidos los no rastreados, y limita el diff al alcance aprobado.

## Esquemas, permisos y privacidad

- Determina el esquema antes de cada operación. Usa `public` para plataforma y datos maestros compartidos. Usa el esquema del laboratorio para pacientes, órdenes, muestras, resultados, informes y configuración clínica. Las cuentas de plataforma y las del laboratorio pertenecen a sus respectivos contextos.
- En peticiones, respeta la resolución de tenant por dominio. En tareas, comandos y operaciones entre esquemas, selecciona el contexto explícitamente con las utilidades de django-tenants y restáuralo al salir. Un ID, un nombre de esquema recibido del cliente o el acceso a la plataforma no otorgan acceso clínico.
- Comprueba sesión, rol, tenant y pertenencia del objeto en servidor antes de mostrar o modificar datos. Aplica el mismo control a HTML, HTMX, JSON, archivos y tareas. Una acción oculta en el menú no sustituye la autorización.
- Protege documentos y objetos R2 con almacenamiento privado y enlaces firmados según el flujo existente. Para QR, conserva el acceso por código y verifica vigencia y expiración en servidor antes de descargar. Limita los metadatos públicos y evita incluir datos clínicos o credenciales de acceso en URLs, logs o mensajes.
- Trata el HTML offline y la cola Dexie como datos clínicos. Todo cambio en PWA o sincronización debe separar los datos por tenant y usuario, contemplar su purga o bloqueo al cerrar sesión o cambiar de cuenta y evitar que otra cuenta lea o reenvíe la cola. Valida permisos y versiones de las mutaciones en servidor y conserva la idempotencia.
- Usa datos sintéticos en pruebas, ejemplos y diagnósticos. No leas ni imprimas secretos de `.env`, Railway o R2, ni copies credenciales, enlaces de acceso, documentos o información de pacientes a código, diffs, logs o respuestas.

## Código e integridad clínica

- Usa los servicios existentes para operaciones clínicas y los selectors para consultas. Mantén las vistas como orquestadoras y conserva las convenciones de las aplicaciones. Respeta transacciones, restricciones, autoría, auditoría y transiciones de estado. Evita el borrado físico de registros clínicos.
- Prohíbe la edición directa de resultados validados e informes emitidos, también mediante admin, ORM o scripts. Corrige por el flujo de rectificación con motivo, autoría, registro de auditoría, instantánea previa y revalidación. Emite una nueva versión del informe y conserva las anteriores, incluidos los activos necesarios para reproducirlas.
- Exige autorización explícita y validación clínica de la persona responsable antes de cambiar rangos de referencia, unidades, fórmulas, ISI, valores críticos o criterios de validación. Conserva las referencias congeladas y los controles de notificación de críticos y segunda validación aplicables al laboratorio.
- En cambios de esquema, revisa si la migración corresponde a `public` o al tenant, su efecto sobre datos existentes, el orden de aplicación, la compatibilidad durante el despliegue y la recuperación ante fallos. Identifica las migraciones de datos y operaciones irreversibles antes de ejecutarlas.

## Pruebas, Git y producción

- Antes de ejecutar pruebas, verifica que el intérprete corresponde a `.venv`, que usa Python 3.13 y que la configuración apunta a un PostgreSQL local aislado con datos sintéticos. Comprueba el destino sin revelar credenciales. Si no puedes confirmarlo, detente antes de ejecutar.
- No ejecutes pruebas que escriban datos o creen bases o esquemas, incluidas las que usan `TenantTestCase`, sin autorización. Según el alcance, usa Ruff y las pruebas pertinentes de permisos, aislamiento, reintentos, validación o informes. No ejecutes migraciones como parte de una revisión de solo lectura.
- Trata `main` como rama de producción y `.railway/railway.ts` como infraestructura crítica. Railway declara `main` como fuente de despliegue. Cambios en infraestructura, operaciones Railway con efectos, despliegues, migraciones productivas y cualquier push requieren autorización explícita. Revisa el plan de infraestructura y el impacto sobre servicios, volúmenes y esquemas antes de una aplicación autorizada.
- No hagas commits, merges, cambios de rama ni operaciones que descarten o reescriban cambios del usuario sin autorización. Al terminar, revisa el diff y el estado de Git, comprueba también los archivos nuevos sin seguimiento e informa qué cambió, qué verificaste, con qué resultado y qué queda pendiente.

## Riesgos abiertos

- **Esquemas huérfanos.** El alta puede reutilizar el nombre de un esquema PostgreSQL que ya no tiene fila en `Tenant`. Verifica este riesgo al tocar aprovisionamiento o baja. Mantén la protección frente al borrado accidental de esquemas clínicos.
- **Navegadores compartidos.** La PWA puede conservar páginas clínicas y la cola Dexie puede persistir entre sesiones. No des por resueltos el aislamiento por usuario, la purga al salir ni el manejo seguro de acciones pendientes.
- **Configuración clínica pendiente.** Hay valores de rangos, críticos, fórmulas e ISI que requieren confirmación del laboratorio. No uses configuraciones pendientes de confirmar en informes reales. Algunas comprobaciones, como la suma leucocitaria, actualmente advierten sin bloquear.
