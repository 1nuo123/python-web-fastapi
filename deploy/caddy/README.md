# Caddy Docker Gateway

This gateway is the only public container in production. FastAPI, Nuxt,
PostgreSQL, Redis, and RabbitMQ remain on Docker networks without published
ports.

The trusted edge boundary is fixed to `172.30.0.0/24`. It must match
`config/runtime/security_runtime/security_runtime_production.toml` so FastAPI
accepts forwarded client IP and Origin metadata only from the gateway network.
The startup script runs `docker network create` when this external network does
not already exist and rejects an existing network with a different subnet.

## Temporary IP production acceptance

The current temporary public entry is `http://47.113.177.140`. Clone the two
repositories as siblings on the server:

```bash
install -d -m 755 /opt/web
cd /opt/web
git clone git@github-backend:1nuo123/python-web-fastapi.git
git clone git@github-frontend:1nuo123/typescript-web-nuxt.git
```

Generate untracked production secrets and start the complete stack:

```bash
cd /opt/web/python-web-fastapi
bash deploy/prepare-production-env.sh ../typescript-web-nuxt
bash deploy/run-production-ip.sh ../typescript-web-nuxt
```

The environment generator creates three mode-`600` files:

- backend runtime secrets: `.env.production.local`
- one-time administrator bootstrap data: `.env.initial-admin.local`
- frontend runtime configuration: `../typescript-web-nuxt/.env.production.local`

Record the generated `admin` password securely and remove
`.env.initial-admin.local` after the administrator is created.

Plain HTTP is only a temporary server acceptance path. Production refresh
cookies remain `Secure`, so persistent browser sessions and Windows Agent WSS
must be accepted again after a real HTTPS domain is available.

## Domain production

After DNS and ICP filing are ready, change `CADDY_SITE_ADDRESS` in the backend
production environment file to the domain, replace the production stream
allowed Origin with `https://<domain>`, and restart the backend and gateway.
Caddy will obtain and renew the public certificate automatically.

The `caddy_data` volume stores certificates and must be backed up. Never use
`docker compose down -v` during routine deployment or rollback.

Final HTTPS acceptance must cover login refresh, WebSocket reconnection, a
mobile network switch, and snapshot recovery.
