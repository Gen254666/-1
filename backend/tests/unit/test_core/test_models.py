from sqlalchemy import CheckConstraint, DateTime, Numeric, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from steel_core.db import models  # noqa: F401  (import registers all tables)
from steel_core.db.base import Base

EXPECTED_TABLES = {
    "users",
    "user_session",
    "chat_session",
    "chat_message",
    "price_point",
    "market_quote",
    "inventory_snapshot",
    "inventory_item",
    "import_batch",
    "dataset_version",
    "daily_report",
    "app_config",
    "audit_log",
}


def test_all_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_users_use_uuid_primary_key_and_unique_username() -> None:
    users = Base.metadata.tables["users"]

    assert isinstance(users.c.id.type, Uuid)
    assert users.c.id.primary_key
    assert users.c.username.unique is True
    assert "must_change_password" in users.c
    created_at_type = users.c.created_at.type
    assert isinstance(created_at_type, DateTime)
    assert created_at_type.timezone is True


def test_price_point_enforces_owner_scope() -> None:
    price_point = Base.metadata.tables["price_point"]

    checks = [
        constraint
        for constraint in price_point.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert any("owner_user_id" in str(constraint.sqltext) for constraint in checks)

    partial_indexes = [
        index
        for index in price_point.indexes
        if index.dialect_options["postgresql"].get("where") is not None
    ]
    assert len(partial_indexes) == 2
    assert all(index.unique for index in partial_indexes)


def test_market_quote_has_unique_version_point_date() -> None:
    market_quote = Base.metadata.tables["market_quote"]

    unique_constraints = [
        constraint
        for constraint in market_quote.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        {column.name for column in constraint.columns} == {"version_id", "point_id", "quote_date"}
        for constraint in unique_constraints
    )
    price_type = market_quote.c.price.type
    assert isinstance(price_type, Numeric)
    assert price_type.precision == 12
    assert price_type.scale == 2


def test_dataset_version_has_single_active_version_per_date() -> None:
    dataset_version = Base.metadata.tables["dataset_version"]

    partial_indexes = [
        index
        for index in dataset_version.indexes
        if index.dialect_options["postgresql"].get("where") is not None
    ]
    assert len(partial_indexes) == 4
    by_name = {str(index.name): index for index in partial_indexes}
    public_active = by_name["uq_dataset_version_public_active"]
    private_active = by_name["uq_dataset_version_private_active"]
    assert public_active.unique is True
    assert private_active.unique is True
    assert {column.name for column in public_active.columns} == {
        "dataset_type",
        "effective_date",
    }
    assert {column.name for column in private_active.columns} == {
        "dataset_type",
        "effective_date",
        "owner_user_id",
    }
    assert "scope" in dataset_version.c
    assert "owner_user_id" in dataset_version.c


def test_json_columns_use_jsonb() -> None:
    chat_message = Base.metadata.tables["chat_message"]
    audit_log = Base.metadata.tables["audit_log"]
    app_config = Base.metadata.tables["app_config"]

    assert isinstance(chat_message.c.artifacts.type, JSONB)
    assert isinstance(audit_log.c.detail.type, JSONB)
    assert isinstance(app_config.c.value.type, JSONB)


def test_report_versions_are_unique_per_date() -> None:
    daily_report = Base.metadata.tables["daily_report"]

    unique_constraints = [
        constraint
        for constraint in daily_report.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        {column.name for column in constraint.columns} == {"report_date", "version_no"}
        for constraint in unique_constraints
    )


def test_import_batch_records_row_counts() -> None:
    import_batch = Base.metadata.tables["import_batch"]

    for column_name in ("rows_total", "rows_ok", "rows_failed"):
        assert column_name in import_batch.c
