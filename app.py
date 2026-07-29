import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(
    page_title="Tumelo Data Explorer: Streamlit Analytics Dashboard,
    page_icon="🚀",
    layout="wide"
)

st.title("🚀Tumelo Data Explorer: Streamlit Analytics Dashboard🚀")
st.sidebar.header("Things to do")
option = st.sidebar.selectbox(
    "Choose an option",
    ["Home", "Data View", "Plot"]
)

if "count" not in st.session_state:
    st.session_state.count = 0

def plot_sine():
    x = np.linspace(0, 10, 100)
    y = np.sin(x)
    fig, ax = plt.subplots()
    ax.plot(x, y)
    ax.set_xlabel("x")
    ax.set_ylabel("sin(x)")
    ax.set_title("Sine Wave")

    st.pyplot(fig)

if option == "Home":
    st.header("Welcome to my data visualisation app")

    st.write(
        """
        **Welcome to Tumelo's Streamlit application!**

        This app allows you to:
        - 📊 View and explore sample data
        - 📈 Plot mathematical functions
        - 🧭 Navigate between sections using the sidebar

        Use the **sidebar on the left** to scroll through the available options.
        """
    )

    name = st.text_input("Please enter your name")

    if st.button("Submit"):
        st.session_state.count += 1
        st.success(f"Hello {name} 👋")

    st.write("Button clicked:", st.session_state.count, "times")

elif option == "Data View":
    st.header("Data View")

    df = pd.DataFrame(
        np.random.randn(10, 3),
        columns=["A", "B", "C"]
    )

    st.dataframe(df)

elif option == "Plot":
    st.header("Plot Example")
    plot_sine()

st.markdown("---")
st.caption("Made by Tumelo ❤️")
