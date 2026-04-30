# Data Schema

This document defines the Excel-first schema for ShowBuilder.

## Goals

The schema must support:

- reusable raw media assets
- playable items derived from those assets
- multiple timed text overlays per item
- reusable nested sequences
- limited overrides when including items/sequences
- extensible effects without redesigning the workbook every time
- future-friendly evolution toward audio and more advanced rendering

## Naming Conventions

Suggested stable IDs:

- Assets: `A_*`
- Items: `I_*`
- Text sets: `TS_*`
- Text overlays: `T_*`
- Sequences: `S_*`
- Sequence entries: `SE_*`
- Styles: `ST_*`
- Regions: `R_*`
- Formats: `F_*`

## Workbook Sheets

Recommended v1 sheets:

- `Formats`
- `Assets`
- `Items`
- `TextSets`
- `TextOverlays`
- `Styles`
- `Regions`
- `Sequences`
- `SequenceEntries`
- `Enums`

## 1. Formats

Defines output canvas presets.

### Columns

- `format_id`
- `name`
- `width_px`
- `height_px`
- `fps`
- `enabled`
- `notes`

### Example

| format_id | name | width_px | height_px | fps | enabled |
|---|---|---:|---:|---:|---|
| F_LANDSCAPE | HD Landscape | 1920 | 1080 | 30 | TRUE |
| F_SQUARE | Square Social | 1080 | 1080 | 30 | TRUE |
| F_VERTICAL | Vertical Social | 1080 | 1920 | 30 | TRUE |

## 2. Assets

Raw media resources.

### Columns

- `asset_id`
- `asset_type`
- `src`
- `title`
- `default_duration_ms`
- `metadata_json`
- `enabled`
- `notes`

### asset_type

- `image`
- `video`
- `youtube`

### Notes

- `src` is a relative media path for `image` and `video`
- `src` is ideally a YouTube video ID for `youtube`
- `default_duration_ms` can be blank if not meaningful

## 3. Items

A playable unit derived from one asset.

### Columns

- `item_id`
- `asset_id`
- `duration_ms`
- `duration_mode`
- `media_start_s`
- `effect_name`
- `effect_params_json`
- `default_text_set_id`
- `region_id`
- `style_class`
- `track_kind`
- `media_audio_mode`
- `media_audio_gain_db`
- `metadata_json`
- `enabled`
- `notes`

### duration_mode

- `fixed`
- `to_media_end`

### track_kind

Suggested initial values:

- `video_main`
- `video_overlay`
- `text_overlay`
- future: `audio_music`, `audio_voice`, `audio_sfx`

### media_audio_mode

Suggested initial values:

- `mute`
- `normal`
- `ducked`

### Notes

- `effect_name` plus `effect_params_json` define media behavior
- `default_text_set_id` selects the default timed text overlay set for this item
- `region_id` is optional if you want a reusable canvas region for the item

## 4. TextSets

Named text variants for an item.

### Columns

- `text_set_id`
- `item_id`
- `text_set_name`
- `metadata_json`
- `enabled`
- `notes`

### Purpose

One item can have multiple text sets, for example:

- `default`
- `short_version`
- `ai_version`
- `no_text`

## 5. TextOverlays

Timed overlay objects attached to a text set.

### Columns

- `text_id`
- `text_set_id`
- `sequence_no`
- `content`
- `start_ms`
- `duration_ms`
- `position_mode`
- `position_preset`
- `pos_x`
- `pos_y`
- `anchor`
- `width_norm`
- `align`
- `region_id`
- `effect_name`
- `effect_params_json`
- `style_class`
- `metadata_json`
- `enabled`
- `notes`

### position_mode

- `preset`
- `coords`

### position_preset

- `top_left`
- `top_center`
- `top_right`
- `center_left`
- `center`
- `center_right`
- `bottom_left`
- `bottom_center`
- `bottom_right`

### anchor

- `top_left`
- `top_center`
- `top_right`
- `center_left`
- `center`
- `center_right`
- `bottom_left`
- `bottom_center`
- `bottom_right`

### align

- `left`
- `center`
- `right`

### Coordinate Semantics

Normalized coordinates are used when `position_mode = coords`:

- `pos_x`: `0..1` left to right
- `pos_y`: `0..1` top to bottom
- `width_norm`: normalized box width, optional

## 6. Styles

Reusable visual text styles.

### Columns

- `style_class`
- `font_family`
- `font_size_px`
- `font_weight`
- `color`
- `bg_color`
- `padding_px`
- `border_radius_px`
- `text_shadow`
- `metadata_json`
- `enabled`
- `notes`

## 7. Regions

Reusable regions / layout boxes.

### Columns

- `region_id`
- `x`
- `y`
- `w`
- `h`
- `anchor`
- `metadata_json`
- `enabled`
- `notes`

### Notes

All values are normalized.

This is optional in v1 but worth freezing into the schema now.

## 8. Sequences

Reusable sequence containers. A show is a sequence.

### Columns

- `sequence_id`
- `sequence_name`
- `sequence_type`
- `format_id`
- `timing_mode`
- `description`
- `metadata_json`
- `enabled`

### sequence_type

- `show`
- `block`
- `playlist`

### timing_mode

- `serial`
- `parallel`

## 9. SequenceEntries

Composition layer linking sequences to items or other sequences.

### Columns

- `sequence_entry_id`
- `sequence_id`
- `sequence_no`
- `entry_type`
- `target_id`
- `track_kind`
- `local_start_ms`
- `override_duration_ms`
- `override_media_start_s`
- `override_effect_name`
- `override_effect_params_json`
- `override_text_set_id`
- `metadata_json`
- `enabled`
- `notes`

### entry_type

- `item`
- `sequence`

## 10. Enums

A helper sheet for controlled vocabularies and data validation.

Suggested groups:

- `asset_type`
- `duration_mode`
- `sequence_type`
- `timing_mode`
- `entry_type`
- `position_mode`
- `position_preset`
- `anchor`
- `align`
- `track_kind`
- `media_audio_mode`

## Relationships

- `Items.asset_id -> Assets.asset_id`
- `Items.default_text_set_id -> TextSets.text_set_id` (optional)
- `TextSets.item_id -> Items.item_id`
- `TextOverlays.text_set_id -> TextSets.text_set_id`
- `TextOverlays.region_id -> Regions.region_id` (optional)
- `Items.region_id -> Regions.region_id` (optional)
- `Sequences.format_id -> Formats.format_id`
- `SequenceEntries.sequence_id -> Sequences.sequence_id`
- `SequenceEntries.target_id -> Items.item_id` when `entry_type=item`
- `SequenceEntries.target_id -> Sequences.sequence_id` when `entry_type=sequence`

## Validation Rules

At minimum, validate:

- all IDs are unique in their own table
- all required foreign keys resolve
- enum values are valid
- JSON fields parse correctly where populated
- `position_mode = coords` requires `pos_x`, `pos_y`, `anchor`
- `position_mode = preset` requires `position_preset`
- normalized values remain in `0..1` where expected
- `start_ms >= 0`
- `duration_ms > 0`
- sequence recursion cannot contain cycles
