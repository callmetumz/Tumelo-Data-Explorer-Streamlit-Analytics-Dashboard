# Changes in version 2.0

This document records what changed between the original single-file app and version 2, and why. It is organised around the five improvements that were planned, followed by the bugs that were fixed along the way.

## Summary

| | Before | After |
|---|---|---|
| Does it start? | No: `app.py` had a syntax error | Yes |
| Structure | One 70-line `app.py` | Entry point + 4 pages + a UI module + a data package |
| Home | Welcome text, a name box and a click counter | Dashboard with KPI cards, dataset catalog, quality snapshot, activity log |
| Data View | 10 rows of random numbers | CSV upload, interactive table, filters, quality checks, cleaning |
| Plot | A fixed sine wave | Six chart types built from any columns |
| Storage | None: everything lost on refresh | SQLite database with a catalog and a pipeline log |
| SQL | None | Read-only SQL page with example queries |
| Tests | None | 67 automated tests |

## 1. Dashboard UI

**Home is now a dashboard landing page.** It shows:

- Five KPI cards: datasets loaded, records processed, rows stored, data completeness and duplicate rows. Each has a tooltip explaining how it is calculated.
- A catalog table of every stored dataset with a completeness bar.
- A data-quality panel for the active dataset (missing values by column, duplicate warning).
- A table of recent pipeline activity.
- A four-step explanation of how data flows through the app.
- An empty state with a "Load sample dataset" button when the database is empty, so the page is never blank.

**The click counter is gone.** The name box and "Button clicked N times" were replaced by *Records processed*: the total number of rows that have passed through the pipeline, across every load and cleaning run. It is calculated in SQL from the `pipeline_runs` table, so it survives restarts and does not drop when a dataset is deleted.

**Navigation, titles and layout.**

- The sidebar dropdown was replaced with proper page navigation (`st.navigation`) with an icon per page. Each page has its own URL, so pages can be bookmarked and the browser back button works.
- Every page starts with the same header block (title + one-line description) from `ui.page_header`.
- A dataset picker in the sidebar sets the *active dataset* used by every page.
- The browser tab title was shortened to "Tumelo Data Explorer".
- The accent colour is defined for both light and dark themes in `.streamlit/config.toml`, so the app follows the viewer's system theme.
- The sidebar collapses automatically on phones.

## 2. Data View

The page that showed ten random numbers now has four parts:

- **Load data.** Upload a CSV. The delimiter (comma, semicolon, tab) and encoding are detected automatically. A preview with row, column, missing and duplicate counts is shown *before* saving, and the page warns if the name would replace an existing dataset. A built-in sample dataset (and a download of it as CSV) is provided for trying things out.
- **Explore.** An interactive, sortable table with a row counter ("Showing 195 of 1,230 rows"), a search box across all columns, and per-column filters whose widget matches the column type: a range slider for numbers, a date range for dates, a value picker for categories and a "contains" box for free text. Filtered rows can be downloaded.
- **Data quality.** Row and column counts as KPI cards; missing values per column as a chart; the duplicate rows themselves, grouped so each set of copies sits together; a per-column table of type, missing %, distinct values and an example; and summary statistics for numeric columns.
- **Clean.** Tick the steps to apply: drop columns, trim whitespace and standardise blanks, remove duplicates, fill missing values (mean, median, mode, constant, forward fill), remove rows with missing values, rename columns to snake_case. The result is previewed live with before/after KPI cards and a plain-English list of what each step did. Nothing is written until **Save to database** is pressed, and the default is to save as a new dataset so the original is kept.

## 3. Plot

The sine wave was replaced by a chart builder that works on any dataset:

| Chart | Options |
|---|---|
| Line | X column, one or more Y columns, date grouping (day to year), aggregation, split into lines by a category |
| Bar | Category, optional value, aggregation (count, sum, mean, median, min, max), split by a second category, top-N limit |
| Histogram | Column, number of bins, stack by a category |
| Scatter | X, Y, colour by a category or a number; shows the correlation in the title |
| Box plot | Column, compare across a category |
| Correlation | Heatmap of pairwise correlation between chosen numeric columns |

Other details:

- Charts use Plotly, so they are interactive (hover, zoom, download as PNG). Matplotlib is no longer needed.
- Under every chart, "Data behind this chart" shows the exact table that was plotted and lets you download it.
- Controls only offer columns that make sense (numeric columns for a Y axis, low-cardinality columns for grouping), and a clear message is shown when a chart cannot be drawn.
- A fixed, colour-blind-safe colour order is used. Columns with many distinct values keep their largest groups and fold the rest into "Other" instead of producing dozens of colours.
- Large scatter plots are sampled to 5,000 points, and the chart says so when that happens.

## 4. Data processing separated from the UI

The single file was split into three layers:

```
views/          Streamlit pages: widgets in, results out
ui/             Streamlit helpers shared by pages
data_explorer/  All data work: no Streamlit imports
```

What this achieves:

