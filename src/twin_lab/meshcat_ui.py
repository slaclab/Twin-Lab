"""Give Drake's own Meshcat page a control panel in its own scrolling column.

Drake gives the canvas the whole viewport and floats dat.GUI on top of it as a
``position: absolute`` block, so a panel taller than the window grows the document
instead of scrolling itself: the wheel then drags the whole page - canvas included -
off screen, and the canvas' ``width: 100vw`` overflows sideways by the width of the
scrollbar it just created. Drake has no hook for restyling the page, but it does honour
``DRAKE_RESOURCE_ROOT``, so we hand it a patched copy of its own ``meshcat.html``. The
fix then lands on Drake's own port and there is only ever one URL to open.
"""

from __future__ import annotations

import os
from pathlib import Path

from .paths import CACHE_ROOT

# dat.GUI's own rules are `.dg li:not(.folder)`, so the overrides need `!important`.
PANEL_CSS = """
html, body { height: 100%; width: 100%; overflow: hidden; }
/* The panel column is shorter than the window, so the gap below it needs dat.GUI's black. */
body { background: #1a1a1a; }
/* Drake sizes the canvas at 100vw, which counts the scrollbar and overflows sideways. */
#meshcat-pane { width: auto !important; max-width: 100%; height: 100vh !important;
                margin-right: var(--twinlab-panel-width, 0px); }
.dg.main { position: fixed !important; top: 0 !important; right: 0 !important;
           font-size: 13px !important; }
/* Subtract the close button, which sits below the list rather than inside it. */
.dg.main > ul { max-height: calc(100vh - 24px); overflow-y: auto; overflow-x: hidden; }
.dg.main > ul::-webkit-scrollbar { width: 8px; }
.dg.main > ul::-webkit-scrollbar-thumb { background: #4d4d4d; }
.dg.main li:not(.folder) { height: 24px !important; line-height: 24px !important; }
.dg.main li.title { height: 24px !important; line-height: 24px !important; }
.dg.main .cr .property-name { height: 24px !important; line-height: 24px !important; }
.dg.main .c { line-height: 24px !important; }
.dg.main .c input[type=text] { height: 22px !important; line-height: 22px !important;
                               font-size: 13px !important; }
.dg.main .c .slider { height: 24px !important; }
.dg.main .c select { height: 22px !important; font-size: 13px !important; }
.dg.main .close-button { height: 24px !important; line-height: 24px !important; }
"""

PANEL_JS = """
window.addEventListener("load", function () {
  var panel = document.querySelector(".dg.main");
  var list = panel && panel.querySelector(":scope > ul");
  if (!list) return;

  // Meshcat opens the scene tree by default, which alone costs a third of the window.
  Array.prototype.forEach.call(list.children, function (item) {
    if (!item.classList.contains("folder")) return;
    var body = item.querySelector(":scope > div > ul");
    var title = body && body.querySelector(":scope > li.title");
    if (title && !body.classList.contains("closed")) title.click();
  });

  // dat.GUI hard-codes 245px, which truncates slider names once the rows are scaled up.
  panel.style.width = Math.round(panel.offsetWidth * 1.2) + "px";

  // The canvas keeps the width the panel is not using, so neither one overlaps or
  // pushes the other, and the document never grows past the window.
  function fit() {
    var reserved = list.classList.contains("closed") ? 0 : panel.offsetWidth;
    document.documentElement.style.setProperty(
      "--twinlab-panel-width", reserved + "px");
    viewer.set_3d_pane_size();
  }
  new ResizeObserver(fit).observe(panel);
  new MutationObserver(fit).observe(list, { attributes: true,
                                            attributeFilter: ["class"] });
  fit();
});
"""

RESOURCE_ROOT = CACHE_ROOT / "drake-resource-root"


def patch_meshcat_page() -> None:
    """Redirect Drake's resource lookup at a patched page. Call before ``Meshcat()``."""

    if os.environ.get("DRAKE_RESOURCE_ROOT"):
        return
    try:
        os.environ["DRAKE_RESOURCE_ROOT"] = str(_build_resource_root())
    except (RuntimeError, OSError) as error:
        print(f"Meshcat UI patch unavailable ({error}); using Drake's page.")


def _build_resource_root() -> Path:
    """Mirror Drake's resource tree with symlinks, swapping in our own meshcat.html."""

    from pydrake.common import FindResourceOrThrow

    source = Path(FindResourceOrThrow("drake/geometry/meshcat.html")).resolve()
    drake = RESOURCE_ROOT / "drake"
    (drake / "geometry").mkdir(parents=True, exist_ok=True)
    for entry in source.parents[1].iterdir():
        if entry.name != "geometry":
            _link(drake / entry.name, entry)
    for entry in source.parent.iterdir():
        if entry.name != source.name:
            _link(drake / "geometry" / entry.name, entry)
    # Written via a temporary so a second viewer starting at the same time never reads
    # a half-written page.
    patched = drake / "geometry" / "meshcat.html.new"
    patched.write_text(_patched_html(source), encoding="utf-8")
    patched.replace(drake / "geometry" / source.name)
    return RESOURCE_ROOT


def _link(link: Path, target: Path) -> None:
    if link.is_symlink() and link.readlink() == target:
        return
    link.unlink(missing_ok=True)
    link.symlink_to(target)


def _patched_html(source: Path) -> str:
    html = source.read_text(encoding="utf-8")
    if "</body>" not in html:
        raise RuntimeError("Drake's meshcat.html no longer has a </body> to patch")
    patch = f"<style>{PANEL_CSS}</style>\n<script>{PANEL_JS}</script>\n"
    html = html.replace("</body>", f"{patch}</body>")
    # The tab title is how you tell a patched page from a stale Drake one.
    return html.replace("<title>Drake MeshCat</title>", "<title>Twin-Lab Meshcat</title>")
