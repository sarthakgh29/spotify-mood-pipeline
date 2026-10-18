"""Mood Lab: label songs by ear (blind), describe them in your own words, then score every mood method against
your labels. Three tabs: Label songs, Scorecard, How to label."""
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text

import ai_labeler
from db import get_engine
from mood_stats import agreement, cohen_kappa
from track_ui import esc, inject_css, mood_badge, track_html, track_table

load_dotenv()
inject_css()

MOODS = ai_labeler.MOODS
BUTTON_ORDER = ["upbeat", "intense", "calm", "mellow"]
DOT = {"upbeat": "🟡", "intense": "🔴", "calm": "🔵", "mellow": "🟢"}
TARGET = 30

# (column in mood_method_eval, name shown, is it a fair test?)
METHODS = [
    ("genre_mood", "Last.fm genre tags", True),
    ("audio_mood", "ReccoBeats audio (valence and energy)", True),
    ("llm_hybrid_mood", "Gemini, with the audio numbers", True),
    ("llm_text_mood", "Gemini, text only", True),
    ("llm_notes_mood", "Gemini + your descriptions", False),  # it sees your words, so it is not a fair test
]

# Only the song's identity is selected here: no method's label can leak into the labelling screen.
POOL_SQL = """
    WITH t AS (
        SELECT track_id, max(track_name) AS track_name, max(artist_names) AS artist_names,
               max(album_name) AS album_name, max(primary_artist_id) AS primary_artist_id
        FROM dbt_dev.stg_recently_played GROUP BY track_id
    )
    SELECT t.track_id, t.track_name, t.artist_names, t.album_name, c.cover_url
    FROM t
    LEFT JOIN dbt_dev.stg_artist_moods g ON g.artist_id = t.primary_artist_id
    LEFT JOIN dbt_dev.stg_track_features f ON f.track_id = t.track_id
    LEFT JOIN dbt_dev.stg_track_covers c ON c.track_id = t.track_id
    WHERE t.track_id NOT IN (SELECT track_id FROM mood_labels)
    -- songs every method can label come first, in a fixed pseudo-random order (stable between reruns)
    ORDER BY (g.mood IS NOT NULL AND coalesce(f.has_features, false)) DESC, md5(t.track_id || 'mood-lab-2')
    LIMIT 60
"""
LABELLED_SQL = """
    SELECT l.track_id, l.mood, l.note, l.labelled_at,
           coalesce(n.name, l.track_id) AS name
    FROM mood_labels l
    LEFT JOIN (SELECT track_id, max(track_name) || ' - ' || max(artist_names) AS name
               FROM dbt_dev.stg_recently_played GROUP BY track_id) n ON n.track_id = l.track_id
    ORDER BY l.labelled_at DESC
"""


CLAUDE_SQL = """
    SELECT e.*, c.mood AS claude_mood, c.confidence AS claude_conf, c.reason AS claude_reason,
           c.saw_label_before, t.album_name, cv.cover_url
    FROM dbt_dev.mood_method_eval e
    JOIN claude_thoughts c ON c.track_id = e.track_id
    LEFT JOIN (SELECT track_id, max(album_name) AS album_name
               FROM dbt_dev.stg_recently_played GROUP BY track_id) t ON t.track_id = e.track_id
    LEFT JOIN dbt_dev.stg_track_covers cv ON cv.track_id = e.track_id
"""


