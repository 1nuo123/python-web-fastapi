# Caddy Docker Gateway

This gateway is the only public container in production. FastAPI, Nuxt,
PostgreSQL, Redis, and RabbitMQ remain on Docker networks without published
ports.

The trusted edge boundary is fixed to `172.30.0.0/24`. It must match
`config/runtime/security_runtime/security_runtime_production.toml` so FastAPI
accepts forwarded client IP and Origin metadata only from the gateway network.
The startup script runs `docker network create` when this external network does
not already exist and rejects an existing network with a different subnet.

## Domain production deployment

The maintained Chinese deployment and operations runbook is
[`docs/生产环境Docker一键部署与长期运维指南.md`](../../docs/生产环境Docker一键部署与长期运维指南.md).

The public entry is `https://nuotop.xyz`. Point the apex DNS A record at
`39.96.201.189`, then clone the two
repositories as siblings on the server:

```bash
install -d -m 755 /opt/web
cd /opt/web
git clone git@github-backend:1nuo123/python-web-fastapi.git
git clone git@github-frontend:1nuo123/typescript-web-nuxt.git
```

Generate untracked production secrets and start the complete stack with the
one-time bootstrap command:

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh bootstrap
```

Routine releases use `bash deploy/production.sh update`; it creates a
PostgreSQL backup, verifies that CI has published the exact images for both
repository commits, fast-forwards both repositories, pulls immutable image
Digests, runs migrations, and verifies readiness. The production host never
builds the frontend or backend images. Run `bash deploy/production.sh help` for
the complete command list.

The environment generator creates three mode-`600` files:

- backend runtime secrets: `.env.production.local`
- one-time administrator bootstrap data: `.env.initial-admin.local`
- frontend runtime configuration: `../typescript-web-nuxt/.env.production.local`

Record the generated `admin` password securely and remove
`.env.initial-admin.local` after the administrator is created.

The generated backend environment uses `CADDY_SITE_ADDRESS=nuotop.xyz` by
default. Once DNS resolves publicly and TCP ports 80 and 443 reach this host,
Caddy obtains and renews the public HTTPS certificate automatically. Production
refresh cookies and the Windows Agent WebSocket connection are HTTPS/WSS only.

The `caddy_data` volume stores certificates and must be backed up. Never use
`docker compose down -v` during routine deployment or rollback.

Final HTTPS acceptance must cover login refresh, WebSocket reconnection, a
mobile network switch, and snapshot recovery.

## Development HTTPS profile

Development uses the separate `fastapi-web-development-edge` network, the
`codex-dev.lan` hostname, and Caddy's internal CA. It must never reuse the
production environment file, Docker network, Caddy data volume, Agent state
directory, or database/Redis credentials.

Create a local environment file from `.env.docker.development.example`, replace
every placeholder password and secret, then create the isolated network before
starting the backend and Caddy:

```powershell
docker network create --driver bridge --internal --subnet 172.32.0.0/24 fastapi-web-development-edge
docker compose --project-name fastapi-web-development --env-file .env.docker.development.local -f compose.yml -f compose.caddy.yml up -d --build
docker compose --project-name fastapi-web-caddy-development --env-file .env.docker.development.local -f deploy/caddy/compose.development.yml up -d
```

The frontend container must also join `fastapi-web-development-edge` with the
network alias `frontend`; Caddy never falls back to the production frontend.
Point the Windows development host and the Android device at the LAN IPv4 of
the Caddy host for `codex-dev.lan`. Use a development-only DNS record when
available. For a temporary Windows hosts entry, edit the hosts file as an
administrator; do not add this mapping to production DNS.

Export and trust only the development CA. The generated CA is owned by the
development Caddy volume, so production certificates remain untouched:

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
docker compose --project-name fastapi-web-caddy-development --env-file .env.docker.development.local -f deploy/caddy/compose.development.yml cp caddy:/data/caddy/pki/authorities/local/root.crt artifacts/codex-dev-root-ca.crt
certutil -addstore -f Root artifacts/codex-dev-root-ca.crt
New-NetFirewallRule -DisplayName "Codex development HTTPS" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443
New-NetFirewallRule -DisplayName "Codex development HTTP3" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 443
```

The Windows root store is sufficient for browsers, but Python's OpenSSL client
does not automatically consume it. The development setup script therefore
persists the exported CA's absolute path in the Development Agent configuration
and uses it for both enrollment HTTPS and the long-lived WSS connection without
disabling certificate verification:

```powershell
.\scripts\codex\setup_local_agent.ps1 -DeploymentProfile development -DevelopmentCaCertificatePath (Resolve-Path .\artifacts\codex-dev-root-ca.crt)
```

This option is rejected for the production profile. Keep the CA file available
while the development Agent runs, then remove the development Agent state,
trusted root, firewall rules, hosts entry, and exported CA when retiring the
environment.

On Android, transfer `artifacts/codex-dev-root-ca.crt`, install it as a CA
certificate from the system security settings, and use the same development DNS
or hosts-capable resolver. Then open `https://codex-dev.lan` in Chrome and
complete login, streaming, approval, reconnect, and preference-sync checks.
Remove the two development firewall rules and the installed CA when the test
environment is retired.
