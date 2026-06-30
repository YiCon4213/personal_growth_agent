# Docker Compose Operations

The stack has three long-running application services (`frontend`, `backend`, and `postgres`) plus a one-shot `migrate` job. Public deployment adds Caddy for HTTPS and a mandatory temporary Basic Auth perimeter. Run commands from the repository root.

## Local startup

1. Copy `backend/.env.example` to uncommitted `backend/.env` and add provider credentials there.
2. Optionally copy `infra/.env.example` to uncommitted `infra/.env` for local overrides.
3. Start the stack:

```powershell
docker compose -f infra/docker-compose.yml up --build -d --wait
```

Local ports bind to `127.0.0.1` by default:

- frontend: `http://127.0.0.1:3000`
- backend liveness: `http://127.0.0.1:8000/api/v1/health`
- backend readiness: `http://127.0.0.1:8000/api/v1/health/ready`
- PostgreSQL: `127.0.0.1:5433`

Set an explicit host IP only for a trusted private network. Never bind PostgreSQL or the backend directly to a public interface.

## Public deployment topology

```text
Internet -> Caddy :80/:443 -> frontend :3000 -> backend :8000 -> PostgreSQL :5432
```

Only Caddy publishes public ports. The base stack's diagnostic ports remain loopback-only. Caddy obtains and renews HTTPS certificates, caps request bodies, emits JSON access logs, strips its server header, and requires Basic Auth. That gate is temporary perimeter protection for this fixed-user application; it is not application authentication or multi-user support. Do not remove it until a separately scoped authentication phase exists. A private VPN or managed identity-aware proxy is preferable when available.

### Prerequisites

- A Linux host with current Docker Engine and Compose v2.
- A domain whose A/AAAA record resolves to the host.
- Inbound TCP 80/443 and UDP 443 allowed; database/backend/frontend ports blocked by the cloud firewall.
- Outbound HTTPS allowed for image pulls, ACME, DeepSeek, DashScope, and explicitly approved remote MCP hosts.

### Configure secrets

```bash
cp backend/.env.example backend/.env
cp infra/public.env.example infra/.env
chmod 600 backend/.env infra/.env
```

Use `openssl rand -hex 32` for `POSTGRES_PASSWORD`. Put real provider keys only in `backend/.env`. Generate the Caddy password hash:

```bash
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext 'a-long-unique-password'
```

In `infra/.env`, double every `$` in the bcrypt result as `$$` so Compose passes it literally. Keep `.env` files out of Git and out of shell history where possible. Set:

- `PUBLIC_DOMAIN` to the real DNS name;
- `ACCESS_USER` and `ACCESS_PASSWORD_HASH` for the temporary perimeter;
- a long URL-safe `POSTGRES_PASSWORD`;
- `MCP_REMOTE_ALLOWED_HOSTS` only when a specific remote HTTPS MCP host is approved;
- `TRUSTED_PROXY_CIDRS` only to the actual reverse-proxy network if the Docker default is unsuitable.

Production rejects wildcard `ALLOWED_HOSTS` and wildcard CORS. Same-origin browser access through Caddy needs no CORS origin.

### Validate and start

```bash
docker compose --env-file infra/.env \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.public.yml config --quiet

docker compose --env-file infra/.env \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.public.yml up --build -d --wait
```

