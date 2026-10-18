with genres_unnested as (

    select
        artist_id,
        artist_name,
        unnest(genres) as genre
    from {{ source('spotify_raw', 'raw_artist_genres') }}

),

tagged as (

    select
        g.artist_id,
        g.artist_name,
        m.mood
    from genres_unnested g
    inner join {{ ref('genre_mood_map') }} m
        on lower(g.genre) = lower(m.genre)
    where m.mood != 'unclassified'

),

mood_counts as (

    select
        artist_id,
        artist_name,
        mood,
        count(*) as mood_tag_count,
        row_number() over (
            partition by artist_id
            -- mood is the tie-breaker: without it, equal tag counts gave an arbitrary mood that changed between runs
            order by count(*) desc, mood
        ) as rn
    from tagged
    group by artist_id, artist_name, mood

)

select
    artist_id,
    artist_name,
    mood
from mood_counts
where rn = 1