import pandas as pd
import pytest

from data_explorer import database
from data_explorer.database import DatabaseError


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "name": ["a", "b", None],
            "when": pd.to_datetime(["2025-01-01", "2025-03-01", None]),
            "ok": [True, False, True],
            "value": [1.5, None, 3.0],
        }
    )


def save(frame, name="Sales 2025"):
    return database.save_dataset(frame, name, "test.csv", missing_cells=3, duplicate_rows=0)


def test_init_db_creates_file_and_system_tables(db_path):
    database.init_db()
    assert db_path.exists()
    assert set(database.list_tables()["table"]) == {"datasets", "pipeline_runs"}


def test_save_and_load_round_trip_keeps_types(db_path, frame):
    record = save(frame)
    assert record.table_name == "ds_sales_2025"
    assert (record.row_count, record.column_count) == (3, 4)

    loaded = database.load_dataset(record.id)
    assert pd.api.types.is_datetime64_any_dtype(loaded["when"])
    assert pd.api.types.is_bool_dtype(loaded["ok"])
    assert loaded["when"].iloc[1] == pd.Timestamp("2025-03-01")
    assert loaded["name"].isna().sum() == 1
    assert loaded["value"].tolist()[0] == 1.5


def test_date_only_columns_are_stored_without_a_time(db_path, frame):
    record = save(frame)
    stored = database.run_query(f"SELECT \"when\" FROM {record.table_name} ORDER BY 1 DESC").data
    assert stored["when"].iloc[0] == "2025-03-01"


def test_saving_the_same_name_replaces_the_dataset(db_path, frame):
    first = save(frame)
    second = save(frame.head(1))
    assert second.id == first.id
    assert second.row_count == 1
    assert len(database.list_datasets()) == 1


def test_names_that_collide_get_different_tables(db_path, frame):
    a = save(frame, "Sales 2025")
    b = save(frame, "sales-2025")
    assert a.table_name != b.table_name


def test_save_rejects_blank_names(db_path, frame):
    with pytest.raises(DatabaseError):
        save(frame, "   ")


def test_delete_dataset_drops_table_and_catalog_row(db_path, frame):
    record = save(frame)
    database.delete_dataset(record.id)
    assert database.list_datasets() == []
    assert record.table_name not in set(database.list_tables()["table"])
    with pytest.raises(DatabaseError):
        database.load_dataset(record.id)


def test_kpis_come_from_catalog_and_log(db_path, frame):
    assert database.get_kpis()["datasets"] == 0
    save(frame)
    database.log_run("Sales 2025", "ingest", rows_in=3, rows_out=3)
    database.log_run("Sales 2025", "clean", rows_in=3, rows_out=2)
    kpis = database.get_kpis()
    assert kpis["datasets"] == 1
    assert kpis["rows_stored"] == 3
    assert kpis["cells_stored"] == 12
    assert kpis["records_processed"] == 6
    assert kpis["rows_removed_by_cleaning"] == 1
    assert database.recent_runs()["action"].tolist() == ["clean", "ingest"]


def test_run_query_returns_rows_and_respects_the_row_limit(db_path, frame):
    record = save(frame)
    result = database.run_query(f"SELECT COUNT(*) AS n FROM {record.table_name};")
    assert result.data["n"].iloc[0] == 3
    limited = database.run_query(f"SELECT * FROM {record.table_name}", max_rows=2)
    assert len(limited.data) == 2 and limited.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM datasets",
        "DROP TABLE datasets",
        "UPDATE datasets SET name = 'x'",
        "INSERT INTO pipeline_runs (dataset_name, action, created_at) VALUES ('x', 'ingest', 'now')",
        "CREATE TABLE hack (a)",
    ],
)
def test_run_query_cannot_change_the_database(db_path, frame, sql):
    save(frame)
    with pytest.raises(DatabaseError, match="read-only"):
        database.run_query(sql)
    assert len(database.list_datasets()) == 1


def test_run_query_reports_bad_sql_clearly(db_path):
    with pytest.raises(DatabaseError, match="SQL error"):
        database.run_query("SELEC 1")
    with pytest.raises(DatabaseError, match="one SQL statement"):
        database.run_query("SELECT 1; SELECT 2")
    with pytest.raises(DatabaseError):
        database.run_query("   ")


def test_run_query_stops_runaway_queries(db_path):
    endless = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(DatabaseError, match="stopped"):
        database.run_query(endless, timeout_seconds=0.3)
