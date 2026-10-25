"""The Wrapped card as a PNG (1080 x 1350, the shape Instagram posts and stories like), for the Lifetime Wrapped page's download button.

The layout follows the card download in Johan's Lifetime-Wrapped project (js/app.js, downloadCard), drawn here with Pillow because this
dashboard runs on Python. build_card_png() does no network access; fetch_cover_bytes() is the only function that does.
"""
import io
import os

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import covers

W, H = 1080, 1350
GRADIENT = [(0.0, (11, 61, 46)), (0.55, (29, 185, 84)), (1.0, (123, 227, 154))]      # #0b3d2e, #1db954, #7be39a
FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu", "/Library/Fonts",
             "/System/Library/Fonts/Supplemental"]
# (regular, semibold, bold) per script; the first file found is used. Songs in Japanese, Korean or Hindi need their own fonts.
FONTS = {
    "latin": [("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf", "arialbd.ttf"), ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf")],
    "cjk": [("YuGothM.ttc", "YuGothB.ttc", "YuGothB.ttc"), ("msyh.ttc", "msyhbd.ttc", "msyhbd.ttc"), ("ARIALUNI.ttf", "ARIALUNI.ttf", "ARIALUNI.ttf")],
    "korean": [("malgun.ttf", "malgunbd.ttf", "malgunbd.ttf")],
    "indic": [("Nirmala.ttc", "Nirmala.ttc", "Nirmala.ttc")],
}


def _script(text):
    for ch in text:
        o = ord(ch)
        if 0x3000 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF:
            return "cjk"
        if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            return "korean"
        if 0x0900 <= o <= 0x0DFF:
            return "indic"
    return "latin"


_font_cache = {}


def font_for(text, size, weight=400):
    """A font that can draw `text`, at this size; weight 400 regular, 600 semibold, 700 and up bold."""
    script, idx = _script(text), 0 if weight < 600 else 1 if weight < 700 else 2
    key = (script, size, idx)
    if key not in _font_cache:
        found = None
        for files in FONTS[script] + (FONTS["latin"] if script != "latin" else []):
            for d in FONT_DIRS:
                path = os.path.join(d, files[idx])
                if os.path.exists(path):
                    try:
                        found = ImageFont.truetype(path, size)
                    except OSError:
                        continue
                    break
            if found:
                break
        _font_cache[key] = found or ImageFont.load_default(size)
    return _font_cache[key]


def clip(draw, text, max_width, size, weight):
    """`text`, shortened with "..." if it would be wider than max_width. Takes one letter off at a time, so it always ends."""
    text = str(text)
    f = font_for(text, size, weight)
    if draw.textlength(text, font=f) <= max_width:
        return text
    while len(text) > 1 and draw.textlength(text + "...", font=f) > max_width:
        text = text[:-1]
    return text.rstrip() + "..."


def gradient_background():
    """The diagonal green gradient of the card, from the top left to the bottom right corner."""
    ys, xs = np.mgrid[0:H, 0:W]
    t = (xs * W + ys * H) / float(W * W + H * H)
    out = np.zeros((H, W, 3))
    for (t0, c0), (t1, c1) in zip(GRADIENT, GRADIENT[1:]):
        m = (t >= t0) & (t <= t1)
        f = ((t - t0) / (t1 - t0))[m]
        for ch in range(3):
            out[..., ch][m] = c0[ch] + (c1[ch] - c0[ch]) * f
    return Image.fromarray(out.astype("uint8"), "RGB")


def fetch_cover_bytes(url, timeout=8):
    """The image at a Spotify cover URL, or None. Only Spotify's image hosts are fetched."""
    if not covers.is_allowed_cover_url(url):
        return None
    try:
        r = requests.get(url, timeout=timeout)
        return r.content if r.status_code == 200 and r.content else None
    except requests.RequestException:
        return None


def build_card_png(card, cover_bytes=None):
    """card: {label, sub, minutes, plays, songs, artists, top: {name, artist, plays}, top_songs: [(name, artist)], top_artists: [(name, plays)]}.
    Returns the PNG as bytes. With cover_bytes the number one song's cover is drawn at the right of the "#1 song" block."""
    img = gradient_background().convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def text(t, x, y, size, weight, alpha, max_w=None):
        t = clip(d, t, max_w, size, weight) if max_w else str(t)
        d.text((x, y), t, font=font_for(t, size, weight), fill=(255, 255, 255, int(alpha * 255)), anchor="ls")

    n0 = lambda v: f"{round(v):,}"
    text("LIFETIME WRAPPED", 80, 120, 28, 600, .8)
    text(card["label"], 80, 230, 120, 700, 1)
    text(card["sub"], 80, 290, 34, 400, .85, W - 160)
    for k, (v, label) in enumerate([(card["minutes"], "minutes listened"), (card["plays"], "real plays"),
                                    (card["songs"], "different songs"), (card["artists"], "different artists")]):
        x, y = 80 + (k % 2) * 480, 420 + (k // 2) * 150
        text(n0(v), x, y, 70, 700, 1)
        text(label, x, y + 42, 28, 400, .85)

    top = card["top"]
    cover = None
    if cover_bytes:
        try:
            cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB").resize((220, 220))
        except Exception:
            cover = None                      # a broken download should never stop the card from being made
    tw = 600 if cover else W - 160
    text("#1 SONG", 80, 760, 26, 600, .75)
    text(top["name"], 80, 815, 48, 700, 1, tw)
    text(f"{top['artist']}, {n0(top['plays'])} plays", 80, 862, 30, 400, .85, tw)

    def column(title, rows, x):
        text(title, x, 960, 26, 600, .75)
        for k, (a, b) in enumerate(rows[:5]):
            text(f"{k + 1}. {a}", x, 1004 + k * 64, 30, 600, 1, 440)
            text(b, x + 38, 1036 + k * 64, 24, 400, .8, 400)

    column("TOP SONGS", card["top_songs"], 80)
    column("TOP ARTISTS", [(a, f"{n0(p)} plays") for a, p in card["top_artists"]], 570)
    text("Made from my Spotify listening history", 80, H - 22, 22, 400, .65)

    img = Image.alpha_composite(img, layer).convert("RGB")
    if cover:
        mask = Image.new("L", (220, 220), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 219, 219), radius=18, fill=255)
        img.paste(cover, (780, 690), mask)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
