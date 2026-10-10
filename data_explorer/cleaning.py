"""Reusable data-cleaning functions.

Every function takes a DataFrame and returns a *new* DataFrame; the input is
never modified. That makes each step safe to preview, test and combine.

``clean_dataset`` runs a chosen set of steps in a fixed order and returns a
report of what each step did, so the UI can show a before/after comparison
without knowing anything about how the cleaning works.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from .profiling import NUMERIC, TEXT, column_kind, count_duplicate_rows
from .text import plural

FILL_STRATEGIES = ("mean", "median", "mode", "constant", "forward fill")

#: Text values that mean "no value" once whitespace is trimmed.
BLANK_MARKERS = {"", "na", "n/a", "nan", "null", "none", "-", "?"}


# --------------------------------------------------------------------------
# Column names
# --------------------------------------------------------------------------
def _make_unique(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        if name in seen:
            seen[name] += 1
            candidate = f"{name}_{seen[name]}"
            while candidate in seen:
                seen[name] += 1
                candidate = f"{name}_{seen[name]}"
            seen[candidate] = 1
            unique.append(candidate)
        else:
            seen[name] = 1
            unique.append(name)
    return unique


def tidy_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from headers, name blank ones and make them unique.

    This is the minimum needed to store a table in SQL, so the pipeline
    applies it to every dataset on the way in.
    """
    names = []
    for position, col in enumerate(df.columns, start=1):
        name = re.sub(r"\s+", " ", str(col)).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{position}"
        names.append(name)
    out = df.copy()
    out.columns = _make_unique(names)
    return out


def to_snake_case(name: str) -> str:
    """``"Unit Price (ZAR)"`` -> ``"unit_price_zar"``."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return name or "column"


def snake_case_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename every column to snake_case, which is easier to use in SQL."""
    out = df.copy()
    out.columns = _make_unique(to_snake_case(col) for col in df.columns)
    return out


