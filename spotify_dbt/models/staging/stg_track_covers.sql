select
    track_id,
    cover_url,
    fetched_at
from {{ source('spotify_raw', 'track_covers') }}
where cover_url is not null
