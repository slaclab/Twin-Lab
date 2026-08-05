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

import base64
import os
from pathlib import Path

from .paths import CACHE_ROOT

# The LCLS roundel: a cardinal disc, an undulator magnet row above and below, and the
# electron beam oscillating between them. Drawn as SVG so the tab icon stays sharp, and
# clipped to the disc so the outer magnets read as wedges against the rim.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><clipPath id="disc"><circle cx="32" cy="32" r="31"/></clipPath></defs>'
    '<circle cx="32" cy="32" r="31" fill="#8c1515"/>'
    '<g clip-path="url(#disc)">'
    '<g fill="#fff">'
    '<path d="M3 17L16 12.5L16 18.5L3 23Z"/>'
    '<path d="M18.5 12L30.5 9.6L30.5 15.6L18.5 18Z"/>'
    '<path d="M33.5 9.6L45.5 12L45.5 18L33.5 15.6Z"/>'
    '<path d="M48 12.5L61 17L61 23L48 18.5Z"/>'
    "</g>"
    '<g fill="#fff" transform="matrix(1 0 0 -1 0 64)">'
    '<path d="M3 17L16 12.5L16 18.5L3 23Z"/>'
    '<path d="M18.5 12L30.5 9.6L30.5 15.6L18.5 18Z"/>'
    '<path d="M33.5 9.6L45.5 12L45.5 18L33.5 15.6Z"/>'
    '<path d="M48 12.5L61 17L61 23L48 18.5Z"/>'
    "</g>"
    '<path d="M2 32q3.75-18 7.5 0t7.5 0t7.5 0t7.5 0t7.5 0t7.5 0t7.5 0" fill="none" '
    'stroke="#fff" stroke-width="4" stroke-linecap="round"/>'
    "</g></svg>"
)

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

# Solid Edge is the CAD everyone here already knows, so its view bindings win: wheel
# zooms, wheel button orbits, shift plus wheel button pans. OrbitControls already sends
# a shifted ROTATE drag to pan, so the mapping is one assignment.
CONTROLS_JS = """
window.addEventListener("load", function () {
  var THREE = window.MeshCat && window.MeshCat.THREE;
  if (!THREE) {
    console.warn("Twin-Lab: MeshCat.THREE is unavailable; view controls left as Drake's.");
    return;
  }
  // Meshcat's own helpers are sized independently of the model, and the grid alone is
  // tens of metres across, so they must not drag the zoom limit out with them.
  var HELPERS = { Grid: 1, Axes: 1, Background: 1, Lights: 1, Cameras: 1 };
  var radius = 0;
  var measuredAt = 0;
  var override = { "Zoom limit override": false };

  // Bounding the model walks every mesh, so the result is reused between wheel ticks
  // while Drake is still streaming geometry in.
  function modelRadius() {
    if (radius > 0 && Date.now() - measuredAt < 5000) return radius;
    measuredAt = Date.now();
    var box = new THREE.Box3();
    viewer.scene.children.forEach(function (child) {
      if (!HELPERS[child.name]) box.expandByObject(child);
    });
    if (!box.isEmpty()) radius = box.getSize(new THREE.Vector3()).length() / 2;
    return radius;
  }

  function apply() {
    var controls = viewer.controls;
    var camera = viewer.camera;
    if (!controls || !camera || !camera.isPerspectiveCamera) return;
    controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.ROTATE,
                              RIGHT: THREE.MOUSE.PAN };
    if (override["Zoom limit override"]) {
      controls.minDistance = 0;
      controls.maxDistance = Infinity;
      return;
    }
    var size = modelRadius();
    if (size <= 0) return;
    // Past the near plane geometry clips anyway, and at four times the distance that
    // fits the model it still covers a quarter of the window.
    var fit = size / Math.sin(THREE.MathUtils.degToRad(camera.fov) / 2);
    controls.minDistance = camera.near * 2;
    controls.maxDistance = Math.min(camera.far / 2, fit * 4);
    controls.update();
    viewer.set_dirty();
  }

  if (viewer.gui) viewer.gui.add(override, "Zoom limit override").onChange(apply);

  // Drake builds a fresh OrbitControls whenever the server sets a camera.
  var set_camera = viewer.set_camera.bind(viewer);
  viewer.set_camera = function (camera) { set_camera(camera); apply(); };

  var pane = viewer.dom_element;
  // Chrome opens its autoscroll widget on a middle press, which eats the orbit drag.
  pane.addEventListener("pointerdown", function (event) {
    if (event.button === 1) event.preventDefault();
  });
  pane.addEventListener("auxclick", function (event) {
    if (event.button === 1) event.preventDefault();
  });
  // The limit has to keep up with a model that is still arriving.
  pane.addEventListener("wheel", apply, true);
  apply();
});
"""

# Drake's Meshcat API can publish sliders and buttons but not checkboxes, so an on/off
# control has to leave Python as a slider that steps 0 to 1. dat.GUI does have a checkbox,
# so one is swapped into the slider's row and the slider stays hidden behind it, still
# carrying the value in both directions.
TOGGLE_JS = """
window.addEventListener("load", function () {
  if (typeof viewer === "undefined" || !viewer.gui) return;
  var swapped = {};

  function isToggle(slider) {
    return !!slider && slider.__min === 0 && slider.__max === 1 && slider.__step === 1;
  }

  function checkboxify(name) {
    var slider = viewer.gui_controllers[name];
    if (!isToggle(slider) || slider.__twinlabToggle) return;
    // dat.GUI wraps a slider's cell, so the row is not the cell's direct parent.
    var row = slider.domElement.closest("li");
    if (!row || !row.parentElement) return;
    // Drake replaces a control by name, which would otherwise leave the old checkbox
    // wired to a discarded slider.
    if (swapped[name]) viewer.gui.remove(swapped[name]);

    var state = {};
    state[name] = slider.getValue() >= 0.5;
    var toggle = viewer.gui.add(state, name);
    toggle.onChange(function (checked) { slider.setValue(checked ? 1 : 0); });
    // dat.GUI only appends, so the checkbox has to be moved back into the slider's slot.
    row.parentElement.insertBefore(toggle.__li, row);
    row.style.display = "none";
    swapped[name] = toggle;

    // The server pushes state as well; resetting to home stops the animation.
    var updateDisplay = slider.updateDisplay.bind(slider);
    slider.updateDisplay = function () {
      state[name] = slider.getValue() >= 0.5;
      toggle.updateDisplay();
      return updateDisplay();
    };
    slider.__twinlabToggle = true;
  }

  var set_control = viewer.set_control.bind(viewer);
  viewer.set_control = function (name) {
    set_control.apply(null, arguments);
    checkboxify(name);
  };
  // Controls normally arrive after load, but a fast connection can beat this listener.
  Object.keys(viewer.gui_controllers).forEach(checkboxify);
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
    patch = (
        f"<style>{PANEL_CSS}</style>\n"
        f"<script>{PANEL_JS}</script>\n"
        f"<script>{CONTROLS_JS}</script>\n"
        f"<script>{TOGGLE_JS}</script>\n"
    )
    html = html.replace("</body>", f"{patch}</body>")
    # Base64 rather than a raw data URI: the SVG carries `#` colours, which would end the
    # href at the first one.
    icon = base64.b64encode(FAVICON_SVG.encode("utf-8")).decode("ascii")
    html = html.replace(
        "</head>",
        f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{icon}">\n'
        "</head>",
    )
    # The tab title is how you tell a patched page from a stale Drake one.
    return html.replace("<title>Drake MeshCat</title>", "<title>Twin-Lab Meshcat</title>")
