# Spotify Mood Pipeline

An end-to-end data pipeline that turns Spotify listening history into a daily "mood" signal, with an interactive dashboard for exploring and reacting to it.

Fetch -> land in Postgres -> transform with dbt -> orchestrate with Prefect -> visualize with Streamlit.

## Architecture

```
Spotify API (recently played) --+
                                +--> ingest.py --> Postgres (raw tables)
Last.fm API (artist tags) ------+                        |
                                                      dbt models
                                                         |
                                        Postgres (dbt_dev schema) --> Streamlit dashboard
                                                         ^
                                             Prefect schedules + orchestrates
                                             Docker Compose runs Postgres
```

## What it does

* Pulls recently played tracks from the Spotify API
* Enriches each track's artist with genre tags from Last.fm
* Maps genres to one of four moods (`calm`, `mellow`, `intense`, `upbeat`) via a hand-curated dbt seed
* Rolls plays up into daily listening stats and a daily dominant mood
* Surfaces "Discovered recently": tracks new to the history in the last 7 days that have already been replayed
* Lets you like tracks from that list; likes are saved to Postgres from the dashboard
* Links every track to Spotify, with a hover card showing the album cover
* Compares the genre-based mood with an audio-based mood (ReccoBeats valence and energy), with agreement and Cohen's kappa
* Looks up any pasted Spotify song link and shows both mood labels for it
* Optionally labels every song's mood with Gemini and scores all methods against your own hand labels (Mood Lab)
* Imports Spotify's Extended Streaming History export (years of plays) and shows it as a Lifetime Wrapped page: top songs and artists, year and month drill-down, when you listen, habits, forgotten favourites and a shareable card
* Looks up any artist or song in that history (peak period, plays per month and year, time of day) and exports an artist's most-played songs as a Spotify playlist
* Shows the last 10 days of genre and audio mood on the dashboard, and finds "Discovered recently" against the whole history
* Runs on a daily schedule via Prefect, with retries and dbt tests guarding data quality

## A real API surprise along the way

The original plan was to derive mood from Spotify's audio-features endpoint (valence, energy). Spotify closed that endpoint to new apps in November 2024, and the artist `genres` field now comes back empty for most artists. The pipeline uses Last.fm's community-tagged artist genres instead, with a hand-built genre-to-mood mapping (`spotify_dbt/seeds/genre_mood_map.csv`).

## Tech stack

| Tool | Role |
|-|-|
| Python (`spotipy`, `requests`) | API ingestion |
| PostgreSQL (Docker) | Storage |
| dbt | Transformation, testing |
| Prefect | Orchestration and scheduling |
| Streamlit + Plotly | Dashboard |
| Last.fm API | Genre tags |
| ReccoBeats API | Audio features (valence, energy), free, no key |
| Gemini API (optional) | A third mood method, judged against hand labels |

## Setup

1. Create a venv and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```
2. Create a Spotify Developer app (redirect URI `http://127.0.0.1:8888/callback`) and a Last.fm API key. Copy `.env.example` to `.env` and fill in the credentials.
3. Start Postgres. On the first start of an empty volume, `sql/init.sql` creates the tables, sets the database time zone to `Asia/Kolkata` and creates the `prefect_meta` database:
   ```
   docker compose up -d
   ```
   If your volume already existed, apply the script by hand (the `CREATE DATABASE prefect_meta` line will report an error if it already exists; that is harmless):
   ```
   docker exec -i spotify_postgres psql -U spotify_user -d spotify_data < sql/init.sql
   ```
   Note: the Compose project name is pinned (`name: spotifydatapipeline` in `docker-compose.yml`), so the data volume is
   always `spotifydatapipeline_pgdata`, whatever the project folder is called. Before this was pinned, Compose derived the
   name from the folder, and moving the folder pointed it at a new, empty volume. Containers are disposable and the volume
   is the data, so check `docker volume ls` before deleting anything.
4. Create the dbt profile: copy `spotify_dbt/profiles.yml.example` to `~/.dbt/profiles.yml`.
5. Build the models:
   ```
   cd spotify_dbt
   dbt deps
   dbt seed
   dbt run
   dbt test
   ```
6. Fetch data (the first run opens a browser for Spotify login), then start the dashboard:
   ```
   python ingest.py
   streamlit run dashboard.py
   ```

To run the whole ingest -> dbt run -> dbt test flow once: `python -c "from pipeline_flow import spotify_pipeline; spotify_pipeline()"`

## Scheduling

