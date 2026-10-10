"""SQLite storage layer.

The database holds three kinds of table:

``datasets``
    The catalog: one row per stored dataset with its name, the table that
    holds its rows, and quality statistics captured when it was saved.
``pipeline_runs``
    An append-only log of everything the pipeline has done (ingest, clean,
    delete) with row counts in and out. The Home page KPIs are SQL
    aggregates over this table and the catalog.
``ds_<name>``
    One table per dataset containing the actual rows.

All SQL in the project lives in this module. Nothing here imports Streamlit.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd

from . import config
from .profiling import BOOLEAN, DATETIME, column_kind

CATALOG_TABLE = "datasets"
RUNS_TABLE = "pipeline_runs"
DATA_TABLE_PREFIX = "ds_"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {CATALOG_TABLE} (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    table_name     TEXT    NOT NULL UNIQUE,
    source         TEXT    NOT NULL,
    row_count      INTEGER NOT NULL,
    column_count   INTEGER NOT NULL,
    missing_cells  INTEGER NOT NULL,
    duplicate_rows INTEGER NOT NULL,
    column_types   TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT    NOT NULL,
    action       TEXT    NOT NULL CHECK (action IN ('ingest', 'clean', 'delete')),
    rows_in      INTEGER NOT NULL DEFAULT 0,
    rows_out     INTEGER NOT NULL DEFAULT 0,
    details      TEXT,
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON {RUNS_TABLE} (created_at);
"""


class DatabaseError(Exception):
    """Raised for problems the user can act on (bad SQL, unknown dataset...)."""


@dataclass(frozen=True)
class DatasetRecord:
    """One row of the ``datasets`` catalog."""

    id: int
    name: str
    table_name: str
    source: str
    row_count: int
    column_count: int
    missing_cells: int
    duplicate_rows: int
    column_types: dict[str, str]
    created_at: str
    updated_at: str

    @property
    def total_cells(self) -> int:
        return self.row_count * self.column_count

    @property
    def completeness_pct(self) -> float:
        if not self.total_cells:
            return 100.0
        return 100 * (1 - self.missing_cells / self.total_cells)


@dataclass(frozen=True)
class QueryResult:
    """Rows returned by a user-written SQL query."""

    data: pd.DataFrame
    truncated: bool
    seconds: float


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------
def _resolve(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path else config.get_db_path()


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a read-write connection, creating the file and schema if needed.

    Commits on success, rolls back on error and always closes the connection.
    """
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> Path:
    """Create the database file and tables if they do not exist yet."""
    with connect(db_path):
        pass
    return _resolve(db_path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def quote_identifier(name: str) -> str:
    """Quote a table or column name for use inside SQL."""
    return '"' + str(name).replace('"', '""') + '"'


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------
def _to_record(row: sqlite3.Row) -> DatasetRecord:
    return DatasetRecord(
        id=row["id"],
        name=row["name"],
        table_name=row["table_name"],
        source=row["source"],
        row_count=row["row_count"],
        column_count=row["column_count"],
        missing_cells=row["missing_cells"],
        duplicate_rows=row["duplicate_rows"],
        column_types=json.loads(row["column_types"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_datasets(db_path: str | Path | None = None) -> list[DatasetRecord]:
    """Every stored dataset, most recently updated first."""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {CATALOG_TABLE} ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [_to_record(row) for row in rows]


def get_dataset(dataset_id: int, db_path: str | Path | None = None) -> DatasetRecord | None:
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {CATALOG_TABLE} WHERE id = ?", (dataset_id,)
        ).fetchone()
    return _to_record(row) if row else None


def get_dataset_by_name(name: str, db_path: str | Path | None = None) -> DatasetRecord | None:
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {CATALOG_TABLE} WHERE name = ?", (name.strip(),)
        ).fetchone()
    return _to_record(row) if row else None


def _table_name_for(conn: sqlite3.Connection, name: str) -> str:
    """Pick a safe, unused table name such as ``ds_sales_2024``."""
    slug = re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_") or "dataset"
    base = f"{DATA_TABLE_PREFIX}{slug}"[:60]
    taken = {
        row[0]
        for row in conn.execute(f"SELECT table_name FROM {CATALOG_TABLE}").fetchall()
    }
    candidate, counter = base, 2
    while candidate in taken:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _column_types(df: pd.DataFrame) -> dict[str, str]:
    return {str(col): column_kind(df[col]) for col in df.columns}


def _for_storage(df: pd.DataFrame) -> pd.DataFrame:
    """Write date-only columns as ``YYYY-MM-DD`` text instead of full timestamps.

    SQLite has no date type, so dates are stored as ISO text. Dropping a
    meaningless ``00:00:00`` keeps query results readable, and SQLite's date
    functions (``strftime``, ``date``) accept both forms.
    """
    out = df
    for col in df.columns:
        if column_kind(df[col]) != DATETIME:
            continue
        values = df[col].dropna()
        if getattr(df[col].dt, "tz", None) is None and (values == values.dt.normalize()).all():
            if out is df:
                out = df.copy()
            out[col] = df[col].dt.strftime("%Y-%m-%d")
    return out


def save_dataset(
    df: pd.DataFrame,
    name: str,
    source: str,
    missing_cells: int,
    duplicate_rows: int,
    db_path: str | Path | None = None,
) -> DatasetRecord:
    """Store a DataFrame as a table and record it in the catalog.

    If a dataset with the same name already exists its rows are replaced and
    its catalog entry is updated; otherwise a new dataset is created.
    """
    name = name.strip()
    if not name:
        raise DatabaseError("A dataset needs a name.")
    if df.shape[1] == 0:
        raise DatabaseError("The dataset has no columns to store.")

    now = _now()
    types = json.dumps(_column_types(df))
    with connect(db_path) as conn:
        existing = conn.execute(
            f"SELECT id, table_name FROM {CATALOG_TABLE} WHERE name = ?", (name,)
        ).fetchone()
        table_name = existing["table_name"] if existing else _table_name_for(conn, name)

        _for_storage(df).to_sql(table_name, conn, if_exists="replace", index=False)

        stats = (source, len(df), df.shape[1], int(missing_cells), int(duplicate_rows), types, now)
        if existing:
            conn.execute(
                f"""
                UPDATE {CATALOG_TABLE}
                   SET source = ?, row_count = ?, column_count = ?, missing_cells = ?,
                       duplicate_rows = ?, column_types = ?, updated_at = ?
                 WHERE id = ?
                """,
                (*stats, existing["id"]),
            )
            dataset_id = existing["id"]
        else:
            cursor = conn.execute(
                f"""
                INSERT INTO {CATALOG_TABLE}
                    (name, table_name, source, row_count, column_count, missing_cells,
                     duplicate_rows, column_types, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, table_name, *stats, now),
            )
            dataset_id = cursor.lastrowid
        row = conn.execute(
            f"SELECT * FROM {CATALOG_TABLE} WHERE id = ?", (dataset_id,)
        ).fetchone()
    return _to_record(row)


