"""showbuilder/clips.py -- Segment cache and parallel clip preloader.

Provides SegmentCache (persistent LRU disk cache for yt-dlp downloads) and
ClipPreloader (parallel background downloader with lookahead).

Both classes are imported by showbuilder/server.py for the Excel-driven flow
and by showbuilder_test_drive.py for the standalone test harness.

Clip tuple format:  (asset_id, yt_vid_id, start_s, dur_ms, effect_name, effect_params)
effect_name and effect_params are not used by the preloader (clip download only).
"""

import concurrent.futures
import json
import os
import re
import subprocess
import sys
import threading
import time

_SB_DIR          = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR        = os.path.join(_SB_DIR, "media")
CACHE_DIR        = os.path.join(_SB_DIR, "media", "cache")
_CACHE_INDEX     = os.path.join(CACHE_DIR, "index.json")
_CACHE_CAP_BYTES = 500 * 1024 * 1024   # 500 MB


def _cropdetect(path: str) -> dict | None:
    """Run ffmpeg cropdetect on the first 30 frames; return {w, h, x, y} or None."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-i", path, "-vf", "cropdetect=24:2:0",
             "-frames:v", "30", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        best = None
        for line in (out.stdout + out.stderr).splitlines():
            m = re.search(r'crop=(\d+):(\d+):(\d+):(\d+)', line)
            if m:
                best = {"w": int(m.group(1)), "h": int(m.group(2)),
                        "x": int(m.group(3)), "y": int(m.group(4))}
        return best
    except Exception:
        return None


class SegmentCache:
    """Persistent LRU cache of downloaded YouTube video segments.

    Segments are stored as mp4 files under CACHE_DIR.
    The index (index.json) records vid_id, start_s, end_s, filename,
    size_bytes, and last_used_ts for each entry.

    get()  -- find a superset segment covering [req_start, req_end] for vid_id.
              Updates last_used_ts and returns the segment path, or None.
    put()  -- register a newly-downloaded segment; evict oldest if over cap.
    trim() -- stream-copy trim a segment file to exact [start_s, end_s].
    """

    def __init__(self) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(_CACHE_INDEX):
            with open(_CACHE_INDEX, encoding="utf-8") as f:
                data = json.load(f)
            self._entries = data.get("segments", [])
        else:
            self._entries = []

    def _save(self) -> None:
        with open(_CACHE_INDEX, "w", encoding="utf-8") as f:
            json.dump({"segments": self._entries}, f, indent=2)

    def _total_bytes(self) -> int:
        return sum(e["size_bytes"] for e in self._entries)

    def get(self, vid_id: str, req_start: float, req_end: float) -> str | None:
        """Return path of a cached segment that covers [req_start, req_end], or None."""
        for e in self._entries:
            if (e["vid_id"] == vid_id
                    and e["start_s"] <= req_start + 0.001
                    and e["end_s"]   >= req_end   - 0.001):
                path = os.path.join(CACHE_DIR, e["filename"])
                if os.path.exists(path):
                    e["last_used_ts"] = time.time()
                    self._save()
                    return path
        return None

    def put(self, vid_id: str, start_s: float, end_s: float, src_path: str) -> str:
        """Copy src_path into the cache and register it. Returns the cache path."""
        import shutil
        fname    = f"{vid_id}_{start_s:.3f}_{end_s:.3f}.mp4".replace(":", "-")
        dst_path = os.path.join(CACHE_DIR, fname)
        if src_path != dst_path:
            shutil.copy2(src_path, dst_path)
        size = os.path.getsize(dst_path)
        self._entries.append({
            "vid_id":       vid_id,
            "start_s":      start_s,
            "end_s":        end_s,
            "filename":     fname,
            "size_bytes":   size,
            "last_used_ts": time.time(),
        })
        self._evict()
        self._save()
        return dst_path

    def _evict(self) -> None:
        """Remove oldest entries until total size is under cap."""
        self._entries.sort(key=lambda e: e["last_used_ts"])
        while self._total_bytes() > _CACHE_CAP_BYTES and self._entries:
            oldest = self._entries.pop(0)
            old_path = os.path.join(CACHE_DIR, oldest["filename"])
            if os.path.exists(old_path):
                os.remove(old_path)

    @staticmethod
    def trim(src_path: str, start_s: float, end_s: float, dst_path: str) -> None:
        """Stream-copy trim src from start_s to end_s into dst_path."""
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start_s),
            "-to", str(end_s),
            "-i",  src_path,
            "-c",  "copy",
            "-avoid_negative_ts", "make_zero",
            dst_path,
        ], check=True, capture_output=True)


class ClipPreloader:
    """Parallel clip preparer with lookahead prefetching during playback.

    Uses ThreadPoolExecutor(max_workers=2) so at most two downloads run
    concurrently, avoiding YouTube CDN rate-limiting.

    clips: list of (asset_id, yt_vid_id, start_s, dur_ms, effect_name, effect_params)

    Usage::

        cache     = SegmentCache()
        preloader = ClipPreloader(clips, cache)
        preloader.submit_all()       # kick off all clips in parallel
        preloader.wait_all()         # block until every clip is ready
        # ... during playback:
        preloader.on_item_start(i)   # call from CDP binding; triggers lookahead
    """

    LOOKAHEAD = 1

    def __init__(self, clips: list, cache: SegmentCache) -> None:
        self._clips    = clips
        self._cache    = cache
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._futures: dict[int, concurrent.futures.Future] = {}
        self._crops:   dict[str, dict] = {}
        self._lock     = threading.Lock()

    def _prepare_one(self, index: int) -> str:
        """Cache lookup + trim (or download + cache + trim). Returns out_path."""
        asset_id, vid_id, start_s, dur_ms, _eff, _ep = self._clips[index]
        end_s    = start_s + dur_ms / 1000.0
        out_path = os.path.join(MEDIA_DIR, f"{asset_id}.mp4")
        if os.path.exists(out_path):
            print(f"[preload] {asset_id}: output exists, skipping")
        else:
            seg = self._cache.get(vid_id, start_s, end_s)
            if seg:
                print(f"[preload] {asset_id}: cache hit -- trimming {os.path.basename(seg)}")
                SegmentCache.trim(seg, 0.0, end_s - start_s, out_path)
            else:
                yt_url = f"https://www.youtube.com/watch?v={vid_id}"
                print(f"[preload] {asset_id}: cache miss -- downloading "
                      f"{yt_url} [{start_s:.3f}s\u2013{end_s:.3f}s] ...")
                tmp = os.path.join(CACHE_DIR, f"_tmp_{asset_id}.mp4")
                subprocess.run([
                    sys.executable, "-m", "yt_dlp",
                    "--download-sections", f"*{start_s}-{end_s}",
                    "-f", "best[height<=720][ext=mp4]/best[height<=720]",
                    "--merge-output-format", "mp4",
                    "--force-keyframes-at-cuts",
                    "-o", tmp, yt_url,
                ], check=True)
                seg = self._cache.put(vid_id, start_s, end_s, tmp)
                if os.path.exists(tmp):
                    os.remove(tmp)
                SegmentCache.trim(seg, 0.0, end_s - start_s, out_path)
            size_kb = os.path.getsize(out_path) // 1024
            print(f"[preload] {asset_id}: ready ({size_kb} KB)")
        crop = _cropdetect(out_path)
        if crop:
            with self._lock:
                self._crops[asset_id] = crop
        return out_path

    def submit(self, index: int) -> None:
        """Submit clip[index] for preparation if not already in flight."""
        if index < 0 or index >= len(self._clips):
            return
        with self._lock:
            if index not in self._futures:
                self._futures[index] = self._executor.submit(self._prepare_one, index)

    def submit_all(self) -> None:
        """Submit all clips; max_workers caps concurrency automatically."""
        for i in range(len(self._clips)):
            self.submit(i)

    def wait_ready(self, index: int, timeout: float = 60.0) -> str:
        """Block until clip[index] is on disk. Submits it if not yet in flight."""
        self.submit(index)
        with self._lock:
            fut = self._futures[index]
        return fut.result(timeout=timeout)

    def wait_all(self, timeout: float = 300.0) -> None:
        """Block until every clip is ready."""
        for i in range(len(self._clips)):
            self.wait_ready(i, timeout=timeout)

    def on_item_start(self, index: int) -> None:
        """Call when item[index] starts playing; submits LOOKAHEAD clips ahead."""
        for i in range(index + 1, index + 1 + self.LOOKAHEAD + 1):
            self.submit(i)

    def crop_map(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._crops)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
