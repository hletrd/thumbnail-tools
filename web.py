import base64
import json
import os
import threading
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, request, send_file, render_template, abort, jsonify

ALLOWED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CANDIDATE_DIRS = ["./thumnails_culled", "./thumbnails_culled"]
CONFIG_PATH = Path("./config.json")
RENDERED_DIR = Path("./thumbnail_rendered")
DATA_PATH = Path("./data.json")


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


def load_all_metadata() -> dict[str, dict[str, str]]:
    if not DATA_PATH.exists():
        return {}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): {
                "title": v.get("title", "") if isinstance(v, dict) else "",
                "desc": v.get("desc", "") if isinstance(v, dict) else ""
            } for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_metadata(filename: str, title: str, desc: str) -> None:
    data = load_all_metadata()
    data[filename] = {"title": title, "desc": desc}
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def metadata_for_files(files: list[str]) -> dict[str, dict[str, str]]:
    stored = load_all_metadata()
    result: dict[str, dict[str, str]] = {}
    for fname in files:
        entry = stored.get(fname, {})
        title = entry.get("title", "") if isinstance(entry, dict) else ""
        desc = entry.get("desc", "") if isinstance(entry, dict) else ""
        result[fname] = {"title": title, "desc": desc}
    return result


def _default_title(fname: str) -> str:
    stem = Path(fname).stem
    return stem.replace("_", " ").replace("-", " ")


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
    files = list_images()
    metadata = metadata_for_files(files)
    config = load_config()
    return render_template(
        "index.html",
        files=files,
        culled_dir=str(CULLED_DIR),
        default_title=_default_title,
        metadata=metadata,
        config=config,
        config_json=json.dumps(config)
    )


@app.route("/image")
def serve_image():
    filename = request.args.get("file", "")
    if not filename:
        abort(400, "Missing file")
    try:
        filename = unquote(filename)
        base_path = safe_path(filename)
    except Exception:
        abort(400, "Bad request")
    return send_file(base_path)


@app.route("/save", methods=["POST"])
def save_image():
    payload = request.get_json(silent=True)
    if not payload:
        abort(400, "Invalid JSON payload")

    filename = payload.get("file", "")
    image_data = payload.get("imageData", "")
    title = payload.get("title", "")[:500]
    desc = payload.get("desc", "")[:500]

    if not filename or not image_data:
        abort(400, "Missing data")

    try:
        filename = unquote(filename)
        base_path = safe_path(filename)
    except Exception:
        abort(400, "Invalid file")

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

    save_metadata(filename, title, desc)

    try:
        rel_path = out_path.relative_to(Path.cwd().resolve())
    except ValueError:
        rel_path = out_path

    return jsonify({"ok": True, "output": str(rel_path)})


def _launch_browser(host: str, port: int) -> None:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    threading.Timer(1.0, lambda: webbrowser.open_new(f"http://{browser_host}:{port}/")).start()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))

    run_main_flag = os.environ.get("WERKZEUG_RUN_MAIN")
    if run_main_flag == "true" or run_main_flag is None:
        _launch_browser(host, port)

    app.run(host=host, port=port, debug=True)
