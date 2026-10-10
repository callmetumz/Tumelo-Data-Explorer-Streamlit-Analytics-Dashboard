"""Small text-formatting helpers shared by the data layer and the UI."""

from __future__ import annotations


def plural(count: int, noun: str) -> str:
    """``plural(1, "row")`` -> ``"1 row"``; ``plural(1230, "row")`` -> ``"1,230 rows"``."""
    return f"{int(count):,} {noun}{'' if count == 1 else 's'}"
