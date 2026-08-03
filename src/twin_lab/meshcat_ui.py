"""Serve Drake's Meshcat page with a control panel that scrolls on its own.

Drake appends dat.GUI to ``<body>`` as a ``position: absolute`` block, so a panel
taller than the window grows the document instead of scrolling itself: the wheel
then drags the whole page - canvas included - off screen. Drake exposes no hook for
restyling its page, so this module serves a patched copy of Drake's own two assets
from a second port and points the copy back at the live Meshcat websocket.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# dat.GUI's own rules are `.dg li:not(.folder)`, so the overrides need `!important`.
PANEL_CSS = """
html, body { height: 100%; overflow: hidden; }
.dg.main { position: fixed !important; top: 0 !important; right: 0 !important; }
.dg.main > ul { max-height: calc(100vh - 20px); overflow-y: auto; overflow-x: hidden; }
.dg.main > ul::-webkit-scrollbar { width: 8px; }
.dg.main > ul::-webkit-scrollbar-thumb { background: #4d4d4d; }
.dg.main li:not(.folder) { height: 20px !important; line-height: 20px !important; }
.dg.main li.title { height: 20px !important; line-height: 20px !important; }
.dg.main .cr .property-name { height: 20px !important; line-height: 20px !important; }
.dg.main .c { line-height: 20px !important; }
.dg.main .c input[type=text] { height: 18px !important; line-height: 18px !important; }
.dg.main .c .slider { height: 20px !important; }
.dg.main .c select { height: 18px !important; }
"""

# Meshcat opens the scene tree by default, which alone costs about a third of the window.
PANEL_JS = """
window.addEventListener("load", function () {
  var panel = document.querySelector(".dg.main > ul");
  if (!panel) return;
  Array.prototype.forEach.call(panel.children, function (item) {
    if (!item.classList.contains("folder")) return;
    var body = item.querySelector(":scope > div > ul");
    var title = body && body.querySelector(":scope > li.title");
    if (title && !body.classList.contains("closed")) title.click();
  });
});
"""

_CONNECT_ANCHOR = "    url = location.toString();"


def serve_ui(meshcat, *, host: str = "0.0.0.0") -> str | None:
    """Start the patched viewer next to ``meshcat`` and return its URL, or None.

    Returns None when Drake's page no longer matches what we patch, so the caller can
    fall back to ``meshcat.web_url()`` instead of losing the viewer to a Drake upgrade.
    """

    try:
        html = _patched_html(meshcat.port())
        script = _drake_asset("meshcat.js")
    except (RuntimeError, OSError) as error:
        print(f"Meshcat UI patch unavailable ({error}); using Drake's page.")
        return None

    routes = {
        "/index.html": ("text/html; charset=utf-8", html.encode("utf-8")),
        "/meshcat.js": ("text/javascript; charset=utf-8", script),
    }
    handler = type("_PatchedMeshcatHandler", (_Handler,), {"routes": routes})
    server = _bind(handler, host, meshcat.port() + 100)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return _swap_port(meshcat.web_url(), server.server_address[1])


def _drake_asset(name: str) -> bytes:
    from pydrake.common import FindResourceOrThrow

    return Path(FindResourceOrThrow(f"drake/geometry/{name}")).read_bytes()


def _patched_html(meshcat_port: int) -> str:
    html = _drake_asset("meshcat.html").decode("utf-8")
    if _CONNECT_ANCHOR not in html or "</body>" not in html:
        raise RuntimeError("Drake's meshcat.html no longer has the expected anchors")
    # The page derives the websocket URL from its own location, which is now our port.
    html = html.replace(
        _CONNECT_ANCHOR,
        f'    url = location.protocol + "//" + location.hostname + ":{meshcat_port}/";',
    )
    patch = f"<style>{PANEL_CSS}</style>\n<script>{PANEL_JS}</script>\n"
    return html.replace("</body>", f"{patch}</body>")


def _bind(handler: type[BaseHTTPRequestHandler], host: str, preferred_port: int):
    try:
        return ThreadingHTTPServer((host, preferred_port), handler)
    except OSError:
        return ThreadingHTTPServer((host, 0), handler)


def _swap_port(url: str, port: int) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, f"{parts.hostname}:{port}", parts.path, "", ""))


class _Handler(BaseHTTPRequestHandler):
    """Serves a fixed route table only, so no request can reach the file system."""

    routes: dict[str, tuple[str, bytes]] = {}

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path in ("/", "/meshcat.html"):
            path = "/index.html"
        entry = self.routes.get(path)
        if entry is None:
            self.send_error(404)
            return
        content_type, body = entry
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass
