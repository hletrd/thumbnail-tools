# Data pipeline & knowledge base

How the candidate thumbnails were produced for the 192-video batch, the
decisions behind it, and the gotchas worth remembering.

---

## 1. Sourcing candidate frames

Two viable sources; **YouTube is the source of truth for matching** because each
video *is* its own upload (zero ambiguity), while NAS masters are higher quality
but must be matched by filename.

### YouTube (chosen for the batch)
Every video is a public upload, so `yt-dlp` by video id is a guaranteed-correct
match. Modern YouTube needs help:

- **SABR / "DRM protected" / empty formats** on the `web`/`tv` clients →
  use **`--extractor-args "youtube:player_client=android_vr"`**, which still
  exposes direct DASH URLs up to 2160p.
- **PO token** is required for >360p. Run the **bgutil POT provider**
  (`docker run -d -p 4416:4416 brainicism/bgutil-ytdlp-pot-provider`) + the
  `bgutil-ytdlp-pot-provider` yt-dlp plugin. No cookies needed for public videos.
- Format: most uploads are **Rec.2020 HDR** (HLG/PQ); YouTube's SDR avc1
  (`137`) is already highlight-clipped. Prefer the **1080p HDR stream (`335`,
  vp9.2)** and tone-map it, falling back to `137` only for SDR-only uploads:
  `-f "335/137/bv*[height<=1080][vcodec^=avc1]/b[height<=1080]"`.
- **HDR→SDR tone-map** needs an ffmpeg WITH `zscale`+`tonemap` (stock macOS
  Homebrew lacks zimg — use an evermeet/BtbN static build). Hable rolls
  highlights off instead of clipping them:
  `zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p`
- **Bot check** ("Sign in to confirm you're not a bot") triggers after ~100+
  downloads from one IP. Mitigation: keep parallelism low (`PAR=1–2`), retry,
  or let it cool down. Valid login cookies (`--cookies cookies.txt`) also clear
  it, but stale cookies do **not** help.
- Extraction (`scripts/hdr_extract.py`): download the chosen stream (kept in
  `downloads_hdr/`, never deleted), decode at **6 fps** through the tone-map
  (HDR) or a plain scale (SDR), and keep only the **sharpest frame per
  1-second bucket** → `thumbnails/<key>/<key>_%03d.jpg`. ±1s-sharpest beats
  fixed 1 fps: a whole second can be motion-blur except one crisp instant.
  HDR is detected from `color_transfer` (substring match — ffprobe appends a
  trailing comma). Resumable (`downloads_hdr/<key>.done`); `PAR=1` after a
  bot-check; `cookies.txt` at the repo root is auto-used to bypass one.
  (`scripts/dense_extract.py` is the earlier SDR-only predecessor.)

### NAS masters (alternative, `ffmpeg`)
- Masters live under `…/photos/<date-event>/exported*/` named by song or artist.
- The Mac↔NAS link measured **~28 MB/s even on 10GbE**, and `.mov` moov atoms
  sit at the end, so streaming whole files is impractical. Solution: a static
  `ffmpeg` in `~/bin` on the NAS, extract there (8 GB/s local reads), pull only
  the small JPEGs.
- Per-frame **input-seek** (`-ss <ts> -i master`) is far cheaper than a full
  single-pass decode when sampling ~192 of thousands of frames.
- **HDR**: most masters are **HLG (`arib-std-b67`, bt2020)**. Tone-map with
  zscale (the stock macOS Homebrew ffmpeg lacks zscale/libplacebo — use a
  johnvansickle/BtbN static build):
  `zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,scale=1920:-2`
- ffprobe color fields can carry a trailing comma — strip with `tr -d ' ,\r'`
  and match by substring (`*2084*|*arib*|*b67*`, primaries `*2020*`).

> Matching NAS masters to uploads is genuinely ambiguous for multi-camera /
> medley / cover / numbered-file events (tws-con, weverse, MOACON medleys). The
> match *score* does **not** reliably separate right from wrong (correct matches
> often score ~0). That's why the batch was re-sourced entirely from YouTube.

This yields ~1 locally-sharpest frame/sec — a dense, blur-averse pool for the
culler. (An earlier version sampled fixed evenly-spaced timestamps; the cull
then had to discard the many that landed mid-motion.)

---

## 2. Auto-cull → 15 best per video (`scripts/cull_model.py`)

