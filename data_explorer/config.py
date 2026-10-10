"""Paths and limits shared across the data layer."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Environment variable that overrides where the SQLite file lives.
DB_ENV_VAR = "DATA_EXPLORER_DB"

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "explorer.db"

#: Most rows the SQL page will fetch for one query.
MAX_QUERY_ROWS = 5_000

#: Seconds a user-written SQL query may run before it is cancelled.
QUERY_TIMEOUT_SECONDS = 10

#: Scatter plots are sampled down to this many points so the browser stays fast.
MAX_SCATTER_POINTS = 5_000


def get_db_path() -> Path:
    """Return the SQLite file path, honouring the ``DATA_EXPLORER_DB`` override."""
    override = os.environ.get(DB_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_DB_PATH
