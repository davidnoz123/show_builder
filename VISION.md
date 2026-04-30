# ShowBuilder — Vision Document

## Core Use Case

Create a personal family film archive from digitised 8mm reels.
The source material is fragile, degraded, and historically irreplaceable.
The goal is to produce watchable, contextualised presentations
that can be shared with family and preserved for the long term.

This is not a general video editor.
It is a specialised authoring system for a known corpus with known metadata.

---

## What We Have Now

| Component | Status |
|-----------|--------|
| Chrome/CDP runtime | Working |
| YouTube playback controller | Working |
| Annotation workbook (11 sheets, ~1800 scenes) | Working |
| `annotations.db` — SQLite snapshot of all scene data | Working |
| `showbuilder.db` — SQLite snapshot of show definition | Working |
| `schema.sql` — DDL single source of truth with CHECK constraints | Working |
| `codegen.py` — auto-generates Python + VBA validators from DB | Working |
| `createPlayer(container, options)` factory | Working |
| 3-clip dev show end-to-end | Working |
| `multi.html` — 4 independent player instances | Working |
| Viewport matte / crop | Working |
| Static asset server | Working |

---

## Architecture Principles

1. **SQLite is the write surface.** The workbook is authored input; the DB is the live show state.
2. **Server owns lifetime.** `AppRuntime` constructs and starts all services.
3. **Controllers cause side effects.** Monitors and agents observe only.
4. **No cross-layer coupling.** Excel ingress → Controller → CDP → Chrome. No upward references.
5. **Schema drives validators.** `codegen.py` regenerates Python + VBA validators from `schema.sql`; no manual sync.
6. **Player is a factory.** `createPlayer(container, options)` builds all DOM inside the container; supports multiple instances.
7. **CSS namespace.** All player styles under `.sb-*` to allow multi-player layouts without bleed.
8. **No yt-dlp until needed.** YouTube playback via CDP avoids download latency; local files used only when required.
9. **Simulation tests first.** `sim_test()` classmethods validate logic without browser dependencies.
10. **No defensive programming beyond correctness.** No try/except around things that cannot fail.
11. **Minimal public API.** Method surfaces are defined in `01_method_surface.tsv`; do not expand without intent.
12. **Agent + user are symmetric authors.** Both write SQL; neither has privileged access.

---

## Object Model (Current)

Defined in `schema.sql` and mirrored in `schema.py`:

| Object | Description |
|--------|-------------|
| `Asset` | A source video (YouTube URL, crop bounds, usb stick + mp4 name) |
| `Item` | A segment of an Asset (start/end seconds, effect, label) |
| `Sequence` | An ordered list of Items forming a playable show |
| `SequenceEntry` | Ordered join table (sequence → item, with position) |
| `Scene` (annotations) | A timed annotation point in the source 8mm footage |
| `Sheet` (annotations) | A grouping of scenes from one digitised reel segment |
| `Reel` (annotations) | A physical 8mm reel (usb stick + mp4 name canonical key) |

---

## Object Model Gaps

The current model is sufficient for a linear sequence of cropped YouTube clips.
It is insufficient for the following patterns:

1. **Parallel tracks.** No way to lay two clips side-by-side or picture-in-picture simultaneously.
2. **Keyframe animation.** No per-frame property curves (position, scale, opacity).
3. **Audio tracks.** No model for music beds, narration, or ambient audio independent of the video clip.
4. **SVG overlays.** No model for text captions, arrows, speech bubbles, or highlight circles over video.
5. **Transitions.** No crossfade or wipe between Items; cuts only.
6. **Stabilisation.** No link between an Asset and a stabilised derivative.
7. **Regions.** No way to define a named spatial region (e.g. "left half") and reuse it across Items.
8. **Composite sources.** No way to mix YouTube playback with local file playback in the same show.
9. **Thumbnail/poster.** No stored poster image for a Sequence (needed for show index UI).

---

## 6-Phase Upgrade Roadmap

### Phase 1 — Schema foundation
Extend `schema.sql` to cover the missing model objects:

- Add `Track` table (type: `video | audio | svg`; z-order; spatial region FK)
- Add `Region` table (x, y, w, h as fractions of stage)
- Add `Keyframe` table (item_id, t_ms, property, value)
- Add `AudioTrack` table (asset_id or url, start_s, end_s, gain, loop)
- Add `SvgOverlay` table (item_id, t_start_ms, t_end_ms, svg_data)
- Add `transition_duration_ms` column to `SequenceEntry`
- Promote `yt_vid_id`, `src_crop_*` as typed Asset columns (they are already JSON blobs now)
- Add `region_id` FK to `Item`

Regenerate `validate_row.py` + `validators.bas` via `codegen.py` after each schema change.

**Done when:** `codegen.py` runs cleanly against the extended schema; `dump_wb.py` loads without FK errors; `validate_row.py` rejects a deliberately invalid row for each new table.

### Phase 2 — Asset pipeline
Machinery to prepare source material for use:

- `download(asset_id)` — fetch via yt-dlp to local cache
- `stabilise(asset_id)` — ffmpeg vidstab; stores derivative path on Asset
- `detect_crop(asset_id)` — ffmpeg cropdetect; updates `src_crop_*` columns
- `extract_thumbnail(item_id, t_s)` — grab poster frame; stored in `media/`

