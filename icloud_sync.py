"""showbuilder/icloud_sync.py -- iCloud Photos ingestion for ShowBuilder.

Architecture:
    iCloud Photos → sync_metadata() → ICloudPhotos table (metadata only)
    ensure_local()  → downloads file on demand into media/cache/
    register_as_asset() → creates Assets row, writes asset_id back to ICloudPhotos

Credentials:
    Passwords stored in Windows Credential Manager via keyring.
    Prompted on first use per account; silent on subsequent calls.

Session cookies:
    Stored in showbuilder/.icloud_sessions/<alias>/ per account.
    Excluded from git via .gitignore.

Public API:
    sync_metadata(account_alias, wb)                    -> int   (new/updated count)
    ensure_local(icloud_photo_id, wb)                   -> str   (local path)
    clear_cache(wb, account_alias=None)                 -> int   (cleared count)
    register_as_asset(icloud_photo_id, wb)              -> str   (asset_id)
    remove_account_credentials(apple_id)                -> None
"""

import getpass
import hashlib
import os
import sys

from utils import get_keyring, get_pyicloud

from workbook_io import (
    _append_table_row,
    _find_list_object,
    _find_sheet,
    _read_table,
    _str,
    find_table_row,
    update_table_row,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SB_DIR       = os.path.dirname(os.path.abspath(__file__))
_SESSIONS_DIR = os.path.join(_SB_DIR, ".icloud_sessions")
_CACHE_DIR    = os.path.join(_SB_DIR, "media", "cache")

KEYRING_SERVICE = "showbuilder_icloud"


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------

def _get_password(apple_id: str) -> str:
    """Return password from Windows Credential Manager, prompting if absent."""
    keyring = get_keyring(globals())
    pw = keyring.get_password(KEYRING_SERVICE, apple_id)
    if pw:
        return pw
    print(f"\nAccount {apple_id!r} not found in Windows Credential Manager.")
    pw = getpass.getpass(f"Enter password for {apple_id}: ")
    keyring.set_password(KEYRING_SERVICE, apple_id, pw)
    print("Password saved to Windows Credential Manager.")
    return pw


def remove_account_credentials(apple_id: str) -> None:
    """Delete saved password from Windows Credential Manager."""
    keyring = get_keyring(globals())
    try:
        keyring.delete_password(KEYRING_SERVICE, apple_id)
        print(f"Credentials removed for {apple_id!r}")
    except Exception:
        print(f"No credentials found for {apple_id!r}")


# ---------------------------------------------------------------------------
# iCloud API connection
# ---------------------------------------------------------------------------

def _session_dir(account_alias: str) -> str:
    d = os.path.join(_SESSIONS_DIR, account_alias)
    os.makedirs(d, exist_ok=True)
    return d


def _get_api(apple_id: str, account_alias: str):
    """Return an authenticated PyiCloudService instance."""
    pyicloud = get_pyicloud(globals())
    pw = _get_password(apple_id)
    api = pyicloud.PyiCloudService(
        apple_id, pw,
        cookie_directory=_session_dir(account_alias),
    )
    if api.requires_2fa:
        code = input(f"Enter 2FA code sent to devices on {apple_id}: ").strip()
        if not api.validate_2fa_code(code):
            raise RuntimeError(f"2FA validation failed for {apple_id!r}")
    elif api.requires_2sa:
        devices = api.trusted_devices
        for i, device in enumerate(devices):
            print(f"  [{i}] {device.get('phoneNumber', 'SMS')}")
        idx = int(input("Choose device for 2SA code: ").strip())
        if not api.send_verification_code(devices[idx]):
            raise RuntimeError("Failed to send 2SA code")
        code = input("Enter 2SA code: ").strip()
        if not api.validate_verification_code(devices[idx], code):
            raise RuntimeError("2SA validation failed")
    return api


def _lookup_account(account_alias: str, wb) -> str:
    """Return apple_id for the given alias from ICloudAccounts table."""
    ws = _find_sheet(wb, "ICloudAccounts")
    if ws is None:
        raise RuntimeError("ICloudAccounts sheet not found — run seed_workbook() first")
    for d in _read_table(ws, "ICloudAccounts"):
        if _str(d.get("account_alias")) == account_alias:
            if not _str(d.get("enabled")).lower() in ("false", "0", "no", ""):
                return _str(d.get("apple_id"))
    raise RuntimeError(f"Account alias {account_alias!r} not found or not enabled in ICloudAccounts")


def _write_account_row(account_alias: str, apple_id: str, wb) -> None:
    """Insert or update a row in the ICloudAccounts table."""
    ws = _find_sheet(wb, "ICloudAccounts")
    if ws is None:
        raise RuntimeError("ICloudAccounts sheet not found — run seed_workbook() first")
    lo = _find_list_object(ws, "ICloudAccounts")
    if lo is None:
        raise RuntimeError("ICloudAccounts ListObject not found")

    row_idx = find_table_row(ws, "ICloudAccounts", "account_alias", account_alias)
    if row_idx is not None:
        update_table_row(ws, "ICloudAccounts", row_idx, {
            "apple_id": apple_id,
            "enabled":  "TRUE",
        })
    else:
        _append_table_row(lo, {
            "account_alias": account_alias,
            "apple_id":      apple_id,
            "enabled":       "TRUE",
            "notes":         "",
        })
    wb.Save()


# ---------------------------------------------------------------------------
# list_albums
# ---------------------------------------------------------------------------

def list_albums(account_alias: str, wb) -> list[str]:
    """Return the list of album names available in the iCloud account."""
    apple_id = _lookup_account(account_alias, wb)
    api = _get_api(apple_id, account_alias)
    return [album.fullname for album in api.photos.albums]


# ---------------------------------------------------------------------------
# sync_metadata
# ---------------------------------------------------------------------------

def sync_metadata(account_alias: str, wb, album: str | None = None) -> int:
    """Pull photo catalogue from iCloud and update ICloudPhotos table.

    Only metadata is fetched — no file downloads.
    If album is given, only photos from that album are synced.
    Returns the count of rows inserted or updated.
    """
    from datetime import datetime, timezone

    apple_id = _lookup_account(account_alias, wb)
    api = _get_api(apple_id, account_alias)

    ws = _find_sheet(wb, "ICloudPhotos")
    if ws is None:
        raise RuntimeError("ICloudPhotos sheet not found — run seed_workbook() first")
    lo = _find_list_object(ws, "ICloudPhotos")
    if lo is None:
        raise RuntimeError("ICloudPhotos ListObject not found")

    if album is not None:
        albums = api.photos.albums
        album_obj = albums.find(album)
        if album_obj is None:
            available = [a.fullname for a in albums]
            raise RuntimeError(
                f"Album {album!r} not found. Available: {available}"
            )
        photo_iter = album_obj.photos
        album_label = album
    else:
        photo_iter  = api.photos.all.photos
        album_label = ""

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0

    for photo in photo_iter:
        try:
            photo_id   = str(photo.id)
            filename   = str(photo.filename)
            media_type = "video" if getattr(photo, "item_type", "image") == "movie" else "image"
            created    = getattr(photo, "created", None)
            created_str = created.strftime("%Y-%m-%dT%H:%M:%SZ") if created else ""
        except Exception:
            continue

        row_idx = find_table_row(ws, "ICloudPhotos", "icloud_photo_id", photo_id)
        if row_idx is not None:
            update_table_row(ws, "ICloudPhotos", row_idx, {
                "filename":    filename,
                "media_type":  media_type,
                "album":       album_label or "",
                "last_synced": now_str,
            })
        else:
            _append_table_row(lo, {
                "icloud_photo_id": photo_id,
                "account_alias":   account_alias,
                "filename":        filename,
                "created_date":    created_str,
                "media_type":      media_type,
                "album":           album_label,
                "local_path":      "",
                "local_hash":      "",
                "asset_id":        "",
                "last_synced":     now_str,
                "notes":           "",
            })
        count += 1
        if count % 50 == 0:
            print(f"  {count} photos synced...", flush=True)

    wb.Save()
    return count


# ---------------------------------------------------------------------------
# sync_photo_ids  -- sync metadata for a specific list of photo IDs
# ---------------------------------------------------------------------------

def sync_photo_ids(account_alias: str, photo_ids: list[str], wb) -> int:
    """Fetch metadata for specific photo IDs and upsert into ICloudPhotos table.

    Used by pick-from-browser after harvesting IDs from the DOM.
    Returns count of rows inserted or updated.
    """
    from datetime import datetime, timezone

    if not photo_ids:
        return 0

    apple_id = _lookup_account(account_alias, wb)
    api = _get_api(apple_id, account_alias)

    ws = _find_sheet(wb, "ICloudPhotos")
    if ws is None:
        raise RuntimeError("ICloudPhotos sheet not found — run seed_workbook() first")
    lo = _find_list_object(ws, "ICloudPhotos")
    if lo is None:
        raise RuntimeError("ICloudPhotos ListObject not found")

    id_set  = set(photo_ids)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count   = 0

    for photo in api.photos.all.photos:
        if str(photo.id) not in id_set:
            continue
        try:
            photo_id   = str(photo.id)
            filename   = str(photo.filename)
            media_type = "video" if photo.item_type == "movie" else "image"
            created    = getattr(photo, "created", None)
            created_str = created.strftime("%Y-%m-%dT%H:%M:%SZ") if created else ""
        except Exception:
            continue

        row_idx = find_table_row(ws, "ICloudPhotos", "icloud_photo_id", photo_id)
        if row_idx is not None:
            update_table_row(ws, "ICloudPhotos", row_idx, {
                "filename":    filename,
                "media_type":  media_type,
                "last_synced": now_str,
            })
        else:
            _append_table_row(lo, {
                "icloud_photo_id": photo_id,
                "account_alias":   account_alias,
                "filename":        filename,
                "created_date":    created_str,
                "media_type":      media_type,
                "album":           "",
                "local_path":      "",
                "local_hash":      "",
                "asset_id":        "",
                "last_synced":     now_str,
                "notes":           "",
            })
        count += 1
        id_set.discard(photo_id)
        if not id_set:
            break  # found everything we need

    if count:
        wb.Save()
    return count


# ---------------------------------------------------------------------------
# ensure_local
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_local(icloud_photo_id: str, wb) -> str:
    """Return local path for a photo, downloading from iCloud if needed.

    The cached file lives at media/cache/<filename> relative to showbuilder/.
    Updates local_path and local_hash in the ICloudPhotos table.
    Returns the absolute local path.
    """
    ws = _find_sheet(wb, "ICloudPhotos")
    if ws is None:
        raise RuntimeError("ICloudPhotos sheet not found")

    row_idx = find_table_row(ws, "ICloudPhotos", "icloud_photo_id", icloud_photo_id)
    if row_idx is None:
        raise RuntimeError(f"icloud_photo_id {icloud_photo_id!r} not in ICloudPhotos table")

    rows = _read_table(ws, "ICloudPhotos")
    row = rows[row_idx - 1]  # DataBodyRange is 1-based
    local_path_rel = _str(row.get("local_path"))
    filename       = _str(row.get("filename"))
    account_alias  = _str(row.get("account_alias"))

    os.makedirs(_CACHE_DIR, exist_ok=True)
    abs_path = os.path.join(_CACHE_DIR, filename)

    # Check if cached file still intact
    if local_path_rel and os.path.isfile(abs_path):
        stored_hash = _str(row.get("local_hash"))
        if stored_hash and _sha256_file(abs_path) == stored_hash:
            return abs_path
        # File on disk doesn't match stored hash — re-download

    # Download
    apple_id = _lookup_account(account_alias, wb)
    api = _get_api(apple_id, account_alias)

    photo = None
    for p in api.photos.all.photos:
        if str(p.id) == icloud_photo_id:
            photo = p
            break
    if photo is None:
        raise RuntimeError(f"Photo {icloud_photo_id!r} not found in iCloud account {account_alias!r}")

    print(f"Downloading {filename} ...")
    data = photo.download()
    if data is None:
        raise RuntimeError(f"download() returned None for {filename!r} — no 'original' version available")
    with open(abs_path, "wb") as f:
        f.write(data)

    file_hash = _sha256_file(abs_path)
    rel_path  = os.path.join("media", "cache", filename)

    update_table_row(ws, "ICloudPhotos", row_idx, {
        "local_path": rel_path,
        "local_hash": file_hash,
    })
    wb.Save()
    return abs_path


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------

def clear_cache(wb, account_alias: str | None = None) -> int:
    """Delete cached local files and clear local_path/local_hash in the table.

    If account_alias is given, only that account's files are cleared.
    Returns count of rows cleared.
    """
    ws = _find_sheet(wb, "ICloudPhotos")
    if ws is None:
        return 0

    rows = _read_table(ws, "ICloudPhotos")
    count = 0
    for i, d in enumerate(rows, start=1):
        if account_alias and _str(d.get("account_alias")) != account_alias:
            continue
        local_path_rel = _str(d.get("local_path"))
        if not local_path_rel:
            continue
        abs_path = os.path.join(_SB_DIR, local_path_rel)
        if os.path.isfile(abs_path):
            os.remove(abs_path)
        update_table_row(ws, "ICloudPhotos", i, {"local_path": "", "local_hash": ""})
        count += 1

    if count:
        wb.Save()
    return count


# ---------------------------------------------------------------------------
# register_as_asset
# ---------------------------------------------------------------------------

def register_as_asset(icloud_photo_id: str, wb) -> str:
    """Download if needed, create an Assets row, write asset_id back.

    asset_id is derived as 'A_' + first 12 chars of SHA-256(icloud_photo_id).
    Returns the new asset_id.
    """
    ws_photos = _find_sheet(wb, "ICloudPhotos")
    if ws_photos is None:
        raise RuntimeError("ICloudPhotos sheet not found")

    row_idx = find_table_row(ws_photos, "ICloudPhotos", "icloud_photo_id", icloud_photo_id)
    if row_idx is None:
        raise RuntimeError(f"icloud_photo_id {icloud_photo_id!r} not in ICloudPhotos table")

    rows = _read_table(ws_photos, "ICloudPhotos")
    row = rows[row_idx - 1]

    # Return existing asset_id if already registered
    existing_asset_id = _str(row.get("asset_id"))
    if existing_asset_id:
        return existing_asset_id

    abs_path = ensure_local(icloud_photo_id, wb)
    rel_path = os.path.join("media", "cache", _str(row.get("filename")))
    media_type = _str(row.get("media_type"))
    filename   = _str(row.get("filename"))
    title      = os.path.splitext(filename)[0]

    asset_id = "A_" + hashlib.sha256(icloud_photo_id.encode()).hexdigest()[:12]

    ws_assets = _find_sheet(wb, "Assets")
    if ws_assets is None:
        raise RuntimeError("Assets sheet not found")
    lo_assets = _find_list_object(ws_assets, "Assets")
    if lo_assets is None:
        raise RuntimeError("Assets ListObject not found")

    _append_table_row(lo_assets, {
        "asset_id":            asset_id,
        "asset_type":          media_type,
        "src":                 rel_path,
        "title":               title,
        "default_duration_ms": "",
        "metadata_json":       f'{{"icloud_photo_id":"{icloud_photo_id}"}}',
        "enabled":             "TRUE",
        "notes":               "",
    })

    update_table_row(ws_photos, "ICloudPhotos", row_idx, {"asset_id": asset_id})
    wb.Save()
    return asset_id
