-- One row per track I labelled by hand, with the mood each method gave it, so every method can be scored against
-- my labels. A method that has no label for a track (no Last.fm tags, no ReccoBeats data, not yet run) is null.

with tracks as (

    select
        track_id,
        max(track_name) as track_name,
        max(artist_names) as artist_names,
        max(primary_artist_id) as primary_artist_id
    from {{ ref('stg_recently_played') }}
    group by track_id

)

select
    l.track_id,
    t.track_name,
    t.artist_names,
    l.mood as user_mood,
    l.note as user_note,
    g.mood as genre_mood,
    case when f.has_features then {{ audio_mood('f.valence', 'f.energy') }} end as audio_mood,
    h.mood as llm_hybrid_mood,
    h.confidence as llm_hybrid_confidence,
    h.reason as llm_hybrid_reason,
    x.mood as llm_text_mood,
    x.confidence as llm_text_confidence,
    x.reason as llm_text_reason,
    n.mood as llm_notes_mood,
    n.confidence as llm_notes_confidence,
    n.reason as llm_notes_reason
from {{ ref('stg_mood_labels') }} l
inner join tracks t
    on t.track_id = l.track_id
left join {{ ref('stg_artist_moods') }} g
    on g.artist_id = t.primary_artist_id
left join {{ ref('stg_track_features') }} f
    on f.track_id = l.track_id
left join {{ ref('stg_llm_moods') }} h
    on h.track_id = l.track_id and h.variant = 'hybrid'
left join {{ ref('stg_llm_moods') }} x
    on x.track_id = l.track_id and x.variant = 'text_only'
left join {{ ref('stg_llm_moods') }} n
    on n.track_id = l.track_id and n.variant = 'with_notes'
