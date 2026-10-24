import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "web";
export default defineRailway(() => {
  const web = service("web", {
    source: github("darwinjoelap/ordo-lab", { branch: "main", checkSuites: false }),
    build: { buildCommand: "pip install -r requirements/production.txt && python manage.py collectstatic --noinput", buildEnvironment: "V3", builder: "NIXPACKS" },
    start: "gunicorn config.wsgi --log-file - --workers 3 --timeout 60",
    preDeploy: "python manage.py migrate_schemas --noinput",
    replicas: { "us-west2": 1 },
    domains: ["*.biolifeve.com", "*.lab.ordove.com"],
  });

  return project("Ordo-Lab", {
    variables: { managed: false },
    resources: [web],
  });
});
