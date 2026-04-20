import json

from sqlalchemy import text

from app.core.db import UTC_DATETIME_MIGRATION_KEY, migrate_datetime_columns_to_explicit_utc_strings


def test_utc_datetime_migration_runs_once_and_records_marker(session):
    migrate_datetime_columns_to_explicit_utc_strings()
    migrate_datetime_columns_to_explicit_utc_strings()
    session.expire_all()

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": UTC_DATETIME_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(UTC_DATETIME_MIGRATION_KEY, json.dumps(True))]
