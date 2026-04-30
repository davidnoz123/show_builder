"""showbuilder/validator.py -- Validates a ShowbookData instance.

Public API:
    validate(data: ShowbookData) -> list[ValidationIssue]

Each issue has:
    table    -- sheet name (e.g. "Items")
    row_id   -- primary-key value identifying the row
    field    -- column name, or "" for row-level issues
    message  -- human-readable description
    severity -- "error" | "warning"

Checks performed:
    - unique, non-empty primary keys per table
    - required foreign keys resolve
    - enum field values are in the seeded vocabulary
    - JSON fields parse correctly when populated
    - numeric constraints (duration_ms > 0, start_ms >= 0, normalised 0..1)
    - position_mode consistency (preset requires position_preset;
      coords requires pos_x, pos_y, anchor)
    - region_id, if set, supersedes position_mode coordinates (warning if both present)
    - cycle detection in Sequences via SequenceEntries
"""

from dataclasses import dataclass
import json

from schema import ShowbookData


# ---------------------------------------------------------------------------
# ValidationIssue
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    table:    str
    row_id:   str
    field:    str
    message:  str
    severity: str   # "error" | "warning"

    def __str__(self) -> str:
        loc = f"{self.table}[{self.row_id}]"
        if self.field:
            loc += f".{self.field}"
        return f"[{self.severity.upper()}] {loc}: {self.message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(issues: list, table: str, row_id: str, field: str, msg: str) -> None:
    issues.append(ValidationIssue(table, row_id, field, msg, "error"))


def _warn(issues: list, table: str, row_id: str, field: str, msg: str) -> None:
    issues.append(ValidationIssue(table, row_id, field, msg, "warning"))


def _check_json(issues: list, table: str, row_id: str, field: str, value: str) -> None:
    if not value:
        return
    try:
        json.loads(value)
    except (json.JSONDecodeError, ValueError):
        _err(issues, table, row_id, field, f"invalid JSON: {value!r}")


def _norm_check(issues: list, table: str, row_id: str, field: str, value) -> None:
    """Warn if a supposed normalised float is outside 0..1."""
    if value is None:
        return
    if value < 0 or value > 1:
        _err(issues, table, row_id, field, f"normalised value out of range: {value}")


def _build_enum_sets(enum_rows) -> dict[str, set[str]]:
    """Return {enum_type: {value, ...}} from the Enums table."""
    sets: dict[str, set[str]] = {}
    for row in enum_rows:
        if row.enum_type:
            sets.setdefault(row.enum_type, set()).add(row.value)
    return sets


def _check_enum(issues: list, enum_sets: dict, table: str, row_id: str,
                field: str, value: str, enum_type: str) -> None:
    if not value:
        return
    allowed = enum_sets.get(enum_type)
    if allowed is None:
        return   # enum_type not seeded -- skip rather than false-positive
    if value not in allowed:
        _err(issues, table, row_id, field,
             f"unknown {enum_type} value: {value!r}  (allowed: {sorted(allowed)})")


def _unique_ids(issues: list, table: str, rows, id_attr: str) -> set[str]:
    """Check id_attr is non-empty and unique.  Returns the valid ID set."""
    seen: set[str] = set()
    valid: set[str] = set()
    for row in rows:
        pk = getattr(row, id_attr, "")
        if not pk:
            _err(issues, table, "", id_attr, f"row has empty {id_attr}")
            continue
        if pk in seen:
            _err(issues, table, pk, id_attr, f"duplicate {id_attr}: {pk!r}")
        else:
            seen.add(pk)
            valid.add(pk)
    return valid


def _fk(issues: list, table: str, row_id: str, field: str,
        value: str, ref_ids: set[str], required: bool = True) -> None:
    if not value:
        if required:
            _err(issues, table, row_id, field, "required foreign key is empty")
        return
    if value not in ref_ids:
        _err(issues, table, row_id, field, f"unresolved reference: {value!r}")


# ---------------------------------------------------------------------------
# Per-table checks
# ---------------------------------------------------------------------------

def _check_formats(data: ShowbookData, issues: list, enums: dict) -> set[str]:
    ids = _unique_ids(issues, "Formats", data.formats, "format_id")
    for f in data.formats:
        rid = f.format_id
        if f.width_px is not None and f.width_px <= 0:
            _err(issues, "Formats", rid, "width_px", "must be > 0")
        if f.height_px is not None and f.height_px <= 0:
            _err(issues, "Formats", rid, "height_px", "must be > 0")
        if f.fps is not None and f.fps <= 0:
            _err(issues, "Formats", rid, "fps", "must be > 0")
    return ids


