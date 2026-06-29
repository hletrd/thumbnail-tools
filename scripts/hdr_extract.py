#!/usr/bin/env python3
"""HDR-aware ±1s-sharpest frame sourcing.

Most fancams are Rec.2020 HDR; YouTube's SDR avc1 (itag 137) is already
highlight-clipped. So download the 1080p HDR stream (itag 335, vp9.2) when
available and decode at FPS through an HDR->SDR tonemap (hable, highlight
roll-off so nothing blows out), keeping the sharpest frame per 1-second bucket
-> thumbnails/<key>/. SDR-only uploads fall back to 137 + a plain scale.

Usage:
    FFMPEG=/path/to/ffmpeg-with-zscale python scripts/hdr_extract.py [manifest.tsv]
Env:
    FFMPEG   ffmpeg WITH zscale+tonemap (stock macOS Homebrew lacks zimg; use an
             evermeet/BtbN/static build). Required for the HDR path.
    FFPROBE  metadata probe (default "ffprobe"); YT_DLP (default "yt-dlp").
    PAR (default 2), FPS (default 6).
Needs PIL+numpy. Resumable via downloads_hdr/<key>.done; cookies.txt at repo
root, if present, is passed to yt-dlp to clear a bot-check.
"""
import subprocess, shutil, time, os, sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sources.tsv"
YTDLP = os.environ.get("YT_DLP", "yt-dlp")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")     # MUST have zscale+tonemap
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
DL = ROOT / "downloads_hdr"; DL.mkdir(exist_ok=True)
THUMB = ROOT / "thumbnails"
TMP = ROOT / ".hdr_tmp"; TMP.mkdir(exist_ok=True)
COOKIES = ROOT / "cookies.txt"

FPS = int(os.environ.get("FPS", "6"))
PAR = int(os.environ.get("PAR", "2"))
RY0, RY1, RX0, RX1 = 0.04, 0.70, 0.10, 0.90
VEXT = (".webm", ".mp4", ".mkv")
# HDR (HLG/PQ Rec.2020) -> SDR bt709, hable highlight roll-off (no clipping)
TONEMAP = ("fps={f},zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"
           "scale=1920:-2:flags=lanczos")
PLAIN = "fps={f},scale=1920:-2:flags=lanczos"


def sharp(path):
    g = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    H, W = g.shape
    r = g[int(H * RY0):int(H * RY1), int(W * RX0):int(W * RX1)]
    gx = np.diff(r, axis=1); gy = np.diff(r, axis=0)
    return float((gx * gx).mean() + (gy * gy).mean())


def _found(key):
    fs = [p for p in DL.glob(f"{key}.*")
          if p.suffix in VEXT and p.stat().st_size > 2_000_000]
    return fs[0] if fs and not list(DL.glob(f"{key}.*.part")) else None


def download(key, vid):
    f = _found(key)
    if f:
        return f
    for _ in range(4):
        for p in DL.glob(f"{key}.*"):
            if p.suffix == ".done":
                continue
            if p.suffix not in VEXT or p.stat().st_size < 2_000_000:
                try: p.unlink()
                except OSError: pass
        cmd = [YTDLP, "--no-warnings", "--no-progress", "-N", "2",
               "--retries", "30", "--fragment-retries", "30", "--retry-sleep", "6",
               "--extractor-args", "youtube:player_client=android_vr",
               "-f", "335/137/bv*[height<=1080][ext=mp4][vcodec^=avc1]/b[height<=1080]",
               "-o", str(DL / f"{key}.%(ext)s")]
        if COOKIES.exists():
            cmd += ["--cookies", str(COOKIES)]
        cmd.append(f"https://www.youtube.com/watch?v={vid}")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        f = _found(key)
        if f:
            return f
        time.sleep(10)
    return None


def is_hdr(path):
    # ffprobe color fields can carry a trailing comma -> substring match, not ==
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=color_transfer", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout
    return ("arib-std-b67" in out) or ("smpte2084" in out)


def process(item):
    key, vid = item
    done = DL / f"{key}.done"
    d = THUMB / key
    if done.exists() and d.exists() and any(d.glob("*.jpg")):
        return f"SKIP {key}"
    src = download(key, vid)
    if not src:
        return f"FAIL-DL {key}"
    hdr = is_hdr(src)
    vf = (TONEMAP if hdr else PLAIN).format(f=FPS)
    tmp = TMP / key; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(src),
                    "-vf", vf, "-q:v", "3", str(tmp / "f_%05d.jpg")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = sorted(tmp.glob("f_*.jpg"))
    if not frames:
        shutil.rmtree(tmp, ignore_errors=True)
        return f"FAIL-EXTRACT {key}"
    buckets = {}
    for idx, f in enumerate(frames):
        sec = idx // FPS
        s = sharp(f)
        if sec not in buckets or s > buckets[sec][0]:
            buckets[sec] = (s, f)
    shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    for i, sec in enumerate(sorted(buckets)):
        shutil.copy2(buckets[sec][1], d / f"{key}_{i:03d}.jpg")
    n = len(buckets)
    shutil.rmtree(tmp, ignore_errors=True)
    done.write_text(("hdr" if hdr else "sdr") + f" {n}")
    return f"DONE {key} {'HDR' if hdr else 'SDR'} secs={n}"


def main():
    import concurrent.futures as cf
    if not MAN.exists():
        sys.exit(f"manifest not found: {MAN} ('<key>\\t<youtube_id>' per line)")
    items = [tuple(l.rstrip("\n").split("\t")) for l in open(MAN) if l.strip()]
    print(f"videos: {len(items)} | FPS={FPS} PAR={PAR}", flush=True)
    ok = fail = skip = hdr = 0
    with cf.ThreadPoolExecutor(max_workers=PAR) as ex:
        for r in ex.map(process, items):
            print(r, flush=True)
            if r.startswith("DONE"):
                ok += 1; hdr += (" HDR " in r)
            elif r.startswith("SKIP"):
                skip += 1
            else:
                fail += 1
    print(f"ALL DONE ok={ok} (hdr={hdr}) skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
