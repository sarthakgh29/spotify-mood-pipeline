with track_counts as (

    select
        date_trunc('day', played_at) as listen_date,
        track_id,
        track_name,
        artist_names,
        count(*) as play_count
    from {{ ref('stg_recently_played') }}
    group by 1, 2, 3, 4

),

ranked as (

    select
        listen_date,
        track_id,
        track_name,
        artist_names,
        play_count,
        row_number() over (
            partition by listen_date
            order by play_count desc, track_id
        ) as rn
    from track_counts

)

select
    listen_date,
    track_id,
    track_name,
    artist_names,
    play_count
from ranked
where rn = 1
order by listen_date desc
