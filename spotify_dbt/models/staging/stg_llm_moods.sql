-- The latest language-model label per track and variant. If the prompt version or the model changes, the newest
-- label wins, while the older rows stay in raw_llm_moods.
--   hybrid     saw the title, artists, tags AND the ReccoBeats numbers
--   text_only  saw the title, artists and tags only
--   with_notes the hybrid prompt plus my own description of the song (NOT a fair test: it sees my words)

with labelled as (

    select
        track_id,
        case
            when prompt_version like '%hybrid' then 'hybrid'
            when prompt_version like '%text' then 'text_only'
            when prompt_version like '%notes' then 'with_notes'
        end as variant,
        model,
        prompt_version,
        mood,
        confidence,
        reason,
        labelled_at
    from {{ source('spotify_raw', 'raw_llm_moods') }}

)

select distinct on (track_id, variant)
    track_id,
    variant,
    model,
    prompt_version,
    mood,
    confidence,
    reason,
    labelled_at
from labelled
where variant is not null
order by track_id, variant, labelled_at desc
