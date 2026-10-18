-- One row per primary artist: the genre mood next to the artist's audio mood, where the artist's audio mood is
-- the most common audio mood across their compared tracks (alphabetical order breaks ties).

with counts as (

    select
        primary_artist_id,
        primary_artist_name,
        genre_mood,
        audio_mood,
        count(*) as tracks_with_this_mood
    from {{ ref('mood_comparison_track') }}
    group by 1, 2, 3, 4

),

ranked as (

    select
        *,
        row_number() over (
            partition by primary_artist_id
            order by tracks_with_this_mood desc, audio_mood
        ) as rn,
        sum(tracks_with_this_mood) over (partition by primary_artist_id) as tracks
    from counts

)

select
    primary_artist_id as artist_id,
    primary_artist_name as artist_name,
    genre_mood,
    audio_mood,
    tracks
from ranked
where rn = 1