def drop_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Remove the named columns (names that do not exist are ignored)."""
    present = [col for col in columns if col in df.columns]
    return df.drop(columns=present)


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------
def trim_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """Trim text values and turn blank markers ("", "N/A", "null"...) into missing.

    Leading/trailing spaces and repeated internal spaces are removed, so
    ``" Western  Cape "`` and ``"Western Cape"`` become the same value.
    """
    out = df.copy()
    for col in out.columns:
        if column_kind(out[col]) != TEXT:
            continue
        series = out[col]
        is_text = series.map(lambda value: isinstance(value, str))
        if not is_text.any():
            continue
        cleaned = series.where(~is_text, series.astype("string").str.replace(r"\s+", " ", regex=True).str.strip())
        blank = is_text & cleaned.astype("string").str.lower().isin(BLANK_MARKERS)
        out[col] = cleaned.mask(blank, pd.NA).astype(series.dtype)
    return out


def infer_datetime_columns(df: pd.DataFrame, threshold: float = 0.9) -> pd.DataFrame:
    """Convert text columns that hold dates into real datetime columns.

    A column is converted only if at least ``threshold`` of its non-missing
    values parse as dates in one consistent format.
    """
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if column_kind(series) != TEXT:
            continue
        non_null = series.dropna()
        if non_null.empty or not non_null.map(lambda v: isinstance(v, str)).all():
            continue
        # Plain numbers stored as text ("2024", "12.5") are not dates.
        if pd.to_numeric(non_null.head(200), errors="coerce").notna().all():
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                sample = pd.to_datetime(non_null.head(200), errors="coerce")
                if sample.notna().mean() < threshold:
                    continue
                parsed = pd.to_datetime(series, errors="coerce")
            except (ValueError, TypeError, OverflowError):
                continue
        if parsed.notna().sum() / len(non_null) >= threshold:
            out[col] = parsed
    return out


def drop_duplicate_rows(df: pd.DataFrame, subset: list[str] | None = None) -> pd.DataFrame:
    """Remove repeated rows, keeping the first occurrence."""
    return df.drop_duplicates(subset=subset or None, keep="first").reset_index(drop=True)


def drop_missing_rows(
    df: pd.DataFrame, columns: list[str] | None = None, how: str = "any"
) -> pd.DataFrame:
    """Remove rows with missing values.

    ``columns`` limits the check to those columns. ``how="any"`` drops a row
    if any checked value is missing; ``how="all"`` only if all of them are.
    """
    subset = [col for col in (columns or []) if col in df.columns] or None
    return df.dropna(subset=subset, how=how).reset_index(drop=True)


def fill_missing(
    df: pd.DataFrame,
    strategy: str = "median",
    columns: list[str] | None = None,
    value: Any = None,
) -> pd.DataFrame:
    """Fill missing values.

    Strategies: ``mean`` and ``median`` (numeric columns only), ``mode`` (most
    common value), ``constant`` (use ``value``) and ``forward fill`` (carry the
    previous row's value down). Columns a strategy cannot apply to are left
    untouched.
    """
    if strategy not in FILL_STRATEGIES:
        raise ValueError(f"Unknown fill strategy {strategy!r}. Choose from {FILL_STRATEGIES}.")
    targets = [col for col in (columns or df.columns) if col in df.columns]
    out = df.copy()
    for col in targets:
        series = out[col]
        if not series.isna().any():
            continue
        kind = column_kind(series)
        if strategy in ("mean", "median"):
            if kind != NUMERIC or series.dropna().empty:
                continue
            fill = series.mean() if strategy == "mean" else series.median()
            if pd.api.types.is_integer_dtype(series):
                fill = round(fill)
            out[col] = series.fillna(fill)
        elif strategy == "mode":
            modes = series.mode(dropna=True)
            if not modes.empty:
                out[col] = series.fillna(modes.iloc[0])
        elif strategy == "constant":
            fill = _coerce_constant(value, kind)
            if fill is not None:
                out[col] = series.fillna(fill)
        else:  # forward fill
            out[col] = series.ffill()
    return out


def _coerce_constant(value: Any, kind: str) -> Any:
    """Make a user-typed fill value match the column's type, or return None."""
    if value is None or (isinstance(value, str) and value == ""):
        return None
    if kind == NUMERIC:
        number = pd.to_numeric(value, errors="coerce")
        return None if pd.isna(number) else number
    if kind == TEXT:
        return str(value)
    return None


# --------------------------------------------------------------------------
# Running several steps together
# --------------------------------------------------------------------------
@dataclass
class CleaningOptions:
    """Which cleaning steps to run. The defaults change nothing."""

    drop_columns: list[str] = field(default_factory=list)
    trim_whitespace: bool = False
    drop_duplicates: bool = False
    fill_strategy: str | None = None
    fill_columns: list[str] = field(default_factory=list)
    fill_value: Any = None
    drop_missing_rows: bool = False
    drop_missing_columns: list[str] = field(default_factory=list)
    snake_case_columns: bool = False

    @property
    def has_steps(self) -> bool:
        return bool(
            self.drop_columns
            or self.trim_whitespace
            or self.drop_duplicates
            or self.fill_strategy
            or self.drop_missing_rows
            or self.snake_case_columns
        )


@dataclass
class CleaningReport:
    """What a cleaning run did, in numbers and in words."""

    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    missing_before: int
    missing_after: int
    duplicates_before: int
    duplicates_after: int
    steps: list[str] = field(default_factory=list)

    @property
    def rows_removed(self) -> int:
        return self.rows_before - self.rows_after

    @property
    def changed(self) -> bool:
        return bool(self.steps)

    def summary(self) -> str:
        return "; ".join(self.steps) if self.steps else "No changes"


def _cells_changed(before: pd.DataFrame, after: pd.DataFrame) -> int:
    """Count cells whose value differs between two same-shaped frames."""
    total = 0
    for col in before.columns:
        old = before[col].astype("string").fillna("\x00")
        new = after[col].astype("string").fillna("\x00")
        total += int((old != new).sum())
    return total


def _missing(df: pd.DataFrame) -> int:
    return int(df.isna().sum().sum())


def clean_dataset(df: pd.DataFrame, options: CleaningOptions) -> tuple[pd.DataFrame, CleaningReport]:
    """Run the selected cleaning steps and report what changed.

    Steps always run in this order, so the result does not depend on the order
    options were ticked in the UI:

    1. drop columns
    2. trim whitespace / standardise blanks
    3. drop duplicate rows
    4. fill missing values
    5. drop rows that still have missing values
    6. rename columns to snake_case
    """
    steps: list[str] = []
    out = df

    if options.drop_columns:
        removed = [col for col in options.drop_columns if col in out.columns]
        out = drop_columns(out, removed)
        if removed:
            steps.append(f"Dropped {plural(len(removed), 'column')}: {', '.join(map(str, removed))}")

    if options.trim_whitespace:
        before = out
        out = trim_whitespace(out)
        changed = _cells_changed(before, out)
        steps.append(f"Trimmed whitespace and standardised blanks ({plural(changed, 'cell')} changed)")

    if options.drop_duplicates:
        before_rows = len(out)
        out = drop_duplicate_rows(out)
        steps.append(f"Removed {plural(before_rows - len(out), 'duplicate row')}")

    if options.fill_strategy:
        before_missing = _missing(out)
        out = fill_missing(
            out,
            strategy=options.fill_strategy,
            columns=options.fill_columns or None,
            value=options.fill_value,
        )
        steps.append(
            f"Filled {plural(before_missing - _missing(out), 'missing value')} "
            f"using {options.fill_strategy}"
        )

    if options.drop_missing_rows:
        before_rows = len(out)
        out = drop_missing_rows(out, columns=options.drop_missing_columns or None)
        steps.append(f"Removed {plural(before_rows - len(out), 'row')} with missing values")

    if options.snake_case_columns:
        renamed = snake_case_columns(out)
        count = sum(old != new for old, new in zip(out.columns, renamed.columns))
        out = renamed
        if count:
            steps.append(f"Renamed {plural(count, 'column')} to snake_case")

    report = CleaningReport(
        rows_before=len(df),
        rows_after=len(out),
        columns_before=df.shape[1],
        columns_after=out.shape[1],
        missing_before=_missing(df),
        missing_after=_missing(out),
        duplicates_before=count_duplicate_rows(df),
        duplicates_after=count_duplicate_rows(out),
        steps=steps,
    )
    return out, report
