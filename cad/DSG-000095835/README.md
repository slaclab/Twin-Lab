# DSG-000095835 — offline assembly

Run from the repository root:

```bash
uv run python cad/DSG-000095835/build.py --view
```

This builds the model and its convex collision meshes, then opens the interference
viewer. Collision checking starts enabled, with clearance highlighting, stage
sliders, animation, and reset to the CAD pose. The first collision build is slow;
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
- The outer structural cage (`A047`, 68 non-fastener members) is fixed geometry
  included in interference checks. The inner analyzer cage rotates with the Huber.
- LJ stages remain fixed. Their four former auxiliary controls are disabled.
- The top electronics (`P1221`) and seven rigid support parts ride the Parker
  vertical lift plate (`P920`) and participate in interference checks.

The retained model uses 356 of the original 1,259 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 903 omitted occurrences
are listed by reason in [assembly.yaml](reviews/assembly.yaml). This removes
fasteners, detector internals, cable carriers, construction geometry, floor
anchors, and the diffractometer. The structural cage is retained. Mounts, outer detector
geometry, and analyzer payloads remain. The diffractometer's empty STEP leaves
are counted with other empty source geometry.

The three jet stages (`P018`, `P019`, `P020`) contain **no geometry** in the
supplied STEP. The available jet parts stay fixed; these missing stages are not
represented as working axes. Manual rotary/tilt adjustments also remain fixed.
There is no XCS connection, PV mapping, or beam configuration.

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
assembly. The local viewer rechecks candidate pairs against the selected source
CAD solids at the current joint pose. Proven positive CAD gaps replace hull
overlaps; touching, penetrating, or unmeasurable pairs remain conservative hull
warnings. This check is always active in the local collision viewer and validator,
not in a generic SDF consumer. The first check loads the required CAD selections;
unchanged-pose measurements are cached. It does not exempt default-pose pairs
from checking after motion.

For a fast motion-only preview without interference checking:

```bash
uv run python cad/DSG-000095835/build.py --collision none --view
```

The motion-only viewer does not report clearances. Close older viewer processes
before relaunching, then use the URL printed by the new process.

The portable SDF can also be opened with `uv run slac-view
exports/DSG-000095835/DSG-000095835.sdf`. The matching `_matlab.sdf` and
`load_in_matlab.m` use STL visuals.
