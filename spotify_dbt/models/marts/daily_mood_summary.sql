with plays_with_mood as (

    select
        p.played_at,
        p.track_name,
        p.primary_artist_id,
        p.duration_minutes,
        m.mood
    from {{ ref('stg_recently_played') }} p
    left join {{ ref('stg_artist_moods') }} m
        on p.primary_artist_id = m.artist_id

)

select
    date_trunc('day', played_at) as listen_date,
    mood,
    count(*) as plays,
    round(sum(duration_minutes)::numeric, 1) as minutes_listened
from plays_with_mood
where mood is not null   -- exclude plays where we have no mood signal at all
group by 1, 2
order by 1 desc, minutes_listened desc