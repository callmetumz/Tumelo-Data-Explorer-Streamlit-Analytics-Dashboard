"""Home: the dashboard landing page.

Shows headline KPIs for everything in the database, the dataset catalog,
a data-quality snapshot of the active dataset and recent pipeline activity.
All numbers come from SQL queries in ``data_explorer.database``.
"""

import pandas as pd
import streamlit as st

from data_explorer import charts, database, profiling
from ui import components as ui

ui.page_header(
    "Tumelo Data Explorer",
    "Load a dataset, check its quality, clean it, chart it and query it with SQL - "
    "all backed by a SQLite database.",
    icon="📊",
)

datasets = database.list_datasets()
kpis = database.get_kpis()

if not datasets:
    ui.empty_state(on_page="home")

# --- KPI cards ---------------------------------------------------------------
completeness = (
    100 * (1 - kpis["missing_cells"] / kpis["cells_stored"]) if kpis["cells_stored"] else None
)
ui.kpi_row(
    [
        ui.Kpi(
            "Datasets loaded",
            ui.fmt_int(kpis["datasets"]),
            help="Datasets currently stored in the SQLite database.",
        ),
        ui.Kpi(
            "Records processed",
            ui.fmt_int(kpis["records_processed"]),
            help="Total rows that have passed through the pipeline: every load "
            f"({kpis['ingest_runs']}) and every cleaning run ({kpis['cleaning_runs']}).",
        ),
        ui.Kpi(
            "Rows stored",
            ui.fmt_int(kpis["rows_stored"]),
            help="Rows held in the database right now, across all datasets.",
        ),
        ui.Kpi(
            "Data completeness",
            ui.fmt_pct(completeness) if completeness is not None else "-",
            help=f"Share of stored cells that have a value. "
            f"{ui.fmt_int(kpis['missing_cells'])} cells are missing.",
        ),
        ui.Kpi(
            "Duplicate rows",
            ui.fmt_int(kpis["duplicate_rows"]),
            help="Exact repeat rows still present in stored datasets. "
            f"Cleaning has removed {ui.fmt_int(kpis['rows_removed_by_cleaning'])} rows so far.",
        ),
    ]
)

# --- Catalog and quality snapshot ------------------------------------------
if datasets:
    active = ui.get_active_dataset(datasets)
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("Datasets", anchor=False)
        catalog = pd.DataFrame(
            {
                "Dataset": [d.name for d in datasets],
                "Rows": [d.row_count for d in datasets],
                "Columns": [d.column_count for d in datasets],
                "Complete": [d.completeness_pct for d in datasets],
                "Duplicates": [d.duplicate_rows for d in datasets],
                "Updated (UTC)": [d.updated_at for d in datasets],
            }
        )
        st.dataframe(
            catalog,
            hide_index=True,
            width="stretch",
            column_config={
                "Rows": st.column_config.NumberColumn(format="localized"),
                "Complete": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0, max_value=100
                ),
            },
        )
        links = st.columns(3)
        links[0].page_link(ui.PAGE_DATA, label="Explore and clean", icon=":material/table_view:")
        links[1].page_link(ui.PAGE_PLOT, label="Build a chart", icon=":material/insert_chart:")
        links[2].page_link(ui.PAGE_SQL, label="Query with SQL", icon=":material/database:")

    with right:
        st.subheader("Data quality", anchor=False)
        st.caption(f"Active dataset: **{active.name}**")
        df = ui.load_active_dataframe(active)
        missing = profiling.missing_by_column(df)
        if missing.empty:
            st.success("No missing values in this dataset.", icon=":material/verified:")
        else:
            result = charts.missing_values_chart(missing, dark=ui.is_dark_theme(), top_n=8)
            result.figure.update_layout(title_text="")
            result.figure.update_layout(margin=dict(t=10))
            st.plotly_chart(result.figure, width="stretch", config={"displayModeBar": False})
        if active.duplicate_rows:
            st.warning(
                f"{ui.fmt_int(active.duplicate_rows)} duplicate rows found. "
                "Remove them on the Data View page.",
                icon=":material/content_copy:",
            )
        else:
            st.success("No duplicate rows in this dataset.", icon=":material/verified:")

    # --- Activity ---------------------------------------------------------
    st.subheader("Recent pipeline activity", anchor=False)
    runs = database.recent_runs(limit=8)
    st.dataframe(
        runs.rename(
            columns={
                "created_at": "When (UTC)",
                "dataset_name": "Dataset",
                "action": "Step",
                "rows_in": "Rows in",
                "rows_out": "Rows out",
                "details": "Details",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Rows in": st.column_config.NumberColumn(format="localized"),
            "Rows out": st.column_config.NumberColumn(format="localized"),
        },
    )

# --- How it works ----------------------------------------------------------
st.subheader("How the data flows", anchor=False)
STAGES = [
    (":material/upload_file:", "1. Data source", "A CSV upload or the built-in sample dataset."),
    (
        ":material/settings:",
        "2. Python processing",
        "pandas parses the file, tidies headers, detects dates and profiles data quality.",
    ),
    (
        ":material/database:",
        "3. SQLite database",
        "Each dataset is stored as a table, with a catalog and a log of every pipeline run.",
    ),
    (
        ":material/dashboard:",
        "4. Dashboard",
        "These pages read from the database to show tables, charts and SQL results.",
    ),
]
for column, (icon, title, text) in zip(st.columns(len(STAGES)), STAGES):
    with column.container(border=True, height="stretch"):
        st.markdown(f"{icon} **{title}**")
        st.caption(text)
