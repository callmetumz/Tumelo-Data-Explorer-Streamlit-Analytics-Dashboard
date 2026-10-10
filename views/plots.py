"""Plot: build charts from any columns of the active dataset.

The page collects the chart type and column choices; the figures themselves
are built by ``data_explorer.charts``.
"""

import streamlit as st

from data_explorer import charts, profiling
from ui import components as ui

NONE = "(none)"

ui.page_header(
    "Plot",
    "Pick a chart type and the columns to plot. Charts are interactive: hover for values, "
    "drag to zoom, double-click to reset.",
    icon=":material/insert_chart:",
)

record = ui.get_active_dataset()
if record is None:
    ui.empty_state(on_page="plot")
    st.stop()

df = ui.load_active_dataframe(record)
if df.empty:
    st.warning("This dataset has no rows to plot.", icon=":material/warning:")
    st.stop()

numeric = profiling.numeric_columns(df)
dates = profiling.datetime_columns(df)
groups = [c for c in profiling.categorical_columns(df) if 1 < df[c].nunique() <= 200]
# Columns with the most distinct values make the most informative defaults
# for histograms and scatter plots.
by_variety = sorted(numeric, key=lambda column: df[column].nunique(), reverse=True)
all_columns = list(df.columns)
dark = ui.is_dark_theme()
key = f"plot{record.id}"


def optional(choice: str) -> str | None:
    return None if choice == NONE else choice


def pick_group(label: str, widget_key: str, help: str | None = None) -> str | None:
    return optional(st.selectbox(label, [NONE] + groups, key=widget_key, help=help))


controls, canvas = st.columns([1, 3], gap="large")

with controls:
    st.caption(f"Dataset: **{record.name}**")
    chart_type = st.selectbox("Chart type", charts.CHART_TYPES, key=f"{key}_type")
    build = None  # (chart function, its keyword arguments)

    if chart_type != "Bar" and not numeric:
        st.warning(
            "This chart needs a numeric column and the dataset has none. Try a bar chart.",
            icon=":material/warning:",
        )

    elif chart_type == "Line":
        x_options = dates + numeric + [c for c in all_columns if c not in dates + numeric]
        x = st.selectbox("X axis", x_options, key=f"{key}_line_x")
        y = st.multiselect(
            "Y axis",
            [c for c in numeric if c != x],
            default=[c for c in numeric if c != x][:1],
            key=f"{key}_line_y",
            help="Choose one or more numeric columns.",
        )
        grouping = None
        if x in dates:
            grouping = optional(
                st.selectbox(
                    "Group dates by",
                    [NONE] + list(charts.DATE_GROUPINGS),
                    index=3,
                    key=f"{key}_line_grouping",
                )
            )
        aggregate = st.selectbox(
            "Combine rows using",
            charts.AGGREGATIONS,
            key=f"{key}_line_agg",
            help="How rows that share the same X value are combined into one point.",
        )
        color = None
        if len(y) == 1:
            color = pick_group("Split into lines by", f"{key}_line_color")
        build = (
            charts.line_chart,
            dict(x=x, y=y, aggregate=aggregate, date_grouping=grouping, color=color),
        )

    elif chart_type == "Bar":
        x_options = groups + [c for c in all_columns if c not in groups]
        x = st.selectbox("Category (bars)", x_options, key=f"{key}_bar_x")
        y = optional(
            st.selectbox(
                "Value",
                [NONE] + [c for c in numeric if c != x],
                key=f"{key}_bar_y",
                help="Leave as (none) to count rows in each category.",
            )
        )
        aggregate = "count"
        if y:
            aggregate = st.selectbox("Combine rows using", charts.AGGREGATIONS, key=f"{key}_bar_agg")
        color = optional(
            st.selectbox(
                "Split bars by", [NONE] + [c for c in groups if c != x], key=f"{key}_bar_color"
            )
        )
        top_n = st.slider("Most categories to show", 5, 40, 15, key=f"{key}_bar_top")
        build = (charts.bar_chart, dict(x=x, y=y, aggregate=aggregate, color=color, top_n=top_n))

    elif chart_type == "Histogram":
        column = st.selectbox(
            "Column", numeric, index=numeric.index(by_variety[0]), key=f"{key}_hist_x"
        )
        bins = st.slider("Number of bins", 5, 100, 30, key=f"{key}_hist_bins")
        color = pick_group("Stack by", f"{key}_hist_color")
        build = (charts.histogram, dict(column=column, bins=bins, color=color))

    elif chart_type == "Scatter":
        if len(numeric) < 2:
            st.warning("A scatter plot needs two numeric columns.", icon=":material/warning:")
        else:
            x = st.selectbox(
                "X axis", numeric, index=numeric.index(by_variety[1]), key=f"{key}_scatter_x"
            )
            y_options = [c for c in numeric if c != x]
            y_default = next(c for c in by_variety if c != x)
            y = st.selectbox(
                "Y axis", y_options, index=y_options.index(y_default), key=f"{key}_scatter_y"
            )
            color = optional(
                st.selectbox(
                    "Colour by",
                    [NONE] + groups + [c for c in numeric if c not in (x, y)],
                    key=f"{key}_scatter_color",
                )
            )
            build = (charts.scatter_chart, dict(x=x, y=y, color=color))

    elif chart_type == "Box plot":
        y = st.selectbox("Column", numeric, key=f"{key}_box_y")
        x = pick_group("Compare across", f"{key}_box_x")
        build = (charts.box_chart, dict(y=y, x=x))

    elif chart_type == "Correlation":
        if len(numeric) < 2:
            st.warning("A correlation chart needs two numeric columns.", icon=":material/warning:")
        else:
            chosen = st.multiselect("Columns", numeric, default=numeric[:12], key=f"{key}_corr")
            build = (charts.correlation_heatmap, dict(columns=chosen))

with canvas:
    if build is not None:
        chart_function, choices = build
        try:
            result = chart_function(df, dark=dark, **choices)
        except charts.ChartError as error:
            st.info(str(error), icon=":material/info:")
        else:
            st.plotly_chart(result.figure, width="stretch", theme="streamlit")
            if result.note:
                st.caption(result.note)
            with st.expander("Data behind this chart", icon=":material/table_rows:"):
                st.dataframe(
                    result.data,
                    hide_index=True,
                    width="stretch",
                    height=ui.table_height(len(result.data), 260),
                    column_config=ui.table_config(result.data),
                )
                st.download_button(
                    "Download chart data as CSV",
                    data=result.data.to_csv(index=False).encode("utf-8"),
                    file_name="chart_data.csv",
                    mime="text/csv",
                    icon=":material/download:",
                )
