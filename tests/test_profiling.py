import pandas as pd

from data_explorer import profiling


def test_column_kind():
    df = pd.DataFrame(
        {
            "n": [1.5, 2.0],
            "t": ["a", "b"],
            "b": [True, False],
            "d": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        }
    )
    kinds = {col: profiling.column_kind(df[col]) for col in df.columns}
    assert kinds == {"n": "numeric", "t": "text", "b": "boolean", "d": "datetime"}
    assert profiling.numeric_columns(df) == ["n"]
    assert profiling.categorical_columns(df) == ["t", "b"]


def test_profile_dataset(messy):
    profile = profiling.profile_dataset(messy)
    assert (profile.rows, profile.columns) == (6, 5)
    assert profile.missing_cells == 5
    assert profile.duplicate_rows == 1
    assert round(profile.missing_pct, 2) == round(100 * 5 / 30, 2)
    assert profile.completeness_pct + profile.missing_pct == 100


def test_profile_of_empty_frame_does_not_divide_by_zero():
    profile = profiling.profile_dataset(pd.DataFrame({"a": []}))
    assert profile.missing_pct == 0
    assert profile.duplicate_pct == 0


def test_missing_by_column_is_sorted_and_skips_complete_columns(messy):
    summary = profiling.missing_by_column(messy)
    assert summary["column"].tolist()[0] == "Price"
    assert "Order ID" not in summary["column"].tolist()
    assert len(profiling.missing_by_column(messy, only_missing=False)) == 5


def test_duplicate_rows_returns_every_copy(messy):
    dupes = profiling.duplicate_rows(messy)
    assert len(dupes) == 2
    assert set(dupes["Order ID"]) == {"A2"}
    assert profiling.duplicate_rows(messy.drop_duplicates()).empty


def test_column_summary_and_numeric_summary(messy):
    summary = profiling.column_summary(messy).set_index("column")
    assert summary.loc["Units", "type"] == "numeric"
    assert summary.loc["Region", "unique"] == 4  # untidy spellings count separately
    stats = profiling.numeric_summary(messy)
    assert set(stats["column"]) == {"Units", "Price"}
