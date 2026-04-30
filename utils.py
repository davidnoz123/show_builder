#!/usr/bin/env python3
"""utils.py -- lazy install-and-import helpers for show_builder.

Logging functions (log_write, log_raise, poll_log, set_poll_trace,
set_log_file, get_log_file) delegate to the project singleton from
project.py.  All package getters remain local.

Each get_X(globals_) function:
  - returns a cached module from globals_ on subsequent calls (zero overhead)
  - on first call: installs the package via pip if missing, imports, caches

Call from the function/method that needs the module, passing globals()::

    psutil    = get_psutil(globals())
    websocket = get_websocket(globals())
    win32     = get_win32com_client(globals())
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time


def install_and_import2(package: str, pip_name: str | None = None):
    """Install *pip_name* if *package* is not importable, then return the module."""
    mod = None
    try:
        mod = importlib.import_module(package)
    except ImportError as exc:
        if not str(exc).startswith("No module named"):
            raise
    if mod is None:
        print(f"Installing {pip_name or package} ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "--disable-pip-version-check", pip_name or package],
            check=True,
        )
        sleep_secs = 0.02
        while sleep_secs < 5.12:
            try:
                mod = importlib.import_module(package)
                break
            except ImportError:
                time.sleep(sleep_secs)
                sleep_secs *= 2.0
        if mod is None:
            raise RuntimeError(
                f"Failed to import '{package}' after installing '{pip_name or package}'"
            )
    return mod


def _get_pkg(globals_: dict, import_name: str, *,
             pip: str | None = None, key: str | None = None):
    """Cache-and-return pattern shared by all simple get_X() wrappers.

    *key* -- globals_ cache key; defaults to *import_name*.
    *pip* -- pip install name; defaults to *import_name*.
    """
    k = key or import_name
    ret = globals_.get(k)
    if ret is None:
        ret = install_and_import2(import_name, pip or import_name)
        globals_[k] = ret
    return ret


# ---------------------------------------------------------------------------
# pywin32 (win32com.client, win32gui, win32con)
# ---------------------------------------------------------------------------

_PYWIN32_RESTART_FLAG = "_PYWIN32_RESTARTED"


def _pywin32_install() -> None:
    """pip install pywin32, run the mandatory DLL post-install, then re-exec."""
    import glob
    print("Installing pywin32 ...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "pywin32"],
        check=True,
    )
    scripts_dir = os.path.dirname(sys.executable)
    candidates = glob.glob(os.path.join(scripts_dir, "pywin32_postinstall.py"))
    if candidates:
        print("Running pywin32 post-install ...")
        subprocess.run([sys.executable, candidates[0], "-install"])
    else:
        print("WARNING: pywin32_postinstall.py not found -- win32 DLLs may not be registered")
    print("Restarting Python to load pywin32 DLLs ...")
    os.environ[_PYWIN32_RESTART_FLAG] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _get_pywin32_module(globals_: dict, key: str, mod_name: str):
    ret = globals_.get(key)
    if ret is None:
        try:
            ret = importlib.import_module(mod_name)
        except ImportError:
            if os.environ.get(_PYWIN32_RESTART_FLAG):
                raise RuntimeError(
                    f"pywin32 was installed and Python restarted, "
                    f"but '{mod_name}' is still not importable"
                )
            _pywin32_install()   # re-execs; code below never reached
        globals_[key] = ret
    return ret


def get_win32com_client(globals_: dict): return _get_pywin32_module(globals_, "win32com_client", "win32com.client")
def get_win32gui(globals_: dict):        return _get_pywin32_module(globals_, "win32gui", "win32gui")
def get_win32con(globals_: dict):        return _get_pywin32_module(globals_, "win32con", "win32con")


# ---------------------------------------------------------------------------
# pyicloud  (optional -- ingestion tool only, not a runtime dependency)
# ---------------------------------------------------------------------------

def get_pyicloud(globals_: dict):
    return _get_pkg(globals_, "pyicloud", pip="pyicloud")


# ---------------------------------------------------------------------------
# keyring  (optional -- iCloud credential storage)
# ---------------------------------------------------------------------------

def get_keyring(globals_: dict):
    return _get_pkg(globals_, "keyring", pip="keyring")


# ---------------------------------------------------------------------------
# Logging -- delegates to the project singleton in project.py
# ---------------------------------------------------------------------------

def log_write(msg: str) -> None:
    """Write a timestamped [py] line to the log file and stdout."""
    from project import project
    project.log(msg)


def log_raise(msg: str, exc_type: type = RuntimeError) -> None:
    """log_write 'ERROR: msg', then raise exc_type(msg)."""
    from project import project
    project.log_raise(msg, exc_type)


def set_log_file(path: str) -> None:
    """Redirect log output to a different file (e.g. next to the workbook)."""
    from project import project
    project.log_file = path


def get_log_file() -> str:
    """Return the current log file path."""
    from project import project
    return project.log_file


def set_poll_trace(enabled: bool) -> None:
    from project import project
    project.set_poll_trace(enabled)


def poll_log(msg: str) -> None:
    """Write a [poll] line only when poll_trace is enabled."""
    from project import project
    project.poll_log(msg)


# ---------------------------------------------------------------------------
# Package getters
# ---------------------------------------------------------------------------

def get_numpy(globals_: dict):     return _get_pkg(globals_, "numpy")
def get_psutil(globals_: dict):    return _get_pkg(globals_, "psutil")
def get_websocket(globals_: dict): return _get_pkg(globals_, "websocket", pip="websocket-client")
def get_pillow(globals_: dict):    return _get_pkg(globals_, "PIL", pip="pillow", key="_pil")


# ---------------------------------------------------------------------------
# Progress logging
# ---------------------------------------------------------------------------

class ProgressLogger:
    """Log the first *log_first* items individually; then one summary line
    every *interval* seconds.  Call step() per iteration and done() at end.

    Usage::

        pl = ProgressLogger("scan", log_first=10, interval=3.0)
        for item in items:
            pl.step(item.name)
            process(item)
        pl.done()
    """

    def __init__(self, label: str, log_first: int = 10, interval: float = 3.0) -> None:
        self._label = label
        self._log_first = log_first
        self._interval = interval
        self._count = 0
        self._next_t = 0.0

    def step(self, msg: str = "") -> None:
        self._count += 1
        now = time.monotonic()
        if self._count <= self._log_first:
            suffix = f"  {msg}" if msg else ""
            log_write(f"{self._label} [{self._count}]{suffix}")
        elif now >= self._next_t:
            log_write(f"{self._label}: {self._count} items so far ...")
            self._next_t = now + self._interval

    def done(self, extra: str = "") -> None:
        suffix = f"  {extra}" if extra else ""
        log_write(f"{self._label}: done — {self._count} total{suffix}")


# ---------------------------------------------------------------------------
# Bootstrap helper — deferred versholn loading
# ---------------------------------------------------------------------------

def get_versholn(g=None):
    """Return the versholn module, adding sibling dir to sys.path if needed.

    Pass globals() to inject versholn into the caller's module namespace so
    subsequent ``versholn.importx(...)`` calls work without re-calling this.
    """
    import sys
    try:
        import versholn
    except ImportError:
        import pathlib
        here = pathlib.Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "versholn"
            if candidate.is_dir():
                sys.path.insert(0, str(candidate))
                break
        import versholn
    if g is not None:
        g["versholn"] = versholn
    return versholn