**Done when:** For one existing asset: yt-dlp download completes; vidstab derivative is stored and playable; cropdetect result is written to the DB; thumbnail appears in `media/`.

### Phase 3 — Write surface (SQLite-first)
This is **the architectural gap to close first** for agent authoring.
Currently the DB is a read-only snapshot of the workbook.
This phase flips it to the live write store:

- Remove workbook-as-source-of-truth for show definition
- Add mutation endpoints to `server.py`:
  - `POST /api/asset` — add source video
  - `POST /api/item` — add segment
  - `POST /api/sequence` — create show
  - `PATCH /api/sequence/{id}` — reorder / append / remove items
  - `PATCH /api/item/{id}` — update crop, effect, label
  - `DELETE /api/item/{id}`
- Agent tools: `add_clip()`, `set_effect()`, `arrange_clips()`, `create_overlay()`
- Workbook becomes an optional export surface, not the write path

**Done when:** A fresh `POST /api/sequence` + several `POST /api/item` calls (with no workbook open) produce a playable show in the browser; `dump_wb.py` is no longer needed to refresh the DB.

### Phase 4 — Multi-track player
Extend the browser player to render multi-track shows:

- `Track` objects rendered as positioned `<div>` layers inside the stage
- `Region` objects mapped to CSS `left/top/width/height` on track containers
- `KeyframeInterpolator` — linear/cubic interpolation over property curves
- `AudioContext` — Web Audio API for music bed, narration mixing
- `SvgOverlay` renderer — inject `<svg>` into the overlay layer at scheduled times
- Transitions: CSS `opacity:0→1` crossfades between Items

**Done when:** A two-track show plays with one video region left, one right; a music bed AudioTrack fades in and out; a keyframe animates one clip's scale over 2 seconds; a crossfade transition is visible between two Items.

### Phase 5 — SVG / cartoon direction
SVG as a first-class authoring layer over live video:

- Primitive types: `highlight_circle`, `arrow`, `speech_bubble`, `caption_band`, `blur_rect`
- All primitives authored as SVG data stored in `SvgOverlay` rows
- Agent can generate SVG primitives from natural language descriptions
- Animations expressed as SVG SMIL or CSS keyframes embedded in the SVG data
- Long-term: full cartoon panels composited over video (South Park / Bluey style)

**Done when:** An agent call produces a speech bubble SVG overlay timed to a clip; it appears and disappears correctly in the player; the SVG string is stored verbatim in the DB with no special schema beyond the `SvgOverlay` table.

### Phase 6 — Export and presentation
Turn shows into standalone deliverables:

- `render_show(sequence_id)` — ffmpeg offline render to MP4
- Show index page — thumbnails, titles, dates, durations
- iCloud export — push rendered MP4s + index HTML to iCloud Drive
- PDF programme notes — LaTeX or WeasyPrint from sequence metadata

**Done when:** `render_show(sequence_id)` produces a watchable MP4 for the 3-clip dev show; the show index page displays title, thumbnail, and duration; the MP4 is accessible via iCloud Drive.

---

## SVG Animation Model

SVG overlays are stored as raw SVG strings in the `SvgOverlay` table, indexed by `(item_id, t_start_ms, t_end_ms)`.

The player injects them into the `#overlay` layer at the scheduled time and removes them at `t_end_ms`.

Primitives are authored at a higher level (natural language → agent → SVG string).
The DB stores only the final SVG; no primitive schema is needed.

This keeps the model simple: one string column holds arbitrary visual complexity.

---

## Audio Model

Multi-track audio is achievable with ~40 lines of Web Audio API code:

```
AudioContext
  └── music bed (looped, gain-ramped)
  └── narration track (one-shot, gain-ramped)
  └── video element audio (gain-controlled per clip)
```

Encoded in `AudioTrack` rows:
- `asset_id` — local file or URL
- `start_s`, `end_s` — trim points
- `gain` — 0.0–1.0
- `loop` — boolean
- `t_offset_ms` — when to start relative to show timeline

---

## Platform Constraints

| Constraint | Implication |
|------------|-------------|
| Source is YouTube | No raw frames; yt-dlp needed for offline pipeline |
| CDP required for control | Annotation server must be running; no competing CDPClients |
| Windows only (pywin32) | No cross-platform build target |
| 8mm runs at 16 fps | Timestamps rounded to 1/16 s in VBA and Python |
| Excel is the annotation surface | Annotation DB is a snapshot; workbook is the write surface for scene data |
| ShowBuilder DB is the show write surface | Workbook is export-only for show definition (after Phase 3) |

---

## Symmetric Authoring Vision

The system should support two authoring modes with identical write access:

**User mode (Excel + VBA):**
- Annotate scenes in the 8mm workbook
- Build clips via the ShowBuilder ribbon
- Trigger refresh via VBA buttons

**Agent mode (Python + SQL):**
- Query annotations.db to find candidate scenes
- Write show definitions directly to showbuilder.db via `/api/*` endpoints
- Call player to preview in the browser
- Iterate without user involvement

Both modes write to the same SQLite database.
Neither has privileged access.
The agent can draft; the user can override; the player reflects the current DB state.

This is the long-term goal: the user describes what they want in natural language,
the agent assembles a draft show from the annotation corpus,
and the user refines it interactively.
