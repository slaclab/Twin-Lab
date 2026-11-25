# DSG-000095835 — offline assembly

Run from the repository root:

```bash
uv run slac-run 95835
```

which runs `python cad/DSG-000095835/build.py --view`.

This builds the model and its convex collision meshes, then opens the interference
viewer. Parts are drawn in their STEP colours, face by face, except that red and
yellow paint is recoloured so it cannot be mistaken for a highlight (see
[Colours](#colours)). Collision checking
starts enabled with a zero warning band: convex-hull contact candidates are
highlighted red by default.
**Collision accuracy check** starts off; enable it to refine candidates against
the source CAD. Contacts present at home are the accepted baseline; see
[Verification and collision review](#verification-and-collision-review).
Increase the clearance warning band to enable yellow near-clearance highlights. Stage sliders, animation,
and reset to the CAD pose remain available. The first collision build is slow;
subsequent builds reuse the cached decompositions.

The source STEP lives at `cad/DSG-000095835/source.stp` and is ignored for now. The
assembly scripts, manifest, and reviews are intended for version control;
no shared source files or stage catalog were changed.
Generated geometry lives in `.cache/twin_lab/`; SDF and MATLAB exports live in
`exports/DSG-000095835/`.

## Offline ePix100 spectroscopy preview

```bash
uv run slac-run 95835 --spectroscopy
```

The preview uses the existing liquid-jet interaction datum (the fixed CAD world
origin), all four concave crystal faces in the reviewed mounting, and the
upward-facing ePix100 sensor. It resolves the active faces from the local STEP
cache and follows the spectroscopy stage sliders. The jet sliders move the CAD
solids without moving the fixed interaction point. The slits stay at their CAD
pose without sliders; they do not mask rays in this preview. The separate
spectroscopy export omits the downstream ePix10k2M scattering detector, its
dedicated mounts, and its stage controls. Spectroscopy also omits the stage
animation and zoom-limit override controls. The spectroscopy export and viewer
enforce **-6.5 mm** as the **ePix100 x** lower limit. The y and z limits and the
regular assembly viewer are unchanged.
This mode does not check collisions or connect to motors.

Start with **Fe K&beta;1,3 + Ge(620)**, based on the Fe K&beta; setup in
[Antolini et al.](https://doi.org/10.3390/molecules29102323). Use the two menus
to pick a line and a reflection independently. The lines come from the
[XCS standard configuration](https://lcls.slac.stanford.edu/instruments/xcs/standard-configurations);
each represents one photon energy from the
[NIST transition tables](https://www.nist.gov/pml/x-ray-transition-energies-database).
K&alpha; uses K&alpha;1, and the K&beta;2,5 presets are nominal valence-to-core
energies, not sample-specific peaks. Crystal presets are examples, not an
inventory of installed optics. A named reflection already specifies its lattice
planes and uses order 1; select **Custom d-spacing / order** to enter a spacing
and apply a separate integer order. The selected reflection applies to all four.

### Experiment planner

Select an emission line, set the requested span below and above it, and click
**Compare reflections here**. **Use published Fe band** fills in the 7030–7125 eV
window in the XCS Fe example. The comparison evaluates the named reflections
at the current CAD pose and Bragg half-width without moving the stages. It checks
21 evenly spaced energies, including both endpoints (one energy for a zero-width
band). These are discrete samples, not a guarantee of continuous coverage.

The matching published XCS setup is listed first; the other options are sorted
by the number of energies where all four crystals place at least 80% of their
accepted samples on the sensor, then by the number of crystal/energy pairs with
hits and the minimum edge distance. Select a row to see the per-crystal coverage
strip and color-coded centroids on the detector. **Use reflection in simulator**
changes only the reflection selection. Change a stage or apply an alignment
preview, then compare again to assess the new pose.

Ge(620) is documented at XCS for Fe; [Si(440) is a precedent on the LCLS
16-crystal instrument](https://biology-lcls.slac.stanford.edu/capabilities/spectroscopy).
The Co setup notes name **Si(533)** for K&beta;1,3 (about 7649 eV, 78.11 degrees)
and **Ge(444)** for valence-to-core K&beta;2,5 (about 7705 eV, 80.13 degrees),
both with a 250 mm radius. The other Si and Ge presets are geometric candidates.
Every preset uses the same 250 mm CAD crystal shapes. The 500 mm Ge(111)
suggestion is not simulated; it needs separate geometry and a specified order.
Capture is a geometry fraction, not a
prediction of photon counts or reflectivity. Detector gaps, real analyzer
availability, and collision clearance still need separate verification.

### Single-line trace and alignment

If the detector is blank, choose a line and click **Find starting poses**. This
tries up to four Bragg-compatible reflections at bounded stage poses. It
shortlists matching Fe/Co references first, then angles closest to 79 degrees,
a heuristic based on the 250 mm examples, not a reachability test. Select any
reflection manually and use **Auto-align preview** to search outside the
shortlist. **Compare reflections here** still evaluates the full catalog at
the current pose. Starting-pose search ranks results by how many crystals have signal
(at least 32 modeled hits), then how many capture at least 80% of their accepted
rays. Partial poses are shown when the search does not land all four crystals.
Select a candidate to preview its reflection and stage changes, then use
**Apply to simulator** to try both. Searches show which compatible reflection
they are testing and can be cancelled without moving stages. Then open
**Check band at this pose** and run **Compare reflections here**; a starting
pose is only for the selected line, not a
hardware recommendation or evidence that the reflection is in stock.

Drag a crystal, common analyzer, or ePix100 slider to see the image change. As
a quick check, from the CAD pose change **ePix100 x** to **-4 mm**: the Fe demo
centroid should move about 4 mm towards the crosshair. The table distinguishes
Bragg-accepted samples that miss the detector from cases with no Bragg rays.
The sensor image shows weighted hits in 4-by-4 pixel bins; the ring marks the
centroid and the RMS values describe the horizontal and vertical footprint.

For a **simulator-only focus example**, leave the default energy, reflection,
and Bragg half-width selected, reset to the CAD pose, and set:

| Slider | Value |
|---|---:|
| Spectrometer vertical | -19.10 mm |
| Analyzer rotation | +0.45 degrees |
| ePix100 x | +1.95 mm |
| ePix100 y | -8.30 mm |
| ePix100 z | -6.50 mm |

With the reviewed 2026-11-21 CAD, the centroid lands at about (-0.03, -0.14) mm
with RMS widths of (0.26, 0.29) mm. Crystals 1 and 2 contribute at this pose;
3 and 4 do not meet the Bragg window. These are CAD slider offsets, not
motor setpoints or a clearance-checked path.

Select a line and reflection, then click **Auto-align preview**. It searches for a
shared spot from all four crystals. It varies
translation, rotation, and tilt on each crystal, the common spectrometer
slides and analyzer rotation, and ePix100 x/y/z and tilt (19 axes total).
It samples the allowed ranges and refines promising poses; it does not
enumerate all combinations. Both searches score each trial with the full
256-by-256 ray grid on each crystal they evaluate, just like the live trace.
A proposed auto-align pose must retain signal from every
crystal and capture at least 80% of its Bragg-accepted samples.
The target defaults to the detector center; **Target u / v**
set the offset in mm on the moving sensor (positive u is right; positive v is
up). After focusing, the preview refines ePix100 x to center the weighted spot
horizontally without sacrificing hits or focus. If x travel limits the
horizontal correction, the proposed image reports the limit. The gold cross
marks the target. The detector model is a continuous
rectangle: it does not locate quadrant gaps or bad pixels.

Compare the two images, target error, and proposed slider changes before
clicking **Apply to simulator**. A pose is shown as best effort if its target
error or either RMS width exceeds 0.5 mm; this is a preview criterion, not a
hardware tolerance. The preview by itself moves nothing. Changing the target,
an optical setting, or a contributing stage invalidates the proposal. The
search does not check clearance.

Pairs with no real Bragg angle cannot be searched. For Bragg-allowed pairs,
results depend on the starting pose, target, and
Bragg window. If the search finds no proposal, that does not prove a pose is
out of reach. A centered centroid alone does not imply a sharp four-crystal
spot; compare the RMS widths and per-crystal hit counts.

The trace assumes a point isotropic source, symmetric reflection from the
curved lattice planes, and an adjustable angular window (default &plusmn;0.05&deg;).
This window is not a measured rocking curve. The image is normalized per frame
and omits occlusion, absorption, detector response, and absolute intensity.
It is a geometry preview, not a calibrated alignment, focus prediction, or
motion safety check.

## Included motion

The model has 35 rigid bodies and 34 joints. 29 have sliders. The other five follow
a leader: the ZA16A's wedge follows ePix10k y, and the M-EL80 lab jack's two arms
and two sliding blocks follow ePix100 y:

- **Spectrometer vertical** and **Spectrometer horizontal** control the two
  large 100 mm Parker/Daedal slides. Both sliders run from −50 to +50 mm.
- The Huber 410 rotation carries the common analyzer frame and all four stacks.
  It is limited to ±45° about the CAD pose.
- The STEP contains four `mo39154771` crystal stacks (`A071`–`A074`). Each has a
  70 mm Kohzu XA07A-L201 translation, a `LIB-000032444` rotation (limited to ±45°
  about the CAD pose), and an SA04B-RM01 tilt (±10°). Each tilt rotates about its
  remote center 74 mm above its local mounting plane.
- The `LIB-000032444` rotation stages replaced the Kohzu RA04A-W in the
  2026-11-04 revision and have no solids in the STEP, so no rotation stage is
  drawn or collision-checked. Each rotation axis rides the adapter
  `mo39185433` above the stage, which kept its place in the stack.
- Stack 4's joint frames are stack 1's carried by the stack placement transform.
  The same transform reproduces stacks 2 and 3 to 0.022 mm.
- The outer structural cage (`A042`, 52 non-fastener members) is fixed geometry
  included in interference checks. The inner analyzer cage rotates with the Huber.
- **LJ x/z/y** drive the liquid jet `DSG-000007948`: Kohzu XA05A-L202-R along the
  jet (x, ±25 mm), XA05A-R202 (z, ±7.5 mm), then the ZA05A lift (y, ±4 mm). The
  lift is at mid-travel in this STEP: its carriage sits at the library's zero
  offset on its base, as both slit lifts do, and can drop more than 5 mm before
  bottoming. (The older 43841 STEP drew it 3.105 mm lower, so that review treats
  it as fully down.) The jet adapter `P011` carries jet holder `DSG-000108486`
  (`P520`) and tube `DSG-000005121` (`P521`), which ride the lift. The
  2026-11-12 export had the long jet `DSG-000022427` there instead; the
  2026-11-21 export swaps it back for the holder and tube, as in the 14:01 export.
- **Bottom slit y/x** and **Top slit y/x** drive the two slit towers (`A011`,
  `A017`): a LIB-000032451 vertical lift (±4 mm) carrying an XA05A-R202 (±7.5 mm)
  that holds the blade rod. The blade holder `DSG-000000720` and its blade
  plates are clamped to each rod tip and ride the X stage (`P511/P436` bottom,
  `P195/P434/P435` top), although the STEP files them under the chamber. The
  bottom holder's second plate `mo39143620` is not in the 2026-11-21 export.
- The user-supplied controls envelope (`P734`) and its four support posts ride the
  Parker vertical lift plate (`P698`) and participate in interference checks. This
  STEP revision replaces the earlier `DSG-000108873` XCS Von Hamos Controls
  assembly with that single envelope.
- **ePix10k z/x/y** drive the detector assembly `LCL5005-008450` on its two Newport
  IMS300CC slides and a Kohzu ZA16A-W2C01 wedge Z stage. Since the 2026-11-21
  export all three are multi-part library models, so no split masks are needed.
  - **z/x:** each IMS300CC (`LIB-000033136`) is a base and a 179 mm carriage. The
    base's carriage channel is open from 0 to 513.5 mm along its travel, and the
    library places the carriage at 167 mm, mid-channel, taken as mid-travel of the
    300 mm stroke. The upper (x) carriage `P2151` is drawn there, so x runs
    ±150 mm. The lower (z) carriage `P2149` is drawn 134.378 mm towards world +Y
    (the chamber), so z runs −284.378/+15.622 mm.
  - **y:** the ZA16A (`LIB-000033137`) sits on adapter `P2102` above the x
    carriage and lifts the detector along world +Z, ±8 mm. Its table `P2147`
    carries frame `LCL5010-008490` (`P2054`) and everything on it. It is a wedge
    actuator: the 1/4 wedge `P2146`, with its retainer `P2145`, slides 4 mm
    forward (world +Y, towards the chamber) for every 1 mm the table rises. The
    wedge has its own joint, `detector_y_wedge_joint`, with no slider. Both
    viewers and validation set it from ePix10k y; the table's and wedge's incline
    faces stay in contact, without overlap, at every height. The base `P2144` and
    its pin `P2143` stay on the x slide. Kohzu's drawing puts the table 80 ± 8 mm
    above the mounting face, and the CAD table face is at 80.01 mm, so the CAD
    pose is mid-travel.
  - The detector keeps its parts at least 100 mm across; smaller parts and
    electronics are omitted, except the 16 sensor modules `DSG-000006659` (frame,
    carrier PCB, four ASICs and sensor chip each) behind the shield window, which
    are retained so the sensor layout is visible. Their Samtec connectors stay
    omitted behind the carrier PCBs. The front plate `mo39134025` is not in the
    2026-11-21 export.
- **ePix100 y/x/z/tilt** drive the smaller, upward-facing ePix100 (module
  `mo39154223` in `DSG-000042618`, sensor `P255`). Since the 2026-11-12 export
  every stage is a multi-part model. The stack, from fixed block `P229` up, is:
  - **y:** a manual Newport M-EL80 lab jack (`LIB-000033108`) along world +Z,
    covering Newport's full 53–113 mm (±30.0 mm about the CAD pose). The
    2026-11-21 export draws the jack 83.0 mm high, mid-stroke, and turned 180°
    about world Z from the 2026-11-12 export.
    - It is a single scissor. Arm A (`P325`) is pinned to the base plate (`P324`)
      and its other end rides top block `P328`. Arm B (`P326`) is pinned to the top
      plate (`P323`) and rides bottom block `P329`. The arms cross at centre pin
      `P330`.
    - The knob and screw (`P327`) ride the top plate and drive `P328` as a nut.
    - The arms are 103.581 mm between pivots, at 33.32° as drawn. The arms and
      blocks follow the top plate by the exact scissor relation: each arm turns by
      asin((rise + y)/arm) − 33.32°, and each block slides by the change in
      arm·cos.
    - Every pin stays seated over the whole stroke. The library CAD is drawn
      tighter than the real jack, though. At 112.2 mm the arms' sliding
      ends cut 1.5 mm into the plates' channels. Below 72.8 mm arm B
      sweeps into the top plate's underside, and the top block reaches its
      channel end at 60.0 mm. So the jack's 14 parts form a reviewed
      `ignored_groups` entry: they are not checked against each other, only
      against the rest of the assembly.
  - **x:** a Micronix VT-50L-13316 stepper stage (`LIB-000033066`: base `P248`,
    carriage `P249`) along world −X. That is the 198 mm version.
    - The carriage can run 203.5 mm between hard stops: 175.5 mm towards the motor
      and 28.0 mm to the far end block. The limit switches are assumed to sit
      centred in that.
    - The carriage is therefore drawn 73.8 mm from mid-travel, and x runs
      −25.2/+172.8 mm about the CAD pose.
  - **z:** a manual stage `LIB-000033109` (base `P365`, table `P366`, micrometer
    `P367`) along world +Y. Its CAD has no end stops, so it keeps the ±6.5 mm
    used for the earlier Kohzu model.
  - **tilt:** a manual Kohzu SH05B-RM swivel `LIB-000013709` (`P245` base, `P247`
    top), ±10° about world X. It pivots about the datum sphere `P246`, where the
    base's guideway arcs are centred, level with the sensor. The top plate's arcs
    sit 0.30 mm lower, a small mating offset in the CAD.

  The detector's 10° CAD tilt comes from the wedge adapter `P222` under the
  swivel; the swivel itself is centred.
  The module's front and rear covers (`P312`/`P268`) and cooling block
  (`P295`/`P296`) are retained, with the coolant fittings and tubes, optical
  transceiver and ribbon cable that stick out of the rear face. Parts fully
  enclosed by the covers stay omitted as detector internals.

LJ, slit and detector joints use beamline axes: y is up (world +Z) and the beam
travels along −z (world −Y), so z is world +Y and x is world −X. The beam direction
is inferred from the slits sitting upstream at world +Y and the ePix10k centred on
world Y downstream. Positive slider values move along the positive beamline axis.

The retained model uses 499 of the 2,158 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 1,659 omitted occurrences
are listed by reason in [assembly.yaml](reviews/assembly.yaml). This removes
fasteners, detector internals, construction geometry, the table understructure
of `DSG-000008836` with its floor anchors, and the two flexible
chamber boots around the slit blade rods. The structural
cage is retained. Mounts, outer detector geometry, and analyzer payloads remain.
Parts with no solid geometry in the STEP are counted as empty source geometry;
the build stops if that list no longer matches the source exactly, so a
re-export that fills in a part cannot leave it hidden.

The diffractometer base `P1005` is shown as fixed geometry, about 1.2 m below
the chamber. The diffractometer body, 2θ arm, and 2θ stage (`P1006`–`P1008`)
contain only coordinate systems in this STEP, with no solids. Its goniometer
`SA-391-444-50` is not in the export at all. Nothing more of the diffractometer
can be drawn or checked, and no diffractometer motion is modelled.

The camera's rotation stage (`LIB-000032933`, `P497`/`P498`) has geometry
since the 2026-11-12 export and is held fixed with the camera mount; its second
stage (`LIB-000032929`) still has no solids. Other manual rotary/tilt
adjustments also remain fixed. There is no XCS connection, PV mapping, or beam
configuration.

## Colours

STEP files carry presentation colours, not image textures; this one has no
texture data. The build reads each leaf's face colours once per STEP revision
(`cache_geometry.py`, cached as `.cache/twin_lab/95835-inspect/colors.json`),
including colours inherited from parent assemblies and transparency. Each
selection's visual OBJ references an `.mtl` with one material per STEP colour;
split stage bodies keep the colour of the face each piece came from. Faces the
STEP leaves uncoloured take the part's most common colour, or `visual_rgba` when
the part has none. Meshcat uses the `.mtl`. The SDF `<diffuse>` and the MATLAB
STL package carry each selection's largest-area colour. Collision meshes and
their cached decompositions are unaffected. Set `visual_colors` to anything other
than `step` in the recipe to return to the flat `visual_rgba` grey.

Red and yellow are reserved for the clearance viewer's interference and
near-clearance highlights. Saturated STEP paint inside a `visual_reserved_hues`
band (red within 12 degrees, yellow 40-65 degrees: the ePix10k housing, the
Thorlabs posts, brass thumb nuts) is drawn in that band's colour (white) instead,
keeping its transparency. `visual_part_rgba` paints whole leaves, named by CAD
name without the `_oa_` suffix, to their real finish; the ePix10k ring set and
back plate, which the STEP draws yellow and olive, are black anodized, the 16
ePix10k2M sensor chips are blue, and the shield window in front of them is
smoked translucent grey. Names, unlike refs, survive a re-export; the build stops
if one no longer matches a retained part. Both keys apply only with
`visual_colors: step`. Remove either key to show the STEP colours again.

## A new STEP revision

Part references (`P###`, `A###`) are numbered in STEP traversal order, and
Solid Edge renumbers its `_oa_NN` occurrence suffixes on every export, so any
change renumbers most leaves. `assembly.yaml` pins `source_sha256`, and the build
stops on a new STEP until the review is migrated against a fresh `manifest.json`.

The 2026-11-04 migration did that as follows:

1. Matched each occurrence to its predecessor parent by parent, by CAD name
   without the `_oa_` suffix and by placement. Identical parts that moved
   together (the 0.5 mm spectrometer adjustments, the 80.1 mm ePix carriage
   shift) were paired by their common rigid shift.
2. Carried every reviewed joint frame with its stage part's world placement.
3. Re-checked every reviewed clearance in source CAD.

Parts that left the design were dropped from the review, and new parts were
reviewed by their CAD contacts.

## Mounting configurations

The supplied STEP places `DSG-000095826` on `DSG-000097481` in the 10 degree
mounting configuration (`A058`). The physical mounting holes also permit 5 and 0
degrees, and since the 2026-11-21 export the STEP carries both: a full 0 degree
copy of the spectrometer (`A075`) and a solid-less 5 degree placement (`P523`).
Both are omitted from the model, under their own `omitted_occurrences` entry.
Relative to the 10 degree placement, in world millimetres:

| Mounting | Rigid placement change |
| --- | --- |
| 0° | 10° about world −X through (y 0.000, z −19.053) |
| 5° | 5° about world −X through (y −1.260, z −18.831) |

The two axes are 1.26 mm apart, so the three mountings are discrete placements,
not positions of one hinge. They are not yet exposed as viewer options.

## Evidence and edits

- [assembly.yaml](reviews/assembly.yaml): explicit body ownership, joint tree,
  world-frame axes, pivots, limits, and omissions. Its source hash pins this
  review to the supplied STEP revision.
- [stage-research.md](reviews/stage-research.md): exact vendor models, published
  travel, links to manufacturer documentation, and remaining identity uncertainty.
- [stage-splits.yaml](reviews/stage-splits.yaml): geometric partitions for fused
  stage bodies, in their original local coordinates and millimetres.
- [geometry-review.md](reviews/geometry-review.md): split assumptions and chain
  ownership.
- [auxiliary-stages.md](reviews/auxiliary-stages.md): auxiliary mounting-plane
  and attachment checks.

All joints use the imported CAD pose as zero. Travel spans come from vendor
specifications; absolute hardware zeros and collision-free operating limits are
unverified. The Z-stage vendor variant is inferred from geometry. The fused
stage splits simplify internal bearings and remove tiny Boolean fragments.
This is a provisional motion model for local review.

## Verification and collision review

```bash
uv run python cad/DSG-000095835/validate.py
uv run python cad/DSG-000095835/view.py --once
```

The validator checks every joint's lower, zero, and upper positions against
independent rigid-transform calculations. It verifies descendants follow the
joint, unrelated bodies stay fixed, and a combined pose follows the full tree.
See [validation.md](reviews/validation.md) for the checks actually run and the
collision approximation limits.

Convex interference checking is now the default; this explicit command is equivalent:

```bash
uv run python cad/DSG-000095835/build.py --collision convex --view
```

Convex decomposition can take tens of minutes and is cached. A quicker plumbing
check uses `--collision hull`; that approximation fills concavities and is not
suitable for judging small clearances. Collision output is separate, under
`exports/DSG-000095835.collision/`. Normal viewer checks use the convex collision meshes only, without
loading CAD selections or calculating CAD distances.

Contacts present at the CAD home pose are the accepted baseline. A contact stays
hidden while its two parts keep their home relative pose, so moving the detector
does not bring back unrelated home contacts elsewhere. As soon as either part
moves relative to the other, the pair is checked again. Hull overlaps of designed
running clearances are reviewed in [assembly.yaml](reviews/assembly.yaml), each
checked against source CAD across the full travel:

- Bearing parts also list the Huber end plate `P968` (0.5 mm to the Huber body
  over ±45°), the Parker bracket `P730` (3.25 mm over ±50 mm), the slit lift
  brackets `P117/P166` (0.787 mm over ±4 mm), and the slit X-stage sensor
  brackets `P132/P181` (0.498 mm to the X carriage over ±7.5 mm).
- `ignored_pairs` lists the chamber port `P439` against each slit blade rod. Its
  hulls fill the rod bores, but the CAD keeps at least 2.73 mm around each rod at
  every corner of the slit y/x travel. Re-check these if the slit limits change.

When **Collision accuracy
check** is enabled, the local viewer rechecks candidate pairs against the selected
source CAD solids at the current joint pose. Proven positive CAD gaps replace hull
overlaps; touching, penetrating, or unmeasurable pairs remain conservative hull
warnings. Constituent solids are also checked: positive compound surface distance
alone does not prove clearance when one solid is contained within another.
The viewer's accuracy check is opt-in; the collision validator always requests it
explicitly. Generic SDF consumers do not perform it. The first accuracy check loads the required CAD selections;
measurements are cached by relative part pose, including when both parts move
together. Relative motion invalidates the measurement; default-pose pairs are
not exempt from checking after motion.

Collision queries run on a separate Drake context while the viewer handles
sliders and camera movement. Moving replaces the previous readout with
`Checking current pose...` and removes stale highlights. Only a result matching
the current pose is displayed, together with its measured check duration.
The worker keeps one query in flight and then checks the latest requested pose,
without accumulating a queue or imposing a delay proportional to the last check.
With accuracy checking enabled, cold CAD checks can take several seconds; continuous animation may remain
pending until paused. These are discrete pose checks, not swept-motion collision
detection, so fast motion between checked poses can cross an obstacle.

The collision validator uses CAD verification to exercise a known cage contact at vertical lift -50 mm
(`P534` against the controls envelope `P702`), and checks that returning home clears it.

**The 2026-11-21 STEP is clear at home**, with nothing within 1 mm. The 2026-11-12
STEP had put the ePix10k frame `LCL5010-008490` and plate `DSG-000007278` 2.3 mm
into chamber part `REF-000062451`; this export raises the ePix10k payload
61.67 mm relative to the chamber, so the home regressions no longer allow any
contact.

Each joint was swept alone from home toward both limits, with the other joints at
home and followers coupled. Steps were 1° for rotations, 0.5 mm for the jet,
slits and ePix100 y, 1 mm for ePix10k y, 2.5 mm for the Parker, crystal and
ePix100 x slides, and 5 mm for ePix10k z and x. Every pose was checked against
source CAD, and each first contact was bisected to 0.01 mm or 0.01°:

| Joint | Usable travel from home | First contact |
| --- | --- | --- |
| Spectrometer vertical | −31.38 mm to +50 mm | down: cage `P534` against controls envelope `P702` |
| Analyzer rotation | −45° to +33.43° | ePix10k `mo39152625` (`P1776`) against analyzer post `P942` |
| Crystal 1 rotation | −45° to +17.23° | SA04B `P765` against Thorlabs post `P941` |
| Crystal 2 rotation | −34.27° to +45° | SA04B `P809` against post `P941` |
| Crystal 3 rotation | −35.60° to +44.86° | SA04B `P852` against post `P941` (down) and post `P942` (up) |
| Crystal 4 rotation | −45° to +16.87° | SA04B `P895` against post `P941` |
| Crystal 1–4 tilt | −9.93° (−9.94° for crystal 3) to +10° | adapter `mo39154776` against the same adapter in the neighbouring stack: `P800`/`P887` (stacks 1 and 3), `P844`/`P930` (stacks 2 and 4) |
| LJ x | −25 mm to +9.52 mm | jet adapter `P011` against port flange `P413` |
| LJ z | −6.19 mm to +7.5 mm | jet tube `DSG-000005121` (`P521`) against port flange `P413` |
| Bottom / top slit y | −1.62 mm to +4 mm | Z carriage `P104`/`P153` against bracket `P095`/`P144` |
| ePix100 x | −6.32 mm to +157.51 mm | inward: `mo39154292` (`P319`) against chamber port part `P429`; outward: the manual stage base `P340` against the VT-50L base `P223` at its motor end |
| ePix100 tilt | −4.95° to +5.09° | arm `P225` against the swivel base `P220` |

Exact CAD distances confirm the crystal 1 rotation and tilt onsets (0.094 mm at
+17.2°, touching at +17.3°; 0.020 mm at −9.9° tilt, touching at −9.95°). The
2026-11-12 table gave +23° and a clear tilt for the same parts, which moved
rigidly with the spectrometer. The old STEP is no longer available to re-measure,
so the difference is unexplained.

Everything else is clear over its full travel:
- the horizontal Parker slide
- all crystal translations
- LJ y (±4 mm)
- both slit X stages
- ePix10k z (−284.4/+15.6 mm), x (±150 mm) and y (±8 mm), with the ZA16A wedge
  following
- ePix100 y (Newport's 53–113 mm, ±30.0 mm), with the M-EL80's arms and
  blocks following. Its 14 parts are not checked against each other
  (`ignored_groups`).
- ePix100 z (±6.5 mm)

These are single-joint sweeps. Combined poses, such as a crystal rotated toward its
neighbour, are not covered.

An earlier finding that the slit rods touch `DSG-000000720` parts at −7.5 mm was a
model error: those parts are the blade holders clamped to the rods. The analyzer
post reaches the ePix front ring again because this STEP puts the ePix10k payload
back where the 93ae4dc6 STEP had it, 80 mm further upstream than the 14:01 STEP.

```bash
uv run python cad/DSG-000095835/validate.py exports/DSG-000095835.collision --collision
```

### Targeted hull refinement

After building the convex package, run the resumable offline comparison:

```bash
.venv/bin/python cad/DSG-000095835/refine_hulls.py --dry-run
.venv/bin/python -u cad/DSG-000095835/refine_hulls.py
```

The runner selects hulls with over 2 mm measured bulge, over 0.2 mm uncovered
vertex gap, or membership in the known home-pose hull overlaps (Huber/end plate
and Parker slide base/bracket). It tries
CoACD preprocessing resolutions 200, 400, and 800, keeping automatic mesh repair
enabled. Resolution 50 remains the normal build default. Each trial grows hulls
to cover sampled CAD mesh vertices before auditing the result again.

Candidates and checkpoints live in `.cache/twin_lab/95835-redecomposition/`.
`comparison.csv` lists the best measured candidate per selection; `results.json`
records attempts, failures, and completion status. Repeating the command resumes
completed work. Changed inputs or settings require a new `--output` directory.
The runner uses one worker with two native threads, a 10 GB address-space limit,
and a 30-minute timeout per attempt. A failed selection does not stop the batch.

Recommendations require at least a 10% bulge reduction, no uncovered sampled
vertices, no more than 2% hull-volume increase, and at most 32 hulls per selection.
Escalation stops once an eligible candidate reaches 0.5 mm measured bulge.
These are tessellated-mesh checks, not a proof of continuous CAD coverage or
collision-free travel. The source remains tessellated at 0.5 mm deflection.
The runner does not modify the active hull cache, recipe, exports, or viewers;
candidate promotion still needs collision regression checks.

Build and validate the recommendations as a separate package:

```bash
.venv/bin/python cad/DSG-000095835/build.py --collision convex \
  --refinement-run .cache/twin_lab/95835-redecomposition
.venv/bin/python cad/DSG-000095835/validate.py exports/DSG-000095835.candidate --collision
```

The candidate builder checks the completed run's recipe and source hashes,
re-audits each recommended selection, and copies its conservative inflated hulls.
All other selections use the existing active hulls. It does not run CoACD or
replace the active export. The output directory must not already exist; use
`--output-dir` with a new directory for another candidate build. Candidate
`refinement.json` records source and hull hashes and the selected resolutions.
The September 11 assembly comparison, on an earlier STEP revision, passed and
reduced home-pose false-positive pairs from five to one; see
[validation.md](reviews/validation.md). That candidate was never promoted, and
its run does not match the current STEP.

For a fast motion-only preview without interference checking:

```bash
uv run python cad/DSG-000095835/build.py --collision none --view
```

The motion-only viewer does not report clearances. Close older viewer processes
before relaunching, then use the URL printed by the new process.

The portable SDF can also be opened with `uv run slac-view
exports/DSG-000095835/DSG-000095835.sdf`. The matching `_matlab.sdf` and
`load_in_matlab.m` use STL visuals.
