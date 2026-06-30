#!/usr/bin/env python3
"""Source ±1s-sharpest tonemapped frames from local HDR masters (e.g. NAS exports)
instead of YouTube — higher quality (4K HDR HLG/PQ) and available before YouTube
finishes its HDR transcode.

Reads a mapping TSV (`<master-filename><TAB><key>`), and for each master decodes
at FPS through an HDR->SDR hable tonemap (when the source is HDR) or a plain
scale (SDR), keeping the sharpest frame per 1-second bucket -> <out>/<key>/.

Usage:
    FFMPEG=/path/to/ffmpeg-with-zscale python scripts/master_extract.py \
        <masters_dir> <mapping.tsv> [out_dir=thumbnails]
Designed to run wherever the masters live (e.g. on the NAS, where a static
johnvansickle ffmpeg has zscale); pull the resulting <key>/ dirs into thumbnails/.
Needs numpy + Pillow.
"""
import subprocess, os, glob, shutil, sys
import numpy as np
from PIL import Image

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")     # MUST have zscale+tonemap
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
FPS = int(os.environ.get("FPS", "6"))
RY0, RY1, RX0, RX1 = 0.04, 0.70, 0.10, 0.90
TONEMAP = ("fps={f},zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"
           "scale=1920:-2:flags=lanczos")
PLAIN = "fps={f},scale=1920:-2:flags=lanczos"


def sharp(p):
    g = np.asarray(Image.open(p).convert("L"), dtype=np.float64)
    H, W = g.shape
    r = g[int(H * RY0):int(H * RY1), int(W * RX0):int(W * RX1)]
    gx = np.diff(r, axis=1); gy = np.diff(r, axis=0)
    return float((gx * gx).mean() + (gy * gy).mean())


def is_hdr(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=color_transfer", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout
    return ("arib-std-b67" in out) or ("smpte2084" in out)


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: master_extract.py <masters_dir> <mapping.tsv> [out_dir]")
    masters, mapping = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else "thumbnails"
    tmp = os.path.join(out, ".master_tmp")
    pairs = [l.rstrip("\n").split("\t") for l in open(mapping) if l.strip()]
    for mov, key in pairs:
        src = os.path.join(masters, mov)
        if not os.path.exists(src):
            print("MISSING", mov, flush=True); continue
        vf = (TONEMAP if is_hdr(src) else PLAIN).format(f=FPS)
        t = os.path.join(tmp, key); shutil.rmtree(t, ignore_errors=True); os.makedirs(t)
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", src,
                        "-vf", vf, "-q:v", "3", os.path.join(t, "f_%05d.jpg")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        frames = sorted(glob.glob(os.path.join(t, "f_*.jpg")))
        if not frames:
            print("FAIL", key, flush=True); shutil.rmtree(t, ignore_errors=True); continue
        buckets = {}
        for idx, f in enumerate(frames):
            sec = idx // FPS; s = sharp(f)
            if sec not in buckets or s > buckets[sec][0]:
                buckets[sec] = (s, f)
        d = os.path.join(out, key); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        for i, sec in enumerate(sorted(buckets)):
            shutil.copy2(buckets[sec][1], os.path.join(d, f"{key}_{i:03d}.jpg"))
        shutil.rmtree(t, ignore_errors=True)
        print(f"DONE {key} secs={len(buckets)}", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