Per frame, measured on the **stage region only** (top ~70%, excludes the
audience/crowd band at the bottom), at 960px:

- **Sharpness** — Tenengrad (Sobel gradient energy). Primary signal; blur comes
  from subject motion, *not* frame type, so keyframe-only extraction does **not**
  help — dense sampling + sharpness culling does.
- **Face** — OpenCV Haar (`haarcascade_frontalface_default`), restricted to the
  stage region so audience faces don't count. A secondary bonus.
- **Exposure** — down-weight very dark / blown / heavily-clipped frames.

```
score = (0.72 * sharpness_norm + 0.38 * face) * exposure
```

Pick `K=15` in **score (sharpness) order**, skipping near-identical frames
(dHash hamming < 8) so the candidates are the sharpest *distinct* ones.
(An earlier diversity-first greedy let blurry-but-different frames in.)
**Use `ProcessPoolExecutor`** — the Haar cascade is **not thread-safe**
(`ThreadPoolExecutor` crashes with a `getScaleData` assertion).

> Earlier the weighting favoured faces (close-up) over sharpness, which surfaced
> blurry frames. Close-up is now handled manually in the UI (wheel zoom), so the
> cull is sharpness-first.

## 3. Auto-correct (`scripts/autocorrect.py`)

Just a gentle unsharp mask now. The HDR→SDR tone-map (+ the per-video
brightness slider) handles exposure, so the old white-point lift is **disabled**
(`GAIN_CAP=1.0`) — lifting whites would re-clip the highlights the tone-map
worked to preserve.

## 4. Previews (canvas-matched, in `web.py`)

The grid uses **AVIF @512px**, generated by `process_preview()` so the preview
matches the right-side canvas render: 16:9 cover-crop + the same
`contrast(1.04) saturate(1.08)` + unsharp. Served with `Cache-Control: no-cache`
(ETag revalidation) so regenerated previews show immediately — `immutable`
caching made edits appear "unchanged".

> AVIF here is correct/consistent — a frame that looks magenta is the actual
> LED-stage content, not a decode bug (verified: AVIF decodes identically to the
> source JPEG).

---

## Re-running the cull stage

```bash
python3 -m venv mlvenv          # Python ≤ 3.13 for opencv wheels
mlvenv/bin/pip install opencv-python-headless numpy pillow
mlvenv/bin/python scripts/cull_model.py    # thumbnails/ → thumbnails_culled/ (15 each)
mlvenv/bin/python scripts/autocorrect.py   # gentle sharpen (white-lift disabled)
# then regenerate previews (web.process_preview) and restart the server
```

## Adding newly-published uploads

When the channel gains new fancams, drop the refreshed export into `inputs/` and:

```bash
python scripts/prep_new.py                 # new 직캠 ids → sources.tsv + reference
FFMPEG=/path/to/ffmpeg-with-zscale python scripts/hdr_extract.py   # only new ids download
# re-cull (above), then set data.json title/desc for the new keys from .new_meta.json
```

`prep_new.py` is idempotent; `hdr_extract.py` skips anything already in
`downloads_hdr/`. Recent uploads may only have SDR until YouTube finishes their
HDR/4K transcode — re-run later to pick up the HDR rendition.

### Higher-quality source: local HDR masters

When the original exports exist (e.g. on the NAS), use them instead of YouTube —
they're 4K HDR (HLG) and available immediately, beating YouTube's 1080p (and any
not-yet-transcoded SDR fallback). `scripts/master_extract.py <masters_dir>
<mapping.tsv>` runs the same tonemap + ±1s-sharpest over local masters; run it
where the masters live (the NAS static johnvansickle ffmpeg has zscale) and pull
the resulting `<key>/` dirs into `thumbnails/`, then re-cull. `.mov` masters keep
the moov atom at the end, so probe/extract on the NAS rather than from a partial
pull.

## Gotchas (quick reference)
- `cv2.CascadeClassifier` is not thread-safe → use processes.
- OpenCV / mediapipe have **no Python 3.14 wheels** → use a 3.12/3.13 venv (`uv`).
- `numpy` 2.x removed `ndarray.ptp()` → use `np.ptp(arr)`.
- `uv venv` has no `pip` → `uv pip install --python <venv>/bin/python …`.
- yt-dlp rewrites the `--cookies` file in place (merges session cookies).
- Vertical sources distort if stretched to 16:9 → cover-fit / center-crop;
  all-YouTube (137) avoids this since every frame is 16:9.
