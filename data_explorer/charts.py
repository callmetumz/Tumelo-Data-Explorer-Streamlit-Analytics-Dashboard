"""Chart builders.

Each function takes a DataFrame plus column choices and returns a
``ChartResult``: the Plotly figure, the exact table that was plotted and an
optional note (for example when points were sampled). The functions do the
data preparation a chart needs - grouping, aggregating, sorting - so the
Streamlit page only has to collect choices and display the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from . import config
from .profiling import DATETIME, NUMERIC, column_kind, numeric_columns

CHART_TYPES = ("Line", "Bar", "Histogram", "Scatter", "Box plot", "Correlation")
AGGREGATIONS = ("sum", "mean", "median", "min", "max", "count")
DATE_GROUPINGS = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}

#: Fixed categorical colour order, chosen so neighbouring series stay
#: distinguishable for colour-blind readers. Light and dark variants.
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
OTHER_COLOUR = "#898781"
MAX_COLOUR_GROUPS = len(PALETTE_LIGHT)

OTHER_LABEL = "Other"
MISSING_LABEL = "(missing)"


class ChartError(ValueError):
    """Raised when the chosen columns cannot produce the requested chart."""


@dataclass
class ChartResult:
    figure: go.Figure
    data: pd.DataFrame
    note: str = ""


def palette(dark: bool = False) -> list[str]:
    return PALETTE_DARK if dark else PALETTE_LIGHT


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _require(df: pd.DataFrame, *columns: str | None) -> None:
    for col in columns:
        if col is not None and col not in df.columns:
            raise ChartError(f"Column {col!r} is not in this dataset.")


def _require_numeric(df: pd.DataFrame, *columns: str) -> None:
    for col in columns:
        if column_kind(df[col]) != NUMERIC:
            raise ChartError(f"{col!r} is not a numeric column.")


def fold_categories(series: pd.Series, max_groups: int = MAX_COLOUR_GROUPS) -> pd.Series:
    """Keep the most common groups and merge the rest into "Other".

    A chart can only show a handful of colours clearly, so a column with many
    distinct values keeps its ``max_groups - 1`` largest groups.
    """
    labels = series.astype("string").fillna(MISSING_LABEL)
    counts = labels.value_counts()
    if len(counts) <= max_groups:
        return labels.astype(object)
    keep = set(counts.index[: max_groups - 1])
    return labels.where(labels.isin(keep), OTHER_LABEL).astype(object)


def _colour_map(groups: list[str], dark: bool) -> dict[str, str]:
    colours = palette(dark)
    mapping, slot = {}, 0
    for group in groups:
        if group == OTHER_LABEL:
            mapping[group] = OTHER_COLOUR
        else:
            mapping[group] = colours[slot % len(colours)]
            slot += 1
    return mapping


def _group_order(labels: pd.Series) -> list[str]:
    """Largest group first, with "Other" always last."""
    order = [str(v) for v in labels.value_counts().index]
    if OTHER_LABEL in order:
        order.remove(OTHER_LABEL)
        order.append(OTHER_LABEL)
    return order


def _style(fig: go.Figure, title: str, show_legend: bool) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16)),
        margin=dict(l=10, r=10, t=70 if show_legend else 50, b=10),
        showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text=""),
        hoverlabel=dict(namelength=-1),
    )
    return fig


def _aggregate(grouped, column: str | None, how: str) -> pd.Series:
    if how not in AGGREGATIONS:
        raise ChartError(f"Unknown aggregation {how!r}.")
    if how == "count" or column is None:
        return grouped.size()
    return grouped[column].agg(how)


# --------------------------------------------------------------------------
# Line
# --------------------------------------------------------------------------
def line_chart(
    df: pd.DataFrame,
    x: str,
    y: list[str],
    aggregate: str = "mean",
    date_grouping: str | None = None,
    color: str | None = None,
    dark: bool = False,
) -> ChartResult:
    """Line chart of one or more numeric columns against ``x``.

    Rows sharing the same ``x`` value are combined with ``aggregate`` so there
    is one point per x position. If ``x`` is a date, ``date_grouping`` ("Day",
    "Week", "Month", "Quarter", "Year") buckets it first. ``color`` splits a
    single ``y`` column into one line per group.
    """
    y = list(y)
    if not y:
        raise ChartError("Choose at least one numeric column for the Y axis.")
    _require(df, x, color, *y)
    _require_numeric(df, *y)
    if color and len(y) > 1:
        raise ChartError("Split by group works with a single Y column.")

    work = df[[x, *y] + ([color] if color else [])].dropna(subset=[x]).copy()
    if work.empty:
        raise ChartError(f"{x!r} has no values to plot.")
    if date_grouping and column_kind(work[x]) == DATETIME:
        work[x] = work[x].dt.to_period(DATE_GROUPINGS[date_grouping]).dt.start_time

    keys = [x]
    if color:
        work[color] = fold_categories(work[color])
        keys.append(color)

    grouped = work.groupby(keys, observed=True, sort=True)
    if aggregate == "count":
        data = grouped[y].count().reset_index()
    else:
        if aggregate not in AGGREGATIONS:
            raise ChartError(f"Unknown aggregation {aggregate!r}.")
        data = grouped[y].agg(aggregate).reset_index()

    if color:
        order = _group_order(work[color])
        fig = px.line(
            data, x=x, y=y[0], color=color,
            category_orders={color: order}, color_discrete_map=_colour_map(order, dark),
        )
        show_legend = True
    else:
        long = data.melt(id_vars=[x], value_vars=y, var_name="series", value_name="value")
        fig = px.line(
            long, x=x, y="value", color="series",
            category_orders={"series": y}, color_discrete_map=_colour_map(y, dark),
        )
        fig.update_yaxes(title_text=y[0] if len(y) == 1 else "value")
        show_legend = len(y) > 1

    fig.update_traces(line=dict(width=2), connectgaps=False)
    if len(data) <= 60:
        fig.update_traces(mode="lines+markers", marker=dict(size=7))
    fig.update_layout(hovermode="x unified")
    label = ", ".join(y)
    title = f"{aggregate.capitalize()} of {label} by {x}"
    if color:
        title += f", split by {color}"
    return ChartResult(_style(fig, title, show_legend), data)


# --------------------------------------------------------------------------
# Bar
# --------------------------------------------------------------------------
def bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str | None = None,
    aggregate: str = "count",
    color: str | None = None,
    top_n: int = 15,
    dark: bool = False,
) -> ChartResult:
    """Bar chart comparing groups of ``x``.

    With no ``y`` the bars count rows; otherwise ``y`` is combined with
    ``aggregate``. Text groups are sorted largest first and limited to the
    ``top_n`` biggest; numeric and date groups keep their natural order.

    When split by ``color``, totals (count, sum) are stacked so each bar still
    shows the whole; other aggregations are drawn side by side because an
    average cannot be added up.
    """
    _require(df, x, y, color)
    if y is None:
        aggregate = "count"
    elif aggregate != "count":
        _require_numeric(df, y)

    columns = list(dict.fromkeys([x] + ([y] if y else []) + ([color] if color else [])))
    work = df[columns].copy()
    ordered_axis = column_kind(work[x]) in (NUMERIC, DATETIME)
    if not ordered_axis:
        work[x] = work[x].astype("string").fillna(MISSING_LABEL).astype(object)
    else:
        work = work.dropna(subset=[x])
    if work.empty:
        raise ChartError(f"{x!r} has no values to plot.")

    value_name = "count" if aggregate == "count" else f"{aggregate} of {y}"
    keys = [x]
    if color and color != x:
        work[color] = fold_categories(work[color])
        keys.append(color)

    data = _aggregate(work.groupby(keys, observed=True, sort=True), y, aggregate)
    data = data.rename(value_name).reset_index()

    note = ""
    if ordered_axis:
        category_order = None
    else:
        totals = data.groupby(x)[value_name].sum().sort_values(ascending=False)
        if len(totals) > top_n:
            note = f"Showing the top {top_n} of {len(totals):,} groups."
            totals = totals.head(top_n)
            data = data[data[x].isin(totals.index)]
        category_order = list(totals.index)

    horizontal = not ordered_axis
    args = dict(
        x=value_name if horizontal else x,
        y=x if horizontal else value_name,
        orientation="h" if horizontal else "v",
    )
    orders = {x: category_order} if category_order else {}
    if len(keys) == 2:
        order = _group_order(work[color])
        orders[color] = order
        stacked = aggregate in ("count", "sum")
        fig = px.bar(
            data, color=color, barmode="stack" if stacked else "group", category_orders=orders,
            color_discrete_map=_colour_map(order, dark), **args,
        )
        show_legend = True
    else:
        fig = px.bar(
            data, category_orders=orders, color_discrete_sequence=palette(dark)[:1], **args
        )
        show_legend = False

    split = len(keys) == 2
    if split and stacked:
        # A thin gap in the background colour separates stacked segments.
        gap = "#0e1117" if dark else "#ffffff"
        fig.update_traces(marker_line_width=1.5, marker_line_color=gap)
    else:
        fig.update_traces(marker_cornerradius=4, marker_line_width=0)
    fig.update_layout(bargap=0.35, bargroupgap=0.08)
    if horizontal:
        row_height = 28 if not split or stacked else 14 * data[color].nunique() + 14
        fig.update_layout(height=max(360, row_height * data[x].nunique() + 120))
        fig.update_yaxes(title_text="")
    title = f"{value_name.capitalize()} by {x}" if aggregate != "count" else f"Number of rows by {x}"
    if show_legend:
        title += f", split by {color}"
    return ChartResult(_style(fig, title, show_legend), data.reset_index(drop=True), note)


# --------------------------------------------------------------------------
# Histogram
# --------------------------------------------------------------------------
def histogram(
    df: pd.DataFrame,
    column: str,
    bins: int = 30,
    color: str | None = None,
    dark: bool = False,
) -> ChartResult:
    """Distribution of one numeric column, optionally stacked by a group."""
    _require(df, column, color)
    _require_numeric(df, column)
    work = df[[column] + ([color] if color else [])].dropna(subset=[column]).copy()
    if work.empty:
        raise ChartError(f"{column!r} has no values to plot.")

    if color:
        work[color] = fold_categories(work[color])
        order = _group_order(work[color])
        fig = px.histogram(
            work, x=column, nbins=bins, color=color, barmode="stack",
            category_orders={color: order}, color_discrete_map=_colour_map(order, dark),
        )
    else:
        fig = px.histogram(work, x=column, nbins=bins, color_discrete_sequence=palette(dark)[:1])
    fig.update_layout(bargap=0.04)
    fig.update_yaxes(title_text="rows")
    title = f"Distribution of {column}" + (f", split by {color}" if color else "")
    return ChartResult(_style(fig, title, bool(color)), work)


# --------------------------------------------------------------------------
# Scatter
# --------------------------------------------------------------------------
def scatter_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None = None,
    max_points: int = config.MAX_SCATTER_POINTS,
    dark: bool = False,
) -> ChartResult:
    """Relationship between two numeric columns, optionally coloured by group."""
    _require(df, x, y, color)
    _require_numeric(df, x, y)
    columns = list(dict.fromkeys([x, y] + ([color] if color else [])))
    work = df[columns].dropna(subset=[x, y]).copy()
    if work.empty:
        raise ChartError("There are no rows where both columns have a value.")

    note = ""
    if len(work) > max_points:
        note = f"Showing a random sample of {max_points:,} of {len(work):,} points."
        work = work.sample(n=max_points, random_state=0)

    ring = "rgba(14,17,23,0.7)" if dark else "rgba(255,255,255,0.8)"
    if color and column_kind(work[color]) != NUMERIC:
        work[color] = fold_categories(work[color])
        order = _group_order(work[color])
        fig = px.scatter(
            work, x=x, y=y, color=color,
            category_orders={color: order}, color_discrete_map=_colour_map(order, dark),
        )
        show_legend = True
    elif color:
        fig = px.scatter(work, x=x, y=y, color=color, color_continuous_scale="Blues")
        show_legend = False
    else:
        fig = px.scatter(work, x=x, y=y, color_discrete_sequence=palette(dark)[:1])
        show_legend = False
    fig.update_traces(marker=dict(size=8, opacity=0.8, line=dict(width=1, color=ring)))

    correlation = work[x].corr(work[y]) if len(work) > 2 else float("nan")
    title = f"{y} vs {x}"
    if pd.notna(correlation):
        title += f" (correlation {correlation:+.2f})"
    return ChartResult(_style(fig, title, show_legend), work.reset_index(drop=True), note)


# --------------------------------------------------------------------------
# Box plot
# --------------------------------------------------------------------------
def box_chart(
    df: pd.DataFrame, y: str, x: str | None = None, top_n: int = 12, dark: bool = False
) -> ChartResult:
    """Spread of a numeric column, optionally compared across groups."""
    _require(df, y, x)
    _require_numeric(df, y)
    work = df[[y] + ([x] if x else [])].dropna(subset=[y]).copy()
    if work.empty:
        raise ChartError(f"{y!r} has no values to plot.")

    note = ""
    if x:
        work[x] = work[x].astype("string").fillna(MISSING_LABEL).astype(object)
        counts = work[x].value_counts()
        if len(counts) > top_n:
            note = f"Showing the {top_n} largest of {len(counts):,} groups."
            work = work[work[x].isin(counts.index[:top_n])]
        order = list(work.groupby(x)[y].median().sort_values(ascending=False).index)
        fig = px.box(
            work, x=x, y=y, category_orders={x: order},
            color_discrete_sequence=palette(dark)[:1],
        )
    else:
        fig = px.box(work, y=y, color_discrete_sequence=palette(dark)[:1])
    title = f"Spread of {y}" + (f" by {x}" if x else "")
    return ChartResult(_style(fig, title, False), work.reset_index(drop=True), note)


# --------------------------------------------------------------------------
# Correlation heatmap
# --------------------------------------------------------------------------
def correlation_heatmap(
    df: pd.DataFrame, columns: list[str] | None = None, dark: bool = False
) -> ChartResult:
    """Pairwise correlation between numeric columns (-1 to +1)."""
    columns = list(columns) if columns else numeric_columns(df)
    _require(df, *columns)
    if len(columns) < 2:
        raise ChartError("A correlation chart needs at least two numeric columns.")
    _require_numeric(df, *columns)

    corr = df[columns].corr().round(2)
    midpoint = "#383835" if dark else "#f0efec"
    fig = go.Figure(
        go.Heatmap(
            z=corr.values,
            x=[str(c) for c in corr.columns],
            y=[str(c) for c in corr.index],
            zmin=-1,
            zmax=1,
            colorscale=[[0.0, "#d03b3b"], [0.5, midpoint], [1.0, "#2a78d6"]],
            text=corr.values,
            texttemplate="%{text:.2f}" if len(columns) <= 12 else None,
            hovertemplate="%{y} vs %{x}<br>correlation %{z:.2f}<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar=dict(title="r", thickness=12),
        )
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=max(380, 46 * len(columns) + 140))
    data = corr.reset_index().rename(columns={"index": "column"})
    return ChartResult(_style(fig, "Correlation between numeric columns", False), data)


# --------------------------------------------------------------------------
# Missing values
# --------------------------------------------------------------------------
def missing_values_chart(summary: pd.DataFrame, dark: bool = False, top_n: int = 12) -> ChartResult:
    """Horizontal bars of missing-value percentage per column.

    ``summary`` is the table returned by ``profiling.missing_by_column``.
    """
    if summary.empty:
        raise ChartError("There are no missing values to chart.")
    data = summary.sort_values("missing_pct", ascending=False).head(top_n)
    fig = px.bar(
        data, x="missing_pct", y="column", orientation="h",
        category_orders={"column": list(data["column"])},
        color_discrete_sequence=palette(dark)[:1],
        custom_data=["missing"],
    )
    fig.update_traces(
        marker_cornerradius=4,
        marker_line_width=0,
        hovertemplate="%{y}<br>%{x:.1f}% missing (%{customdata[0]:,} cells)<extra></extra>",
    )
    fig.update_layout(bargap=0.4, height=max(240, 30 * len(data) + 110))
    fig.update_xaxes(title_text="% of rows missing", rangemode="tozero")
    fig.update_yaxes(title_text="")
    return ChartResult(_style(fig, "Missing values by column", False), data.reset_index(drop=True))
