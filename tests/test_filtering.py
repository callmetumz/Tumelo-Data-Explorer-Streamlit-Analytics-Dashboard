import pandas as pd

from data_explorer.filtering import (
    RangeFilter,
    TextFilter,
    ValuesFilter,
    apply_filters,
    search_rows,
)


def test_range_filter_on_numbers(messy):
    out = apply_filters(messy, [RangeFilter("Units", 2, 3)])
    assert out["Units"].tolist() == [2, 2, 3]
    with_missing = apply_filters(messy, [RangeFilter("Units", 2, 3, keep_missing=True)])
    assert len(with_missing) == 4


def test_range_filter_on_dates():
    df = pd.DataFrame({"d": pd.to_datetime(["2025-01-01", "2025-02-01", None])})
    out = apply_filters(df, [RangeFilter("d", pd.Timestamp("2025-01-15"), None)])
    assert len(out) == 1


def test_values_and_text_filters(messy):
    assert len(apply_filters(messy, [ValuesFilter("Region", ("Gauteng",))])) == 1
    assert len(apply_filters(messy, [ValuesFilter("Region", (), keep_missing=True)])) == 1
    assert len(apply_filters(messy, [TextFilter("Region", "gauteng")])) == 2
    assert len(apply_filters(messy, [TextFilter("Region", "gauteng", case_sensitive=True)])) == 0


def test_filters_combine_and_ignore_unknown_columns(messy):
    filters = [RangeFilter("Units", 1, 5), TextFilter("Order ID", "A2"), ValuesFilter("nope", (1,))]
    assert len(apply_filters(messy, filters)) == 2
    assert len(apply_filters(messy, [])) == len(messy)


def test_search_rows_looks_in_every_column(messy):
    assert len(search_rows(messy, "cape")) == 2
    assert len(search_rows(messy, "2025-02")) == 2
    assert len(search_rows(messy, "  ")) == len(messy)
