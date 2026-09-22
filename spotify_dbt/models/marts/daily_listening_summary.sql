select
    date_trunc('day', played_at) as listen_date,
    count(*) as plays,
    count(distinct track_id) as distinct_tracks,
    count(distinct artist_names) as distinct_artists,
    round(sum(duration_minutes)::numeric, 1) as total_minutes_listened
from {{ ref('stg_recently_played') }}
group by 1
order by 1 desc