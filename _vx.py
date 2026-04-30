"""_vx.py -- import shim for show_builder.

All cross-repo imports come through this file.
"""

# noqa: F401 -- re-exports consumed by sibling modules

from utils import get_versholn, log_write as _log

_vx_cache: dict = {}
_VX_REEXPORTS = {
    "CDPClient":        "chrome_tools.CDPClient",
    "CDPSession":       "chrome_tools.CDPSession",
    "ExcelRibbon":      "excel_tools.ExcelRibbon",
    "RibbonTabSpec":    "excel_tools.RibbonTabSpec",
    "RibbonGroupSpec":  "excel_tools.RibbonGroupSpec",
    "RibbonButtonSpec": "excel_tools.RibbonButtonSpec",
    "_DECL_TEMPLATE":   "excel_tools._DECL_TEMPLATE",
    "set_op_result":    "local_server_tools.set_op_result",
    "get_op_result":    "local_server_tools.get_op_result",
    "get_session_nonce": "local_server_tools.get_session_nonce",
}


def __getattr__(name: str):
    if name in _VX_REEXPORTS:
        if name not in _vx_cache:
            get_versholn(globals())
            _vx_cache[name] = versholn.importx(_VX_REEXPORTS[name])
        return _vx_cache[name]
    raise AttributeError(name)
