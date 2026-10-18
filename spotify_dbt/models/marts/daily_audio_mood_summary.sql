-- Same shape as daily_mood_summary, but the mood comes from the track's own valence and energy (ReccoBeats)
-- instead of the artist's Last.fm tags. Plays without audio features are left out.

select
    listen_date,
    audio_mood as mood,
    count(*) as plays,
    round(sum(duration_minutes)::numeric, 1) as minutes_listened
from {{ ref('play_mood_comparison') }}
where audio_mood is not null
group by 1, 2
order by 1 desc, minutes_listened desc
