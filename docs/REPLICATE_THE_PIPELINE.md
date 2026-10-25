# Replicating the Spotify mood pipeline

A hand-over guide for rebuilding this project on another machine, written so Johan can give it to his coding assistant and get the same result. It says what the project is, how it is built in order, what each push added, the choices that were made on purpose, and the traps that cost time.

Repo: github.com/sarthakgh29/spotify-mood-pipeline. Read `docs/HOW_IT_WORKS.md` next to this file for a longer plain-language explanation of every tool.

**Instructions for the assistant reading this:** build in the order of section 4 and run the check at the end of each step before moving on. Never print, log or commit secrets (`.env`, `.cache`, `.spotify_playlist_cache`) or the personal Spotify export folder (`Spotify_Extended/`). Do not add author or co-author credits for any assistant to commits, files or the README.

---

## 1. What it does

Spotify plays in, moods out, shown on a dashboard.

```
Spotify (recently played) --\
Last.fm (artist tags) ------+--> Postgres (Docker) --> dbt --> Streamlit dashboard
ReccoBeats (valence/energy) /          ^                         ^
Spotify extended history (zip) --------/      Prefect runs it daily at 20:00 IST
```

Two ways to decide a song's mood, kept side by side so they can be compared:

1. **Genre mood:** Last.fm tags of the artist, mapped to a mood by a seed table (`genre_mood_map.csv`, 79 rows).
2. **Audio mood:** ReccoBeats `valence` and `energy` with fixed 0.5 cut-offs:

| energy | valence | mood |
|---|---|---|
| >= 0.5 | >= 0.5 | upbeat |
| >= 0.5 | < 0.5 | intense |
| < 0.5 | >= 0.5 | calm |
| < 0.5 | < 0.5 | mellow |

The same four mood names are used everywhere.

## 2. Stack and versions

