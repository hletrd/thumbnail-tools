import subprocess
from pathlib import Path

def extract_keyframe_thumbnails():
    inputs_dir = Path("./inputs")
    out_root = Path("./thumbnails")
    exts = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".mts", ".m2ts", ".mpg", ".mpeg"}

    if not inputs_dir.exists():
        raise SystemExit("Inputs folder './inputs' not found.")

    out_root.mkdir(parents=True, exist_ok=True)

    videos = [p for p in sorted(inputs_dir.iterdir()) if p.is_file() and p.suffix.lower() in exts]
    if not videos:
        raise SystemExit("No video files found in ./inputs")

    for vid in videos:
        out_dir = out_root / vid.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        out_pattern = str(out_dir / f"{vid.stem}_kf_%010d.jpg")
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-y",
            "-skip_frame", "nokey",
            "-i", str(vid),
            "-map", "0:v:0",
            "-fps_mode", "vfr",
            "-frame_pts", "true",
            out_pattern,
        ]

        try:
            subprocess.run(cmd, check=True)
            print(f"[OK] {vid.name} → {out_dir}")
        except subprocess.CalledProcessError as e:
            print(f"[ERR] Failed on {vid.name}: {e}")

if __name__ == "__main__":
    extract_keyframe_thumbnails()
