"""player.py -- PlayerTargetManager and PlayerController.

PlayerTargetManager finds or creates a Chrome tab at the ShowBuilder
player URL using the shared CDPClient passed in from AppRuntime.

PlayerController wraps Runtime.evaluate calls for the JS API exposed
by showbuilder/player/app.js.
"""

import json
import time

from _vx import CDPClient, CDPSession, _log


class PlayerTargetManager:
    """finds or creates the ShowBuilder player tab in the shared Chrome instance."""

    _URL_PREFIX = "http://127.0.0.1:7100/"

    def __init__(self, cdp: CDPClient) -> None:
        self._cdp = cdp

    def get_or_create_tab(self) -> CDPSession:
        target_id = self._find()
        if target_id is None:
            _log("PlayerTargetManager: no player tab found -- creating")
            result    = self._cdp.send("Target.createTarget", {"url": self._URL_PREFIX})
            target_id = result["targetId"]
            deadline  = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                targets = self._cdp.send("Target.getTargets").get("targetInfos", [])
                if any(t["targetId"] == target_id for t in targets):
                    break
                time.sleep(0.2)
        else:
            _log(f"PlayerTargetManager: found existing player tab {target_id[:16]}... -- reloading")
            # Reload so the tab always picks up the latest app.js/index.html.
            session = CDPSession(self._cdp)
            session.attach(target_id)
            session.send("Page.reload", {})
            time.sleep(0.5)  # give the page a moment to start loading

        session = CDPSession(self._cdp)
        session.attach(target_id)
        _log("PlayerTargetManager: session attached")
        return session

    def _find(self) -> str | None:
        result = self._cdp.send("Target.getTargets")
        for t in result.get("targetInfos", []):
            if t["type"] == "page" and t.get("url", "").startswith(self._URL_PREFIX):
                return t["targetId"]
        return None


class PlayerController:
    """Controls the ShowBuilder player via CDP Runtime.evaluate."""

    def __init__(self, session: CDPSession) -> None:
        self._session = session

    def load_show(self, json_str: str) -> None:
        # Pass as a JS string argument so the player can JSON.parse it.
        self._eval(f"window.loadShow({json.dumps(json_str)})")

    def play(self) -> None:
        self._eval("window.playShow()")

    def pause(self) -> None:
        self._eval("window.pauseShow()")

    def stop(self) -> None:
        self._eval("window.stopShow()")

    def goto_item(self, n: int) -> None:
        self._eval(f"window.goToItem({int(n)})")

    def get_status(self) -> dict:
        result = self._session.send("Runtime.evaluate", {
            "expression":   "JSON.stringify(window.getShowStatus())",
            "returnByValue": True,
        })
        exc = result.get("exceptionDetails")
        if exc:
            desc = exc.get("exception", {}).get("description", str(exc))
            _log(f"PlayerController.get_status: JS exception: {desc}")
            return {"error": desc}
        raw = result.get("result", {}).get("value", "{}")
        try:
            return json.loads(raw)
        except Exception:
            _log(f"PlayerController.get_status: unexpected raw={raw!r}")
            return {}

    def _eval(self, expression: str) -> None:
        result = self._session.send("Runtime.evaluate", {"expression": expression})
        exc = result.get("exceptionDetails")
        if exc:
            desc = exc.get("exception", {}).get("description", str(exc))
            _log(f"PlayerController._eval: JS exception: {desc}  expr={expression[:80]!r}")
