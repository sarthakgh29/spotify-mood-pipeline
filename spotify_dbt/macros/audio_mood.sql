{#
  Mood from a track's own valence and energy (ReccoBeats). Same rule as play_mood_comparison:
    high energy + high valence -> upbeat      high energy + low valence -> intense
    low energy  + high valence -> calm        low energy  + low valence -> mellow
  Thresholds default to 0.5 and can be overridden with --vars '{energy_threshold: 0.6, valence_threshold: 0.45}'.
#}
{% macro audio_mood(valence, energy) %}
    case
        when {{ energy }} >= {{ var('energy_threshold', 0.5) }}
         and {{ valence }} >= {{ var('valence_threshold', 0.5) }} then 'upbeat'
        when {{ energy }} >= {{ var('energy_threshold', 0.5) }} then 'intense'
        when {{ valence }} >= {{ var('valence_threshold', 0.5) }} then 'calm'
        else 'mellow'
    end
{% endmacro %}
