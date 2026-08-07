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
import json
import math
import os
import shutil
import socket
import subprocess
import webbrowser
from pathlib import Path

from .paths import CACHE_ROOT

# The LCLS roundel, trimmed to the disc and matted onto transparency so the tab strip
# shows through rather than a white square.
FAVICON_PATH = Path(__file__).parent / "assets" / "lcls-roundel.png"

# What makes a view isometric is that the camera sits at equal angles to all three axes.
# Which of the four top corners reads as "near left" was settled by eye against the CAD
# package's own isometric, not derived: the enclosure opening is hard to pin to an axis
# from the geometry alone. Z stays positive so the camera looks down rather than up.
ISOMETRIC_DIRECTION = (1.0, -1.0, 1.0)
# A trimetric view is one where all three axes are foreshortened differently, which is
# what stops two of them reading as the same length in a still image. Swinging further
# off the front than the isometric's 45 degrees and rising less than its 35 degrees gives
# foreshortenings of 0.88, 0.58, and 0.94 on X, Y, and Z: three visibly different numbers.
TRIMETRIC_SWING_DEG = 30.0
TRIMETRIC_RISE_DEG = 20.0
# Drake's Meshcat camera has a 75 degree vertical field of view, so a sphere of radius R is
# wholly in frame from R / sin(37.5 deg) ~= 1.64 R away. The rest is margin, since an
# assembly is a box rather than a sphere and a photograph wants some air around it.
FRAMING_DISTANCE = 2.2
# Big enough to hit a corner cell with the mouse without crowding the render.
VIEW_CUBE_PX = 132


def _swing_and_rise(swing_deg: float, rise_deg: float) -> tuple[float, float, float]:
    """A unit direction ``swing_deg`` off the front face (-Y) and ``rise_deg`` above it."""

    swing = math.radians(swing_deg)
    rise = math.radians(rise_deg)
    return (
        math.sin(swing) * math.cos(rise),
        -math.cos(swing) * math.cos(rise),
        math.sin(rise),
    )


TRIMETRIC_DIRECTION = _swing_and_rise(TRIMETRIC_SWING_DEG, TRIMETRIC_RISE_DEG)

# Written as JSON rather than interpolated into the script body: the directions are
# derived here, and a second copy in the JavaScript would be free to drift from this one.
VIEW_SETTINGS_JS = (
    "window.TWINLAB_VIEWS = "
    + json.dumps(
        {
            "isometric": list(ISOMETRIC_DIRECTION),
            "trimetric": list(TRIMETRIC_DIRECTION),
            "fit": FRAMING_DISTANCE,
            "cube_px": VIEW_CUBE_PX,
        }
    )
    + ";"
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
/* dat.GUI writes the button's width inline from its own 245px, which our wider panel
   leaves it short of; !important beats that, and outlasts dat.GUI reapplying it. */
.dg.main .close-button { height: 24px !important; line-height: 24px !important;
                         width: 100% !important; }
/* Bottom left is the one corner neither the control panel nor Drake's stats plot uses,
   so the cube never has to move out of anything's way. */
#twinlab-view-cube { position: fixed; left: 12px; bottom: 12px; z-index: 8; }
#twinlab-view-cube canvas { display: block; cursor: pointer; }
/* Drake's own rtr% plot is switched off in every viewer here, so the top-left is free. */
#twinlab-fps { position: fixed; left: 12px; top: 12px; z-index: 8; pointer-events: none;
               font: 12px/1.4 monospace; color: #d8d8d8; background: rgba(26,26,26,0.6);
               padding: 3px 7px; border-radius: 3px; white-space: pre; }
