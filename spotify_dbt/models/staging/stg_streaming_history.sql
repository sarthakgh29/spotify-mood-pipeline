select
    played_at,
    track_id,
    track_name,
    artist_name,
    album_name,
    ms_played,
    ms_played / 1000.0 as seconds_played,
    ms_played >= 30000 as is_real_play,
    reason_start,
    reason_end,
    skipped,
    shuffle,
    offline,
    incognito,
    platform
from {{ source('spotify_raw', 'raw_streaming_history') }}
where track_id not in (select track_id from {{ ref('excluded_tracks') }})
