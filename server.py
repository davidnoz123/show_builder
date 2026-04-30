"""server.py -- ShowBuilderRouter: command dispatcher for showbuilder module."""

import json
import os
import traceback

from _vx import set_op_result, _log
from player import PlayerController


class ShowBuilderRouter:
    """Routes commands with module=="showbuilder" to PlayerController.

    Called from CommandRouter.dispatch when cmd["module"] == "showbuilder".
    Calls set_op_result directly because all operations are synchronous CDP calls.

    If workbook_path is supplied, load_show reads the open Excel workbook,
    prepares clips via ClipPreloader, resolves the first enabled show sequence,
    and sends the resulting show JSON to the player.
    """

    _KNOWN = {"load_show", "play_show", "pause_show", "stop_show", "goto_item", "sync_icloud", "get_status", "dev_play"}

    def __init__(self, ctrl: PlayerController, workbook_path: str = "",
                 db_path: str = "") -> None:
        self._ctrl          = ctrl
        self._workbook_path = workbook_path
        from .db import DEFAULT_DB_PATH
        self._db_path       = db_path or DEFAULT_DB_PATH

    def dispatch(self, cmd: dict) -> dict:
        name  = cmd.get("cmd", "")
        op_id = cmd.get("id", "")
        try:
            if name == "load_show":
                if self._workbook_path:
                    _log("ShowBuilderRouter: load_show -- building from workbook")
                    show_json = self._build_show_from_workbook()
                elif os.path.isfile(self._db_path):
                    seq_id = cmd.get("seq_id", "")
                    _log(f"ShowBuilderRouter: load_show -- building from DB  seq_id={seq_id!r}")
                    show_json = self._build_show_from_db(seq_id)
                else:
                    data = cmd.get("data", "{}")
                    _log(f"ShowBuilderRouter: load_show  data={str(data)[:60]!r}")
                    show_json = data
                self._ctrl.load_show(show_json)
                set_op_result(op_id, done=True, ok=True, msg="show loaded")

            elif name == "play_show":
                _log("ShowBuilderRouter: play_show")
                self._ctrl.play()
                set_op_result(op_id, done=True, ok=True, msg="playing")

            elif name == "pause_show":
                _log("ShowBuilderRouter: pause_show")
                self._ctrl.pause()
                set_op_result(op_id, done=True, ok=True, msg="paused")

            elif name == "stop_show":
                _log("ShowBuilderRouter: stop_show")
                self._ctrl.stop()
                set_op_result(op_id, done=True, ok=True, msg="stopped")

            elif name == "goto_item":
                n = int(cmd.get("n", 0))
                _log(f"ShowBuilderRouter: goto_item  n={n}")
                self._ctrl.goto_item(n)
                set_op_result(op_id, done=True, ok=True, msg=f"at item {n}")

            elif name == "get_status":
                status = self._ctrl.get_status()
                set_op_result(op_id, done=True, ok=True, msg="ok",
                              progress=json.dumps(status))
                return {"ok": True, "status": status}

            elif name == "dev_play":
                _log("ShowBuilderRouter: dev_play -- loading hardcoded 3-clip show")
                show_json = _build_dev_show_json()
                self._ctrl.load_show(show_json)
                self._ctrl.play()
                set_op_result(op_id, done=True, ok=True, msg="dev show playing")

            elif name == "sync_icloud":
                set_op_result(op_id, done=True, ok=False, msg="sync_icloud: not implemented")

            elif name not in self._KNOWN:
                return {"ok": False, "error": f"unknown showbuilder command: {name!r}"}

            return {"ok": True}

        except Exception as exc:
            _log(f"ShowBuilderRouter ERROR: cmd={name!r}  {exc}\n{traceback.format_exc()}")
            set_op_result(op_id, done=True, ok=False, msg=str(exc)[:200])
            return {"ok": False, "error": str(exc)}

    def _build_show_from_workbook(self) -> str:
        """Read the open workbook, prepare clips, resolve, return show JSON string.

        1. Attaches to the running Excel instance.
        2. Reads ShowBuilder data sheets via workbook_io.read_workbook.
        3. For each enabled video asset with yt_vid_id in metadata_json,
           builds a clip tuple and runs ClipPreloader (download + trim).
        4. Writes detected src_crop back into Assets.metadata_json and saves.
        5. Resolves the first enabled show-type Sequence and returns JSON.
        """
        import pythoncom
        import win32com.client as wc
        pythoncom.CoInitialize()
        from workbook_io import read_workbook, write_asset_metadata
        from resolver import resolve, build_show_json
        from clips import SegmentCache, ClipPreloader, MEDIA_DIR

        abs_path = os.path.normcase(os.path.abspath(self._workbook_path))
        try:
            xl = wc.GetActiveObject("Excel.Application")
        except Exception as e:
            raise RuntimeError(f"Excel is not running: {e}")
        wb = None
        for i in range(1, xl.Workbooks.Count + 1):
            if os.path.normcase(xl.Workbooks(i).FullName) == abs_path:
                wb = xl.Workbooks(i)
                break
        if wb is None:
            wb = xl.Workbooks.Open(self._workbook_path)
        _log(f"ShowBuilderRouter: reading workbook {wb.Name}")
        data = read_workbook(wb)

        # Find the first enabled show-type sequence
        seq_id = None
        for seq in data.sequences:
            if seq.enabled and seq.sequence_type == "show":
                seq_id = seq.sequence_id
                break
        if seq_id is None:
            raise RuntimeError("No enabled 'show' sequence in workbook")
        _log(f"ShowBuilderRouter: sequence={seq_id!r}")

        # Build ordered clip tuple list from sequence entries
        asset_by_id = {a.asset_id: a for a in data.assets if a.enabled}
        item_by_id  = {it.item_id: it for it in data.items if it.enabled}
        entries = sorted(
            [e for e in data.sequence_entries
             if e.enabled and e.sequence_id == seq_id and e.entry_type == "item"],
            key=lambda e: e.sequence_no or 0,
        )
        clips = []
        for entry in entries:
            item  = item_by_id.get(entry.target_id)
            if item is None:
                continue
            asset = asset_by_id.get(item.asset_id)
            if asset is None or asset.asset_type != "video":
                continue
            try:
                meta = json.loads(asset.metadata_json) if asset.metadata_json else {}
            except Exception:
                meta = {}
            yt_vid_id  = meta.get("yt_vid_id")
            yt_start_s = meta.get("yt_start_s")
            if not yt_vid_id or yt_start_s is None:
                _log(f"ShowBuilderRouter: asset {asset.asset_id!r} missing yt_vid_id/yt_start_s -- skipping")
                continue
            dur_ms = item.duration_ms or asset.default_duration_ms or 5000
            clips.append((
                asset.asset_id, yt_vid_id, float(yt_start_s), int(dur_ms),
                item.effect_name, item.effect_params_json,
            ))
        _log(f"ShowBuilderRouter: {len(clips)} clip(s) to prepare")

        if clips:
            os.makedirs(MEDIA_DIR, exist_ok=True)
            cache     = SegmentCache()
            preloader = ClipPreloader(clips, cache)
            preloader.submit_all()
            preloader.wait_all()
            crop_map = preloader.crop_map()
            preloader.shutdown()
            if crop_map:
                for asset_id, crop in crop_map.items():
                    write_asset_metadata(wb, asset_id, {"src_crop": crop})
                wb.Save()
                _log(f"ShowBuilderRouter: src_crop written for {len(crop_map)} asset(s)")
                data = read_workbook(wb)   # re-read so resolver sees updated metadata_json

        show      = resolve(data, seq_id)
        show_dict = build_show_json(show)
        _log(f"ShowBuilderRouter: resolved  items={len(show.items)}  total={show.total_duration_ms}ms")
        return json.dumps(show_dict)

    def _build_show_from_db(self, seq_id: str = "") -> str:
        """Read ShowbookData from showbuilder.db, resolve, return show JSON string.

        If seq_id is empty, uses the first enabled show-type sequence in the DB.
        No workbook or Excel COM required.
        """
        from .db import read_db
        from .resolver import resolve, build_show_json

        data = read_db(self._db_path)
        if not seq_id:
            for seq in data.sequences:
                if seq.enabled and seq.sequence_type == "show":
                    seq_id = seq.sequence_id
                    break
        if not seq_id:
            raise RuntimeError("No enabled 'show' sequence found in DB")
        _log(f"ShowBuilderRouter: DB sequence={seq_id!r}")
        show      = resolve(data, seq_id)
        show_dict = build_show_json(show)
        _log(f"ShowBuilderRouter: resolved  items={len(show.items)}  total={show.total_duration_ms}ms")
        return json.dumps(show_dict)


