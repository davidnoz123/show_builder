# AGENTS.project.md — show_builder

> Read `AGENTS.md` (auto-generated) for universal base rules.  
> This file adds show_builder-specific conventions.  
> If `AGENTS.local.md` exists, it overrides everything here.

---

## Project Overview

`show_builder` is a data-driven multimedia show system for authoring and playing back
personal film archives — originally extracted from `video_annotation`.

The system supports:
- Image slides
- Local MP4 video clips
- YouTube clips (iframe API)
- Timed text overlays (title, subtitle, caption)
- Reusable nested sequences
- Effect-driven rendering (Ken Burns, zoom, pan, fade)
- Python-controlled CDP playback
- Excel as the primary authoring surface

Architecture in one line: **Excel (authoring) → Python (resolve/validate/control) → Browser (render) ← CDP (command) ← Python**

---

## REPL-Style Development

This repo uses REPL-style development. To run a module directly:

```powershell
import runpy ; temp = runpy._run_module_as_main("dump_wb")
```

Hardcode desired values directly in `main()` — do not refactor these overrides away.

---

## Module Layout Contract

Do not move classes between files or create new modules without explicit instruction.

| File | Responsibility |
|------|----------------|
| `show_builder.py` | re-export shim for `versholn.importx` consumers |
| `schema.py` | all dataclass definitions (Asset, Format, Item, Sequence, SequenceEntry, ShowbookData, TextSet, TextOverlay, Style) |
| `resolver.py` | sequence flattener and JSON emitter (`resolve`, `build_show_json`) |
| `workbook_io.py` | Excel ListObject reader/writer (`read_workbook`, `seed_workbook`, etc.) |
| `validator.py` | schema-driven validation logic |
| `db.py` | SQLite snapshot writer |
| `dump_wb.py` | CLI: snapshot Excel workbook → SQLite |
| `server.py` | HTTP command router (`ShowBuilderRouter`) |
| `player.py` | CDP player control (`PlayerTargetManager`, `PlayerController`) |
| `static_server.py` | static file server for browser player assets (`StaticFileServer`) |
| `clips.py` | YouTube segment cache and parallel clip preloader (`SegmentCache`, `ClipPreloader`) |
| `excel_project.py` | VBA ribbon injection for ShowBuilder commands |
| `icloud_tool.py` | CLI: iCloud photo ingestion into workbook |
| `icloud_sync.py` | iCloud sync helpers (metadata, download, register) |
| `utils.py` | `get_versholn`, `log_write`, COM helpers |
| `_vx.py` | cross-repo import shim (lazy, cached `__getattr__`) |
| `project.py` | project singleton |
| `player/` | browser player (index.html, app.js, styles.css, multi.html) |
| `media/` | static assets: slide PNGs; downloaded/cached MP4 clips go here too |

---

## Cross-Repo Imports

All cross-repo symbols are loaded lazily via `_vx.py`:

```python
from _vx import CDPClient, CDPSession   # in player.py
from _vx import RibbonTabSpec, ...      # in excel_project.py
from _vx import set_op_result, _log     # in server.py
```

`_vx.py` uses `versholn.importx()` internally — do not add direct cross-repo imports.

---

## Sibling Repos Required

All repos must sit in the same parent directory:

```
<parent>\
  show_builder\         ← this repo
  versholn\
  project_tools\
  chrome_tools\
  excel_tools\
  local_server_tools\
  video_annotation\     ← test drive script + showbuilder/ media directory
```

The `video_annotation/showbuilder/media/` directory currently holds the MP4 clip
assets used during test drives. `show_builder/media/` holds slide PNGs and is also
the default download target for the segment cache.

> **Future:** `video_annotation/showbuilder/` will be deleted once its assets are
> migrated and `show_builder` is the canonical media home. Requires explicit
> confirmation before deletion (~150 MB of clips).

---

## Versholn Compliance

### Module-level imports: stdlib + same-repo only

Third-party and cross-repo packages must never appear at module level.

Exception already in place: `icloud_tool.py` imports `win32com.client` **inside
`_open_wb()`** — keep it there.

### Entry-point error handling

Every `if __name__ == "__main__":` block must have a last-resort except handler:

```python
if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        _log(f"FATAL unhandled exception:\n{traceback.format_exc()}")
        raise
```

`_log` must be defined at module level before `safe_local_imports` is called:

```python
import sys
_log = lambda msg: print(msg, file=sys.stderr)
```

### `safe_local_imports` — when required

Only needed if the `__main__` block has non-stdlib imports that could raise.
Both `dump_wb.py` and `icloud_tool.py` are covered; they only do local imports
at module level after the `win32com` fix.

---

## Syntax-Check After Every Edit

```powershell
& "C:\analytics\projects\git\lexi\demos\venv\Scripts\python.exe" -m py_compile path\to\edited_file.py
```

A `SyntaxError` at module level in a background-spawned process dies silently — no log, no error visible to the user.

---

## Key Safety Rules (inherited, restated for emphasis)

1. **Never create a competing `CDPClient`** if the annotation server (port 6789) is running — two clients on the same WebSocket cause silent response corruption.
2. **`headless=False` always** — hidden Chrome windows can block silently on modal dialogs.
3. **Excel visible** — `Application.Visible = True` always when automating via COM.
4. **Never log `GITHUB_TOKEN`** or any other secret — use `"<redacted>"`.
5. **Never commit `locals.txt`** — machine-specific paths only.
