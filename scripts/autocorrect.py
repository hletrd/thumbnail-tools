#!/usr/bin/env python3
"""Auto-correct culled thumbnails: gentle sharpen only. Exposure is handled by
the HDR->SDR tonemap at extraction (+ the per-video brightness slider), so the
old white-point lift is disabled (GAIN_CAP=1.0) to avoid re-clipping highlights."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
import concurrent.futures as cf

CULL = Path(__file__).resolve().parents[1] / "thumbnails_culled"
GAIN_CAP = 1.0          # white-lift disabled (HDR tonemap handles exposure)
WHITE_TARGET = 250.0

def correct(p):
    im = Image.open(p).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    p_hi = float(np.percentile(lum, 99.5))
    gain = WHITE_TARGET / max(p_hi, 1.0)
    gain = min(max(gain, 1.0), GAIN_CAP)        # only brighten, capped; bright frames -> ~1.0 (noop)
    if gain > 1.005:
        a = np.clip(a * gain, 0, 255)
        im = Image.fromarray(a.astype(np.uint8), "RGB")
    # gentle sharpen ("조금 선명") - mild so already-sharp frames aren't harmed
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=3))
    im.save(p, "JPEG", quality=92)
    return gain

def main():
    files = sorted(CULL.glob("*.jpg"))
    gains = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for g in ex.map(correct, files):
            gains.append(g)
    n_lifted = sum(1 for g in gains if g > 1.005)
    print(f"corrected {len(files)} | white-lifted {n_lifted} | avg gain {sum(gains)/len(gains):.3f}")

if __name__ == "__main__":
    main()
