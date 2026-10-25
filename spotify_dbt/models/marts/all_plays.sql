-- Every play: the downloaded history, then pipeline plays that came after the history ends.
with history as (
    select
        played_at, track_id, track_name, artist_name, album_name,
        seconds_played, is_real_play, skipped, 'history' as source
    from {{ ref('stg_streaming_history') }}
),

pipeline as (
    select
        p.played_at, p.track_id, p.track_name,
        coalesce(g.artist_name, split_part(p.artist_names, ', ', 1)) as artist_name,
        p.album_name,
        p.duration_ms / 1000.0 as seconds_played,
        true as is_real_play,
        false as skipped,
        'pipeline' as source
    from {{ ref('stg_recently_played') }} p
    left join {{ source('spotify_raw', 'raw_artist_genres') }} g on g.artist_id = p.primary_artist_id
    where p.track_id not in (select track_id from {{ ref('excluded_tracks') }})
      and p.played_at > (select coalesce(max(played_at), '1900-01-01') from history)
)

select * from history
union all
select * from pipeline
