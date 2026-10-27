import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "web";

// El proyecto tiene un segundo servicio, `cron-bcv`, que trae la tasa del BCV a las
// 23:00 UTC (7 pm de Caracas). NO está declarado aquí y es deliberado, por dos razones:
//
//   1. IaC no sabe declarar horarios de cron. La referencia enumera servicios, bases,
//      volúmenes, buckets, dominios, variables, réplicas y grupos; `cronSchedule` no
//      existe. Declararlo aquí lo dejaría sin horario, es decir, muerto.
//   2. Un parcial con nombre sólo borra los recursos que él mismo declara, así que
//      `cron-bcv` queda intacto mientras no aparezca en este archivo.
//
// Está configurado a mano en la interfaz de Railway (Start Command, Cron Schedule y
// Restart Policy en `Never`); `railway.cron.json`, en la raíz del repositorio, conserva
// esos valores como documentación. Un servicio creado después del 2026-08-28 ya no puede
// acogerse a Config as Code, así que ese archivo no lo lee nadie.
//
// Si alguna vez se "ordena" este archivo agregándole `cron-bcv`, el parcial lo reclama y
// pasa a gestionarlo sin horario. No hacerlo.
export default defineRailway(() => {
  const web = service("web", {
    source: github("darwinjoelap/ordo-lab", { branch: "main", checkSuites: false }),
    build: { buildCommand: "pip install -r requirements/production.txt && python manage.py collectstatic --noinput", buildEnvironment: "V3", builder: "NIXPACKS" },
    start: "gunicorn config.wsgi --log-file - --workers 3 --timeout 60",
    preDeploy: "python manage.py migrate_schemas --noinput",
    replicas: { "us-west2": 1 },
    // `*.biolifeve.com` se retiró el 2026-10-27 (ADR-037). Dejarlo aquí haría que el
    // cutover a IaC lo volviera a crear, y gastaría uno de los dos cupos del plan Hobby.
    domains: ["*.lab.ordove.com"],
  });

  return project("Ordo-Lab", {
    variables: { managed: false },
    resources: [web],
  });
});