def save_label(track_id, mood, note):
    note = ai_labeler.clean_note(note) or None
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO mood_labels (track_id, mood, note) VALUES (:t, :m, :n)
            ON CONFLICT (track_id) DO UPDATE SET mood = :m, note = :n, labelled_at = now()"""),
                     {"t": track_id, "m": mood, "n": note})


def delete_label(track_id):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM mood_labels WHERE track_id = :t"), {"t": track_id})


st.title("🧪 Mood Lab")
st.markdown(
    "Label songs by ear, then see which method is closest to **you**. While you label, no method's guess is shown, "
    "so it can't sway you."
)

try:
    labelled = pd.read_sql(LABELLED_SQL, get_engine())
    pool = pd.read_sql(POOL_SQL, get_engine())
except Exception as exc:
    st.error("Couldn't read the labels. Check that Postgres is running and that the mood_labels table has its `note` "
             "column (see sql/init.sql).")
    st.code(str(exc))
    st.stop()

tab_label, tab_score, tab_claude, tab_help = st.tabs(["🎧 Label songs", "📊 Scorecard", "🧠 Claude's thoughts", "📖 How to label"])

# ================================================================= tab 1: label
with tab_label:
    done = len(labelled)
    st.progress(min(done / TARGET, 1.0),
                text=f"{done} of {TARGET} labelled" + ("  -  enough for a first look" if done >= TARGET else ""))
    st.info(f"**The rule:** {ai_labeler.LABELLING_RULE}", icon="💡")

    skipped = st.session_state.setdefault("lab_skipped", set())
    queue = pool[~pool["track_id"].isin(skipped)]
    if queue.empty:
        st.success("No more songs to label right now." if not pool.empty else "Every song is labelled.")
    else:
        row = queue.iloc[0]
        tid = row["track_id"]
        with st.container(border=True):
            left, right = st.columns([1, 3])
            with left:
                if isinstance(row["cover_url"], str):
                    st.image(row["cover_url"], width=190)
            with right:
                st.markdown(
                    f"### {track_html(tid, row['track_name'], row['artist_names'], row['album_name'], row['cover_url'])}",
                    unsafe_allow_html=True)
                st.write(row["artist_names"])
                st.caption(f"{row['album_name']}  |  click the title to open it in Spotify, listen, then choose.")
                note = st.text_area(
                    "Describe it in your own words (optional)",
                    key=f"note_{tid}", height=80, max_chars=ai_labeler.NOTE_MAX_CHARS,
                    placeholder="e.g. pre-gym hype, dark and confident  |  late-night drive, wistful",
                    help="Saved with your label. It is only sent to Gemini's 'with your descriptions' variant, "
                         "never to the fair tests.")
                cols = st.columns(5)
                for col, mood in zip(cols[:4], BUTTON_ORDER):
                    if col.button(f"{DOT[mood]} {mood.capitalize()}", key=f"mood_{mood}_{tid}", width="stretch"):
                        save_label(tid, mood, note)
                        st.rerun()
                if cols[4].button("Skip", key=f"skip_{tid}", width="stretch"):
                    skipped.add(tid)
                    st.rerun()

    if not labelled.empty:
        st.markdown("**Your latest labels**")
        recent = labelled.head(5)
        st.dataframe(
            pd.DataFrame({"Song": recent["name"], "Mood": recent["mood"].str.capitalize(),
                          "Your description": recent["note"].fillna("")}),
            hide_index=True, width="stretch")
        c_undo, _ = st.columns([1, 3])
        if c_undo.button("↩ Undo the last label"):
            delete_label(labelled.iloc[0]["track_id"])
            st.rerun()

        with st.expander("Change a label or description, or remove one"):
            by_id = labelled.set_index("track_id")
            pick = st.selectbox("Song", list(by_id.index), format_func=lambda t: by_id.loc[t, "name"])
            new_mood = st.radio("Mood", BUTTON_ORDER, index=BUTTON_ORDER.index(by_id.loc[pick, "mood"]),
                                horizontal=True, format_func=str.capitalize, key=f"edit_mood_{pick}")
            new_note = st.text_area("Description", value=by_id.loc[pick, "note"] or "", height=70,
                                    max_chars=ai_labeler.NOTE_MAX_CHARS, key=f"edit_note_{pick}")
            e1, e2, _ = st.columns([1, 1, 3])
            if e1.button("Save change"):
                save_label(pick, new_mood, new_note)
                st.rerun()
            if e2.button("Remove this label"):
                delete_label(pick)
                st.rerun()

# ================================================================= tab 2: scorecard
with tab_score:
    if labelled.empty:
        st.info("Label a few songs and the scorecard appears here.")
    else:
        ev = pd.read_sql("SELECT * FROM dbt_dev.mood_method_eval", get_engine())
        n = len(ev)
        if n < TARGET:
            st.warning(f"Only {n} labelled so far. With fewer than {TARGET}, agreement and kappa swing a lot: "
                       "treat them as rough.")

        if not ev[["llm_hybrid_mood", "llm_text_mood", "llm_notes_mood"]].notna().any().any():
            st.info("Gemini hasn't labelled these songs yet. After adding GEMINI_API_KEY to .env, run  "
                    "`python ingest_llm_moods.py --only-labelled`  (try `--dry-run` first to see what would be sent).")

        fair_cols = [c for c, _, fair in METHODS if fair and ev[c].notna().any()]
        common = ev.dropna(subset=fair_cols) if fair_cols else ev.iloc[0:0]
        rows = []
        for col, name, fair in METHODS:
            has = ev[ev[col].notna()]
            label = name if fair else f"{name} (sees your notes)"
            if has.empty:
                rows.append({"Method": label, "Can label": f"0 of {n}", "Agrees with me": None, "Kappa": None, "Common": None})
                continue
            k = cohen_kappa(has["user_mood"], has[col])
            rows.append({
                "Method": label,
                "Can label": f"{len(has)} of {n}",
                "Agrees with me": agreement(has["user_mood"], has[col]),
                "Kappa": None if k != k else k,
                "Common": agreement(common["user_mood"], common[col]) if fair and len(common) else None,
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={
                "Agrees with me": st.column_config.ProgressColumn("Agrees with me", min_value=0.0, max_value=1.0, format="percent"),
                "Common": st.column_config.ProgressColumn(f"Same {len(common)} songs for all", min_value=0.0, max_value=1.0, format="percent"),
                "Kappa": st.column_config.NumberColumn("Cohen's kappa", format="%.2f"),
            },
        )
        st.caption(
            "**Can label** is coverage: a method that can't label a song (no tags, no ReccoBeats data, not run yet) is left "
            "out of its own row. **Same songs for all** compares the fair methods on only the songs every one of them labelled. "
            "**Kappa** discounts the agreement you would get by chance: 0 is no better than chance, 1 is perfect. "
            "The last row sees your own descriptions of the songs, so its agreement is inflated: don't rank it against the others."
        )

        shown = {c: nm for c, nm, _ in METHODS}
        pick_method = st.selectbox("Look closer at", list(shown), format_func=shown.get)
        sub = ev[ev[pick_method].notna()]
        if sub.empty:
            st.info("This method has no labels for your songs yet.")
        else:
            a, b = st.columns([2, 3])
            with a:
                ct = pd.crosstab(pd.Categorical(sub["user_mood"], categories=MOODS),
                                 pd.Categorical(sub[pick_method], categories=MOODS), dropna=False)
                fig = px.imshow(ct.values, x=[m.capitalize() for m in MOODS], y=[m.capitalize() for m in MOODS],
                                text_auto=True, color_continuous_scale="Greens",
                                labels=dict(x="Method says", y="You said", color="Songs"))
                fig.update_layout(margin=dict(t=10), height=360, coloraxis_showscale=False)
                st.plotly_chart(fig, width="stretch", key="lab_confusion")
            with b:
                miss = sub[sub[pick_method] != sub["user_mood"]]
                st.markdown(f"**Where it disagreed with you** ({len(miss)} of {len(sub)})")
                if miss.empty:
                    st.success("It agreed with every label.")
                else:
                    table = pd.DataFrame({"Song": miss["track_name"], "Artist": miss["artist_names"],
                                          "You": miss["user_mood"], "Method": miss[pick_method]})
                    stem = {"llm_hybrid_mood": "llm_hybrid", "llm_text_mood": "llm_text", "llm_notes_mood": "llm_notes"}.get(pick_method)
                    if stem:
                        table["Confidence"] = miss[f"{stem}_confidence"]
                        table["Gemini's reason"] = miss[f"{stem}_reason"]
                    if pick_method == "llm_notes_mood":
                        table["Your description"] = miss["user_note"].fillna("")
                    st.dataframe(table, hide_index=True, width="stretch", height=320)

# ================================================================= tab: Claude's thoughts
with tab_claude:
    st.subheader("Claude's thoughts: a one-time, theoretical test")
    st.markdown(
        "As an experiment, Claude (the AI assistant that helped build this project) labelled the same songs **once, by hand**, "
        "as if it were another method. It saw only what Gemini's 'with the audio numbers' run sees: title, artists, album, "
        "Last.fm tags and ReccoBeats' numbers where they exist, plus the labelling rule on the first tab, plus whatever Claude "
        "already knew about a song. It did **not** look at your labels or descriptions before writing its own down. "
        "This is a snapshot, not part of the pipeline: it can't be re-run or updated by a script."
    )
    st.warning(
        "**What can bias this test:** before labelling, Claude had seen your *first* 18 labels (a backup from before the reset) "
        "and the overall results of the Gemini run (your label mix and Gemini's confusion table). Songs whose earlier label "
        "Claude had seen are flagged, and the 'clean' columns below leave them out. Treat the clean numbers as the honest ones."
    )
    try:
        cl = pd.read_sql(CLAUDE_SQL, get_engine())
    except Exception:
        cl = None
    if cl is None or cl.empty:
        st.info("The snapshot isn't loaded. Run  `python analysis/load_claude_thoughts.py`  (see analysis/claude_thoughts.json).")
    else:
        clean = cl[~cl["saw_label_before"]]
        cols = [("claude_mood", "Claude (by hand, once)"), ("audio_mood", "ReccoBeats audio rule"),
                ("llm_hybrid_mood", "Gemini + audio numbers"), ("llm_text_mood", "Gemini, text only"),
                ("genre_mood", "Last.fm genre tags")]

        def numbers(frame, col):
            d = frame[frame[col].notna()]
            if d.empty:
                return 0, None, None
            k = cohen_kappa(d["user_mood"], d[col])
            return len(d), agreement(d["user_mood"], d[col]), (None if k != k else k)

        rows = []
        for col, name in cols:
            n_all, a_all, k_all = numbers(cl, col)
            n_cl, a_cl, k_cl = numbers(clean, col)
            rows.append({"Method": name, "Songs": n_all, "Agrees": a_all, "Kappa": k_all,
                         "Clean songs": n_cl, "Agrees (clean)": a_cl, "Kappa (clean)": k_cl})
        st.markdown(f"**Against your labels** ({len(cl)} songs; {len(clean)} are 'clean')")
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={
                "Agrees": st.column_config.ProgressColumn("Agrees", min_value=0.0, max_value=1.0, format="percent"),
                "Agrees (clean)": st.column_config.ProgressColumn("Agrees (clean)", min_value=0.0, max_value=1.0, format="percent"),
                "Kappa": st.column_config.NumberColumn("Kappa", format="%.2f"),
                "Kappa (clean)": st.column_config.NumberColumn("Kappa (clean)", format="%.2f"),
            })
        st.caption("Methods label different numbers of songs (the audio rule and Last.fm can't label songs with no data), so rows "
                   "aren't strictly comparable. With this few songs a gap of ten points or so is within noise.")

        left, right = st.columns(2)
        with left:
            st.markdown("**Does Claude know when it is unsure?** (clean songs)")
            calib = []
            for level in ("high", "medium", "low"):
                g = clean[clean["claude_conf"] == level]
                calib.append({"Claude's confidence": level, "Songs": len(g),
                              "Agrees with you": agreement(g["user_mood"], g["claude_mood"]) if len(g) else None})
            st.dataframe(pd.DataFrame(calib), hide_index=True, width="stretch", column_config={
                "Agrees with you": st.column_config.ProgressColumn("Agrees with you", min_value=0.0, max_value=1.0, format="percent")})
        with right:
            st.markdown("**The songs ReccoBeats has no numbers for**")
            gap = cl[cl["audio_mood"].isna()]
            if gap.empty:
                st.write("None.")
            else:
                st.metric(f"{len(gap)} songs: Claude agrees with you", f"{agreement(gap['user_mood'], gap['claude_mood']):.0%}")
                st.caption("Gemini (text only) on the same songs: "
                           f"{agreement(gap['user_mood'], gap['llm_text_mood']):.0%}" if gap["llm_text_mood"].notna().any() else "")
                st.caption("These are mostly recent releases an AI model hasn't heard of, so it is guessing from titles and tags, "
                           "like the other methods. That is the gap a supplement has to fill.")

        a, b = st.columns([2, 3])
        with a:
            st.markdown("**You (rows) vs Claude (columns)**")
            ct = pd.crosstab(pd.Categorical(cl["user_mood"], categories=MOODS),
                             pd.Categorical(cl["claude_mood"], categories=MOODS), dropna=False)
            fig = px.imshow(ct.values, x=[m.capitalize() for m in MOODS], y=[m.capitalize() for m in MOODS], text_auto=True,
                            color_continuous_scale="Greens", labels=dict(x="Claude says", y="You said", color="Songs"))
            fig.update_layout(margin=dict(t=10), height=340, coloraxis_showscale=False)
            st.plotly_chart(fig, width="stretch", key="claude_confusion")
        with b:
            st.markdown("**Mix of labels**")
            mix = pd.DataFrame({"You": cl["user_mood"].value_counts(), "Claude": cl["claude_mood"].value_counts()}).reindex(MOODS).fillna(0).astype(int)
            mix.index = [m.capitalize() for m in mix.index]
            st.dataframe(mix, width="stretch")

        st.markdown("**Song by song** (hover a title for its cover; the title links to Spotify)")
        view = st.radio("Show", ["All songs", "Only where Claude disagreed with you", "Only songs whose earlier label Claude had not seen"],
                        horizontal=True, key="claude_view")
        songs = cl.copy()
        if view.startswith("Only where"):
            songs = songs[songs["claude_mood"] != songs["user_mood"]]
        elif view.startswith("Only songs"):
            songs = songs[~songs["saw_label_before"]]
        if songs.empty:
            st.info("No songs match.")
        else:
            songs = songs.assign(
                **{"Claude": songs["claude_mood"].map(mood_badge), "You": songs["user_mood"].map(mood_badge),
                   "Result": (songs["claude_mood"] == songs["user_mood"]).map({
                       True: '<span style="color:#1DB954;font-weight:600">Same</span>',
                       False: '<span style="color:#FFC000;font-weight:600">Differs</span>'}),
                   "Confidence": songs["claude_conf"], "Claude's reason": songs["claude_reason"],
                   "Seen before": songs["saw_label_before"].map({True: "yes", False: ""})})
            st.markdown(track_table(songs, [("Claude says", "Claude"), ("Confidence", "Confidence"), ("You said", "You"),
                                            ("Result", "Result"), ("Claude's reason", "Claude's reason"),
                                            ("Earlier label seen", "Seen before")],
                                    html_cols=("Claude", "You", "Result"), scroll_height=520), unsafe_allow_html=True)

# ================================================================= tab 3: help
with tab_help:
    st.subheader("How to decide a mood")
    st.markdown(ai_labeler.DEFINITIONS)
    st.markdown(ai_labeler.LABELLING_RULE)
    st.markdown("**Worked examples**")
    st.dataframe(pd.DataFrame([
        {"Song type": "Pre-gym hype, dark and swaggering", "Energy": "High", "Tone": "Dark / heavy", "Mood": "Intense"},
        {"Song type": "Pre-gym hype, euphoric and feel-good", "Energy": "High", "Tone": "Bright", "Mood": "Upbeat"},
        {"Song type": "Late-night drive, wistful", "Energy": "Low", "Tone": "Wistful / sad", "Mood": "Mellow"},
        {"Song type": "Sunday morning, warm and gentle", "Energy": "Low", "Tone": "Bright / warm", "Mood": "Calm"},
    ]), hide_index=True, width="stretch")
    st.markdown(
        "**Label the song, not the occasion.** Every method here only sees the song, so judging by when you play it would "
        "grade them on something they can't know. A quick test: *with no context, how would the first 30 seconds feel?* "
        "If it really sits between two moods, pick the one you'd say first, or Skip."
    )
    st.subheader("What the description box does")
    st.markdown(
        "Your description is saved with your label. It is sent **only** to a separate Gemini run called *with your "
        "descriptions*, and only for songs you described. That row is not a fair test, because Gemini is reading your own "
        "words about the same song you labelled, so it is shown apart from the fair methods. The fair runs (with and "
        "without the audio numbers) never see it."
    )
    st.subheader("What is sent to Gemini")
    st.markdown(
        "Only song metadata: title, artist names, album, Last.fm tags, ReccoBeats' numbers (in two of the three runs) and, "
        "for the descriptions run, your description. Never ids, dates, keys or play history. On Google's free tier "
        "prompts may be used to improve its products, so enable billing if that matters to you."
    )
