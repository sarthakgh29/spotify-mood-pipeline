* Validation: does the genre-based mood agree with the audio-based mood?
* Same analysis as validate_moods.py (percent agreement, confusion matrix, Cohen's kappa), at track and artist level.
*
* Usage: run  python analysis/export_mood_data.py  first, then set Stata's working directory to this analysis/
* folder and run:  do validate_moods.do
* NOTE: not run here, because Stata is not installed on this machine. The Python script is the tested version;
* both should print the same numbers.

clear all
set more off
global outdir "output"

foreach level in track artist {

    di _newline as text "=== `level' level ==="
    import delimited "${outdir}/mood_comparison_`level'.csv", clear varnames(1) stringcols(_all)

    * string moods -> numeric codes with one fixed label order, so both methods share the same categories
    label define moodlbl 1 "calm" 2 "mellow" 3 "intense" 4 "upbeat", replace
    foreach v in genre_mood audio_mood {
        gen `v'_n = .
        replace `v'_n = 1 if `v' == "calm"
        replace `v'_n = 2 if `v' == "mellow"
        replace `v'_n = 3 if `v' == "intense"
        replace `v'_n = 4 if `v' == "upbeat"
        label values `v'_n moodlbl
    }

    count
    di as text "n = " as result r(N)

    * percent agreement
    gen byte agree = (genre_mood_n == audio_mood_n)
    quietly summarize agree
    di as text "percent agreement = " as result %5.1f 100*r(mean) as text "%"

    * confusion matrix (rows = genre mood, columns = audio mood)
    tabulate genre_mood_n audio_mood_n

    * Cohen's kappa, treating the two methods as two raters. Undefined if either method uses a single label.
    capture noisily kap genre_mood_n audio_mood_n
    if _rc {
        di as error "kappa could not be computed (too few rows, or a method uses a single label)"
    }
}
