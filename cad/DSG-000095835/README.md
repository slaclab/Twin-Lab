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

The model has 28 rigid bodies and 27 active joints:

- **Spectrometer vertical** and **Spectrometer horizontal** control the two
  large 100 mm Parker/Daedal slides. Both sliders run from −50 to +50 mm.
- The Huber 410 rotation carries the common analyzer frame and all four stacks.
  It is limited to ±45° about the CAD pose.
- The STEP contains four `mo39154771` crystal stacks (`A064`–`A067`). Each has a
  70 mm Kohzu XA07A-L201 translation, a `LIB-000032444` rotation (limited to ±45°
  about the CAD pose), and an SA04B-RM01 tilt (±10°). Each tilt rotates about its
  remote center 74 mm above its local mounting plane.
- The `LIB-000032444` rotation stages replaced the Kohzu RA04A-W in the
  2026-11-04 revision and have no solids in the STEP, so no rotation stage is
  drawn or collision-checked. Each rotation axis rides the adapter
  `mo39185433` above the stage, which kept its place in the stack.
- Stack 4's joint frames are stack 1's carried by the stack placement transform.
  The same transform reproduces stacks 2 and 3 to 0.022 mm.
- The outer structural cage (`A035`, 52 non-fastener members) is fixed geometry
  included in interference checks. The inner analyzer cage rotates with the Huber.
- **LJ x/z/y** drive the liquid jet `DSG-000007948`: Kohzu XA05A-L202-R along the
  jet (x, ±25 mm), XA05A-R202 (z, ±7.5 mm), then the ZA05A lift (y, ±4 mm). The
  lift is at mid-travel in this STEP: its carriage sits at the library's zero
  offset on its base, as both slit lifts do, and can drop more than 5 mm before
  bottoming. (The older 43841 STEP drew it 3.105 mm lower, so that review treats
  it as fully down.) The jet adapter `P011`, holder `DSG-000108486` (`P507`) and
  tube `DSG-000005121` (`P514`) ride the lift.
- **Bottom slit y/x** and **Top slit y/x** drive the two slit towers (`A009`,
  `A015`): a LIB-000032451 vertical lift (±4 mm) carrying an XA05A-R202 (±7.5 mm)
  that holds the blade rod. The blade holder `DSG-000000720` and its two blade
  plates are clamped to each rod tip and ride the X stage (`P497/P424/P425`
  bottom, `P194/P422/P423` top), although the STEP files them under the chamber.
- The user-supplied controls envelope (`P702`) and its four support posts ride the
  Parker vertical lift plate (`P666`) and participate in interference checks. This
  STEP revision replaces the earlier `DSG-000108873` XCS Von Hamos Controls
  assembly with that single envelope.
