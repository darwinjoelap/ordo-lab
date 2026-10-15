# Fase 13 — PWA base y modo lectura offline

**Estado:** en curso (iniciada 2026-10-14).

**Depende de:** 01 · **Criterio de salida:** la app es instalable como PWA y las
páginas de Órdenes y Pacientes que ya se visitaron se pueden volver a abrir sin
conexión (sólo lectura).

## Decisiones (Darwin, 2026-10-14)

- **Alcance offline:** Órdenes + Pacientes (lista y detalle) — más amplio que sólo
  Órdenes. Nunca se cachean rutas de acción/búsqueda ni nada con querystring.
- **Botón de instalar:** no es un botón suelto y visible — vive dentro del popover
  que sale al presionar el avatar del usuario (poco visible en primera vista), y sólo
  aparece si el navegador disparó `beforeinstallprompt`.

## Qué se hizo

- [x] `templates/core/sw.js`: service worker servido como "template" Django (no como
  estático) para que `{% static %}` resuelva los nombres con hash de WhiteNoise — así
  el script cambia de bytes solo cuando cambia un asset precacheado, sin tocar
  `CACHE_VERSION` a mano salvo que cambie la lógica del propio `sw.js`.
  - Cachea en la instalación el "esqueleto" (CSS, htmx, Alpine, fuente, iconos, la
    página `/offline/`).
  - Sólo intercepta `GET`. Para navegaciones, sólo cachea rutas bajo `/ordenes/` o
    `/pacientes/` que no sean acción/búsqueda (lista de exclusión explícita:
    `/nueva/`, `/nuevo/`, `/buscar/`, `/tomar/`, `/rechazar/`, `/pagar/`,
    `/recotizar/`, `/anular/`, `/agregar/`, `/editar/`, `/representantes/`,
    `/antecedentes/`, PDFs, `resumen-del-dia`, `por-tomar/tabla`) y sin querystring —
    red primero, con la copia en caché como respaldo, y `/offline/` si no hay nada
    guardado. Estáticos: caché primero.
- [x] `templates/core/manifest.webmanifest`: `name` incluye el laboratorio
  (`{{ request.tenant.name }}`), `display: standalone`, reutiliza los íconos
  `icon-192.png`/`icon-512.png` que ya existían en `static/img/brand/`.
- [x] `templates/core/offline.html`: respaldo del service worker. Extiende
  `base.html` directamente (no `base_tenant.html`) para no depender de nada que no
  esté en el caché del "esqueleto".
- [x] `apps.core.views`: `service_worker`, `manifest`, `offline` — ninguna detrás de
  `@login_required` a propósito: el navegador los pide fuera de una sesión "normal"
  (instalación del SW, lectura del manifest) y cachear una redirección al login en
  vez del recurso real rompería todo.
- [x] `apps.core.urls`: `sw.js`, `manifest.webmanifest`, `offline/` — montadas en la
  raíz (vía `config/urls_tenant.py`, que ya incluye `apps.core.urls` sin prefijo) para
  que el alcance por defecto del service worker cubra todo el dominio del
  laboratorio.
- [x] `templates/base_tenant.html`: enlaza el manifest y registra el service worker
  (bloque `extra_head`) — sólo aquí, no en `base_platform.html` (panel SuperAdmin,
  Fase 12) ni en `base_auth.html` (login); aviso fijo de "Sin conexión" cuando
  `navigator.onLine` es falso; el popover del avatar (antes sólo tenía "Cerrar
  sesión") ahora agrupa Mi perfil, Instalar app (gated por `beforeinstallprompt`) y
  Cerrar sesión.
- [x] CSS nuevo en `static/css/biolife.css`: `.avatar--btn`, `.popover`/`.popover__item`
  (mismo lenguaje visual que `.card`/`.btn` existentes), `.offline-banner`.
- [x] Tests (`apps/core/tests/test_pwa.py`, vía `TenantClient` sin login): las tres
  rutas responden sin sesión con el `Content-Type` correcto; el `sw.js` generado
  contiene las rutas cacheables y al menos una exclusión.

## Limitaciones conocidas / no incluye

- Sólo lectura: no hay cola de escritura offline (tomar muestra, cargar resultado,
  etc. sin conexión) — eso sería una fase aparte si se llega a necesitar.
- El service worker no se probó en un navegador real todavía (instalación, Lighthouse,
  comportamiento al cortar la conexión en DevTools) — pendiente abajo.
- `start_url`/`scope` del manifest son `/` fijo: no se contempló por ahora un caso de
  laboratorio con subruta propia.
- No se agregó un banner de "nueva versión disponible" cuando el service worker se
  actualiza — hoy sólo se activa (`skipWaiting`/`clients.claim`) sin avisar al usuario.

## Verificación pendiente en la máquina de Darwin

- [x] ~~`pytest -q` y `ruff check .`~~ (2026-10-14) — 315 passed, ruff limpio
- [ ] En el navegador: abrir el laboratorio, confirmar que aparece el manifest/ícono y
  que Chrome ofrece instalar (o que el botón "Instalar app" aparece en el popover del
  avatar al hacerlo).
- [ ] Visitar una orden y un paciente, cortar la conexión (DevTools → Network →
  Offline) y confirmar que se pueden volver a abrir; confirmar que una página no
  visitada antes cae en `/offline/`.
- [ ] Confirmar que el login y el panel `/panel/` (Fase 12) siguen sin el banner ni el
  registro del service worker (no deberían tenerlo).
