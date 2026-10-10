"""Tumelo Data Explorer - entry point.

Run with:  streamlit run app.py

This file only wires the app together: page config, navigation and the
shared sidebar. Each page lives in ``views/`` and all data work lives in the
``data_explorer`` package.
"""

import streamlit as st

from data_explorer import database
from ui import components as ui

st.set_page_config(
    page_title="Tumelo Data Explorer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto",
)

# Make sure the SQLite file and its tables exist before any page runs.
database.init_db()

navigation = st.navigation(
    {
        "Tumelo Data Explorer": [
            st.Page(ui.PAGE_HOME, title="Home", icon=":material/dashboard:", default=True),
            st.Page(ui.PAGE_DATA, title="Data View", icon=":material/table_view:"),
            st.Page(ui.PAGE_PLOT, title="Plot", icon=":material/insert_chart:"),
            st.Page(ui.PAGE_SQL, title="SQL Lab", icon=":material/database:"),
        ]
    }
)

ui.dataset_sidebar()
ui.show_flash()
navigation.run()
