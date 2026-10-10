import pandas as pd
import pytest

from data_explorer import cleaning
from data_explorer.cleaning import CleaningOptions, clean_dataset


def test_tidy_column_names_fixes_blank_and_repeated_headers():
    df = pd.DataFrame([[1, 2, 3, 4]], columns=[" Name ", "Name", "", "Unnamed: 3"])
    assert list(cleaning.tidy_column_names(df).columns) == ["Name", "Name_2", "column_3", "column_4"]


@pytest.mark.parametrize(
    "raw, expected",
    [("Unit Price (ZAR)", "unit_price_zar"), ("orderDate", "order_date"), ("  %  ", "column")],
)
def test_to_snake_case(raw, expected):
    assert cleaning.to_snake_case(raw) == expected


def test_trim_whitespace_cleans_text_and_marks_blanks_missing(messy):
    out = cleaning.trim_whitespace(messy)
    assert out["Region"].tolist()[:3] == ["Gauteng", "Western Cape", "Western Cape"]
    assert out["Region"].isna().sum() == 2  # "N/A" and the original None
    assert messy["Region"].iloc[0] == " Gauteng "  # input is not modified


def test_drop_duplicate_rows(messy):
    out = cleaning.drop_duplicate_rows(messy)
    assert len(out) == 5
    assert out["Order ID"].is_unique


def test_drop_missing_rows_can_be_limited_to_columns(messy):
    assert len(cleaning.drop_missing_rows(messy)) == 2
    assert len(cleaning.drop_missing_rows(messy, columns=["Units"])) == 5


def test_fill_missing_median_only_touches_numeric_columns(messy):
    out = cleaning.fill_missing(messy, strategy="median")
    assert out["Price"].isna().sum() == 0
    assert out["Price"].iloc[1] == messy["Price"].median()
    assert out["Region"].isna().sum() == 1  # text column left alone


def test_fill_missing_mode_and_constant(messy):
    mode = cleaning.fill_missing(messy, strategy="mode", columns=["Region"])
    assert mode["Region"].iloc[4] == "Western  Cape"
    constant = cleaning.fill_missing(messy, strategy="constant", columns=["Price"], value="0")
    assert constant["Price"].iloc[1] == 0
    # A non-numeric constant cannot go into a numeric column, so nothing changes.
    ignored = cleaning.fill_missing(messy, strategy="constant", columns=["Price"], value="abc")
    assert ignored["Price"].isna().sum() == 2


def test_fill_missing_rejects_unknown_strategy(messy):
    with pytest.raises(ValueError):
        cleaning.fill_missing(messy, strategy="magic")


def test_infer_datetime_columns_converts_dates_but_not_text_or_numbers(messy):
    df = messy.assign(code=["1", "2", "3", "4", "5", "6"])
    out = cleaning.infer_datetime_columns(df)
    assert pd.api.types.is_datetime64_any_dtype(out["Order Date"])
    assert not pd.api.types.is_datetime64_any_dtype(out["Region"])
    assert not pd.api.types.is_datetime64_any_dtype(out["code"])


def test_clean_dataset_with_no_options_changes_nothing(messy):
    out, report = clean_dataset(messy, CleaningOptions())
    assert out.equals(messy)
    assert not report.changed
    assert report.summary() == "No changes"


def test_clean_dataset_runs_steps_and_reports(messy):
    options = CleaningOptions(
        drop_columns=["Order Date"],
        trim_whitespace=True,
        drop_duplicates=True,
        fill_strategy="median",
        drop_missing_rows=True,
        snake_case_columns=True,
    )
    out, report = clean_dataset(messy, options)

    assert list(out.columns) == ["order_id", "region", "units", "price"]
    assert out.isna().sum().sum() == 0
    assert report.rows_before == 6 and report.rows_after == len(out) == 3
    assert report.columns_after == 4
    assert report.duplicates_before == 1 and report.duplicates_after == 0
    assert report.missing_after == 0
    assert len(report.steps) == 6
    assert "Removed 1 duplicate row" in report.summary()