`pipeline_flow.py` serves the flow on a daily cron at 8:00 PM IST. Prefect cannot schedule on its temporary server, so run a persistent one that stores its metadata in the `prefect_meta` database:

```
prefect config set PREFECT_API_DATABASE_CONNECTION_URL="postgresql+asyncpg://spotify_user:spotify_pass@localhost:5432/prefect_meta"
prefect config set PREFECT_API_URL=http://127.0.0.1:4200/api
prefect server start        # terminal 1, leave running
python pipeline_flow.py     # terminal 2, leave running
```

Neither process restarts by itself after a reboot, and runs do not fire while the laptop is asleep.

## Time zones

The database time zone is `Asia/Kolkata`, so dbt's day bucketing (`date_trunc('day', played_at)`) follows IST. For an existing database, run this once (it only affects new sessions):

```
docker exec -it spotify_postgres psql -U spotify_user -d spotify_data -c "ALTER DATABASE spotify_data SET timezone TO 'Asia/Kolkata';"
```

The dashboard also converts timestamps to IST explicitly, because pandas reads `timestamptz` columns as UTC.

## Dashboard pages

Run `streamlit run dashboard.py`. Pages are tabs across the top:

* **Dashboard**: today's vibe (play by play, the mood of the song's own audio from ReccoBeats where it has the track, and the Last.fm genre mood only where it does not; the banner says how many minutes came from each), mood over time (genre-based and audio-based; click a coloured block to see the songs behind it), listening activity, song of the day, discoveries and likes. Track names link to Spotify and show a cover card on hover.
* **Mood Comparison**: genre mood against audio mood: coverage, daily charts, agreement, Cohen's kappa, confusion matrix and a song-by-song table.
* **Song Lookup**: paste a Spotify song link to see its details, ReccoBeats ratings, Last.fm tags and both mood labels. Nothing is saved.
* **Mood Lab**: label songs by ear (blind: no method's guess is shown), then a scorecard shows which method is closest to you.
* **Lifetime Wrapped**: your whole history from Spotify's Extended Streaming History export: top songs and artists, year and month drill-down, when you listen, habits (discovery, repeats), forgotten favourites and a shareable wrapped card.
* **Song Globe**: your songs on a spinnable globe, placed by who they were played with (songs from the same sittings sit close together). Move in eight directions with the arrow keys, scrolling or swiping; click a song for its stats and a link to open it in Spotify. Needs the album covers from `python globe_covers.py` (about 2,000 songs, a few minutes, safe to re-run). The globe itself is from Johan's Lifetime-Wrapped project.

## Lifetime Wrapped (optional)

Request your *Extended streaming history* from Spotify's privacy page, unzip it, then:

```
python import_history.py Spotify_Extended   # music plays only; the export's IP address and country are never stored
cd spotify_dbt && dbt seed && dbt build      # stg_streaming_history, all_plays (history + later pipeline plays)
python history_covers.py                     # album covers for the songs the page shows
```

A "real play" is a play of 30 seconds or more; songs released twice are merged by title and artist. To leave a song out (an alarm, say), add its track id to `spotify_dbt/seeds/excluded_tracks.csv` and run `dbt seed && dbt build`. The export folder is git-ignored.

The **Look up** tab searches one artist or one song: first and last play, the peak three months, best day, plays per month and per year, and the time of day you play it.

The **Look up** tab can turn an artist's most-played songs into a Spotify playlist (named by you, private by default). One-time setup: run `python playlists.py` and approve the extra permission (`playlist-modify-private/public`) in the browser. The token is stored in `.spotify_playlist_cache` (git-ignored), separate from the ingest token. It only creates new playlists.

How a playlist is made: pick an artist, name the playlist, choose how many songs (most played first) and whether it is public (private by default), then click **Create on Spotify**. Old exports often hold track ids Spotify no longer plays, so each song is checked first; a dead id is replaced by a playable copy found by searching title and artist, and any song with no playable copy is left out and listed. The new playlist opens in a browser tab. This uses Spotify's `/me/playlists` endpoint (the older `/users/{id}/playlists` returns 403 now).

## Audio features and the mood comparison

`python ingest_features.py` fetches valence and energy from ReccoBeats for every track played and stores them in `raw_track_features` (tracks ReccoBeats doesn't know are stored as `not_found` and retried after 3 days). The audio mood splits valence and energy at 0.5: high/high is upbeat, high energy with low valence is intense, low energy with high valence is calm, and low/low is mellow. Coverage is partial, and noticeably lower for recent releases.

To measure how well the two methods agree on tracks that have both labels:

```
python analysis/export_mood_data.py
python analysis/validate_moods.py
```

`analysis/validate_moods.do` is the same analysis for Stata (run it from the `analysis/` folder).

Unit tests: `python -m unittest discover -s tests`

## Mood Lab: is Gemini better than the other methods?

None of the mood methods is ground truth, so the Mood Lab scores them against **your own labels**:

1. Open the **Mood Lab** page and label about 30 songs (the page hides every method's guess while you do). You can
   also describe a song in your own words (for example "pre-gym hype, dark and confident"). Decide by how the song
   *feels*, not the occasion; the page's "How to label" tab has the rule and worked examples.
2. Add `GEMINI_API_KEY` to `.env`, then preview what would be sent and run it on just your labelled songs:
   ```
   python ingest_llm_moods.py --dry-run
   python ingest_llm_moods.py --only-labelled
   ```
   Drop `--only-labelled` to label every song. Each song is labelled once per model and prompt version, so re-running
   only pays for songs still missing a label. Three variants run: one that also sees ReccoBeats' numbers, one that
   sees only the title, artists, album and tags (so you can tell whether Gemini adds anything beyond the audio
   numbers), and one that also reads your description of the song (only for songs you described). The last one sees
   your own words, so it is shown apart on the scorecard and is not a fair comparison. `--variant` picks just one.
3. The scorecard shows, per method, how many songs it can label, how often it agrees with you, and Cohen's kappa.
   With fewer than 30 labels the numbers are rough.

Privacy: only song metadata is sent (title, artist names, album, Last.fm tags, ReccoBeats' numbers and, for the
third variant, your description), never ids, dates, keys or play history. On Google's free tier prompts may be used to improve its products and reviewed by humans;
the paid tier does not do this.

## Project structure

```
spotify-pipeline/
  ingest.py              - fetch, transform, load (Spotify + Last.fm + covers)
  ingest_features.py     - ReccoBeats audio features
  pipeline_flow.py       - Prefect flow
  dashboard.py           - Streamlit entry point (top navigation)
  views/                 - Dashboard, Mood Comparison, Song Lookup, Mood Lab, Lifetime Wrapped, Song Globe (the pages)
  import_history.py, wrapped.py, history_covers.py - Lifetime Wrapped: import, analysis functions, covers
  playlists.py           - create a Spotify playlist from track ids (checks each id is playable)
  globe_data.py          - the song map behind the Song Globe (sessions, embedding, t-SNE); globe_covers.py fetches its covers
  globe_assets/          - the globe's script and styles (from Johan's Lifetime-Wrapped project)
  theme.py, .streamlit/config.toml - the dashboard's dark theme with the green and purple glow and gradient titles
  db.py, track_ui.py     - shared dashboard helpers (engine, IST, track links)
  covers.py, lookup.py, mood_stats.py
  ai_labeler.py          - prompt, parsing and the Gemini call for AI mood labels
  ingest_llm_moods.py    - label songs with Gemini into raw_llm_moods
  analysis/              - export and validate the two mood methods
  tests/
  docker-compose.yml     - Postgres container
  sql/init.sql           - table definitions
  requirements.txt
  .env.example
  spotify_dbt/
    profiles.yml.example - dbt connection template
    seeds/genre_mood_map.csv
    macros/audio_mood.sql
    models/
      staging/           - stg_recently_played, stg_artist_moods,
                           stg_track_features, stg_track_covers,
                           stg_streaming_history, stg_llm_moods, stg_mood_labels
      marts/             - daily_listening_summary, daily_mood_summary,
                           daily_dominant_mood, daily_top_track,
                           play_mood_comparison, mood_comparison_track,
                           mood_comparison_artist, all_plays,
                           mood_method_eval
    seeds/excluded_tracks.csv - songs to leave out of the history (empty by default)
```

## User-generated data

`liked_tracks` is written directly by the dashboard and is not managed by dbt. Unlike the marts, which are rebuilt from raw data on every run, it holds durable user state.

## Data quality

dbt tests cover not-null checks on key fields, a composite-uniqueness check on `(played_at, track_id)`, and `accepted_values` checks that `mood` is one of the four defined moods.

## Known limitations

* Spotify's recently-played endpoint returns at most 50 plays, so the pipeline must run regularly; plays beyond the last 50 since the previous run are lost.
* Genre coverage depends on Last.fm community tagging, so smaller artists may have no mood.
* Plays from before `primary_artist_id` was added have no mood.
* ReccoBeats' features are its own estimates, not Spotify's, and many recent releases have none, so the audio mood covers only part of the listening.