def _check_assets(data: ShowbookData, issues: list, enums: dict) -> set[str]:
    ids = _unique_ids(issues, "Assets", data.assets, "asset_id")
    for a in data.assets:
        rid = a.asset_id
        _check_enum(issues, enums, "Assets", rid, "asset_type", a.asset_type, "asset_type")
        if not a.src:
            _err(issues, "Assets", rid, "src", "src is required")
        if not a.asset_type:
            _err(issues, "Assets", rid, "asset_type", "asset_type is required")
        _check_json(issues, "Assets", rid, "metadata_json", a.metadata_json)
    return ids


def _check_items(data: ShowbookData, issues: list, enums: dict,
                 asset_ids: set[str], text_set_ids: set[str],
                 region_ids: set[str], style_classes: set[str]) -> set[str]:
    ids = _unique_ids(issues, "Items", data.items, "item_id")
    for it in data.items:
        rid = it.item_id
        _fk(issues, "Items", rid, "asset_id", it.asset_id, asset_ids)
        if it.default_text_set_id:
            _fk(issues, "Items", rid, "default_text_set_id",
                it.default_text_set_id, text_set_ids, required=False)
        if it.region_id:
            _fk(issues, "Items", rid, "region_id",
                it.region_id, region_ids, required=False)
        if it.style_class:
            _fk(issues, "Items", rid, "style_class",
                it.style_class, style_classes, required=False)
        _check_enum(issues, enums, "Items", rid, "duration_mode", it.duration_mode, "duration_mode")
        _check_enum(issues, enums, "Items", rid, "track_kind", it.track_kind, "track_kind")
        _check_enum(issues, enums, "Items", rid, "media_audio_mode", it.media_audio_mode, "media_audio_mode")
        _check_enum(issues, enums, "Items", rid, "fit_mode", it.fit_mode, "fit_mode")
        if it.duration_ms is not None and it.duration_ms <= 0:
            _err(issues, "Items", rid, "duration_ms", "must be > 0")
        if it.z_order is not None and it.z_order < 0:
            _warn(issues, "Items", rid, "z_order", "negative z_order is unusual")
        _check_json(issues, "Items", rid, "effect_params_json", it.effect_params_json)
        _check_json(issues, "Items", rid, "transition_in_params_json", it.transition_in_params_json)
        _check_json(issues, "Items", rid, "transition_out_params_json", it.transition_out_params_json)
        _check_json(issues, "Items", rid, "metadata_json", it.metadata_json)
    return ids


def _check_text_sets(data: ShowbookData, issues: list, item_ids: set[str]) -> set[str]:
    ids = _unique_ids(issues, "TextSets", data.text_sets, "text_set_id")
    for ts in data.text_sets:
        rid = ts.text_set_id
        _fk(issues, "TextSets", rid, "item_id", ts.item_id, item_ids)
        _check_json(issues, "TextSets", rid, "metadata_json", ts.metadata_json)
    return ids


