#!/usr/bin/env python3
"""Model-assisted cull: pick K best frames per video into thumbnails_culled/.
Score = sharpness (stage-region Tenengrad) + face presence (Haar, stage region only,
weighted by size & centeredness) - exposure penalty; then take K sharpest distinct (dHash).
Run with the ML venv python (has cv2). Faces make fancam thumbnails far better."""
import shutil
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "thumbnails"
DST = ROOT / "thumbnails_culled"
K = 15            # candidates shown per video
DST.mkdir(parents=True, exist_ok=True)
cv2.setNumThreads(1)
FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# stage region (exclude bottom crowd + extreme edges)
RY0, RY1, RX0, RX1 = 0.04, 0.70, 0.10, 0.90

def analyze(p):
    bgr = cv2.imread(str(p))
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    W = 960
    img = cv2.resize(bgr, (W, max(1, round(W * h / w))))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, Wd = gray.shape
    y0, y1, x0, x1 = int(H*RY0), int(H*RY1), int(Wd*RX0), int(Wd*RX1)
    region = gray[y0:y1, x0:x1].astype(np.float64)
    gx = np.diff(region, axis=1); gy = np.diff(region, axis=0)
    sharp = float((gx*gx).mean() + (gy*gy).mean())
    mean = float(region.mean())
    clip = float(((region < 6) | (region > 250)).mean())
    # faces in stage region -> favour CLOSE-UPS (biggest single face area drives the score)
    rg = gray[y0:y1, x0:x1]
    faces = FACE.detectMultiScale(rg, scaleFactor=1.1, minNeighbors=5, minSize=(18, 18))
    rh, rw = rg.shape
    max_area = 0.0; best_center = 0.0
    for (fx, fy, fw, fh) in faces:
        area = (fw * fh) / float(rw * rh)
        if area > max_area:
            max_area = area
            cx = (fx + fw/2)/rw; cy = (fy + fh/2)/rh
            best_center = 1.0 - min(1.0, (abs(cx-0.5)/0.5)*0.5 + (abs(cy-0.45)/0.55)*0.5)
    # area ~0.10 of the stage region -> ~full close-up score; bigger faces saturate high
    closeup = min(1.0, max_area * 10.0)
    fscore = closeup * (0.7 + 0.3 * best_center)
    nfaces = len(faces)
    h8 = cv2.resize(gray, (9, 8)).astype(np.int16)
    dh = (h8[:, 1:] > h8[:, :-1]).flatten()
    return sharp, mean, clip, fscore, nfaces, dh

def cull_video(key):
    frames = sorted((SRC/key).glob("*.jpg"))
    if not frames:
        return 0
    feats = [analyze(f) for f in frames]
    keep = [(f, ft) for f, ft in zip(frames, feats) if ft is not None]
    if not keep:
        return 0
    frames = [f for f, _ in keep]; feats = [ft for _, ft in keep]
    sharp = np.array([f[0] for f in feats]); mean = np.array([f[1] for f in feats])
    clip = np.array([f[2] for f in feats]); face = np.array([f[3] for f in feats])
    dh = [f[5] for f in feats]
    n = len(frames); k = min(K, n)
    s_n = (sharp - sharp.min())/(np.ptp(sharp)+1e-9)
    expo = np.ones(n)
    expo[mean < 22] = 0.5; expo[mean > 232] = 0.7; expo[clip > 0.30] = 0.6
    # sharpness dominates (avoid blur); face is a secondary bonus. close-up is manual (wheel zoom).
    score = (0.72*s_n + 0.38*face) * expo
    order = list(np.argsort(-score))           # sharpest (highest score) first
    DUP = 8                                     # skip near-identical frames (dHash hamming < DUP)
    picked = []
    for i in order:
        if len(picked) >= k: break
        if any(np.count_nonzero(dh[i] != dh[j]) < DUP for j in picked): continue
        picked.append(i)
    if len(picked) < k:                         # fill if dup-skip left us short
        for i in order:
            if len(picked) >= k: break
            if i not in picked: picked.append(i)
    picked.sort()
    for i in picked:
        shutil.copy2(frames[i], DST/frames[i].name)
    return len(picked)

def main():
    from concurrent.futures import ProcessPoolExecutor
    keys = sorted([d.name for d in SRC.iterdir() if d.is_dir() and any(d.glob("*.jpg"))])
    for old in DST.glob("*.jpg"): old.unlink()
    total = 0; done = 0
    with ProcessPoolExecutor(max_workers=8) as ex:
        for c in ex.map(cull_video, keys):
            total += c; done += 1
            if done % 25 == 0: print(f"  {done}/{len(keys)}...", flush=True)
    print(f"DONE: {len(keys)} videos -> {total} culled")

if __name__ == "__main__":
    main()
