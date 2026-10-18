import os
import shutil
import subprocess
import sys

from prefect import flow, task
from prefect.schedules import Cron

# Reuse the exact same functions from ingest.py - no duplicate logic
from ingest import (
    fetch_recently_played,
    transform,
    load,
    get_unique_artists,
    fetch_and_load_artist_genres,
    load_covers,
)
from ingest_features import run as fetch_audio_features


def dbt_executable():
    """The dbt that belongs to this Python. Found next to the interpreter, so it works even when the venv isn't
    activated (for example when the flow is started from a script or a scheduled task)."""
    sibling = os.path.join(os.path.dirname(sys.executable), "dbt.exe" if os.name == "nt" else "dbt")
    return sibling if os.path.exists(sibling) else (shutil.which("dbt") or "dbt")


@task(retries=2, retry_delay_seconds=30)
def ingest_task():
    raw_tracks = fetch_recently_played()
    load(transform(raw_tracks))
    # Tag any artists we haven't seen before. The earlier version of this flow skipped this step,
    # so artists first heard on a scheduled or flow-driven run never got genres.
    fetch_and_load_artist_genres(get_unique_artists(raw_tracks))
    # Album covers for the dashboard's hover cards (best effort: a cover lookup failure shouldn't fail the run)
    try:
        load_covers(raw_tracks)
    except Exception as exc:
        print(f"Cover fetch failed, continuing without it: {exc}")


@task
def audio_features_task():
    # Best effort: a ReccoBeats outage should not stop dbt from running on the data we already have.
    try:
        fetch_audio_features()
    except Exception as exc:
        print(f"Audio feature fetch failed, continuing without it: {exc}")


@task(retries=1)
def dbt_run_task():
    result = subprocess.run(
        [dbt_executable(), "run"],
        cwd="spotify_dbt",
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        raise Exception(f"dbt run failed:\n{result.stderr}")


@task(retries=1)
def dbt_test_task():
    result = subprocess.run(
        [dbt_executable(), "test"],
        cwd="spotify_dbt",
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        raise Exception(f"dbt test failed:\n{result.stderr}")


@flow(name="spotify-daily-pipeline")
def spotify_pipeline():
    ingest_task()
    audio_features_task()
    dbt_run_task()
    dbt_test_task()


if __name__ == "__main__":
    spotify_pipeline.serve(
        name="spotify-daily-deployment",
        schedule=Cron("0 20 * * *", timezone="Asia/Kolkata"),  # daily at 8:00 PM IST
    )
