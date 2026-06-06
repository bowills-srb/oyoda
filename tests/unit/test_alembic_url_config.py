from db.migrations.url_config import resolve_migration_url


def test_prefers_explicit_alembic_database_url():
    url, source = resolve_migration_url(
        {
            "ALEMBIC_DATABASE_URL": "postgresql://user:pass@db.example.com:5432/app",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@pool.example.com:6543/app",
        }
    )

    assert source == "ALEMBIC_DATABASE_URL"
    assert url == "postgresql://user:pass@db.example.com:5432/app?sslmode=require"


def test_falls_back_to_database_url_without_forcing_direct_rewrite():
    url, source = resolve_migration_url(
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@pool.example.com:6543/app",
        }
    )

    assert source == "DATABASE_URL"
    assert url == "postgresql://user:pass@pool.example.com:6543/app?sslmode=require"


def test_direct_rewrite_is_explicit_opt_in():
    url, source = resolve_migration_url(
        {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@pool.example.com:6543/app",
            "ALEMBIC_USE_DIRECT_URL": "true",
        }
    )

    assert source == "DATABASE_URL"
    assert url == "postgresql://user:pass@pool.example.com:5432/app?sslmode=require"


def test_preserves_existing_sslmode():
    url, _ = resolve_migration_url(
        {
            "ALEMBIC_DATABASE_URL": "postgresql://user:pass@db.example.com:5432/app?sslmode=verify-full",
        }
    )

    assert url == "postgresql://user:pass@db.example.com:5432/app?sslmode=verify-full"
