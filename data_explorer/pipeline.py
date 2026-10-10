"""The data pipeline: source -> Python processing -> SQLite.

::

    CSV upload / sample data
            |
            v
    read_csv()            parse the file (delimiter and encoding are detected)
            |
            v
    prepare()             tidy headers, detect date columns
            |
            v
    profile_dataset()     count missing values and duplicates
            |
            v
    database.save_dataset()  +  database.log_run()
            |
            v
    Streamlit pages read the stored tables back out

The dashboard calls ``ingest_csv`` / ``ingest_dataframe`` / ``save_cleaned``
and never touches pandas parsing or SQL directly.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from . import database
from .cleaning import (
    CleaningOptions,
    CleaningReport,
    clean_dataset,
    infer_datetime_columns,
    tidy_column_names,
)
from .database import DatasetRecord
from .profiling import profile_dataset
from .sample_data import SAMPLE_NAME, make_sample_dataset
from .text import plural

ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


class PipelineError(Exception):
    """Raised when a file cannot be turned into a usable dataset."""


def read_csv(source: bytes | str | Path | BinaryIO) -> pd.DataFrame:
    """Parse a CSV file into a DataFrame.

    Accepts raw bytes, a path or a file-like object (such as a Streamlit
    upload). The delimiter (comma, semicolon, tab...) is detected
    automatically and common encodings are tried in turn.
    """
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    elif isinstance(source, bytes):
        raw = source
    else:
        raw = source.read()
    if not raw or not raw.strip():
        raise PipelineError("The file is empty.")

    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
            raise PipelineError(f"Could not read the file as CSV: {exc}") from exc
        if df.shape[1] == 0:
            raise PipelineError("No columns were found in the file.")
        return df
    raise PipelineError(f"Could not decode the file: {last_error}")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Standard preparation applied to every dataset before it is stored.

    Only safe, lossless steps run here: header tidy-up and date detection.
    Anything that removes or changes values is left to the user on the
    Clean tab.
    """
    return infer_datetime_columns(tidy_column_names(df))


def ingest_dataframe(
    df: pd.DataFrame, name: str, source: str, db_path: str | Path | None = None
) -> DatasetRecord:
    """Prepare a DataFrame, store it in SQLite and log the run."""
    prepared = prepare(df)
    profile = profile_dataset(prepared)
    replaced = database.get_dataset_by_name(name, db_path) is not None
    record = database.save_dataset(
        prepared,
        name=name,
        source=source,
        missing_cells=profile.missing_cells,
        duplicate_rows=profile.duplicate_rows,
        db_path=db_path,
    )
    database.log_run(
        dataset_name=record.name,
        action="ingest",
        rows_in=len(df),
        rows_out=record.row_count,
        details=f"{'Replaced' if replaced else 'Loaded'} from {source}: "
        f"{plural(record.column_count, 'column')}, "
        f"{plural(profile.missing_cells, 'missing cell')}, "
        f"{plural(profile.duplicate_rows, 'duplicate row')}",
        db_path=db_path,
    )
    return record


def ingest_csv(
    source: bytes | str | Path | BinaryIO,
    name: str,
    filename: str | None = None,
    db_path: str | Path | None = None,
) -> DatasetRecord:
    """Run the whole pipeline for one CSV file."""
    df = read_csv(source)
    label = filename or (Path(source).name if isinstance(source, (str, Path)) else "upload")
    return ingest_dataframe(df, name=name, source=label, db_path=db_path)


def ingest_sample(db_path: str | Path | None = None) -> DatasetRecord:
    """Load the built-in demo dataset through the same pipeline as an upload."""
    return ingest_dataframe(
        make_sample_dataset(), name=SAMPLE_NAME, source="built-in sample", db_path=db_path
    )


def save_cleaned(
    record: DatasetRecord,
    cleaned: pd.DataFrame,
    report: CleaningReport,
    new_name: str | None = None,
    db_path: str | Path | None = None,
) -> DatasetRecord:
    """Store a cleaned dataset, either over the original or under a new name."""
    target = (new_name or record.name).strip()
    profile = profile_dataset(cleaned)
    saved = database.save_dataset(
        cleaned,
        name=target,
        source=record.source if target == record.name else f"cleaned from {record.name}",
        missing_cells=profile.missing_cells,
        duplicate_rows=profile.duplicate_rows,
        db_path=db_path,
    )
    database.log_run(
        dataset_name=saved.name,
        action="clean",
        rows_in=report.rows_before,
        rows_out=report.rows_after,
        details=report.summary(),
        db_path=db_path,
    )
    return saved


def clean_and_save(
    record: DatasetRecord,
    options: CleaningOptions,
    new_name: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[DatasetRecord, CleaningReport]:
    """Load a stored dataset, clean it and save the result in one call."""
    df = database.load_dataset(record.id, db_path)
    cleaned, report = clean_dataset(df, options)
    return save_cleaned(record, cleaned, report, new_name, db_path), report


def remove_dataset(record: DatasetRecord, db_path: str | Path | None = None) -> None:
    """Delete a dataset and note it in the pipeline log."""
    database.delete_dataset(record.id, db_path)
    database.log_run(
        dataset_name=record.name,
        action="delete",
        rows_in=record.row_count,
        rows_out=0,
        details="Dataset deleted",
        db_path=db_path,
    )
