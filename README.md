# Spotify Mood Pipeline

An end-to-end data pipeline that turns Spotify listening history into a daily "mood" signal.

**Fetch → land in Postgres → transform with dbt → orchestrate with Prefect → visualize with Streamlit.**

## Architecture

```
Spotify API (recently played) ──┐
                                 ├──▶ ingest.py ──▶ Postgres (raw schema)
Last.fm API (artist genres) ────┘                        │
                                                       dbt models
                                                           │
                                          Postgres (dbt\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_dev schema) ──▶ Streamlit dashboard
                                                           ▲
                                               Prefect schedules + orchestrates
                                               Docker Compose runs Postgres
```

## What it does

* Pulls recently played tracks from the Spotify API daily
* Enriches each track's artist with genre tags from Last.fm
* Maps genres to one of four mood categories (`calm`, `mellow`, `intense`, `upbeat`) via a hand-curated dbt seed
* Rolls plays up into daily listening stats and a daily "dominant mood"
* Surfaces "Discovered recently" — tracks new to the listening history in the last 7 days that have already been replayed
* Lets the user like tracks from the discovery list, persisted back to Postgres from the dashboard itself
* Displays it all on an interactive Streamlit dashboard, with an animated mood chart and smooth in-page navigation
* Runs unattended on a daily schedule via Prefect, with retries and dbt tests guarding data quality



## A real API surprise along the way

The original plan was to use Spotify's audio-features endpoint (valence, energy, danceability) to derive mood directly. Spotify deprecated that endpoint for all new apps in November 2024, with no official replacement. Spotify's artist `genres` field which the API docs still describe and has also been silently returning empty/null for most artists as of 2025-2026.

The pipeline pivoted to Last.fm's community-tagged artist genres instead, paired with a hand-built genre→mood mapping (`seeds/genre\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_mood\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_map.csv`) reflecting the genres actually present in the listening history.

## Tech stack

|Tool|Role|
|-|-|
|Python (`spotipy`, `requests`)|API ingestion|
|PostgreSQL (Docker)|Storage|
|dbt|Transformation, testing, documentation|
|Prefect|Orchestration \& scheduling|
|Streamlit + Plotly|Dashboard|
|Last.fm API|Genre data (Spotify's own genre/audio-feature endpoints are dead for new apps)|

## Project structure

```
spotify-pipeline/
├── ingest.py                  # fetch → transform → load (Spotify + Last.fm)
├── pipeline\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_flow.py           # Prefect flow: ingest → dbt run → dbt test
├── dashboard.py                # Streamlit dashboard
├── docker-compose.yml          # Postgres container
└── spotify\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_dbt/
    ├── seeds/genre\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_mood\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_map.csv       # hand-curated genre → mood mapping
    └── models/
        ├── staging/
        │   ├── stg\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_recently\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_played.sql
        │   └── stg\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_artist\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_moods.sql
        └── marts/
            ├── daily\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_listening\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_summary.sql
            ├── daily\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_mood\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_summary.sql
            └── daily\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_dominant\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_mood.sql
```

User-generated data
---



`liked\_tracks` is a Postgres table written to directly by the Streamlit dashboard (not managed by dbt) — it stores songs the user has liked from the "Discovered recently" section. Unlike the dbt-managed marts, which are fully re-derived from raw data on every run, this table holds durable user state that persists independently of the pipeline.



## Data quality

11 dbt tests cover the core models: not-null checks on key fields, a composite-uniqueness check on `(played\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_at, track\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_id)` to guarantee the ingest is idempotent, and `accepted\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_values` checks that `mood` can only ever be one of the four defined categories.

## Setup

1. Clone the repo, create a venv, `pip install -r requirements.txt`
2. Create a Spotify Developer app and a Last.fm API account; copy `.env.example` to `.env` and fill in credentials`docker compose up -d` to start Postgres
3. `python ingest.py` to run a first fetch
4. `cd spotify\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_dbt \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\&\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\& dbt seed \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\&\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\& dbt run \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\&\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\& dbt test`
5. `streamlit run dashboard.py`
6. Optionally: `python pipeline\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\_flow.py` to serve the daily-scheduled version via Prefect

## Known limitations

* Spotify's "recently played" endpoint only returns the last 50 plays and the pipeline needs to run at least once a day to avoid gaps for heavy listeners
* Genre coverage depends on Last.fm's community tagging; smaller/independent artists are sometimes untagged
* The scheduled run depends on a local Prefect server + serving process staying open — not yet running as a background service (e.g. Windows Task Scheduler or Docker service)
* Prefect's own metadata is stored in a dedicated Postgres database (`prefect\\\\\\\\\\\\\\\_meta`) rather than its SQLite default, after a SQLite lock-contention bug caused a scheduled run to silently fail ("Late" state) under concurrent access from the server, UI, and worker process simultaneously

