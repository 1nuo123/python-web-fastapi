# Development observability stack

This directory contains a local-only Prometheus, Alertmanager, and Grafana stack. It is intentionally separate from production deployment and binds only to loopback ports:

- Prometheus: `http://127.0.0.1:19090`
- Alertmanager: `http://127.0.0.1:19093`
- Grafana: `http://127.0.0.1:13000`

The Prometheus target is the fresh development app on `host.docker.internal:18005` used by the current end-to-end Compose run. Start it with:

```powershell
docker compose --project-name codex-observability-development -f deploy/observability/compose.development.yml up -d --pull always
```

The smoke rule in `prometheus/rules/codex-development-smoke.yml` is development-only. Its checked-in recovery state is `vector(0) == 1`; temporarily change it to `vector(1)` and POST `http://127.0.0.1:19090/-/reload` to verify firing, then restore `vector(0) == 1` and reload again to verify recovery. Do not mount this rule into production. The dashboard is provisioned read-only and uses only Prometheus; no application database or log storage is exposed to Grafana. `grafana.ini` disables update checks, plugin preinstall, and signature-key retrieval so this local stack does not require outbound Grafana access.
