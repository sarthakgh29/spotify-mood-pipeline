"""HTML for track links with a hover card (cover, title, artist, album). Used by the Streamlit pages.
Everything interpolated into HTML is escaped, and cover URLs must be Spotify image hosts."""
import html

import streamlit as st

from covers import TRACK_ID, is_allowed_cover_url

MOOD_COLORS = {"calm": "#5B9BD5", "mellow": "#1DB954", "intense": "#E33A3A", "upbeat": "#FFC000"}

HOVER_CSS = """<style>
.trk{position:relative;display:inline-block}
.trk a{color:inherit;text-decoration:underline dotted;font-weight:600}
.trk a:hover{color:#1DB954}
.trk .card{display:none;position:absolute;z-index:1000;left:0;top:1.7em;width:290px;gap:10px;align-items:center;
  background:#1e1e1e;border:1px solid #333;border-radius:10px;padding:10px;box-shadow:0 6px 18px rgba(0,0,0,.5);color:#eee}
.trk:hover .card,.trk:focus-within .card{display:flex}
.trk .card img{width:64px;height:64px;border-radius:6px;object-fit:cover;flex:none}
.trk .card .noimg{display:block;width:64px;height:64px;border-radius:6px;background:#333;flex:none}
.trk .card .txt{display:block}
.trk .card b{display:block;font-size:.95rem}
.trk .card .m{display:block;font-size:.8rem;opacity:.75}
table.trk-table{width:100%;border-collapse:collapse;font-size:.92rem}
table.trk-table th{text-align:left;color:#a3a8b4;font-weight:600;padding:6px 8px;border-bottom:1px solid #333}
table.trk-table td{padding:6px 8px;border-bottom:1px solid #2a2a2a;vertical-align:top}
.scroll-box{overflow-y:auto;padding-right:6px;scrollbar-width:thin;scrollbar-color:#555 transparent}
.scroll-box table.trk-table th{position:sticky;top:0;z-index:2;background:#0e1117}
/* A scrolling box clips anything below its edge, so in here the cover card opens beside the row, not under it */
.scroll-box .trk .card{left:100%;top:50%;transform:translateY(-50%);margin-left:10px}
.badge{display:inline-block;padding:1px 10px;border-radius:999px;font-size:.82rem;font-weight:600}
.chip{display:inline-block;margin:1px 4px 1px 0;padding:0 8px;border-radius:999px;border:1px solid;font-size:.8rem}
.chip.ign{border-style:dashed;opacity:.55}
.muted{opacity:.7;font-size:.85rem}
</style>"""


def inject_css():
    st.markdown(HOVER_CSS, unsafe_allow_html=True)


def _clean(value):
    return "" if value is None or (isinstance(value, float) and value != value) else str(value)


def track_html(track_id, name, artist="", album="", cover_url=None):
    """One track name as a Spotify link with a hover card. Single line, so markdown can't mangle it."""
    name_h = html.escape(_clean(name) or "(unknown)")
    if TRACK_ID.fullmatch(_clean(track_id)):
        link = f'<a href="https://open.spotify.com/track/{track_id}" target="_blank" rel="noopener">{name_h}</a>'
    else:
        link = name_h
    cover = _clean(cover_url)
    img = (f'<img src="{html.escape(cover, quote=True)}" alt="">'
           if is_allowed_cover_url(cover) else '<span class="noimg"></span>')
    meta = "".join(f'<span class="m">{html.escape(v)}</span>' for v in (_clean(artist), _clean(album)) if v)
    return f'<span class="trk" tabindex="0">{link}<span class="card">{img}<span class="txt"><b>{name_h}</b>{meta}</span></span></span>'


def track_table(df, extra_columns=(), id_col="track_id", name_col="track_name",
                artist_col="artist_names", album_col="album_name", cover_col="cover_url", html_cols=(),
                scroll_height=None):
    """HTML table: a Track column (link + hover card), the artist, then extra (header, column) pairs.
    Columns named in html_cols hold HTML the caller already escaped (badges, chips); all others are escaped here.
    With scroll_height (pixels) the table sits in a scrolling box with a sticky header."""
    headers = ["Track", "Artist"] + [h for h, _ in extra_columns]
    parts = ['<table class="trk-table"><thead><tr>' + "".join(f"<th>{html.escape(h)}</th>" for h in headers)
             + "</tr></thead><tbody>"]
    for _, row in df.iterrows():
        cells = [
            track_html(row.get(id_col), row.get(name_col), row.get(artist_col),
                       row.get(album_col), row.get(cover_col)),
            html.escape(_clean(row.get(artist_col))),
        ] + [_clean(row.get(c)) if c in html_cols else html.escape(_clean(row.get(c))) for _, c in extra_columns]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    parts.append("</tbody></table>")
    table = "".join(parts)
    if scroll_height:
        return f'<div class="scroll-box" style="max-height:{int(scroll_height)}px">{table}</div>'
    return table


def esc(value):
    return html.escape(_clean(value), quote=True)


def mood_badge(mood):
    """Coloured pill for a mood, or a muted 'none' when there is no label."""
    if not mood:
        return '<span class="muted">none</span>'
    color = MOOD_COLORS.get(mood, "#999999")
    return (f'<span class="badge" style="background:{color}26;border:1px solid {color};color:{color}">'
            f'{esc(mood)}</span>')


def tag_chip(tag, mood=None):
    """A Last.fm tag: coloured when it voted for a mood, dashed grey when it cast no vote."""
    if mood in MOOD_COLORS:
        color = MOOD_COLORS[mood]
        return f'<span class="chip" style="border-color:{color};color:{color}">{esc(tag)}</span>'
    return f'<span class="chip ign">{esc(tag)}</span>'
