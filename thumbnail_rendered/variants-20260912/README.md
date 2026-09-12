# Photo-preserving thumbnails, 2026-09-12

Open `index.html` locally to compare each selected original with the two finished thumbnails. Download `thumbnails-286.zip` for all 286 JPEGs, arranged by artist, song and video ID.

- 143 videos with 3,432 candidate JPEGs were found. The `.previews` directory is not a video.
- Four candidates per video were ranked using stage-region sharpness and exposure, then visually compared. Selections favor readable performers and unobstructed composition where the available frames permit it. The first video was reviewed across all 24 frames and frame 09 was selected separately.
- `best/<video-id>.jpg` contains byte-identical copies of the 143 selected originals. SHA-256 equality was checked for every copy.
- `manifest.json` records each selected source and the original video title.
- `final/` contains all 286 finished images: 1920 × 1080 RGB JPEGs, individually below 2 MiB. `previews/` contains lightweight 640 × 360 gallery images.
- A uses large upright song typography above the concert photo; B uses a larger photo with compact typography underneath. Narrow sources use a photo panel and separate text column. Accent colors come from the source stage lighting.
- The user authorized deterministic editing. Finals use only the original photograph, aspect-preserving crop/resize, gentle midtone and color adjustments, mild sharpening and text. No faces or scenery are generated, reconstructed or replaced. Text occupies dedicated space outside the photograph.
- `face-rectangles.json` contains local Apple Vision face rectangles used to protect visible faces during cropping. If a crop cannot contain the detected faces, the complete photograph is fitted instead. Detection is not identity recognition and is not guaranteed to find every face.
- `render-report.json` records the exact source crop, treatment, text layout and output size for each final. Long medley captions may show only the first song; full source titles remain in the gallery and manifest.
- `validation.json` records checks of all 286 image formats, dimensions and sizes, all 143 original-copy hashes, visible detected faces inside crops, and text boxes outside photographs. All 286 designs were visually compared to their sources in contact sheets; narrow English wrapping and long medley captions were corrected.
- The earlier 10 generated PNG concepts remain available in `concepts.html`. They are separate from the finished JPEGs and ZIP because their faces and stage details differ from the originals. `prompts.json` retains their original prompts and supplies artist/song metadata for the deterministic renderer.
- Image assets, previews and the ZIP are local and gitignored. Scripts, metadata, reports and galleries are versioned.

Reproduce using the existing Pillow/NumPy environment, installed Noto Sans/Noto Sans KR fonts in `~/Library/Fonts`, and macOS Vision:

```sh
swift scripts/detect_thumbnail_faces.swift thumbnail_rendered/variants-20260912/best thumbnail_rendered/variants-20260912/face-rectangles.json
.venv/bin/python scripts/render_photo_variants.py thumbnail_rendered/variants-20260912
.venv/bin/python scripts/build_variant_gallery.py thumbnail_rendered/variants-20260912
```

Design reference: [vidIQ thumbnail design guide](https://vidiq.com/blog/post/youtube-thumbnail-design-tips/) — concise typography, a clear subject and authentic expressions. A uses prominent song typography; B prioritizes the photographed performance.

Face rectangle API: [Apple Vision documentation](https://developer.apple.com/documentation/vision/vndetectfacerectanglesrequest).
