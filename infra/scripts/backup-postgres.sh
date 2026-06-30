#!/bin/sh
set -eu

umask 077
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
backup_dir=${BACKUP_DIR:-"$repo_root/infra/backups"}
retention_days=${BACKUP_RETENTION_DAYS:-14}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
output="$backup_dir/personal_growth_agent_$timestamp.dump"

mkdir -p "$backup_dir"
cd "$repo_root"
docker compose --env-file infra/.env \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.public.yml \
  exec -T postgres pg_dump \
  --username personal_growth_agent \
  --dbname personal_growth_agent \
  --format custom \
  --no-owner \
  --no-acl > "$output"

find "$backup_dir" -maxdepth 1 -type f -name 'personal_growth_agent_*.dump' \
  -mtime "+$retention_days" -delete
printf '%s\n' "$output"