def _check_text_overlays(data: ShowbookData, issues: list, enums: dict,
                         text_set_ids: set[str], region_ids: set[str],
                         style_classes: set[str]) -> set[str]:
    ids = _unique_ids(issues, "TextOverlays", data.text_overlays, "text_id")
    for ov in data.text_overlays:
        rid = ov.text_id
        _fk(issues, "TextOverlays", rid, "text_set_id", ov.text_set_id, text_set_ids)
        if ov.region_id:
            _fk(issues, "TextOverlays", rid, "region_id",
                ov.region_id, region_ids, required=False)
            # Warn if region_id is set alongside explicit position coords
            if ov.position_mode == "coords" and (ov.pos_x is not None or ov.pos_y is not None):
                _warn(issues, "TextOverlays", rid, "region_id",
                      "region_id is set alongside position_mode=coords; region_id takes precedence")
        if ov.style_class:
            _fk(issues, "TextOverlays", rid, "style_class",
                ov.style_class, style_classes, required=False)
        _check_enum(issues, enums, "TextOverlays", rid, "position_mode", ov.position_mode, "position_mode")
        _check_enum(issues, enums, "TextOverlays", rid, "align", ov.align, "align")
        _check_enum(issues, enums, "TextOverlays", rid, "anchor", ov.anchor, "anchor")

        if ov.position_mode == "preset":
            _check_enum(issues, enums, "TextOverlays", rid, "position_preset",
                        ov.position_preset, "position_preset")
            if not ov.position_preset:
                _err(issues, "TextOverlays", rid, "position_preset",
                     "required when position_mode=preset")
        elif ov.position_mode == "coords":
            if ov.pos_x is None:
                _err(issues, "TextOverlays", rid, "pos_x",
                     "required when position_mode=coords")
            if ov.pos_y is None:
                _err(issues, "TextOverlays", rid, "pos_y",
                     "required when position_mode=coords")
            if not ov.anchor:
                _err(issues, "TextOverlays", rid, "anchor",
                     "required when position_mode=coords")

        _norm_check(issues, "TextOverlays", rid, "pos_x", ov.pos_x)
        _norm_check(issues, "TextOverlays", rid, "pos_y", ov.pos_y)
        _norm_check(issues, "TextOverlays", rid, "width_norm", ov.width_norm)

        if ov.start_ms is not None and ov.start_ms < 0:
            _err(issues, "TextOverlays", rid, "start_ms", "must be >= 0")
        if ov.duration_ms is not None and ov.duration_ms <= 0:
            _err(issues, "TextOverlays", rid, "duration_ms", "must be > 0")
        _check_json(issues, "TextOverlays", rid, "effect_params_json", ov.effect_params_json)
        _check_json(issues, "TextOverlays", rid, "metadata_json", ov.metadata_json)
    return ids


def _check_styles(data: ShowbookData, issues: list) -> set[str]:
    ids = _unique_ids(issues, "Styles", data.styles, "style_class")
    for s in data.styles:
        rid = s.style_class
        if s.font_size_px is not None and s.font_size_px <= 0:
            _err(issues, "Styles", rid, "font_size_px", "must be > 0")
        if s.padding_px is not None and s.padding_px < 0:
            _err(issues, "Styles", rid, "padding_px", "must be >= 0")
        if s.border_radius_px is not None and s.border_radius_px < 0:
            _err(issues, "Styles", rid, "border_radius_px", "must be >= 0")
        _check_json(issues, "Styles", rid, "metadata_json", s.metadata_json)
    return ids


def _check_regions(data: ShowbookData, issues: list, enums: dict) -> set[str]:
    ids = _unique_ids(issues, "Regions", data.regions, "region_id")
    for r in data.regions:
        rid = r.region_id
        _norm_check(issues, "Regions", rid, "x", r.x)
        _norm_check(issues, "Regions", rid, "y", r.y)
        _norm_check(issues, "Regions", rid, "w", r.w)
        _norm_check(issues, "Regions", rid, "h", r.h)
        _check_enum(issues, enums, "Regions", rid, "anchor", r.anchor, "anchor")
        _check_json(issues, "Regions", rid, "metadata_json", r.metadata_json)
    return ids


def _check_sequences(data: ShowbookData, issues: list, enums: dict,
                     format_ids: set[str]) -> set[str]:
    ids = _unique_ids(issues, "Sequences", data.sequences, "sequence_id")
    for s in data.sequences:
        rid = s.sequence_id
        if s.format_id:
            _fk(issues, "Sequences", rid, "format_id",
                s.format_id, format_ids, required=False)
        _check_enum(issues, enums, "Sequences", rid, "sequence_type", s.sequence_type, "sequence_type")
        _check_enum(issues, enums, "Sequences", rid, "timing_mode", s.timing_mode, "timing_mode")
        if not s.timing_mode:
            _err(issues, "Sequences", rid, "timing_mode", "timing_mode is required")
        _check_json(issues, "Sequences", rid, "metadata_json", s.metadata_json)
    return ids


