"""static_server.py -- StaticFileServer for the ShowBuilder player.

Serves showbuilder/player/ as the document root.
Serves showbuilder/media/ at the /media/ URL prefix.
Serves /api/* mutation and query endpoints for SQLite-first show authoring.

API endpoints
-------------
GET    /api/show/{seq_id}          resolve sequence → player JSON
POST   /api/asset                  insert asset row
POST   /api/item                   insert item row
POST   /api/sequence               insert sequence row
POST   /api/sequence_entry         insert sequence_entry row
PATCH  /api/sequence/{id}          update sequence metadata OR entry-list ops
PATCH  /api/item/{id}              update item columns
DELETE /api/item/{id}              delete item
DELETE /api/sequence_entry/{id}    delete sequence_entry

All /api/* endpoints read/write showbuilder.db directly via showbuilder.db module.
Request and response bodies are JSON.
"""

import json
import os
import posixpath
import threading
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

from _vx import _log


class _PlayerHandler(SimpleHTTPRequestHandler):
    """Request handler with configurable document root, /media/ mount, and /api/*."""

    _player_root: str = ""
    _media_root:  str = ""
    _db_path:     str = ""

    # ------------------------------------------------------------------
    # Path translation (static file serving)
    # ------------------------------------------------------------------

    def translate_path(self, path: str) -> str:
        # Strip query string and fragment, then URL-decode.
        path = urllib.parse.urlsplit(path).path
        path = urllib.parse.unquote(path, encoding="utf-8", errors="replace")
        # Normalise and split, discarding empty segments and ".." to prevent traversal.
        path = posixpath.normpath(path)
        parts = [p for p in path.split("/") if p and p != ".."]
        if parts and parts[0] == "media":
            return os.path.join(self._media_root, *parts[1:])
        return os.path.join(self._player_root, *parts) if parts else self._player_root

    def log_message(self, fmt: str, *args) -> None:  # suppress access log
        pass

    # ------------------------------------------------------------------
    # API routing helpers
    # ------------------------------------------------------------------

    def _api_path(self) -> list[str]:
        """Return path segments after /api/, e.g. ['show', 'SQ_clips']."""
        raw = urllib.parse.urlsplit(self.path).path
        raw = urllib.parse.unquote(raw, encoding="utf-8", errors="replace")
        parts = [p for p in raw.split("/") if p]
        return parts[1:] if parts and parts[0] == "api" else []

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, msg: str) -> None:
        self._send_json(status, {"ok": False, "error": msg})

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self):
        seg = self._api_path()
        if seg:
            self._handle_api_get(seg)
        else:
            super().do_GET()

    def _handle_api_get(self, seg: list[str]) -> None:
        if len(seg) == 2 and seg[0] == "show":
            seq_id = seg[1]
            self._api_get_show(seq_id)
        else:
            self._send_error_json(404, f"unknown API path: /{'/'.join(seg)}")

    def _api_get_show(self, seq_id: str) -> None:
        from .db import read_db
        from .resolver import resolve, build_show_json, ResolutionError
        db_path = type(self)._db_path
        data = read_db(db_path)
        resolved = resolve(data, seq_id)
        show_dict = build_show_json(resolved)
        self._send_json(200, {"ok": True, "show": show_dict})

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self):
        seg = self._api_path()
        if not seg:
            self._send_error_json(404, "not found")
            return
        body = self._read_body()
        db_path = type(self)._db_path
        resource = seg[0]

        if resource == "asset":
            from .db import insert_asset
            new_id = insert_asset(db_path, body)
            self._send_json(201, {"ok": True, "asset_id": new_id})

        elif resource == "item":
            from .db import insert_item
            new_id = insert_item(db_path, body)
            self._send_json(201, {"ok": True, "item_id": new_id})

        elif resource == "sequence":
            from .db import insert_sequence
            new_id = insert_sequence(db_path, body)
            self._send_json(201, {"ok": True, "sequence_id": new_id})

        elif resource == "sequence_entry":
            from .db import insert_sequence_entry
            new_id = insert_sequence_entry(db_path, body)
            self._send_json(201, {"ok": True, "sequence_entry_id": new_id})

        else:
            self._send_error_json(404, f"unknown resource: {resource!r}")

    # ------------------------------------------------------------------
    # PATCH
    # ------------------------------------------------------------------

    def do_PATCH(self):
        seg = self._api_path()
        if len(seg) < 2:
            self._send_error_json(400, "PATCH requires /api/<resource>/<id>")
            return
        body = self._read_body()
        db_path = type(self)._db_path
        resource, pk = seg[0], seg[1]

        if resource == "item":
            from .db import patch_item
            patch_item(db_path, pk, body)
            self._send_json(200, {"ok": True})

        elif resource == "sequence":
            # If body contains "op", it's an entry-list mutation.
            # Otherwise it's a metadata update on the sequence itself.
            op = body.pop("op", None)
            if op is not None:
                from .db import patch_sequence_entries
                result = patch_sequence_entries(db_path, pk, op, **body)
                self._send_json(200, result)
            else:
                from .db import patch_sequence
                patch_sequence(db_path, pk, body)
                self._send_json(200, {"ok": True})

        elif resource == "asset":
            from .db import patch_asset
            patch_asset(db_path, pk, body)
            self._send_json(200, {"ok": True})

        else:
            self._send_error_json(404, f"unknown resource: {resource!r}")

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self):
        seg = self._api_path()
        if len(seg) < 2:
            self._send_error_json(400, "DELETE requires /api/<resource>/<id>")
            return
        db_path = type(self)._db_path
        resource, pk = seg[0], seg[1]

        if resource == "item":
            from .db import delete_item
            delete_item(db_path, pk)
            self._send_json(200, {"ok": True})

        elif resource == "sequence_entry":
            from .db import delete_sequence_entry
            delete_sequence_entry(db_path, pk)
            self._send_json(200, {"ok": True})

        else:
            self._send_error_json(404, f"unknown resource: {resource!r}")

    # ------------------------------------------------------------------
    # OPTIONS (CORS preflight)
    # ------------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()


class StaticFileServer:
    """HTTP file server for the ShowBuilder player, media assets, and SQL API."""

    def __init__(self, root_dir: str, port: int = 7100,
                 db_path: str = "") -> None:
        """root_dir should be the showbuilder/ folder."""
        player_dir = os.path.join(root_dir, "player")
        media_dir  = os.path.join(root_dir, "media")
        os.makedirs(player_dir, exist_ok=True)
        os.makedirs(media_dir,  exist_ok=True)

        from .db import DEFAULT_DB_PATH
        resolved_db = db_path or DEFAULT_DB_PATH

        class _Handler(_PlayerHandler):
            _player_root = player_dir
            _media_root  = media_dir
            _db_path     = resolved_db

        self._httpd  = HTTPServer(("127.0.0.1", port), _Handler)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="sb-static", daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address
        _log(f"StaticFileServer: listening on http://{host}:{port}/")

    def stop(self) -> None:
        # shutdown() blocks until serve_forever() exits its poll loop.
        # Run it in a daemon thread so we don't stall the teardown path.
        # The serve thread is already daemon=True, so it will die with the
        # process regardless -- we just need to signal it to stop cleanly.
        threading.Thread(target=self._httpd.shutdown, daemon=True, name="sb-static-stop").start()
