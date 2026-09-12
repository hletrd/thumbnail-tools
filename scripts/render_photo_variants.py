"""Render two photo-preserving thumbnails from each reviewed source frame."""
import argparse
import colorsys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

FONT_DIR = Path.home() / "Library/Fonts"
SIZE = (1920, 1080)
MAX_BYTES = 2 * 1024 * 1024


@lru_cache(maxsize=256)
def font(size, korean=False, italic=False):
    name = "NotoSansKR-Black.ttf" if korean else (
        "NotoSans_Condensed-ExtraBoldItalic.ttf" if italic else "NotoSans_Condensed-Black.ttf"
    )
    return ImageFont.truetype(str(FONT_DIR / name), size)


def wrap(text, face, width):
    lines = []
    current = ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if face.getlength(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if word.isascii():
            current = word
            continue
        for char in word:
            if current and face.getlength(current + char) > width:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines


def text_block(canvas, text, box, maximum, minimum=38, max_lines=2,
               color="#f5f4ef", italic=False):
    x, y, width, height = box
    korean = bool(re.search(r"[\uac00-\ud7a3♡]", text))
    for size in range(maximum, minimum - 1, -2):
        face = font(size, korean, italic and not korean)
        lines = wrap(text, face, width - 14)
        metrics = [face.getbbox(line) for line in lines]
        gap = round(size * .16)
        actual_height = sum(b[3] - b[1] for b in metrics) + max(0, len(lines) - 1) * gap
        if (len(lines) <= max_lines and actual_height <= height
                and all(b[2] - b[0] <= width for b in metrics)):
            break
    else:
        raise ValueError(f"Text does not fit: {text}")
    draw = ImageDraw.Draw(canvas)
    for line, bounds in zip(lines, metrics):
        # Cancel font bearings so italic overhang cannot escape the text box.
        draw.text((x - bounds[0], y - bounds[1]), line, font=face, fill=color)
        assert bounds[2] - bounds[0] <= width
        y += bounds[3] - bounds[1] + gap
    return {"text": text, "font_size": size, "lines": lines, "box": list(box)}


def photo_treatment(source):
    sample = np.array(source.resize((192, 108)), dtype=np.float32)
    stage = sample[8:78]
    luminance = stage @ np.array([.2126, .7152, .0722])
    median = float(np.median(luminance))
    # Lift dark concert midtones gently; no local reconstruction or face processing.
    gamma = min(1.35, max(1.0, 1.0 + (92 - median) / 180))
    lut = [round(255 * (v / 255) ** (1 / gamma)) for v in range(256)]
    photo = source.point(lut * 3)
    photo = ImageEnhance.Color(photo).enhance(1.06)
    photo = ImageEnhance.Contrast(photo).enhance(1.025)
    return photo, gamma


def accent_color(source):
    colors = source.resize((96, 54)).convert("HSV")
    a = np.asarray(colors)
    mask = (a[:, :, 1] > 85) & (a[:, :, 2] > 55) & (a[:, :, 2] < 235)
    if mask.sum() < 20:
        return (196, 240, 128)
    hist, edges = np.histogram(a[:, :, 0][mask], bins=12, range=(0, 256))
    hue = (edges[int(hist.argmax())] + 10.7) / 255
    return tuple(round(v * 255) for v in colorsys.hsv_to_rgb(hue, .40, .98))


def paste_cover(canvas, photo, box, faces):
    x, y, width, height = box
    pw, ph = photo.size
    target = width / height
    cw, ch = (ph * target, ph) if pw / ph > target else (pw, pw / target)
    usable = [f for f in faces if f[1] < .82]
    cx, cy = pw / 2, ph * .48
    if usable:
        cx = (min(f[0] for f in usable) + max(f[0] + f[2] for f in usable)) * pw / 2
        cy = (sum(f[1] + f[3] / 2 for f in usable) / len(usable)
              + np.median([f[3] for f in usable]) * 2) * ph
    left, top = min(pw - cw, max(0, cx - cw / 2)), min(ph - ch, max(0, cy - ch / 2))
    if usable:
        x0 = max(0, min(f[0] - f[2] * .4 for f in usable) * pw)
        y0 = max(0, min(f[1] - f[3] * .65 for f in usable) * ph)
        x1 = min(pw, max(f[0] + f[2] * 1.4 for f in usable) * pw)
        y1 = min(ph, max(f[1] + f[3] * 1.4 for f in usable) * ph)
        if x1 - x0 > cw or y1 - y0 > ch:
            fitted = ImageOps.contain(photo, (width, height), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (x + (width - fitted.width) // 2, y + (height - fitted.height) // 2))
            return {"mode": "contain", "box": list(box)}
        left = min(max(left, x1 - cw), x0)
        top = min(max(top, y1 - ch), y0)
    crop = (round(left), round(top), round(left + cw), round(top + ch))
    fitted = photo.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
    fitted = fitted.filter(ImageFilter.UnsharpMask(radius=1.0, percent=35, threshold=4))
    canvas.paste(fitted, (x, y))
    return {"mode": "crop", "source_rectangle": crop, "box": list(box)}


def save_jpeg(canvas, destination):
    for quality in (94, 91, 88, 85, 80):
        buf = BytesIO()
        canvas.save(buf, "JPEG", quality=quality, optimize=True, subsampling=0)
        if buf.tell() <= MAX_BYTES:
            destination.write_bytes(buf.getvalue())
            return quality, buf.tell()
    raise ValueError(f"JPEG exceeds size limit: {destination}")


def render(row, directory):
    source_path = directory / "best" / f"{row['id']}.jpg"
    with Image.open(source_path) as image:
        source = ImageOps.exif_transpose(image).convert("RGB")
    photo, gamma = photo_treatment(source)
    faces = row.get("faces", [])
    song = row['song']
    if len(song) > 34 and " · " in song:
        song = song.split(" · ")[0]
    accent = accent_color(source)
    narrow = photo.width / photo.height < 1.45
    results = []
    for variant in ("A", "B"):
        destination = directory / "final" / f"{row['id']}_{variant}.jpg"
        canvas = Image.new("RGB", SIZE, (14, 17, 25))
        draw = ImageDraw.Draw(canvas)
        texts = []
        if narrow:
            # A real, unwarped portrait on the right; dedicated copy space on the left.
            photo_width = 1000 if variant == "A" else 1080
            photo_x = 1920 - photo_width
            crop = paste_cover(canvas, photo, (photo_x, 0, photo_width, 1080), faces)
            width = photo_x - 128
            draw.rectangle((photo_x - 8, 0, photo_x - 1, 1080), fill=accent)
            if variant == "A":
                draw.rectangle((64, 68, 136, 77), fill=accent)
                texts.append(text_block(canvas, row['artist'], (64, 115, width, 155), 76, max_lines=2, color=accent))
                texts.append(text_block(canvas, song, (64, 320, width, 565), 170, max_lines=5))
            else:
                texts.append(text_block(canvas, row['artist'], (64, 510, width, 130), 58, max_lines=2, color=accent))
                texts.append(text_block(canvas, song, (64, 690, width, 260), 108, max_lines=3, italic=True))
            texts.append(text_block(canvas, "hletrd", (64, 1005, width, 40), 28, minimum=24, color="#929ba9"))
        elif variant == "A":
            # Typography is outside the source photo, so it cannot cover a face.
            crop = paste_cover(canvas, photo, (0, 306, 1920, 774), faces)
            draw.rectangle((64, 42, 76, 99), fill=accent)
            texts.append(text_block(canvas, row['artist'], (98, 40, 1640, 70), 64, max_lines=1, color=accent))
            texts.append(text_block(canvas, song, (64, 138, 1792, 140), 152, max_lines=2))
            draw.rectangle((0, 299, 1919, 305), fill=accent)
            texts.append(text_block(canvas, "hletrd", (1730, 64, 130, 36), 28, minimum=24, color="#929ba9"))
        else:
            crop = paste_cover(canvas, photo, (0, 0, 1920, 830), faces)
            draw.rectangle((64, 866, 130, 873), fill=accent)
            texts.append(text_block(canvas, row['artist'], (158, 848, 1530, 54), 48, max_lines=1, color=accent))
            texts.append(text_block(canvas, song, (64, 927, 1670, 116), 116, max_lines=2, italic=True))
            texts.append(text_block(canvas, "hletrd", (1730, 868, 130, 36), 28, minimum=24, color="#929ba9"))
        quality, size = save_jpeg(canvas, destination)
        preview = canvas.resize((640, 360), Image.Resampling.LANCZOS)
        preview.save(directory / "previews" / destination.name, quality=85, optimize=True)
        results.append({"id": row['id'], "variant": variant, "file": f"final/{destination.name}",
                        "source": row['selected'], "gamma": round(gamma, 4), "accent": accent,
                        "width": 1920, "height": 1080, "bytes": size,
                        "jpeg_quality": quality, "photo_layout": crop, "text_layout": texts})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = json.loads((args.directory / "prompts.json").read_text())
    faces = json.loads((args.directory / "face-rectangles.json").read_text())
    for row in rows:
        row["faces"] = faces[row["id"]]
    if args.limit:
        rows = rows[:args.limit]
    for folder in ("final", "previews"):
        (args.directory / folder).mkdir(exist_ok=True)
    records = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, pair in enumerate(pool.map(lambda row: render(row, args.directory), rows), 1):
            records.extend(pair)
            if index % 20 == 0:
                print(f"Rendered {index}/{len(rows)} videos", flush=True)
    (args.directory / "render-report.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f"Saved {len(records)} photo-preserving thumbnails", flush=True)


if __name__ == "__main__":
    main()