def _check_sequence_entries(data: ShowbookData, issues: list, enums: dict,
                             sequence_ids: set[str], item_ids: set[str],
                             style_classes: set[str]) -> set[str]:
    ids = _unique_ids(issues, "SequenceEntries", data.sequence_entries, "sequence_entry_id")
    for se in data.sequence_entries:
        rid = se.sequence_entry_id
        _fk(issues, "SequenceEntries", rid, "sequence_id", se.sequence_id, sequence_ids)
        _check_enum(issues, enums, "SequenceEntries", rid, "entry_type", se.entry_type, "entry_type")
        _check_enum(issues, enums, "SequenceEntries", rid, "track_kind", se.track_kind, "track_kind")

        if se.entry_type == "item":
            _fk(issues, "SequenceEntries", rid, "target_id", se.target_id, item_ids)
        elif se.entry_type == "sequence":
            _fk(issues, "SequenceEntries", rid, "target_id", se.target_id, sequence_ids)
        elif se.entry_type:
            _err(issues, "SequenceEntries", rid, "entry_type",
                 f"unknown entry_type: {se.entry_type!r}")

        if se.sequence_no is not None and se.sequence_no < 1:
            _err(issues, "SequenceEntries", rid, "sequence_no", "must be >= 1")
        if se.override_duration_ms is not None and se.override_duration_ms <= 0:
            _err(issues, "SequenceEntries", rid, "override_duration_ms", "must be > 0")
        if se.override_z_order is not None and se.override_z_order < 0:
            _warn(issues, "SequenceEntries", rid, "override_z_order", "negative z_order is unusual")
        if se.override_style_class:
            _fk(issues, "SequenceEntries", rid, "override_style_class",
                se.override_style_class, style_classes, required=False)
        _check_json(issues, "SequenceEntries", rid, "override_effect_params_json",
                    se.override_effect_params_json)
        _check_json(issues, "SequenceEntries", rid, "metadata_json", se.metadata_json)
    return ids


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def _check_cycles(data: ShowbookData, issues: list) -> None:
    """DFS cycle detection over nested sequence references."""
    # Build adjacency: sequence_id -> [child sequence_ids]
    adj: dict[str, list[str]] = {s.sequence_id: [] for s in data.sequences}
    for se in data.sequence_entries:
        if se.entry_type == "sequence" and se.sequence_id in adj and se.target_id:
            adj[se.sequence_id].append(se.target_id)

    visited:  set[str] = set()
    in_stack: set[str] = set()

    def dfs(node: str) -> bool:
        if node in in_stack:
            return True   # cycle
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for child in adj.get(node, []):
            if dfs(child):
                return True
        in_stack.discard(node)
        return False

    for seq_id in adj:
        if seq_id not in visited:
            if dfs(seq_id):
                _err(issues, "Sequences", seq_id, "",
                     "cyclic sequence reference detected")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate(data: ShowbookData) -> list[ValidationIssue]:
    """Validate a ShowbookData instance.  Returns all issues found."""
    issues: list[ValidationIssue] = []
    enums = _build_enum_sets(data.enums)

    # Pass 1: build ID sets (ordering matters -- Items needs asset_ids etc.)
    format_ids    = _check_formats(data, issues, enums)
    asset_ids     = _check_assets(data, issues, enums)
    style_classes = _check_styles(data, issues)
    region_ids    = _check_regions(data, issues, enums)
    sequence_ids  = _check_sequences(data, issues, enums, format_ids)

    # TextSets needs item_ids, but item_ids needs text_set_ids -- bootstrap
    # the item pass without text_set FK check, then validate that FK once
    # text_set_ids are known.
    item_ids = _unique_ids(issues, "Items", data.items, "item_id")
    text_set_ids = _check_text_sets(data, issues, item_ids)

    # Pass 2: full item check now that text_set_ids, region_ids, style_classes known
    _check_items(data, issues, enums, asset_ids, text_set_ids, region_ids, style_classes)

    _check_text_overlays(data, issues, enums, text_set_ids, region_ids, style_classes)
    _check_sequence_entries(data, issues, enums, sequence_ids, item_ids, style_classes)

    # Structural
    _check_cycles(data, issues)

    return issues


# ---------------------------------------------------------------------------
# sim_test
# ---------------------------------------------------------------------------

class _ValidatorTest:
    @classmethod
    def sim_test(cls) -> None:
        """Run validation against the live workbook (expected: zero errors on empty tables)."""
        import os
        import win32com.client as wc
        from workbook_io import read_workbook

        wb_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "8mm_database.xlsm")
        )
        print(f"sim_test: opening {wb_path}")
        xl = wc.Dispatch("Excel.Application")
        xl.Visible = False
        wb = xl.Workbooks.Open(wb_path)
        try:
            data = read_workbook(wb)
            issues = validate(data)
            if not issues:
                print("sim_test: PASS -- no issues")
            else:
                for i in issues:
                    print(" ", i)
                errors = [i for i in issues if i.severity == "error"]
                print(f"sim_test: {len(errors)} errors, {len(issues)-len(errors)} warnings")
        finally:
            wb.Close(SaveChanges=False)
            xl.Quit()
