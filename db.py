"""Shared Streamlit helpers: the cached database engine and IST time conversion."""
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

IST = "Asia/Kolkata"


@st.cache_resource
def get_engine():
    conn_str = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    # pre_ping + recycle: a database restart (e.g. Docker closed and reopened) would otherwise leave the
    # cached connection broken and every query failing with PendingRollbackError until Streamlit restarts.
    return create_engine(conn_str, pool_pre_ping=True, pool_recycle=300)


def to_ist(series):
    """pandas reads timestamptz as UTC, so convert explicitly before taking dates or times."""
    return pd.to_datetime(series, utc=True).dt.tz_convert(IST)


def ist_day_label(series):
    return to_ist(series).dt.strftime("%b %d")
