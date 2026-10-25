-- One row per play, carrying the mood under BOTH methods so they can be compared directly.
--   genre_mood : artist-level, from Last.fm tags via the genre_mood_map seed
--   audio_mood : track-level, from ReccoBeats valence + energy split at the thresholds below
-- Thresholds can be overridden with: dbt run --vars '{energy_threshold: 0.6, valence_threshold: 0.45}'
-- Keep ENERGY_THRESHOLD / VALENCE_THRESHOLD in the Streamlit page in sync.

with plays as (

    select
        played_at,
        date_trunc('day', played_at) as listen_date,
        track_id,
        track_name,
        artist_names,
        primary_artist_id,
        duration_minutes
    from {{ ref('stg_recently_played') }}

),

joined as (

    select
        p.played_at,
        p.listen_date,
        p.track_id,
        p.track_name,
        p.artist_names,
        p.duration_minutes,
        m.mood as genre_mood,
        coalesce(f.has_features, false) as has_features,
        f.valence,
        f.energy
    from plays p
    left join {{ ref('stg_artist_moods') }} m
        on p.primary_artist_id = m.artist_id
    left join {{ ref('stg_track_features') }} f
        on p.track_id = f.track_id

)

select
    played_at,
    listen_date,
    track_id,
    track_name,
    artist_names,
    duration_minutes,
    genre_mood,
    case when has_features then valence end as valence,
    case when has_features then energy end as energy,
    case
        when not has_features then null
        when energy >= {{ var('energy_threshold', 0.5) }}
         and valence >= {{ var('valence_threshold', 0.5) }} then 'upbeat'
        when energy >= {{ var('energy_threshold', 0.5) }} then 'intense'
        when valence >= {{ var('valence_threshold', 0.5) }} then 'calm'
        else 'mellow'
    end as audio_mood
from joined
