"""showbuilder/schema.py -- Dataclasses for all ShowBuilder schema entities.

Pure data definitions; no I/O.  Column order matches DATA_SCHEMA.md exactly.
"""
# ---------------------------------------------------------------------------
# SOURCE OF TRUTH NOTE
# showbuilder/schema.sql is the authoritative SQLite schema (DDL + CHECK
# constraints for all enum-valued columns).  When adding columns or tables:
#   1. Update schema.sql first (column definition + CHECK constraint if enum).
#   2. Update this file (add field to the matching dataclass).
#   3. Update showbuilder/workbook_io.py (read/write mapping).
#   4. Re-run showbuilder/dump_wb.py to push changes to showbuilder.db.
#   5. Re-run showbuilder/codegen.py to regenerate Python + VBA validators.
#
# Workflow summary:
#   schema.sql  (DDL + CHECK constraints)
#       ↓  dump_wb.py reads workbook → writes showbuilder.db using schema.sql
#   showbuilder.db
#       ↓  codegen.py introspects via PRAGMA table_info / foreign_key_list /
#          sqlite_master CHECK text
#   validate_row.py  (Python)  +  validators.bas  (VBA)
#
# codegen.py emits:
#   - validate_row(table, row_dict) → list[str]  (enum + nullable checks)
#   - VBA Public Sub Validate_<table>(ws, rowNum) with Select Case enum guards
#   Both can be used for:
#     * Programmatic row-insert validation in Python server code
#     * Ribbon "Validate" button in the workbook
#     * Excel sheet-change event handlers to flag bad values live
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 1. Formats
# ---------------------------------------------------------------------------

@dataclass
class Format:
    format_id:  str
    name:       str
    width_px:   int | None
    height_px:  int | None
    fps:        float | None
    enabled:    bool
    notes:      str


# ---------------------------------------------------------------------------
# 2. Assets
# ---------------------------------------------------------------------------

@dataclass
class Asset:
    asset_id:           str
    asset_type:         str   # image | video | youtube
    src:                str
    title:              str
    default_duration_ms: int | None
    metadata_json:      str
    enabled:            bool
    notes:              str


# ---------------------------------------------------------------------------
# 3. Items
# ---------------------------------------------------------------------------

@dataclass
class Item:
    item_id:             str
    asset_id:            str
    duration_ms:         int | None
    duration_mode:       str   # fixed | to_media_end
    media_start_s:       float | None
    effect_name:         str
    effect_params_json:  str
    default_text_set_id: str
    region_id:           str
    style_class:         str
    track_kind:          str
    media_audio_mode:    str
    media_audio_gain_db:       float | None
    z_order:                   int | None
    fit_mode:                  str   # cover | contain | stretch | none
    transition_in:             str
    transition_in_params_json: str
    transition_out:            str
    transition_out_params_json: str
    yt_freeze_at_s:            float | None
    yt_freeze_duration_ms:     int | None
    metadata_json:             str
    enabled:                   bool
    notes:                     str


# ---------------------------------------------------------------------------
# 4. TextSets
# ---------------------------------------------------------------------------

@dataclass
class TextSet:
    text_set_id:   str
    item_id:       str
    text_set_name: str
    metadata_json: str
    enabled:       bool
    notes:         str


# ---------------------------------------------------------------------------
# 5. TextOverlays
# ---------------------------------------------------------------------------

@dataclass
class TextOverlay:
    text_id:             str
    text_set_id:         str
    sequence_no:         int | None
    content:             str
    start_ms:            int | None
    duration_ms:         int | None
    position_mode:       str   # preset | coords
    position_preset:     str
    pos_x:               float | None
    pos_y:               float | None
    anchor:              str
    width_norm:          float | None
    align:               str
    region_id:           str
    effect_name:         str
    effect_params_json:  str
    style_class:         str
    metadata_json:       str
    enabled:             bool
    notes:               str


