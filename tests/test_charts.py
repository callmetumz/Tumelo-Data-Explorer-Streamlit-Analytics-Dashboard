import pandas as pd
import pytest

from data_explorer import charts, cleaning, profiling
from data_explorer.sample_data import make_sample_dataset


@pytest.fixture(scope="module")
def sales():
    return cleaning.infer_datetime_columns(make_sample_dataset())


def test_line_chart_groups_dates_by_month(sales):
    result = charts.line_chart(sales, "order_date", ["revenue"], aggregate="sum", date_grouping="Month")
    assert len(result.data) == 12
    assert result.data["revenue"].sum() == pytest.approx(sales["revenue"].sum())
    assert len(result.figure.data) == 1


def test_line_chart_supports_several_series_and_splitting(sales):
    two = charts.line_chart(sales, "order_date", ["revenue", "units"], date_grouping="Quarter")
    assert len(two.figure.data) == 2
    split = charts.line_chart(sales, "order_date", ["revenue"], date_grouping="Month", color="category")
    assert len(split.figure.data) == sales["category"].nunique()
    with pytest.raises(charts.ChartError):
        charts.line_chart(sales, "order_date", ["revenue", "units"], color="category")
    with pytest.raises(charts.ChartError):
        charts.line_chart(sales, "order_date", [])


def test_bar_chart_counts_rows_or_aggregates_a_value(sales):
    counts = charts.bar_chart(sales, "category")
    assert counts.data["count"].sum() == len(sales)
    totals = charts.bar_chart(sales, "category", "revenue", aggregate="sum")
    assert totals.data["sum of revenue"].sum() == pytest.approx(sales["revenue"].sum())


def test_bar_chart_limits_the_number_of_groups(sales):
    result = charts.bar_chart(sales, "order_id", top_n=5)
    assert result.data["order_id"].nunique() == 5
    assert "top 5" in result.note


def test_histogram_scatter_box_and_correlation(sales):
    assert charts.histogram(sales, "revenue", bins=20, color="region").figure.data
    scatter = charts.scatter_chart(sales, "unit_price", "revenue", color="category", max_points=100)
    assert len(scatter.data) == 100 and "sample" in scatter.note
    assert charts.box_chart(sales, "revenue", "category").figure.data
    corr = charts.correlation_heatmap(sales)
    assert corr.data.shape[0] == len(profiling.numeric_columns(sales))


def test_charts_reject_columns_they_cannot_plot(sales):
    with pytest.raises(charts.ChartError):
        charts.histogram(sales, "region")
    with pytest.raises(charts.ChartError):
        charts.scatter_chart(sales, "region", "revenue")
    with pytest.raises(charts.ChartError):
        charts.bar_chart(sales, "not_a_column")
    with pytest.raises(charts.ChartError):
        charts.correlation_heatmap(sales, ["revenue"])


def test_fold_categories_keeps_the_largest_groups():
    series = pd.Series(list("aaaabbbccd") + [None])
    folded = charts.fold_categories(series, max_groups=3)
    assert set(folded) == {"a", "b", "Other"}
    assert (folded == "Other").sum() == 4


def test_missing_values_chart(sales):
    result = charts.missing_values_chart(profiling.missing_by_column(sales))
    assert result.data["column"].iloc[0] == "customer_rating"
    with pytest.raises(charts.ChartError):
        charts.missing_values_chart(profiling.missing_by_column(sales.dropna()))
