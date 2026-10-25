select
    track_id,
    reccobeats_id,
    valence,
    energy,
    danceability,
    acousticness,
    tempo,
    instrumentalness,
    liveness,
    loudness,
    speechiness,
    key,
    mode,
    isrc,
    status,
    fetched_at,
    (status = 'found' and valence is not null and energy is not null) as has_features
from {{ source('audio_features_raw', 'raw_track_features') }}
