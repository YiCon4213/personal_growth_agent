from pathlib import Path

import pytest

from app.db.migrate import discover_migrations


def test_discover_migrations_orders_and_hashes_versioned_sql(tmp_path: Path) -> None:
    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "notes.sql").write_text("ignored", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == ["001", "002"]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_discover_migrations_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_other.sql").write_text("SELECT 2;", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Duplicate migration versions"):
        discover_migrations(tmp_path)
