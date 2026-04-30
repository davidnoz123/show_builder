"""excel_project.py -- ShowBuilder VBA procs and ribbon tab spec.

inject_sb_vba(drv, port) adds ShowBuilder button handlers into the
existing YTControl module so they can call SendCommand normally.

_SB_RIBBON_TAB defines the tabShowBuilder ribbon tab.
"""

from _vx import RibbonTabSpec, RibbonGroupSpec, RibbonButtonSpec


# ---------------------------------------------------------------------------
# ShowBuilder VBA procs (injected into YTControl alongside YT procs)
# ---------------------------------------------------------------------------

_SB_VBA_PROCS: dict[str, str] = {}

_SB_VBA_PROCS["SBDevPlay"] = r"""
Sub SBDevPlay(control As IRibbonControl)
    LogMsg "SBDevPlay: button clicked"
    UpdateSessionNonce
    SendCommand "{""cmd"":""dev_play"",""module"":""showbuilder""}", POLL_STATUS
    LogMsg "SBDevPlay: SendCommand returned"
End Sub
"""


# ---------------------------------------------------------------------------
# Ribbon tab spec
# ---------------------------------------------------------------------------

_SB_RIBBON_TAB = RibbonTabSpec(
    id="tabShowBuilder",
    label="Show Builder",
    groups=(
        RibbonGroupSpec(
            id="grpSBDev",
            label="Dev",
            buttons=(
                RibbonButtonSpec(
                    id="btnSBDevPlay",
                    label="Play Dev Show",
                    on_action="SBDevPlay",
                    image_mso="MediaPlay",
                    size="large",
                    screentip="Play hardcoded 3-clip show",
                    supertip="Load and play the hardcoded 3-clip YouTube show. For development only.",
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Injection helper
# ---------------------------------------------------------------------------

def inject_sb_vba(drv, port: int) -> int:
    """Add ShowBuilder VBA procs to the YTControl module in drv's workbook.

    Uses the same module as the YT procs so SBxxx handlers can call
    SendCommand, POLL_STATUS, LogMsg etc. without cross-module wiring.

    Returns the number of procs written (0 if all were already up to date).
    """
    from _vx import _DECL_TEMPLATE
    _YT_DECL_TEMPLATE = (
        _DECL_TEMPLATE
        + "Private Declare PtrSafe Function OpenProcess Lib \"kernel32\" (ByVal dwAccess As Long, ByVal bInherit As Long, ByVal dwPID As Long) As Long\r\n"
        + "Private Declare PtrSafe Function GetExitCodeProcess Lib \"kernel32\" (ByVal hProcess As Long, lpExitCode As Long) As Long\r\n"
        + "Private Declare PtrSafe Function CloseHandle Lib \"kernel32\" (ByVal hObject As Long) As Long\r\n"
        + "Private Const PROCESS_QUERY_INFORMATION As Long = &H400\r\n"
        + "Private Const STILL_ACTIVE As Long = 259\r\n"
        + "Private navStack As Collection\r\n"
        + "Private serverAvailable As Boolean\r\n"
        + "Private nextPingTime As Date\r\n"
        + "Private lastPidFileMTime As Date\r\n"
        + "Private serverPid As Long\r\n"
        + "Private pollTrace As Boolean\r\n"
        + "Private lastProbeUrl As String\r\n"
        + "Private logFilePath As String\r\n"
    )
    return drv._inject_module(port, _YT_DECL_TEMPLATE, _SB_VBA_PROCS)
