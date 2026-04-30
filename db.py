"""showbuilder/db.py -- Direct SQLite read/write for ShowBuilder.

Replaces the workbook COM path for show definition data.
annotations.db (scene data) is a separate read-only snapshot; it is not
touched here.

Public API
----------
    read_db(path)              -> ShowbookData
    insert_asset(path, fields) -> asset_id
    insert_item(path, fields)  -> item_id
    insert_sequence(path, fields) -> sequence_id
    insert_sequence_entry(path, fields) -> sequence_entry_id
    patch_item(path, item_id, fields)
    patch_sequence(path, seq_id, fields)   -- patches top-level sequence cols only
    patch_sequence_entries(path, seq_id, op, **kw)  -- append / remove / reorder
    delete_item(path, item_id)
    delete_sequence_entry(path, se_id)
    DEFAULT_DB_PATH

All write functions open their own connection, commit, and close.
read_db() does the same.  Thread safety: SQLite WAL mode is not enforced here;
the server processes requests serially so single-connection-per-call is fine.
"""

import json
import os
import sqlite3
import uuid

from schema import (
    Asset, EnumRow, Format, ICloudAccount, ICloudPhoto,
    Item, Region, Sequence, SequenceEntry, ShowbookData,
    Style, TextOverlay, TextSet,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

DEFAULT_DB_PATH = os.path.join(_ROOT, "showbuilder.db")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _open(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# ID generator
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Coercion helpers (mirrors dump_wb._v / _fk)
# ---------------------------------------------------------------------------

def _b(v) -> bool:
    return bool(v)

def _s(v) -> str:
    return v if v is not None else ""

def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_db(path: str = DEFAULT_DB_PATH) -> ShowbookData:
    """Read all ShowBuilder tables from SQLite and return as ShowbookData."""
    con = _open(path)
    try:
        return ShowbookData(
            formats          = _read_formats(con),
            assets           = _read_assets(con),
            items            = _read_items(con),
            text_sets        = _read_text_sets(con),
            text_overlays    = _read_text_overlays(con),
            styles           = _read_styles(con),
            regions          = _read_regions(con),
            sequences        = _read_sequences(con),
            sequence_entries = _read_sequence_entries(con),
            enums            = _read_enums(con),
            icloud_accounts  = _read_icloud_accounts(con),
            icloud_photos    = _read_icloud_photos(con),
        )
    finally:
        con.close()


def _read_formats(con: sqlite3.Connection) -> list[Format]:
    return [
        Format(
            format_id  = _s(r["format_id"]),
            name       = _s(r["name"]),
            width_px   = _to_int(r["width_px"]),
            height_px  = _to_int(r["height_px"]),
            fps        = _to_float(r["fps"]),
            enabled    = _b(r["enabled"]),
            notes      = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM formats").fetchall()
    ]


def _read_assets(con: sqlite3.Connection) -> list[Asset]:
    return [
        Asset(
            asset_id            = _s(r["asset_id"]),
            asset_type          = _s(r["asset_type"]),
            src                 = _s(r["src"]),
            title               = _s(r["title"]),
            default_duration_ms = _to_int(r["default_duration_ms"]),
            metadata_json       = _s(r["metadata_json"]),
            enabled             = _b(r["enabled"]),
            notes               = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM assets").fetchall()
    ]


def _read_items(con: sqlite3.Connection) -> list[Item]:
    return [
        Item(
            item_id                    = _s(r["item_id"]),
            asset_id                   = _s(r["asset_id"] or ""),
            duration_ms                = _to_int(r["duration_ms"]),
            duration_mode              = _s(r["duration_mode"]),
            media_start_s              = _to_float(r["media_start_s"]),
            effect_name                = _s(r["effect_name"]),
            effect_params_json         = _s(r["effect_params_json"]),
            default_text_set_id        = _s(r["default_text_set_id"] or ""),
            region_id                  = _s(r["region_id"] or ""),
            style_class                = _s(r["style_class"] or ""),
            track_kind                 = _s(r["track_kind"]),
            media_audio_mode           = _s(r["media_audio_mode"]),
            media_audio_gain_db        = _to_float(r["media_audio_gain_db"]),
            z_order                    = _to_int(r["z_order"]),
            fit_mode                   = _s(r["fit_mode"]),
            transition_in              = _s(r["transition_in"]),
            transition_in_params_json  = _s(r["transition_in_params_json"]),
            transition_out             = _s(r["transition_out"]),
            transition_out_params_json = _s(r["transition_out_params_json"]),
            yt_freeze_at_s             = _to_float(r["yt_freeze_at_s"]),
            yt_freeze_duration_ms      = _to_int(r["yt_freeze_duration_ms"]),
            metadata_json              = _s(r["metadata_json"]),
            enabled                    = _b(r["enabled"]),
            notes                      = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM items").fetchall()
    ]


def _read_text_sets(con: sqlite3.Connection) -> list[TextSet]:
    return [
        TextSet(
            text_set_id   = _s(r["text_set_id"]),
            item_id       = _s(r["item_id"] or ""),
            text_set_name = _s(r["text_set_name"]),
            metadata_json = _s(r["metadata_json"]),
            enabled       = _b(r["enabled"]),
            notes         = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM text_sets").fetchall()
    ]


def _read_text_overlays(con: sqlite3.Connection) -> list[TextOverlay]:
    return [
        TextOverlay(
            text_id             = _s(r["text_id"]),
            text_set_id         = _s(r["text_set_id"] or ""),
            sequence_no         = _to_int(r["sequence_no"]),
            content             = _s(r["content"]),
            start_ms            = _to_int(r["start_ms"]),
            duration_ms         = _to_int(r["duration_ms"]),
            position_mode       = _s(r["position_mode"]),
            position_preset     = _s(r["position_preset"]),
            pos_x               = _to_float(r["pos_x"]),
            pos_y               = _to_float(r["pos_y"]),
            anchor              = _s(r["anchor"]),
            width_norm          = _to_float(r["width_norm"]),
            align               = _s(r["align"]),
            region_id           = _s(r["region_id"] or ""),
            effect_name         = _s(r["effect_name"]),
            effect_params_json  = _s(r["effect_params_json"]),
            style_class         = _s(r["style_class"] or ""),
            metadata_json       = _s(r["metadata_json"]),
            enabled             = _b(r["enabled"]),
            notes               = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM text_overlays").fetchall()
    ]


def _read_styles(con: sqlite3.Connection) -> list[Style]:
    return [
        Style(
            style_class      = _s(r["style_class"]),
            font_family      = _s(r["font_family"]),
            font_size_px     = _to_int(r["font_size_px"]),
            font_weight      = _s(r["font_weight"]),
            color            = _s(r["color"]),
            bg_color         = _s(r["bg_color"]),
            padding_px       = _to_int(r["padding_px"]),
            border_radius_px = _to_int(r["border_radius_px"]),
            text_shadow      = _s(r["text_shadow"]),
            metadata_json    = _s(r["metadata_json"]),
            enabled          = _b(r["enabled"]),
            notes            = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM styles").fetchall()
    ]


def _read_regions(con: sqlite3.Connection) -> list[Region]:
    return [
        Region(
            region_id     = _s(r["region_id"]),
            x             = _to_float(r["x"]),
            y             = _to_float(r["y"]),
            w             = _to_float(r["w"]),
            h             = _to_float(r["h"]),
            anchor        = _s(r["anchor"]),
            metadata_json = _s(r["metadata_json"]),
            enabled       = _b(r["enabled"]),
            notes         = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM regions").fetchall()
    ]


def _read_sequences(con: sqlite3.Connection) -> list[Sequence]:
    return [
        Sequence(
            sequence_id   = _s(r["sequence_id"]),
            sequence_name = _s(r["sequence_name"]),
            sequence_type = _s(r["sequence_type"]),
            format_id     = _s(r["format_id"] or ""),
            timing_mode   = _s(r["timing_mode"]),
            description   = _s(r["description"]),
            metadata_json = _s(r["metadata_json"]),
            enabled       = _b(r["enabled"]),
        )
        for r in con.execute("SELECT * FROM sequences").fetchall()
    ]


def _read_sequence_entries(con: sqlite3.Connection) -> list[SequenceEntry]:
    return [
        SequenceEntry(
            sequence_entry_id          = _s(r["sequence_entry_id"]),
            sequence_id                = _s(r["sequence_id"]),
            sequence_no                = _to_int(r["sequence_no"]),
            entry_type                 = _s(r["entry_type"]),
            target_id                  = _s(r["target_id"]),
            track_kind                 = _s(r["track_kind"]),
            local_start_ms             = _to_int(r["local_start_ms"]),
            override_duration_ms       = _to_int(r["override_duration_ms"]),
            override_media_start_s     = _to_float(r["override_media_start_s"]),
            override_effect_name       = _s(r["override_effect_name"]),
            override_effect_params_json = _s(r["override_effect_params_json"]),
            override_text_set_id       = _s(r["override_text_set_id"] or ""),
            override_z_order           = _to_int(r["override_z_order"]),
            override_style_class       = _s(r["override_style_class"] or ""),
            metadata_json              = _s(r["metadata_json"]),
            enabled                    = _b(r["enabled"]),
            notes                      = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM sequence_entries").fetchall()
    ]


def _read_enums(con: sqlite3.Connection) -> list[EnumRow]:
    return [
        EnumRow(
            enum_type = _s(r["enum_type"]),
            value     = _s(r["value"]),
            label     = _s(r["label"]),
            notes     = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM enums").fetchall()
    ]


def _read_icloud_accounts(con: sqlite3.Connection) -> list[ICloudAccount]:
    return [
        ICloudAccount(
            account_alias = _s(r["account_alias"]),
            apple_id      = _s(r["apple_id"]),
            enabled       = _b(r["enabled"]),
            notes         = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM icloud_accounts").fetchall()
    ]


def _read_icloud_photos(con: sqlite3.Connection) -> list[ICloudPhoto]:
    return [
        ICloudPhoto(
            icloud_photo_id = _s(r["icloud_photo_id"]),
            account_alias   = _s(r["account_alias"] or ""),
            filename        = _s(r["filename"]),
            created_date    = _s(r["created_date"]),
            media_type      = _s(r["media_type"]),
            album           = _s(r["album"]),
            local_path      = _s(r["local_path"]),
            local_hash      = _s(r["local_hash"]),
            asset_id        = _s(r["asset_id"] or ""),
            last_synced     = _s(r["last_synced"]),
            notes           = _s(r["notes"]),
        )
        for r in con.execute("SELECT * FROM icloud_photos").fetchall()
    ]


# ---------------------------------------------------------------------------
# Write -- assets
# ---------------------------------------------------------------------------

def insert_asset(path: str, fields: dict) -> str:
    """Insert a new asset row.  Returns the asset_id used."""
    asset_id = fields.get("asset_id") or _new_id("A")
    con = _open(path)
    with con:
        con.execute(
            "INSERT INTO assets "
            "(asset_id, asset_type, src, title, default_duration_ms, metadata_json, enabled, notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                asset_id,
                fields.get("asset_type", "video"),
                fields.get("src", ""),
                fields.get("title", ""),
                fields.get("default_duration_ms"),
                fields.get("metadata_json", "{}"),
                1 if fields.get("enabled", True) else 0,
                fields.get("notes", ""),
            ),
        )
    con.close()
    return asset_id


def patch_asset(path: str, asset_id: str, fields: dict) -> None:
    """UPDATE allowed asset columns.  Silently ignores unknown keys."""
    _ALLOWED = {"asset_type", "src", "title", "default_duration_ms",
                "metadata_json", "enabled", "notes"}
    _patch(path, "assets", "asset_id", asset_id, fields, _ALLOWED)


# ---------------------------------------------------------------------------
# Write -- items
# ---------------------------------------------------------------------------

def insert_item(path: str, fields: dict) -> str:
    """Insert a new item row.  Returns the item_id used."""
    item_id = fields.get("item_id") or _new_id("I")
    con = _open(path)
    with con:
        con.execute(
            "INSERT INTO items "
            "(item_id, asset_id, duration_ms, duration_mode, media_start_s, "
            " effect_name, effect_params_json, default_text_set_id, region_id, "
            " style_class, track_kind, media_audio_mode, media_audio_gain_db, "
            " z_order, fit_mode, transition_in, transition_in_params_json, "
            " transition_out, transition_out_params_json, yt_freeze_at_s, "
            " yt_freeze_duration_ms, metadata_json, enabled, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item_id,
                fields.get("asset_id") or None,
                fields.get("duration_ms"),
                fields.get("duration_mode", "fixed"),
                fields.get("media_start_s"),
                fields.get("effect_name", "none"),
                fields.get("effect_params_json", "{}"),
                fields.get("default_text_set_id") or None,
                fields.get("region_id") or None,
                fields.get("style_class") or None,
                fields.get("track_kind", "video"),
                fields.get("media_audio_mode", "none"),
                fields.get("media_audio_gain_db"),
                fields.get("z_order"),
                fields.get("fit_mode", "cover"),
                fields.get("transition_in", "none"),
                fields.get("transition_in_params_json", "{}"),
                fields.get("transition_out", "none"),
                fields.get("transition_out_params_json", "{}"),
                fields.get("yt_freeze_at_s"),
                fields.get("yt_freeze_duration_ms"),
                fields.get("metadata_json", "{}"),
                1 if fields.get("enabled", True) else 0,
                fields.get("notes", ""),
            ),
        )
    con.close()
    return item_id


def patch_item(path: str, item_id: str, fields: dict) -> None:
    """UPDATE allowed item columns."""
    _ALLOWED = {
        "asset_id", "duration_ms", "duration_mode", "media_start_s",
        "effect_name", "effect_params_json", "region_id", "style_class",
        "track_kind", "media_audio_mode", "media_audio_gain_db", "z_order",
        "fit_mode", "transition_in", "transition_in_params_json",
        "transition_out", "transition_out_params_json",
        "yt_freeze_at_s", "yt_freeze_duration_ms", "metadata_json",
        "enabled", "notes",
    }
    _patch(path, "items", "item_id", item_id, fields, _ALLOWED)


def delete_item(path: str, item_id: str) -> None:
    """Delete an item row (and cascade-remove sequence_entries if FK enabled)."""
    con = _open(path)
    with con:
        con.execute("DELETE FROM items WHERE item_id = ?", (item_id,))
    con.close()


# ---------------------------------------------------------------------------
# Write -- sequences
# ---------------------------------------------------------------------------

def insert_sequence(path: str, fields: dict) -> str:
    """Insert a new sequence row.  Returns the sequence_id used."""
    seq_id = fields.get("sequence_id") or _new_id("SQ")
    con = _open(path)
    with con:
        con.execute(
            "INSERT INTO sequences "
            "(sequence_id, sequence_name, sequence_type, format_id, "
            " timing_mode, description, metadata_json, enabled) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                seq_id,
                fields.get("sequence_name", ""),
                fields.get("sequence_type", "show"),
                fields.get("format_id") or None,
                fields.get("timing_mode", "serial"),
                fields.get("description", ""),
                fields.get("metadata_json", "{}"),
                1 if fields.get("enabled", True) else 0,
            ),
        )
    con.close()
    return seq_id


def patch_sequence(path: str, seq_id: str, fields: dict) -> None:
    """UPDATE top-level sequence columns (not entries)."""
    _ALLOWED = {"sequence_name", "sequence_type", "format_id",
                "timing_mode", "description", "metadata_json", "enabled"}
    _patch(path, "sequences", "sequence_id", seq_id, fields, _ALLOWED)


# ---------------------------------------------------------------------------
# Write -- sequence_entries
# ---------------------------------------------------------------------------

def insert_sequence_entry(path: str, fields: dict) -> str:
    """Insert a new sequence_entry row.  Returns the sequence_entry_id used."""
    se_id = fields.get("sequence_entry_id") or _new_id("SE")
    con = _open(path)
    with con:
        con.execute(
            "INSERT INTO sequence_entries "
            "(sequence_entry_id, sequence_id, sequence_no, entry_type, "
            " target_id, track_kind, local_start_ms, override_duration_ms, "
            " override_media_start_s, override_effect_name, "
            " override_effect_params_json, override_text_set_id, "
            " override_z_order, override_style_class, metadata_json, "
            " enabled, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                se_id,
                fields.get("sequence_id"),
                fields.get("sequence_no"),
                fields.get("entry_type", "item"),
                fields.get("target_id"),
                fields.get("track_kind", "video"),
                fields.get("local_start_ms"),
                fields.get("override_duration_ms"),
                fields.get("override_media_start_s"),
                fields.get("override_effect_name", ""),
                fields.get("override_effect_params_json", "{}"),
                fields.get("override_text_set_id") or None,
                fields.get("override_z_order"),
                fields.get("override_style_class") or None,
                fields.get("metadata_json", "{}"),
                1 if fields.get("enabled", True) else 0,
                fields.get("notes", ""),
            ),
        )
    con.close()
    return se_id


def delete_sequence_entry(path: str, se_id: str) -> None:
    con = _open(path)
    with con:
        con.execute(
            "DELETE FROM sequence_entries WHERE sequence_entry_id = ?", (se_id,)
        )
    con.close()


def patch_sequence_entries(path: str, seq_id: str, op: str, **kw) -> dict:
    """Mutate the entry list for a sequence.

    op="append"   kw: item_id, sequence_no (optional; auto-appended if absent)
    op="remove"   kw: sequence_entry_id
    op="reorder"  kw: order=[{"sequence_entry_id": ..., "sequence_no": N}, ...]

    Returns {"ok": True, ...} or raises ValueError on bad input.
    """
    if op == "append":
        item_id = kw.get("item_id")
        if not item_id:
            raise ValueError("append requires item_id")
        seq_no = kw.get("sequence_no")
        if seq_no is None:
            con = _open(path)
            row = con.execute(
                "SELECT MAX(sequence_no) FROM sequence_entries WHERE sequence_id=?",
                (seq_id,),
            ).fetchone()
            con.close()
            seq_no = (row[0] or 0) + 1
        se_id = insert_sequence_entry(path, {
            "sequence_id": seq_id,
            "sequence_no": seq_no,
            "entry_type": "item",
            "target_id": item_id,
        })
        return {"ok": True, "sequence_entry_id": se_id, "sequence_no": seq_no}

    if op == "remove":
        se_id = kw.get("sequence_entry_id")
        if not se_id:
            raise ValueError("remove requires sequence_entry_id")
        delete_sequence_entry(path, se_id)
        return {"ok": True}

    if op == "reorder":
        order = kw.get("order", [])
        con = _open(path)
        with con:
            for entry in order:
                con.execute(
                    "UPDATE sequence_entries SET sequence_no=? "
                    "WHERE sequence_entry_id=? AND sequence_id=?",
                    (entry["sequence_no"], entry["sequence_entry_id"], seq_id),
                )
        con.close()
        return {"ok": True}

    raise ValueError(f"unknown op: {op!r}")


# ---------------------------------------------------------------------------
# Generic UPDATE helper
# ---------------------------------------------------------------------------

def _patch(path: str, table: str, pk_col: str, pk_val: str,
           fields: dict, allowed: set) -> None:
    cols = {k: v for k, v in fields.items() if k in allowed}
    if not cols:
        return
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    values = list(cols.values()) + [pk_val]
    con = _open(path)
    with con:
        con.execute(
            f"UPDATE {table} SET {set_clause} WHERE {pk_col} = ?",
            values,
        )
    con.close()
