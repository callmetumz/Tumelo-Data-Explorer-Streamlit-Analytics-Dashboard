"""Row filters.

A filter is a small, immutable description of a condition ("revenue between
100 and 500"). The UI builds these objects from widgets and ``apply_filters``
turns them into a filtered DataFrame, so the filtering rules live in one place
and can be tested without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Union

import pandas as pd


@dataclass(frozen=True)
class RangeFilter:
    """Keep rows where a numeric or datetime column is within [low, high]."""

    column: str
    low: Any = None
    high: Any = None
    keep_missing: bool = False

    def mask(self, df: pd.DataFrame) -> pd.Series:
        series = df[self.column]
        mask = pd.Series(True, index=df.index)
        if self.low is not None:
            mask &= series >= self.low
        if self.high is not None:
            mask &= series <= self.high
        mask = mask.fillna(False).astype(bool)
        if self.keep_missing:
            mask |= series.isna()
        return mask


@dataclass(frozen=True)
class ValuesFilter:
    """Keep rows where a column's value is one of ``values``."""

    column: str
    values: tuple
    keep_missing: bool = False

    def mask(self, df: pd.DataFrame) -> pd.Series:
        series = df[self.column]
        mask = series.isin(list(self.values))
        if self.keep_missing:
            mask |= series.isna()
        return mask


@dataclass(frozen=True)
class TextFilter:
    """Keep rows where a column contains ``text`` (case-insensitive by default)."""

    column: str
    text: str
    case_sensitive: bool = False

    def mask(self, df: pd.DataFrame) -> pd.Series:
        if not self.text:
            return pd.Series(True, index=df.index)
        as_text = df[self.column].astype("string")
        return as_text.str.contains(self.text, case=self.case_sensitive, regex=False).fillna(False).astype(bool)


Filter = Union[RangeFilter, ValuesFilter, TextFilter]


def apply_filters(df: pd.DataFrame, filters: Iterable[Filter]) -> pd.DataFrame:
    """Return the rows that satisfy every filter. Unknown columns are skipped."""
    mask = pd.Series(True, index=df.index)
    for flt in filters:
        if flt.column in df.columns:
            mask &= flt.mask(df)
    return df[mask]


def search_rows(df: pd.DataFrame, text: str) -> pd.DataFrame:
    """Keep rows where any column contains ``text`` (case-insensitive)."""
    text = (text or "").strip()
    if not text:
        return df
    mask = pd.Series(False, index=df.index)
    for col in df.columns:
        as_text = df[col].astype("string")
        mask |= as_text.str.contains(text, case=False, regex=False).fillna(False).astype(bool)
    return df[mask]
