"""Data-quality summaries.

These functions only *describe* a DataFrame; they never change it. The
dashboard uses them for the KPI cards and the Data quality tab, and the
pipeline uses them to record statistics in the database catalog.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pandas.api import types as ptypes

NUMERIC = "numeric"
DATETIME = "datetime"
BOOLEAN = "boolean"
TEXT = "text"


def column_kind(series: pd.Series) -> str:
    """Classify a column as numeric, datetime, boolean or text."""
    if ptypes.is_bool_dtype(series):
        return BOOLEAN
    if ptypes.is_datetime64_any_dtype(series):
        return DATETIME
    if ptypes.is_numeric_dtype(series):
        return NUMERIC
    return TEXT


def columns_of_kind(df: pd.DataFrame, *kinds: str) -> list[str]:
    """Column names whose kind is one of ``kinds``, in their original order."""
    return [col for col in df.columns if column_kind(df[col]) in kinds]


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return columns_of_kind(df, NUMERIC)


def datetime_columns(df: pd.DataFrame) -> list[str]:
    return columns_of_kind(df, DATETIME)


def categorical_columns(df: pd.DataFrame) -> list[str]:
    """Columns that work as groups on a chart: text and boolean columns."""
    return columns_of_kind(df, TEXT, BOOLEAN)


@dataclass(frozen=True)
class DatasetProfile:
    """Headline numbers describing one dataset."""

    rows: int
    columns: int
    missing_cells: int
    duplicate_rows: int
    numeric_columns: int
    text_columns: int
    datetime_columns: int
    memory_bytes: int

    @property
    def total_cells(self) -> int:
        return self.rows * self.columns

    @property
    def missing_pct(self) -> float:
        return 100 * self.missing_cells / self.total_cells if self.total_cells else 0.0

    @property
    def completeness_pct(self) -> float:
        return 100 - self.missing_pct

    @property
    def duplicate_pct(self) -> float:
        return 100 * self.duplicate_rows / self.rows if self.rows else 0.0


def count_duplicate_rows(df: pd.DataFrame) -> int:
    """Number of rows that repeat an earlier row exactly."""
    return int(df.duplicated().sum())


def profile_dataset(df: pd.DataFrame) -> DatasetProfile:
    """Compute the headline quality numbers for a DataFrame."""
    kinds = [column_kind(df[col]) for col in df.columns]
    return DatasetProfile(
        rows=len(df),
        columns=df.shape[1],
        missing_cells=int(df.isna().sum().sum()),
        duplicate_rows=count_duplicate_rows(df),
        numeric_columns=kinds.count(NUMERIC),
        text_columns=kinds.count(TEXT) + kinds.count(BOOLEAN),
        datetime_columns=kinds.count(DATETIME),
        memory_bytes=int(df.memory_usage(deep=True).sum()),
    )


def column_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per column: type, missing values, distinct values, an example."""
    rows = []
    total = len(df)
    for col in df.columns:
        series = df[col]
        missing = int(series.isna().sum())
        non_null = series.dropna()
        rows.append(
            {
                "column": str(col),
                "type": column_kind(series),
                "missing": missing,
                "missing_pct": round(100 * missing / total, 2) if total else 0.0,
                "unique": int(non_null.nunique()),
                "example": str(non_null.iloc[0]) if len(non_null) else "",
            }
        )
    return pd.DataFrame(
        rows, columns=["column", "type", "missing", "missing_pct", "unique", "example"]
    )


def missing_by_column(df: pd.DataFrame, only_missing: bool = True) -> pd.DataFrame:
    """Missing-value count and percentage per column, worst first."""
    summary = column_summary(df)[["column", "type", "missing", "missing_pct"]]
    if only_missing:
        summary = summary[summary["missing"] > 0]
    return summary.sort_values("missing", ascending=False, kind="stable").reset_index(drop=True)


def duplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Every row that belongs to a group of identical rows, grouped together.

    Unlike :func:`count_duplicate_rows`, this includes the first occurrence so
    the user can see what is being repeated.
    """
    mask = df.duplicated(keep=False)
    dupes = df[mask]
    if dupes.empty:
        return dupes
    try:
        return dupes.sort_values(list(dupes.columns), kind="stable", na_position="last")
    except TypeError:  # a column mixes types that cannot be ordered
        return dupes


def numeric_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Descriptive statistics for the numeric columns (one row per column)."""
    cols = numeric_columns(df)
    if not cols:
        return pd.DataFrame()
    stats = df[cols].describe().T
    stats.insert(0, "column", stats.index.astype(str))
    return stats.reset_index(drop=True)
