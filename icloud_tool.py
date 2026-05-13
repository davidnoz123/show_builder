"""icloud_tool.py -- CLI for iCloud photo ingestion.

Usage (run from repo root with project venv):

    python icloud_tool.py --workbook PATH <command> [options]

Commands:
    add-account  ALIAS APPLE_ID        Add account to ICloudAccounts table
    list-albums  ALIAS                 Print available albums in iCloud account
    sync         ALIAS [--album NAME]  Pull photo metadata into ICloudPhotos table
    list-photos  [--album NAME] [--limit N]  List photos currently in workbook
    download     ALIAS [--album NAME] [--limit N]  Download photos to media/cache/
    register     ALIAS [--album NAME]  Register downloaded photos as Assets
    clear-cache  [ALIAS]               Evict local files, clear local_path/hash
    remove-creds APPLE_ID             Delete password from Windows Credential Manager

Each command opens and closes the workbook via COM automatically.
Excel does NOT need to be open.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request

# Allow running directly: python icloud_tool.py
sys.path.insert(0, os.path.dirname(__file__))

_log = lambda msg: print(msg, file=sys.stderr)

from icloud_sync import (
    KEYRING_SERVICE,
    clear_cache,
    ensure_local,
    list_albums,
    register_as_asset,
    remove_account_credentials,
    sync_metadata,
    _lookup_account,
    _write_account_row,
)
from workbook_io import read_workbook, seed_workbook, _str


# ---------------------------------------------------------------------------
# COM open/close helpers
# ---------------------------------------------------------------------------

def _open_wb(path: str):
    import win32com.client as wc
    xl = wc.Dispatch("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    wb = xl.Workbooks.Open(os.path.abspath(path))
    return xl, wb


def _close_wb(xl, wb, save: bool = True) -> None:
    wb.Close(SaveChanges=save)
    xl.Quit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_add_account(args):
    xl, wb = _open_wb(args.workbook)
    try:
        seed_workbook(wb)  # ensure tables exist
        _write_account_row(args.alias, args.apple_id, wb)
        print(f"Account {args.alias!r} ({args.apple_id}) added to workbook.")
        print("Password will be prompted on first sync.")
    finally:
        _close_wb(xl, wb)


def cmd_list_albums(args):
    xl, wb = _open_wb(args.workbook)
    try:
        seed_workbook(wb)
        albums = list_albums(args.alias, wb)
    finally:
        _close_wb(xl, wb, save=False)
    if not albums:
        print("No albums found (or account has none).")
        return
    print(f"\nAlbums in account {args.alias!r}:")
    for name in sorted(albums):
        print(f"  {name}")
    print(f"\n{len(albums)} album(s) total.")


def cmd_sync(args):
    xl, wb = _open_wb(args.workbook)
    try:
        seed_workbook(wb)
        album = getattr(args, "album", None)
        label = f"album={album!r}" if album else "all photos"
        print(f"Syncing metadata for {args.alias!r} ({label}) ...")
        n = sync_metadata(args.alias, wb, album=album)
        print(f"Done — {n} photo(s) synced/updated in ICloudPhotos table.")
    finally:
        _close_wb(xl, wb)


def cmd_list_photos(args):
    xl, wb = _open_wb(args.workbook)
    try:
        data = read_workbook(wb)
    finally:
        _close_wb(xl, wb, save=False)

    photos = data.icloud_photos
    album  = getattr(args, "album", None)
    if album:
        photos = [p for p in photos if p.album == album]
    limit = getattr(args, "limit", None)
    if limit:
        photos = photos[:limit]

    if not photos:
        print("No photos in ICloudPhotos table (run sync first).")
        return

    print(f"\n{'ID':<32}  {'type':<6}  {'cached':<6}  {'album':<20}  filename")
    print("-" * 90)
    for p in photos:
        cached = "yes" if p.local_path else "no"
        asset  = p.asset_id or ""
        print(f"{p.icloud_photo_id:<32}  {p.media_type:<6}  {cached:<6}  "
              f"{p.album:<20}  {p.filename}"
              + (f"  [{asset}]" if asset else ""))
    print(f"\n{len(photos)} photo(s) shown.")


def cmd_download(args):
    xl, wb = _open_wb(args.workbook)
    try:
        data  = read_workbook(wb)
        album = getattr(args, "album", None)
        limit = getattr(args, "limit", None)

        photos = [p for p in data.icloud_photos
                  if p.account_alias == args.alias
                  and (not album or p.album == album)
                  and not p.local_path]   # skip already-cached
        if limit:
            photos = photos[:limit]

        if not photos:
            print("No photos to download (already cached or none matching).")
            return

        print(f"Downloading {len(photos)} photo(s) ...")
        for i, p in enumerate(photos, 1):
            print(f"  [{i}/{len(photos)}] {p.filename} ...", end=" ", flush=True)
            ensure_local(p.icloud_photo_id, wb)
            print("ok")
        print("Done.")
    finally:
        _close_wb(xl, wb)


def cmd_register(args):
    xl, wb = _open_wb(args.workbook)
    try:
        data  = read_workbook(wb)
        album = getattr(args, "album", None)

        photos = [p for p in data.icloud_photos
                  if p.account_alias == args.alias
                  and (not album or p.album == album)
                  and p.local_path
                  and not p.asset_id]

        if not photos:
            print("No downloaded, unregistered photos found.")
            return

        print(f"Registering {len(photos)} photo(s) as Assets ...")
        for p in photos:
            asset_id = register_as_asset(p.icloud_photo_id, wb)
            print(f"  {p.filename} → {asset_id}")
        print("Done.")
    finally:
        _close_wb(xl, wb)


def cmd_clear_cache(args):
    xl, wb = _open_wb(args.workbook)
    try:
        alias = getattr(args, "alias", None)
        n = clear_cache(wb, account_alias=alias)
        label = f"account {alias!r}" if alias else "all accounts"
        print(f"Cleared {n} cached file(s) for {label}.")
    finally:
        _close_wb(xl, wb)


def cmd_remove_creds(args):
    remove_account_credentials(args.apple_id)


# ---------------------------------------------------------------------------
# Chrome debug-attach helpers
# ---------------------------------------------------------------------------

_DEBUG_PORT = 9222
_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
_REAL_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")


def _debug_port_open(port: int = _DEBUG_PORT) -> bool:
    """Return True if something is already listening on the CDP debug port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _chrome_pids() -> list[int]:
    """Return PIDs of any running chrome.exe processes."""
    import psutil
    return [p.pid for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() == "chrome.exe"]