def load_dataset(dataset_id: int, db_path: str | Path | None = None) -> pd.DataFrame:
    """Read a stored dataset back into a DataFrame with its original types.

    SQLite stores dates as text and booleans as 0/1, so the column types
    saved in the catalog are used to convert them back.
    """
    record = get_dataset(dataset_id, db_path)
    if record is None:
        raise DatabaseError(f"No dataset with id {dataset_id}.")
    with connect(db_path) as conn:
        df = pd.read_sql_query(f"SELECT * FROM {quote_identifier(record.table_name)}", conn)
    for col, kind in record.column_types.items():
        if col not in df.columns:
            continue
        if kind == DATETIME:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif kind == BOOLEAN:
            df[col] = df[col].astype("boolean") if df[col].isna().any() else df[col].astype(bool)
    return df


def delete_dataset(dataset_id: int, db_path: str | Path | None = None) -> None:
    """Drop a dataset's table and remove it from the catalog."""
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT table_name FROM {CATALOG_TABLE} WHERE id = ?", (dataset_id,)
        ).fetchone()
        if row is None:
            return
        conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(row['table_name'])}")
        conn.execute(f"DELETE FROM {CATALOG_TABLE} WHERE id = ?", (dataset_id,))


# --------------------------------------------------------------------------
# Pipeline log and KPIs
# --------------------------------------------------------------------------
def log_run(
    dataset_name: str,
    action: str,
    rows_in: int = 0,
    rows_out: int = 0,
    details: str = "",
    db_path: str | Path | None = None,
) -> None:
    """Append one entry to the pipeline log."""
    with connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {RUNS_TABLE} (dataset_name, action, rows_in, rows_out, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (dataset_name, action, int(rows_in), int(rows_out), details, _now()),
        )


def recent_runs(limit: int = 10, db_path: str | Path | None = None) -> pd.DataFrame:
    """The latest pipeline log entries, newest first."""
    with connect(db_path) as conn:
        return pd.read_sql_query(
            f"""
            SELECT created_at, dataset_name, action, rows_in, rows_out, details
              FROM {RUNS_TABLE}
             ORDER BY id DESC
             LIMIT ?
            """,
            conn,
            params=(int(limit),),
        )


