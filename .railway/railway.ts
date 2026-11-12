import { bucket, defineRailway, github, postgres, project, service, volume } from "railway/iac";

// Infraestructura de Ordo-Lab (ADR-048). Reemplaza a `railway.json`, que Railway deja de
// leer el 2026-12-01.
//
// Partió de `railway config migrate`, con dos correcciones a mano en `cron-bcv` (abajo).
// Revisar siempre con `railway config plan` antes de `apply`: esto toca infraestructura
// viva.
//
// **Entorno completo, sin `partial`.** Este repositorio es dueño de todo el proyecto, así
// que el archivo describe el estado deseado entero: un recurso que falte aquí se propone
// para BORRAR en el próximo `apply`. Por eso están Postgres, su volumen, el bucket del
// PITR y el volumen restaurado, aunque ninguno se configure desde aquí.
export default defineRailway(() => {
  const ordoLab = github("darwinjoelap/ordo-lab", { branch: "main", checkSuites: false });

  const Postgres = postgres("Postgres", { region: "us-west2" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 5000 });
  // Resto de la restauración de prueba del PITR (2026-10-29), desconectado. Se declara
  // para que la migración no cambie nada; borrarlo es una decisión aparte y deliberada:
  // quitar esta línea y el `apply` lo propondrá para borrar.
  const postgresRestored = volume("postgres-restored", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 50000 });
  const PostgresPITR = bucket("Postgres-PITR", { region: "sjc" });

  const web = service("web", {
    source: ordoLab,
    build: { buildCommand: "pip install -r requirements/production.txt && python manage.py collectstatic --noinput", buildEnvironment: "V3", builder: "NIXPACKS" },
    start: "gunicorn config.wsgi --log-file - --workers 3 --timeout 60",
    // Sólo web migra. Si dos servicios corren migraciones en el mismo despliegue, compiten
    // por los mismos esquemas.
    preDeploy: "python manage.py migrate_schemas --noinput",
    replicas: { "us-west2": 1 },
    domains: ["*.lab.ordove.com"],
  });

  // Trae la tasa oficial del BCV a las 23:00 UTC (7 pm de Caracas).
  //
  // `railway config migrate` le generó `start: gunicorn …` y `preDeploy: migrate_schemas`:
  // los valores de `railway.json`, que es el archivo de web. Aplicado así, el cron habría
  // arrancado un servidor que no termina nunca; como Railway salta una ejecución si la
  // anterior sigue viva, la tasa habría dejado de actualizarse para siempre, sin un solo
  // error. Corregido a mano: el comando del cron y sin `preDeploy`.
  const cronBcv = service("cron-bcv", {
    source: ordoLab,
    build: { buildCommand: "pip install -r requirements/production.txt && python manage.py collectstatic --noinput", buildEnvironment: "V3", builder: "NIXPACKS" },
    start: "python manage.py actualizar_tasa_bcv",
    replicas: { "us-west2": 1 },
    deploy: { cronSchedule: "0 23 * * *", restartPolicyType: "NEVER" },
  });

  return project("Ordo-Lab", {
    // Ninguna variable vive en este archivo: SECRET_KEY, DATABASE_URL y las de R2 son
    // secretos. `managed: true` haría a este archivo dueño de todas, y el primer `apply`
    // borraría las que no estuvieran escritas aquí, es decir todas.
    variables: { managed: false },
    resources: [web, cronBcv, Postgres, postgresVolume, postgresRestored, PostgresPITR],
  });
});