- **Cleaning logic is reusable.** Each step in `data_explorer/cleaning.py` is a plain function that takes a DataFrame and returns a new one (`trim_whitespace`, `drop_duplicate_rows`, `fill_missing`, ...). `clean_dataset(df, options)` runs the chosen steps in a fixed order and returns a `CleaningReport`.
- **Preparation is separate from presentation.** Pages never parse files, compute statistics or build figures. `views/plots.py`, for example, only collects column choices and calls `charts.bar_chart(...)`; the grouping, aggregation and sorting happen inside the chart function.
- **No duplicated logic.** Missing-value counts are needed by the Home page, the Data View KPIs, the Data quality tab and the pipeline. All four call `profiling.profile_dataset` / `profiling.missing_by_column`. Likewise the page header, KPI cards and dataset picker are written once in `ui/components.py`.
- **Filters are data, not code.** The Explore tab builds small `RangeFilter` / `ValuesFilter` / `TextFilter` objects and hands them to `filtering.apply_filters`, so the filtering rules can be tested without a browser.
- **It is testable.** Because the data layer has no Streamlit dependency, it is covered by ordinary pytest tests.

## 5. Database and pipeline

The app now implements the pipeline that was discussed:

```
Data source → Python processing → Database → Streamlit dashboard
```

- **Data source**: a CSV upload or the built-in sample.
- **Python processing** (`pipeline.py`, `cleaning.py`, `profiling.py`): parse the file, tidy the headers (blank and repeated column names are fixed so the table can be stored in SQL), detect date columns, count missing values and duplicates.
- **Database** (`database.py`): SQLite via Python's built-in `sqlite3`, so there is nothing extra to install. Three kinds of table:
  - `datasets`: the catalog, one row per dataset with its quality statistics.
  - `pipeline_runs`: an append-only log of every ingest, clean and delete with rows in and out.
  - `ds_<name>`: one table per dataset.
- **Dashboard**: every page reads from the database. Datasets persist between sessions.

**SQL Lab** is a new page for querying the database directly: an editor, example queries written for the active dataset's real column names (preview, count, group and aggregate, top 10, missing values, monthly trend), a table browser, and dataset deletion.

**Safety.** User-written SQL runs on a connection opened in SQLite's read-only mode, so anything that would change data is refused by the database engine rather than by trying to spot dangerous keywords in the text. Queries are also stopped after 10 seconds and results are capped at 5,000 rows. In the app's own SQL, values are always passed as parameters and dataset table names are quoted.

**Type round-trip.** SQLite stores dates as text and booleans as 0/1. The catalog records each column's type, and `load_dataset` converts them back, so a date column is still a date after being stored.

## Bugs fixed

1. **The app did not start.** `page_title` in `app.py` was missing its closing quote, a `SyntaxError` on line 7.
2. **`run_streamlit.py` crashed.** It used `subprocess` without importing it, and passed a list together with `shell=True`, which on macOS and Linux runs only `streamlit` and ignores the rest. It now runs `python -m streamlit run app.py` and passes extra arguments through.
3. **The README described features that did not exist** (Data Profile, Math Plotter, Machine Learning Demo, About page) and its Installation section stopped mid-way with the wrong repository URL and an unclosed code block. It has been rewritten to match the app; features that are not built are listed under Roadmap.
4. **Data View changed on every click.** It generated new random numbers on each rerun.

## Dependencies

- Added version floors to `requirements.txt` (`streamlit>=1.52`, `pandas>=2.2`, `numpy>=1.26`, `plotly>=5.24`). The test suite passes on those minimums and on the current releases (Streamlit 1.65, pandas 3.0, Plotly 7.1).
- Removed `matplotlib` (replaced by Plotly) and `scikit-learn` (was listed but never used). Add `scikit-learn` back when the machine learning demo is built.
- Added `requirements-dev.txt` with `pytest`.

## Files

Added:

```
.gitignore
.streamlit/config.toml
data_explorer/  __init__, charts, cleaning, config, database, filtering,
                pipeline, profiling, sample_data, text
ui/             __init__, components
views/          home, data_view, plots, sql_lab
tests/          conftest, test_app, test_charts, test_cleaning, test_database,
                test_filtering, test_pipeline, test_profiling
docs/CHANGES.md, docs/screenshots/
pytest.ini
requirements-dev.txt
```

Changed: `app.py` (rewritten), `run_streamlit.py` (rewritten), `requirements.txt`, `README.md`.

## Known limits

- **Hosting.** On Streamlit Community Cloud the SQLite file is temporary and shared by all visitors. Uploaded data will disappear when the app restarts, and visitors can see each other's datasets.
- **Size.** Datasets are loaded fully into memory. This is comfortable up to a few hundred thousand rows; beyond that the app would need paging or to push more work into SQL.
- **File types.** CSV and other delimited text only.
- **Date detection** converts a text column to dates only when at least 90% of its values parse in one consistent format. Columns with mixed date formats stay as text.
- **No undo.** "Replace the current dataset" overwrites the stored table. Saving as a new dataset (the default) keeps the original.
