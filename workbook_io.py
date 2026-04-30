"""showbuilder/workbook_io.py -- COM-based Excel reader/writer for ShowBuilder.

Uses win32com.client (pywin32).  Pass an already-open win32com Workbook object.

Sheet layout
------------
- "ShowBuilder"    -- always visible; summary dashboard rebuilt by seed_workbook()
- 10 data sheets   -- xlSheetVeryHidden; one named ListObject each; touched only by Python

Public API
----------
    seed_workbook(wb)                       -- create missing sheets/tables, seed Enums, rebuild summary, save
    read_workbook(wb)                       -> ShowbookData
    write_asset_metadata(wb, asset_id, md)  -- merge md dict into Asset.metadata_json (e.g. src_crop after cropdetect)
    expose_sheets(wb)                       -- set all data sheets to xlSheetVisible (for manual inspection)
    seal_sheets(wb)                         -- set all data sheets back to xlSheetVeryHidden
"""

import json

from schema import (
    Asset,
    EnumRow,
    Format,
    ICloudAccount,
    ICloudPhoto,
    Item,
    Region,
    Sequence,
    SequenceEntry,
    ShowbookData,
    Style,
    TextOverlay,
    TextSet,
)

# ---------------------------------------------------------------------------
# Excel constants
# ---------------------------------------------------------------------------

_XL_VISIBLE      = -1   # xlSheetVisible
_XL_VERY_HIDDEN  =  2   # xlSheetVeryHidden
_XL_SRC_RANGE    =  1   # xlSrcRange  (ListObjects.Add SourceType)
_XL_YES          =  1   # xlYes       (ListObjects.Add HasHeaders)

SUMMARY_SHEET = "ShowBuilder"

DATA_SHEETS = [
    "Formats",
    "Assets",
    "Items",
    "TextSets",
    "TextOverlays",
    "Styles",
    "Regions",
    "Sequences",
    "SequenceEntries",
    "Enums",
    "ICloudAccounts",
    "ICloudPhotos",
]

# ---------------------------------------------------------------------------
# Column order per sheet  (must match DATA_SCHEMA.md exactly)
# ---------------------------------------------------------------------------

_SHEET_COLS: dict[str, list[str]] = {
    "Formats": [
        "format_id", "name", "width_px", "height_px", "fps", "enabled", "notes",
    ],
    "Assets": [
        "asset_id", "asset_type", "src", "title", "default_duration_ms",
        "metadata_json", "enabled", "notes",
    ],
    "Items": [
        "item_id", "asset_id", "duration_ms", "duration_mode", "media_start_s",
        "effect_name", "effect_params_json", "default_text_set_id", "region_id",
        "style_class", "track_kind", "media_audio_mode", "media_audio_gain_db",
        "z_order", "fit_mode", "transition_in", "transition_in_params_json",
        "transition_out", "transition_out_params_json",
        "yt_freeze_at_s", "yt_freeze_duration_ms",
        "metadata_json", "enabled", "notes",
    ],
    "TextSets": [
        "text_set_id", "item_id", "text_set_name", "metadata_json", "enabled", "notes",
    ],
    "TextOverlays": [
        "text_id", "text_set_id", "sequence_no", "content", "start_ms", "duration_ms",
        "position_mode", "position_preset", "pos_x", "pos_y", "anchor", "width_norm",
        "align", "region_id", "effect_name", "effect_params_json", "style_class",
        "metadata_json", "enabled", "notes",
    ],
    "Styles": [
        "style_class", "font_family", "font_size_px", "font_weight", "color",
        "bg_color", "padding_px", "border_radius_px", "text_shadow",
        "metadata_json", "enabled", "notes",
    ],
    "Regions": [
        "region_id", "x", "y", "w", "h", "anchor", "metadata_json", "enabled", "notes",
    ],
    "Sequences": [
        "sequence_id", "sequence_name", "sequence_type", "format_id", "timing_mode",
        "description", "metadata_json", "enabled",
    ],
    "SequenceEntries": [
        "sequence_entry_id", "sequence_id", "sequence_no", "entry_type", "target_id",
        "track_kind", "local_start_ms", "override_duration_ms", "override_media_start_s",
        "override_effect_name", "override_effect_params_json", "override_text_set_id",
        "override_z_order", "override_style_class",
        "metadata_json", "enabled", "notes",
    ],
    "Enums": [
        "enum_type", "value", "label", "notes",
    ],
    "ICloudAccounts": [
        "account_alias", "apple_id", "enabled", "notes",
    ],
    "ICloudPhotos": [
        "icloud_photo_id", "account_alias", "filename", "created_date",
        "media_type", "album", "local_path", "local_hash",
        "asset_id", "last_synced", "notes",
    ],
}

