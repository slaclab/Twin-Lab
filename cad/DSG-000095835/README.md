# DSG-000095835 — offline assembly

Run from the repository root:

```bash
uv run slac-run 95835
```

which runs `python cad/DSG-000095835/build.py --view`.

This builds the model and its convex collision meshes, then opens the interference
viewer. Parts are drawn in their STEP colours, face by face. Collision checking
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
  it as fully down.) The jet adapter `P011` carries the long jet
  `DSG-000022427` (`A008`). The 2026-11-04 14:01 export had swapped it for jet
  holder `DSG-000108486` and tube `DSG-000005121`; the 2026-11-12 export restores
  it, and its 17 non-fastener parts ride the lift as in the earlier review.
- **Bottom slit y/x** and **Top slit y/x** drive the two slit towers (`A011`,
  `A017`): a LIB-000032451 vertical lift (±4 mm) carrying an XA05A-R202 (±7.5 mm)
  that holds the blade rod. The blade holder `DSG-000000720` and its two blade
  plates are clamped to each rod tip and ride the X stage (`P537/P461/P462`
  bottom, `P220/P459/P460` top), although the STEP files them under the chamber.
- The user-supplied controls envelope (`P734`) and its four support posts ride the
  Parker vertical lift plate (`P698`) and participate in interference checks. This
  STEP revision replaces the earlier `DSG-000108873` XCS Von Hamos Controls
  assembly with that single envelope.
