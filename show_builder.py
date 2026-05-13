"""show_builder.py -- re-export shim for versholn.importx consumers.

Allows sibling repos to do:
    versholn.importx("show_builder.ShowBuilderRouter")
    versholn.importx("show_builder.StaticFileServer")
    versholn.importx("show_builder.inject_sb_vba")
    etc.

versholn adds the show_builder repo root to sys.path, then imports this
module.  __getattr__ lazily loads the requested symbol from the flat modules
in the repo root (server.py, player.py, clips.py, etc.).
"""

import os
import sys

# Ensure this repo's root is on sys.path so the flat modules are importable.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_cache: dict = {}

# Maps exported symbol name → module filename (without .py)
_EXPORTS: dict[str, str] = {
    # excel_project
    "inject_sb_vba":        "excel_project",
    "_SB_RIBBON_TAB":       "excel_project",
    # static_server
    "StaticFileServer":     "static_server",
    # player
    "PlayerTargetManager":  "player",
    "PlayerController":     "player",
    # server
    "ShowBuilderRouter":    "server",
    # clips
    "SegmentCache":         "clips",
    "ClipPreloader":        "clips",
    # workbook_io
    "read_workbook":        "workbook_io",
    "_find_sheet":          "workbook_io",
    "_find_list_object":    "workbook_io",
    "_read_table":          "workbook_io",
    "_append_table_row":    "workbook_io",
    "find_table_row":       "workbook_io",
    "seed_workbook":        "workbook_io",
    "_str":                 "workbook_io",
    # schema
    "Asset":                "schema",
    "Format":               "schema",
    "Item":                 "schema",
    "Sequence":             "schema",
    "SequenceEntry":        "schema",
    "ShowbookData":         "schema",
    "TextSet":              "schema",
    "TextOverlay":          "schema",
    "Style":                "schema",
    # resolver
    "resolve":              "resolver",
    "build_show_json":      "resolver",
}


def __getattr__(name: str):
    if name in _EXPORTS:
        if name not in _cache:
            import importlib
            mod = importlib.import_module(_EXPORTS[name])
            _cache[name] = getattr(mod, name)
        return _cache[name]
    raise AttributeError(f"module 'show_builder' has no attribute {name!r}")
