# How the hosted Lifetime Wrapped works

A guide to the standalone **Lifetime Wrapped** site: https://lifetime-wrapped.pages.dev/
Source code: https://github.com/johanchopra28/Lifetime-Wrapped (built by Johan Chopra and Sarthak Sharma).

This is the *hosted, browser-only* version. It is a different program from the "Lifetime Wrapped" tab in your Spotify Mood
Pipeline dashboard (that one runs on Python, Postgres and dbt). Both do the same job and share the same maths, but this one needs
no server and no database: everything happens inside the visitor's web browser.

Read it top to bottom, or jump to a section. Real file names, real code and real numbers are used throughout, so you can open
the file next to this guide. State of the repo described here: 42 commits, latest on 25 Oct 2026.

**Contents**

1. [The 60-second version](#1-the-60-second-version)
2. [One file's journey](#2-one-files-journey)
3. [File map](#3-file-map)
4. [Hosting: how it gets onto the internet](#4-hosting-how-it-gets-onto-the-internet)
5. [Privacy and security design](#5-privacy-and-security-design)
6. [Reading the Spotify file (`load.js`)](#6-reading-the-spotify-file-loadjs)
7. [The data model: plays, real plays, songs](#7-the-data-model-plays-real-plays-songs)
8. [The analysis (`analysis.js`)](#8-the-analysis-analysisjs)
9. [The page (`app.js`) and the charts](#9-the-page-appjs-and-the-charts)
10. [Album covers](#10-album-covers)
11. [The Wrapped card and its PNG download](#11-the-wrapped-card-and-its-png-download)
12. [The Song Globe](#12-the-song-globe)
13. [Sample data](#13-sample-data)
14. [The Streamlit version](#14-the-streamlit-version)
15. [Testing](#15-testing)
16. [Challenges and how each was solved](#16-challenges-and-how-each-was-solved)
17. [How it was made, in order](#17-how-it-was-made-in-order)
18. [Recipes: how to change things](#18-recipes-how-to-change-things)
19. [Cheat sheet and troubleshooting](#19-cheat-sheet-and-troubleshooting)
20. [Glossary](#20-glossary)

---

## 1. The 60-second version

Spotify will give you a zip file of your **Extended streaming history**: one record for every play since you joined (title,
artist, album, time, how many milliseconds you listened). This site turns that file into a "lifetime wrapped": top songs and
artists, the song that ruled each month, when you listen, what you keep coming back to, songs you left behind, an artist deep
dive, a spinnable song globe and a downloadable card.

The key idea: **there is no server.** The page is a handful of plain files (HTML, CSS, JavaScript). When someone opens it, their
browser downloads those files and *runs them locally*. When they pick their zip, the browser reads it on their own computer.
The file is never uploaded anywhere, because there is nothing to upload it to.

```
visitor's browser
  1. downloads index.html + style.css + js/*.js (from Cloudflare)
  2. visitor picks their Spotify zip  ----------------->  stays on their computer
  3. JavaScript unzips it, reads the plays, works out every chart
  4. (only) album covers are requested from Spotify, one song id at a time
```

There are no outside libraries: no React, no chart library, no zip library. Everything is written out in the repo, so the whole
program can be read.

---

## 2. One file's journey

What happens from "I picked my zip" to "I see my wrapped":

```
 zip file (e.g. my_spotify_data.zip)
        |
  load.js     finds Streaming_History_Audio_*.json inside the zip, unzips each one in the browser,
        |     keeps only 8 fields per play (song, artist, album, time, length, ...) - everything else is ignored
        v
  plays = [{ts, ms, id, name, artist, album, skipped}, ...]        (one object per play)
        |
  analysis.js prepare(): adds year, month, hour, weekday, "day number", song key; sorts by time;
        |     marks "real plays" (30 seconds or more)
        v
  state.data = { all: every play, real: only real plays }
        |
  analysis.js  pure functions turn it into numbers: top songs, streaks, drift, ...
        |
  app.js       builds HTML strings for the selected tab, puts them in the page; charts.js draws SVG
        |
  covers       (in the background) ask Spotify for album art of the songs on screen, fill in the images
```

Everything after the first arrow runs in memory. Close the tab and every trace is gone.

---

## 3. File map

```
Lifetime-Wrapped/
|-- index.html        The page: landing section + the (hidden until data is loaded) app section.  101 lines
|-- style.css         All the styling, dark by default with a light theme.                         253 lines
|-- _headers          Cloudflare/Netlify read this: security headers sent with every page.          8 lines
|-- js/
|   |-- app.js        The page's brain: state, tabs, events, covers, card download.                598 lines
|   |-- analysis.js   All the maths, as plain functions on arrays (no web page code).              457 lines
|   |-- load.js       Reads the zip / JSON files in the browser.                                    80 lines
|   |-- charts.js     Draws the SVG charts (bars, heatmap, calendar, stream chart).                170 lines
|   |-- embed.js      Works out the 2-D "song map" for the globe (sessions -> SVD -> t-SNE).        156 lines
|   |-- globe.js      Draws and runs the song globe, plus the "Pin this song" tray.                 270 lines
|   `-- sample.js     Makes up a fake history for "Try it with sample data".                         70 lines
|-- bundle.py         Glues the page into ONE html file (used only by the Streamlit version).
|-- streamlit_app.py  The Streamlit wrapper around that single page.
|-- requirements.txt  (just streamlit, for the Streamlit version)
|-- tests/            reference.py + compare.js (check maths against the Python version), make_nocsp.py
`-- README.md
```

About 160 KB of source in total: small enough to load instantly and to read.

---

## 4. Hosting: how it gets onto the internet

### 4.1 A "static site"

A static site is just files that a web server hands out unchanged. There is no program running on the server and no database.
That is the simplest and cheapest way to publish something, and it fits the privacy promise: a server that never sees your data
cannot leak it.

### 4.2 Cloudflare Pages

The live site is hosted on **Cloudflare Pages**, which is connected to the GitHub repository. In practice:

1. You (or Johan) push a commit to the `main` branch on GitHub.
2. Cloudflare notices, copies the repository's files and publishes them at https://lifetime-wrapped.pages.dev/.
3. This takes about 30 seconds (observed: after a push, the live files matched the repo within a minute).

There is **no build step**: no compiling, no bundling. Cloudflare serves the repository root as it is. That is why the code is
written as plain files that browsers understand directly. The live site's files match `main`.

> Tip: right after you push, if the live page looks old, wait a minute and hard-refresh (Ctrl+Shift+R). Browsers cache files.

### 4.3 `_headers`: security rules sent with every page

```
/*
  Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data: https://*.spotifycdn.com https://*.scdn.co; connect-src https://open.spotify.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=()
```

`/*` means "every file". Cloudflare Pages (and Netlify) read this file and attach those lines as HTTP headers. What each one does
is explained in section 5. The same policy also appears inside `index.html` as a `<meta>` tag; the header is the stronger copy
(the browser applies it before the page even starts, and it can also say `frame-ancestors`, which a meta tag cannot). The
meta tag is a fallback for hosts that cannot send headers. They are identical except that the header adds
`frame-ancestors 'none'` ("nobody may put this site inside their own page").

### 4.4 Three branches

The GitHub repo has `main` (the live site), `streamlit-test` (used to try the Streamlit version, with the globe commits) and
`release`. The live site matches `main`.

### 4.5 Running it on your own computer

ES modules (`import ... from "./analysis.js"`) do not load from a `file://` address, so you need any simple web server:

```powershell
cd path\to\Lifetime-Wrapped
python -m http.server 8600
```

then open http://localhost:8600 and choose your zip.

---

## 5. Privacy and security design

The site makes strong promises, and the code is arranged so the promises are enforced by the browser, not just by good intentions.

### 5.1 The Content-Security-Policy (CSP), directive by directive

A CSP is a list of rules the browser enforces about what a page may load and where it may talk. Here, directive by directive:

| Directive | Value | Plain meaning |
|---|---|---|
| `default-src` | `'none'` | By default the page may load **nothing** from anywhere |
| `script-src` | `'self'` | JavaScript may only come from this site's own files (no outside scripts, no injected scripts) |
| `style-src` | `'self' 'unsafe-inline'` | CSS from this site's files, plus inline style attributes |
| `img-src` | `data:` + Spotify image hosts | Images may be embedded data (`data:`) or come from `*.spotifycdn.com` / `*.scdn.co` (album covers) |
| `connect-src` | `https://open.spotify.com` | The page may make network requests **only** to Spotify's public cover lookup |
| `base-uri` | `'none'` | Nobody can change where relative links point |
| `form-action` | `'none'` | No form can ever send data anywhere |
| `frame-ancestors` | `'none'` (header only) | Other sites cannot embed this one |

The consequence: **even if a bug or a malicious piece of text got into the page, the browser would block it from sending your
history anywhere**, because the only place the page is allowed to talk to is Spotify's cover service.

### 5.2 What does leave the page

Only the album-cover lookup. For each song shown on screen, the page asks `https://open.spotify.com/oembed?url=...track/<id>`
for the cover. So Spotify receives the **track ids** of the songs on screen, and, as with any web request, your IP address. It
never receives the file, your name or your history. (This is stated openly on the page.) The made-up sample data skips covers,
so the demo sends nothing at all.

### 5.3 What is never read or stored

- The IP address, country and device that Spotify puts in every record are **not copied out of the JSON** (`load.js`'s `pick()`
  only copies the 8 fields it needs).
- No database, cookies, analytics or local storage of the data. "Songs you leave out" live in a JavaScript variable and vanish
  with the tab. (The one thing stored in the browser is a tiny preference for the globe's scroll style.)

### 5.4 Defence against bad text in the data

Song names and artist names come from the file and are inserted into HTML. `esc()` in `charts.js` converts `& < > " '` to their
safe forms, and every string is passed through it before it goes into the page. Cover URLs are accepted only if their host ends
in `.spotifycdn.com` or `.scdn.co` (`safeImage`).

### 5.5 No third-party code

No libraries and no CDN links. That removes a whole class of risk (a compromised library) and means anyone can read exactly what
runs.

---

## 6. Reading the Spotify file (`load.js`)

Browsers can unzip, but there is no built-in "open a zip file" function, so `load.js` reads the zip format itself. You do not need
to memorise this; the idea is what matters.

### 6.1 How a zip file is laid out

A zip is a list of compressed files with an **index at the end** ("the central directory"). To read it you:

1. Find the "end of central directory" marker (`0x06054b50`) by scanning backwards from the end of the file.
2. It tells you how many files there are and where the index starts.
3. Each index entry (`0x02014b50`) holds a file's name, compression method, compressed size and where its data begins.
4. At that position a "local header" (`0x04034b50`) precedes the data.

`zipEntries(buf)` does steps 1-3 and returns a list of entries. `zipEntryText(buf, e)` does step 4 and decompresses:

```js
if (e.method === 0) return new TextDecoder().decode(data);          // "stored": not compressed
...
const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
return await new Response(stream).text();                            // the browser's own unzip
```

`DecompressionStream("deflate-raw")` is a built-in browser feature, so no library is needed. Limits: it does not support zip64 (zips over 4 GB) and the whole zip is held in memory while it is read.

### 6.2 Which files, which fields

```js
const NAME_RE = /(?:^|\/)(?:Streaming_History_Audio_[^/]*|endsong_[^/]*)\.json$/i;
```

Only files named `Streaming_History_Audio_*.json` (and the older `endsong_*.json`) are used. The video files in the export are ignored.
For each record, `pick()` keeps it only if it has a track URI starting `spotify:track:` and a track name (so podcasts, audiobooks and
video are dropped), a valid time, and a length, and copies exactly:

```js
{ ts: Date.parse(r.ts), ms: r.ms_played, id: uri.slice(14), name, artist, album, skipped }
```

- `ts` is when the play **ended** (the export's timestamp), in milliseconds since 1970.
- `id` is the 22-character Spotify track id (the URI without `spotify:track:`).
- `skipped` is Spotify's own flag, which is unreliable for early years, so the analysis rarely uses it.

### 6.3 Overlapping exports

If the visitor picks two exports that overlap, the same play would appear twice. `loadFiles` drops duplicates using `ts + id`.

### 6.4 Files may be picked directly

The page also accepts the unzipped `.json` files (the file input is `multiple`), and gives a clear message if none are found:
"No streaming history files found. Look for files named Streaming_History_Audio_....json inside your Spotify zip."

---

## 7. The data model: plays, real plays, songs

### 7.1 A play becomes a "row"

`prepare(raw)` in `analysis.js` turns each play into a richer object once, so every later function is simple:

```js
{ ts, ms, id, name, artist, album, skipped,
  key,            // "title|artist" in lower case: identifies the SONG
  real,           // ms >= 30000
  hours,          // ms / 3 600 000
  y, mo,          // year, month (1-12) in the visitor's own time zone
  dn,             // "day number": whole days since 1970, for day-level maths
  h, wd }         // hour (0-23) and weekday (0 = Monday)
```

The rows are sorted by time. The function returns `{ all, real }`: every play, and only the real ones.

### 7.2 Two rules that shape every number

1. **A real play is 30 seconds or more.** Plays under 30 seconds are accidental skips and are not counted as listening
   (`REAL_MS = 30000`). Almost every statistic uses `real`.
2. **A song is "title + artist".** `songKey` joins the lower-cased title and artist. A song released twice (a single, then an
   album) has two Spotify ids but one key, so it counts once. For display, the release that was played most supplies the id,
   title and album (`songs()`).

### 7.3 Time zone

Times use the **visitor's own time zone** (the browser's `Date`). (The Python version in your pipeline uses IST.) Day boundaries
therefore follow where the visitor is.

---

## 8. The analysis (`analysis.js`)

All the maths lives here as **pure functions**: they take arrays in and return numbers or arrays out, and never touch the web
page. That is what makes them testable (section 15).

### 8.1 The functions

| Function | What it gives you |
|---|---|
| `overview` | Totals: hours, real plays, different songs and artists, active days, first and last day |
| `byYear`, `byMonth` | Plays per year / per month of one year |
| `topSongs`, `topArtists`, `topAlbums` | Rankings, optionally for one year or month |
| `monthlyRulers` | The song with the most plays in each month of a year |
| `milestones` | Which song was play number 1, 1,000, 10,000 ... |
| `streaks` | Longest run of consecutive listening days, and the longest silence |
| `busiestDays` | Days with the most plays |
| `hourWeekday`, `timeBands`, `dailyCounts` | The data behind the hour-by-weekday heatmap, the night/morning/afternoon/evening split, and the calendar |
| `discovery` | Per year: songs heard for the first time and what share of plays they were |
| `skipRates` | Per year: how many plays ended under 30 seconds |
| `comfortSongs` | Songs played in many different years (the Habits tab uses six or more) |
| `forgottenFavourites` | Songs with many plays but none for a long while |
| `obsessions` | The most plays of one song in a single day |
| `replayAverage`, `memoryLane` | How much you replay songs the same day, and which songs beat your average |
| `hiddenLikes` | "Songs you probably missed" (a behavioural guess, see 8.2) |
| `personality` | The five or six personality chips |
| `yearProfile`, `yearCard`, `newArtists` | Per-year numbers, and everything for one year's wrapped card |
| `artistOptions`, `artistProfile` | The artist deep dive: peak month, quiet spells, top songs |
| `breaks` | Silences of 14+ days |
| `tasteDrift` | How much each year's top 50 carried over, is new, or returned |

### 8.2 The few non-obvious ones, explained

**`memoryLane`.** First `replayAverage` works out, over all (song, day) pairs, how many times a song is typically played on a day
you play it at all. A song earns a place if it has at least 10 real plays, was played on at least a minimum number of different days,
and its **plays per day it was played** is above that average. In plain words: songs you tend to put on repeat.

**`hiddenLikes` ("Missed from artists you love").** A score from 0 to 100 for songs with 1 to 15 real plays, blended from four
behaviours:

| Part | Weight | Meaning |
|---|---|---|
| `cameBack` | 30% | You played it on more than one day (capped: 4 or more days scores full) |
| `finished` | 25% | The share of its plays you listened to at least 90% of the way through |
| `artist` | 30% | How much you play the *rest* of that artist (ranked against other candidates) |
| `noSkips` | 15% | The share of its starts that were not abandoned under 30 seconds |

It is a **guess from behaviour, not a record of likes**, and the page says so.

**`personality`.** Plain thresholds:

| Question | Result |
|---|---|
| 25%+ of plays between midnight and 6am? | "Night owl", otherwise "Morning / Afternoon / Evening listener" (the busiest band) |
| Replay a song the same day on 12%+ of play-days? | "Binge repeater", else "One-and-done" |
| Top 10 artists = 20%+ of plays? | "Artist loyalist", else "Wide explorer" |
| 120+ different songs per 1,000 plays? | "Collector", else "Keeper" |
| Listened on 80%+ of all days / under 50%? | "Daily habit" / "In bursts" |

**`tasteDrift`.** For each year it takes the top 50 songs (or top 20 artists). Each one is **carried** (also in last year's top
list), **new** (first heard that year), or **returning** (neither: an old favourite that came back).

---

## 9. The page (`app.js`) and the charts

### 9.1 The pattern: state, then render

`app.js` follows a simple pattern used by many small web apps:

```js
const state = { raw, data, tab: "life", year, month, card: "all", covers: true, ... };
```

- Everything the page needs to remember lives in the `state` object.
- `render()` rebuilds the header (metrics, personality chips, tab bar) and calls `renderPanel()`.
- `renderPanel()` picks the function for the open tab (`tabLife`, `tabYear`, ...), which **returns an HTML string**, and puts it into the page with `innerHTML`.
- When the visitor clicks something, an event handler changes `state` and calls `renderPanel()` again.

There is no framework: the page is simply rebuilt from the state each time.

### 9.2 Speed: `memo`

Some results are expensive on a history of 300,000 plays. `memo(name, fn, ...args)` caches a result by its name and arguments
(`memoCache`). The cache is emptied whenever the history changes (for example when a song is left out).

### 9.3 Event delegation

Instead of attaching a handler to every button, one handler on the whole document looks at `data-act` attributes:

```html
<button data-act="tab" data-k="year">Year by year</button>
```

```js
document.addEventListener("click", e => { const t = e.target.closest("[data-act]"); ... if (act === "tab") { state.tab = ...; render(); } ... })
```

This keeps working however many times the HTML is rebuilt.

### 9.4 The tabs

| Tab | What it shows |
|---|---|
| Lifetime | Top 20 songs (in a scrolling box), top artists, "artist eras" stream chart, milestones, longest streak and break, biggest days, and a list of long silences ("Breaks") |
| Year by year | Bars for each year (click one), monthly bars, "the song that ruled each month", top songs/artists |
| Compare years | Pick two years: numbers side by side, new artists, taste drift |
| When you listen | Night/morning/afternoon/evening, hour-by-weekday heatmap, a calendar of every day of a year |
| Habits | How much of what you start you really listen to (the 30-second rule), new songs each year, how much you repeat, one-day obsessions, comfort songs (played in six or more years), "Down the memory lane" |
| Forgotten favourites | Sliders for minimum plays and months of silence |
| Missed from artists you love | The `hiddenLikes` list |
| Artist deep dive | Search any artist: peak month, quiet spells, favourite songs |
| Song globe | See section 12 |
| Wrapped card | See section 11 |

Long song lists (the top 20, "Down the memory lane", forgotten favourites) sit in their own scrolling box with a header that stays
put (`.scroll.scrolly` in the CSS).

### 9.5 Lists you can take with you

Every song table has **Copy Spotify links** (one `https://open.spotify.com/track/<id>` per line, to paste into a Spotify
playlist in the desktop app) and **Download CSV** (`Song, Artist, Spotify link`). These exist because the site cannot create
playlists itself: that would need each visitor to log in to Spotify, and Spotify allows only a handful of people to use a new app.

### 9.6 Leave songs out

A collapsible panel lets the visitor remove songs that distort their stats (an alarm song, say). It stores their keys in
`state.excluded`; `build()` then re-runs `excludeSongs` before `prepare`, and everything is recalculated. They are never saved.

### 9.7 Charts (`charts.js`)

All charts are hand-made **SVG** strings, no library. `bars` (vertical bars with clickable columns), `hbars` (ranked horizontal
bars), `stacked`, `heatmap`, `calendar` (a GitHub-style year grid) and `streamChart` (the smooth, translucent "artist eras"
chart, with a hover tooltip that follows the pointer). Colours come from CSS variables so they follow the dark/light theme.

Bar-chart x-axis labels are **thinned out**: the chart labels only every 1st, 2nd, 3rd, 4th, 6th, 12th or 24th bar, whichever
is the smallest step where the labels do not overlap (each bar still shows its full label in a tooltip).

### 9.8 Smooth scrolling, and living inside an iframe

The landing page's top links glide to their section. The animation is written in JavaScript (`scrollToElement`) rather than using
the browser's built-in "smooth scrolling", because browsers skip that when the visitor's computer has animations turned off.
`scrollToElement` also knows about the Streamlit version, where the page lives inside an iframe and the *outer* page does the
scrolling (section 14).

---

## 10. Album covers

Covers make the lists much nicer but are the hardest part, because they depend on an outside service.

### 10.1 How a cover is found

For a track id, the page calls `https://open.spotify.com/oembed?url=https://open.spotify.com/track/<id>` (a public endpoint that
needs no login). The reply contains `thumbnail_url`, an image address on Spotify's image servers. The URL is only accepted if its
host ends in `.spotifycdn.com` or `.scdn.co`.

### 10.2 Why there is a whole machine for it

Spotify answers too many requests too fast with an error the browser reports as a plain "network failure". A first attempt that
fired all lookups at once got blocked. The final design (`coverQueue`, `coverWorker`) behaves politely:

| Mechanism | What it does |
|---|---|
| **A queue** | Songs wait in a line; `urgent` ones (the songs on screen right now) jump to the front, background ones (for the globe) go to the back |
| **3 workers at a fixed pace** | `COVER_WORKERS = 3` and `COVER_GAP_MS = 200`: all workers together never go faster than one request per 200 ms |
| **Shared back-off** | When a request fails or gets HTTP 429/5xx, *every* worker waits longer (2 s, doubling up to 30 s) |
| **Retries** | A failed song goes back to the front of the queue, up to 6 tries |
| **A cache** | `coverCache` remembers each answer (a URL, or an empty string meaning "Spotify has none") so a song is asked once |
| **Image preloading** | The image file is downloaded before the tile is shown, so the cover appears the instant the tile does |
| **Dropping stale work** | If the visitor leaves a tab or loads a new file, queued lookups for places they have left are discarded |

### 10.3 Where covers appear

Small thumbnails next to song names in tables, the big #1 cover on the Wrapped card, every tile on the globe, and the
pinned-song tray.

---

## 11. The Wrapped card and its PNG download

### 11.1 The card on screen

`tabCard()` builds a card for "Lifetime" or any single year (a drop-down): minutes, plays, songs, artists, the #1 song with its
cover, top 5 songs, top 5 artists, top album and biggest day. It is HTML with a diagonal green gradient
(`#0b3d2e`, `#1db954`, `#7be39a`).

### 11.2 The PNG download (`downloadCard`)

Taking a screenshot of HTML in the browser needs a library, so the card is **drawn again from scratch on a `<canvas>`**, 1080
by 1350 pixels (the shape Instagram posts and stories like):

1. `lastCard` remembers the data the on-screen card used, so the PNG shows exactly the same thing.
2. A canvas is filled with the same three-colour diagonal gradient.
3. Text is drawn line by line at fixed positions with `text(t, x, y, size, weight, alpha, maxWidth)`.
4. The `clip` helper shortens a title with "..." so it fits its width.
5. The #1 song's cover is loaded with `crossOrigin = "anonymous"` (Spotify's image server allows that), drawn with rounded corners.
6. `canvas.toBlob(...)` makes the PNG and a temporary link downloads it as `lifetime-wrapped-<label>.png`.

Why it can be trusted with the cover: if the image host refused a cross-origin copy, the canvas would be "tainted" and refuse to
export; the code simply skips the cover in that case instead of failing.

### 11.3 Two bugs worth knowing

- **A freeze on long titles.** The first `clip` removed *two* letters and then added three dots; for a very long title the text
  never got short enough and the loop ran forever. It now removes **one letter at a time** until the text plus dots fits.
- **White corners.** Rounded corners on the whole card left transparent corners that some image viewers show as white. The card
  went back to square corners.

---

## 12. The Song Globe

An experimental view: all the songs in the history wrapped on a globe that you spin. Songs you played in the same listening
sessions sit close together.

### 12.1 Step 1: a map (`embed.js`, runs in the browser)

1. **Sessions.** Plays are walked in time order; 30 minutes of silence ends a session.
2. **Songs x sessions matrix.** For every song, which sessions it appeared in. Busy sessions count for less (weight `1 / log(2 + size)`),
   and each song's row is scaled to length 1.
3. **Low-rank embedding** (`lowRank`): a truncated SVD by "subspace iteration" gives each song 24 numbers, so songs that appear in similar sessions get similar numbers.
4. **t-SNE** (`tsne`): squashes those 24 numbers to 2-D points. t-SNE is heavy (it compares every song with every other), so it is run only on the
   **1,200 most played songs** (the "skeleton"). It yields to the page every few steps so the browser does not freeze.
5. **Everyone else.** Every remaining song is placed at the weighted middle of the six skeleton songs it is closest to. A song never played
   alongside another goes next to its artist's other songs, or somewhere inside the map.
6. The map is scaled into a 0-1000 square. A seeded random generator makes the same history give the same map every time.

### 12.2 Step 2: the globe (`globe.js`)

- The grid is **endless**: a cell `(gx, gy)` holds one song, cells are filled in as you move and remembered, so a place always holds the same songs.
- Moving in direction *k* picks the **nearest unused song on the map within 75 degrees** of that direction; at the edge of the map it wraps to the far side.
- The grid is drawn as CSS 3-D tiles placed on a sphere (`rotateY`, `rotateX`, `translateZ`); the lit tile faces you, the eight around it are faded.
- The view glides with a **critically damped spring** (eases in and out, never overshoots). If the visitor prefers reduced motion, it jumps instead.
- Controls: arrow keys, Q/E/Z/C for the corners, numpad, mouse wheel or trackpad, swipe, click a faded tile. Backspace goes back, Space is a random song.
- A side panel shows the song's plays, first and last year, a plays-per-year bar chart, a link to open it on Spotify, and a mini map of where you are.

### 12.3 Covers first

A tile with no picture looks broken, so the globe only uses songs **whose cover has loaded**. Before it starts, a loading panel
fetches the top 2,000 songs' covers at the polite pace from section 10. It starts by itself when they are all in, or the visitor can
start after 150 covers, or choose plain name tiles. The counter reads "N of 2,000 most played songs".

### 12.4 "Pin this song"

A tray lets the visitor pin up to 100 songs (the most Spotify accepts in one paste), then **Copy Spotify links** or **Download
CSV**: a way to build a playlist from songs found by wandering the globe. Pins live only in the page.

---

## 13. Sample data

Spotify can take days to send the export, so **Try it with sample data** (`sample.js`) lets a visitor explore at once. It generates
about 18,500 plays across 8 invented artists from 2022 to 2026 (a late-night listener, a burst in summer 2024, taste that drifts
by year), in exactly the format Spotify's file uses, and passes them through the **normal loader**, so the sample exercises the same
code as a real file. A seeded random generator makes it identical every time. The page labels it "Sample data, made up for this demo".
Covers are switched off for it (the songs are fake), so the demo sends nothing to Spotify.

---

## 14. The Streamlit version

The same page can also run inside Streamlit (the wrapper was added early on, and it still works).

- `bundle.py` glues `index.html`, `style.css` and the `js/` modules into **one HTML string**: each module is wrapped in a function
  scope, `import` lines become lookups, the CSS and JS are inlined, and the security policy is rewritten to allow the inline script
  (`script-src 'unsafe-inline'`).
- `streamlit_app.py` shows that string with `components.html(...)` (an iframe), hides Streamlit's own header and footer, and adds the
  "Created by" badges. Streamlit only *delivers* the page; the file is still read in the visitor's browser.
- **Cache stamp.** Streamlit caches the built page; `_stamp()` fingerprints the modification times and sizes of every file that goes
  into it, so a redeploy can never serve a stale page.
- **Frame sizing.** An iframe has a fixed height, which would give the page its own scroll bar inside Streamlit's. `fitFrame()` sets
  the iframe (and Streamlit's box around it) to the content's real height, so the outer Streamlit page scrolls. This only runs when
  the page detects it is inside a same-origin frame (`hostFrame()`); on Cloudflare nothing changes.
- In-page links and the landing page's glide work on the *outer* page's scroller, which is why `scrollToElement` looks for Streamlit's
  main container.

---

## 15. Testing

The hosted site has no unit-test framework. Instead its maths is **checked against the Python version of the same analysis**
(`wrapped.py` in your pipeline project, which has its own unit tests):

1. `tests/reference.py` loads a real export with Python, runs 18 figures (totals, top songs and artists, a year profile, replay
   average, memory-lane songs, "missed" songs, taste drift, streaks, forgotten favourites, comfort songs ...) and prints them as JSON.
2. `python tests/make_nocsp.py` writes a copy of the page **without the security policy** (`tests/index_nocsp.html`, git-ignored so it
   is never published) so the test can load a local file.
3. The same export is loaded into that page, and `tests/compare.js` is pasted in the browser console. It recomputes the same figures
   in JavaScript and prints any that differ.

On a real 327,508-play export all 18 figures matched exactly. The tests directory also holds `fixtures/` (git-ignored) with the
reference numbers.

---

## 16. Challenges and how each was solved

**1. No zip library allowed.** The site promises no outside code, and browsers cannot open zips on their own. *Fix:* read the zip
format directly (`zipEntries`) and use the browser's built-in `DecompressionStream("deflate-raw")` to decompress.

**2. Keeping the privacy promise provable.** A statement is easy to make and hard to verify. *Fix:* a strict Content-Security-Policy
(`default-src 'none'`), sent both as a header and as a meta tag, so the browser itself blocks any other network request.

**3. Album covers vs. "nothing leaves".** Covers need Spotify's cover lookup, which is a network request. *Fix:* allow exactly one
address (`connect-src https://open.spotify.com`), send only track ids, say so openly on the page, and skip the lookups for sample
data. (Covers were first an opt-in switch, then became on by default; the privacy text was rewritten to match.)

**4. Spotify rate-limiting the cover lookups.** Firing thousands of requests at once made Spotify refuse them. *Fix:* the
polite queue in section 10: 3 workers, one request per 200 ms in total, shared back-off, retries, urgent-first ordering.

**5. A globe with blank tiles.** Tiles appeared before their cover loaded. *Fix:* the globe only uses songs whose cover has loaded,
and a loading panel with a progress bar runs first.

**6. t-SNE freezing the page.** Mapping thousands of songs is heavy. *Fix:* t-SNE on only the 1,200 most played songs, the rest
placed by nearest neighbours, and `await yieldNow()` every few iterations so the browser keeps responding and the progress counter updates.

**7. Stale pages on Streamlit.** After a redeploy the old page kept appearing. *Fix:* the file-fingerprint `_stamp()` in
`streamlit_app.py`.

**8. The iframe's own scroll bar and wrong height.** *Fix:* `fitFrame()` sizes the frame (and Streamlit's wrapper) to the content;
a `ResizeObserver` keeps it in step as content changes.

**9. Anchor links broke inside a frame.** A plain `#section` link inside an iframe would send the frame to the host page's address.
*Fix:* intercept `a[href^="#"]` clicks and scroll the host page's own scroller with `scrollToElement`.

**10. "Smooth" scrolling that did not animate.** When the computer has animations turned off, browsers ignore smooth scrolling.
*Fix:* drive the animation from JavaScript (an eased scroll with `requestAnimationFrame` and a timer fallback for pages that are
not being painted), stopping if the visitor scrolls, touches or presses a key.

**11. Chart labels piling up.** A 60-month chart printed 60 labels on top of each other. *Fix:* label only as many bars as fit,
at whole-quarter, half-year or year steps.

**12. The PNG download froze on long titles.** The label-shortening loop removed two letters and added three dots, so it never
finished. *Fix:* remove one letter at a time (section 11.3).

**13. White corners on the downloaded card.** Back to square corners (section 11.3).

**14. A downloaded image refusing to export.** Drawing another site's image on a canvas "taints" it. *Fix:* request the cover with
`crossOrigin = "anonymous"`; if it is refused, skip the cover.

**15. The globe moving the wrong way.** On touch screens "up" must go north, but on a mouse wheel "rolled up" does the opposite.
*Fix:* two scroll styles ("Trackpad / touch" and "Mouse wheel"), remembered in the browser; the globe turns opposite the finger, like
turning a real globe.

**16. Going wrong quietly on bad data.** Odd records (podcasts, missing names, impossible times) would skew totals. *Fix:* `pick()`
keeps only records that have a track URI, a name, a valid time and a length; duplicates from overlapping exports are dropped.

**17. Proving the maths.** A reimplementation in another language can drift. *Fix:* the Python/JS comparison harness (section 15):
18 figures, all identical on a real 327,508-play export.

**18. A short history made the sample look empty.** People without an export saw nothing. *Fix:* the sample-data button (section 13).

**19. A rewritten history.** On 25 Oct 2026 the Git history was rewritten once to remove co-author lines from commit messages; the files
did not change, but every commit id did. A collaborator's copy must be re-synced with `git fetch` then `git reset --hard origin/main`
(never `git pull`).

**The approach behind the fixes.** Keep the privacy rules fixed and let features adapt to them (not the other way round); prefer a
small, readable solution to a library; reproduce each problem with real or sample data before changing code; and write down the
reason in a comment, because the code usually shows *what*, not *why*.

---

## 17. How it was made, in order

Dates are from the Git history (42 commits, 18-25 October 2026).

| When | What was added |
|---|---|
| **18 Oct 15:57** | **First version** (Johan): "browser-only Spotify history viewer". The analysis ported from the Python `wrapped.py`, plus the zip reader, the charts and the tabs. |
| 18 Oct 16:33 | **New design and landing page**, optional album covers |
| 18 Oct 16:36 | Fix for stale pages on Streamlit |
| 18 Oct 16:43-17:11 | **Landing redesign** (Sarthak): new headline with a gradient, top bar, "Try it with sample data", section order; creator credits (Johan) |
| 18 Oct 17:19-17:25 | **Wrapped card** reshaped to match the pipeline's card; covers on by default |
| 18 Oct 17:39-17:41 | Creator badges and Streamlit frame sizing |
| 18 Oct 17:51-17:54 | Landing tabs, then smooth scroll for the Streamlit version |
| **18 Oct 18:04** | **Cloudflare Pages headers**: the privacy policy sent as a real HTTP header |
| 18 Oct 19:52-19:57 | "Artist eras" stream chart |
| 18 Oct 19:59-20:26 | Stacked landing sections with a gliding top bar; scrolling boxes for long lists; chart label fix; "Check it yourself" and "Code on GitHub" buttons removed |
| **18 Oct 20:43-21:29** | **Song Globe** (map from sessions, every song not just the top 1,200, covers first, cover counter) |
| 19 Oct 00:45-00:53 | Globe feels like a real globe (view moves opposite the finger, hard swipes spin several songs) |
| **25 Oct 00:56-01:34** | **Wrapped card PNG download** (cover, then rounded corners, then square corners) |
| 25 Oct 16:37-17:05 | Fix the long-title freeze; add top album and biggest day to the PNG |
| **25 Oct 17:15-17:31** | **Globe queue**, then renamed "Pin this song" |

### How the pieces were built

1. **The maths first.** Start from the working Python analysis in the pipeline project and port it function by function, then check each
   number against Python.
2. **A reader for the file**, with a strict list of fields to keep.
3. **Charts and tabs** on top of a simple state-and-render loop.
4. **A landing page** that explains where to get the file and what happens to it (the privacy section is as important as the features).
5. **Hosting**, first as a Streamlit app (needs a little glue), then as plain static files on Cloudflare Pages with real security headers.
6. **Extras last**, once the core was solid: covers, the sample data, the globe, the card download.

---

## 18. Recipes: how to change things

Edit the files in the repository, push to `main`, and the live site updates in about 30 seconds.

**Add a new statistic.** (1) Write a pure function in `js/analysis.js` that takes `real` (or `all`) and returns data. (2) Show it from a
`tab...` function in `js/app.js`, by adding to the HTML string it returns. (3) If it is important, add it to `tests/reference.py` and
`tests/compare.js` so it is checked against Python.

**Add a tab.** Add `["id", "Label"]` to `TABS`, write `function tabId() { return \`...html...\`; }`, and add `id: tabId` to the object in
`renderPanel`.

**Change the colours.** The palette is the `:root { --bg, --card, --accent, ... }` block at the top of `style.css` (plus a light-theme
block for people who prefer light). The card's gradient is repeated in the CSS (`.wcard`) and in `downloadCard` for the PNG.

**Change a rule** (what counts as a real play). `REAL_MS` in `analysis.js`, and the same number in the Python version, or the
two will disagree.

**Change what is allowed on the network.** Edit the policy in **both** `index.html` (the meta tag) and `_headers`. Keep them identical
apart from `frame-ancestors`. `bundle.py` has its own copy for the Streamlit version.

**Test locally.** `python -m http.server 8600`, open http://localhost:8600, click "Try it with sample data".

**Update the live site.** Push to `main`. To confirm, compare the file on the live site with your copy (or just reload with Ctrl+Shift+R).

---

## 19. Cheat sheet and troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| "No streaming history files found" | Picked the wrong download (Account data, not Extended streaming history) | Request **Extended streaming history** from Spotify's privacy page |
| Page opens but nothing happens on file pick (local) | Opened `index.html` from the file system | Run `python -m http.server 8600` and open `http://localhost:8600` |
| New change not visible on the live site | Cache, or Cloudflare still publishing | Wait a minute; hard-refresh (Ctrl+Shift+R) |
| Covers missing or arriving slowly | Spotify is rate-limiting the lookups | They retry on their own; a long history takes a few minutes |
| Globe asks to "Use name tiles instead" | Few covers could be fetched | Choose name tiles, or try again later |
| "The globe needs a longer history" | Fewer than 60 different songs in sessions | Load the full export, not one small file |
| Smooth scroll looks instant | The computer's animation setting is off | Built-in JavaScript animation handles this for the landing links |
| Collaborator's Git is confused after a history rewrite | Commit ids changed | `git fetch origin` then `git reset --hard origin/main` (back up local work first) |

**Useful addresses:** live site https://lifetime-wrapped.pages.dev/ | code https://github.com/johanchopra28/Lifetime-Wrapped

---

## 20. Glossary

| Term | Meaning |
|---|---|
| **Static site** | A website made only of files; no program runs on the server |
| **Cloudflare Pages** | Hosting that publishes a GitHub repo as a static site |
| **ES module** | A JavaScript file that `import`s other files; needs a web server, not `file://` |
| **CSP (Content-Security-Policy)** | Browser rules about what a page may load and where it may send data |
| **Header** | Extra information a server sends with a file (here, the security rules) |
| **DOM / `innerHTML`** | The page's structure in memory / replacing a part of it with HTML text |
| **SVG** | Pictures described as text (shapes, lines), used here for all charts |
| **Canvas** | A drawing surface in the browser; used to make the PNG card |
| **Event delegation** | One click handler on the whole page that looks at `data-act` to decide what was clicked |
| **oEmbed** | A public Spotify address that returns a track's cover without a login |
| **Rate limit / HTTP 429** | The service saying "too many requests, slow down" |
| **Back-off** | Waiting longer after each failure before trying again |
| **Real play** | A play of 30 seconds or more |
| **Song key** | Lower-case "title\|artist", so a song released twice counts once |
| **Session** | A stretch of listening with no gap over 30 minutes |
| **SVD / t-SNE** | Techniques that squash many numbers per song down to a 2-D map |
| **Idempotent / deterministic** | Same input always gives the same output (the sample and the map are seeded for this) |
