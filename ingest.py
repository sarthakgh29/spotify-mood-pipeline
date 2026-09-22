import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    scope="user-read-recently-played",
    cache_path=".spotify_cache"
))

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

def fetch_recently_played():
    results = sp.current_user_recently_played(limit=50)
    return results["items"]

def transform(tracks):
    """Turn Spotify's raw JSON into flat tuples matching our table columns."""
    rows = []
    for item in tracks:
        track = item["track"]
        rows.append((
            item["played_at"],
            track["id"],
            track["name"],
            ", ".join([a["name"] for a in track["artists"]]),
            track["album"]["name"],
            track["duration_ms"],
        ))
    return rows

def load(rows):
    """Insert rows into Postgres, skipping duplicates."""
    if not rows:
        print("No rows to insert.")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    query = """
        INSERT INTO raw_recently_played
            (played_at, track_id, track_name, artist_names, album_name, duration_ms)
        VALUES %s
        ON CONFLICT (played_at, track_id) DO NOTHING
    """
    execute_values(cur, query, rows)
    inserted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    print(f"Inserted {inserted} new rows (out of {len(rows)} fetched).")

if __name__ == "__main__":
    raw_tracks = fetch_recently_played()
    rows = transform(raw_tracks)
    load(rows)