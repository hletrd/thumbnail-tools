"""Build an offline comparison gallery for originals and finished thumbnails."""
import html
import json
from pathlib import Path
import sys


def build(directory):
    rows = json.loads((directory / "prompts.json").read_text())
    count = 0
    cards = []
    finished = (directory / "final").is_dir()
    for row in rows:
        images = [("선택한 원본", f"best/{row['id']}.jpg")]
        for variant, label in [("A", "A · 큰 곡명"), ("B", "B · 사진 중심")]:
            source = (f"final/{row['id']}_{variant}.jpg" if finished
                      else f"{row['id']}_{variant}.png")
            if (directory / source).exists():
                images.append((label, source))
                count += 1
        figures = []
        for label, source in images:
            preview = source.replace("final/", "previews/") if source.startswith("final/") else source
            figures.append(
                f'<figure><a href="{source}" target="_blank">'
                f'<img loading="lazy" src="{preview}" alt="{html.escape(row["title"], quote=True)}">'
                f'</a><figcaption>{label} <a href="{source}" download>다운로드</a></figcaption></figure>'
            )
        cards.append(
            f'<article data-search="{html.escape(row["title"].lower(), quote=True)}">'
            f'<h2>{html.escape(row["title"])}</h2><div class="grid">{"".join(figures)}</div></article>'
        )
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>썸네일 비교</title>
<style>*{box-sizing:border-box}body{background:#0e1014;color:#e9edf5;font:15px system-ui;margin:0;padding:28px}
header{position:sticky;top:0;padding:18px 0;background:#0e1014ed;z-index:1}h1{margin:0 0 8px}p{color:#a9b3c5}
input{width:min(600px,100%);padding:14px;background:#20242e;color:white;border:1px solid #404858;border-radius:10px}
article{padding:24px 0;border-bottom:1px solid #303644}h2{font-size:17px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
figure{margin:0}img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#08090c;border-radius:8px}
figcaption{padding:10px 0}a{color:#b9ceff}figcaption a{float:right}.note{color:#efc787}
@media(max-width:850px){.grid{grid-template-columns:1fr}}[hidden]{display:none}</style>
<header><h1>영상별 썸네일 비교</h1>'''
    if finished:
        page += f'<p>영상 {len(rows)}개 · 완성본 {count}/{len(rows) * 2}장 · 1920×1080 JPG · 원본 사진 사용</p>'
        if (directory / "thumbnails-286.zip").exists():
            page += '<p><a href="thumbnails-286.zip" download>전체 286장 ZIP 다운로드</a></p>'
    else:
        page += f'<p>기준 컷 {len(rows)}개 · 생성형 시안 {count}개</p>'
        page += '<p class="note">생성형 시안은 얼굴·무대 일부가 원본과 다를 수 있습니다.</p>'
    page += '<input id="search" placeholder="아티스트 또는 곡명 검색" aria-label="영상 검색"></header>'
    page += "".join(cards)
    page += '''<script>document.querySelector('#search').addEventListener('input',e=>{
const q=e.target.value.toLowerCase();document.querySelectorAll('article').forEach(a=>a.hidden=!a.dataset.search.includes(q));
});</script></html>'''
    (directory / "index.html").write_text(page)
    print(f"Gallery: {len(rows)} selections, {count} thumbnails")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
