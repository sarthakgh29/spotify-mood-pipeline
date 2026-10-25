"""The dashboard's look: a dark page with a soft green and purple glow, a gradient page title, card-style metrics, pill tabs and
green buttons. The palette and the gradients follow Johan's Lifetime-Wrapped page. Applied once, in dashboard.py, so every page gets it."""
import streamlit as st

BG, CARD, LINE = "#090d12", "#131a22", "#232e3a"
GREEN, PURPLE, PINK = "#1ed760", "#7c5cff", "#ff5d8f"

CSS = f"""<style>
.stApp {{
  background-color: {BG};
  background-image:
    radial-gradient(60% 40% at 20% 0%, rgba(30,215,96,.16), transparent 70%),
    radial-gradient(50% 36% at 90% 6%, rgba(124,92,255,.16), transparent 70%);
  background-repeat: no-repeat;
  background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background: transparent; }}

/* page title: the same green to purple to pink gradient as Johan's headlines */
[data-testid="stHeadingWithActionElements"] h1 {{
  background: linear-gradient(90deg, {GREEN}, {PURPLE} 70%, {PINK});
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  font-weight: 800; letter-spacing: -0.02em; width: fit-content;
}}
/* section headings get the little gradient bar */
[data-testid="stHeadingWithActionElements"] h2::before, [data-testid="stHeadingWithActionElements"] h3::before {{
  content: ""; display: inline-block; width: 5px; height: 1.05em; margin-right: 10px; border-radius: 3px;
  background: linear-gradient({GREEN}, {PURPLE}); vertical-align: -0.14em;
}}

/* metrics as cards */
[data-testid="stMetric"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; padding: 14px 18px;
  box-shadow: 0 10px 30px rgba(0,0,0,.25);
}}

/* tabs as pills, the open one filled green (Streamlit draws each tab as a div with role="tab" and its own underline element) */
[data-testid="stTabs"] [role="tablist"] {{ gap: 8px; border-bottom: 0; }}
[data-testid="stTab"] .react-aria-SelectionIndicator {{ display: none; }}
[data-testid="stTab"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 999px; padding: 4px 16px; height: auto; cursor: pointer;
}}
[data-testid="stTab"]:hover {{ border-color: {GREEN}; }}
[data-testid="stTab"][aria-selected="true"] {{ background: {GREEN}; border-color: {GREEN}; }}
[data-testid="stTab"][aria-selected="true"] p {{ color: #04210e; font-weight: 700; }}

/* primary buttons and the cards around expanders */
button[kind="primary"], button[data-testid="stBaseButton-primary"] {{
  background: linear-gradient(135deg, {GREEN}, #14b24c); color: #04210e; border: 0; border-radius: 999px; font-weight: 700;
}}
button[kind="primary"] p, button[data-testid="stBaseButton-primary"] p {{ color: #04210e; }}
[data-testid="stExpander"] details {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
</style>"""


def inject_theme():
    st.markdown(CSS, unsafe_allow_html=True)
