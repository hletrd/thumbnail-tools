#!/usr/bin/env python3
"""Compute a face-centered 16:9 crop box per culled thumbnail -> crops.json.
Medium zoom: face height ~25% of crop, max 1.6x zoom, face placed in upper third.
No face -> cover-fit 16:9 (landscape: full; tall: top-biased)."""
import json
from pathlib import Path
import cv2
import concurrent.futures as cf

ROOT = Path(__file__).resolve().parents[1]
CULL = ROOT / "thumbnails_culled"
OUT = ROOT / "crops.json"
cv2.setNumThreads(1)
FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

TAR = 16 / 9
TARGET_FACE_FRAC = 0.20   # face height / crop height (gentler)
MAX_ZOOM = 1.3            # cap zoom mild so few frames look over-cropped
FACE_VPOS = 0.32          # face center at ~32% from crop top
TOP_BIAS = 0.18           # tall no-face crop keeps top

def baseline(W, H):
    if W / H >= TAR:
        bh = H; bw = H * TAR
    else:
        bw = W; bh = W / TAR
    return bw, bh

def cover_box(W, H):
    bw, bh = baseline(W, H)
    if W / H >= TAR:
        return [((W - bw) / 2) / W, 0.0, bw / W, bh / H]
    return [0.0, ((H - bh) * TOP_BIAS) / H, bw / W, bh / H]

def face_box(W, H, fx, fy, fw, fh):
    bw, bh = baseline(W, H)
    crop_h = fh / TARGET_FACE_FRAC
    crop_h = max(bh / MAX_ZOOM, min(crop_h, bh))   # clamp zoom 1..MAX
    crop_w = crop_h * TAR
    if crop_w > bw:
        crop_w = bw; crop_h = bw / TAR
    fcx = fx + fw / 2.0; fcy = fy + fh / 2.0
    left = fcx - crop_w / 2.0
    top = fcy - FACE_VPOS * crop_h
    left = max(0.0, min(left, W - crop_w))
    top = max(0.0, min(top, H - crop_h))
    return [left / W, top / H, crop_w / W, crop_h / H]

def compute(p):
    img = cv2.imread(str(p))
    if img is None:
        return p.name, None
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    region = gray[0:int(H * 0.72), :]   # exclude bottom crowd
    faces = FACE.detectMultiScale(region, 1.1, 5, minSize=(int(H*0.03), int(H*0.03)))
    if len(faces):
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        box = face_box(W, H, fx, fy, fw, fh)
    else:
        box = cover_box(W, H)
    return p.name, [round(v, 5) for v in box]

def main():
    files = sorted(CULL.glob("*.jpg"))
    crops = {}
    with cf.ProcessPoolExecutor(max_workers=8) as ex:
        for name, box in ex.map(compute, files):
            if box: crops[name] = box
    json.dump(crops, open(OUT, "w"))
    nface = sum(1 for f in files if f.name in crops)
    print(f"crops: {len(crops)} boxes for {len(files)} frames")

if __name__ == "__main__":
    main()