# ---------------------------------------------------------------------------
# Seeded Enums  (enum_type, value, label)
# ---------------------------------------------------------------------------

_ENUM_SEED: list[tuple[str, str, str]] = [
    ("asset_type",       "image",         "Image file"),
    ("asset_type",       "video",         "Video file"),
    ("asset_type",       "youtube",       "YouTube video"),
    ("duration_mode",    "fixed",         "Fixed duration (duration_ms)"),
    ("duration_mode",    "to_media_end",  "Play until media ends"),
    ("sequence_type",    "show",          "Top-level show"),
    ("sequence_type",    "block",         "Reusable block"),
    ("sequence_type",    "playlist",      "Playlist"),
    ("timing_mode",      "serial",        "Items play one after another"),
    ("timing_mode",      "parallel",      "Items play simultaneously"),
    ("entry_type",       "item",          "Entry references an Item"),
    ("entry_type",       "sequence",      "Entry references a Sequence"),
    ("position_mode",    "preset",        "Use position_preset"),
    ("position_mode",    "coords",        "Use pos_x / pos_y"),
    ("position_preset",  "top_left",      ""),
    ("position_preset",  "top_center",    ""),
    ("position_preset",  "top_right",     ""),
    ("position_preset",  "center_left",   ""),
    ("position_preset",  "center",        ""),
    ("position_preset",  "center_right",  ""),
    ("position_preset",  "bottom_left",   ""),
    ("position_preset",  "bottom_center", ""),
    ("position_preset",  "bottom_right",  ""),
    ("anchor",           "top_left",      ""),
    ("anchor",           "top_center",    ""),
    ("anchor",           "top_right",     ""),
    ("anchor",           "center_left",   ""),
    ("anchor",           "center",        ""),
    ("anchor",           "center_right",  ""),
    ("anchor",           "bottom_left",   ""),
    ("anchor",           "bottom_center", ""),
    ("anchor",           "bottom_right",  ""),
    ("align",            "left",          ""),
    ("align",            "center",        ""),
    ("align",            "right",         ""),
    ("track_kind",       "video_main",    "Primary video track"),
    ("track_kind",       "video_overlay", "Video overlay track"),
    ("track_kind",       "text_overlay",  "Text overlay track"),
    ("media_audio_mode", "mute",          "No audio"),
    ("media_audio_mode", "normal",        "Full volume"),
    ("media_audio_mode", "ducked",        "Reduced volume"),
    ("fit_mode",         "cover",         "Scale to fill canvas, crop edges"),
    ("fit_mode",         "contain",       "Scale to fit, letterbox"),
    ("fit_mode",         "stretch",       "Stretch to fill, ignore aspect ratio"),
    ("fit_mode",         "none",          "No scaling, original size"),
]

# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------

def _str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() not in ("false", "0", "no", "")


def _int_or_none(v) -> "int | None":
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _float_or_none(v) -> "float | None":
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Low-level sheet / ListObject helpers
# ---------------------------------------------------------------------------

def _find_sheet(wb, name: str):
    """Return the named worksheet or None (works for any Visible setting)."""
    try:
        for ws in wb.Sheets:
            if ws.Name == name:
                return ws
    except Exception:
        pass
    return None


