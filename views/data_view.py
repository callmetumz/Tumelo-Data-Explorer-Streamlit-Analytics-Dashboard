"""Data View: load, explore, check and clean a dataset.

This page only collects choices from widgets and displays results. Parsing,
profiling, filtering, cleaning and storage are all done by functions in the
``data_explorer`` package.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from data_explorer import charts, database, pipeline, profiling
from data_explorer.cleaning import FILL_STRATEGIES, CleaningOptions, clean_dataset
from data_explorer.filtering import (
    RangeFilter,
    TextFilter,
    ValuesFilter,
    apply_filters,
    search_rows,
)
from data_explorer.sample_data import sample_csv_bytes
from ui import components as ui

MAX_PICKLIST_VALUES = 50


# --------------------------------------------------------------------------
# Load data
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Reading file...")
def parse_upload(raw: bytes) -> pd.DataFrame:
    return pipeline.prepare(pipeline.read_csv(raw))


UPLOAD_COUNTER = "upload_counter"


def render_loader(has_data: bool) -> None:
    with st.expander("Load data", icon=":material/upload_file:", expanded=not has_data):
        upload_col, sample_col = st.columns([3, 2], gap="large")

        with upload_col:
            uploaded = st.file_uploader(
                "Upload a CSV file",
                type=["csv", "tsv", "txt"],
                help="Comma, semicolon and tab separated files are detected automatically.",
                # A new key after each save gives a fresh, empty uploader.
                key=f"upload_{st.session_state.get(UPLOAD_COUNTER, 0)}",
            )
            if uploaded is not None:
                try:
                    preview = parse_upload(uploaded.getvalue())
                except pipeline.PipelineError as error:
                    st.error(str(error), icon=":material/error:")
                else:
                    profile = profiling.profile_dataset(preview)
                    st.caption(
                        f"**{uploaded.name}** - {ui.plural(profile.rows, 'row')}, "
                        f"{ui.plural(profile.columns, 'column')}, "
                        f"{ui.plural(profile.missing_cells, 'missing cell')}, "
                        f"{ui.plural(profile.duplicate_rows, 'duplicate row')}"
                    )
                    st.dataframe(
                        preview.head(5),
                        hide_index=True,
                        width="stretch",
                        column_config=ui.table_config(preview),
                    )
                    name = st.text_input(
                        "Dataset name", value=Path(uploaded.name).stem, max_chars=60
                    ).strip()
                    exists = bool(name) and database.get_dataset_by_name(name) is not None
                    if exists:
                        st.warning(
                            f"A dataset called '{name}' already exists and will be replaced.",
                            icon=":material/warning:",
                        )
                    if st.button(
                        "Replace dataset" if exists else "Save to database",
                        type="primary",
                        icon=":material/save:",
                        disabled=not name,
                    ):
                        record = pipeline.ingest_csv(
                            uploaded.getvalue(), name=name, filename=uploaded.name
                        )
                        ui.refresh_data(record.id)
                        st.session_state[UPLOAD_COUNTER] = st.session_state.get(UPLOAD_COUNTER, 0) + 1
                        ui.flash(f"Saved '{record.name}' ({ui.plural(record.row_count, 'row')})")
                        st.rerun()

        with sample_col:
            st.markdown("**No file to hand?**")
            st.caption(
                "The sample is a retail sales dataset with missing values, duplicate rows "
                "and untidy text, so every tool on this page has something to do."
            )
            if st.button("Load sample dataset", icon=":material/dataset:", key="loader_sample"):
                ui.load_sample()
            st.download_button(
                "Download the sample as CSV",
                data=sample_csv_bytes(),
                file_name="sample_retail_sales.csv",
                mime="text/csv",
                icon=":material/download:",
                help="Handy for trying the upload yourself.",
            )


# --------------------------------------------------------------------------
# Explore
# --------------------------------------------------------------------------
def build_filters(df: pd.DataFrame, key: str) -> list:
    """Turn the user's widget choices into filter objects."""
    chosen = st.multiselect(
        "Filter by column",
        list(df.columns),
        key=f"{key}_filter_columns",
        placeholder="Choose columns to filter on",
    )
    filters = []
    for column in chosen:
        series = df[column]
        kind = profiling.column_kind(series)
        has_missing = bool(series.isna().any())
        non_null = series.dropna()
        widget_key = f"{key}_filter_{column}"

        with st.container(border=True):
            if non_null.empty:
                st.caption(f"**{column}** has no values to filter on.")
                continue

            if kind == profiling.NUMERIC:
                low, high = non_null.min(), non_null.max()
                if low == high:
                    st.caption(f"**{column}** only contains the value {low}.")
                    continue
                if pd.api.types.is_integer_dtype(series):
                    low, high = int(low), int(high)
                else:
                    low, high = float(low), float(high)
                picked = st.slider(column, low, high, (low, high), key=widget_key)
                keep = has_missing and st.checkbox(
                    "Include rows where this is missing", key=f"{widget_key}_na"
                )
                if picked != (low, high):
                    filters.append(RangeFilter(column, picked[0], picked[1], keep_missing=keep))

            elif kind == profiling.DATETIME:
                first, last = non_null.min().date(), non_null.max().date()
                picked = st.date_input(
                    column, (first, last), min_value=first, max_value=last, key=widget_key
                )
                keep = has_missing and st.checkbox(
                    "Include rows where this is missing", key=f"{widget_key}_na"
                )
                if not (isinstance(picked, tuple) and len(picked) == 2):
                    st.caption("Pick an end date to apply this filter.")
                elif picked != (first, last):
                    start = pd.Timestamp(picked[0])
                    end = pd.Timestamp(picked[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
                    filters.append(RangeFilter(column, start, end, keep_missing=keep))

            elif non_null.nunique() <= MAX_PICKLIST_VALUES:
                options = sorted(non_null.unique().tolist(), key=str)
                picked = st.multiselect(
                    column, options, key=widget_key, placeholder="Choose values to keep"
                )
                keep = has_missing and st.checkbox(
                    "Include rows where this is missing", key=f"{widget_key}_na"
                )
                if picked or keep:
                    filters.append(ValuesFilter(column, tuple(picked), keep_missing=keep))

            else:
                text = st.text_input(f"{column} contains", key=widget_key)
                if text:
                    filters.append(TextFilter(column, text))
    return filters


def render_explore(df: pd.DataFrame, record: database.DatasetRecord) -> None:
    key = f"ds{record.id}"
    filter_col, table_col = st.columns([1, 3], gap="large")

    with filter_col:
        st.markdown("**Filters**")
        search = st.text_input(
            "Search all columns", key=f"{key}_search", placeholder="Type to search"
        )
        filters = build_filters(df, key)
        visible = st.multiselect(
            "Columns to show",
            list(df.columns),
            key=f"{key}_visible",
            placeholder="All columns",
        )

    filtered = search_rows(apply_filters(df, filters), search)
    shown = filtered[visible] if visible else filtered

    with table_col:
        if len(filtered) == len(df):
            st.caption(f"Showing all {ui.fmt_int(len(df))} rows. Click a column header to sort.")
        else:
            st.caption(
                f"Showing {ui.fmt_int(len(filtered))} of {ui.fmt_int(len(df))} rows "
                f"({ui.fmt_pct(100 * len(filtered) / len(df))}). Click a column header to sort."
            )
        st.dataframe(
            shown,
            hide_index=True,
            width="stretch",
            height=ui.table_height(len(shown)),
            column_config=ui.table_config(shown),
        )
        st.download_button(
            "Download these rows as CSV",
            data=shown.to_csv(index=False).encode("utf-8"),
            file_name=f"{record.table_name.removeprefix('ds_')}_filtered.csv",
            mime="text/csv",
            icon=":material/download:",
            disabled=shown.empty,
        )


# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------
def render_quality(df: pd.DataFrame) -> None:
    missing = profiling.missing_by_column(df)
    dupes = profiling.duplicate_rows(df)
    repeat_count = profiling.count_duplicate_rows(df)

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Missing values", anchor=False)
        if missing.empty:
            st.success("No missing values.", icon=":material/verified:")
        else:
            st.caption(
                f"{len(missing)} of {df.shape[1]} columns have missing values "
                f"({ui.fmt_int(missing['missing'].sum())} cells in total)."
            )
            result = charts.missing_values_chart(missing, dark=ui.is_dark_theme())
            result.figure.update_layout(title_text="", margin=dict(t=10))
            st.plotly_chart(result.figure, width="stretch", config={"displayModeBar": False})

    with right:
        st.subheader("Duplicate rows", anchor=False)
        if dupes.empty:
            st.success("No duplicate rows.", icon=":material/verified:")
        else:
            st.caption(
                f"{ui.plural(repeat_count, 'row')} repeat{'s' if repeat_count == 1 else ''} "
                "an earlier row exactly. "
                "Each group of identical rows is shown together below."
            )
            st.dataframe(
                dupes,
                hide_index=True,
                width="stretch",
                height=ui.table_height(len(dupes), 300),
                column_config=ui.table_config(dupes),
            )

    st.subheader("Columns", anchor=False)
    st.dataframe(
        profiling.column_summary(df),
        hide_index=True,
        width="stretch",
        column_config={
            "column": "Column",
            "type": "Type",
            "missing": st.column_config.NumberColumn("Missing", format="localized"),
            "missing_pct": st.column_config.ProgressColumn(
                "Missing %", format="%.1f%%", min_value=0, max_value=100
            ),
            "unique": st.column_config.NumberColumn("Distinct values", format="localized"),
            "example": "Example",
        },
    )

    stats = profiling.numeric_summary(df)
    if not stats.empty:
        st.subheader("Numeric summary", anchor=False)
        st.dataframe(stats.round(2), hide_index=True, width="stretch")


# --------------------------------------------------------------------------
# Clean
# --------------------------------------------------------------------------
def render_clean(df: pd.DataFrame, record: database.DatasetRecord) -> None:
    key = f"ds{record.id}_clean"
    columns = list(df.columns)
    options_col, result_col = st.columns([2, 3], gap="large")

    with options_col:
        st.markdown("**Cleaning steps**")
        st.caption("Tick the steps to apply. They always run in the order shown.")

        to_drop = st.multiselect(
            "Drop columns", columns, key=f"{key}_drop", placeholder="None"
        )
        remaining = [c for c in columns if c not in to_drop]

        trim = st.checkbox(
            "Trim whitespace and standardise blanks",
            key=f"{key}_trim",
            help='Removes stray spaces from text and treats "", "N/A", "null" and similar as missing.',
        )
        dedupe = st.checkbox("Remove duplicate rows", key=f"{key}_dedupe")

        fill = st.checkbox("Fill missing values", key=f"{key}_fill")
        strategy, fill_columns, fill_value = None, [], None
        if fill:
            with st.container(border=True):
                strategy = st.selectbox(
                    "Fill with",
                    FILL_STRATEGIES,
                    index=FILL_STRATEGIES.index("median"),
                    key=f"{key}_strategy",
                    help="Mean and median apply to numeric columns only. "
                    "Mode uses the most common value and works for any column.",
                )
                with_missing = [c for c in remaining if df[c].isna().any()]
                fill_columns = st.multiselect(
                    "In columns",
                    with_missing,
                    key=f"{key}_fill_columns",
                    placeholder="All columns with missing values",
                )
                if strategy == "constant":
                    fill_value = st.text_input("Value to use", key=f"{key}_fill_value")

        drop_missing = st.checkbox("Remove rows with missing values", key=f"{key}_dropna")
        drop_missing_columns = []
        if drop_missing:
            with st.container(border=True):
                drop_missing_columns = st.multiselect(
                    "Only check these columns",
                    remaining,
                    key=f"{key}_dropna_columns",
                    placeholder="Any column",
                )

        snake = st.checkbox(
            "Rename columns to snake_case",
            key=f"{key}_snake",
            help='For example "Unit Price (ZAR)" becomes unit_price_zar, which is easier to use in SQL.',
        )

    options = CleaningOptions(
        drop_columns=to_drop,
        trim_whitespace=trim,
        drop_duplicates=dedupe,
        fill_strategy=strategy,
        fill_columns=fill_columns,
        fill_value=fill_value,
        drop_missing_rows=drop_missing,
        drop_missing_columns=drop_missing_columns,
        snake_case_columns=snake,
    )

    with result_col:
        st.markdown("**Result**")
        if not options.has_steps:
            st.info("Choose one or more cleaning steps to preview the result.", icon=":material/info:")
            return

        cleaned, report = clean_dataset(df, options)
        ui.kpi_row(
            [
                ui.change_kpi("Rows", report.rows_before, report.rows_after),
                ui.change_kpi("Columns", report.columns_before, report.columns_after),
                ui.change_kpi(
                    "Missing cells", report.missing_before, report.missing_after, lower_is_better=True
                ),
                ui.change_kpi(
                    "Duplicate rows",
                    report.duplicates_before,
                    report.duplicates_after,
                    lower_is_better=True,
                ),
            ]
        )
        st.caption("Change compared with the stored dataset is shown under each number.")
        for step in report.steps:
            st.markdown(f"- {step}")
        if cleaned.empty:
            st.warning(
                "These steps remove every row. Loosen the options before saving.",
                icon=":material/warning:",
            )

        st.dataframe(
            cleaned.head(200),
            hide_index=True,
            width="stretch",
            height=ui.table_height(min(len(cleaned), 200), 260),
            column_config=ui.table_config(cleaned),
        )
        if len(cleaned) > 200:
            st.caption(f"Preview of the first 200 of {ui.fmt_int(len(cleaned))} rows.")

        st.markdown("**Save the cleaned data**")
        mode = st.radio(
            "Where to save",
            ["As a new dataset", "Replace the current dataset"],
            key=f"{key}_mode",
            horizontal=True,
            label_visibility="collapsed",
        )
        new_name = None
        if mode == "As a new dataset":
            new_name = st.text_input(
                "New dataset name", value=f"{record.name} (cleaned)", key=f"{key}_name", max_chars=60
            ).strip()
            if new_name and new_name != record.name and database.get_dataset_by_name(new_name):
                st.warning(
                    f"'{new_name}' already exists and will be replaced.", icon=":material/warning:"
                )
        else:
            st.caption(f"'{record.name}' will be overwritten in the database. This cannot be undone.")

        save_col, download_col = st.columns(2)
        can_save = not cleaned.empty and cleaned.shape[1] > 0 and (new_name != "")
        if save_col.button(
            "Save to database",
            type="primary",
            icon=":material/save:",
            key=f"{key}_save",
            disabled=not can_save,
            width="stretch",
        ):
            saved = pipeline.save_cleaned(record, cleaned, report, new_name=new_name)
            ui.refresh_data(saved.id)
            ui.flash(f"Saved '{saved.name}' ({ui.plural(saved.row_count, 'row')})")
            st.rerun()
        download_col.download_button(
            "Download cleaned CSV",
            data=cleaned.to_csv(index=False).encode("utf-8"),
            file_name=f"{record.table_name.removeprefix('ds_')}_cleaned.csv",
            mime="text/csv",
            icon=":material/download:",
            key=f"{key}_download",
            width="stretch",
        )


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
ui.page_header(
    "Data View",
    "Upload a CSV, explore it in an interactive table, check its quality and clean it.",
    icon=":material/table_view:",
)

datasets = database.list_datasets()
render_loader(has_data=bool(datasets))

record = ui.get_active_dataset(datasets)
if record is None:
    st.info(
        "Upload a CSV or load the sample dataset above to get started.", icon=":material/info:"
    )
    st.stop()

df = ui.load_active_dataframe(record)
profile = profiling.profile_dataset(df)

st.subheader(record.name, anchor=False)
ui.kpi_row(
    [
        ui.Kpi("Rows", ui.fmt_int(profile.rows)),
        ui.Kpi(
            "Columns",
            ui.fmt_int(profile.columns),
            help=f"{profile.numeric_columns} numeric, {profile.text_columns} text, "
            f"{profile.datetime_columns} date",
        ),
        ui.Kpi(
            "Missing values",
            ui.fmt_int(profile.missing_cells),
            help=f"{ui.fmt_pct(profile.missing_pct)} of all cells are empty.",
        ),
        ui.Kpi(
            "Duplicate rows",
            ui.fmt_int(profile.duplicate_rows),
            help=f"{ui.fmt_pct(profile.duplicate_pct)} of rows repeat an earlier row exactly.",
        ),
    ]
)

explore_tab, quality_tab, clean_tab = st.tabs(
    [":material/search: Explore", ":material/fact_check: Data quality", ":material/cleaning_services: Clean"]
)
with explore_tab:
    render_explore(df, record)
with quality_tab:
    render_quality(df)
with clean_tab:
    render_clean(df, record)
