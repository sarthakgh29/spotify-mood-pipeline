with ranked as (

    select
        listen_date,
        mood,
        minutes_listened,
        row_number() over (
            partition by listen_date
            order by minutes_listened desc
        ) as rn
    from {{ ref('daily_mood_summary') }}

)

select
    listen_date,
    mood as dominant_mood,
    minutes_listened as dominant_mood_minutes
from ranked
where rn = 1
order by listen_date desc