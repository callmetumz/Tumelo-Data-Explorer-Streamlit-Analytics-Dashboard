"""Shared Streamlit building blocks.

Everything that touches ``st`` and is used by more than one page lives here:
the page header, KPI cards, the sidebar dataset picker and cached access to
the active dataset. Pages import from this module instead of repeating the
same widget code.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from data_explorer import config, database, pipeline
from data_explorer.database import DatasetRecord
from data_explorer.text import plural  # noqa: F401  (re-exported for the pages)

ACTIVE_KEY = "active_dataset_id"
FLASH_KEY = "flash_message"

# Paths used by st.navigation and st.page_link.
PAGE_HOME = "views/home.py"
PAGE_DATA = "views/data_view.py"
PAGE_PLOT = "views/plots.py"
PAGE_SQL = "views/sql_lab.py"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def table_height(rows: int, max_height: int = 480) -> int:
    """Pixel height that fits a short table exactly and caps a long one."""
    return min(max_height, 38 + 35 * max(rows, 1))


def fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%"


def fmt_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def is_dark_theme() -> bool:
    """True when the viewer is using Streamlit's dark theme."""
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def flash(message: str, icon: str = ":material/check_circle:") -> None:
    """Queue a message to show after the next rerun."""
    st.session_state[FLASH_KEY] = (message, icon)


def show_flash() -> None:
    queued = st.session_state.pop(FLASH_KEY, None)
    if queued:
        st.toast(queued[0], icon=queued[1])


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
def page_header(title: str, subtitle: str, icon: str | None = None) -> None:
    """Consistent title block at the top of every page."""
    st.title(f"{icon} {title}" if icon else title, anchor=False)
    st.caption(subtitle)


@dataclass
class Kpi:
    label: str
    value: str
    help: str | None = None
    delta: str | None = None
    delta_color: str = "off"
    delta_arrow: str = "auto"


def change_kpi(label: str, before: int, after: int, lower_is_better: bool = False) -> Kpi:
    """A KPI card showing a value and how it changed from ``before``."""
    change = after - before
    if change == 0:
        return Kpi(label, fmt_int(after), delta="no change", delta_arrow="off")
    return Kpi(
        label,
        fmt_int(after),
        delta=f"{change:+,}",
        delta_color="inverse" if lower_is_better else "off",
    )


def table_config(df: pd.DataFrame) -> dict:
    """Column display settings: show date-only columns without a time part."""
    settings = {}
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            values = series.dropna()
            if values.empty or (values == values.dt.normalize()).all():
                settings[column] = st.column_config.DateColumn(format="YYYY-MM-DD")
    return settings


def kpi_row(items: list[Kpi]) -> None:
    """A row of bordered KPI cards."""
    for column, item in zip(st.columns(len(items)), items):
        column.metric(
            item.label,
            item.value,
            delta=item.delta,
            delta_color=item.delta_color,
            delta_arrow=item.delta_arrow,
            help=item.help,
            border=True,
        )


def empty_state(on_page: str = "") -> None:
    """Shown when the database has no datasets yet."""
    with st.container(border=True):
        st.subheader("No data loaded yet", anchor=False)
        st.write(
            "Load the built-in sample dataset to try everything straight away, "
            "or upload your own CSV file on the Data View page."
        )
        left, right, _ = st.columns([1, 1, 2])
        if left.button(
            "Load sample dataset",
            type="primary",
            icon=":material/dataset:",
            key=f"load_sample_{on_page}",
            width="stretch",
        ):
            load_sample()
        if on_page != "data":
            right.page_link(PAGE_DATA, label="Upload a CSV", icon=":material/upload_file:")


def load_sample() -> None:
    record = pipeline.ingest_sample()
    refresh_data(record.id)
    flash(f"Loaded '{record.name}' ({plural(record.row_count, 'row')}) into the database")
    st.rerun()


# --------------------------------------------------------------------------
# Active dataset
# --------------------------------------------------------------------------
def refresh_data(active_id: int | None = None) -> None:
    """Call after any database write so pages pick up the new state."""
    load_dataframe.clear()
    if active_id is not None:
        st.session_state[ACTIVE_KEY] = active_id


@st.cache_data(show_spinner="Loading dataset from the database...")
def load_dataframe(dataset_id: int, updated_at: str, db_path: str) -> pd.DataFrame:
    """Read a dataset out of SQLite. Cached until the dataset changes."""
    return database.load_dataset(dataset_id, db_path)


def get_active_dataset(datasets: list[DatasetRecord] | None = None) -> DatasetRecord | None:
    """The dataset chosen in the sidebar (falls back to the newest one)."""
    datasets = database.list_datasets() if datasets is None else datasets
    if not datasets:
        st.session_state.pop(ACTIVE_KEY, None)
        return None
    by_id = {record.id: record for record in datasets}
    active_id = st.session_state.get(ACTIVE_KEY)
    if active_id not in by_id:
        active_id = datasets[0].id
        st.session_state[ACTIVE_KEY] = active_id
    return by_id[active_id]


def load_active_dataframe(record: DatasetRecord) -> pd.DataFrame:
    return load_dataframe(record.id, record.updated_at, str(config.get_db_path()))


def dataset_sidebar() -> None:
    """Dataset picker shown in the sidebar on every page."""
    datasets = database.list_datasets()
    with st.sidebar:
        if not datasets:
            st.caption("No datasets in the database yet.")
        else:
            active = get_active_dataset(datasets)
            ids = [record.id for record in datasets]
            names = {record.id: record.name for record in datasets}
            chosen = st.selectbox(
                "Active dataset",
                ids,
                index=ids.index(active.id),
                format_func=lambda dataset_id: names[dataset_id],
                help="The dataset every page works with. Stored in the SQLite database.",
            )
            if chosen != active.id:
                st.session_state[ACTIVE_KEY] = chosen
                st.rerun()
            st.caption(
                f"{plural(active.row_count, 'row')} · {plural(active.column_count, 'column')} · "
                f"{fmt_pct(active.completeness_pct)} complete"
            )
        st.divider()
        st.caption("Made by Tumelo ❤️")
