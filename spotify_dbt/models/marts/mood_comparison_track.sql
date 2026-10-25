-- One row per distinct track that has BOTH a genre mood (artist-level, Last.fm tags) and an audio mood
-- (track-level, ReccoBeats valence/energy). This is the sample the two methods can be compared on.

with tracks as (

    select
        track_id,
        max(track_name) as track_name,
        max(artist_names) as artist_names,
        max(primary_artist_id) as primary_artist_id,
        count(*) as plays
    from {{ ref('stg_recently_played') }}
    group by track_id

),

joined as (

    select
        t.track_id,
        t.track_name,
        t.artist_names,
        t.primary_artist_id,
        m.artist_name as primary_artist_name,
        t.plays,
        m.mood as genre_mood,
        f.valence,
        f.energy
    from tracks t
    inner join {{ ref('stg_artist_moods') }} m
        on t.primary_artist_id = m.artist_id
    inner join {{ ref('stg_track_features') }} f
        on t.track_id = f.track_id
    where f.has_features

)

select
    track_id,
    track_name,
    artist_names,
    primary_artist_id,
    primary_artist_name,
    plays,
    valence,
    energy,
    genre_mood,
    {{ audio_mood('valence', 'energy') }} as audio_mood
from joined