# ---------------------------------------------------------------------------
# Dev-only hardcoded 3-clip show
# ---------------------------------------------------------------------------

# (asset_id, youtube_id, start_s, dur_ms, effect_name, effect_params)
_DEV_CLIPS = [
    ("A_clip1", "NZicIgULNmk", 724.0, 5000, "zoom_in",  {"from": 1.0, "to": 1.35}),
    ("A_clip2", "OE4hAfgZBvw", 979.0, 5000, "",         {}),
    ("A_clip3", "itABF_YEjR4", 308.0, 5000, "pan_left", {}),
]


def _build_dev_show_json() -> str:
    """Build the hardcoded 3-clip show using local mp4 files and return a show JSON string.

    Uses asset_type='video' so the matte/effects work correctly.
    The mp4 files are already trimmed to clip length so media_start_s=0.
    """
    import json as _json
    from .schema import (
        Asset, Format, Item, Sequence, SequenceEntry, ShowbookData,
    )
    from .resolver import resolve, build_show_json

    data = ShowbookData()
    data.formats.append(Format(
        format_id="f_hd", name="1080p 16:9",
        width_px=1920, height_px=1080, fps=25.0,
        enabled=True, notes="",
    ))

    for asset_id, _vid_id, _start_s, dur_ms, _eff, _ep in _DEV_CLIPS:
        data.assets.append(Asset(
            asset_id=asset_id, asset_type="video",
            src=f"/media/{asset_id}.mp4",
            title=asset_id,
            default_duration_ms=dur_ms,
            # Crop rect detected from the downloaded mp4 files (480x360 pillarboxed in 640x360).
            metadata_json='{"src_crop": {"w": 480, "h": 360, "x": 80, "y": 0}}',
            enabled=True, notes="",
        ))

    for i, (asset_id, _vid_id, _start_s, dur_ms, effect_name, effect_params) in enumerate(_DEV_CLIPS):
        data.items.append(Item(
            item_id=f"I_clip{i+1}", asset_id=asset_id,
            duration_ms=dur_ms, duration_mode="fixed",
            media_start_s=0.0,  # already trimmed
            effect_name=effect_name,
            effect_params_json=_json.dumps(effect_params) if effect_params else "",
            default_text_set_id="",
            region_id="", style_class="",
            track_kind="video_main", media_audio_mode="normal",
            media_audio_gain_db=None, z_order=0, fit_mode="contain",
            transition_in="", transition_in_params_json="",
            transition_out="", transition_out_params_json="",
            yt_freeze_at_s=None, yt_freeze_duration_ms=None,
            metadata_json="", enabled=True, notes="",
        ))

    data.sequences.append(Sequence(
        sequence_id="SQ_dev", sequence_name="Dev 3-Clip Show",
        sequence_type="show", format_id="f_hd",
        timing_mode="serial",
        description="Hardcoded dev show -- 3 YouTube clips",
        metadata_json="", enabled=True,
    ))

    for i in range(len(_DEV_CLIPS)):
        data.sequence_entries.append(SequenceEntry(
            sequence_entry_id=f"SE_{i+1}",
            sequence_id="SQ_dev",
            sequence_no=i + 1,
            entry_type="item",
            target_id=f"I_clip{i+1}",
            track_kind="",
            local_start_ms=None,
            override_duration_ms=None,
            override_media_start_s=None,
            override_effect_name="",
            override_effect_params_json="",
            override_text_set_id="",
            override_z_order=None,
            override_style_class="",
            metadata_json="", enabled=True, notes="",
        ))

    show      = resolve(data, "SQ_dev")
    show_dict = build_show_json(show)
    _log(f"_build_dev_show_json: {len(show.items)} item(s)  total={show.total_duration_ms}ms")
    return _json.dumps(show_dict)
