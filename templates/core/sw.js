{% load static %}const CACHE_VERSION = "ordolab-v1";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const PAGES_CACHE = `${CACHE_VERSION}-pages`;

/* Fase 13 (PWA base y modo lectura offline): el service worker guarda el "esqueleto"
   de la app al instalarse y, al visitarlas, las páginas de Órdenes y Pacientes (lista
   y detalle) para poder abrirlas sin conexión. Nunca intercepta un método distinto de
   GET: la escritura offline no pasa por aquí, la encola `static/js/sync.js` (Fase 14) y
   se envía cuando vuelve la conexión. */

const SHELL_URLS = [
  "{% static 'css/ordolab.css' %}",
  "{% static 'vendor/htmx-2.0.11.min.js' %}",
  "{% static 'vendor/alpine-3.17.4.min.js' %}",
  // Fase 14: sin estos dos en el caché, una página abierta sin conexión no podría
  // encolar nada — que es justo lo que hace falta cuando no hay conexión.
  "{% static 'vendor/dexie-4.0.11.min.js' %}",
  "{% static 'js/sync.js' %}",
  "{% static 'fonts/inter-latin-wght-normal.woff2' %}",
  "{% static 'img/brand/ordolab-mark-96.png' %}",
  "{% static 'img/brand/favicon-32.png' %}",
  "{% url 'core:offline' %}",
];

// Rutas de sólo consulta: se guardan al visitarlas la primera vez.
const CACHEABLE_PATH_PREFIXES = ["/ordenes/", "/pacientes/"];
// Dentro de esas rutas, lo que es acción o búsqueda (no ficha) nunca se cachea.
const EXCLUDED_PATH_PARTS = [
  "/nueva/", "/nuevo/", "/buscar/", "/tomar/", "/rechazar/", "/pagar/",
  "/recotizar/", "/anular/", "/agregar/", "/editar/", "/representantes/",
  "/antecedentes/", "/evolucion/pdf", "resumen-del-dia", "por-tomar/tabla",
  "etiquetas.pdf",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          // Cualquier caché que no sea la versión actual, no sólo las del prefijo de
          // turno: así el renombrado de Biolife a Ordo Lab no deja cachés huérfanas en
          // los navegadores que ya tenían la aplicación instalada.
          .filter((name) => !name.startsWith(CACHE_VERSION))
          .map((name) => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

function isCacheableNavigation(url) {
  if (url.search) return false; // nunca cachea con querystring (búsquedas, filtros)
  const path = url.pathname;
  if (!CACHEABLE_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))) return false;
  if (EXCLUDED_PATH_PARTS.some((part) => path.includes(part))) return false;
  return true;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // nunca intercepta escrituras

  const url = new URL(request.url);

  if (request.mode === "navigate" || request.destination === "document") {
    if (!isCacheableNavigation(url)) return; // login, acciones, etc.: tal cual, sin SW
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(PAGES_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(request).then((cached) => cached || caches.match("{% url 'core:offline' %}"))
        )
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});
