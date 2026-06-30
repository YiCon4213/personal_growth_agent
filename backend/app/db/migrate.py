from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.pq import TransactionStatus

from app.core.database import require_database_url


MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_[a-z0-9_]+\.sql$")
MIGRATION_LOCK_NAME = "personal_growth_agent_schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str


def migrations_directory() -> Path:
    configured = os.getenv("MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    module_path = Path(__file__).resolve()
    candidates = (
        module_path.parents[2] / "infra" / "migrations",
        module_path.parents[3] / "infra" / "migrations",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])


def discover_migrations(directory: Path) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if not match:
            continue
        content = path.read_bytes()
        migrations.append(
            Migration(
                version=match.group("version"),
                name=path.name,
                path=path,
                checksum=hashlib.sha256(content).hexdigest(),
            )
        )
    if not migrations:
        raise RuntimeError(f"No versioned SQL migrations found in {directory}")
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise RuntimeError("Duplicate migration versions found")
    return migrations


def _schema_has_migration(cursor: psycopg.Cursor, version: str) -> bool:
    checks: dict[str, str] = {
        "001": (
            "SELECT count(*) = 12 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ("
            "'threads', 'messages', 'user_profile_items', 'profile_candidates', "
            "'user_skills', 'skill_candidates', 'mcp_servers', 'mcp_tools', "
            "'mcp_tool_calls', 'approval_requests', 'rag_documents', 'rag_chunks')"
        ),
        "003": (
            "SELECT count(*) = 8 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND ("
            "(table_name = 'rag_documents' AND column_name IN "
            "('embedding_provider', 'embedding_version', 'content_hash', 'index_status')) OR "
            "(table_name = 'rag_chunks' AND column_name IN "
            "('embedding_provider', 'embedding_version', 'embedding_dimension', 'content_hash')))"
        ),
        "004": (
            "SELECT COALESCE((SELECT format_type(a.atttypid, a.atttypmod) = 'vector(1024)' "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'rag_chunks' "
            "AND a.attname = 'embedding' AND NOT a.attisdropped), false)"
        ),
        "005": (
            "SELECT count(*) = 4 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'mcp_servers' "
            "AND column_name IN ('command', 'args', 'env', 'working_directory')"
        ),
    }
    check = checks.get(version)
    if check is None:
        return False
    cursor.execute(check)
    row = cursor.fetchone()
    return bool(row and row[0])


def _record_migration(cursor: psycopg.Cursor, migration: Migration, *, baseline: bool) -> None:
    cursor.execute(
        "INSERT INTO schema_migrations (version, name, checksum, baseline) VALUES (%s, %s, %s, %s)",
        (migration.version, migration.name, migration.checksum, baseline),
    )


def run_migrations() -> None:
    migrations = discover_migrations(migrations_directory())
    database_url = require_database_url().replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext(%s))", (MIGRATION_LOCK_NAME,))
            try:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                      version varchar(20) PRIMARY KEY,
                      name text NOT NULL,
                      checksum varchar(64) NOT NULL,
                      baseline boolean NOT NULL DEFAULT false,
                      applied_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                cursor.execute("SELECT version, name, checksum FROM schema_migrations")
                applied = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

                for migration in migrations:
                    previous = applied.get(migration.version)
                    if previous:
                        if previous != (migration.name, migration.checksum):
                            raise RuntimeError(
                                f"Applied migration {migration.version} differs from {migration.name}; "
                                "never edit an applied migration"
                            )
                        print(f"Migration {migration.name} already applied", flush=True)
                        continue

                    if _schema_has_migration(cursor, migration.version):
                        _record_migration(cursor, migration, baseline=True)
                        print(f"Baselined existing migration {migration.name}", flush=True)
                        continue

                    print(f"Applying migration {migration.name}", flush=True)
                    cursor.execute(migration.path.read_text(encoding="utf-8"))
                    _record_migration(cursor, migration, baseline=False)
                    print(f"Applied migration {migration.name}", flush=True)
            except Exception:
                connection.rollback()
                raise
            finally:
                if connection.info.transaction_status != TransactionStatus.IDLE:
                    connection.rollback()
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (MIGRATION_LOCK_NAME,))


if __name__ == "__main__":
    run_migrations()
