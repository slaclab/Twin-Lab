# DSG-000095835 — offline assembly

Run from the repository root:

```bash
uv run python cad/DSG-000095835/build.py --view
```

This builds the model and its convex collision meshes, then opens the interference
viewer. Collision checking starts enabled with neutral CAD colors and a zero
warning band: convex-hull contact candidates are highlighted red by default.
**Collision accuracy check** starts off; enable it to refine candidates against
the source CAD. Hull contacts can be false positives, including at home.
Increase the clearance warning band to enable yellow near-clearance highlights. Stage sliders, animation,
and reset to the CAD pose remain available. The first collision build is slow;
subsequent builds reuse the cached decompositions.

The source STEP remains at `cad/DSG-000095835.stp` and is ignored for now. The
assembly scripts, manifest, and reviews are intended for version control;
no shared source files or stage catalog were changed.
Generated geometry lives in `.cache/twin_lab/`; SDF and MATLAB exports live in
`exports/DSG-000095835/`.

## Included motion

The model has 13 rigid bodies and 12 active joints:

- **Spectrometer vertical** and **Spectrometer horizontal** control the two
  large 100 mm Parker/Daedal slides. Both sliders run from −50 to +50 mm.
- The Huber 410 rotation carries the common analyzer frame and all three stacks.
- Each crystal stack has a 70 mm Kohzu XA07A-L201 translation, RA04A-W rotation
  (±177°), and SA04B-RM01 tilt (±10°). Each tilt rotates about its remote center
  74 mm above its local mounting plane.
- The supplied STEP contains three `mo39154771` crystal stacks (`A081/A082/A083`).
  All three stage chains and crystal payloads are retained at their CAD placements;
  an additional stack would require an updated source assembly.
- The outer structural cage (`A047`, 68 non-fastener members) is fixed geometry
  included in interference checks. The inner analyzer cage rotates with the Huber.
- LJ stages remain fixed. Their four former auxiliary controls are disabled.
- The top electronics (`P1221`) and seven rigid support parts ride the Parker
  vertical lift plate (`P920`) and participate in interference checks.
- The complete `DSG-000108873` XCS Von Hamos Controls assembly (`A079`, 33 parts)
  and mounting parts `P1043/P1044` also ride the lift. These were previously
  misidentified as a flexible cable carrier; all are retained as rigid geometry.

The retained model uses 391 of the original 1,259 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 868 omitted occurrences
are listed by reason in [assembly.yaml](reviews/assembly.yaml). This removes
fasteners, detector internals, construction geometry, floor
anchors, and the diffractometer. The structural cage is retained. Mounts, outer detector
geometry, and analyzer payloads remain. The diffractometer's empty STEP leaves
are counted with other empty source geometry.

The three jet stages (`P018`, `P019`, `P020`) contain **no geometry** in the
supplied STEP. The available jet parts stay fixed; these missing stages are not
represented as working axes. Manual rotary/tilt adjustments also remain fixed.
There is no XCS connection, PV mapping, or beam configuration.

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
(`P750` against `P1035/P1040`), and checks that returning home clears it:

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
