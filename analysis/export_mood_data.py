"""Write the two mood-comparison tables to CSV for the validation script.

    python analysis/export_mood_data.py

Needs dbt to have built mood_comparison_track and mood_comparison_artist. Output goes to analysis/output/
(git-ignored).
"""
import os
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
TABLES = ("mood_comparison_track", "mood_comparison_artist")


def main():
    conn_str = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    engine = create_engine(conn_str)
    os.makedirs(OUT_DIR, exist_ok=True)
    for table in TABLES:
        df = pd.read_sql(f"SELECT * FROM dbt_dev.{table}", engine)
        path = os.path.join(OUT_DIR, f"{table}.csv")
        df.to_csv(path, index=False)
        print(f"{table}: {len(df)} rows -> {path}")


if __name__ == "__main__":
    sys.exit(main())
