#!/usr/bin/env python3
"""Source candidate frames with ±1s SHARPEST sampling.

For each "<key>\\t<youtube_id>" line of the manifest: download the video (kept in
downloads/, never deleted), decode at FPS, and keep only the sharpest frame in
each 1-second bucket -> thumbnails/<key>/. This beats fixed 1 fps sampling on
fast-motion stages, where a given second may be all motion-blur except one
crisp instant.

Usage:
    python scripts/dense_extract.py [manifest.tsv]
Env:
    PAR  concurrent videos (default 3; drop to 1 after a YouTube bot-check)
    FPS  samples per second to rank (default 6)
Needs: yt-dlp on PATH (+ bgutil POT provider for >360p), ffmpeg, opencv, numpy.
Resumable: writes downloads/<key>.done; re-running skips finished videos.
A cookies.txt at the repo root, if present, is passed to yt-dlp (bot-check bypass).
"""
import subprocess, shutil, time, os, sys
from pathlib import Path
import cv2, numpy as np
import concurrent.futures as cf

ROOT = Path(__file__).resolve().parents[1]
MAN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sources.tsv"
YTDLP = os.environ.get("YT_DLP", "yt-dlp")
DL = ROOT / "downloads"; DL.mkdir(exist_ok=True)
THUMB = ROOT / "thumbnails"
TMP = ROOT / ".dense_tmp"; TMP.mkdir(exist_ok=True)
COOKIES = ROOT / "cookies.txt"

FPS = int(os.environ.get("FPS", "6"))
PAR = int(os.environ.get("PAR", "3"))
RY0, RY1, RX0, RX1 = 0.04, 0.70, 0.10, 0.90   # stage region for sharpness
cv2.setNumThreads(1)


def sharp(path):
    img = cv2.imread(str(path))
    if img is None:
        return -1.0
    g = cv2.cvtColor(cv2.resize(img, (960, 540)), cv2.COLOR_BGR2GRAY).astype(np.float64)
    H, W = g.shape
    r = g[int(H * RY0):int(H * RY1), int(W * RX0):int(W * RX1)]
    gx = np.diff(r, axis=1); gy = np.diff(r, axis=0)
    return float((gx * gx).mean() + (gy * gy).mean())


def download(key, vid):
    out = DL / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 2_000_000 and not Path(str(out) + ".part").exists():
        return out
    for _ in range(4):
        for p in DL.glob(f"{key}.*"):                  # clear partials
            if p.suffix == ".done":
                continue
            if p.suffix != ".mp4" or p.stat().st_size < 2_000_000:
                try: p.unlink()
                except OSError: pass
        cmd = [
            YTDLP, "--no-warnings", "--no-progress", "-N", "2",
            "--retries", "30", "--fragment-retries", "30", "--retry-sleep", "6",
            "--extractor-args", "youtube:player_client=android_vr",
            "-f", "137/bv*[height<=1080][ext=mp4][vcodec^=avc1]/b[height<=1080]",
            "--merge-output-format", "mp4", "-o", str(out),
        ]
        if COOKIES.exists():
            cmd += ["--cookies", str(COOKIES)]
        cmd.append(f"https://www.youtube.com/watch?v={vid}")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if out.exists() and out.stat().st_size > 2_000_000 and not Path(str(out) + ".part").exists():
            return out
        time.sleep(10)
    return None


def process(item):
    key, vid = item
    done = DL / f"{key}.done"
    d = THUMB / key
    if done.exists() and d.exists() and any(d.glob("*.jpg")) and (DL / f"{key}.mp4").exists():
        return f"SKIP {key}"
    mp4 = download(key, vid)
    if not mp4:
        return f"FAIL-DL {key}"
    tmp = TMP / key; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
        "-vf", f"fps={FPS},scale=1920:-2:flags=lanczos", "-q:v", "3",
        str(tmp / "f_%05d.jpg"),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = sorted(tmp.glob("f_*.jpg"))
    if not frames:
        shutil.rmtree(tmp, ignore_errors=True)
        return f"FAIL-EXTRACT {key}"
    buckets = {}                                        # second -> (sharpness, path)
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
    done.write_text(str(n))
    return f"DONE {key} secs={n} (from {len(frames)} @ {FPS}fps)"


def main():
    if not MAN.exists():
        sys.exit(f"manifest not found: {MAN} (tab-separated '<key>\\t<youtube_id>' per line)")
    items = [tuple(l.rstrip("\n").split("\t")) for l in open(MAN) if l.strip()]
    print(f"videos: {len(items)} | FPS={FPS} PAR={PAR}", flush=True)
    ok = fail = skip = 0
    with cf.ThreadPoolExecutor(max_workers=PAR) as ex:
        for r in ex.map(process, items):
            print(r, flush=True)
            if r.startswith("DONE"): ok += 1
            elif r.startswith("SKIP"): skip += 1
            else: fail += 1
    print(f"ALL DONE ok={ok} skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
