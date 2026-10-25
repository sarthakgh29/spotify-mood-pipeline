-- Daily mood with ReccoBeats given priority, play by play: a play takes the mood of its own audio (valence and energy) when
-- ReccoBeats has the track, and the Last.fm genre mood only when it does not. Plays with neither are left out.
-- minutes_from_audio is how many of the minutes in that row came from ReccoBeats (the rest came from Last.fm).

select
    listen_date,
    coalesce(audio_mood, genre_mood) as mood,
    count(*) as plays,
    round(sum(duration_minutes)::numeric, 1) as minutes_listened,
    coalesce(round(sum(duration_minutes) filter (where audio_mood is not null)::numeric, 1), 0) as minutes_from_audio
from {{ ref('play_mood_comparison') }}
where coalesce(audio_mood, genre_mood) is not null
group by 1, 2
order by 1 desc, minutes_listened desc