# ---------------------------------------------------------------------------
# 6. Styles
# ---------------------------------------------------------------------------

@dataclass
class Style:
    style_class:       str
    font_family:       str
    font_size_px:      int | None
    font_weight:       str
    color:             str
    bg_color:          str
    padding_px:        int | None
    border_radius_px:  int | None
    text_shadow:       str
    metadata_json:     str
    enabled:           bool
    notes:             str


# ---------------------------------------------------------------------------
# 7. Regions
# ---------------------------------------------------------------------------

@dataclass
class Region:
    region_id:     str
    x:             float | None
    y:             float | None
    w:             float | None
    h:             float | None
    anchor:        str
    metadata_json: str
    enabled:       bool
    notes:         str


# ---------------------------------------------------------------------------
# 8. Sequences
# ---------------------------------------------------------------------------

@dataclass
class Sequence:
    sequence_id:   str
    sequence_name: str
    sequence_type: str   # show | block | playlist
    format_id:     str
    timing_mode:   str   # serial | parallel
    description:   str
    metadata_json: str
    enabled:       bool


# ---------------------------------------------------------------------------
# 9. SequenceEntries
# ---------------------------------------------------------------------------

@dataclass
class SequenceEntry:
    sequence_entry_id:         str
    sequence_id:               str
    sequence_no:               int | None
    entry_type:                str   # item | sequence
    target_id:                 str
    track_kind:                str
    local_start_ms:            int | None
    override_duration_ms:      int | None
    override_media_start_s:    float | None
    override_effect_name:      str
    override_effect_params_json: str
    override_text_set_id:        str
    override_z_order:            int | None
    override_style_class:        str
    metadata_json:               str
    enabled:                     bool
    notes:                       str


# ---------------------------------------------------------------------------
# 10. Enums
# ---------------------------------------------------------------------------

@dataclass
class EnumRow:
    enum_type: str
    value:     str
    label:     str
    notes:     str


# ---------------------------------------------------------------------------
# 11. ICloudAccounts
# ---------------------------------------------------------------------------

@dataclass
class ICloudAccount:
    account_alias: str   # short name, used as FK in ICloudPhotos
    apple_id:      str   # Apple ID email
    enabled:       bool
    notes:         str


# ---------------------------------------------------------------------------
# 12. ICloudPhotos
# ---------------------------------------------------------------------------

@dataclass
class ICloudPhoto:
    icloud_photo_id: str          # stable iCloud photo ID (dedup key)
    account_alias:   str          # FK → ICloudAccounts
    filename:        str          # original iCloud filename
    created_date:    str          # ISO 8601 string
    media_type:      str          # image | video
    album:           str          # iCloud album name, may be empty
    local_path:      str          # relative path under media/cache/, empty if evicted
    local_hash:      str          # SHA-256 of cached file, empty if evicted
    asset_id:        str          # FK → Assets, empty if not registered
    last_synced:     str          # ISO 8601 string of last metadata pull
    notes:           str


# ---------------------------------------------------------------------------
# ShowbookData -- top-level container
# ---------------------------------------------------------------------------

@dataclass
class ShowbookData:
    formats:          list[Format]         = field(default_factory=list)
    assets:           list[Asset]          = field(default_factory=list)
    items:            list[Item]           = field(default_factory=list)
    text_sets:        list[TextSet]        = field(default_factory=list)
    text_overlays:    list[TextOverlay]    = field(default_factory=list)
    styles:           list[Style]          = field(default_factory=list)
    regions:          list[Region]         = field(default_factory=list)
    sequences:        list[Sequence]       = field(default_factory=list)
    sequence_entries: list[SequenceEntry]  = field(default_factory=list)
    enums:            list[EnumRow]        = field(default_factory=list)
    icloud_accounts:  list[ICloudAccount]  = field(default_factory=list)
    icloud_photos:    list[ICloudPhoto]    = field(default_factory=list)
