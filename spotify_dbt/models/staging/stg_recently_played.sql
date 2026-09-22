select
    played_at,
    track_id,
    track_name,
    artist_names,
    primary_artist_id,
    album_name,
    duration_ms,
    duration_ms / 1000.0 / 60 as duration_minutes,
    ingested_at
from {{ source('spotify_raw', 'raw_recently_played') }}
where primary_artist_id is not null