"""

# Anything that has to measure the model needs the same idea of what the model is, and
# getting that wrong is invisible until the framing is quietly wrong, so there is one copy.
SCENE_JS = """
window.twinlab = window.twinlab || {};
(function () {
  // Meshcat's own helpers are sized independently of the model - the grid alone is tens of
  // metres across - so measuring the model has to leave them out.
  var HELPERS = { Grid: 1, Axes: 1, Background: 1, Lights: 1, Cameras: 1 };
  // The box comes back in three.js' own frame, which is the model frame turned Z-up to
  // Y-up by the scene's rotation.
  window.twinlab.modelBox = function () {
    var THREE = window.MeshCat.THREE;
    var box = new THREE.Box3();
    viewer.scene.children.forEach(function (child) {
      if (!HELPERS[child.name]) box.expandByObject(child);
    });
    return box;
  };
})();
"""

PANEL_JS = """
window.addEventListener("load", function () {
  var panel = document.querySelector(".dg.main");
  var list = panel && panel.querySelector(":scope > ul");
  if (!list) return;
  // dat.GUI calls this "Close Controls", but it collapses the whole side panel rather
  // than any one group of controls.
  var closeButton = panel.querySelector(".close-button");

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
    var closed = list.classList.contains("closed");
    // dat.GUI rewrites the caption on every toggle, so ours has to be reapplied here.
    if (closeButton) closeButton.innerHTML = closed ? "Show panel" : "Hide panel";
    var reserved = closed ? 0 : panel.offsetWidth;
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
  var radius = 0;
  var measuredAt = 0;
  var override = { "Zoom limit override": false };

  // Bounding the model walks every mesh, so the result is reused between wheel ticks
  // while Drake is still streaming geometry in.
  function modelRadius() {
    if (radius > 0 && Date.now() - measuredAt < 5000) return radius;
    measuredAt = Date.now();
    var box = window.twinlab.modelBox();
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

  // dat.GUI only appends, and the server's own controls arrive after this script runs, so
  // the row lands at the top of the panel and has to be moved down to the toggle it
  // belongs with once that toggle exists.
  var overrideRow = null;
  if (viewer.gui) {
    overrideRow = viewer.gui.add(override, "Zoom limit override").onChange(apply).__li;
  }

  function regroup() {
    var animation = viewer.gui_controllers && viewer.gui_controllers["Animation"];
    if (!overrideRow || !animation) return;
    var row = animation.domElement.closest("li");
    // TOGGLE_JS puts the checkbox immediately before this row, so "after" still reads as
    // directly below the animation toggle.
    if (row && row.parentElement) row.parentElement.insertBefore(overrideRow, row.nextSibling);
  }

  var set_control = viewer.set_control.bind(viewer);
  viewer.set_control = function () { set_control.apply(null, arguments); regroup(); };
  regroup();

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

# The scenes here are heavy enough that a slow viewer reads as a hung one, so the draw
# rate is worth showing. Counting viewer.render rather than requestAnimationFrame is
# deliberate: rAF keeps ticking at the display rate while a backed-up message queue
# starves the actual drawing, which is exactly the case this is meant to expose. Meshcat
# only redraws a scene that changed, so a still model legitimately draws nothing at all
# and has to say so rather than report a zero that reads as a stall.
FPS_JS = """
window.addEventListener("load", function () {
  if (typeof viewer === "undefined" || typeof viewer.render !== "function") return;
  var readout = document.createElement("div");
  readout.id = "twinlab-fps";
  readout.textContent = "idle";
  document.body.appendChild(readout);

  var frames = 0;
  var render = viewer.render.bind(viewer);
  viewer.render = function () { frames += 1; return render.apply(null, arguments); };

  var since = performance.now();
  setInterval(function () {
    var now = performance.now();
    var drawn = frames;
    var fps = drawn * 1000 / Math.max(now - since, 1);
    frames = 0;
    since = now;
    readout.textContent = drawn ? fps.toFixed(0).padStart(2, " ") + " fps" : "idle";
  }, 500);
});
"""

# Every CAD package puts a clickable cube in the corner, so this is the navigation people
# arrive already knowing. Snapping runs entirely in the browser: a round trip to Python for
# each click would make the cube feel unlike the one it is imitating, and the camera is the
# one piece of viewer state the server does not otherwise own.
VIEW_CUBE_JS = """
window.addEventListener("load", function () {
  var THREE = window.MeshCat && window.MeshCat.THREE;
  if (!THREE || typeof viewer === "undefined") {
    console.warn("Twin-Lab: MeshCat.THREE is unavailable; the view cube is off.");
    return;
  }
  var VIEWS = window.TWINLAB_VIEWS;

  // --- moving the camera ---------------------------------------------------
  // Meshcat renders the model's Z-up frame through a scene rotated into three.js' Y-up
  // one, so every direction quoted in model axes has to cross that rotation.
  function toRender(v) {
    return new THREE.Vector3(v[0], v[1], v[2]).applyQuaternion(viewer.scene.quaternion);
  }
  var MODEL_UP = toRender([0, 0, 1]);

  // The camera hangs under Cameras/default/rotated, and OrbitControls reads its position
  // and target in that parent's frame rather than the world one.
  function cameraParent() {
    var parent = viewer.camera.parent;
    parent.updateWorldMatrix(true, false);
    return parent;
  }

  function eyeInWorld() {
    return viewer.camera.getWorldPosition(new THREE.Vector3());
  }

  function targetInWorld() {
    return cameraParent().localToWorld(viewer.controls.target.clone());
  }

  function placeCamera(eye, target) {
    var parent = cameraParent();
    viewer.camera.position.copy(parent.worldToLocal(eye.clone()));
    viewer.controls.target.copy(parent.worldToLocal(target.clone()));
    viewer.controls.update();
    viewer.set_dirty();
  }

  // Straight down the up axis OrbitControls has no azimuth left to keep and the view rolls
  // to wherever it was last. A hair towards the front pins the roll instead, and lands the
  // front of the model at the bottom of the screen the way a CAD top view does.
  var POLE_NUDGE = 0.001;
  function approach(direction) {
    var dir = toRender(direction).normalize();
    if (Math.abs(dir.dot(MODEL_UP)) > 0.9999) {
      dir.addScaledVector(toRender([0, -1, 0]), POLE_NUDGE).normalize();
    }
    return dir;
  }

  // Framing is measured rather than fixed, so it follows the model as the joints move.
  function framing() {
    var box = window.twinlab.modelBox();
    if (box.isEmpty()) return null;
    var radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
    return { target: box.getCenter(new THREE.Vector3()), distance: radius * VIEWS.fit };
  }

  function lookFrom(direction, fit) {
    if (!viewer.camera || !viewer.controls) return;
    var target = targetInWorld();
    var distance = eyeInWorld().distanceTo(target);
    if (fit) {
      var framed = framing();
      if (framed) { target = framed.target; distance = framed.distance; }
    }
    if (!(distance > 1e-9)) distance = 1;
    var eye = target.clone().addScaledVector(approach(direction), distance);
    glide(eye, target);
  }

  // A jump cut loses which way the model turned, which is most of what the cube is for.
  var GLIDE_MS = 260;
  var glideToken = 0;
  function glide(eye, target) {
    var startTarget = targetInWorld();
    var startOffset = eyeInWorld().sub(startTarget);
    var endOffset = eye.clone().sub(target);
    var startLength = startOffset.length();
    var endLength = endOffset.length();
    if (startLength < 1e-9 || endLength < 1e-9) { placeCamera(eye, target); return; }
    var startDirection = startOffset.clone().normalize();
    var swing = new THREE.Quaternion().setFromUnitVectors(
      startDirection, endOffset.clone().normalize());
    var still = new THREE.Quaternion();
    var token = ++glideToken;
    var began = performance.now();
    function step() {
      if (token !== glideToken) return;
      var t = Math.min((performance.now() - began) / GLIDE_MS, 1);
      // Smoothstep, so the camera leaves and arrives at rest instead of starting at speed.
      var eased = t * t * (3 - 2 * t);
      var offset = startDirection.clone()
        .applyQuaternion(still.clone().slerp(swing, eased))
        .multiplyScalar(startLength + (endLength - startLength) * eased);
      var here = startTarget.clone().lerp(target, eased);
      placeCamera(here.clone().add(offset), here);
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // --- the cube ------------------------------------------------------------
  // The cube spans -1..1 and is cut into 26 cells: a face panel out to BAND on each axis,
  // then the rim that is left over. That makes the faces, edges, and corners fall out of
  // one loop, and each cell's own index is the direction to look from.
  var HALF = 1.0;
  var BAND = 0.62;
  var FACE_RGB = 0xe9edf2;
  var RIM_RGB = 0xc3cad3;
  var HOVER_RGB = 0xffb128;
  var OUTLINE_RGB = 0x7b8794;
  // The front of the assembly faces -Y, as it does in the CAD package, so a view named
  // here and a view of the same name there look at the same side.
  var FACE_TEXT = { "1,0,0": "RIGHT", "-1,0,0": "LEFT", "0,1,0": "BACK",
                    "0,-1,0": "FRONT", "0,0,1": "TOP", "0,0,-1": "BOTTOM" };
  // BoxGeometry's material slots, in its own order.
  var SLOTS = [[1,0,0], [-1,0,0], [0,1,0], [0,-1,0], [0,0,1], [0,0,-1]];
  // Quarter turns that stand each slot's label upright once you are looking at it. They
  // differ because three.js lays the six faces' texture coordinates out in six directions.
  var SLOT_TURNS = [1, 3, 2, 0, 0, 2];

  function labelTexture(text, quarterTurns) {
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#e9edf2";
    ctx.fillRect(0, 0, 128, 128);
    ctx.translate(64, 64);
    // The canvas y axis points down, so a turn that reads counter-clockwise is negative.
    ctx.rotate(-quarterTurns * Math.PI / 2);
    ctx.fillStyle = "#243447";
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 0, 0, 110);
    var texture = new THREE.CanvasTexture(canvas);
    if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }

  var gizmo = new THREE.Scene();
  // Turned exactly as the model's own scene is, so the cube reads in model axes.
  var cube = new THREE.Group();
  cube.quaternion.copy(viewer.scene.quaternion);
  gizmo.add(cube);
  var cells = [];

  function addCell(index) {
    var span = function (n) { return n === 0 ? BAND * 2 : HALF - BAND; };
    var offset = function (n) { return n === 0 ? 0 : n * (HALF + BAND) / 2; };
    var geometry = new THREE.BoxGeometry(span(index[0]), span(index[1]), span(index[2]));
    var rim = Math.abs(index[0]) + Math.abs(index[1]) + Math.abs(index[2]) > 1;
    var base = rim ? RIM_RGB : FACE_RGB;
    var materials = SLOTS.map(function (slot, s) {
      var outward = slot[0] === index[0] && slot[1] === index[1] && slot[2] === index[2];
      if (!outward) return new THREE.MeshBasicMaterial({ color: base });
      return new THREE.MeshBasicMaterial(
        { map: labelTexture(FACE_TEXT[index.join(",")], SLOT_TURNS[s]) });
    });
    var cell = new THREE.Mesh(geometry, materials);
    cell.position.set(offset(index[0]), offset(index[1]), offset(index[2]));
    cell.userData = { direction: index, base: base };
    // Without an outline the cells merge into one blank silhouette when seen face on.
    cell.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),
                                    new THREE.LineBasicMaterial({ color: OUTLINE_RGB })));
    cube.add(cell);
    cells.push(cell);
  }

  for (var i = -1; i <= 1; i++) {
    for (var j = -1; j <= 1; j++) {
      for (var k = -1; k <= 1; k++) {
        if (i || j || k) addCell([i, j, k]);
      }
    }
  }

  // The arrows are what makes the cube worth more than six buttons: they say which way the
  // model's own axes run in the current view. They are depth tested against the cube, so an
  // axis pointing away from you is hidden by it rather than drawn through it.
  var AXIS_RGB = [0xd1495b, 0x3aa06d, 0x3d7ea6];
  var AXIS_TEXT = ["X", "Y", "Z"];
  var AXIS_LENGTH = 1.3;

  function axisLabel(text, colour) {
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#" + ("000000" + colour.toString(16)).slice(-6);
    ctx.font = "bold 44px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 32, 32);
    var texture = new THREE.CanvasTexture(canvas);
    if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture }));
    sprite.scale.set(0.45, 0.45, 0.45);
    return sprite;
  }

  [0, 1, 2].forEach(function (axis) {
    var along = new THREE.Vector3(axis === 0 ? 1 : 0, axis === 1 ? 1 : 0, axis === 2 ? 1 : 0);
    // Cylinders and cones are born pointing along +Y.
    var turn = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), along);
    var material = new THREE.MeshBasicMaterial({ color: AXIS_RGB[axis] });
    var shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(0.045, 0.045, AXIS_LENGTH, 12), material);
    shaft.quaternion.copy(turn);
    shaft.position.copy(along.clone().multiplyScalar(AXIS_LENGTH / 2));
    var tip = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.24, 14), material);
    tip.quaternion.copy(turn);
    tip.position.copy(along.clone().multiplyScalar(AXIS_LENGTH + 0.12));
    var label = axisLabel(AXIS_TEXT[axis], AXIS_RGB[axis]);
    label.position.copy(along.clone().multiplyScalar(AXIS_LENGTH + 0.42));
    cube.add(shaft, tip, label);
  });

  var host = document.createElement("div");
  host.id = "twinlab-view-cube";
  host.title = "Click a face, edge, or corner to look from it";
  document.body.appendChild(host);
  var renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(VIEWS.cube_px, VIEWS.cube_px);
  host.appendChild(renderer.domElement);
  // Orthographic, so the cube does not gain a perspective the model does not have. The
  // frustum clears the arrow labels, which reach furthest.
  var SPAN = 1.95;
  var STANDOFF = 10;
  var gizmoCamera = new THREE.OrthographicCamera(-SPAN, SPAN, SPAN, -SPAN, 0.1, 100);

  // --- picking -------------------------------------------------------------
  var raycaster = new THREE.Raycaster();
  var pointer = new THREE.Vector2();
  var hovered = null;
  var dirty = true;

  function paint(cell, colour) {
    cell.material.forEach(function (material) {
      // A labelled slot tints its texture, so its rest colour is white, not the base one.
      if (colour !== null) material.color.setHex(colour);
      else material.color.setHex(material.map ? 0xffffff : cell.userData.base);
    });
  }

  function highlight(cell) {
    if (hovered === cell) return;
    if (hovered) paint(hovered, null);
    hovered = cell;
    if (hovered) paint(hovered, HOVER_RGB);
    dirty = true;
  }

  function cellAt(event) {
    var rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, gizmoCamera);
    // Not recursive: the outlines and arrows are not places to click.
    var hits = raycaster.intersectObjects(cells, false);
    return hits.length ? hits[0].object : null;
  }

  renderer.domElement.addEventListener("pointermove", function (event) {
    highlight(cellAt(event));
  });
  renderer.domElement.addEventListener("pointerleave", function () { highlight(null); });
  renderer.domElement.addEventListener("click", function (event) {
    var cell = cellAt(event);
    // Distance is left alone, so clicking round the cube turns the model rather than
    // rezooming it; the keyboard views are the ones that reframe.
    if (cell) lookFrom(cell.userData.direction, false);
  });

  // --- keeping the cube pointed where the camera is ------------------------
  var shown = new THREE.Quaternion(0, 0, 0, 0);
  function tick() {
    requestAnimationFrame(tick);
    if (!viewer.camera) return;
    viewer.camera.updateWorldMatrix(true, false);
    var orientation = viewer.camera.getWorldQuaternion(new THREE.Quaternion());
    if (!dirty && orientation.angleTo(shown) < 1e-4) return;
    shown.copy(orientation);
    dirty = false;
    // Same orientation and standoff direction as the real camera, so the cube shows the
    // model's attitude exactly, roll included.
    gizmoCamera.quaternion.copy(orientation);
    gizmoCamera.position.copy(
      new THREE.Vector3(0, 0, STANDOFF).applyQuaternion(orientation));
    renderer.render(gizmo, gizmoCamera);
  }
  requestAnimationFrame(tick);

  // --- keyboard ------------------------------------------------------------
  // Ctrl-I and Ctrl-T are the asked-for bindings; the unmodified keys answer too because
  // Chrome keeps Ctrl-T for its own new tab and never delivers it to the page.
  window.addEventListener("keydown", function (event) {
    if (event.altKey || event.metaKey) return;
    var target = event.target;
    if (target && (target.isContentEditable || target.tagName === "INPUT" ||
                   target.tagName === "TEXTAREA")) return;
    if (event.code === "KeyI") lookFrom(VIEWS.isometric, true);
    else if (event.code === "KeyT") lookFrom(VIEWS.trimetric, true);
    else return;
    event.preventDefault();
  });
});
"""

RESOURCE_ROOT = CACHE_ROOT / "drake-resource-root"


def viewer_params(*, show_stats_plot: bool = False):
    """Build the Meshcat settings every viewer shares.

    Drake's default host and ``host="*"`` both bind the IPv6 wildcard, so the socket only
    shows up in ``/proc/net/tcp6``; VS Code scans the IPv4 table for new servers and so
    never lists the viewer under Ports. The IPv4 wildcard reaches the same places and lands
    in the table the editor reads.

    Every viewer must build its params here: when the three of them each configured their
    own, a change to one silently left the others behind.
    """

    from pydrake.geometry import MeshcatParams

    return MeshcatParams(host="0.0.0.0", show_stats_plot=show_stats_plot)


def announce_viewer(label: str, meshcat, *, open_browser: bool = True) -> None:
    """Print the viewer's localhost URL and open it.

    The URL is printed as well as opened so there is still something to click when the
    browser cannot be launched, and it is built here rather than taken from ``web_url()``,
    which reports whatever host the server bound to.
    """

    url = f"http://localhost:{meshcat.port()}"
    print(f"{label}: {url}")
    address = wsl_ipv4_address()
    if address is not None:
        print(f"From another machine: http://{address}:{meshcat.port()}")
    if open_browser:
        open_in_browser(url)


def print_view_help() -> None:
    """Describe the browser-side navigation, which no Meshcat control advertises."""

    print(
        "View cube, bottom left: click a face, edge, or corner to swing the camera onto "
        "it. The red, green, and blue arrows are the model's X, Y, and Z axes."
    )
    print(
        "Ctrl-I frames the model isometrically and Ctrl-T trimetrically. Chrome keeps "
        "Ctrl-T for its own new tab, so plain I and T do the same and always land."
    )


def open_in_browser(url: str) -> None:
    """Show ``url`` in the desktop browser, falling back to the printed link in silence.

    WSL has no Linux browser to hand the URL to, so it goes to the Windows default browser
    instead; ``explorer.exe`` exits non-zero even when it worked, so its status is ignored.
    """

    if "WSL_DISTRO_NAME" in os.environ:
        launcher = shutil.which("wslview") or shutil.which("explorer.exe")
        if launcher is not None:
            subprocess.run(
                [launcher, url],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
    try:
        webbrowser.open(url)
    except (webbrowser.Error, OSError):
        pass


def wsl_ipv4_address() -> str | None:
    """Return this WSL distro's LAN address, or ``None`` when not running under WSL."""

    if "WSL_DISTRO_NAME" not in os.environ:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("1.1.1.1", 53))
            address = str(connection.getsockname()[0])
            return address if not address.startswith("127.") else None
    except OSError:
        return None


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
        f"<script>{VIEW_SETTINGS_JS}</script>\n"
        f"<script>{SCENE_JS}</script>\n"
        f"<script>{PANEL_JS}</script>\n"
        f"<script>{CONTROLS_JS}</script>\n"
        f"<script>{TOGGLE_JS}</script>\n"
        f"<script>{FPS_JS}</script>\n"
        f"<script>{VIEW_CUBE_JS}</script>\n"
    )
    html = html.replace("</body>", f"{patch}</body>")
    # Inlined rather than served as a sibling file: Drake only maps meshcat.html onto its
    # resource root, so a relative icon href would 404.
    icon = base64.b64encode(FAVICON_PATH.read_bytes()).decode("ascii")
    html = html.replace(
        "</head>",
        f'<link rel="icon" type="image/png" href="data:image/png;base64,{icon}">\n</head>',
    )
    # The tab title is how you tell a patched page from a stale Drake one.
    return html.replace("<title>Drake MeshCat</title>", "<title>Twin-Lab Meshcat</title>")
