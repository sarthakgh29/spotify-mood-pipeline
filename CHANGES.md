# Changes on top of Johan's copy

This repo started as the original pipeline (Spotify + Last.fm -> Postgres -> dbt -> Prefect -> Streamlit). Johan Chopra
built a parallel copy ([johanchopra28/spotify-mood-analytics](https://github.com/johanchopra28/spotify-mood-analytics))
and documented it in his own `CHANGES.md`. This file records what was done **here, on top of his work**:

1. which of his changes were brought across, and how they differ in this codebase (section 1),
2. what is new here and not in his copy (section 2),
3. what you need to know to pull this repo into his copy, or his ideas into this one (sections 3 and 4).

His changes were reimplemented to fit this codebase from the behaviour in his `CHANGES.md` and his repo, not pasted over.
Date of this write-up: 2026-10-18.

## 1. Johan's changes: what happened to each

| His change | Here | Notes |
|---|---|---|
| 1. `sql/init.sql`, trimmed `requirements.txt`, `.gitignore`, dbt profile, README | Brought across | `init.sql` also defines this repo's extra tables. `requirements.txt` is pinned. `spotify_dbt/profiles.yml.example` is committed (the real `profiles.yml` stays local). `.gitignore` also covers `.cache` and `backups/`. README rewritten. |
| 2. Genre-mood seed rows and the tie-break | Brought across | 44 of his rows added to ours (35 -> 79 rows, no conflicts). `stg_artist_moods` orders by `count(*) desc, mood`. |
| 3. IST time zone | Brought across | `alter database ... set timezone` in `init.sql`; dashboard converts explicitly via the shared helper `db.py`. |
| 4. ReccoBeats audio features | **Different design** | See section 3. Same behaviour (batches of 40, misses cached and retried after 3 days, 429 handling); different files and table names. |
| 5. Spotify links, covers, hover cards | Brought across | `covers.py`, `track_ui.py`, `track_covers`, `stg_track_covers`, `daily_top_track.track_id`. "Discovered recently" has no scroll box (it would clip the card) and shows 15 rows with an expander. |
| 6. Prefect: flow fetches everything, `Cron` timezone | Brought across | Flow also finds `dbt` next to its own Python (works without an activated venv) and treats the audio-feature fetch as best-effort. |
| 7. Validation analysis | Brought across | `mood_comparison_track`/`_artist` marts, `analysis/export_mood_data.py`, `validate_moods.py` (+ plain-language kappa) and a Stata `.do` (untested: no Stata here). |
| 8. Clickable mood charts | Brought across | Both the genre-mood and audio-mood charts; songs are embedded in the chart and built with DOM nodes, never `innerHTML`. |
| 9. Label Comparison page | **Adapted** | Lives on the **Mood Comparison** page (`views/2_Method_Comparison.py`), which keeps its own extra sections (section 2). Has his Last.fm / ReccoBeats / maths toggles, filters, badges and kappa. |
| 10. Song Lookup | Brought across | Weighted Last.fm tags, listeners, similar artists, song-level tags, feature explanations, play history, raw-data view. Token kept in memory only. |
| 11. Top navigation | Brought across, **folder renamed** | Page scripts are in `views/`, not `pages/`. With a `pages/` folder Streamlit can run a page directly on a fresh server (a refresh on `/Method_Comparison`), skipping the router and the top bar. |
| 12. Self-recovering DB connections, start scripts, `conversations.md` | Connections brought across; scripts are our own | Start scripts and `conversations.md` are **local-only** (see section 5). |
| Weekly cat meme | **Not adopted** | Left out on purpose. |

## 2. New here (not in Johan's copy)

**Mood Lab and the AI labeler** (the biggest addition)
- `views/4_Mood_Lab.py`: label songs by ear, **blind** (no method's guess is shown while you label), optionally describe a
  song in your own words, undo the last label, edit or remove labels. A scorecard then shows, per method, coverage,
  agreement with you, Cohen's kappa, a confusion matrix and the songs it got wrong.
- `ai_labeler.py` + `ingest_llm_moods.py`: Gemini as a third mood method (`GEMINI_API_KEY` in `.env`; model via
  `GEMINI_MODEL`). Only song metadata is sent, never ids, dates, keys or play history. `--dry-run` shows the prompts
  without calling anything. Labels are stored once per (track, model, prompt version).
- Three variants: `hybrid` (title, artists, album, tags and ReccoBeats numbers), `text_only` (no numbers), and
  `with_notes` (hybrid plus your description of the song). `with_notes` sees your own words, so the scorecard flags it
  as **not a fair test**. All prompts carry one shared labelling rule (judge the feel of the song, energy first then tone).
- New tables `raw_llm_moods` and `mood_labels` (your hand labels; written by the dashboard, not managed by dbt) and dbt
  models `stg_llm_moods`, `stg_mood_labels`, `mood_method_eval`.
- Not wired into the daily Prefect flow until the scorecard shows it is worth it. The live Gemini call has not been run
  yet (no key); the code is covered by tests with a fake client.

**Mood Comparison page extras** (`views/2_Method_Comparison.py`): daily side-by-side charts, play-weighted agreement,
the valence/energy-over-time chart, a list of the most-played tracks with no audio features, coverage figures.

**Pipeline**
- `ingest_features.py`: a separate, more defensive ReccoBeats fetcher (accepts both response shapes, resolves ids through
  `/track` when needed, `--probe`, `--limit`, `--retry-misses`, `--refresh-found`). Stores all nine ratings plus
  `key`, `mode` and `isrc`.
- `spotify_dbt/macros/audio_mood.sql`: the valence/energy rule as one macro with overridable thresholds
  (`dbt run --vars '{energy_threshold: 0.6, valence_threshold: 0.45}'`).
- `play_mood_comparison` (one row per play, both moods), `daily_audio_mood_summary` (built on it).
- `daily_top_track` breaks ties deterministically.

**Dashboard**
- Scrollable "Song of the day" and "Today's full play history" (sticky header; the cover card opens beside the row).
- Audio-mood-over-time chart with a coverage line. Chart days are sorted by real date (the old code sorted as if every
  date were in 2026, which breaks across New Year).

**Lifetime Wrapped (ported from Johan's `3_Lifetime_Wrapped`, rebuilt for this project)**
- `import_history.py` loads the Extended Streaming History export (folder or zip) into `raw_streaming_history`: music
  plays only, idempotent, and the export's IP address and country are never stored. dbt adds `stg_streaming_history`,
  `all_plays` (history plus later pipeline plays) and an `excluded_tracks` seed (empty here; the mechanism is kept).
- `wrapped.py` (pure pandas, tested) and `views/5_Lifetime_Wrapped.py`: Lifetime, Year by year, When you listen, Habits,
  Forgotten favourites, Wrapped card. A real play is 30 seconds or more; songs are merged by title and artist. Year and
  month are chosen with dropdowns rather than clickable charts. `history_covers.py` fetches covers for the songs shown.
- **Look up** tab: one artist or one song (peak period, per-month and per-year plays, time of day), and **Create a
  Spotify playlist** from an artist's most-played songs (`playlists.py`; one-time `python playlists.py` approval; separate
  git-ignored token; checks each track is playable and swaps dead ids for a playable copy; never edits existing playlists).
  Uses `/me/playlists`; the older `/users/{id}/playlists` endpoint returns 403.
- Dashboard: the two mood-over-time charts show only the last 10 days with listening; "Discovered recently" now checks
  against `all_plays`, so a song first heard years ago no longer counts as new.

**Reliability and operations**
- `docker-compose.yml` pins the project name (`name: spotifydatapipeline`) so the data volume no longer depends on the
  folder name. Before this, moving the project folder made `docker compose up` point at a new, empty volume.
- `vote()` in `lookup.py` picks the five tags by position (a repeated tag could previously exceed the cap).
- `backups/` (git-ignored) holds database dumps taken before risky changes.

## 3. Differences to know about when merging with Johan's copy

| Thing | Johan's copy | This repo |
|---|---|---|
| Page folder | `pages/` | `views/` (and the page is called Mood Comparison, not Label Comparison) |
| Audio features table | `raw_audio_features` (`found` boolean) | `raw_track_features` (`status` = `found` / `not_found`) |
| Cover column | `track_covers.image_url` | `track_covers.cover_url` |
| Where features are fetched | inside `ingest.py` | `ingest_features.py` (run by the flow; `ingest.py` fetches plays, genres and covers) |
| dbt audio models | `stg_audio_features`, `stg_track_audio_moods` | `stg_track_features`, `play_mood_comparison` (+ the `audio_mood` macro) |
| Stats helper | `analysis/mood_stats.py` (scikit-learn) | `mood_stats.py` at the root (pure Python); scikit-learn only in `analysis/validate_moods.py` and a test |
| Shared helpers | each page defines its own engine | `db.py` (engine + IST helpers), `track_ui.py` |
| Cat meme | present | absent |

Both versions read `RECCOBEATS_RETRY_DAYS` from `.env`, use the same four moods, the same 0.5 audio-mood cut-offs and the
same seed file format, so the data is comparable.

## 4. Moving an existing database to this version

Tables are created by `sql/init.sql` (every statement is safe to repeat, except the final `CREATE DATABASE prefect_meta`,
which reports an error if it already exists; that is harmless):

```
docker exec -i spotify_postgres psql -U spotify_user -d spotify_data < sql/init.sql
```

Then fill the audio-feature table (from Johan's `raw_audio_features` you simply re-fetch; it takes a few minutes) and
rebuild:

```
python ingest_features.py
cd spotify_dbt
dbt seed
dbt build
```

If you created `mood_labels` before the description feature, add the column once:
`ALTER TABLE mood_labels ADD COLUMN IF NOT EXISTS note TEXT;`

**Docker caution.** Before running `docker compose up`, check `docker ps -a` and `docker volume ls`. A container made by a
different compose project can clash on the name `spotify_postgres`, and a different project name means a different
(empty) data volume. Containers are disposable; the volume is the data. Start an existing container with
`docker start spotify_postgres` instead of recreating it.

## 5. Local-only files (not in git)

`start_all.ps1`, `start_all.bat`, `start_localhost.bat`, `refresh_dashboard.bat` and `conversations.md` are listed in the
local `.git/info/exclude`, so a clone does not get them. The start scripts use `$PSScriptRoot`, so they work from any
folder: to share them, delete their lines from `.git/info/exclude` and commit them. `start_all.ps1` starts Docker,
Postgres, the Prefect server, the daily flow and the dashboard in order, leaves anything healthy alone, and has
`-SkipIngest`, `-DashboardOnly`, `-Open`, `-RestartDashboard`, `-Stop` and `-DryRun`.

## 6. Known issues and open items

- Spotify's recently-played endpoint returns at most 50 plays, so the pipeline must run regularly; missed plays are lost.
- ReccoBeats knows about half of the tracks and far fewer 2025-26 releases, so the audio mood covers only part of the
  listening. In this data about 60% of audio labels sit within 0.10 of a valence or energy cut-off, so they are fragile.
- Kappa is unstable on small samples; the pages and scripts say so.
- The Gemini labeler has not been run against the live API yet; judge it with the Mood Lab scorecard once there are
  about 30 hand labels. On Google's free tier prompts may be used to improve its products; the paid tier does not.
- `st.components.v1.html` is deprecated in favour of `st.iframe`; the mood charts and nav buttons still use it.
- On one machine an old, unused Docker volume `spotify-pipeline_pgdata` remains and can be removed once nothing needs it.

## 7. Checks

```
python -m unittest discover -s tests          # unit tests
cd spotify_dbt && dbt build                    # models, seed and data tests
python analysis/export_mood_data.py && python analysis/validate_moods.py
```
