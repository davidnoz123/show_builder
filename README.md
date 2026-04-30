# ShowBuilder Spec Pack

This pack defines a data-driven multimedia show system intended to start with Excel as the authoring surface and a browser-based player controlled from Python via Chrome DevTools Protocol (CDP).

## Purpose

The system is intended to support:

- image slides
- local MP4 media
- YouTube clips
- timed text overlays
- reusable nested sequences
- effect-driven rendering
- Python-controlled playback
- eventual MP4 export

## Main Subsystems

- `DATA_SCHEMA.md` — Excel-first data schema and validation rules
- `SEQUENCING_AND_RESOLUTION.md` — how reusable blocks/shows are composed and flattened
- `PLAYER_AND_RENDERING.md` — browser player behavior and playback model
- `EFFECTS_SYSTEM.md` — extensible effects model for media and text
- `PYTHON_SYSTEM.md` — workbook IO, validation, resolver/compiler, JSON builder, CLI tools
- `CDP_AND_RUNTIME_CONTROL.md` — local Chrome player control through CDP
- `AGENT_WORKFLOW.md` — safe VS Code / Claude workflow guidance
- `RENDERING_AND_EXPORT.md` — capture/export direction for MP4 outputs
- `ROADMAP.md` — v1 scope, deferred features, future expansion

## Core Design Principles

- Excel is the initial authoring surface, not the runtime model.
- Python owns validation, resolution, and control.
- The browser owns rendering.
- Shows are built from reusable nested sequences.
- Effects are specified by `effect_name` plus `effect_params`.
- Text overlays are timed objects, not hardwired title/body fields.
- Coordinates are normalized where precise placement is needed.
- Overrides are allowed, but should stay deliberately limited.

## Recommended First Build Order

1. Freeze workbook schema
2. Implement workbook reader/writer
3. Implement validation
4. Implement sequence resolver/compiler
5. Emit resolved JSON for the player
6. Build browser player
7. Build CDP controller
8. Add preview flow
9. Add export/capture flow later

## Intended Repo Role

This pack is suitable to place under a subdirectory in an existing repo while the system is being incubated. It is also structured so it can later be split into its own repo.

Generated: 2026-04-04T03:59:23.716670Z
