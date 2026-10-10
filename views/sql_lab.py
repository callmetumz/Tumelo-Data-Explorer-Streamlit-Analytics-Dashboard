"""SQL Lab: query the SQLite database behind the dashboard.

Queries run through ``database.run_query``, which opens the database in
read-only mode, so this page can never change stored data.
"""

import pandas as pd
import streamlit as st

from data_explorer import config, database, pipeline, profiling
from data_explorer.database import DatabaseError, quote_identifier
from ui import components as ui

QUERY_KEY = "sql_query_text"
EXAMPLE_KEY = "sql_example"


def example_queries(
    record: database.DatasetRecord | None, df: pd.DataFrame | None = None
) -> dict[str, str]:
    """Starter queries, written for the active dataset's real column names.

    When the data is available, the examples group by the text column with
    the fewest distinct values and measure the numeric column with the most,
    which usually gives a sensible "category" and "amount".
    """
    examples = {
        "Dataset catalog": (
            "SELECT name, table_name, row_count, column_count, missing_cells, duplicate_rows\n"
            "FROM datasets\n"
            "ORDER BY updated_at DESC;"
        ),
        "Pipeline activity by step": (
            "SELECT action,\n"
            "       COUNT(*)      AS runs,\n"
            "       SUM(rows_in)  AS rows_in,\n"
            "       SUM(rows_out) AS rows_out\n"
            "FROM pipeline_runs\n"
            "GROUP BY action\n"
            "ORDER BY runs DESC;"
        ),
    }
    if record is None:
        return examples

    table = quote_identifier(record.table_name)
    kinds = record.column_types
    text = [c for c, kind in kinds.items() if kind == profiling.TEXT]
    numeric = [c for c, kind in kinds.items() if kind == profiling.NUMERIC]
    dates = [c for c, kind in kinds.items() if kind == profiling.DATETIME]

    if df is not None:
        distinct = {column: df[column].nunique() for column in df.columns if column in kinds}
        text = sorted(text, key=lambda column: (distinct[column] < 2, distinct[column]))
        numeric = sorted(numeric, key=lambda column: -distinct[column])
    group_column = text[0] if text else None
    value_column = numeric[0] if numeric else None

    dataset_examples = {
        "Preview rows": f"SELECT *\nFROM {table}\nLIMIT 20;",
        "Count rows": f"SELECT COUNT(*) AS total_rows\nFROM {table};",
    }
    if text and numeric:
        group, value = quote_identifier(group_column), quote_identifier(value_column)
        dataset_examples["Group and aggregate"] = (
            f"SELECT {group},\n"
            f"       COUNT(*)                AS row_count,\n"
            f"       ROUND(AVG({value}), 2) AS average,\n"
            f"       ROUND(SUM({value}), 2) AS total\n"
            f"FROM {table}\n"
            f"GROUP BY {group}\n"
            f"ORDER BY total DESC;"
        )
    if numeric:
        value = quote_identifier(value_column)
        dataset_examples["Top 10 by value"] = (
            f"SELECT *\nFROM {table}\nWHERE {value} IS NOT NULL\nORDER BY {value} DESC\nLIMIT 10;"
        )
        dataset_examples["Count missing values"] = (
            f"SELECT COUNT(*)                         AS total_rows,\n"
            f"       SUM({value} IS NULL)             AS missing,\n"
            f"       ROUND(100.0 * SUM({value} IS NULL) / COUNT(*), 1) AS missing_pct\n"
            f"FROM {table};"
        )
    if dates and numeric:
        date, value = quote_identifier(dates[0]), quote_identifier(value_column)
        dataset_examples["Monthly trend"] = (
            f"SELECT strftime('%Y-%m', {date}) AS month,\n"
            f"       COUNT(*)               AS row_count,\n"
            f"       ROUND(SUM({value}), 2) AS total\n"
            f"FROM {table}\n"
            f"WHERE {date} IS NOT NULL\n"
            f"GROUP BY month\n"
            f"ORDER BY month;"
        )
    return {**dataset_examples, **examples}


def use_example() -> None:
    st.session_state[QUERY_KEY] = st.session_state["sql_examples"][st.session_state[EXAMPLE_KEY]]
    st.session_state.pop("sql_result", None)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
ui.page_header(
    "SQL Lab",
    "Query the SQLite database that stores every dataset. Read-only: SELECT statements only.",
    icon=":material/database:",
)

datasets = database.list_datasets()
record = ui.get_active_dataset(datasets)
tables = database.list_tables()