def get_kpis(db_path: str | Path | None = None) -> dict[str, int]:
    """Headline numbers for the Home page, computed with SQL aggregates."""
    with connect(db_path) as conn:
        stored = conn.execute(
            f"""
            SELECT COUNT(*)                                   AS datasets,
                   COALESCE(SUM(row_count), 0)                AS rows_stored,
                   COALESCE(SUM(row_count * column_count), 0) AS cells_stored,
                   COALESCE(SUM(missing_cells), 0)            AS missing_cells,
                   COALESCE(SUM(duplicate_rows), 0)           AS duplicate_rows
              FROM {CATALOG_TABLE}
            """
        ).fetchone()
        activity = conn.execute(
            f"""
            SELECT COALESCE(SUM(CASE WHEN action IN ('ingest', 'clean') THEN rows_in END), 0)
                       AS records_processed,
                   COALESCE(SUM(CASE WHEN action = 'ingest' THEN 1 END), 0) AS ingest_runs,
                   COALESCE(SUM(CASE WHEN action = 'clean' THEN 1 END), 0)  AS cleaning_runs,
                   COALESCE(SUM(CASE WHEN action = 'clean' THEN rows_in - rows_out END), 0)
                       AS rows_removed_by_cleaning
              FROM {RUNS_TABLE}
            """
        ).fetchone()
    return {**dict(stored), **dict(activity)}


# --------------------------------------------------------------------------
# Schema browsing and ad-hoc SQL
# --------------------------------------------------------------------------
def list_tables(db_path: str | Path | None = None) -> pd.DataFrame:
    """Every table in the database with its row count."""
    with connect(db_path) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        rows = [
            {
                "table": name,
                "rows": conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(name)}").fetchone()[0],
                "kind": "dataset" if name.startswith(DATA_TABLE_PREFIX) else "system",
            }
            for name in names
        ]
    return pd.DataFrame(rows, columns=["table", "rows", "kind"])


def table_schema(table: str, db_path: str | Path | None = None) -> pd.DataFrame:
    """Column names and SQL types for one table."""
    with connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return pd.DataFrame(
        [{"column": row["name"], "sql_type": row["type"] or "ANY"} for row in rows],
        columns=["column", "sql_type"],
    )


def database_size_bytes(db_path: str | Path | None = None) -> int:
    path = _resolve(db_path)
    return path.stat().st_size if path.exists() else 0


def run_query(
    sql: str,
    max_rows: int = config.MAX_QUERY_ROWS,
    timeout_seconds: float = config.QUERY_TIMEOUT_SECONDS,
    db_path: str | Path | None = None,
) -> QueryResult:
    """Run one read-only SQL statement and return its rows.

    Safety comes from the database, not from inspecting the SQL text: the
    connection is opened in SQLite's read-only mode, so INSERT, UPDATE, DELETE
    and DROP are rejected by the engine itself. The query is also cancelled
    if it runs longer than ``timeout_seconds`` and at most ``max_rows`` rows
    are fetched.
    """
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise DatabaseError("Write a SQL query first.")

    path = init_db(db_path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    deadline = time.monotonic() + timeout_seconds
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    started = time.perf_counter()
    try:
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise DatabaseError("That statement does not return any rows. Try a SELECT query.")
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)
    except (sqlite3.ProgrammingError, sqlite3.Warning) as exc:
        # sqlite3 refuses to run several statements in one execute() call.
        raise DatabaseError("Run one SQL statement at a time.") from exc
    except sqlite3.OperationalError as exc:
        message = str(exc)
        if "readonly" in message or "read-only" in message:
            raise DatabaseError(
                "This page is read-only: only SELECT queries are allowed. "
                "Use the Data View page to change data."
            ) from exc
        if "interrupted" in message:
            raise DatabaseError(
                f"The query was stopped after {timeout_seconds:g} seconds. Add a filter or a LIMIT."
            ) from exc
        raise DatabaseError(f"SQL error: {message}") from exc
    except sqlite3.Error as exc:
        raise DatabaseError(f"SQL error: {exc}") from exc
    finally:
        conn.close()

    truncated = len(rows) > max_rows
    data = pd.DataFrame(rows[:max_rows], columns=_unique_labels(columns))
    return QueryResult(data=data, truncated=truncated, seconds=time.perf_counter() - started)


def _unique_labels(columns: list[str]) -> list[str]:
    """Result sets may repeat a column name (e.g. after a JOIN); make them unique."""
    seen: dict[str, int] = {}
    labels = []
    for col in columns:
        seen[col] = seen.get(col, 0) + 1
        labels.append(col if seen[col] == 1 else f"{col}_{seen[col]}")
    return labels
