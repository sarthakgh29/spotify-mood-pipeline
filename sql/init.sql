-- Table definitions for a fresh database.
-- Mounted into the Postgres container (see docker-compose.yml) and run automatically the first time
-- the container starts on an empty volume. It is NOT re-run on an existing volume: apply it by hand
-- with   docker exec -i spotify_postgres psql -U spotify_user -d spotify_data < sql/init.sql
-- (every statement below is safe to repeat except the CREATE DATABASE at the end).
--
-- The raw_* tables are written by the ingest scripts, liked_tracks by the dashboard. dbt never touches them.

-- Day bucketing in the dbt marts (date_trunc('day', played_at)) uses the session time zone, so set it here.
ALTER DATABASE spotify_data SET timezone TO 'Asia/Kolkata';

CREATE TABLE IF NOT EXISTS raw_recently_played (
    played_at         TIMESTAMPTZ NOT NULL,
    track_id          TEXT        NOT NULL,
    track_name        TEXT,
    artist_names      TEXT,
    primary_artist_id TEXT,
    album_name        TEXT,
    duration_ms       INTEGER,
    ingested_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (played_at, track_id)
);

CREATE TABLE IF NOT EXISTS raw_artist_genres (
    artist_id   TEXT PRIMARY KEY,
    artist_name TEXT,
    genres      TEXT[],
    fetched_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liked_tracks (
    track_id     TEXT PRIMARY KEY,
    track_name   TEXT,
    artist_names TEXT,
    liked_at     TIMESTAMPTZ DEFAULT now()
);

-- Audio features from ReccoBeats, written by ingest_features.py.
-- NOTE: columns inferred from ingest_features.py (the original CREATE TABLE was run by hand).
CREATE TABLE IF NOT EXISTS raw_track_features (
    track_id         TEXT PRIMARY KEY,
    reccobeats_id    TEXT,
    valence          DOUBLE PRECISION,
    energy           DOUBLE PRECISION,
    danceability     DOUBLE PRECISION,
    acousticness     DOUBLE PRECISION,
    tempo            DOUBLE PRECISION,
    instrumentalness DOUBLE PRECISION,
    liveness         DOUBLE PRECISION,
    loudness         DOUBLE PRECISION,
    speechiness      DOUBLE PRECISION,
    key              INTEGER,             -- pitch class, 0 = C
    mode             INTEGER,             -- 1 = major, 0 = minor
    isrc             TEXT,
    status           TEXT NOT NULL,            -- 'found' or 'not_found'
    first_fetched_at TIMESTAMPTZ DEFAULT now(),
    fetched_at       TIMESTAMPTZ DEFAULT now()
);

-- Album covers, cached by ingest (covers.py). cover_url is NULL when no cover could be found.
CREATE TABLE IF NOT EXISTS track_covers (
    track_id   TEXT PRIMARY KEY,
    cover_url  TEXT,
    fetched_at TIMESTAMPTZ DEFAULT now()
);

-- Mood labels from a language model (ingest_llm_moods.py). One row per track, model and prompt version, so a new
-- prompt or model adds rows instead of overwriting; a second variant (text only) can sit beside the hybrid one.
CREATE TABLE IF NOT EXISTS raw_llm_moods (
    track_id       TEXT        NOT NULL,
    model          TEXT        NOT NULL,
    prompt_version TEXT        NOT NULL,
    mood           TEXT        NOT NULL,
    confidence     TEXT,
    reason         TEXT,
    labelled_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (track_id, model, prompt_version)
);

-- My own hand labels, written by the dashboard's Mood Lab page (not managed by dbt).
CREATE TABLE IF NOT EXISTS mood_labels (
    track_id    TEXT PRIMARY KEY,
    mood        TEXT NOT NULL,
    note        TEXT,                    -- optional description in my own words (only sent to Gemini's with_notes variant)
    labelled_at TIMESTAMPTZ DEFAULT now()
);

-- Full listening history from Spotify's "Extended streaming history" export (import_history.py). Music plays only;
-- the export's IP address and country columns are deliberately not stored.
CREATE TABLE IF NOT EXISTS raw_streaming_history (
    played_at    TIMESTAMPTZ NOT NULL,     -- when the play ended (the export's ts)
    track_id     TEXT        NOT NULL,
    track_name   TEXT,
    artist_name  TEXT,
    album_name   TEXT,
    ms_played    INTEGER     NOT NULL,
    reason_start TEXT,
    reason_end   TEXT,
    skipped      BOOLEAN,                  -- unreliable before about 2023
    shuffle      BOOLEAN,
    offline      BOOLEAN,
    incognito    BOOLEAN,
    platform     TEXT,
    UNIQUE (played_at, track_id)
);
CREATE INDEX IF NOT EXISTS raw_streaming_history_track_idx ON raw_streaming_history (track_id);

-- Prefect's own metadata lives in a separate database (see README, "Scheduling"). Only runs on first start.
CREATE DATABASE prefect_meta;

-- Playlists made by mood_playlists.py, so a mood is not turned into a second playlist by accident.
CREATE TABLE IF NOT EXISTS mood_playlists (
    id          SERIAL PRIMARY KEY,
    mood        TEXT NOT NULL,
    playlist_id TEXT NOT NULL,
    url         TEXT NOT NULL,
    name        TEXT NOT NULL,
    songs       INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
