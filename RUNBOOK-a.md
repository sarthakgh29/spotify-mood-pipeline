# Runbook: Terminal Setup

How to start, use, and stop every part of the Spotify Mood Pipeline.

## Overview

| # | Component | Terminal | Stays open? | Needed for |
|---|---|---|---|---|
| 0 | Docker Desktop + Postgres | Any (one-off) | No | Everything |
| 1 | Prefect server | Terminal 1 | Yes | Scheduling + Prefect UI |
| 2 | Prefect serving process | Terminal 2 | Yes | The daily 8 PM scheduled run |
| 3 | Streamlit dashboard | Terminal 3 | Yes | Viewing the dashboard |
| 4 | Manual refresh | Terminal 4 | No (exits when done) | Fetching fresh data on demand |

Terminals 1 to 3 run continuously and will look "hung". That is expected, because they are servers. Open a new terminal for any other command.

## Rule for every new terminal

Every terminal needs these two lines first, except Step 0:

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1
```

Confirm `(venv)` appears at the start of the prompt. Most "command not found" errors come from skipping this.

---

## Step 0: Docker and Postgres

Run once after every restart. Start Docker Desktop first and wait for "Engine running".

```powershell
cd C:\dev\spotify-pipeline
docker compose up -d
docker ps
```

`docker ps` should list `spotify_postgres` with a status starting with `Up`.

Everything below depends on this. Prefect, dbt, ingest and the dashboard all connect to this container.

---

## Terminal 1: Prefect server

Hosts the Prefect UI and stores run history in the `prefect_meta` database.

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1
prefect server start
```

- UI: http://127.0.0.1:4200
- Leave it running.
- Start this before Terminal 2.

## Terminal 2: Prefect serving process

Registers the deployment and picks up scheduled runs (daily at 8:00 PM IST).

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1
python pipeline_flow.py
```

- Expected output: "Your flow 'spotify-daily-pipeline' is being served and polling for scheduled runs!"
- Leave it running.
- If this terminal is closed, or the laptop sleeps at 8 PM, the run shows as "Late" in the UI and does not execute.

## Terminal 3: Streamlit dashboard

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1
streamlit run dashboard.py
```

- URL: http://localhost:8501
- Data is cached for 5 minutes. For instant updates, use the menu (top right) and choose Clear cache, then refresh.
- Editing `dashboard.py` while it runs auto-reloads in the browser.

## Terminal 4: Manual data refresh

Runs the same steps as the scheduled run: ingest, `dbt run`, `dbt test`. It exits when finished.

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1
python -c "from pipeline_flow import spotify_pipeline; spotify_pipeline()"
```

Do not use `python pipeline_flow.py` for this. That starts the serving process and never exits.

Individual steps, if needed:

```powershell
python ingest.py
cd spotify_dbt
dbt run
dbt test
```

---

## Start order

1. Docker Desktop
2. `docker compose up -d`
3. Terminal 1 (Prefect server)
4. Terminal 2 (Prefect serving process)
5. Terminal 3 (Streamlit)

Skip Terminals 1 and 2 if you only want to view the dashboard or run a manual refresh. They are only needed for scheduling.

## Stop order

1. Press `Ctrl+C` in Terminal 3, then Terminal 2, then Terminal 1.
2. Optional: `docker compose stop` to stop Postgres. Data is kept in a Docker volume.

## Quick checks

| Check | Command |
|---|---|
| Postgres running | `docker ps` |
| Latest ingested play | `docker exec -it spotify_postgres psql -U spotify_user -d spotify_data` then `SELECT max(ingested_at) FROM raw_recently_played;` |
| Prefect config | `prefect config view` |
| Scheduled runs | http://127.0.0.1:4200, then Deployments |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `dbt` / `prefect` / `streamlit` not recognized | venv not active | Run `venv\Scripts\Activate.ps1` |
| `ConnectionRefusedError` when starting Prefect | Postgres container not running | Start Docker Desktop, then `docker compose up -d` |
| Docker "cannot find the file specified" on `docker_engine` | Docker Desktop not running | Open Docker Desktop, wait for "Engine running" |
| Scheduled runs marked "Late" | Terminal 2 closed or laptop asleep at 8 PM | Restart Terminal 2, keep the laptop awake and plugged in |
| Dashboard shows old numbers | 5-minute cache | Clear cache from the menu, then refresh |
| Gaps in daily charts | Spotify only returns the last 50 plays | Run the pipeline more often. Missed plays cannot be recovered |
| Terminal appears frozen | Server process is running (expected) | Open a new terminal for other commands |

## Credentials

Stored in `.env` (never committed). See `.env.example` for the required variables. If `.spotify_cache` is deleted, the next `python ingest.py` opens a browser to re-authorise Spotify.
