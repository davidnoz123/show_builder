# Player and Rendering

This document defines the browser-side player.

## Goal

The player is a local browser app that renders resolved show JSON.

It must support:

- image slides
- local MP4 playback
- YouTube clips
- timed text overlays
- normalized coordinate placement
- reusable visual styles
- media effects and text effects
- eventual preview and export flows

## Runtime Model

The player receives already-resolved show data from Python.

The player should **not** understand workbook structure or nested sequence recursion.

Its job is to render a flat resolved timeline.

## Media Types

### image

- displayed as a background/media layer
- can have pan/zoom effects
- can have text overlays

### video

- local MP4 or other browser-playable file
- starts at `media_start`
- plays for `duration`
- can have overlays

### youtube

- embedded player using YouTube IFrame API
- starts at `media_start`
- plays for `duration`
- can have overlays

## Layer Model

Recommended conceptual layers:

- background/media layer
- text overlay layer
- optional debug/diagnostic layer

## Timing Model

Each resolved item has a duration in milliseconds.

Within an item:

- media starts at item start
- text overlays are triggered relative to item start
- media effect progression also uses item-relative time
- item ends when its resolved duration ends

## Coordinate System

Normalized coordinates should be supported.

### Coordinate semantics

- `x = 0` left edge
- `x = 1` right edge
- `y = 0` top edge
- `y = 1` bottom edge

### Preset positions

Support simple presets too:

- `top_left`
- `top_center`
- `top_right`
- `center_left`
- `center`
- `center_right`
- `bottom_left`
- `bottom_center`
- `bottom_right`

## Player JS API

Recommended surface:

- `loadShow(resolvedShow)`
- `playShow()`
- `pauseShow()`
- `stopShow()`
- `goToItem(index)`
- `getShowStatus()`

This API is the contract between Python/CDP and the browser player.

---

## Stage Containment System

**Problem:** CSS zoom/pan effects (`scale`, `translate`) applied to a video element can push
pixels outside the logical bounds of `#stage`. Browser-side OOPIF compositing (used by YouTube
iframes) escapes `overflow:hidden` on regular elements and paints directly on the screen.
Both failures let video content "bleed" visibly beyond the stage rectangle.

**Solution: two complementary layers (both are required):**

### 1. `#stage` CSS clip (software clip)
`#stage` has `overflow:hidden` and `clip-path:inset(0)`. This is sufficient for ordinary
HTML content but **does not contain OOPIF painters** (Chrome out-of-process iframes).

### 2. `#stage-frame` (compositor-level mask)
A `<div id="stage-frame">` inside `#stage`, defined in `index.html` and styled in
`styles.css`:

```css
#stage-frame {
    position: absolute;
    inset: -300px;               /* extends 300px beyond stage in all directions */
    border: 300px solid #000;    /* same 300px of solid black border */
    pointer-events: none;
    z-index: 9000;               /* above all media and overlay content */
    box-sizing: border-box;
}
```

This element lives in the same compositor layer as the stage. Its black border covers
everything outside the stage boundary, including any OOPIF overflow. The 300px margin
is large enough to absorb any realistic zoom factor.

**Do not remove `#stage-frame` from `index.html`. Without it, zoomed video will visibly
overflow the stage boundary.**

---

## Video Asset Render Architecture

For `asset_type = "video"` (local mp4), the player builds a three-level DOM stack:

```
#media-layer
  └── clipBox2        overflow:hidden; sized to crop rect (px coords)
        └── effectBox inset:0 inside clipBox2; receives CSS transform for effects
              └── vid  absolute; sized to full encoded-frame envelope;
                        offset so picture area aligns with effectBox origin
#overlay-layer
  └── matte strips    4 black divs covering pillarbox / letterbox bars
                      and anything outside the crop rect
```

### Why this stack

- **`clipBox2`** clamps effects. Any scale/translate applied to `effectBox` is hardware-clipped
  by `clipBox2`'s `overflow:hidden`. Effects never escape the crop rectangle.

- **`effectBox`** is the transform target. Its origin is the center of the picture, so
  `scale(1.35)` zooms from the center. If the transform were applied to the offset wrapper
  that also positions the video, the picture would jump.

- **`vid`** is positioned to bring the cropped picture area to `(0,0)` of `effectBox`.
  Formula (all in stage-scale pixels):
  ```
  scale  = min(stageW / encW, stageH / encH)
  envX   = (stageW - encW*scale) / 2        # letterbox/pillarbox centering
  clipX  = envX + crop.x * scale            # crop rect left in stage coords
  vid.left = envX - clipX = -crop.x * scale
  ```

### Crop data (`src_crop`)
Each video asset may carry a `src_crop: {w, h, x, y}` object (encoded-frame pixels).
If absent, the full encoded frame is used. `loadedmetadata` computes stage-scale pixel
positions and sets final sizes. The video is hidden (`visibility:hidden`) until
`loadedmetadata` completes to avoid an unsized flash on first frame.

### Matte strips
Four black `div`s are appended to `#overlay-layer` after crop geometry is known.
They permanently cover the pillarbox/letterbox bars and any clip-edge artefacts.
They are removed when the item ends (`clearMedia()`).

### Adding new effects
Effects are applied to `effectBox` via `_makeMediaEffectFn`. To add a new effect,
add a case to that function — do not change the layer stack.