Inspect status and logs without printing environment values:

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/docker-compose.public.yml ps
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/docker-compose.public.yml logs --tail 200 caddy backend frontend migrate postgres
```

Acceptance checks:

```bash
curl -I https://YOUR_DOMAIN/
curl -u 'ACCESS_USER:ACCESS_PASSWORD' https://YOUR_DOMAIN/api/v1/health
curl -u 'ACCESS_USER:ACCESS_PASSWORD' https://YOUR_DOMAIN/api/v1/health/ready
```

Confirm HTTP redirects to HTTPS, unauthenticated requests receive 401, authenticated frontend/API requests succeed, the certificate chain is valid, and security headers are present. Then exercise one non-quota fake/safe workflow. Existing DeepSeek/DashScope live acceptance does not need repetition unless provider configuration or integration code changed.

## Security controls and operational limits

- FastAPI enforces explicit Host values, optional exact-origin CORS, a total request-body ceiling, per-client in-process rate limiting, request IDs, security headers, and structured access logs that omit bodies and query strings.
- The current rate limiter is per backend process and memory-local. Keep one backend worker, and use an edge/WAF or shared rate limiter before horizontal scaling.
- The upload endpoint retains its separate 10 MiB file limit; Caddy/frontend/backend use a 12 MiB envelope.
- stdio MCP requires an allowlisted bare command and allowlisted first target (`uvx` defaults only to `mcp-server-time`); arbitrary absolute commands, working directories, and environment keys are denied by default.
- Production remote MCP requires HTTPS and an exact `MCP_REMOTE_ALLOWED_HOSTS` entry. Remote Streamable HTTP remains live-unverified.
- High-risk MCP tools still create approval records and preserve the row-lock exactly-once execution boundary.
- API docs are disabled in production.
- Backend and frontend run non-root with read-only root filesystems, dropped Linux capabilities, and `no-new-privileges`. PostgreSQL data remains on a named volume.

## Migration behavior

The `migrate` job runs after PostgreSQL is healthy and must finish before backend readiness can pass. It discovers numbered SQL files, serializes runners with an advisory lock, verifies checksums, and records applied versions in `schema_migrations`. Never edit an applied migration; add the next numbered file.

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/docker-compose.public.yml logs migrate
```

`docker compose down` keeps named volumes. Never add `--volumes` unless permanent deletion is intentional.

## Backups and restore drills

Create an encrypted/off-host backup target before launch. The supplied script creates a PostgreSQL custom-format dump with mode `0600` semantics and deletes local dumps older than `BACKUP_RETENTION_DAYS` (default 14):

```bash
BACKUP_DIR=/secure/backup/path BACKUP_RETENTION_DAYS=14 ./infra/scripts/backup-postgres.sh
```

Schedule it with systemd timer or cron, then replicate the directory to encrypted object storage. A local Docker volume is not a backup.

Test restore on an isolated database, never over production:

```bash
docker compose exec -T postgres createdb -U personal_growth_agent personal_growth_agent_restore_test
docker compose exec -T postgres pg_restore -U personal_growth_agent -d personal_growth_agent_restore_test --clean --if-exists < /secure/backup/path/FILE.dump
```

Record restore time and verify `schema_migrations`, row counts, and representative conversations/RAG documents. Delete the isolated restore database after verification.

## Updating and rollback

Before updating, take a backup and record the current Git commit and image digests. Pull reviewed code, run Compose config validation, build, and start with `--wait`. If application code regresses without a new migration, redeploy the previous commit/images. If a migration ran, do not edit or reverse SQL casually; restore into an isolated environment and follow a reviewed forward-fix or backup recovery plan.

## Verification record

- Phase 4 full-stack live acceptance on 2026-06-28 remains valid for migrations 001-006, persistence, image builds, health, and browser access.
- Credentialed DashScope/index rebuild, Time stdio, and DeepSeek MCP tool selection were previously user-confirmed and were not mechanically repeated for Phase 5.
- Phase 5 verification on 2026-06-30 passed 95 backend tests, frontend lint/type/host production build, base/public Compose parsing, backend image build, hardened local container recreation, Caddyfile validation, and temporary local HTTPS Basic Auth 401/200 smoke.
- A fresh frontend image did not build because official npm registry access failed twice (`EIDLETIMEOUT`, then `ECONNRESET`). The runtime smoke therefore used the previously available frontend image; rebuild that image before release.
- Public DNS, ACME certificate issuance, firewall policy, off-host backup execution, external rate limiting, and remote Streamable HTTP require deployment-environment live verification.
