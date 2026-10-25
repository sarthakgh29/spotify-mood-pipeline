"""Entry point: `streamlit run dashboard.py`. Registers the pages and shows them as a tab bar across the top.

The page scripts live in views/, not pages/: with a pages/ folder Streamlit can run a page script directly on a
fresh server (for example a refresh on /Method_Comparison), skipping this router and its top navigation."""
import streamlit as st

from theme import inject_theme

st.set_page_config(page_title="My Listening & Mood", page_icon="🎧", layout="wide")
inject_theme()

pages = [
    st.Page("views/0_Dashboard.py", title="Dashboard", icon="🎧", default=True),
    st.Page("views/5_Lifetime_Wrapped.py", title="Lifetime Wrapped", icon="🎁"),
    st.Page("views/6_Song_Globe.py", title="Song Globe", icon="🌍"),
    st.Page("views/7_Mood_Playlists.py", title="Mood Playlists", icon="🎶"),
    st.Page("views/2_Method_Comparison.py", title="Mood Comparison", icon="🔬"),
    st.Page("views/4_Mood_Lab.py", title="Mood Lab", icon="🧪"),
]

st.navigation(pages, position="top").run()
