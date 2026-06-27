import base64
import json
import os
import re
import sqlite3
import threading
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, request, send_file, render_template, abort, jsonify
from PIL import Image, ImageEnhance, ImageFilter

ALLOWED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CANDIDATE_DIRS = ["./thumbnails_culled"]
CONFIG_PATH = Path("./config.json")
RENDERED_DIR = Path("./thumbnail_rendered")
DATA_PATH = Path("./data.json")
SELECTIONS_PATH = Path("./selections.json")
PREVIEW_DIR = Path("./.previews")
PREVIEW_WIDTH = 800
PREVIEW_QUALITY = 66


def _cover_169(im):
    w, h = im.size
    tar = 16 / 9
    if w / h > tar:
        nw = int(round(h * tar)); x = (w - nw) // 2; return im.crop((x, 0, x + nw, h))
    # tall frame -> bias crop toward the TOP (keep stage/faces, drop bottom crowd/text area)
    nh = int(round(w / tar)); y = int((h - nh) * 0.18); return im.crop((0, y, w, y + nh))


def process_preview(im, width=PREVIEW_WIDTH):
    """Match the right-side canvas look: 16:9 cover-fit + contrast/sat + sharpen."""
    im = _cover_169(im.convert("RGB")).resize((width, round(width * 9 / 16)))
    im = ImageEnhance.Contrast(im).enhance(1.04)
    im = ImageEnhance.Color(im).enhance(1.08)
    return im.filter(ImageFilter.UnsharpMask(radius=1.5, percent=75, threshold=2))


def find_culled_dir() -> Path:
    for d in CANDIDATE_DIRS:
        p = Path(d)
        if p.exists() and p.is_dir():
            return p
    p = Path(CANDIDATE_DIRS[0])
    p.mkdir(parents=True, exist_ok=True)
    return p


CULLED_DIR = find_culled_dir()
RENDERED_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")
    return data