def ensure_debug_chrome(port: int = _DEBUG_PORT) -> None:
    """Make sure a Chrome instance with --remote-debugging-port is running.

    Three cases handled:

    1. Debug port already open        → nothing to do, connect as-is.
    2. Chrome running, no debug port  → tell user to close it, then relaunch.
    3. Chrome not running             → launch it with real profile + debug port.
    """
    if _debug_port_open(port):
        print(f"Chrome debug port {port} already open — attaching.")
        return

    try:
        import psutil as _psutil
        pids = _chrome_pids()
    except ImportError:
        pids = []

    if pids:
        print()
        print(f"Chrome is running (PID {pids[0]}) but WITHOUT the debug port.")
        print("Close Chrome, then press Enter to relaunch it with debug access,")
        print("or Ctrl+C to cancel.")
        try:
            input()
        except KeyboardInterrupt:
            print("Cancelled.")
            sys.exit(1)

        # Wait up to 10 s for Chrome to close
        for _ in range(20):
            if not _chrome_pids():
                break
            time.sleep(0.5)
        else:
            print("Chrome is still running. Please close it manually and retry.")
            sys.exit(1)

    print(f"Launching Chrome with your real profile and debug port {port} ...")
    subprocess.Popen(
        [
            _CHROME_EXE,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={_REAL_PROFILE}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for debug port to come up (up to 15 s)
    for _ in range(30):
        if _debug_port_open(port):
            print("Chrome ready.")
            return
        time.sleep(0.5)

    print("Timed out waiting for Chrome debug port. Check that Chrome launched correctly.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# pick-from-browser command
# ---------------------------------------------------------------------------

_ICLOUD_PHOTOS_URL = "https://www.icloud.com/photos/"

# JS injected into the iCloud Photos page.
# iCloud Photos marks selected thumbnails with aria-selected="true" on the
# figure element.  The CloudKit record name lives in the data-guid attribute
# (or falls back to parsing the element ID).  We collect whichever is present.
_SELECTION_SCRIPT = """
(function () {
    var imgs = document.querySelectorAll(
        'figure[aria-selected="true"], [data-guid][aria-selected="true"]'
    );
    var ids = [];
    imgs.forEach(function (el) {
        var guid = el.getAttribute('data-guid')
                   || el.id
                   || '';
        if (guid) ids.push(guid);
    });
    return JSON.stringify(ids);
})()
"""


def cmd_pick_from_browser(args):
    """Open icloud.com/photos in Chrome, let the user select photos, harvest IDs."""
    import json
    from chrome_tools import CDPClient, CDPSession

    ensure_debug_chrome()

    cdp = CDPClient(port=_DEBUG_PORT)
    cdp.connect()

    # Find or open the iCloud Photos tab
    targets = cdp.send("Target.getTargets").get("targetInfos", [])
    icloud_target = next(
        (t for t in targets
         if t["type"] == "page" and _ICLOUD_PHOTOS_URL in t.get("url", "")),
        None,
    )

    if icloud_target is None:
        print("Opening iCloud Photos tab ...")
        result    = cdp.send("Target.createTarget", {"url": _ICLOUD_PHOTOS_URL})
        target_id = result["targetId"]
        # Wait for the tab to appear
        for _ in range(20):
            targets = cdp.send("Target.getTargets").get("targetInfos", [])
            if any(t["targetId"] == target_id for t in targets):
                break
            time.sleep(0.5)
    else:
        target_id = icloud_target["targetId"]
        print(f"Found existing iCloud Photos tab.")

    session = CDPSession(cdp)
    session.attach(target_id)

    print()
    print("iCloud Photos is open in Chrome.")
    print("Select the photos you want (click to select, Shift/Cmd-click for multiple).")
    print("Press Enter here when done, or Ctrl+C to cancel.")
    try:
        input()
    except KeyboardInterrupt:
        print("Cancelled.")
        cdp.close()
        return

    # Harvest selected photo IDs from the DOM
    result = session.send("Runtime.evaluate", {
        "expression":    _SELECTION_SCRIPT,
        "returnByValue": True,
    })
    raw = result.get("result", {}).get("value", "[]")
    cdp.close()

    try:
        guids = json.loads(raw)
    except Exception:
        guids = []

    if not guids:
        print("No photos selected (or selection could not be read from the page).")
        print("Tip: make sure photos are selected before pressing Enter.")
        return

    print(f"\n{len(guids)} photo(s) selected:")
    for g in guids:
        print(f"  {g}")

    if not args.dry_run:
        xl, wb = _open_wb(args.workbook)
        try:
            seed_workbook(wb)
            # sync metadata for just these IDs, then download
            from icloud_sync import sync_photo_ids, ensure_local
            n_synced = sync_photo_ids(args.alias, guids, wb)
            print(f"\nSynced {n_synced} photo(s) to ICloudPhotos table.")
            if not args.metadata_only:
                print("Downloading ...")
                for guid in guids:
                    try:
                        path = ensure_local(guid, wb)
                        print(f"  {guid[:20]}...  → {os.path.basename(path)}")
                    except Exception as e:
                        print(f"  {guid[:20]}...  FAILED: {e}")
        finally:
            _close_wb(xl, wb)
    else:
        print("(dry-run — workbook not updated)")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="icloud_tool",
        description="ShowBuilder iCloud photo ingestion CLI",
    )
    p.add_argument("--workbook", required=True, metavar="PATH",
                   help="Path to the ShowBuilder .xlsm workbook")

    sub = p.add_subparsers(dest="command", required=True)

    # add-account
    s = sub.add_parser("add-account", help="Register an iCloud account in the workbook")
    s.add_argument("alias",    help="Short alias, e.g. 'main'")
    s.add_argument("apple_id", help="Apple ID email")
    s.set_defaults(func=cmd_add_account)

    # list-albums
    s = sub.add_parser("list-albums", help="List available albums in the iCloud account")
    s.add_argument("alias", help="Account alias")
    s.set_defaults(func=cmd_list_albums)

    # sync
    s = sub.add_parser("sync", help="Pull photo metadata into ICloudPhotos table")
    s.add_argument("alias", help="Account alias")
    s.add_argument("--album", default=None, help="Sync only this album (default: all)")
    s.set_defaults(func=cmd_sync)

    # list-photos
    s = sub.add_parser("list-photos", help="List photos in the ICloudPhotos table")
    s.add_argument("--album", default=None, help="Filter by album name")
    s.add_argument("--limit", type=int, default=None, help="Max rows to show")
    s.set_defaults(func=cmd_list_photos)

    # download
    s = sub.add_parser("download", help="Download photos into media/cache/")
    s.add_argument("alias", help="Account alias")
    s.add_argument("--album", default=None, help="Only download from this album")
    s.add_argument("--limit", type=int, default=None, help="Max photos to download")
    s.set_defaults(func=cmd_download)

    # register
    s = sub.add_parser("register", help="Register downloaded photos as Assets")
    s.add_argument("alias", help="Account alias")
    s.add_argument("--album", default=None, help="Only register photos from this album")
    s.set_defaults(func=cmd_register)

    # clear-cache
    s = sub.add_parser("clear-cache", help="Delete local cached files")
    s.add_argument("alias", nargs="?", default=None, help="Account alias (default: all)")
    s.set_defaults(func=cmd_clear_cache)

    # remove-creds
    s = sub.add_parser("remove-creds", help="Remove saved password from Windows Credential Manager")
    s.add_argument("apple_id", help="Apple ID email")
    s.set_defaults(func=cmd_remove_creds)

    # pick-from-browser
    s = sub.add_parser("pick-from-browser",
                       help="Select photos in iCloud Photos web UI and sync/download them")
    s.add_argument("alias", help="Account alias")
    s.add_argument("--metadata-only", action="store_true",
                   help="Sync metadata only; do not download files")
    s.add_argument("--dry-run", action="store_true",
                   help="Print selected IDs but do not update workbook")
    s.set_defaults(func=cmd_pick_from_browser)

    return p


def main():
    parser = _build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        _log(f"FATAL unhandled exception:\n{traceback.format_exc()}")
        raise
