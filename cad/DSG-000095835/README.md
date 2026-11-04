# DSG-000095835 — offline assembly

Run from the repository root:

```bash
uv run slac-run 95835
```

which runs `python cad/DSG-000095835/build.py --view`.

This builds the model and its convex collision meshes, then opens the interference
viewer. Collision checking starts enabled with neutral CAD colors and a zero
warning band: convex-hull contact candidates are highlighted red by default.
**Collision accuracy check** starts off; enable it to refine candidates against
the source CAD. Hull contacts can be false positives, including at home.
Increase the clearance warning band to enable yellow near-clearance highlights. Stage sliders, animation,
and reset to the CAD pose remain available. The first collision build is slow;
subsequent builds reuse the cached decompositions.

The source STEP lives at `cad/DSG-000095835/source.stp` and is ignored for now. The
assembly scripts, manifest, and reviews are intended for version control;
no shared source files or stage catalog were changed.
Generated geometry lives in `.cache/twin_lab/`; SDF and MATLAB exports live in
`exports/DSG-000095835/`.

## Included motion

The model has 22 rigid bodies and 21 active joints:

- **Spectrometer vertical** and **Spectrometer horizontal** control the two
  large 100 mm Parker/Daedal slides. Both sliders run from −50 to +50 mm.
- The Huber 410 rotation carries the common analyzer frame and all three stacks.
- Each crystal stack has a 70 mm Kohzu XA07A-L201 translation, RA04A-W rotation
  (±177°), and SA04B-RM01 tilt (±10°). Each tilt rotates about its remote center
  74 mm above its local mounting plane.
- The supplied STEP contains three `mo39154771` crystal stacks (`A076/A077/A078`).
  All three stage chains and crystal payloads are retained at their CAD placements;
  an additional stack would require an updated source assembly.
- The outer structural cage (`A047`, 52 non-fastener members) is fixed geometry
  included in interference checks. The inner analyzer cage rotates with the Huber.
- **LJ x/z/y** drive the liquid jet `DSG-000007948`: Kohzu XA05A-L202-R along the
  jet (x, ±25 mm), XA05A-R202 (z, ±7.5 mm), then the ZA05A lift (y, 0 to +8 mm,
  assembled fully down). The jet adapter and long jet ride the lift.
- **Bottom slit y/x** and **Top slit y/x** drive the two slit towers (`A021`,
  `A027`): a LIB-000032451 vertical lift (±4 mm) carrying an XA05A-R202 (±7.5 mm)
  that holds the blade rod.
- The user-supplied controls envelope (`P867`) and its four support posts ride the
  Parker vertical lift plate (`P831`) and participate in interference checks. This
  STEP revision replaces the earlier `DSG-000108873` XCS Von Hamos Controls
  assembly with that single envelope.
- **ePix10k z/x** drive the detector assembly `LCL5005-008450` on its two Newport
  IMS300CC slides (±150 mm each, assumed centred at the CAD pose). Each fused slide
  is split at its carriage plate. Its 45 parts at least 100 mm across are retained;
  smaller parts and electronics are omitted.

LJ, slit and detector joints use beamline axes: y is up (world +Z) and the beam
travels along −z (world −Y), so z is world +Y and x is world −X. The beam direction
is inferred from the slits sitting upstream at world +Y and the ePix10k centred on
world Y downstream. Positive slider values move along the positive beamline axis.

The retained model uses 378 of the 1,948 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 1,570 omitted occurrences
are listed by reason in [assembly.yaml](reviews/assembly.yaml). This removes
fasteners, detector internals, construction geometry, the table assembly
`DSG-000008836` with its floor anchors, the diffractometer, and the two flexible
chamber boots around the slit blade rods. The structural
cage is retained. Mounts, outer detector geometry, and analyzer payloads remain.
Parts with no solid geometry in the STEP, including the base detector's front
and rear covers, are counted as empty source geometry.

The camera's two stages (`LIB-000032933`, `LIB-000032929`) have no geometry in
this STEP, so the camera stays fixed. Manual rotary/tilt adjustments also remain
fixed. There is no XCS connection, PV mapping, or beam configuration.

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
`exports/DSG-000095835.collision/`. No ignored contact pairs are added by this
assembly. Normal viewer checks use the convex collision meshes only, without
loading CAD selections or calculating CAD distances. When **Collision accuracy
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
(`P691` against the controls envelope `P867`), and checks that returning home clears it.
At home the STEP itself overlaps the jet adapter `P011` about 1.1 mm into the chamber
`P679`; the home checks allow that one pair through `allowed_pairs`.

CAD-verified checks at each new joint limit found these contacts, which are real
findings rather than model errors:

- Both slit lifts reach their fixed limit-switch brackets after about 1.5 mm of
  downward travel, so the CAD pose is near the bottom of their ±4 mm range.
- At −7.5 mm the slit blade rods touch fixed `DSG-000000720` parts (`P669`, `P364`).
- LJ x at +25 mm and LJ z at −7.5 mm bring the jet adapter and tube into the
  chamber walls and port.
- ePix10k z at +150 mm drives the detector into the chamber; its forward travel
  is not usable in this layout.

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
vertex gap, or membership in the five known home-pose candidate pairs. It tries
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
The September 11 assembly comparison passed and reduced home-pose false-positive
pairs from five to one; see [validation.md](reviews/validation.md). The candidate
has not been promoted to the active model.

For a fast motion-only preview without interference checking:

```bash
uv run python cad/DSG-000095835/build.py --collision none --view
```

The motion-only viewer does not report clearances. Close older viewer processes
before relaunching, then use the URL printed by the new process.

The portable SDF can also be opened with `uv run slac-view
exports/DSG-000095835/DSG-000095835.sdf`. The matching `_matlab.sdf` and
`load_in_matlab.m` use STL visuals.
