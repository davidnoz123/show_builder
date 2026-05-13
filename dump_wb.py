"""dump_wb.py -- Snapshot the ShowBuilder workbook into SQLite.

Attaches to the running Excel instance, reads all ShowBuilder ListObjects
via read_workbook(), and writes a typed SQLite snapshot with PKs, FKs,
UNIQUE constraints, CHECK constraints, and indexes.

The database is always dropped and recreated -- it is a query cache, not a
write-back store.  Source of truth is always the Excel workbook.

Schema is defined in schema.sql (single source of truth).
Validators derived from the schema live in codegen.py.

Run with:
    C:\\analytics\\projects\\git\\lexi\\demos\\venv\\Scripts\\python.exe dump_wb.py [--db PATH]

Default output: <workspace>/showbuilder.db
"""

import os
import sys
import sqlite3
import argparse

_log = lambda msg: print(msg, file=sys.stderr)

# ---------------------------------------------------------------------------
# Schema DDL -- loaded from schema.sql at runtime
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_SQL = os.path.join(_HERE, "schema.sql")

# ---------------------------------------------------------------------------
# Drop order (reverse FK dependency)
# ---------------------------------------------------------------------------

_DROP_ORDER = [
    "icloud_photos",
    "icloud_accounts",
    "enums",
    "sequence_entries",
    "sequences",
    "text_overlays",
    "text_sets",
    "items",
    "styles",
    "regions",
    "assets",
    "formats",
]

# ---------------------------------------------------------------------------
# Helper: coerce None → None, bool → 0/1
# ---------------------------------------------------------------------------