def _get_or_create_sheet(wb, name: str):
    """Return sheet by name, creating it after the last sheet if absent."""
    ws = _find_sheet(wb, name)
    if ws is None:
        ws = wb.Sheets.Add(After=wb.Sheets(wb.Sheets.Count))
        ws.Name = name
    return ws


def _find_list_object(ws, name: str):
    """Return the named ListObject on ws, or None."""
    try:
        for lo in ws.ListObjects:
            if lo.Name == name:
                return lo
    except Exception:
        pass
    return None


def _create_list_object(ws, table_name: str, cols: list[str]):
    """Write header row and create a named ListObject from it.

    The table is created from just the header row; DataBodyRange will be None
    until data rows are appended.
    """
    for c, col in enumerate(cols, start=1):
        ws.Cells(1, c).Value = col
    rng = ws.Range(ws.Cells(1, 1), ws.Cells(1, len(cols)))
    lo = ws.ListObjects.Add(_XL_SRC_RANGE, rng, None, _XL_YES)
    lo.Name = table_name
    return lo


def _table_col_map(lo) -> dict[str, int]:
    """Return {column_name: 1-based index within the table} for a ListObject."""
    return {
        lo.ListColumns(i).Name: i
        for i in range(1, lo.ListColumns.Count + 1)
    }


def _read_table(ws, table_name: str) -> list[dict]:
    """Read all non-empty data rows from a named ListObject as list[dict]."""
    lo = _find_list_object(ws, table_name)
    if lo is None:
        return []
    dbr = lo.DataBodyRange
    if dbr is None:
        return []
    col_map = _table_col_map(lo)
    rows: list[dict] = []
    for r in range(1, dbr.Rows.Count + 1):
        row: dict = {}
        all_empty = True
        for name, c in col_map.items():
            v = dbr.Cells(r, c).Value
            row[name] = v
            if v is not None and str(v).strip():
                all_empty = False
        if not all_empty:
            rows.append(row)
    return rows


def _append_table_row(lo, values: dict) -> None:
    """Append one row to a ListObject using values keyed by column name."""
    col_map = _table_col_map(lo)
    lr = lo.ListRows.Add()
    for name, col_idx in col_map.items():
        v = values.get(name, "")
        if v is not None:
            lr.Range.Cells(1, col_idx).Value = v


def find_table_row(ws, table_name: str, key_col: str, key_val: str) -> "int | None":
    """Return the 1-based DataBodyRange row index where key_col == key_val, or None."""
    lo = _find_list_object(ws, table_name)
    if lo is None:
        return None
    dbr = lo.DataBodyRange
    if dbr is None:
        return None
    col_map = _table_col_map(lo)
    c = col_map.get(key_col)
    if c is None:
        return None
    for r in range(1, dbr.Rows.Count + 1):
        v = dbr.Cells(r, c).Value
        if v is not None and str(v).strip() == key_val:
            return r
    return None


def update_table_row(ws, table_name: str, row_idx: int, values: dict) -> None:
    """Update specific columns in a DataBodyRange row (1-based row_idx)."""
    lo = _find_list_object(ws, table_name)
    if lo is None:
        return
    dbr = lo.DataBodyRange
    if dbr is None:
        return
    col_map = _table_col_map(lo)
    for col_name, val in values.items():
        c = col_map.get(col_name)
        if c is not None and val is not None:
            dbr.Cells(row_idx, c).Value = val


def write_asset_metadata(wb, asset_id: str, metadata: dict) -> bool:
    """Merge metadata dict into Asset.metadata_json for the given asset_id.

    Reads the existing JSON blob, updates it with the supplied keys, and
    writes it back.  Returns True if the asset was found, False otherwise.
    Safe to call with a partial dict -- only the supplied keys are changed.
    """
    ws = _find_sheet(wb, "Assets")
    if ws is None:
        return False
    row_idx = find_table_row(ws, "Assets", "asset_id", asset_id)
    if row_idx is None:
        return False
    lo = _find_list_object(ws, "Assets")
    dbr = lo.DataBodyRange
    col_map = _table_col_map(lo)
    c = col_map.get("metadata_json")
    if c is None:
        return False
    existing_raw = _str(dbr.Cells(row_idx, c).Value)
    try:
        existing = json.loads(existing_raw) if existing_raw else {}
    except Exception:
        existing = {}
    existing.update(metadata)
    dbr.Cells(row_idx, c).Value = json.dumps(existing)
    return True