- **ePix10k z/x** drive the detector assembly `LCL5005-008450` on its two Newport
  IMS300CC slides. Each fused slide is split at its carriage plate, and its 300 mm
  travel is assumed centred on the carriage position the fused slide models.
  - In the 2026-11-04 STEP, everything on the lower (z) carriage sits 80.1151 mm
    along world −Y from that carriage. The carriage's moving region is offset by
    that much (`moving_offset_mm` in the recipe's `stage_splits`) so it sits under
    the payload.
  - z therefore runs from −69.9 to +230.1 mm about the CAD pose; x keeps ±150 mm.
  - The detector keeps its parts at least 100 mm across, including the new front
    plate `mo39134025` (`P1342`); smaller parts and electronics are omitted.
- **ePix100 x/z/tilt** drive the smaller, upward-facing ePix100 (module
  `mo39154223` in `DSG-000042618`, sensor `P209`). The stack, from its fixed
  column up, is:
  - **x:** a lead-screw linear stage `LIB-000000725` (`P197`) along world −X.
    Its travel comes from the stage's end blocks, −92.2/+101.7 mm for the
    carriage the fused part models. In this STEP the payload adapter `P199` sits
    61.19 mm along the travel from that carriage, matched by its M3 counterbores
    against the carriage's tapped holes. The carriage's moving region is offset by
    that much, and x runs −40.5/+153.4 mm about the CAD pose. These are mechanical
    end stops, not limit switches, and nothing else catches over-travel because the
    carriage and its rail are one bearing.
  - **z:** an old 70 mm manual Kohzu cross-roller stage `LIB-000005430` (`P313`)
    along world +Y, given the ±6.5 mm of its current equivalent, the Kohzu
    XM07A-S1.
  - **tilt:** a manual Kohzu SH05B-RM swivel `LIB-000013709` (`P325` base, `P327`
    top), ±10° about world X. It pivots about the datum sphere `P326` that marks
    its remote centre, level with the sensor.

  Both translation stages are single fused solids in the STEP, so each is split at
  its carriage or table (`stage-splits.yaml`). The detector's 10° CAD tilt comes
  from the wedge adapter `P196` under the swivel; the swivel itself is centred.
  The module's front and rear covers (`P266`/`P222`) and cooling block
  (`P249`/`P250`) are retained, with the coolant fittings and tubes, optical
  transceiver and ribbon cable that stick out of the rear face. Parts fully
  enclosed by the covers stay omitted as detector internals.

LJ, slit and detector joints use beamline axes: y is up (world +Z) and the beam
travels along −z (world −Y), so z is world +Y and x is world −X. The beam direction
is inferred from the slits sitting upstream at world +Y and the ePix10k centred on
world Y downstream. Positive slider values move along the positive beamline axis.

The retained model uses 369 of the 1,819 leaf occurrences, with fused
stage geometry split into fixed and moving regions. The 1,450 omitted occurrences
are listed by reason in [assembly.yaml](reviews/assembly.yaml). This removes
fasteners, detector internals, construction geometry, the table understructure
of `DSG-000008836` with its floor anchors, and the two flexible
chamber boots around the slit blade rods. The structural
cage is retained. Mounts, outer detector geometry, and analyzer payloads remain.
Parts with no solid geometry in the STEP are counted as empty source geometry;
the build stops if that list no longer matches the source exactly, so a
re-export that fills in a part cannot leave it hidden.

The diffractometer base `P973` is shown as fixed geometry, about 1.2 m below
the chamber. The diffractometer body, 2θ arm, and 2θ stage (`P974`–`P976`)
contain only coordinate systems in this STEP, with no solids. Its goniometer
`SA-391-444-50` is not in the export at all. Nothing more of the diffractometer
can be drawn or checked, and no diffractometer motion is modelled.

The camera's two stages (`LIB-000032933`, `LIB-000032929`) have no geometry in
this STEP, so the camera stays fixed. Other manual rotary/tilt adjustments also
remain fixed. There is no XCS connection, PV mapping, or beam configuration.

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

The chamber `P513` is red in the STEP, the same hue as a contact highlight.
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

- Bearing parts also list the Huber end plate `P936` (0.5 mm to the Huber body
  over ±45°), the Parker bracket `P698` (3.25 mm over ±50 mm), the slit lift
  brackets `P091/P140` (0.787 mm over ±4 mm), and the slit X-stage sensor
  brackets `P106/P155` (0.498 mm to the X carriage over ±7.5 mm).
- `ignored_pairs` lists the chamber port `P403` against each slit blade rod. Its
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
(`P526` against the controls envelope `P702`), and checks that returning home clears it.
At home the CAD is clear. In this revision the chamber `P513` keeps 4.945 mm from
the jet adapter `P011`, so the home regressions allow no contact pairs.

Each joint was swept alone from home toward both limits, with the other joints at
home. Steps were 1° for rotations, 0.5 mm for the jet and slits, 2.5 mm for the
Parker and crystal slides, and 5 mm for the ePix. Each new hull contact was checked
against source CAD. The first CAD-confirmed contacts are real findings rather than
model errors:

| Joint | Usable travel from home | First contact |
| --- | --- | --- |
| Spectrometer vertical | above −37.5 mm (clear at −25 mm) to +50 mm | cage `P526` against controls envelope `P702` |
| Crystal 1 rotation | −45° to below +23° | SA04B `P765` against Thorlabs post `P941` |
| Crystal 2 rotation | above −35° to +45° | SA04B `P809` against post `P941` |
| Crystal 3 rotation | above −40° to +45° | SA04B `P852` against post `P941` |
| Crystal 4 rotation | −45° to below +21° | SA04B `P895` against post `P941` |
| LJ x | −25 mm to below +11 mm | jet adapter `P011` against port flange `P402` |
| LJ z | down to −7.5 mm, the limit | jet tube `P514` against port flange `P402` |
| Bottom / top slit y | above −1.72 mm to +4 mm (CAD bisection) | Z carriage `P085`/`P134` against bracket `P087`/`P136` |
| ePix10k z | −69.9 mm to below +105 mm | front plate `P1342` against chamber `P513` |
| ePix100 x | above −18.9 mm to below +144.9 mm (CAD bisection) | inward: module part `P298` against chamber port parts `P417`/`P419`; outward: Kohzu base `P313` against the linear stage's own end hardware |
| ePix100 tilt | −5.48° to +5.73° (CAD bisection) | arm `P330` against the swivel base `P325` |

Everything else is clear over its full travel:
- the horizontal Parker slide
- the analyzer rotation (±45°)
- all crystal translations and tilts
- LJ y (±4 mm)
- both slit X stages
- ePix10k x
- ePix100 z (±6.5 mm)

These are single-joint sweeps. Combined poses, such as a crystal rotated toward its
neighbour, are not covered.

An earlier finding that the slit rods touch `DSG-000000720` parts at −7.5 mm was a
model error: those parts are the blade holders clamped to the rods. On the
previous STEP the analyzer post swept through the ePix front ring between +33°
and +43.5°. The ePix now sits 80 mm further downstream, and that contact is gone.

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