def _v(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _fk(value):
    """Like _v() but converts empty string to NULL -- for nullable FK columns."""
    v = _v(value)
    if v == "":
        return None
    return v


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def dump(wb_path: str, db_path: str) -> None:
    # ---- Attach to running Excel ----
    try:
        import win32com.client as wc
    except ImportError:
        sys.exit("pywin32 not installed -- run inside the project venv")

    abs_wb = os.path.normcase(os.path.abspath(wb_path))
    try:
        xl = wc.GetActiveObject("Excel.Application")
    except Exception:
        sys.exit("Excel is not running.  Open 8mm_database.xlsm first.")

    wb = None
    for i in range(1, xl.Workbooks.Count + 1):
        if os.path.normcase(xl.Workbooks(i).FullName) == abs_wb:
            wb = xl.Workbooks(i)
            break
    if wb is None:
        sys.exit(f"Workbook not open: {wb_path}\nOpen it in Excel first.")

    # ---- Read via workbook_io ----
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)

    from workbook_io import read_workbook
    print("Reading workbook...")
    data = read_workbook(wb)
    print(f"  formats={len(data.formats)}  assets={len(data.assets)}  "
          f"items={len(data.items)}  sequences={len(data.sequences)}  "
          f"seq_entries={len(data.sequence_entries)}")

    # ---- Build SQLite ----
    print(f"Writing {db_path} ...")
    con = sqlite3.connect(db_path)

    # Drop all tables in reverse FK order, then recreate schema.
    # executescript() handles multi-statement DDL correctly and auto-commits.
    ddl = open(_SCHEMA_SQL, encoding="utf-8").read()
    drop_stmts = "\n".join(f"DROP TABLE IF EXISTS {t};" for t in _DROP_ORDER)
    con.executescript(drop_stmts + "\n" + ddl)

    # Insert all data in one transaction.
    con.execute("PRAGMA foreign_keys = ON")
    with con:

        # ---- Insert rows ----

        con.executemany(
            "INSERT INTO formats VALUES (?,?,?,?,?,?,?)",
            [(_v(r.format_id), _v(r.name), _v(r.width_px), _v(r.height_px),
              _v(r.fps), _v(r.enabled), _v(r.notes))
             for r in data.formats],
        )

        con.executemany(
            "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)",
            [(_v(r.asset_id), _v(r.asset_type), _v(r.src), _v(r.title),
              _v(r.default_duration_ms), _v(r.metadata_json), _v(r.enabled), _v(r.notes))
             for r in data.assets],
        )

        con.executemany(
            "INSERT INTO styles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(_v(r.style_class), _v(r.font_family), _v(r.font_size_px), _v(r.font_weight),
              _v(r.color), _v(r.bg_color), _v(r.padding_px), _v(r.border_radius_px),
              _v(r.text_shadow), _v(r.metadata_json), _v(r.enabled), _v(r.notes))
             for r in data.styles],
        )

        con.executemany(
            "INSERT INTO regions VALUES (?,?,?,?,?,?,?,?,?)",
            [(_v(r.region_id), _v(r.x), _v(r.y), _v(r.w), _v(r.h),
              _v(r.anchor), _v(r.metadata_json), _v(r.enabled), _v(r.notes))
             for r in data.regions],
        )

        con.executemany(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(_v(r.item_id), _fk(r.asset_id), _v(r.duration_ms), _v(r.duration_mode),
              _v(r.media_start_s), _v(r.effect_name), _v(r.effect_params_json),
              _fk(r.default_text_set_id), _fk(r.region_id), _fk(r.style_class),
              _v(r.track_kind), _v(r.media_audio_mode), _v(r.media_audio_gain_db),
              _v(r.z_order), _v(r.fit_mode), _v(r.transition_in),
              _v(r.transition_in_params_json), _v(r.transition_out),
              _v(r.transition_out_params_json), _v(r.yt_freeze_at_s),
              _v(r.yt_freeze_duration_ms), _v(r.metadata_json),
              _v(r.enabled), _v(r.notes))
             for r in data.items],
        )

        con.executemany(
            "INSERT INTO text_sets VALUES (?,?,?,?,?,?)",
            [(_v(r.text_set_id), _fk(r.item_id), _v(r.text_set_name),
              _v(r.metadata_json), _v(r.enabled), _v(r.notes))
             for r in data.text_sets],
        )

        con.executemany(
            "INSERT INTO text_overlays VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(_v(r.text_id), _fk(r.text_set_id), _v(r.sequence_no), _v(r.content),
              _v(r.start_ms), _v(r.duration_ms), _v(r.position_mode),
              _v(r.position_preset), _v(r.pos_x), _v(r.pos_y), _v(r.anchor),
              _v(r.width_norm), _v(r.align), _fk(r.region_id), _v(r.effect_name),
              _v(r.effect_params_json), _fk(r.style_class), _v(r.metadata_json),
              _v(r.enabled), _v(r.notes))
             for r in data.text_overlays],
        )

        con.executemany(
            "INSERT INTO sequences VALUES (?,?,?,?,?,?,?,?)",
            [(_v(r.sequence_id), _v(r.sequence_name), _v(r.sequence_type),
              _fk(r.format_id), _v(r.timing_mode), _v(r.description),
              _v(r.metadata_json), _v(r.enabled))
             for r in data.sequences],
        )

        con.executemany(
            "INSERT INTO sequence_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(_v(r.sequence_entry_id), _v(r.sequence_id), _v(r.sequence_no),
              _v(r.entry_type), _v(r.target_id), _v(r.track_kind),
              _v(r.local_start_ms), _v(r.override_duration_ms),
              _v(r.override_media_start_s), _v(r.override_effect_name),
              _v(r.override_effect_params_json), _v(r.override_text_set_id),
              _v(r.override_z_order), _v(r.override_style_class),
              _v(r.metadata_json), _v(r.enabled), _v(r.notes))
             for r in data.sequence_entries],
        )

        con.executemany(
            "INSERT INTO enums VALUES (?,?,?,?)",
            [(_v(r.enum_type), _v(r.value), _v(r.label), _v(r.notes))
             for r in data.enums],
        )

        con.executemany(
            "INSERT INTO icloud_accounts VALUES (?,?,?,?)",
            [(_v(r.account_alias), _v(r.apple_id), _v(r.enabled), _v(r.notes))
             for r in data.icloud_accounts],
        )

        con.executemany(
            "INSERT INTO icloud_photos VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(_v(r.icloud_photo_id), _fk(r.account_alias), _v(r.filename),
              _v(r.created_date), _v(r.media_type), _v(r.album),
              _v(r.local_path), _v(r.local_hash), _fk(r.asset_id),
              _v(r.last_synced), _v(r.notes))
             for r in data.icloud_photos],
        )

    con.close()
    print(f"Done.  {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot ShowBuilder workbook to SQLite")
    _here = os.path.dirname(os.path.abspath(__file__))
    _default_wb = os.path.join(os.path.dirname(_here), "8mm_database.xlsm")
    _default_db = os.path.join(os.path.dirname(_here), "showbuilder.db")
    parser.add_argument(
        "--wb",
        default=_default_wb,
        help="Path to the Excel workbook (must be open in Excel)",
    )
    parser.add_argument(
        "--db",
        default=_default_db,
        help="Output SQLite database path",
    )
    args = parser.parse_args()
    try:
        dump(args.wb, args.db)
    except SystemExit:
        raise
    except Exception:
        import traceback
        _log(f"FATAL unhandled exception:\n{traceback.format_exc()}")
        raise
