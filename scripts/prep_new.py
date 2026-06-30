#!/usr/bin/env python3
"""Append newly-published fancams from the latest inputs JSON to the work list.

Finds fancam (직캠) uploads whose id is not already in sources.tsv, derives the
same `date6_song_id` key, and appends them to sources.tsv +
thumbnail_metadata_reference.json. Writes .new_meta.json (key -> {song, artist})
for the post-cull data.json step. Idempotent — safe to re-run after each new
batch of uploads. Then run hdr_extract.py (only the new ids download) and re-cull.
"""
import json, glob, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAN = ROOT / "sources.tsv"
REF = ROOT / "thumbnail_metadata_reference.json"
NEW_META = ROOT / ".new_meta.json"


def sanitize(s):
    s = re.sub(r"[()\[\]]", "", s)
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", s).strip("_")[:60]


def parse(title):
    m = re.search(r"(\d{6})\s+(.+?)\s+-\s+(.+?)\s+직캠", title)
    return (m.group(1), m.group(2).strip(), m.group(3).strip()) if m else None


def main():
    inputs = sorted(glob.glob(str(ROOT / "inputs/youtube-videos-*.json")))
    if not inputs:
        sys.exit("no inputs/youtube-videos-*.json found")
    arr = json.load(open(inputs[-1]))
    lines = [l.rstrip("\n") for l in open(MAN)] if MAN.exists() else []
    ids = {l.split("\t")[1] for l in lines if "\t" in l}
    ref = json.load(open(REF)) if REF.exists() else {}

    new_meta, added = {}, []
    for v in arr:
        vid, title = v["id"], v.get("title", "")
        if vid in ids or "직캠" not in title:
            continue
        p = parse(title)
        if not p:
            print("NO-PARSE:", title[:70]); continue
        d6, artist, song = p
        key = f"{d6}_{sanitize(song)}_{vid}"
        lines.append(f"{key}\t{vid}"); ids.add(vid)
        ref[key] = {"yt_id": vid, "yt_title": title, "yt_description": v.get("description", ""),
                    "song": song, "event": None, "source": "YouTube",
                    "nas_path": None, "match_score": 0.0}
        new_meta[key] = {"song": song, "artist": artist}
        added.append(key)

    MAN.write_text("\n".join(lines) + "\n")
    json.dump(ref, open(REF, "w"), ensure_ascii=False, indent=2)
    json.dump(new_meta, open(NEW_META, "w"), ensure_ascii=False, indent=2)
    print(f"added {len(added)} new fancams | sources.tsv now {len(lines)}")
    for k in added:
        print("  +", k)


if __name__ == "__main__":
    main()
