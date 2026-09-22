select
    played_at,
    track_id,
    track_name,
    artist_names,
    album_name,
    duration_ms,
    duration_ms / 1000.0 / 60 as duration_minutes,
    ingested_at
from {{ source('spotify_raw', 'raw_recently_played') }}