# YT Thumbnail Generator

Tooling to generate YouTube thumbnails for a large batch of (fancam) videos:
extract candidate frames → auto-cull the best ones with a model → pick & frame
each one in a fast dark web UI → overlay title/description → download / save.

Built for ~200 K-pop fancam uploads, but works for any video set.

---

## Pipeline at a glance

```
source videos ──► candidate frames ──► auto-cull (model) ──► web UI ──► rendered thumbnail
 (NAS / YouTube)   thumbnails/<key>/    thumbnails_culled/    pick+crop+text   thumbnail_rendered/
                   192 frames / video   9 best / video        per video         (+ direct download)
```

1. **Candidate frames** — N evenly-spaced frames per video into `thumbnails/<key>/`
   (HDR→SDR tone-mapped where needed, scaled to 1920px). See
   [`docs/PIPELINE.md`](docs/PIPELINE.md) for how the frames were sourced
   (YouTube via `yt-dlp`, or local masters via `ffmpeg`).
2. **Auto-cull** — `scripts/cull_model.py` scores every frame by **sharpness**
   (stage-region Tenengrad, blur-averse) + a **face** bonus (OpenCV Haar,
   stage area only) and writes the best **9 per video** to `thumbnails_culled/`,
   then `scripts/autocorrect.py` lifts dull (HLG-tonemapped) whites toward 100%
   and gently sharpens.
3. **Web UI** (`web.py`) — one section per video showing the 9 candidates;
   click to select, frame it (mouse-wheel zoom + drag), edit title/description
   (auto-saved), then **Save** (renders to `thumbnail_rendered/`) or **Download**.
4. **Persistence** — selection, title/description and crop are stored in a
   **SQLite** database (`state.db`) so nothing is lost across restarts.

---

## Web UI

Run it with the bundled venv recipe:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # Flask, Pillow, waitress
# production-ish server (recommended, multi-threaded):
waitress-serve --listen=0.0.0.0:8080 --threads=16 web:app
# or the dev server:
python web.py                            # serves on 0.0.0.0:8080
```

Open `http://<host>:8080/`.

**Features**
- **Per-video workflow** — 9 candidate thumbnails per video; pick one, the rest
  stay as alternatives.
- **Manual framing** — mouse **wheel = zoom** (cursor-anchored, gentle steps),
  **drag = pan**. Default zoom 1× (no crop, nothing cut). Per-video, persisted.
- **Text overlay** — title (song) and description (artist) prefilled, fully
  editable, **auto-saved** as you type. Rendered on a canvas using `config.json`
  (Pretendard font, stroke, bottom gradient + drop shadow for legibility).
- **Save / Download** — Save writes a JPEG to `thumbnail_rendered/`; Download
  grabs it straight to the browser.
- **Fast & dark** — sticky dark header, title filter, AVIF previews (512px,
  lazy-loaded) so a 1700+ image grid stays snappy.
- Default ordering follows the input video JSON (newest upload first).

### Endpoints
| Route | Purpose |
|---|---|
| `GET /` | the gallery (videos + candidates + config + crop state) |
| `GET /preview?file=` | cached AVIF preview for the grid (revalidated) |
| `GET /image?file=` | full-res culled frame (canvas source) |
| `POST /select` | record the chosen candidate (→ DB) |
| `POST /savetext` | auto-save title/description (→ DB) |
| `POST /cropset` | save manual zoom/pan (→ DB) |
| `POST /save` | render the canvas → `thumbnail_rendered/` + persist state |

---

## Persistence (SQLite)

`state.db`, single table — authoritative for user edits; `data.json` only holds
the **defaults** (title = song, description = artist) and is never required.

```sql
video_state(
  key TEXT PRIMARY KEY,   -- "<date6>_<song>_<videoId>"
  selected TEXT,          -- chosen candidate filename
  title TEXT, desc TEXT,  -- overlay text (NULL → fall back to data.json default)
  zoom REAL, px REAL, py REAL,   -- manual crop (1.0 / 0.5 / 0.35 = no crop)
  updated_at TEXT
)
```

Legacy `selections.json` / `cropsettings.json` are auto-migrated on first run.

---

## Layout

```
web.py                     Flask app (gallery, preview/image, save, DB)
config.json                render config (fonts, sizes, stroke, 1920x1080, 2MB cap)
templates/index.html       dark per-video UI + canvas render + wheel/drag crop
scripts/cull_model.py      auto-cull: sharpness + face → 9 best per video
scripts/autocorrect.py     white-point lift + gentle sharpen on culled frames
scripts/facecrop.py        (optional) auto face-centered crop boxes → crops.json
extract.py                 original local-video keyframe extractor (ffmpeg)
docs/PIPELINE.md           full data pipeline / how candidates were produced
thumbnails/<key>/          candidate frames (gitignored)
thumbnails_culled/         the culled 9/video shown in the UI (gitignored)
thumbnail_rendered/        final saved thumbnails (gitignored)
.previews/                 cached AVIF grid previews (gitignored)
state.db, data.json        runtime state / defaults (gitignored)
```

The culling/preview scripts need `numpy`, `Pillow`, and `opencv-python-headless`
(run them in a separate venv; OpenCV needs Python ≤ 3.13). See `docs/PIPELINE.md`.
