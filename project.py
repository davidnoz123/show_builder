"""project.py -- per-repo singleton for show_builder.

Subclasses project_tools.Project to add:
  - POLL_TRACE property (for callers using utils.poll_log / utils.set_poll_trace)
  - workbook_path: resolved path to the .xlsm workbook in the repo root
"""
from utils import get_versholn

_cache: dict = {}


def __getattr__(name: str):
    if name in ("Project", "project"):
        if "Project" not in _cache:
            get_versholn(globals())
            _Base = versholn.importx("project_tools.Project")

            class Project(_Base):
                @property
                def POLL_TRACE(self) -> bool:
                    return self._poll_trace

                @property
                def workbook_path(self) -> str:
                    """Path to the first .xlsm file found in the repo root."""
                    import glob
                    candidates = glob.glob(
                        __import__("os").path.join(self.root, "*.xlsm")
                    )
                    if not candidates:
                        raise FileNotFoundError(
                            f"No .xlsm workbook found in {self.root!r}"
                        )
                    return candidates[0]

            _cache["Project"] = Project
            _cache["project"] = Project()
        return _cache[name]
    raise AttributeError(name)
