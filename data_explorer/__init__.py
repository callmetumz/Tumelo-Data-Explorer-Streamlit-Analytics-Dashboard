"""Data-processing layer for Tumelo Data Explorer.

Nothing in this package imports Streamlit. Every function takes plain Python
or pandas objects and returns plain Python or pandas objects, so the same code
can be used from the dashboard, a notebook, a script or the test suite.

Modules
-------
config       Paths and limits shared by the rest of the package.
cleaning     Reusable data-cleaning functions and the ``clean_dataset`` runner.
filtering    Row filters described as small data objects.
profiling    Data-quality summaries: shape, missing values, duplicates.
charts       Plotly figure builders (line, bar, histogram, scatter, ...).
database     SQLite storage: dataset tables, catalog, pipeline log, SQL queries.
pipeline     Glue for the full flow: source -> processing -> database.
sample_data  A deliberately messy demo dataset.
text         Small text-formatting helpers.
"""

__version__ = "2.0.0"
