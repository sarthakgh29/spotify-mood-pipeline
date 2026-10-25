# How the Spotify Mood Pipeline works

A guide for understanding the whole project from the ground up: Docker, PostgreSQL, the pipeline code, dbt, Prefect, the
dashboard, the problems that came up and how they were solved, and how the project was built.

It is written to be read top to bottom, but each section also stands alone. Real file names, real code and real numbers are
used throughout, so you can open the file next to this guide and follow along.

**Contents**

1. [The 60-second version](#1-the-60-second-version)
2. [The big picture: one play, start to finish](#2-the-big-picture-one-play-start-to-finish)
3. [Folder map](#3-folder-map)
4. [Docker](#4-docker)
5. [PostgreSQL](#5-postgresql)
6. [The pipeline code (ingest)](#6-the-pipeline-code-ingest)
7. [dbt](#7-dbt)
8. [Prefect: the flow and the server](#8-prefect-the-flow-and-the-server)
9. [Running everything day to day](#9-running-everything-day-to-day)
10. [How a mood is decided](#10-how-a-mood-is-decided)
11. [The dashboard layer](#11-the-dashboard-layer)
12. [Challenges and how each was solved](#12-challenges-and-how-each-was-solved)
13. [How it was made, in order](#13-how-it-was-made-in-order)
14. [Cheat sheet and "if X breaks"](#14-cheat-sheet-and-if-x-breaks)
15. [Glossary](#15-glossary)

---

## 1. The 60-second version

Every song you play on Spotify is a row of data. This project collects those rows, stores them, turns them into a
**mood** for each day, and shows the result on a dashboard.

```
fetch  ->  store  ->  transform  ->  schedule  ->  show
Python     Postgres    dbt            Prefect       Streamlit
(Docker runs Postgres)
```

- **Python scripts** call the Spotify, Last.fm and ReccoBeats web APIs and write what they get into database tables.
- **PostgreSQL** (running inside **Docker**) holds all the data.
- **dbt** is a set of SQL files that clean the raw data and compute things like "daily dominant mood". It also runs tests.
- **Prefect** runs the whole chain automatically every evening at 8 PM IST and shows you whether it worked.
- **Streamlit** is the dashboard you open in the browser.

Spotify only remembers your last 50 plays, so the pipeline's main job is to keep catching them before they fall off.

A second, bigger data source was added later: Spotify's **Extended Streaming History** export (about 86,000 plays going back
to 2020). It feeds the Lifetime Wrapped pages.

---

## 2. The big picture: one play, start to finish

Say you play a song at 6:52 PM. This is everything that happens to it.

```
  You play "Song X"
        |
        v
  Spotify remembers it (only the last 50 plays)
        |
        |  python ingest.py        (or the Prefect flow, daily at 8 PM)
        v
  1. ingest.py asks Spotify: "what did I play recently?"        -> raw_recently_played
  2. For each artist it hasn't seen, asks Last.fm for genre tags -> raw_artist_genres
  3. Saves album covers                                          -> track_covers
  4. ingest_features.py asks ReccoBeats for valence/energy       -> raw_track_features
        |
        |  dbt run   (SQL files turn raw tables into clean views)
        v
  stg_recently_played, stg_artist_moods, stg_track_features ...   (staging: tidy copies)
  play_mood_comparison, daily_mood_summary, daily_blended_mood ... (marts: answers)
        |
        |  dbt test  (60+ checks: no nulls, no duplicates, moods are one of four values ...)
        v
  Streamlit reads the marts and draws charts, tables and the "Today's vibe" banner
```

Three things to notice:

1. **Raw data is never edited.** Scripts only add rows to `raw_*` tables. Everything clever happens later, in SQL, where you
   can change your mind and re-run without losing anything.
2. **Every step can be re-run safely.** Inserting the same play twice does nothing (section 5), so a repeated run is harmless.
3. **The steps are separate on purpose.** If ReccoBeats is down, the flow still runs dbt on the data it already has.

---

## 3. Folder map

```
spotify-pipeline/
|-- docker-compose.yml        Docker: how to run Postgres
|-- sql/init.sql              Creates every raw table (runs the first time Postgres starts)
|-- .env                      Your secrets and settings (never committed)
|-- ingest.py                 Fetch plays, artist genres, covers from Spotify + Last.fm
|-- ingest_features.py        Fetch valence/energy (and 7 other ratings) from ReccoBeats (--history for the whole export)
|-- mood_playlists.py         Pick songs per mood from the whole history and create Spotify playlists
|-- pipeline_flow.py          The Prefect flow: ingest -> audio features -> dbt run -> dbt test
|-- covers.py                 Album-cover helpers (Spotify oEmbed)
|-- spotify_dbt/              The dbt project (all the SQL transformations)
|   |-- dbt_project.yml, packages.yml, profiles.yml.example
|   |-- seeds/                CSV files dbt loads as tables (genre_mood_map.csv ...)
|   |-- macros/audio_mood.sql A reusable SQL snippet
|   `-- models/staging, models/marts   The SQL models + their tests (.yml)
|-- dashboard.py + views/     The Streamlit app (router + one file per page)
|-- db.py, track_ui.py, theme.py   Shared dashboard helpers
|-- wrapped.py, import_history.py, history_covers.py, globe_*.py, card_image.py, playlists.py
|                             Lifetime Wrapped, song globe, card download, playlist export
|-- ai_labeler.py, ingest_llm_moods.py, mood_stats.py, lookup.py   Mood Lab / statistics
|-- tests/                    Python unit tests
|-- analysis/                 Validation scripts (Python + Stata)
|-- start_all.ps1 (+ .bat)    One command that starts everything (local only, not in git)
`-- README.md, CHANGES.md, RUNBOOK-a.md, docs/   Documentation
```

---

## 4. Docker

### 4.1 The idea

Postgres is a program. You *could* install it on Windows like any other program, but then its version, its settings and its
files are tangled up with your computer. **Docker** lets you run Postgres inside an isolated box instead:

- An **image** is a frozen recipe for a box ("Postgres 16, ready to go"). You download it once.
- A **container** is a running box made from an image. You can stop, delete and recreate containers freely.
- A **volume** is a folder that lives *outside* the box, managed by Docker. **The container is disposable; the volume is
  your data.** If you delete the container the data survives, because it is in the volume.
- **Docker Compose** lets you describe all of that in one file (`docker-compose.yml`) and start it with one command.

> Rule of thumb: containers are disposable, volumes are the data. Never delete a volume unless you are sure.

### 4.2 Your file, line by line

```yaml
name: spotifydatapipeline        # the "project" name; it also names the volume (see 4.4)

services:
  postgres:
    image: postgres:16           # which recipe: PostgreSQL version 16
    container_name: spotify_postgres
    restart: unless-stopped      # start again automatically when Docker starts
    environment:                 # first-start settings: creates this user, password and database
      POSTGRES_USER: spotify_user
      POSTGRES_PASSWORD: spotify_pass
      POSTGRES_DB: spotify_data
    ports:
      - "5432:5432"              # host port : container port. Python on Windows connects to localhost:5432
    volumes:
      - pgdata:/var/lib/postgresql/data                              # the data folder lives in the volume
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro       # a script Postgres runs on first start

volumes:
  pgdata:                        # declares the volume
```

Things worth understanding:

- **`ports: "5432:5432"`** is the door between your computer and the box. Without it, your Python scripts could not reach
  the database.
- **`/docker-entrypoint-initdb.d/`** is a special folder in the Postgres image: any `.sql` file in it runs **once, the very
  first time the database starts with an empty data folder**. That is how `sql/init.sql` creates the tables. It does *not*
  run again on later starts. (To add a table to an existing database you run the SQL by hand, see 5.5.)
- **`restart: unless-stopped`** means that after a reboot, once Docker Desktop is up, Postgres comes back by itself.
- The user and password here are for a local-only database that is not exposed to the internet.

### 4.3 The commands you actually use

| Command | What it does |
|---|---|
| `docker compose up -d` | Create/start the container in the background |
| `docker ps` | List running containers (look for `spotify_postgres` with `Up`) |
| `docker ps -a` | List all containers, including stopped ones |
| `docker start spotify_postgres` | Start an existing stopped container |
| `docker stop spotify_postgres` | Stop it (data stays) |
| `docker exec -it spotify_postgres psql -U spotify_user -d spotify_data` | Open a SQL prompt inside the box |
| `docker volume ls` | List volumes (yours is `spotifydatapipeline_pgdata`) |
| `docker logs spotify_postgres` | Read the database's own log |

### 4.4 The volume-name problem (and the fix)

Docker Compose names a volume `<project name>_<volume name>`. If you do not set `name:`, the project name comes from the
**folder name**. That caused a real problem: the project folder had been moved/renamed earlier, so Compose looked for a volume
with a different name than the one holding the data, and an old container with the same name `spotify_postgres` clashed.
It would have started a fresh, **empty** database without any warning.

The fix is the very first line of the file: `name: spotifydatapipeline`. Now the volume is always
`spotifydatapipeline_pgdata`, whatever the folder is called. Before changing it, a full backup was taken (`backups/`), and
after recreating the container the row counts were compared and matched exactly.

### 4.5 Backing up and restoring

```powershell
# backup: dump the whole database to a file (do this before anything risky)
docker exec spotify_postgres pg_dump -U spotify_user spotify_data > backups\spotify_data.sql

# restore into an empty database
docker exec -i spotify_postgres psql -U spotify_user -d spotify_data < backups\spotify_data.sql
```

---

## 5. PostgreSQL

### 5.1 What it is

A database that stores data in **tables** (like spreadsheets with strict column types) and answers questions written in
**SQL**. Postgres is the "store" in the pipeline: every script writes into it, dbt reads and reshapes it, the dashboard
reads the results.

### 5.2 Two databases, several schemas

One Postgres server holds more than one database:

| Database | Used by | What is in it |
|---|---|---|
| `spotify_data` | the pipeline, dbt, the dashboard | all your data |
| `prefect_meta` | Prefect | Prefect's own records (runs, logs, schedules) |

Inside `spotify_data` there are two **schemas** (folders for tables):

| Schema | Who writes it | Contents |
|---|---|---|
| `public` | Python scripts (and the dashboard for likes/labels) | the **raw** tables, listed below |
| `dbt_dev` | dbt | everything dbt builds: staging views, marts, seeds |

### 5.3 The raw tables (all created by `sql/init.sql`)

| Table | One row per | Written by | Notes |
|---|---|---|---|
| `raw_recently_played` | play | `ingest.py` | primary key `(played_at, track_id)` |
| `raw_artist_genres` | artist | `ingest.py` | `genres` is an array of Last.fm tags |
| `raw_track_features` | track | `ingest_features.py` | valence, energy and 7 more ratings; `status` is `found` or `not_found` |
| `track_covers` | track | `covers.py`, `history_covers.py`, `globe_covers.py` | album cover URL |
| `liked_tracks` | liked track | the dashboard | |
| `raw_llm_moods` | track + model + prompt | `ingest_llm_moods.py` | Gemini's mood labels |
| `mood_labels` | track | the dashboard (Mood Lab) | your own hand labels = the "ground truth" |
| `raw_streaming_history` | play | `import_history.py` | the 86,000-play Extended Streaming History |

As of 25 Oct 2026: 441 pipeline plays, 129 artists with genres, 193 tracks with audio data, over 2,000 covers, 85,839
history plays and 61 hand labels.

### 5.4 Four Postgres ideas that the project relies on

**1. A primary key makes duplicates impossible.**
`PRIMARY KEY (played_at, track_id)` means the same song at the same instant can exist only once. Combined with
`INSERT ... ON CONFLICT (played_at, track_id) DO NOTHING`, re-running the ingest never creates duplicates. This property
("run it twice, same result") is called **idempotency** and it is what makes the whole pipeline safe to re-run.

**2. `timestamptz` plus a database time zone.**
Times are stored as `TIMESTAMPTZ` (a moment in time, stored in UTC). `init.sql` runs
`ALTER DATABASE spotify_data SET timezone TO 'Asia/Kolkata'`, so when SQL says `date_trunc('day', played_at)` ("which
day was this?") it uses **IST days**, not UTC days. Without this, a play at 11 PM IST would be counted as the next day's.
(Python's pandas reads timestamps as UTC, so the dashboard converts explicitly with `to_ist()` in `db.py`.)

**3. Array columns.**
`raw_artist_genres.genres` is `TEXT[]`, e.g. `{"punjabi","hip hop","pop"}`. dbt later "unnests" it into one row per tag with
`unnest(genres)`.

**4. Upserts.**
`ON CONFLICT (track_id) DO UPDATE SET ...` (used in `ingest_features.py`) means "insert, or update the existing row if the
key already exists".

### 5.5 psql cheat sheet (open with the `docker exec -it ... psql` command from 4.3)

```sql
\dt                         -- list tables in the current schema
\dt dbt_dev.*               -- list tables/views dbt built
\d raw_recently_played      -- describe a table
select count(*) from raw_recently_played;
select * from dbt_dev.daily_dominant_mood limit 5;
\q                          -- quit
```

To add the tables to a database that already exists (init.sql only runs on a fresh volume):

```powershell
docker exec -i spotify_postgres psql -U spotify_user -d spotify_data < sql/init.sql
```

Every statement in it is safe to repeat, except the final `CREATE DATABASE prefect_meta`, which just reports "already
exists" (harmless).

### 5.6 How Python talks to Postgres

- Scripts use **psycopg2** with the settings in `.env` (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
- The dashboard uses **SQLAlchemy** (`db.py`) with `pool_pre_ping=True` and `pool_recycle=300`. That means a stale
  connection (after Docker was restarted, say) is detected and replaced instead of making every page fail.

---

## 6. The pipeline code (ingest)

### 6.1 `ingest.py`: Spotify plays, Last.fm genres, covers

It is a small script of plain functions run in this order at the bottom:

```python
raw_tracks = fetch_recently_played()        # 1. ask Spotify
load(transform(raw_tracks))                 # 2. flatten and store
fetch_and_load_artist_genres(get_unique_artists(raw_tracks))   # 3. genres for new artists
load_covers(raw_tracks)                     # 4. album covers
```

**Authentication.** `SpotifyOAuth(... scope="user-read-recently-played", cache_path=".spotify_cache")`. The first run opens a
browser so you can approve access; Spotify returns a token that is saved in `.spotify_cache` and refreshed automatically
after that. That file is a secret and is git-ignored (see challenge #3 in section 12).

**1. `fetch_recently_played()`** calls `sp.current_user_recently_played(limit=50)`. 50 is Spotify's hard maximum. That is
why the pipeline has to run regularly: plays older than the last 50 are gone for good.

**2. `transform(tracks)`** turns Spotify's nested JSON into flat tuples that match the table columns:

```python
(item["played_at"], track["id"], track["name"],
 ", ".join(a["name"] for a in track["artists"]),   # all artist names as one text
 track["artists"][0]["id"],                        # the primary artist's Spotify id
 track["album"]["name"], track["duration_ms"])
```

**3. `load(rows)`** inserts them with `execute_values` (one fast bulk statement) and
`ON CONFLICT (played_at, track_id) DO NOTHING`. It prints "Inserted N new play rows (out of M fetched)", so you can see how
many were genuinely new.

**4. Genres: `fetch_and_load_artist_genres`.** First it asks the database which artist ids it already has, then calls Last.fm
only for the new ones. Last.fm's `artist.gettoptags` returns community tags with a popularity count. The code keeps tags
with `count >= 10` and at most 5 of them, to drop noisy one-person tags. It sleeps 0.25 s between calls to stay under
Last.fm's rate limit.

**5. Covers.** `load_covers` stores the album-cover URL that came inside Spotify's payload, and for older tracks without one,
asks Spotify's keyless **oEmbed** endpoint (`covers.py`). Only Spotify's image hosts are accepted (`is_allowed_cover_url`), so
a bad response can never put a strange URL into the dashboard.

### 6.2 `ingest_features.py`: ReccoBeats audio data

ReccoBeats is a free API that returns **valence** (how positive a song sounds) and **energy** (how intense), both 0 to 1,
plus danceability, acousticness, tempo and more. It replaced the Spotify endpoint that was shut down (section 12, #1).

How it works:

1. `get_pending_track_ids` finds every played track with no stored result, plus earlier misses older than 3 days.
2. Tracks are sent **40 at a time** (bigger batches return HTTP 400) as a repeated parameter: `?ids=A&ids=B&...`.
3. **Matching the answer to the question.** ReccoBeats does not return records in request order and uses its own ids, so each
   returned record is matched by the **Spotify track id found inside its `href` URL** (`candidate_ids`). If a record has only
   ReccoBeats' id, a second call (`/track`) resolves it. The order of results is never trusted.
4. `parse_features` accepts a record only if valence and energy are numbers between 0 and 1.
5. A track ReccoBeats genuinely does not know is stored as `status = 'not_found'`, so it is not asked again every run; it is
   retried after 3 days in case ReccoBeats added it. A failed *batch* (network error, HTTP 429) is not saved at all, so it is
   retried next run.
6. Rate limits: on HTTP 429 the script reads `Retry-After` and waits.
7. `--probe` mode tests the request formats on 20 tracks and writes nothing: this is how the API's quirks were discovered.

**Looking up the whole history (`--history`).** By default the script only asks about tracks the pipeline has seen being played.
`python ingest_features.py --history` instead asks about every song in `raw_streaming_history` (about 6,600 distinct songs),
**most played first**, so a stopped run has already covered the songs that matter. `get_pending_track_ids(..., source=...)` takes
`"plays"` (default), `"history"` or `"all"`; the rest of the script is unchanged, and songs already stored are not asked again.
`--limit 500` does only the 500 most played. Results are stored in the same `raw_track_features` table, so every page benefits.

Coverage is partial: ReccoBeats knows roughly half of your tracks and far fewer 2025-26 releases. That is a limitation of
the data source, not a bug, and it is why the dashboard always shows how much of the data a mood chart covers.

### 6.3 The other scripts, in one line each

| Script | Job |
|---|---|
| `covers.py` | Cover helpers: validate URLs, oEmbed lookup, save to `track_covers` |
| `import_history.py` | Read the Extended Streaming History export (folder or zip) into `raw_streaming_history`. Music plays only; **IP address and country are never stored** |
| `history_covers.py`, `globe_covers.py` | Fill `track_covers` for songs the Wrapped page and the globe show; wait and retry when Spotify rate-limits |
| `ingest_llm_moods.py` + `ai_labeler.py` | Ask Gemini to label moods; store in `raw_llm_moods` |
| `playlists.py` | Create a Spotify playlist from track ids (after a one-time permission step) |
| `wrapped.py` | Pure-pandas functions behind Lifetime Wrapped (top songs, streaks, discovery, ...), covered by tests |
| `globe_data.py` | Builds the 2-D "song map" (sessions -> embedding -> t-SNE) for the Song Globe |
| `card_image.py` | Draws the Wrapped card as a PNG for the download button |

---

## 7. dbt

### 7.1 The idea

After the scripts load raw data, it is messy: one row per play, genres in arrays, moods not yet decided. **dbt** (data build
tool) is where raw data becomes useful. You write each transformation as a `SELECT` statement in its own `.sql` file; dbt
runs them in the right order and creates a view (or table) for each one. dbt does not move data around; it only runs SQL
inside Postgres.

Why not just write the SQL in Python? Because dbt gives you, for free:

- **Dependencies:** `{{ ref('other_model') }}` tells dbt "I need that model first", so the order is worked out automatically.
- **Tests:** declare "this column is never null" in a YAML file and dbt checks it.
- **Documentation and lineage:** the model graph is known.
- **Repeatability:** change one file, run `dbt run`, everything downstream is rebuilt.

### 7.2 Layers

```
sources (raw_* tables)  ->  staging (stg_*)  ->  marts (daily_*, play_*, mood_*)  ->  dashboard
```

- **Sources** (`sources.yml`) declare which raw tables exist. SQL then says `{{ source('spotify_raw', 'raw_recently_played') }}`.
- **Staging** models are light clean-ups of one raw table each: rename, add a computed column, nothing clever.
- **Marts** are the answers: joins, aggregates, the mood logic. The dashboard reads these.

All models are **views**: the SQL is saved in Postgres and runs when something reads it. So new plays show up in the marts as
soon as they are inserted; `dbt run` is needed when the SQL itself changes (and the daily run re-creates everything and, with
`dbt test`, checks the data). Seeds, by contrast, are real tables.

### 7.3 The project files

| File | What it is |
|---|---|
| `spotify_dbt/dbt_project.yml` | Project name (`spotify_dbt`), which profile to use, folder locations |
| `~/.dbt/profiles.yml` (or `spotify_dbt/profiles.yml`, git-ignored; template: `profiles.yml.example`) | *How to connect*: Postgres at localhost:5432, user, password, database `spotify_data`, **schema `dbt_dev`**, 4 threads |
| `packages.yml` | Extra packages: `dbt-labs/dbt_utils` 1.3.0 (install with `dbt deps`) |
| `models/staging/sources.yml`, `sources_features.yml` | Declares the raw tables |
| `models/**/*.yml` | Descriptions and **tests** for models |
| `seeds/*.csv` | CSV files loaded as tables with `dbt seed` |
| `macros/audio_mood.sql` | A reusable SQL snippet (a "function" for SQL) |

### 7.4 Every model, in plain words

**Staging**

| Model | What it does |
|---|---|
| `stg_recently_played` | The raw plays plus `duration_minutes` (`duration_ms / 1000 / 60`) |
| `stg_artist_moods` | One mood per artist. Unnests the genre array, joins each tag to the `genre_mood_map` seed (ignoring `unclassified`), counts tags per mood and keeps the winning mood. **Ties are broken alphabetically** so the answer never changes between runs |
| `stg_track_features` | ReccoBeats data plus `has_features` (found, and valence and energy are present) |
| `stg_track_covers` | Cover URLs that exist |
| `stg_streaming_history` | The history export, plus `seconds_played` and `is_real_play` (a play of 30 seconds or more); songs in the `excluded_tracks` seed are left out |
| `stg_mood_labels` | Your hand labels |
| `stg_llm_moods` | The latest Gemini label per track and prompt variant |

**Marts**

| Model | What it answers |
|---|---|
| `daily_listening_summary` | Per day: plays, distinct tracks, distinct artists, minutes |
| `daily_top_track` | Per day: the most played track (ties broken by track id) |
| `daily_mood_summary` | Per day and mood: plays and minutes, using the **Last.fm genre mood** |
| `daily_dominant_mood` | Per day: the mood with the most minutes (genre-based) |
| `play_mood_comparison` | **One row per play with both moods**: `genre_mood` (artist-level) and `audio_mood` (track-level, from valence and energy) |
| `daily_audio_mood_summary` | Like `daily_mood_summary` but from the audio mood |
| `daily_blended_mood_summary` | Per play, **ReccoBeats first, Last.fm only where ReccoBeats has no data** (`coalesce(audio_mood, genre_mood)`); also records how many minutes came from audio. Feeds the "Today's vibe" banner |
| `mood_comparison_track`, `mood_comparison_artist` | Tracks/artists that have *both* moods, to compare the methods |
| `mood_method_eval` | Your hand-labelled tracks next to what each method said, so every method can be scored |
| `all_plays` | The history export plus pipeline plays that came after it ends, for Lifetime Wrapped |
| `history_song_moods` | **One row per song of the whole history that ReccoBeats has data for**: real plays, last played, valence, energy and its `audio_mood` (from the macro). Feeds the Mood Playlists page and `mood_playlists.py`. Tests: `track_id` unique and not null, mood is one of the four |

### 7.5 Seeds and the macro

**`genre_mood_map.csv`** is a hand-made lookup with two columns, `genre,mood`. It has 79 rows: 22 intense, 15 mellow, 11
upbeat, 6 calm and 25 `unclassified`. `unclassified` rows exist only to *ignore* tags that say nothing about mood (a
language, a nationality, "seen live"). A tag not in the file is ignored too. This file is the single most important piece of
"human knowledge" in the project: change a row, run `dbt seed && dbt run`, and every mood updates.

**`audio_mood` macro** (`macros/audio_mood.sql`) holds the valence/energy rule once so several models can use it:

```sql
case
  when energy >= 0.5 and valence >= 0.5 then 'upbeat'
  when energy >= 0.5                    then 'intense'
  when valence >= 0.5                   then 'calm'
  else                                       'mellow'
end
```

The 0.5 cut-offs can be changed without editing SQL: `dbt run --vars '{energy_threshold: 0.6, valence_threshold: 0.45}'`.

### 7.6 Tests

dbt reads the `.yml` files and runs one SQL query per test; a test passes if the query finds **zero bad rows**. This project
has more than 60. The kinds used:

| Test | Meaning | Count |
|---|---|---|
| `not_null` | this column is never empty | 28 |
| `accepted_values` | e.g. `mood` is only calm, mellow, intense or upbeat | 20 |
| `unique` | no duplicates | 8 |
| `dbt_utils.unique_combination_of_columns` | e.g. `(played_at, track_id)` is unique, which guards the idempotency from section 5 | 5 |
| `dbt_utils.accepted_range` | e.g. valence between 0 and 1 | 2 |

Tests are the safety net behind the nightly run: if bad data ever gets in, the Prefect run turns red instead of the dashboard
quietly showing wrong numbers.

### 7.7 Commands

Run them from inside `spotify_dbt/` with the venv active.

| Command | What it does |
|---|---|
| `dbt deps` | Install packages (`dbt_utils`) |
| `dbt seed` | Load the CSV seeds as tables |
| `dbt run` | Build every model |
| `dbt test` | Run all the tests |
| `dbt build` | seed + run + test, in dependency order (use this when unsure) |
| `dbt run -s daily_blended_mood_summary` | Just one model |
| `dbt run -s +play_mood_comparison` | That model and everything it depends on |

---

## 8. Prefect: the flow and the server

### 8.1 The idea

You could schedule `python ingest.py` with Windows Task Scheduler. **Prefect** adds what that does not give you: automatic
retries, a record of every run, logs, and a web page showing green or red. In Prefect:

- A **task** is one step (a Python function with `@task`).
- A **flow** is a function that calls tasks in order (`@flow`).
- A **deployment** is a flow plus a schedule.
- The **Prefect server** is the control room: it stores history and serves the UI at http://127.0.0.1:4200.
- A **serving process** (`python pipeline_flow.py`) is the worker that actually runs the flow when the schedule says so.

Two separate processes are needed, and both must stay running: the server (the UI and the database of runs) and the serving
process (the thing that executes the work). If the serving process is closed, a scheduled run shows as **Late** and never
executes. Neither restarts by itself after a reboot, and nothing fires while the laptop sleeps.

### 8.2 `pipeline_flow.py`, explained

```python
@task(retries=2, retry_delay_seconds=30)
def ingest_task():
    raw_tracks = fetch_recently_played()
    load(transform(raw_tracks))
    fetch_and_load_artist_genres(get_unique_artists(raw_tracks))
    try:
        load_covers(raw_tracks)
    except Exception as exc:
        print(f"Cover fetch failed, continuing without it: {exc}")
```

- It **reuses the exact functions from `ingest.py`**: no duplicated logic, so the script and the flow can never drift apart.
- `retries=2` means a flaky network gets two more tries, 30 seconds apart.
- Covers are *best effort*: a cover failure is printed but never fails the run.

```python
@task
def audio_features_task():
    try:
        fetch_audio_features()
    except Exception as exc:
        print(f"Audio feature fetch failed, continuing without it: {exc}")
```

A ReccoBeats outage must not stop dbt from working on the data already collected, so this step also swallows its errors.

```python
@task(retries=1)
def dbt_run_task():
    result = subprocess.run([dbt_executable(), "run"], cwd="spotify_dbt", capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        raise Exception(f"dbt run failed:\n{result.stderr}")
```

dbt is a command-line tool, so the task runs it with `subprocess`. If it exits with an error, the task raises an exception and
the Prefect run turns red. `dbt_test_task` is identical but runs `dbt test`: **a failing data test fails the run on purpose**.
`dbt_executable()` finds `dbt` next to the running Python, so it works even when the virtual environment is not activated (for
example when started from a script).

```python
@flow(name="spotify-daily-pipeline")
def spotify_pipeline():
    ingest_task()
    audio_features_task()
    dbt_run_task()
    dbt_test_task()
```

The order is the data's order: collect, enrich, transform, verify. If `ingest_task` still fails after its retries, the later
tasks do not run.

```python
if __name__ == "__main__":
    spotify_pipeline.serve(
        name="spotify-daily-deployment",
        schedule=Cron("0 20 * * *", timezone="Asia/Kolkata"),   # every day at 8:00 PM IST
    )
```

`Cron("0 20 * * *")` reads: minute 0, hour 20, every day, every month, every weekday. The `timezone` is passed to `Cron`
because `Flow.serve()` has no timezone option of its own.

### 8.3 Where Prefect keeps its memory

Prefect needs a database for its run history. The default is a SQLite file, which broke here (section 12, #4), so it is
pointed at Postgres, into the separate `prefect_meta` database:

```powershell
prefect config set PREFECT_API_DATABASE_CONNECTION_URL="postgresql+asyncpg://spotify_user:spotify_pass@localhost:5432/prefect_meta"
prefect config set PREFECT_API_URL=http://127.0.0.1:4200/api
prefect server start        # terminal 1, leave open
python pipeline_flow.py     # terminal 2, leave open
```

`asyncpg` is the database driver Prefect's server uses; that is why it is in `requirements.txt`.

### 8.4 Reading the Prefect UI

Open http://127.0.0.1:4200 and look at **Deployments** or **Flow runs**: each run lists its four tasks with a state
(Completed, Failed, Retrying, Late) and the printed log lines, such as "Inserted 0 new play rows (out of 50 fetched)".
To run it once right now without waiting for 8 PM, use **Quick run** on the deployment, or:

```powershell
python -c "from pipeline_flow import spotify_pipeline; spotify_pipeline()"
```

---

## 9. Running everything day to day

### 9.1 The one-click way

`refresh_dashboard.bat` (double-click) runs `start_all.ps1`, which, in order:

1. checks Docker Desktop is running and **starts it for you** if not (waiting up to 3 minutes for the engine),
2. starts the existing Postgres container if it is stopped (it only runs `docker compose up -d` if no container exists at all, so
   the data is safe), waits until Postgres accepts connections, and creates the `prefect_meta` database if it is missing,
3. starts the **Prefect server** if port 4200 is not listening,
4. starts the **serving process** (the 8 PM flow),
5. starts the **dashboard** on port 8501,
6. fetches the latest plays (`ingest.py`, `ingest_features.py`, `dbt run`),
7. restarts the dashboard so it shows the new data immediately (it caches queries for 5 minutes),
8. opens the browser.

Anything already running and healthy is left alone, so it is safe to run at any time. Useful switches:
`-SkipIngest`, `-DashboardOnly`, `-RestartDashboard`, `-Stop`, `-DryRun`. Background processes run hidden; their output goes to
`logs\<name>.out.log` and `logs\<name>.err.log`.

### 9.2 The manual way (what the script automates)

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1        # always first; "(venv)" must appear in the prompt
docker compose up -d             # Postgres
prefect server start             # terminal 1
python pipeline_flow.py          # terminal 2
streamlit run dashboard.py       # terminal 3
```

### 9.3 A healthy day

- 8 PM IST: Prefect runs the flow. Four green tasks.
- Any time: open http://localhost:8501.
- After a reboot: double-click `refresh_dashboard.bat` (it starts Docker Desktop too, which can take a minute or two).

The one weakness: if the laptop is asleep or the two Prefect processes are not running at 8 PM, that day's run is skipped and
plays beyond Spotify's last 50 are lost. Running `refresh_dashboard.bat` whenever you open the laptop closes most gaps.

---

## 10. How a mood is decided

The project's central idea: turn a song into one of **four moods**: *calm, mellow, intense, upbeat*. The four are a deliberate,
fixed vocabulary (they are meant to be shared later with images, so no fifth mood is added).

There are three ways to get a mood, and they are kept side by side so they can be compared honestly.

**A. Genre mood (Last.fm).** Artist level: every song by an artist gets the same mood. Last.fm tags -> `genre_mood_map` seed ->
the mood with the most matching tags.
*Strength:* covers almost every artist. *Weakness:* an artist is not a song, and the tag-to-mood table is hand-made.

**B. Audio mood (ReccoBeats).** Track level: the song's own valence (sad to happy) and energy (calm to intense) decide the
quadrant:

```
              energy high            energy low
valence high   upbeat                 calm
valence low    intense                mellow
```

*Strength:* it measures the actual song. *Weakness:* ReccoBeats knows only about half of your tracks, and about 60% of audio
labels sit within 0.10 of a cut-off, so they are fragile.

**C. AI mood (Gemini).** The model is given the title, artists, tags and (in one variant) the ReccoBeats numbers, and returns a
mood with a reason. Optional, and not part of the daily run.

**Scoring them: Mood Lab.** The Mood Lab page lets you label songs **blind** (no method's guess is shown) and then scores each
method against your labels with agreement % and **Cohen's kappa** (agreement beyond chance). On 60 labels:

| Method | Agreed with you |
|---|---|
| Audio rule (ReccoBeats), on the songs it covers | 72% |
| Gemini (two variants) | 55% and 53% |
| Last.fm genre | 38% (about the same as always guessing "upbeat") |

That result is why the "Today's vibe" banner now uses the **blended** mood: for each play, the audio mood if ReccoBeats has the
song, otherwise the Last.fm mood. It takes the better method where it exists and still covers every song.

---

## 11. The dashboard layer

### 11.1 Structure

- `dashboard.py` is the **router**: it sets the page title, injects the theme and registers the pages with `st.navigation`
  (a tab bar across the top). The tab order is Dashboard, Lifetime Wrapped, Song Globe, Mood Playlists, then the two
  analysis pages, Mood Comparison and Mood Lab, at the end.
- Each page is a file in `views/`: `0_Dashboard.py`, `2_Method_Comparison.py`, `4_Mood_Lab.py`, `5_Lifetime_Wrapped.py`,
  `6_Song_Globe.py`, `7_Mood_Playlists.py`. The folder is named `views`, not `pages`, on purpose (section 12, #16).
- Shared helpers: `db.py` (cached database engine, IST conversion), `track_ui.py` (song links, hover cards, cover thumbnails),
  `theme.py` (the dark gradient look, applied once for all pages).

### 11.2 How a page gets its data

The main page loads everything in one cached function:

```python
@st.cache_data(ttl=300)        # remember the result for 5 minutes
def load_data():
    ...pd.read_sql("SELECT * FROM dbt_dev.daily_dominant_mood ...", engine)
```

`st.cache_data` keeps query results in memory so every click is not a new database trip; the 5-minute limit is why the start
script restarts the dashboard after a fetch. Streamlit **re-runs the whole page script from the top on every click**, so
anything expensive must be cached.

### 11.3 The pages

| Page | What it shows |
|---|---|
| Dashboard | "Today's vibe" banner, mood over time (genre and audio, last 10 days, click a coloured block to see the songs), song of the day, today's plays, this week's rotation, "Discovered recently" with like buttons, liked songs |
| Mood Comparison | Genre mood vs audio mood: coverage, agreement, Cohen's kappa, confusion matrix, song-by-song tables, and the maths |
| Mood Lab | Label songs blind, scorecard per method, the labelling guide |
| Lifetime Wrapped | The whole history: top songs and artists, year/month drill-down, when you listen, habits, forgotten favourites, **Look up** an artist or a song (and make a playlist), and the **Wrapped card** (with a PNG download) |
| Song Globe | Your songs on a spinnable globe, placed by who they were played with |
| Mood Playlists | One tab per mood (upbeat, intense, calm, mellow): choose how many songs with a slider, **Randomize** for a different set from that mood, untick songs you do not want, name the playlist, and add it to Spotify |

### 11.4 Lifetime Wrapped in one paragraph

`import_history.py` loads the export into `raw_streaming_history`. dbt turns it into `stg_streaming_history` and `all_plays`.
`wrapped.py` (pure pandas, unit-tested) computes everything; the page just draws it. A **real play** is 30 seconds or more, and
songs are merged by lower-case title + artist so a re-released song counts once. The same page also exists as a hosted, browser-only
version at https://lifetime-wrapped.pages.dev/ (built together with Johan Chopra), where visitors drop their own export and
nothing is uploaded.

### 11.4b Mood Playlists, step by step

1. `python ingest_features.py --history` stores valence and energy for the history songs (section 6.2).
2. The dbt model `history_song_moods` labels each of those songs with the four-mood rule (section 10).
3. `mood_playlists.pick_songs` takes the songs of one mood with at least 2 real plays, sorts them by plays and keeps **one copy per
   title and artist**, because the same song often exists as an album track and as a single with different ids.
4. The page (`views/7_Mood_Playlists.py`) shows that list for the mood tab you are on. The **slider** (1 to 300) sets how many songs;
   **Randomize** takes a random sample of that size from every song of the mood (then sorts it by plays) and **Most played** goes
   back; the **Add** tick boxes let you remove songs; the name box and the **Public** tick box (off = private) set the rest.
   Changing the slider or randomizing resets the tick boxes, because they belong to the list that was shown.
5. **Add to Spotify** checks each chosen song is still playable (swapping dead ids for a playable copy found by search), creates a
   *new* playlist through `playlists.py`, opens it, and records it in the `mood_playlists` table, which feeds the "Playlists you made
   here" table at the bottom. Existing playlists are never touched.
6. The same thing from the terminal: `python mood_playlists.py --dry-run` (preview) or `--create` (all four), with `--mood`, `--max`,
   `--min-plays` and `--public`.

### 11.4c Look and feel (`theme.py`)

One CSS block, injected on every page: dark background with green and purple glows, gradient headings, pill-shaped tabs with the
open one in green, green gradient buttons. Two details worth knowing: the **top navigation bar is translucent and blurred**
(`background: rgba(...)` plus `backdrop-filter: blur(14px)`) so pages scroll softly beneath it instead of overlapping its labels, and
the thin grey rule Streamlit draws under tab pills is kept but **spaced away from the pills** (bottom padding and margin on the
tab list) so it no longer touches them.

### 11.5 The Song Globe in one paragraph

`globe_data.py` splits all plays into **sessions** (30 minutes of silence ends one), builds a songs-by-sessions matrix, reduces it
to 24 numbers per song with a truncated SVD, squashes that to a 2-D map with t-SNE (the 1,200 most-played songs first, the rest
placed beside their nearest neighbours) and the page draws it as a globe of covers. Songs that were played in the same sittings
end up close together.

---

## 12. Challenges and how each was solved

Each entry: **what happened -> why -> the fix**. They are roughly in the order they appeared.

**1. Spotify closed the audio-features endpoint.**
The plan was to read each song's valence and energy from Spotify. In November 2024 Spotify closed that endpoint to new apps, and
the artist `genres` field comes back empty for most artists too. *Fix:* the mood idea was rebuilt on two other sources: Last.fm
community tags for artists plus a hand-made genre-to-mood table (`genre_mood_map.csv`), and later ReccoBeats for audio values.
*Lesson:* check that an API still exists before designing around it.

**2. Last.fm tags are noisy.**
Anyone can tag anything ("seen live", "british"). *Fix:* keep only tags with a count of 10 or more and at most five per artist; add
`unclassified` seed rows for non-mood tags; and break ties alphabetically, because with equal counts the winner used to be
arbitrary and the same artist's mood changed between runs.

**3. A secret was committed to git.**
The very first commit (`50aebda`) included `.spotify_cache`, which holds the Spotify login token. Git remembers every file ever
committed, so deleting it later does not remove it from history. *Fix:* the file was removed from tracking and added to
`.gitignore` (`73c6d79`), and the **Spotify client secret was reset** so the leaked token was worthless. *Lesson:* the safe fix for
a leaked credential is to make it invalid, not to hide it. This is also why `.env`, tokens and the history export are git-ignored.

**4. Prefect crashed with a locked SQLite database.**
Prefect's default storage is a SQLite file. It produced database-lock errors (SQLite allows one writer at a time, and Prefect's
server and its serving process both write to it). *Fix:* point Prefect at Postgres, in its own `prefect_meta` database (section 8.3). Documented in the README.

**5. `Flow.serve()` has no timezone argument.**
A schedule written as "8 PM" needs a time zone, or it means 8 PM in whatever zone the machine or server assumes, and
`Flow.serve()` has no timezone option of its own. *Fix:* pass the schedule as `Cron("0 20 * * *", timezone="Asia/Kolkata")`.

**6. A staging filter silently dropped rows.**
`stg_recently_played` had `where primary_artist_id is not null`. Plays recorded before that column existed vanished from every
count, with no error. *Fix:* the filter was removed; those old plays now simply have no mood, and only the mood views leave them
out (`where mood is not null`). *Lesson:* filter at the point where the reason is visible, not deep in a staging layer.

**7. Days were off by up to 5.5 hours.**
`date_trunc('day', played_at)` follows the database time zone, and pandas shows `timestamptz` as UTC. *Fix:* set the database time
zone to `Asia/Kolkata` in `init.sql` and convert explicitly in the dashboard with `to_ist()`.

**8. Re-running created duplicates (risk).**
A pipeline that runs repeatedly must not double-count. *Fix:* primary key `(played_at, track_id)`, `ON CONFLICT DO NOTHING`, and a
dbt test (`unique_combination_of_columns`) that fails loudly if duplicates ever appear.

**9. The scheduled flow skipped the genre step.**
The first version of the flow loaded plays but never fetched genres, so artists first heard on a scheduled run had no mood. *Fix:*
`ingest_task` now calls the same genre function as `ingest.py`.

**10. The flow could not find `dbt` when started from a hidden process.**
Started from a script, the virtual environment was not active, so `dbt` was "not found". *Fix:* `dbt_executable()` looks next to
the running Python, and `start_all.ps1` puts the venv's `Scripts` folder on `PATH` for everything it starts.

**11. Spotify only returns the last 50 plays.**
There is no fix for plays that fall off before the next run; the pipeline can only be run often enough. *Mitigations:* the daily
flow, `refresh_dashboard.bat`, and the Extended Streaming History import for the past.

**12. ReccoBeats' answers do not line up with the question.**
Results arrive in any order, with ReccoBeats' own ids, and batches over 40 return HTTP 400. *Fix:* send 40 at a time, match each
record by the Spotify id inside its `href`, resolve through `/track` when needed, never trust order, store genuine misses as
`not_found` and retry them after 3 days, and respect `Retry-After` on HTTP 429. The `--probe` mode was added to find all this out
safely.

**13. ReccoBeats knows only about half the songs.**
Not fixable at the source. *Fix:* the dashboard shows coverage next to the audio charts, and the blended mood falls back to
Last.fm per play. A rescue (send a 30-second preview of the song to ReccoBeats' file-analysis endpoint) was piloted: on the 14 songs ReccoBeats
lacked, the result agreed with your hand labels 57% of the time, a small sample. It was parked because the terms of using the
previews were unverified.

**14. Which mood method is right? Nobody knew.**
The two methods agreed only 45% of the time, and neither had been checked against a ground truth. *Fix:* the Mood Lab: blind
hand labels, then a scorecard with agreement and Cohen's kappa. Result: audio 72%, Gemini about 54%, Last.fm 38%, which led to the
blended banner.

**15. A dbt syntax change broke the tests.**
In dbt 1.12, arguments of tests such as `accepted_values` must be nested under `arguments:`. *Fix:* all test YAML files were
updated to that shape.

**16. Opening a page directly skipped the top navigation.**
With a folder called `pages/`, Streamlit can run a page script on its own (for example after refreshing `/Method_Comparison`),
bypassing the router and its tab bar. *Fix:* the folder was renamed `views/`, so every address goes through `dashboard.py`.

**17. Streamlit kept using old code.**
After editing a *shared module* (like `track_ui.py` or `wrapped.py`) the dashboard showed `ImportError`s or old behaviour, because
Streamlit caches imported modules. Editing a page file alone is fine. *Fix:* restart the dashboard (kill the old process and start
a new one) after changing a shared file; check the process start time to be sure.

**18. HTML in markdown broke layouts.**
A `<div>` inside a markdown paragraph split the paragraph, and a half-transparent sticky table header let rows show through.
*Fix:* only inline `<span>`s inside text, and a solid colour for sticky headers.

**19. A restarted Docker made every page fail.**
The cached database connection died with the container and stayed broken. *Fix:* `pool_pre_ping=True` and `pool_recycle=300` in
`db.py`, so dead connections are replaced automatically.

**20. Chart days sorted wrongly across New Year.**
The old code sorted "Dec 30", "Jan 02" as if every date were in 2026. *Fix:* sort by the real date, label afterwards.

**21. Docker pointed at an empty database.**
Described in section 4.4: the volume name came from the folder name. *Fix:* pin `name: spotifydatapipeline`, back up first, and compare
row counts after recreating.

**22. The mood charts could come up blank.**
The chart script drew once, at whatever width its frame had at that instant (about 100 px, which gives a negative width), and
loaded its charting library from a single website. *Fix:* wait for a usable width, re-fit when the frame resizes, try a second
website for the library, and show a message instead of a blank area if both fail.

**23. Spotify changed its playlist rules.**
Creating a playlist answered 403 on the old address, and old track ids in the export were dead (they show as grey, unplayable
rows). *Fix:* use the new `/me/playlists` address, check each song is playable and swap a dead id for a playable copy found by
title and artist. In development mode a Spotify app may only be used by a handful of allow-listed people, which is why the
hosted version offers "Copy Spotify links" and a CSV instead.

**24. Windows quirks.**
Emoji in script output crashed with an encoding error (cp1252) because the Windows console is not UTF-8 -> set
`PYTHONIOENCODING=utf-8`. Scripts must be started from the project folder with the venv active, which is why the start script
uses `$PSScriptRoot` and puts the venv on `PATH`.

**25. The top bar showed page text through it while scrolling.**
The navigation bar was fully transparent, so content scrolled underneath and overlapped the tab names. *Fix:* a translucent dark
background with a blur behind it. It first looked unchanged because Streamlit keeps imported helper modules in memory; the
server had to be restarted to load the new `theme.py` (after editing a shared module,
restart, then check the process start time).

**26. A line touching the tab pills.**
Streamlit draws a rule under every tab list, right against the pills. It comes from an `::after` element on the tab list, found
by inspecting the page's real computed styles instead of guessing. *Fix:* padding below the pills and margin below the rule.

**27. Printing song titles crashed on Windows.**
A Japanese title raised `UnicodeEncodeError` in the console (cp1252). *Fix:* `sys.stdout.reconfigure(errors="replace")` in
`mood_playlists.py`, so one odd title cannot stop a playlist run.

**28. A background lookup seemed to stop early.**
The first history lookup ended after a part of the songs with no message. Re-running is safe by design: it only asks about songs
without a stored result, so it continued where it left off. Lesson: run long jobs with unbuffered output (`python -u`) so you can see
progress, and check "how many are still pending" instead of trusting the exit code.

**29. Too much empty space under the navigation bar.**
Streamlit pads the page by about 96 px at the top, and every hidden block a page uses to inject CSS adds a further 16 px gap, so
the title sat far below the bar (and the Dashboard page used a different padding from the rest). *Fix:* one rule in `theme.py` sets
the same small top padding (4.5 rem) on every page and hides the empty style-only blocks; the Dashboard's own padding rule was
removed so all pages match.

**How problems were approached.** The same loop every time: (1) read the actual error or look at the actual data instead of
guessing; (2) reproduce it in the smallest way (a `--probe` run, a SQL query in psql, a headless test); (3) fix the *cause*, not the
symptom; (4) add a guard so it cannot silently come back (a dbt test, a unit test, a log line); (5) write down the lesson (README,
CHANGES.md, code comments).

---

## 13. How it was made, in order

### Phase 1: the pipeline (22-29 September 2026)

Built bottom-up, one layer at a time, checking each layer before starting the next:

1. **Infrastructure first.** `docker-compose.yml` and `sql/init.sql`: a Postgres that works and keeps its data.
2. **Ingest.** `ingest.py`: Spotify OAuth -> flatten -> `raw_recently_played`, made idempotent with the primary key.
3. **dbt skeleton.** `stg_recently_played`, `daily_listening_summary`, tests, `dbt_utils`. (Commit `50aebda`.)
4. **Enrichment.** Last.fm genres -> `raw_artist_genres`; the genre-to-mood seed; `stg_artist_moods`; `daily_mood_summary`;
   `daily_dominant_mood`; more tests. (`a94f9e9`)
5. **Orchestration.** Prefect flow, then the SQLite-lock fix and the timezone fix. (`1f44c50`, `cf9e935`)
6. **Dashboard.** Streamlit, `daily_top_track`, then liked songs, "Discovered recently", animated navigation. (`cf9e935`, `370e2f0`)
7. **Documentation.** README, `requirements.txt`, `.env.example`.

### Phase 2: depth (October 2026)

- **Audio mood.** ReccoBeats ingest, `play_mood_comparison`, the `audio_mood` macro, the Mood Comparison page with agreement and
  kappa.
- **A second set of eyes.** A parallel copy of the project built by Johan Chopra was studied; its fixes and features were
  re-implemented here (covers and hover cards, clickable charts, top navigation, self-healing connections), see `CHANGES.md`.
- **Mood Lab and Gemini.** Blind hand labels, an AI labeler as a third method, and a scorecard to decide which method to trust.
- **Operations.** Backups, the pinned Docker project name, and `start_all.ps1` / `refresh_dashboard.bat`.
- **Lifetime Wrapped.** Import of the 86,000-play export, `all_plays`, `wrapped.py`, the Wrapped page, artist/song look-up and
  playlist export.
- **Song Globe, theme, card download, covers everywhere.** Then the blended "Today's vibe".
- **Mood playlists from the whole history.** ReccoBeats lookup of the history (`--history`), the `history_song_moods` model,
  `mood_playlists.py`, and the Mood Playlists page with a song-count slider, Randomize, remove-songs and naming. Plus a translucent
  navigation bar and tidier tab spacing.
- **A hosted version.** The Lifetime Wrapped idea was rebuilt with Johan as a browser-only page (nothing uploaded), deployed at
  https://lifetime-wrapped.pages.dev/.

### The method behind the build

- **Raw first, clever later.** Never edit raw data; derive everything in SQL so you can change your mind.
- **Small steps, each verified.** Run the new thing alone (a `--probe`, a single `dbt run -s model`, a headless page test) before
  connecting it to the rest.
- **Tests as a ratchet.** Every bug that mattered got a test or a dbt check afterwards, so the suite only grows.
- **Measure before trusting.** The mood methods were scored against your own labels instead of assumed to be right.
- **Write it down.** README (how to run), CHANGES.md (what changed and why), RUNBOOK (terminal steps), code comments for the
  non-obvious "why".

---

## 14. Cheat sheet and "if X breaks"

### Commands

```powershell
cd C:\dev\spotify-pipeline
venv\Scripts\Activate.ps1                      # every new terminal starts with this

docker compose up -d                           # start Postgres
docker ps                                      # is it up?

python ingest.py                               # fetch plays + genres + covers
python ingest_features.py                      # fetch ReccoBeats audio data
cd spotify_dbt; dbt build; cd ..               # seed + run + test
streamlit run dashboard.py                     # the dashboard

python -m unittest discover -s tests           # all Python tests
.\start_all.ps1 -DryRun                        # say what the start script would do
```

### If something breaks

| Symptom | Likely cause | What to do |
|---|---|---|
| Dashboard does not open | Streamlit process is not running (reboot, closed terminal) | Double-click `refresh_dashboard.bat` |
| "connection refused" / pages fail | Docker or the container is down | Run `refresh_dashboard.bat`, or start Docker Desktop and `docker start spotify_postgres` |
| `dbt: command not found` | venv not active | `venv\Scripts\Activate.ps1` |
| Prefect run shows **Late** | The serving process (`python pipeline_flow.py`) is not running, or the laptop slept | Start it; run `refresh_dashboard.bat` for a manual fetch |
| dbt error "relation ... already exists" | Two dbt runs overlapped | Run `dbt run` again, alone |
| Mood is blank for new artists | Last.fm has no usable tags for them | Add genre rows to `seeds/genre_mood_map.csv`, then `dbt seed && dbt run` |
| Few songs on the audio chart | ReccoBeats does not know them | Normal; check the coverage line under the chart |
| Edited a shared `.py` file and the dashboard looks wrong | Streamlit cached the old module | Restart the dashboard |
| Covers missing | Cover not fetched yet | `python history_covers.py` or `python globe_covers.py` |
| Spotify login popup every time | `.spotify_cache` missing | Approve once; it is saved again |

### Backups before anything risky

`docker exec spotify_postgres pg_dump -U spotify_user spotify_data > backups\spotify_data.sql`

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **API** | A web address you ask for data (Spotify, Last.fm, ReccoBeats) |
| **OAuth** | The "log in with Spotify and approve access" flow; gives your script a token |
| **ETL / ELT** | Extract, Transform, Load. Here: load raw data first, transform inside the database with dbt (ELT) |
| **Idempotent** | Running it twice gives the same result as once |
| **Image / container / volume** | Docker's recipe / running box / the data folder outside the box |
| **Schema** | A folder of tables inside a database (`public`, `dbt_dev`) |
| **View** | A saved SQL query that behaves like a table |
| **Seed** | A CSV that dbt loads as a table |
| **Macro** | A reusable piece of SQL (dbt) |
| **Staging / mart** | Cleaned copy of one raw table / a finished answer table |
| **Flow / task / deployment** | Prefect: a pipeline / one step of it / a pipeline plus a schedule |
| **Cron** | A compact schedule format: `0 20 * * *` = every day at 20:00 |
| **Valence / energy** | ReccoBeats ratings (0 to 1): how positive / how intense a song sounds |
| **Cohen's kappa** | How much two raters agree beyond what luck would give (0 = chance, 1 = perfect) |
| **Real play** | A play of 30 seconds or more (used in Lifetime Wrapped) |
| **Session** | A stretch of listening with no gap longer than 30 minutes (used by the Song Globe) |
| **t-SNE / SVD** | Techniques that squash many numbers per song down to a 2-D map |
| **oEmbed** | A public Spotify endpoint that returns a track's cover without a login |
