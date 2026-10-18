-- My own hand labels (the ground truth the three methods are scored against).
select
    track_id,
    mood,
    nullif(trim(note), '') as note,
    labelled_at
from {{ source('spotify_raw', 'mood_labels') }}