def list_images() -> list[str]:
    images = []
    for path in sorted(CULLED_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in ALLOWED_IMG_EXTS:
            images.append(path.name)
    return images


def video_key(fname: str) -> str:
    return re.sub(r"_\d+\.(jpg|jpeg|png|webp)$", "", fname, flags=re.IGNORECASE)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


CROPSET_PATH = Path("./cropsettings.json")  # legacy seed for the one-time DB migration

# ---- SQLite persistence (authoritative for user edits: selection, title/desc, crop) ----
DB_PATH = Path("./state.db")
_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock, db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS video_state(
            key TEXT PRIMARY KEY, selected TEXT, title TEXT, desc TEXT,
            zoom REAL, px REAL, py REAL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        # one-time migration from the legacy JSON files
        n = conn.execute("SELECT COUNT(*) FROM video_state").fetchone()[0]
        if n == 0:
            sel = load_json(SELECTIONS_PATH)
            crp = load_json(CROPSET_PATH)
            keys = set(sel) | set(crp)
            for k in keys:
                c = crp.get(k, {})
                conn.execute(
                    "INSERT OR IGNORE INTO video_state(key,selected,zoom,px,py) VALUES(?,?,?,?,?)",
                    (k, sel.get(k), c.get("zoom"), c.get("px"), c.get("py")))


def state_set(key, **fields):
    cols = [c for c in ("selected", "title", "desc", "zoom", "px", "py") if c in fields]
    if not cols:
        return
    with _db_lock, db() as conn:
        conn.execute("INSERT INTO video_state(key) VALUES(?) ON CONFLICT(key) DO NOTHING", (key,))
        conn.execute(
            "UPDATE video_state SET " + ", ".join(f"{c}=?" for c in cols) +
            ", updated_at=CURRENT_TIMESTAMP WHERE key=?",
            [fields[c] for c in cols] + [key])


def state_all():
    with db() as conn:
        return {r["key"]: dict(r) for r in conn.execute("SELECT * FROM video_state")}


init_db()


def load_all_metadata() -> dict:
    data = load_json(DATA_PATH)
    return {str(k): {
        "title": v.get("title", "") if isinstance(v, dict) else "",
        "desc": v.get("desc", "") if isinstance(v, dict) else ""
    } for k, v in data.items()}


def _json_order() -> dict:
    """Map video-key -> position so the UI follows the input JSON (upload) order."""
    ref = load_json(Path("./thumbnail_metadata_reference.json"))  # vkey -> {yt_id,...}
    key_to_id = {k: (v.get("yt_id") if isinstance(v, dict) else None) for k, v in ref.items()}
    order_ids = []
    inputs = sorted(Path("inputs").glob("youtube-videos-*.json"))
    if inputs:
        try:
            arr = json.load(open(inputs[-1], encoding="utf-8"))
            order_ids = [v.get("id") for v in arr if isinstance(v, dict)]
        except Exception:
            pass
    id_pos = {vid: i for i, vid in enumerate(order_ids)}
    return {k: id_pos.get(key_to_id.get(k), -1) for k in key_to_id}


def build_videos() -> list[dict]:
    files = list_images()
    meta = load_all_metadata()           # data.json = default title/desc (song / artist)
    st = state_all()                     # DB = user edits/selection/crop (authoritative)
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(video_key(f), []).append(f)
    pos = _json_order()
    ordered = sorted(groups, key=lambda k: pos.get(k, 10**9))
    videos = []
    for vkey in ordered:
        cands = sorted(groups[vkey])
        row = st.get(vkey, {})
        dtitle = next((meta[c]["title"] for c in cands if meta.get(c, {}).get("title")), "")
        ddesc = meta.get(cands[0], {}).get("desc", "")
        videos.append({
            "key": vkey,
            "title": row["title"] if row.get("title") is not None else dtitle,
            "desc": row["desc"] if row.get("desc") is not None else ddesc,
            "candidates": cands,
            "selected": row["selected"] if row.get("selected") in cands else "",
        })
    return videos


def cropset_map() -> dict:
    out = {}
    for k, r in state_all().items():
        if r.get("zoom") is not None:
            out[k] = {"zoom": r["zoom"], "px": r.get("px", 0.5), "py": r.get("py", 0.35)}
    return out


def safe_path(filename: str) -> Path:
    path = (CULLED_DIR / filename).resolve()
    if not str(path).startswith(str(CULLED_DIR.resolve())):
        abort(400, "Invalid file")
    if not path.exists() or path.suffix.lower() not in ALLOWED_IMG_EXTS:
        abort(404, "File not found")
    return path


app = Flask(__name__)


@app.route("/")
def index():
    config = load_config()
    return render_template(
        "index.html",
        videos=build_videos(),
        culled_dir=str(CULLED_DIR),
        config=config,
        config_json=json.dumps(config),
        cropset_json=json.dumps(cropset_map()),
    )


@app.route("/preview")
def serve_preview():
    """Small AVIF preview for the candidate grid (cached on disk)."""
    filename = unquote(request.args.get("file", ""))
    if not filename:
        abort(400, "Missing file")
    src = safe_path(filename)
    base = PREVIEW_DIR.resolve()
    safe_name = Path(filename).name  # basename only: strips any path separators / ".."
    cache = (PREVIEW_DIR / (safe_name + ".avif")).resolve()
    if not cache.is_relative_to(base):
        abort(400)
    if (not cache.exists()) or cache.stat().st_mtime < src.stat().st_mtime:
        im = process_preview(Image.open(src))
        try:
            im.save(cache, "AVIF", quality=PREVIEW_QUALITY)
        except Exception:
            cache = (PREVIEW_DIR / (safe_name + ".webp")).resolve()
            if not cache.is_relative_to(base):
                abort(400)
            im.save(cache, "WEBP", quality=70, method=4)
    mt = "image/avif" if cache.suffix == ".avif" else "image/webp"
    resp = send_file(cache, mimetype=mt)
    # revalidate (send_file sets ETag/Last-Modified) so regenerated previews show immediately
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/image")
def serve_image():
    filename = unquote(request.args.get("file", ""))
    if not filename:
        abort(400, "Missing file")
    return send_file(safe_path(filename))


@app.route("/save", methods=["POST"])
def save_image():
    payload = request.get_json(silent=True)
    if not payload:
        abort(400, "Invalid JSON payload")
    filename = unquote(payload.get("file", ""))
    image_data = payload.get("imageData", "")
    title = payload.get("title", "")[:500]
    desc = payload.get("desc", "")[:500]
    if not filename or not image_data:
        abort(400, "Missing data")
    safe_path(filename)
    if not image_data.startswith("data:image/") or "," not in image_data:
        abort(400, "Invalid image data")
    header, b64data = image_data.split(",", 1)
    try:
        binary = base64.b64decode(b64data)
    except Exception:
        abort(400, "Unable to decode image")
    ext = header.split("/")[-1].split(";")[0]
    ext = "png" if ext.lower() not in {"png", "jpeg", "jpg", "webp"} else ext.lower()
    out_path = (RENDERED_DIR / f"{Path(filename).stem}.{ext}").resolve()
    out_path.write_bytes(binary)
    state_set(video_key(filename), selected=filename, title=title, desc=desc)
    try:
        rel_path = out_path.relative_to(Path.cwd().resolve())
    except ValueError:
        rel_path = out_path
    return jsonify({"ok": True, "output": str(rel_path)})


@app.route("/select", methods=["POST"])
def select_only():
    payload = request.get_json(silent=True) or {}
    filename = unquote(payload.get("file", ""))
    if not filename:
        abort(400, "Missing file")
    safe_path(filename)
    state_set(video_key(filename), selected=filename)
    return jsonify({"ok": True})


@app.route("/savetext", methods=["POST"])
def savetext():
    """Auto-save title/desc for a video to the DB (no render)."""
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", ""))
    if not key:
        abort(400, "Missing key")
    state_set(key, title=payload.get("title", "")[:500], desc=payload.get("desc", "")[:500])
    return jsonify({"ok": True})


@app.route("/cropset", methods=["POST"])
def cropset():
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", ""))
    if not key:
        abort(400, "Missing key")
    try:
        zoom = max(1.0, min(3.0, float(payload.get("zoom", 1.0))))
        px = max(0.0, min(1.0, float(payload.get("px", 0.5))))
        py = max(0.0, min(1.0, float(payload.get("py", 0.35))))
    except (TypeError, ValueError):
        abort(400, "Bad values")
    state_set(key, zoom=round(zoom, 3), px=round(px, 3), py=round(py, 3))
    return jsonify({"ok": True})


def _launch_browser(host: str, port: int) -> None:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    threading.Timer(1.0, lambda: webbrowser.open_new(f"http://{browser_host}:{port}/")).start()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    run_main_flag = os.environ.get("WERKZEUG_RUN_MAIN")
    if run_main_flag == "true" or run_main_flag is None:
        _launch_browser(host, port)
    app.run(host=host, port=port, debug=True)
