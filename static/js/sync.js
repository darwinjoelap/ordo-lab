/* Escritura offline (Fase 14, tramo B).
 *
 * Qué hace: cuando no hay conexión, intercepta los formularios marcados con
 * `data-offline` y guarda la acción en una cola en IndexedDB (Dexie). Al volver la
 * conexión la manda al servidor, que es el único que calcula, marca y decide conflictos.
 *
 * Idempotencia: cada entrada lleva un `client_mutation_id` (UUID v4) que viaja en cada
 * reintento. El servidor es idempotente por ese id, así que reenviar nunca duplica.
 *
 * La cola local sólo guarda lo que **todavía no llegó** al servidor. En cuanto el
 * servidor responde (aplicada, en conflicto o con error), la entrada se borra de aquí:
 * desde ese momento la verdad vive en el servidor y se consulta en la pantalla de
 * Sincronización. Así no hay dos listas que puedan contradecirse.
 *
 * Sin build: Dexie se carga como estático *vendor*, igual que htmx y Alpine.
 */
(function () {
  "use strict";

  var node = document.getElementById("bl-sync");
  if (!node || typeof Dexie === "undefined") return;
  var cfg = node.dataset;
  var TTL_MS = 24 * 60 * 60 * 1000; // 24 h (00_ARQUITECTURA §5)
  var RETRY_MS = 60000;

  var db = new Dexie("ordolab-sync");
  db.version(1).stores({
    queue: "client_mutation_id, kind, client_created_at",
    meta: "key",
  });

  // ---------------------------------------------------------------- utilidades
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function deviceId() {
    var key = "bl-device-id";
    var id = null;
    try {
      id = localStorage.getItem(key);
      if (!id) {
        id = uuid();
        localStorage.setItem(key, id);
      }
    } catch (e) {
      id = id || uuid(); // modo privado: id efímero, la cola sigue funcionando
    }
    return id;
  }

  function csrf() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input) return input.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }

  async function setMeta(key, value) {
    try {
      await db.meta.put({ key: key, value: value });
    } catch (e) {
      /* la cola es best-effort: nunca romper la pantalla por el almacenamiento */
    }
  }

  async function getMeta(key) {
    try {
      var row = await db.meta.get(key);
      return row ? row.value : null;
    } catch (e) {
      return null;
    }
  }

  // --------------------------------------------------------------------- cola
  async function enqueue(kind, payload) {
    var entry = {
      client_mutation_id: uuid(),
      kind: kind,
      payload: payload,
      client_created_at: new Date().toISOString(),
    };
    await db.queue.add(entry);
    await refreshBadges();
    return entry;
  }

  async function pendingCount() {
    try {
      return await db.queue.count();
    } catch (e) {
      return 0;
    }
  }

  var flushing = false;

  async function flush() {
    if (flushing || !navigator.onLine) return;
    var batch = await db.queue.orderBy("client_created_at").limit(100).toArray();
    if (!batch.length) {
      await markOnline();
      return;
    }
    flushing = true;
    try {
      var response = await fetch(cfg.mutationsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        credentials: "same-origin",
        body: JSON.stringify({ device_id: deviceId(), mutations: batch }),
      });
      if (!response.ok) return; // 4xx/5xx: se reintenta más tarde, nada se pierde
      var data = await response.json();
      // Todo lo que el servidor acusó sale de la cola local: aplicado, en conflicto o
      // con error, ya quedó registrado allá y se revisa en la pantalla.
      var acked = (data.results || []).map(function (r) {
        return r.client_mutation_id;
      });
      if (acked.length) await db.queue.bulkDelete(acked);
      await markOnline();
      announce(data.results || []);
    } catch (e) {
      /* sin red: se reintenta */
    } finally {
      flushing = false;
      await refreshBadges();
    }
  }

  async function markOnline() {
    await setMeta("last_online_at", Date.now());
  }

  async function isStale() {
    var last = await getMeta("last_online_at");
    return last !== null && Date.now() - last > TTL_MS;
  }

  function announce(results) {
    var problems = results.filter(function (r) {
      return r.status === "CONFLICTO" || r.status === "ERROR";
    });
    if (!problems.length) return;
    toast(
      problems.length +
        " de los cambios guardados sin conexión necesitan revisión. Abra Sincronización.",
      "warn"
    );
  }

  // ------------------------------------------------------------------ interfaz
  function toast(message, level) {
    var box = document.getElementById("bl-sync-toast");
    if (!box) return;
    box.textContent = message;
    box.className = "alert alert--" + (level === "warn" ? "warn" : "ok");
    box.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () {
      box.hidden = true;
    }, 8000);
  }

  async function refreshBadges() {
    var count = await pendingCount();
    document.querySelectorAll("[data-sync-count]").forEach(function (el) {
      el.textContent = count ? String(count) : "";
      el.hidden = !count;
    });
    document.body.classList.toggle("has-queue", count > 0);
  }

  async function refreshServerBadge() {
    if (!navigator.onLine || !cfg.statusUrl) return;
    try {
      var response = await fetch(cfg.statusUrl, { credentials: "same-origin" });
      if (!response.ok) return;
      var data = await response.json();
      var needs = (data.conflictos || 0) + (data.errores || 0);
      document.querySelectorAll("[data-sync-review]").forEach(function (el) {
        el.textContent = needs ? String(needs) : "";
        el.hidden = !needs;
      });
    } catch (e) {
      /* da igual: es sólo el contador */
    }
  }

  // ------------------------------------------------------- captura de formularios
  // Cada formulario habilitado declara su tipo de mutación en `data-offline`, y de ahí
  // se saca el payload. Sin conexión no se calcula nada en el dispositivo: se guarda lo
  // escrito tal cual y el servidor resuelve al sincronizar.
  var BUILDERS = {
    MUESTRA_TOMADA: function (form, data) {
      var ids = (form.dataset.offlineSamples || "").split(",").filter(Boolean);
      var one = data.get("muestra");
      return (one ? [String(one)] : ids).map(function (id) {
        return { sample_id: id };
      });
    },
    MUESTRA_RECHAZADA: function (form, data) {
      if (!(data.get("reason") || "").trim()) return null; // el motivo es obligatorio
      return [{ sample_id: form.dataset.offlineSample, reason: data.get("reason") }];
    },
    RESULTADO_CAPTURADO: function (form, data) {
      var entries = {};
      var notes = {};
      data.forEach(function (value, key) {
        if (key.indexOf("v_") === 0) {
          var id = key.slice(2);
          // Un parámetro de selección múltiple manda varios valores con la misma clave.
          if (entries[id] === undefined) entries[id] = value;
          else if (Array.isArray(entries[id])) entries[id].push(value);
          else entries[id] = [entries[id], value];
        } else if (key.indexOf("obs_") === 0) {
          notes[key.slice(4)] = Object.assign(notes[key.slice(4)] || {}, {
            observations: value,
          });
        } else if (key.indexOf("nota_") === 0) {
          notes[key.slice(5)] = Object.assign(notes[key.slice(5)] || {}, {
            internal_note: value,
          });
        }
      });
      var versions = {};
      try {
        versions = JSON.parse(form.dataset.offlineVersions || "{}");
      } catch (e) {
        versions = {};
      }
      return [
        {
          order_id: form.dataset.offlineOrder,
          entries: entries,
          notes: notes,
          sync_versions: versions,
        },
      ];
    },
  };

  async function onSubmit(event) {
    var form = event.target;
    if (!form || !form.dataset || !form.dataset.offline) return;
    if (navigator.onLine) return; // con conexión, el flujo normal de siempre

    var kind = form.dataset.offline;
    var build = BUILDERS[kind];
    if (!build) return;

    event.preventDefault();
    event.stopPropagation();

    if (await isStale()) {
      toast(
        "Han pasado más de 24 horas sin conexión: vuelva a conectarse antes de seguir " +
          "capturando (el catálogo y los precios podrían estar vencidos).",
        "warn"
      );
      return;
    }

    var payloads = build(form, new FormData(form));
    if (!payloads || !payloads.length) {
      toast("Falta un dato obligatorio para guardar sin conexión.", "warn");
      return;
    }
    for (var i = 0; i < payloads.length; i++) await enqueue(kind, payloads[i]);
    form.querySelectorAll("button, input[type=submit]").forEach(function (b) {
      b.disabled = true;
    });
    toast(
      payloads.length === 1
        ? "Guardado en este dispositivo. Se enviará al volver la conexión."
        : payloads.length + " cambios guardados en este dispositivo. Se enviarán al " +
          "volver la conexión.",
      "ok"
    );
  }

  // Validar, cobrar y emitir informes no funcionan sin conexión (requieren estado del
  // servidor): se deshabilitan en vez de dejar que fallen a medias.
  function toggleOnlineOnly() {
    var offline = !navigator.onLine;
    document.querySelectorAll("[data-online-only]").forEach(function (el) {
      el.disabled = offline;
      el.title = offline ? "Necesita conexión" : el.dataset.titleOnline || "";
    });
  }

  // ------------------------------------------------------------------- arranque
  document.addEventListener("submit", onSubmit, true);
  window.addEventListener("online", function () {
    toggleOnlineOnly();
    flush();
    refreshServerBadge();
  });
  window.addEventListener("offline", toggleOnlineOnly);

  toggleOnlineOnly();
  refreshBadges();
  refreshServerBadge();
  flush();
  setInterval(function () {
    pendingCount().then(function (n) {
      if (n) flush();
    });
  }, RETRY_MS);

  // Para la consola y para la pantalla de Sincronización.
  window.ordoLabSync = { enqueue: enqueue, flush: flush, pending: pendingCount };
})();
