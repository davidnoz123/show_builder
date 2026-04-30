# Rendering and Export

This document defines the intended direction for MP4 export and related rendering concerns.

## Goal

Use the same resolved show model for:

- interactive preview
- deterministic playback
- eventual MP4 export

## Recommended Strategy

Do not build two completely different systems.

Instead:

- Excel + Python produce resolved show data
- browser player renders it
- export pipeline captures or renders from that player environment

## Social Media Target Formats

Common useful presets:

- `1920x1080` landscape
- `1080x1080` square
- `1080x1920` vertical
