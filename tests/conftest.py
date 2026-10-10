"""Shared fixtures. Every test gets its own throwaway SQLite file."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_explorer import config  # noqa: E402


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv(config.DB_ENV_VAR, str(path))
    return path


@pytest.fixture
def messy():
    """A small frame with every problem the cleaning tools handle."""
    return pd.DataFrame(
        {
            "Order ID": ["A1", "A2", "A2", "A3", "A4", "A5"],
            "Region": [" Gauteng ", "Western  Cape", "Western  Cape", "N/A", None, "Gauteng"],
            "Units": [1, 2, 2, 3, None, 10],
            "Price": [10.0, None, None, 30.0, 40.0, 50.0],
            "Order Date": ["2025-01-05", "2025-01-06", "2025-01-06", "2025-02-01", "2025-02-02", None],
        }
    )