| Part | Choice |
|---|---|
| Database | Postgres 16 in Docker (`docker-compose.yml`, project name `spotifydatapipeline`, container `spotify_postgres`, port 5432, `sql/init.sql` runs on first start only) |
| Databases | `spotify_data` (schema `public` = raw tables, `dbt_dev` = dbt output) and `prefect_meta` (Prefect's own state) |
| Transform | dbt Core 1.12 with dbt-postgres 1.11, `dbt_utils` 1.3.0. All models are views; seeds are tables |
| Orchestration | Prefect 3 (server plus a serving process), schedule `Cron("0 20 * * *", timezone="Asia/Kolkata")` |
| Dashboard | Streamlit 1.64, Plotly, pandas; pages in `views/`, router in `dashboard.py` |
| Spotify | spotipy (reading plays; creating playlists) |
| Python | 3.11 in a `venv`; see `requirements.txt` for pinned versions |

Secrets live in `.env` (copy `.env.example`): Spotify client id, secret and redirect URI (`http://127.0.0.1:8888/callback`), Last.fm API key, DB settings, and an optional Gemini key. Database timezone is `Asia/Kolkata`.

## 3. Data sources and their quirks

- **Spotify recently played:** the API returns only the last 50 plays, so the pipeline must run often or plays are lost. Stored in `raw_recently_played`.
- **Last.fm artist tags:** keep tags with count >= 10, top 5 per artist, stored in `raw_artist_genres`; moods come from the seed map.
- **ReccoBeats audio features** (Spotify closed its own audio-features endpoint to new apps): batches of 40 ids as repeated `ids` parameters, records matched back by the Spotify id found in each record's `href`. Handle HTTP 429 with `Retry-After`. Coverage is only about half of all tracks, so a miss is stored as `status = 'not_found'` and retried after 3 days. Table `raw_track_features`.
- **Spotify extended streaming history:** the user requests "Extended streaming history" from Spotify's privacy page and gets a zip of JSON files. `import_history.py` loads it into `raw_streaming_history` (about 85,000 plays here). The IP address and country fields are never stored. The folder `Spotify_Extended/` is git-ignored and must never be committed or served over a web server.
- **Album covers:** Spotify's public oEmbed endpoint, cached in `track_covers`, fetched politely (small pauses, back-off on errors). Only Spotify image hosts are allowed when fetching a cover URL.
- **Playlists:** Spotify rejects the old `/users/{id}/playlists` call (403); use `current_user_playlist_create` (`/me/playlists`). In development mode the app allows 5 users and the owner needs Premium. Some old track ids are dead ("grey" tracks), so each song is checked and a playable copy is found by search before adding.

## 4. Build order (each step has a check)

1. **Docker + Postgres.** `docker compose up -d`, tables from `sql/init.sql`. *Check:* `psql` shows `spotify_data` and `prefect_meta`.
2. **Ingest plays** (`ingest.py`): Spotify OAuth with the read-only recently-played scope, upsert into `raw_recently_played`; Last.fm tags into `raw_artist_genres`. *Check:* row counts rise on a second run without duplicates.
3. **dbt staging and marts.** Sources in `sources.yml`, `stg_recently_played` (watch out: it had a bug, fixed in `cf9e935`), the seed `genre_mood_map`, then marts `daily_mood_summary`, `daily_dominant_mood`, `daily_listening_summary`, `daily_top_track`. Test syntax in this dbt version needs an `arguments:` block under `accepted_values`. *Check:* `dbt build` all green.
4. **Prefect flow** (`pipeline_flow.py`): tasks in order `ingest_task`, `audio_features_task`, `dbt_run_task`, `dbt_test_task`. Run Prefect's metadata on Postgres, not SQLite, which locked (see commit `1f44c50`). `start_all.ps1` starts the services and runs a refresh.
5. **Audio features** (`ingest_features.py`) and the macro `audio_mood(valence, energy)` plus `stg_track_features` (adds `has_features`). Marts `daily_audio_mood_summary`, `play_mood_comparison`, `mood_comparison_artist`, `mood_comparison_track`. Python twin of the macro is `lookup.audio_mood`; keep the two identical.
6. **Dashboard** (`dashboard.py` router + `views/`): Dashboard, Mood Comparison, Mood Lab, Lifetime Wrapped, Song Globe, Mood Playlists. Put page scripts in `views/`, not `pages/`, so a browser refresh cannot skip the router.
7. **Extended history.** `import_history.py`, `stg_streaming_history`, view `all_plays` (history first, then pipeline plays newer than the history ends; a play is "real" at 30 seconds or more), seed `excluded_tracks` for songs to hide. `wrapped.py` holds the calculations for Lifetime Wrapped; `views/5_Lifetime_Wrapped.py` shows them (tabs: Lifetime, Year by year, When you listen, Habits, Forgotten favourites, Look up, Wrapped card).
8. **Blended "Today's vibe"** (`daily_blended_mood_summary`): for each song use ReccoBeats audio mood if it exists, otherwise the Last.fm genre mood, then take the day's dominant mood. ReccoBeats has priority.
9. **Song Globe** (`globe_data.py`, `globe_covers.py`, `globe_assets/`): sessions -> co-play vectors -> SVD -> t-SNE gives each song a position; the spinning globe is drawn by `globe.js`, adapted from Johan's Lifetime-Wrapped project.
10. **Look and feel** (`theme.py`, `.streamlit/config.toml`): dark theme, green to purple gradient headings, pill tabs, translucent blurred top bar. `track_ui.py` shows album covers in every table.
11. **Wrapped card PNG** (`card_image.py`): Pillow draws a 1080x1350 PNG (gradient, four totals, number one song with cover, top five songs and artists) for a download button. It picks a font per script so Japanese, Korean and Hindi titles do not turn into boxes.
12. **Playlists from the artist lookup** (`playlists.py`): needs a one-time `python playlists.py` to approve the playlist permission; the token goes in `.spotify_playlist_cache` (git-ignored), separate from the ingest token. It only ever creates new playlists.
13. **Mood playlists from the whole history** (the newest feature, section 6).

## 5. What each push added

| Commit | Date | What |
|---|---|---|
| `50aebda` | 22 Sep | Ingest, Postgres in Docker, dbt staging, first mart and tests |
| `73c6d79` | 22 Sep | Last.fm genre tags, mood mapping seed, mood marts and tests |
| `a94f9e9`, `0d09800` | 22 Sep | README, ignore the Spotify cache |
| `1f44c50` | 23 Sep | Prefect SQLite lock bug and the switch to Postgres |
| `cf9e935` | 26 Sep | Streamlit dashboard, daily top track, `stg_recently_played` fix, Prefect timezone fix |
| `7c7dbc9`, `26500ed` | 26 Sep | `requirements.txt`, `.env.example` |
| `370e2f0`, `994204e` | 29 Sep | Liked songs, "discovered recently", animated nav, README |
| `c3016a2` | 25 Oct | Audio mood, Mood Lab, Lifetime Wrapped, song globe and the new look |
| `fa4113a` | 25 Oct | README links the hosted Lifetime Wrapped site |

**Not yet pushed** when this guide was written (all in the working folder): wrapped-card PNG download, album covers everywhere, removal of the separate Song Lookup page, the two guides in `docs/`, the mood-playlist feature, the translucent top bar. `git status` lists them; commit them together or in small pieces.

## 6. The newest feature: mood playlists from the whole history

1. `python ingest_features.py --history` looks up valence and energy for every song in `raw_streaming_history`, most played first (about 5,000 songs, 40 per request, roughly 10 minutes; results are stored, so reruns only fetch what is missing). `get_pending_track_ids(..., source="plays" | "history" | "all")` chooses the song list.
2. dbt mart `history_song_moods`: one row per track from `all_plays` joined to `stg_track_features` where `has_features`, with `audio_mood`, `real_plays`, `last_played_at`. Tests: unique and not null `track_id`, accepted moods.
3. `mood_playlists.py`: `pick_songs(rows, max_songs, min_plays)` sorts by real plays, drops songs under `min_plays` (default 2) and keeps one copy per normalised title and artist (the same song on an album and a single counts once). Command line: `--dry-run`, `--create`, `--mood`, `--max`, `--min-plays`, `--public`. Table `mood_playlists` records what was created.
4. Dashboard page `views/7_Mood_Playlists.py`, one tab per mood: a slider for how many songs (1 to 300), a table with cover, title, artist, plays and an "Add" tick box to remove songs, a Randomize button (random songs from the whole mood) and a Most played button to go back, a name box, a Public tick box (off by default), and an Add to Spotify button that checks each song is playable, creates the playlist, opens it, and logs it.

## 7. Decisions made on purpose

- Keep both mood methods and compare them; they agree only about 45% of the time (kappa about 0.23), and about 63% of audio labels sit within 0.10 of a cut-off, so neither is "the truth".
- All dbt models are views, so changing a model never needs a data reload.
- Raw tables are written by Python with upserts; dbt never writes raw data.
- Missing data is stored as a miss and retried later, not skipped silently.
- Playlist creation only ever makes new private playlists; it never edits or deletes.
- Personal files, tokens and the history export stay local and git-ignored.
- Everything that talks to a web service is polite (batches, pauses, back-off) and fails soft.

## 8. Traps that cost time

- **Streamlit caches imported modules.** After editing `theme.py`, `playlists.py` or any helper, stop all `streamlit` processes and start again; page scripts reload on their own, helpers do not. Symptoms were `AttributeError` on a new function and a style change that "did nothing". Check the new process start time.
- Killing processes by a command-line match that contains "streamlit" can kill the shell that runs it; filter on process name too.
- A `psycopg2` raw connection from SQLAlchemy needs `commit()` after writes.
- An empty seed CSV makes dbt guess an integer column; set `column_types: text` in the seed yml.
- `all_plays` must not be run twice at once (dbt "relation already exists"); rerun alone.
- Console encoding on Windows (cp1252) fails when printing Japanese titles; reconfigure stdout with `errors="replace"`.
- Gradient headings with an emoji turn the emoji into flat blobs; leave emoji out of `st.title`.
- Streamlit 1.64 tab selector is `div[data-testid="stTab"]`, not a button.
- Windows with animations off reports `prefers-reduced-motion`, so smooth scrolling must be done in JavaScript.
- Spotify playlist creation, grey tracks and the 403 on the old endpoint: see section 3.
- Write long multi-line scripts to a file and run it; very long shell heredocs got mangled.
- `docker compose` mounts the data in volume `spotifydatapipeline_pgdata`; `init.sql` runs only when that volume is created, so add new tables to the live database by hand as well as to `init.sql`.

## 9. How to check the whole thing works

```bash
python -m unittest discover -s tests          # all unit tests
cd spotify_dbt && dbt build                   # models, seeds and tests
python mood_playlists.py --dry-run            # four moods, songs listed, nothing created
streamlit run dashboard.py                    # open http://localhost:8501
```

Then open each page, move the slider on Mood Playlists, click Randomize, and (only when happy) Add to Spotify.

## 10. Getting started on a new machine

1. Install Docker Desktop, Python 3.11 and Git; clone the repo; create a `venv`; `pip install -r requirements.txt`.
2. Make your own Spotify developer app and Last.fm API key; copy `.env.example` to `.env` and fill it in. Never share `.env`.
3. `docker compose up -d`, then run `ingest.py` once (it opens a browser to approve Spotify access).
4. Ask Spotify for your extended streaming history, unzip it into `Spotify_Extended/`, run `python import_history.py Spotify_Extended`, then `python ingest_features.py --history`, `dbt seed`, `dbt build`.
5. Run `python playlists.py` once to allow playlist creation, then start the dashboard.

Note: Spotify development-mode apps allow only a few named users, so Johan must use his own Spotify developer app and his own account, not copy Sarthak's keys.
