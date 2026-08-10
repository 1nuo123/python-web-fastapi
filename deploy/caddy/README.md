# Caddy Docker Gateway

This directory contains the production gateway for the FastAPI and Nuxt
containers. Caddy terminates TLS, forwards WebSocket upgrades, adds a small
set of security headers, and writes structured access logs to Docker stdout.

The gateway uses the fixed internal network `fastapi-web-edge` with subnet
`172.30.0.0/24`. The backend trusts forwarded client headers only from this
network. Do not attach unrelated containers to it, and keep the subnet in sync
if the network is intentionally changed.

## Local acceptance without a domain

Run these commands from the backend workspace root:

```powershell
docker network create --driver bridge --internal --subnet 172.30.0.0/24 fastapi-web-edge
docker compose -f compose.yml -f compose.caddy.yml up -d --no-build --no-deps app
docker compose -f ..\typescript-web-nuxt\compose.yml -f ..\typescript-web-nuxt\compose.caddy.yml up -d --no-build --no-deps frontend
docker compose -f deploy\caddy\compose.yml up -d
```

The local gateway is available at `http://localhost:8080`. The default
`8443` mapping is reserved for later HTTPS verification; no certificate is
requested while `CADDY_SITE_ADDRESS` is `http://localhost`.

## Production with a domain

Set the following values in a deployment-only environment file, then run the
same Compose files with the production overlays. Caddy will serve
`https://example.com` after DNS points to the host:

```dotenv
EDGE_NETWORK_NAME=fastapi-web-edge
CADDY_SITE_ADDRESS=example.com
CADDY_BIND_ADDRESS=0.0.0.0
CADDY_HTTP_PORT=80
CADDY_HTTPS_PORT=443
```

```powershell
docker compose -f compose.yml -f compose.production.yml -f compose.caddy.yml up -d --no-build --no-deps app
docker compose -f ..\typescript-web-nuxt\compose.yml -f ..\typescript-web-nuxt\compose.production.yml -f ..\typescript-web-nuxt\compose.caddy.yml up -d --no-build --no-deps frontend
docker compose -f deploy\caddy\compose.yml up -d
```

Only Caddy publishes public ports in production. PostgreSQL, Redis, RabbitMQ,
FastAPI, and Nuxt stay on Docker networks. Caddy's `caddy_data` volume stores
certificates and must be backed up; it is separate from the existing database
volume and this setup never uses `down -v`.

The browser keeps one origin: `/api/*` is handled by Nuxt's backend proxy so
refresh-cookie path rewriting remains intact. Caddy sends only explicit API
and WebSocket paths directly to FastAPI; `/codex/tasks` and other page routes
remain Nuxt routes. WebSocket and HTTPS acceptance must be repeated after a
real domain is available, including a mobile network switch, reconnection,
and snapshot recovery.
