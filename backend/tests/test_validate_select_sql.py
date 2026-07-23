import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MAAS_ADMIN_TOKEN", "test-token")

from app.services.tool_service import validate_select_sql  # noqa: E402


ALLOWED_TABLES = {"work_orders"}


def test_validate_select_sql_allows_plain_select_and_adds_limit():
    sql = validate_select_sql(
        "SELECT task_id FROM work_orders", allowed_tables=ALLOWED_TABLES
    )

    assert "FROM work_orders" in sql
    assert sql.endswith("LIMIT 50")


def test_validate_select_sql_allows_cte_alias_without_treating_it_as_physical_table():
    sql = validate_select_sql(
        "WITH t AS (SELECT task_id FROM work_orders) SELECT * FROM t",
        allowed_tables=ALLOWED_TABLES,
    )

    assert "WITH t AS" in sql
    assert sql.endswith("LIMIT 50")


def test_validate_select_sql_allows_string_literal_with_blocked_keyword():
    sql = validate_select_sql(
        "SELECT '含 insert 字样的字符串字面量' AS note FROM work_orders",
        allowed_tables=ALLOWED_TABLES,
    )

    assert "insert" in sql.lower()
    assert sql.endswith("LIMIT 50")


def test_validate_select_sql_preserves_existing_limit():
    sql = validate_select_sql(
        "SELECT task_id FROM work_orders LIMIT 10", allowed_tables=ALLOWED_TABLES
    )

    assert sql.lower().count("limit") == 1
    assert "10" in sql


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO work_orders (task_id) VALUES ('1')",
        "UPDATE work_orders SET task_id = '1'",
        "DELETE FROM work_orders",
        "DROP TABLE work_orders",
        "ALTER TABLE work_orders ADD COLUMN x TEXT",
        "CREATE TABLE x (id INTEGER)",
    ],
)
def test_validate_select_sql_rejects_write_or_admin_statements(sql):
    with pytest.raises(ValueError, match="write_or_admin_statement_not_allowed"):
        validate_select_sql(sql, allowed_tables=ALLOWED_TABLES)


def test_validate_select_sql_rejects_multiple_statements():
    with pytest.raises(ValueError, match="multiple_statements_not_allowed"):
        validate_select_sql(
            "SELECT 1; DROP TABLE work_orders", allowed_tables=ALLOWED_TABLES
        )


def test_validate_select_sql_rejects_unauthorized_table():
    with pytest.raises(ValueError, match="table_not_allowed"):
        validate_select_sql("SELECT * FROM secret_table", allowed_tables=ALLOWED_TABLES)


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info(work_orders)",
        "ATTACH DATABASE 'x.db' AS x",
    ],
)
def test_validate_select_sql_rejects_sqlite_admin_constructs(sql):
    with pytest.raises(ValueError, match="forbidden_construct"):
        validate_select_sql(sql, allowed_tables=ALLOWED_TABLES)


def test_validate_select_sql_rejects_write_statement_inside_subquery():
    with pytest.raises(ValueError, match="write_or_admin_statement_not_allowed"):
        validate_select_sql(
            "SELECT * FROM (DELETE FROM work_orders)", allowed_tables=ALLOWED_TABLES
        )


def test_validate_select_sql_rejects_sqlite_metadata_table():
    with pytest.raises(ValueError, match="forbidden_construct"):
        validate_select_sql(
            "SELECT * FROM sqlite_master", allowed_tables=ALLOWED_TABLES
        )