- **ePix10k z/x/y** drive the detector assembly `LCL5005-008450` on its two Newport
  IMS300CC slides and a Kohzu ZA16A-W2C01 wedge Z stage. Each fused slide is
  split at its carriage plate, and its 300 mm travel is assumed centred on the
  carriage position the fused slide models.
  - The 2026-11-04 14:01 STEP moved everything on the lower (z) carriage
    80.1151 mm along world −Y, which needed a `moving_offset_mm` on the carriage.
    The 2026-11-12 STEP puts the payload back where the earlier 93ae4dc6 STEP had
    it, on the carriage, so no offset is needed and z and x both run ±150 mm.
  - **y:** the ZA16A (`P1138`, Kohzu's own nine-solid STEP) sits on adapter
    `P1802` above the x carriage and lifts the detector along world +Z, ±8 mm.
    Its table (solid 1) carries frame `LCL5010-008490` (`P1751`) and everything
    on it. It is a wedge actuator: the 1/4 wedge (solids 6–7) slides 4 mm
    forward (world +Y, towards the chamber) for every 1 mm the table rises. At
    +8 mm it sticks 29 mm out of the stage's front, as in Kohzu's drawing. The
    wedge has its own joint, `detector_y_wedge_joint`, with no slider. Both
    viewers and validation set it from ePix10k y, so the table never separates
    from or sinks into the wedge. The base, feet and motor stay on the x slide.
    Kohzu's drawing puts the table 80 ± 8 mm above the mounting face, and the CAD
    table face is at 80.0 mm, so the CAD pose is mid-travel.
  - The detector keeps its parts at least 100 mm across, including the new front
    plate `mo39134025` (`P1374`); smaller parts and electronics are omitted.
- **ePix100 y/x/z/tilt** drive the smaller, upward-facing ePix100 (module
  `mo39154223` in `DSG-000042618`, sensor `P255`). Since the 2026-11-12 export
  every stage is a multi-part model. The stack, from fixed block `P229` up, is:
  - **y:** a manual Newport M-EL80 lab jack (`LIB-000033108`) along world +Z,
    covering Newport's full 53–113 mm (−59.2/+0.8 mm about the CAD pose). The
    jack is drawn 112.2 mm high, near the top of its travel.
    - It is a single scissor. Arm A (`P350`) is pinned to the base plate (`P349`)
      and its other end rides top block `P353`. Arm B (`P351`) is pinned to the top
      plate (`P348`) and rides bottom block `P354`. The arms cross at centre pin
      `P355`.
    - The knob and screw (`P352`) ride the top plate and drive `P353` as a nut.
    - The arms are 103.581 mm between pivots, at 56.24° as drawn. The arms and
      blocks follow the top plate by the exact scissor relation: each arm turns by
      asin((rise + y)/arm) − 56.24°, and each block slides by the change in
      arm·cos.
    - Every pin stays seated over the whole stroke. The library CAD is drawn
      tighter than the real jack, though. At the drawn height the arms' sliding
      ends already cut 1.5 mm into the plates' channels. Below 72.8 mm arm B
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

The retained model uses 403 of the 1,851 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 1,448 omitted occurrences
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

The chamber `P546` is red in the STEP, the same hue as a contact highlight.
Highlights are drawn on the part's collision hulls, which bulge slightly beyond
the CAD surface.

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
mounting configuration. The physical mounting holes also permit 5 and 0 degrees.
Those alternative placements have not been verified or exposed as viewer options.
STEP exports of the 0 and 5 degree configurations, with the same assembly frame
and unchanged motor-stage positions, can establish the exact rigid placements
for a discrete selector. No hole constraint solver is required once those
placements are known; both rotation and translation must be preserved.

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
(`P558` against the controls envelope `P734`), and checks that returning home clears it.

**The 2026-11-12 STEP is not clear at home.** Everything outside chamber assembly
`DSG-000102548` (spectrometer, cage, table and the ePix10k assembly) sits
67.818 mm lower than in the 14:01 STEP. That puts the ePix10k frame
`LCL5010-008490` (`P1751`) and plate `DSG-000007278` (`P1759`) into chamber part
`REF-000062451` (`P464`, under `DSG-000000413`). The overlap is 4.3 cm³ and 1.0
cm³; the frame's underside is now 15.5 mm below that part's top, where the 14:01
STEP had it 52 mm above. The ePix10k front plate `P1374` is 0.91 mm from the
chamber `P546`. The viewer shows this contact. The home regressions list the two
pairs as `allowed_pairs` until the CAD is confirmed or corrected.

Each joint was swept alone from home toward both limits, with the other joints at
home and followers coupled. Steps were 1° for rotations, 0.5 mm for the jet,
slits and ePix100 y, 2.5 mm for the Parker, crystal and ePix100 x slides, and 5 mm
for the ePix10k. Each new hull contact was checked against source CAD, and the
first CAD-confirmed contacts were then bisected on the reported part pairs:

| Joint | Usable travel from home | First contact |
| --- | --- | --- |
| Spectrometer vertical | above −37.5 mm (clear at −25 mm) to +39.70 mm | down: cage `P558` against controls envelope `P734`; up (+ is down along the tilted lift): Huber base `P965` against the ePix100 end plate `P228` |
| Analyzer rotation | −45° to +33.03° | ePix10k front plate `P1374` (and front ring `P1477` at +33.25°) against analyzer post `P974` |
| Crystal 1 rotation | −45° to below +23° | SA04B `P797` against Thorlabs post `P973` |
| Crystal 2 rotation | above −35° to +45° | SA04B `P841` against post `P973` |
| Crystal 3 rotation | above −40° to +45° | SA04B `P884` against post `P973` |
| Crystal 4 rotation | −45° to below +21° | SA04B `P927` against post `P973` |
| LJ x | −25 mm to below +11 mm | jet adapter `P011` against port flange `P438` |
| LJ z | −6.48 mm to +7.5 mm | long jet part `DSG-000011652` (`P077`) against `P369` |
| Bottom / top slit y | above −1.72 mm to +4 mm | Z carriage `P111`/`P160` against bracket `P113`/`P162` |
| ePix10k z, x, y | none from home | the home interference with `P464` above; at +5 mm z the front plate also reaches the chamber `P546`, and z must move −104.1 mm to clear `P464`; at y −8 mm the frame drops into the ePix100 breadboard `P219` |
| ePix100 x | −7.05 mm to +157.52 mm | inward: rear cover `P268` against chamber port parts `P453`/`P455`; outward: the manual stage base `P365` against the VT-50L base `P248` at its motor end |
| ePix100 tilt | −4.96° to +5.09° | arm `P250` against the swivel base `P245` (1.96 mm apart at home) |

Everything else is clear over its full travel:
- the horizontal Parker slide
- all crystal translations and tilts
- LJ y (±4 mm)
- both slit X stages
- ePix100 y (Newport's 53–113 mm, −59.2/+0.8 mm), with the M-EL80's arms and
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
