"""Smoke tests that run each page headlessly with Streamlit's test client."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from data_explorer import database, pipeline

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["views/home.py", "views/data_view.py", "views/plots.py", "views/sql_lab.py"]


def open_page(page: str) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=30).run()
    if page != PAGES[0]:
        app.switch_page(page).run()
    assert not app.exception, app.exception
    return app


def find(widgets, label: str):
    return next(widget for widget in widgets if widget.label == label)


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_with_an_empty_database(db_path, page):
    open_page(page)


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_with_data(db_path, page):
    pipeline.ingest_sample()
    open_page(page)


def test_home_shows_kpis_from_the_database(db_path):
    pipeline.ingest_sample()
    app = open_page("views/home.py")
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Datasets loaded"] == "1"
    assert metrics["Records processed"] == "1,230"
    assert metrics["Duplicate rows"] == "30"


def test_load_sample_button_fills_the_database(db_path):
    app = open_page("views/home.py")
    app.button(key="load_sample_home").click().run()
    assert not app.exception
    assert [d.row_count for d in database.list_datasets()] == [1230]


def test_every_chart_type_renders(db_path):
    pipeline.ingest_sample()
    app = open_page("views/plots.py")
    options = find(app.selectbox, "Chart type").options
    assert len(options) == 6
    for option in options:
        find(app.selectbox, "Chart type").select(option).run()
        assert not app.exception, (option, app.exception)
        assert not app.warning, (option, [w.value for w in app.warning])


def test_sql_lab_runs_a_query_and_blocks_writes(db_path):
    pipeline.ingest_sample()
    app = open_page("views/sql_lab.py")

    app.text_area[0].set_value("SELECT COUNT(*) AS n FROM ds_sample_retail_sales").run()
    app.button[0].click().run()
    assert not app.error
    assert any(frame.value.shape == (1, 1) for frame in app.dataframe)

    app.text_area[0].set_value("DELETE FROM datasets").run()
    app.button[0].click().run()
    assert "read-only" in app.error[0].value
    assert len(database.list_datasets()) == 1