# ---------------------------------------------------------------------------
# Sheet readers
# ---------------------------------------------------------------------------

def _read_formats(wb) -> list[Format]:
    ws = _find_sheet(wb, "Formats")
    if ws is None:
        return []
    return [
        Format(
            format_id = _str(d.get("format_id")),
            name      = _str(d.get("name")),
            width_px  = _int_or_none(d.get("width_px")),
            height_px = _int_or_none(d.get("height_px")),
            fps       = _float_or_none(d.get("fps")),
            enabled   = _bool(d.get("enabled")),
            notes     = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Formats")
    ]


def _read_assets(wb) -> list[Asset]:
    ws = _find_sheet(wb, "Assets")
    if ws is None:
        return []
    return [
        Asset(
            asset_id            = _str(d.get("asset_id")),
            asset_type          = _str(d.get("asset_type")),
            src                 = _str(d.get("src")),
            title               = _str(d.get("title")),
            default_duration_ms = _int_or_none(d.get("default_duration_ms")),
            metadata_json       = _str(d.get("metadata_json")),
            enabled             = _bool(d.get("enabled")),
            notes               = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Assets")
    ]


def _read_items(wb) -> list[Item]:
    ws = _find_sheet(wb, "Items")
    if ws is None:
        return []
    return [
        Item(
            item_id             = _str(d.get("item_id")),
            asset_id            = _str(d.get("asset_id")),
            duration_ms         = _int_or_none(d.get("duration_ms")),
            duration_mode       = _str(d.get("duration_mode")),
            media_start_s       = _float_or_none(d.get("media_start_s")),
            effect_name         = _str(d.get("effect_name")),
            effect_params_json  = _str(d.get("effect_params_json")),
            default_text_set_id = _str(d.get("default_text_set_id")),
            region_id           = _str(d.get("region_id")),
            style_class         = _str(d.get("style_class")),
            track_kind          = _str(d.get("track_kind")),
            media_audio_mode    = _str(d.get("media_audio_mode")),
            media_audio_gain_db        = _float_or_none(d.get("media_audio_gain_db")),
            z_order                    = _int_or_none(d.get("z_order")),
            fit_mode                   = _str(d.get("fit_mode")),
            transition_in              = _str(d.get("transition_in")),
            transition_in_params_json  = _str(d.get("transition_in_params_json")),
            transition_out             = _str(d.get("transition_out")),
            transition_out_params_json = _str(d.get("transition_out_params_json")),
            yt_freeze_at_s             = _float_or_none(d.get("yt_freeze_at_s")),
            yt_freeze_duration_ms      = _int_or_none(d.get("yt_freeze_duration_ms")),
            metadata_json              = _str(d.get("metadata_json")),
            enabled                    = _bool(d.get("enabled")),
            notes                      = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Items")
    ]


def _read_text_sets(wb) -> list[TextSet]:
    ws = _find_sheet(wb, "TextSets")
    if ws is None:
        return []
    return [
        TextSet(
            text_set_id   = _str(d.get("text_set_id")),
            item_id       = _str(d.get("item_id")),
            text_set_name = _str(d.get("text_set_name")),
            metadata_json = _str(d.get("metadata_json")),
            enabled       = _bool(d.get("enabled")),
            notes         = _str(d.get("notes")),
        )
        for d in _read_table(ws, "TextSets")
    ]


def _read_text_overlays(wb) -> list[TextOverlay]:
    ws = _find_sheet(wb, "TextOverlays")
    if ws is None:
        return []
    return [
        TextOverlay(
            text_id            = _str(d.get("text_id")),
            text_set_id        = _str(d.get("text_set_id")),
            sequence_no        = _int_or_none(d.get("sequence_no")),
            content            = _str(d.get("content")),
            start_ms           = _int_or_none(d.get("start_ms")),
            duration_ms        = _int_or_none(d.get("duration_ms")),
            position_mode      = _str(d.get("position_mode")),
            position_preset    = _str(d.get("position_preset")),
            pos_x              = _float_or_none(d.get("pos_x")),
            pos_y              = _float_or_none(d.get("pos_y")),
            anchor             = _str(d.get("anchor")),
            width_norm         = _float_or_none(d.get("width_norm")),
            align              = _str(d.get("align")),
            region_id          = _str(d.get("region_id")),
            effect_name        = _str(d.get("effect_name")),
            effect_params_json = _str(d.get("effect_params_json")),
            style_class        = _str(d.get("style_class")),
            metadata_json      = _str(d.get("metadata_json")),
            enabled            = _bool(d.get("enabled")),
            notes              = _str(d.get("notes")),
        )
        for d in _read_table(ws, "TextOverlays")
    ]


def _read_styles(wb) -> list[Style]:
    ws = _find_sheet(wb, "Styles")
    if ws is None:
        return []
    return [
        Style(
            style_class      = _str(d.get("style_class")),
            font_family      = _str(d.get("font_family")),
            font_size_px     = _int_or_none(d.get("font_size_px")),
            font_weight      = _str(d.get("font_weight")),
            color            = _str(d.get("color")),
            bg_color         = _str(d.get("bg_color")),
            padding_px       = _int_or_none(d.get("padding_px")),
            border_radius_px = _int_or_none(d.get("border_radius_px")),
            text_shadow      = _str(d.get("text_shadow")),
            metadata_json    = _str(d.get("metadata_json")),
            enabled          = _bool(d.get("enabled")),
            notes            = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Styles")
    ]


def _read_regions(wb) -> list[Region]:
    ws = _find_sheet(wb, "Regions")
    if ws is None:
        return []
    return [
        Region(
            region_id     = _str(d.get("region_id")),
            x             = _float_or_none(d.get("x")),
            y             = _float_or_none(d.get("y")),
            w             = _float_or_none(d.get("w")),
            h             = _float_or_none(d.get("h")),
            anchor        = _str(d.get("anchor")),
            metadata_json = _str(d.get("metadata_json")),
            enabled       = _bool(d.get("enabled")),
            notes         = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Regions")
    ]


def _read_sequences(wb) -> list[Sequence]:
    ws = _find_sheet(wb, "Sequences")
    if ws is None:
        return []
    return [
        Sequence(
            sequence_id   = _str(d.get("sequence_id")),
            sequence_name = _str(d.get("sequence_name")),
            sequence_type = _str(d.get("sequence_type")),
            format_id     = _str(d.get("format_id")),
            timing_mode   = _str(d.get("timing_mode")),
            description   = _str(d.get("description")),
            metadata_json = _str(d.get("metadata_json")),
            enabled       = _bool(d.get("enabled")),
        )
        for d in _read_table(ws, "Sequences")
    ]


def _read_sequence_entries(wb) -> list[SequenceEntry]:
    ws = _find_sheet(wb, "SequenceEntries")
    if ws is None:
        return []
    return [
        SequenceEntry(
            sequence_entry_id           = _str(d.get("sequence_entry_id")),
            sequence_id                 = _str(d.get("sequence_id")),
            sequence_no                 = _int_or_none(d.get("sequence_no")),
            entry_type                  = _str(d.get("entry_type")),
            target_id                   = _str(d.get("target_id")),
            track_kind                  = _str(d.get("track_kind")),
            local_start_ms              = _int_or_none(d.get("local_start_ms")),
            override_duration_ms        = _int_or_none(d.get("override_duration_ms")),
            override_media_start_s      = _float_or_none(d.get("override_media_start_s")),
            override_effect_name        = _str(d.get("override_effect_name")),
            override_effect_params_json = _str(d.get("override_effect_params_json")),
            override_text_set_id        = _str(d.get("override_text_set_id")),
            override_z_order            = _int_or_none(d.get("override_z_order")),
            override_style_class        = _str(d.get("override_style_class")),
            metadata_json               = _str(d.get("metadata_json")),
            enabled                     = _bool(d.get("enabled")),
            notes                       = _str(d.get("notes")),
        )
        for d in _read_table(ws, "SequenceEntries")
    ]


def _read_enums(wb) -> list[EnumRow]:
    ws = _find_sheet(wb, "Enums")
    if ws is None:
        return []
    return [
        EnumRow(
            enum_type = _str(d.get("enum_type")),
            value     = _str(d.get("value")),
            label     = _str(d.get("label")),
            notes     = _str(d.get("notes")),
        )
        for d in _read_table(ws, "Enums")
    ]


def _read_icloud_accounts(wb) -> list[ICloudAccount]:
    ws = _find_sheet(wb, "ICloudAccounts")
    if ws is None:
        return []
    return [
        ICloudAccount(
            account_alias = _str(d.get("account_alias")),
            apple_id      = _str(d.get("apple_id")),
            enabled       = _bool(d.get("enabled")),
            notes         = _str(d.get("notes")),
        )
        for d in _read_table(ws, "ICloudAccounts")
    ]


def _read_icloud_photos(wb) -> list[ICloudPhoto]:
    ws = _find_sheet(wb, "ICloudPhotos")
    if ws is None:
        return []
    return [
        ICloudPhoto(
            icloud_photo_id = _str(d.get("icloud_photo_id")),
            account_alias   = _str(d.get("account_alias")),
            filename        = _str(d.get("filename")),
            created_date    = _str(d.get("created_date")),
            media_type      = _str(d.get("media_type")),
            album           = _str(d.get("album")),
            local_path      = _str(d.get("local_path")),
            local_hash      = _str(d.get("local_hash")),
            asset_id        = _str(d.get("asset_id")),
            last_synced     = _str(d.get("last_synced")),
            notes           = _str(d.get("notes")),
        )
        for d in _read_table(ws, "ICloudPhotos")
    ]


# ---------------------------------------------------------------------------
# Enum seeding
# ---------------------------------------------------------------------------

def _seed_enums(wb) -> None:
    """Append missing Enums rows (keyed on enum_type + value) to the ListObject."""
    ws = _find_sheet(wb, "Enums")
    if ws is None:
        return
    lo = _find_list_object(ws, "Enums")
    if lo is None:
        return

    existing: set[tuple[str, str]] = set()
    for d in _read_table(ws, "Enums"):
        k = (_str(d.get("enum_type")), _str(d.get("value")))
        if k[0]:
            existing.add(k)

    for enum_type, value, label in _ENUM_SEED:
        if (enum_type, value) in existing:
            continue
        _append_table_row(lo, {"enum_type": enum_type, "value": value,
                                "label": label, "notes": ""})
        existing.add((enum_type, value))


# ---------------------------------------------------------------------------
# Summary sheet
# ---------------------------------------------------------------------------

def _rebuild_summary(wb) -> None:
    """Rebuild the ShowBuilder summary sheet with row counts per data table."""
    ws = _get_or_create_sheet(wb, SUMMARY_SHEET)
    ws.Visible = _XL_VISIBLE
    ws.Cells.ClearContents()

    ws.Cells(1, 1).Value = "ShowBuilder"
    ws.Cells(3, 1).Value = "Table"
    ws.Cells(3, 2).Value = "Rows"
    ws.Cells(3, 3).Value = "Enabled"

    for i, name in enumerate(DATA_SHEETS, start=4):
        data_ws = _find_sheet(wb, name)
        rows = 0
        enabled = 0
        if data_ws is not None:
            lo = _find_list_object(data_ws, name)
            if lo is not None:
                dbr = lo.DataBodyRange
                if dbr is not None:
                    rows = dbr.Rows.Count
                    # Count enabled rows where the "enabled" column exists
                    col_map = _table_col_map(lo)
                    if "enabled" in col_map:
                        ec = col_map["enabled"]
                        for r in range(1, rows + 1):
                            if _bool(dbr.Cells(r, ec).Value):
                                enabled += 1
        ws.Cells(i, 1).Value = name
        ws.Cells(i, 2).Value = rows
        ws.Cells(i, 3).Value = enabled if rows else ""


# ---------------------------------------------------------------------------
# Public: seed
# ---------------------------------------------------------------------------

def seed_workbook(wb) -> None:
    """Create missing ShowBuilder sheets and ListObjects, seed Enums, rebuild summary.

    - Never modifies an existing ListObject or its data.
    - Data sheets are set to xlSheetVeryHidden after creation.
    - The ShowBuilder summary sheet is always visible.
    """
    for name in DATA_SHEETS:
        cols = _SHEET_COLS[name]
        ws = _get_or_create_sheet(wb, name)
        if _find_list_object(ws, name) is None:
            _create_list_object(ws, name, cols)
        ws.Visible = _XL_VERY_HIDDEN

    _seed_enums(wb)
    _rebuild_summary(wb)
    wb.Save()


# ---------------------------------------------------------------------------
# Public: read
# ---------------------------------------------------------------------------

def read_workbook(wb) -> ShowbookData:
    """Read all ShowBuilder data from an open win32com Workbook.

    Absent sheets or empty ListObjects return empty lists.
    """
    return ShowbookData(
        formats          = _read_formats(wb),
        assets           = _read_assets(wb),
        items            = _read_items(wb),
        text_sets        = _read_text_sets(wb),
        text_overlays    = _read_text_overlays(wb),
        styles           = _read_styles(wb),
        regions          = _read_regions(wb),
        sequences        = _read_sequences(wb),
        sequence_entries = _read_sequence_entries(wb),
        enums            = _read_enums(wb),
        icloud_accounts  = _read_icloud_accounts(wb),
        icloud_photos    = _read_icloud_photos(wb),
    )


# ---------------------------------------------------------------------------
# Public: expose / seal
# ---------------------------------------------------------------------------

def expose_sheets(wb) -> None:
    """Make all data sheets visible for manual inspection."""
    for name in DATA_SHEETS:
        ws = _find_sheet(wb, name)
        if ws is not None:
            ws.Visible = _XL_VISIBLE


def seal_sheets(wb) -> None:
    """Return all data sheets to xlSheetVeryHidden."""
    for name in DATA_SHEETS:
        ws = _find_sheet(wb, name)
        if ws is not None:
            ws.Visible = _XL_VERY_HIDDEN


# ---------------------------------------------------------------------------
# sim_test
# ---------------------------------------------------------------------------

class _WorkbookIoTest:
    @classmethod
    def sim_test(cls) -> None:
        """Smoke-test against the live 8mm_database.xlsm."""
        import os
        import win32com.client as wc

        wb_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "8mm_database.xlsm")
        )
        print(f"sim_test: opening {wb_path}")
        xl = wc.Dispatch("Excel.Application")
        xl.Visible = False
        wb = xl.Workbooks.Open(wb_path)
        try:
            print("sim_test: seeding workbook...")
            seed_workbook(wb)
            print("sim_test: reading workbook...")
            data = read_workbook(wb)
            print(f"  formats:          {len(data.formats)}")
            print(f"  assets:           {len(data.assets)}")
            print(f"  items:            {len(data.items)}")
            print(f"  text_sets:        {len(data.text_sets)}")
            print(f"  text_overlays:    {len(data.text_overlays)}")
            print(f"  styles:           {len(data.styles)}")
            print(f"  regions:          {len(data.regions)}")
            print(f"  sequences:        {len(data.sequences)}")
            print(f"  sequence_entries: {len(data.sequence_entries)}")
            print(f"  enums:            {len(data.enums)}")
            print(f"  icloud_accounts:  {len(data.icloud_accounts)}")
            print(f"  icloud_photos:    {len(data.icloud_photos)}")
            print("sim_test: PASS")
        finally:
            wb.Close(SaveChanges=False)
            xl.Quit()


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from showbuilder.workbook_io import _WorkbookIoTest
    _WorkbookIoTest.sim_test()
