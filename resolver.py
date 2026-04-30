"""showbuilder/resolver.py -- Sequence resolver for ShowBuilder.

Resolves a root sequence_id from ShowbookData into a flat linear timeline.

Public API:
    resolve(data, root_sequence_id)   -> ResolvedShow
    build_show_json(show)             -> dict   (browser-ready JSON payload)

Design:
    - serial sequences: items laid out end-to-end (cumulative offset)
    - parallel sequences: items placed at offset + (local_start_ms or 0)
    - overrides from SequenceEntry win over Item defaults
    - text set: override_text_set_id > item.default_text_set_id > none
    - duration priority: override_duration_ms > item.duration_ms (fixed mode)
                         > asset.default_duration_ms (to_media_end mode) > 5000 fallback
    - cycle detection: DFS with a visiting-set; raises ResolutionError on cycle
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from schema import (
    Asset,
    Format,
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
# Resolved output types
# ---------------------------------------------------------------------------

@dataclass
class ResolvedOverlay:
    text_id:             str
    sequence_no:         int | None
    content:             str
    start_ms:            int | None   # relative to item start
    duration_ms:         int | None
    position_mode:       str          # preset | coords
    position_preset:     str
    pos_x:               float | None
    pos_y:               float | None
    anchor:              str
    width_norm:          float | None
    align:               str
    region_id:           str
    effect_name:         str
    effect_params:       dict
    style_class:         str


@dataclass
class ResolvedItem:
    sequence_entry_id: str            # source entry
    item_id:           str
    asset_type:        str            # image | video | youtube
    src:               str
    absolute_start_ms: int            # position in the show
    duration_ms:       int
    media_start_s:     float | None
    effect_name:       str
    effect_params:     dict
    z_order:           int
    fit_mode:          str
    style_class:       str
    region_id:         str
    track_kind:        str
    transition_in:     str
    transition_in_params: dict
    transition_out:    str
    transition_out_params: dict
    yt_freeze_at_s:    float | None
    yt_freeze_duration_ms: int | None
    src_crop:          dict | None     # {x, y, w, h} in source pixels (baked-in crop)
    overlays:          list[ResolvedOverlay]
    format_id:         str            # inherited from root sequence


@dataclass
class ResolvedShow:
    sequence_id:   str
    sequence_name: str
    format:        Format | None
    items:         list[ResolvedItem]

    @property
    def total_duration_ms(self) -> int:
        if not self.items:
            return 0
        return max(it.absolute_start_ms + it.duration_ms for it in self.items)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ResolutionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal context
# ---------------------------------------------------------------------------

_FALLBACK_DURATION_MS = 5000


class _Ctx:
    """Lookup maps built once from ShowbookData."""

    def __init__(self, data: ShowbookData) -> None:
        self.formats:    dict[str, Format]         = {f.format_id: f   for f in data.formats}
        self.assets:     dict[str, Asset]          = {a.asset_id: a    for a in data.assets}
        self.items:      dict[str, Item]           = {i.item_id: i     for i in data.items}
        self.text_sets:  dict[str, TextSet]        = {ts.text_set_id: ts for ts in data.text_sets}
        self.sequences:  dict[str, Sequence]       = {s.sequence_id: s  for s in data.sequences}
        self.regions:    dict[str, Region]         = {r.region_id: r   for r in data.regions}
        self.styles:     dict[str, Style]          = {s.style_class: s  for s in data.styles}

        # overlays grouped by text_set_id, sorted by sequence_no
        self.overlays:   dict[str, list[TextOverlay]] = {}
        for ov in data.text_overlays:
            self.overlays.setdefault(ov.text_set_id, []).append(ov)
        for lst in self.overlays.values():
            lst.sort(key=lambda o: (o.sequence_no or 0))

        # sequence entries grouped by sequence_id, sorted by sequence_no
        self.entries: dict[str, list[SequenceEntry]] = {}
        for e in data.sequence_entries:
            self.entries.setdefault(e.sequence_id, []).append(e)
        for lst in self.entries.values():
            lst.sort(key=lambda e: (e.sequence_no or 0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(s: str) -> dict:
    if not s or not s.strip():
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def _eff_str(override: str, base: str) -> str:
    """Return override if non-empty, else base."""
    return override if override else base


def _eff_int(override: int | None, base: int | None) -> int | None:
    return override if override is not None else base


def _eff_float(override: float | None, base: float | None) -> float | None:
    return override if override is not None else base


def _resolve_duration(entry: SequenceEntry, item: Item, asset: Asset | None) -> int:
    """Determine effective duration in ms."""
    if entry.override_duration_ms is not None:
        return entry.override_duration_ms
    if item.duration_ms is not None and item.duration_mode == "fixed":
        return item.duration_ms
    if asset is not None and asset.default_duration_ms is not None:
        return asset.default_duration_ms
    return _FALLBACK_DURATION_MS


def _resolve_overlays(text_set_id: str, ctx: _Ctx) -> list[ResolvedOverlay]:
    if not text_set_id:
        return []
    overlays_raw = ctx.overlays.get(text_set_id, [])
    result = []
    for ov in overlays_raw:
        if not ov.enabled:
            continue
        result.append(ResolvedOverlay(
            text_id         = ov.text_id,
            sequence_no     = ov.sequence_no,
            content         = ov.content,
            start_ms        = ov.start_ms,
            duration_ms     = ov.duration_ms,
            position_mode   = ov.position_mode,
            position_preset = ov.position_preset,
            pos_x           = ov.pos_x,
            pos_y           = ov.pos_y,
            anchor          = ov.anchor,
            width_norm      = ov.width_norm,
            align           = ov.align,
            region_id       = ov.region_id,
            effect_name     = ov.effect_name,
            effect_params   = _parse_json(ov.effect_params_json),
            style_class     = ov.style_class,
        ))
    return result


def _resolve_item_entry(
    entry:      SequenceEntry,
    abs_start:  int,
    format_id:  str,
    ctx:        _Ctx,
) -> ResolvedItem:
    item = ctx.items.get(entry.target_id)
    if item is None:
        raise ResolutionError(
            f"SequenceEntry {entry.sequence_entry_id!r}: "
            f"target_id {entry.target_id!r} not found in Items"
        )

    asset = ctx.assets.get(item.asset_id)
    duration_ms = _resolve_duration(entry, item, asset)

    eff_effect_name   = _eff_str(entry.override_effect_name,  item.effect_name)
    eff_effect_params = _parse_json(
        entry.override_effect_params_json
        if entry.override_effect_params_json
        else item.effect_params_json
    )

    text_set_id = _eff_str(entry.override_text_set_id, item.default_text_set_id)
    overlays    = _resolve_overlays(text_set_id, ctx)

    z_order     = entry.override_z_order if entry.override_z_order is not None else (item.z_order or 0)
    style_class = _eff_str(entry.override_style_class, item.style_class)
    media_start = _eff_float(entry.override_media_start_s, item.media_start_s)
    track_kind  = _eff_str(entry.track_kind, item.track_kind)

    return ResolvedItem(
        sequence_entry_id = entry.sequence_entry_id,
        item_id           = item.item_id,
        asset_type        = asset.asset_type if asset else "",
        src               = asset.src        if asset else "",
        absolute_start_ms = abs_start,
        duration_ms       = duration_ms,
        media_start_s     = media_start,
        effect_name       = eff_effect_name,
        effect_params     = eff_effect_params,
        z_order           = z_order,
        fit_mode          = item.fit_mode or "contain",
        style_class       = style_class,
        region_id         = item.region_id,
        track_kind        = track_kind,
        transition_in     = item.transition_in,
        transition_in_params  = _parse_json(item.transition_in_params_json),
        transition_out    = item.transition_out,
        transition_out_params = _parse_json(item.transition_out_params_json),
        yt_freeze_at_s        = item.yt_freeze_at_s,
        yt_freeze_duration_ms = item.yt_freeze_duration_ms,
        src_crop              = _parse_json(asset.metadata_json).get('src_crop') if asset else None,
        overlays  = overlays,
        format_id = format_id,
    )


def _resolve_sequence(
    sequence_id: str,
    offset_ms:   int,
    format_id:   str,
    ctx:         _Ctx,
    visiting:    set[str],
) -> tuple[list[ResolvedItem], int]:
    """Recursively expand a sequence.

    Returns (resolved_items, total_duration_ms) where total_duration_ms is the
    duration of this sequence's envelope (for use by the parent in serial layout).
    """
    if sequence_id in visiting:
        raise ResolutionError(
            f"Cycle detected: sequence {sequence_id!r} references itself recursively"
        )

    seq = ctx.sequences.get(sequence_id)
    if seq is None:
        raise ResolutionError(f"Sequence {sequence_id!r} not found")
    if not seq.enabled:
        return [], 0

    entries = [e for e in ctx.entries.get(sequence_id, []) if e.enabled]
    if not entries:
        return [], 0

    visiting = visiting | {sequence_id}   # immutable push

    resolved: list[ResolvedItem] = []
    cursor_ms     = offset_ms   # running position (serial)
    max_end_ms    = offset_ms   # tracks parallel envelope end

    timing_mode = seq.timing_mode or "serial"

    for entry in entries:
        if timing_mode == "parallel":
            abs_start = offset_ms + (entry.local_start_ms or 0)
        else:
            abs_start = cursor_ms

        if entry.entry_type == "item":
            ri = _resolve_item_entry(entry, abs_start, format_id, ctx)
            resolved.append(ri)
            entry_end = abs_start + ri.duration_ms

        elif entry.entry_type == "sequence":
            child_items, child_dur = _resolve_sequence(
                entry.target_id, abs_start, format_id, ctx, visiting
            )
            resolved.extend(child_items)
            entry_end = abs_start + child_dur

        else:
            raise ResolutionError(
                f"SequenceEntry {entry.sequence_entry_id!r}: "
                f"unknown entry_type {entry.entry_type!r}"
            )

        if timing_mode == "serial":
            cursor_ms = entry_end
        max_end_ms = max(max_end_ms, entry_end)

    total_duration = max_end_ms - offset_ms
    return resolved, total_duration


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(data: ShowbookData, root_sequence_id: str) -> ResolvedShow:
    """Resolve root_sequence_id into a flat linear timeline.

    Raises ResolutionError on missing IDs, unknown entry types, or cycles.
    """
    ctx = _Ctx(data)

    root_seq = ctx.sequences.get(root_sequence_id)
    if root_seq is None:
        raise ResolutionError(f"Root sequence {root_sequence_id!r} not found")

    format_id = root_seq.format_id
    fmt = ctx.formats.get(format_id)

    items, _ = _resolve_sequence(root_sequence_id, 0, format_id, ctx, set())

    # Sort by (z_order, absolute_start_ms) for deterministic render order
    items.sort(key=lambda it: (it.absolute_start_ms, it.z_order))

    return ResolvedShow(
        sequence_id   = root_sequence_id,
        sequence_name = root_seq.sequence_name,
        format        = fmt,
        items         = items,
    )


def build_show_json(show: ResolvedShow) -> dict:
    """Convert a ResolvedShow to a browser-player-ready dict.

    The resulting dict can be serialised directly with json.dumps().
    """
    fmt = show.format
    format_dict: dict = {}
    if fmt is not None:
        format_dict = {
            "format_id": fmt.format_id,
            "width_px":  fmt.width_px,
            "height_px": fmt.height_px,
            "fps":       fmt.fps,
        }

    items_out = []
    for it in show.items:
        overlays_out = []
        for ov in it.overlays:
            overlays_out.append({
                "text_id":        ov.text_id,
                "sequence_no":    ov.sequence_no,
                "content":        ov.content,
                "start_ms":       ov.start_ms,
                "duration_ms":    ov.duration_ms,
                "position_mode":  ov.position_mode,
                "position_preset": ov.position_preset,
                "pos_x":          ov.pos_x,
                "pos_y":          ov.pos_y,
                "anchor":         ov.anchor,
                "width_norm":     ov.width_norm,
                "align":          ov.align,
                "region_id":      ov.region_id,
                "effect_name":    ov.effect_name,
                "effect_params":  ov.effect_params,
                "style_class":    ov.style_class,
            })

        items_out.append({
            "sequence_entry_id":  it.sequence_entry_id,
            "item_id":            it.item_id,
            "asset_type":         it.asset_type,
            "src":                it.src,
            "absolute_start_ms":  it.absolute_start_ms,
            "duration_ms":        it.duration_ms,
            "media_start_s":      it.media_start_s,
            "effect_name":        it.effect_name,
            "effect_params":      it.effect_params,
            "z_order":            it.z_order,
            "fit_mode":           it.fit_mode,
            "style_class":        it.style_class,
            "region_id":          it.region_id,
            "track_kind":         it.track_kind,
            "transition_in":      it.transition_in,
            "transition_in_params":  it.transition_in_params,
            "transition_out":        it.transition_out,
            "transition_out_params":  it.transition_out_params,
            "yt_freeze_at_s":         it.yt_freeze_at_s,
            "yt_freeze_duration_ms":  it.yt_freeze_duration_ms,
            "src_crop":               it.src_crop,
            "overlays":               overlays_out,
        })

    return {
        "sequence_id":        show.sequence_id,
        "sequence_name":      show.sequence_name,
        "total_duration_ms":  show.total_duration_ms,
        "format":             format_dict,
        "items":              items_out,
    }


# ---------------------------------------------------------------------------
# sim_test
# ---------------------------------------------------------------------------

class _ResolverTest:
    @classmethod
    def sim_test(cls) -> None:
        """Build a minimal in-memory ShowbookData and resolve it."""
        from schema import (
            Asset, Format, Item, Sequence, SequenceEntry, ShowbookData,
            TextOverlay, TextSet,
        )

        data = ShowbookData(
            formats=[
                Format("FMT_1", "HD", 1920, 1080, 25.0, True, ""),
            ],
            assets=[
                Asset("A_IMG1", "image",   "media/cache/img1.jpg", "Image 1",   3000, "", True, ""),
                Asset("A_VID1", "video",   "media/cache/vid1.mp4", "Video 1",   8000, "", True, ""),
                Asset("A_YT1",  "youtube", "https://youtu.be/abc", "YouTube 1", None, "", True, ""),
            ],
            items=[
                Item("IT_A", "A_IMG1", 4000, "fixed",      None, "ken_burns",
                     '{"x1":0.5,"y1":0.5,"s1":1.0,"x2":0.6,"y2":0.4,"s2":1.2}',
                     "TS_A", "", "", "media", "full", None,
                     1, "cover", "fade", "{}", "fade", "{}", "", True, ""),
                Item("IT_B", "A_VID1", None, "to_media_end", 2.5, "none", "{}",
                     "",     "", "", "media", "full", None,
                     2, "contain", "", "{}", "", "{}", "", True, ""),
                Item("IT_C", "A_YT1",  6000, "fixed",      10.0, "none", "{}",
                     "TS_C", "", "", "media", "muted", None,
                     3, "contain", "", "{}", "", "{}", "", True, ""),
            ],
            text_sets=[
                TextSet("TS_A", "IT_A", "Default", "", True, ""),
                TextSet("TS_C", "IT_C", "Default", "", True, ""),
            ],
            text_overlays=[
                TextOverlay(
                    "TO_1", "TS_A", 1, "Welcome to the show",
                    500, 3000, "preset", "bottom_center",
                    None, None, "", None, "center", "",
                    "fade", "{}", "", "", True, ""),
                TextOverlay(
                    "TO_2", "TS_C", 1, "YouTube clip",
                    0, 2000, "coords", "",
                    0.1, 0.85, "top_left", 0.4, "left", "",
                    "slide_up", "{}", "", "", True, ""),
            ],
            sequences=[
                Sequence("SEQ_INTRO", "Intro Block",   "block", "FMT_1", "serial",  "", "", True),
                Sequence("SEQ_SHOW1", "Show 1",        "show",  "FMT_1", "serial",  "", "", True),
            ],
            sequence_entries=[
                # Intro block: IT_A then IT_B
                SequenceEntry("SE_1", "SEQ_INTRO", 1, "item",     "IT_A", "media", None, None,  None, "", "", "",    None, "", "", True, ""),
                SequenceEntry("SE_2", "SEQ_INTRO", 2, "item",     "IT_B", "media", None, None,  None, "", "", "",    None, "", "", True, ""),
                # Show 1: nested intro block + IT_C
                SequenceEntry("SE_3", "SEQ_SHOW1", 1, "sequence", "SEQ_INTRO", "media", None, None, None, "", "", "", None, "", "", True, ""),
                SequenceEntry("SE_4", "SEQ_SHOW1", 2, "item",     "IT_C",     "media", None, 5000, None, "", "", "TS_C", None, "", "", True, ""),
            ],
        )

        show = resolve(data, "SEQ_SHOW1")
        j    = build_show_json(show)

        print(f"\n=== resolver sim_test ===")
        print(f"  sequence_id:       {j['sequence_id']}")
        print(f"  sequence_name:     {j['sequence_name']}")
        print(f"  total_duration_ms: {j['total_duration_ms']}")
        print(f"  format:            {j['format']}")
        print(f"  items ({len(j['items'])}):")
        for it in j["items"]:
            print(f"    [{it['sequence_entry_id']}] {it['item_id']}  "
                  f"start={it['absolute_start_ms']}ms  dur={it['duration_ms']}ms  "
                  f"type={it['asset_type']}  overlays={len(it['overlays'])}")

        # Expected layout (serial):
        #   SE_1: IT_A  start=0     dur=4000   (fixed 4000)
        #   SE_2: IT_B  start=4000  dur=8000   (to_media_end → asset 8000)
        #   SE_3 envelope = 12000ms
        #   SE_4: IT_C  start=12000 dur=5000   (override 5000, src fixed 6000)
        # total = 17000ms
        assert j["total_duration_ms"] == 17000,       f"total_duration_ms = {j['total_duration_ms']}"
        assert j["items"][0]["absolute_start_ms"] == 0
        assert j["items"][1]["absolute_start_ms"] == 4000
        assert j["items"][2]["absolute_start_ms"] == 12000
        assert j["items"][2]["duration_ms"]        == 5000   # override wins
        assert len(j["items"][0]["overlays"]) == 1           # TS_A has 1 overlay
        assert len(j["items"][2]["overlays"]) == 1           # TS_C override on SE_4
        print("  [PASS]")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 2)[0])
    _ResolverTest.sim_test()
