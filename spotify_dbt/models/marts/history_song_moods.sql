-- One row per song in the whole listening history that ReccoBeats has valence and energy for, with its audio mood.
with plays as (
    select
        track_id,
        max(track_name) as track_name,
        max(artist_name) as artist_name,
        count(*) filter (where is_real_play) as real_plays,
        count(*) as total_plays,
        max(played_at) as last_played_at
    from {{ ref('all_plays') }}
    group by track_id
)

select
    p.track_id,
    p.track_name,
    p.artist_name,
    p.real_plays,
    p.total_plays,
    p.last_played_at,
    f.valence,
    f.energy,
    {{ audio_mood('f.valence', 'f.energy') }} as audio_mood
from plays p
join {{ ref('stg_track_features') }} f on f.track_id = p.track_id
where f.has_features