ui.kpi_row(
    [
        ui.Kpi("Dataset tables", ui.fmt_int((tables["kind"] == "dataset").sum())),
        ui.Kpi("Rows in dataset tables", ui.fmt_int(tables.loc[tables["kind"] == "dataset", "rows"].sum())),
        ui.Kpi("Database size", ui.fmt_bytes(database.database_size_bytes())),
        ui.Kpi(
            "Engine",
            "SQLite",
            help=f"File: {config.get_db_path()}. Set the DATA_EXPLORER_DB environment "
            "variable to store it somewhere else.",
        ),
    ]
)

query_tab, schema_tab, manage_tab = st.tabs(
    [":material/terminal: Query", ":material/schema: Tables", ":material/settings: Manage"]
)

# --- Query -----------------------------------------------------------------
with query_tab:
    examples = example_queries(record, ui.load_active_dataframe(record) if record else None)
    st.session_state["sql_examples"] = examples
    # Start with the first example, and again whenever the active dataset
    # changes, so the editor never points at a table the user has moved on from.
    active_id = record.id if record else None
    if QUERY_KEY not in st.session_state or st.session_state.get("sql_for_dataset") != active_id:
        st.session_state[QUERY_KEY] = next(iter(examples.values()))
        st.session_state["sql_for_dataset"] = active_id
        st.session_state.pop("sql_result", None)
        st.session_state.pop("sql_error", None)

    editor_col, help_col = st.columns([3, 1], gap="large")
    with help_col:
        st.selectbox(
            "Example queries",
            list(examples),
            key=EXAMPLE_KEY,
            on_change=use_example,
            help="Choosing an example replaces the text in the editor.",
        )
        if record is not None:
            st.caption(f"Active dataset table: `{record.table_name}`")
        st.caption(
            f"Results are limited to {ui.fmt_int(config.MAX_QUERY_ROWS)} rows and queries "
            f"stop after {config.QUERY_TIMEOUT_SECONDS} seconds."
        )
    with editor_col:
        sql = st.text_area("SQL query", key=QUERY_KEY, height=220)
        run = st.button("Run query", type="primary", icon=":material/play_arrow:")

    if run:
        try:
            st.session_state["sql_result"] = database.run_query(sql)
            st.session_state.pop("sql_error", None)
        except DatabaseError as error:
            st.session_state["sql_error"] = str(error)
            st.session_state.pop("sql_result", None)

    if "sql_error" in st.session_state:
        st.error(st.session_state["sql_error"], icon=":material/error:")
    result = st.session_state.get("sql_result")
    if result is not None:
        rows, columns = result.data.shape
        message = f"{ui.fmt_int(rows)} rows, {columns} columns in {result.seconds * 1000:.0f} ms."
        if result.truncated:
            message += f" Only the first {ui.fmt_int(config.MAX_QUERY_ROWS)} rows are shown."
        st.caption(message)
        st.dataframe(result.data, hide_index=True, width="stretch")
        st.download_button(
            "Download result as CSV",
            data=result.data.to_csv(index=False).encode("utf-8"),
            file_name="query_result.csv",
            mime="text/csv",
            icon=":material/download:",
            disabled=result.data.empty,
        )

# --- Tables ----------------------------------------------------------------
with schema_tab:
    st.caption(
        "`datasets` is the catalog, `pipeline_runs` is the activity log and each `ds_...` "
        "table holds one dataset's rows."
    )
    list_col, detail_col = st.columns([2, 3], gap="large")
    with list_col:
        st.dataframe(
            tables,
            hide_index=True,
            width="stretch",
            column_config={
                "table": "Table",
                "rows": st.column_config.NumberColumn("Rows", format="localized"),
                "kind": "Kind",
            },
        )
    with detail_col:
        names = tables["table"].tolist()
        default = names.index(record.table_name) if record and record.table_name in names else 0
        chosen = st.selectbox("Show columns for", names, index=default)
        st.dataframe(
            database.table_schema(chosen),
            hide_index=True,
            width="stretch",
            column_config={"column": "Column", "sql_type": "SQL type"},
        )

# --- Manage ----------------------------------------------------------------
with manage_tab:
    if not datasets:
        st.info("There are no datasets to manage yet.", icon=":material/info:")
    else:
        st.markdown("**Delete a dataset**")
        by_name = {d.name: d for d in datasets}
        target = by_name[st.selectbox("Dataset", list(by_name), key="delete_target")]
        st.caption(
            f"Table `{target.table_name}` - {ui.fmt_int(target.row_count)} rows, "
            f"{target.column_count} columns, loaded from {target.source}."
        )
        confirmed = st.checkbox(
            f"Yes, permanently delete '{target.name}'", key=f"confirm_delete_{target.id}"
        )
        if st.button("Delete dataset", icon=":material/delete:", disabled=not confirmed):
            pipeline.remove_dataset(target)
            ui.refresh_data()
            st.session_state.pop("sql_result", None)
            ui.flash(f"Deleted '{target.name}'", icon=":material/delete:")
            st.rerun()
