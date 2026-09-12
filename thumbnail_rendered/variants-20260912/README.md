# Thumbnail review, 2026-09-12

Open `index.html` locally to compare selected original frames with design concepts.

- 143 videos with 3,432 candidate JPEGs were found. The `.previews` directory is not a video.
- Four candidates per video were ranked using stage-region sharpness and exposure, then visually compared. Selections favor readable performers and unobstructed composition where the available frames permit it. The first video was reviewed across all 24 frames and frame 09 was selected separately.
- `best/<video-id>.jpg` contains byte-identical copies of the 143 selected originals. SHA-256 equality was checked for every copy.
- `manifest.json` records each selected source and the original video title.
- `prompts.json` records the two design prompts for each video. Only the first five videos have been generated so far: 10 concepts out of 286 planned.
- The built-in image generation tool produced the concepts. They are not identity-preserving production finals: inspection showed changes to facial details and parts of the stage, despite preservation instructions. Further generation is paused pending the user's choice between generation and deterministic photo editing.
- The PNG concepts are roughly 1672 × 941; some exceed the repository's 2 MiB thumbnail limit. Upload-ready conversion remains part of final production.
- Image assets are local and gitignored. The manifests, prompts, gallery and this status note are versioned.

Regenerate the gallery after adding assets:

```sh
python scripts/build_variant_gallery.py thumbnail_rendered/variants-20260912
```

Design reference: [vidIQ thumbnail design guide](https://vidiq.com/blog/post/youtube-thumbnail-design-tips/) — concise typography, a clear subject and authentic expressions. A uses prominent song typography; B prioritizes the photographed performance.
