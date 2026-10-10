import pandas as pd
import pytest

from data_explorer import database, pipeline
from data_explorer.cleaning import CleaningOptions
from data_explorer.sample_data import SAMPLE_NAME, make_sample_dataset, sample_csv_bytes


def test_read_csv_detects_delimiters_and_encodings():
    assert pipeline.read_csv(b"a,b\n1,x\n").shape == (1, 2)
    assert pipeline.read_csv(b"a;b\n1;x\n2;y\n").shape == (2, 2)
    assert pipeline.read_csv("a\tb\n1\tx\n".encode()).shape == (1, 2)
    latin = "name,city\nZo\xeb,Durban\n".encode("latin-1")
    assert pipeline.read_csv(latin)["name"].iloc[0] == "Zo\xeb"


def test_read_csv_rejects_empty_files():
    with pytest.raises(pipeline.PipelineError):
        pipeline.read_csv(b"   \n")


def test_sample_dataset_is_reproducible_and_messy():
    df = make_sample_dataset()
    assert df.equals(make_sample_dataset())
    assert df.isna().sum().sum() > 0
    assert df.duplicated().sum() == 30


def test_ingest_csv_runs_the_whole_pipeline(db_path):
    record = pipeline.ingest_csv(sample_csv_bytes(), name="Sales", filename="sales.csv")

    assert record.row_count == 1230
    assert record.duplicate_rows == 30
    assert record.column_types["order_date"] == "datetime"
    assert record.source == "sales.csv"

    stored = database.load_dataset(record.id)
    assert pd.api.types.is_datetime64_any_dtype(stored["order_date"])

    runs = database.recent_runs()
    assert runs["action"].tolist() == ["ingest"]
    assert runs["rows_in"].iloc[0] == 1230


def test_clean_and_save_as_new_dataset_keeps_the_original(db_path):
    original = pipeline.ingest_sample()
    options = CleaningOptions(trim_whitespace=True, drop_duplicates=True)
    saved, report = pipeline.clean_and_save(original, options, new_name="Sales clean")

    assert saved.id != original.id
    assert saved.duplicate_rows == 0
    assert saved.row_count == 1200
    assert report.rows_removed == 30
    assert {d.name for d in database.list_datasets()} == {SAMPLE_NAME, "Sales clean"}

    kpis = database.get_kpis()
    assert kpis["records_processed"] == 2460
    assert kpis["cleaning_runs"] == 1
    assert kpis["rows_removed_by_cleaning"] == 30


def test_clean_and_save_can_replace_the_original(db_path):
    original = pipeline.ingest_sample()
    saved, _ = pipeline.clean_and_save(original, CleaningOptions(drop_duplicates=True))
    assert saved.id == original.id
    assert len(database.list_datasets()) == 1
    assert database.get_dataset(original.id).row_count == 1200


def test_remove_dataset_is_logged(db_path):
    record = pipeline.ingest_sample()
    pipeline.remove_dataset(record)
    assert database.list_datasets() == []
    assert database.recent_runs()["action"].tolist() == ["delete", "ingest"]
    # Deleting data does not shrink the "records processed" total.
    assert database.get_kpis()["records_processed"] == 1230
