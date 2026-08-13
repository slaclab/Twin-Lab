# CAD review workflow

STEP describes geometry, assembly hierarchy, and occurrence poses. It does not
reliably describe which solids form a moving carriage, the joint type, the motion
axis, travel limits, or payload ownership. Those decisions live in a small
reviewed YAML overlay.

## Project files

Each source assembly has one directory:

```text
cad/DSG-000040389/
  source.stp
  manifest.json
  reviews/
    43841-stage-stack.inventory.yaml
```

- `source.stp` is the original assembly.
- `manifest.json` is generated from STEP and assigns short stable references such
  as `A035` and `P1114` for that exact STEP revision.
- `reviews/*.yaml` contains human-reviewed mechanical meaning.

Generated previews and motion meshes go under `.cache/twin_lab/`; they do
not belong beside the source or review files.

## Inspect the hierarchy

Print the assembly tree without creating another review template:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --show-tree --manifest-only --no-preview
```

Preview only the active `*43841` subassembly:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --view --focus A037 --manifest-only
```

Preview only the cataloged stage occurrences:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --view --manifest-only \
  --stage-inventory cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Open Cascade reports STEP translations in millimetres. Drake and the reviewed
motion files use metres; the import code performs this conversion.

## Review the stage inventory

The active inventory contains four kinds of information:

1. `stage_instances` maps STEP assembly occurrences to reusable catalog entries.
2. `motion_chains` and `compound_motion_chains` define base-to-payload order.
3. `joint_limit_overrides` defines assembly operating windows and logical homes.
4. `attachment_overrides` records which non-stage parts are fixed or move with a
   particular stage carriage.

Manufacturer/model facts and internal component roles belong in
`config/stage-catalog.yaml`. Occurrence references and adapter ownership belong
in the assembly review, because they change with the STEP revision.

## Test motion

```bash
uv run slac-stage-cad \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The viewer splits each stage into reviewed rigid roles, nests downstream links,
and attaches adapter/payload meshes to the selected carriage. Slider units are
millimetres or degrees. The original assembled CAD pose is home.

A toggle button and two sliders drive a cyclic demo motion:

- `Animation: OFF (click to start)` starts the automatic cycle; the button then
  reads `Animation: ON (click to stop)` and clicking it again hands control back
  to the manual sliders at the current pose.
- `Auto motion range (% of travel)` scales the excursion. Each joint swings
  symmetrically about its home by that percentage of the smaller side of its
  reviewed limits, so a low value keeps the motion well clear of interference.
- `Auto motion period (s)` sets the cycle time. Joints are phase-staggered so
  the stack does not move as one block.

`Reset to home` also switches the toggle back off.

If the STEP, manifest, inventory, or catalog changes, the cache is rebuilt. Use
`--rebuild` only when forcing a fresh tessellation is useful.

## Updating the STEP revision

### Reviewed 43841 workflow

For the current `DSG-000040389` review, use the dedicated helper:

```bash
uv run slac-refresh-43841 --rebuild-viewer-cache
```

Or, if the replacement STEP is not yet inside the repo:

```bash
uv run slac-refresh-43841 /path/to/new/DSG-000040389.stp --rebuild-viewer-cache
```

This helper:

1. Copies the STEP into `cad/DSG-000040389/source.stp` when needed.
2. Backs up the previous manifest.
3. Regenerates the manifest.
4. Remaps the reviewed inventory with the checked-in alias file.
5. Rebuilds the stage-viewer cache when requested.

Use the lower-level commands below only when you need to inspect or debug the
refresh process itself.

Regenerate the manifest explicitly:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --refresh-manifest --manifest-only --no-preview
```

Then compare occurrence references before trusting the existing review. A new
CAD revision can reorder `A` and `P` references even when part names look similar.
Do not overwrite reviewed YAML automatically.

If Teamcenter copies forced you to publish near-identical assemblies under new
IDs, keep the previous manifest and supply an alias map so reviewed inventories
can be rewritten automatically against the new STEP revision:

```yaml
# aliases.yaml
name_aliases:
  LIB-000007591: LIB-000032456
  LIB-000014334: REF-000221283
  DSG-000046520: DSG-000046526

# Optional when an entire occurrence path moved in a way name aliases cannot
# express by parent-local matching alone.
occurrence_id_aliases: {}
```

Then run:

```bash
cp cad/DSG-000040389/manifest.json cad/DSG-000040389/manifest.previous.json
slac-cad-manifest cad/DSG-000040389/source.stp \
  --refresh-manifest --manifest-only --no-preview \
  --remap-stage-inventory cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --previous-manifest cad/DSG-000040389/manifest.previous.json \
  --alias-map aliases.yaml
```

The remap step preserves the inventory file layout and comments while replacing
stale `A###` and `P###` references. Any unresolved refs are printed explicitly
so you can review only the ambiguous cases.

For entirely new assemblies with no meaningful carry-over from a prior STEP,
skip remapping and treat the import as a new review:

1. Generate the manifest and inspect the tree.
2. Create a new review inventory or kinematics template.
3. Add any new stage model facts to `config/stage-catalog.yaml`.
4. Review stage ownership, motion chains, attachment overrides, and limits.

## Clearance review

`slac-collision` compiles the reviewed inventory into an SDF package with collision
geometry, loads it into a Drake plant, and drives it from the same sliders you use
for manual manipulation. Every slider change re-runs a signed-distance query, so the
geometry on screen is the geometry being checked.

```bash
slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

`Clearance warning band (mm)` sets the distance below which a pair is reported.
`Log clearance report` prints the full sorted table to the terminal for a design
review; the live status line only reports the worst pair.

Offending parts light up on the model itself: yellow inside the warning band, red
where they touch. `Showing: whole assembly` marks every offending part at once, which
is the view for judging whether a pose is safe. Clicking it switches to `Showing:
worst pair only`, which hides the illustration meshes and leaves just the two parts of
the worst pair on screen, for looking at one interface without the rest of the
assembly in the way. What remains in that mode are the convex hulls rather than the
CAD meshes, because the compiled package carries one visual mesh per sub-assembly and
only the collision geometry is split per reviewed part.

Collision geometry is built one of two ways, selected by `--collision-mode`:

- `hull` wraps each merged mesh in a single convex hull. It compiles in seconds but
  inflates part volume by 1.65x-2.93x, and a hollow part such as the `A036` enclosure
  becomes solid. At the home pose this mode reports 112 touching pairs that are
  entirely artefacts of hull inflation, so it is not usable for clearance review.
- `convex` (the default for `slac-collision`) runs CoACD on each part and emits one
  `<collision>` per convex piece, each tagged `<drake:declare_convex/>`. Volume error
  drops to roughly 1.4x-1.5x, and the residual is mostly filled bolt holes rather than
  spanned external concavity.

Decomposing the full `43841` assembly -- 187 sub-parts and 1.0 M triangles at the
current revision -- costs tens of minutes: 34 minutes measured on a 12-core Xeon
W-2265, and roughly an hour on an 8-core i9-11950H running 12 workers. A
triangles-per-second figure does not predict that well, because per-part setup dominates: the median part is about 1,400 triangles, while
spawning a worker and running CoACD's size-independent search costs the equivalent of
roughly 15,000. Results are cached under `.cache/twin_lab/convex-collision/` keyed by
source mtime, size, and settings, so the full assembly is a one-time cost and
milliseconds thereafter. Hull count barely affects that runtime: CoACD's search
dominates, so `max_hulls` trades query cost and package size, not build time.

`slac-hull-audit` measures what that decomposition costs in accuracy, comparing every
cached hull against the tessellated part it replaces:

```bash
slac-hull-audit                       # every cached decomposition, worst fit first
slac-hull-audit --tour                # the ten worst parts, one per click
slac-hull-audit static_A003 --view    # one mesh, with the hulls drawn over the CAD
slac-hull-audit --assembly            # every part in place, hulls over the CAD mesh
```

Three numbers per part: `vol x` is hull volume over CAD volume, where the hull volume
is the union rather than the sum, so overlapping pieces are not counted twice; `bulge`
is the furthest a hull vertex sits *outside* the CAD surface, which is the added
material that produces phantom contact; `gap` is the furthest a CAD vertex sits outside
every hull, which is real material CoACD's voxel remesh shaved off and Drake will
therefore never collide with. `--view` opens the same parts in Meshcat with the hulls
drawn translucent over the grey CAD mesh, so a bad row can be looked at rather than
guessed at. Sorting by `gap` finds parts that are too small, sorting by `volume` finds
the parts worth a per-part `threshold` or `max_hulls` override.

`--view` answers *how* badly one part fits; `--assembly` answers *which* parts fit
badly, which is where a settings pass starts. It draws every audited part at its
assembly position with the hulls layered translucent over the CAD mesh, so the pieces
Drake collides with are read against the geometry they stand in for rather than in
isolation. The hull button cycles three states: piece colours, which give each hull of
a decomposition its own colour so the cut lines are visible; bulge shading, which
recolours every hull vertex grey where it lies on the CAD surface and red at
`--bulge-scale-mm` (2 mm by default) of outward bulge, so a spanned concavity shows up
as a red patch on the part that has it; and hidden, leaving the CAD alone. Both
colourings are uploaded once and switched by visibility, so the toggle is instant.
`Show worst N parts` hides the good parts and leaves the bad ones standing in the
assembly, and `Focus part index` flies the camera to one part and prints which it is.

The bulge ramp holds grey out to a quarter of its scale rather than starting at zero.
Every hull vertex bulges a little -- the median across `static_A003` is 0.17 mm, at the
tessellation deflection rather than at anything CoACD did -- so a ramp anchored at zero
paints the whole assembly amber and separates nothing.

`--tour` is the same rendering as `--assembly` restricted to one part at a time, but it
chooses the parts itself: the `--tour-count` worst by the active `--sort`, ten by
default, framed one per click of `Next part`. Both other viewers ask the reviewer for an
index, and an index is exactly what the audit has already worked out, so the tour is the
form of the review that gets finished. Position is derived from the Next and Previous
click counters rather than tracked in the loop, so a click landing between polls is
never dropped and both ends wrap. The panel republishes the part's audited numbers as
control labels on every step, which is the only text Meshcat can show.

Note that relabelling a Drake button -- how all three viewers show a toggle's next state
-- creates a *new* button whose click count starts at zero, so the tracked count has to
be reset with it. Carrying the old count over made the next poll compare 1 against 0 and
fire the toggle a second time, which advanced the three-state hull button by two states
per click and ran the cycle backwards.

Nearly all of that runtime is the two distance fields, so each part's measurements are
cached in an `audit.npz` beside the hulls they judge, keyed to the source mesh's digest
and the decomposition settings. Re-running the audit costs a second rather than
minutes, and a re-decomposed part is the only one re-measured. `--refresh` forces the
measurement anyway, which is what to reach for after changing the metrics themselves.

Bulge is measured against a *signed* distance to the surface. Hulls fill solid regions,
so their vertices routinely sit deep inside the part, and an unsigned distance counts
that depth as added material: `static_A003/P024` reported 4.42 mm of bulge while its
hulls fit it to 8% by volume, and the offending vertex turned out to be 4.42 mm inside
the solid, with a true outward bulge of 0.28 mm. Signing the distance moved the median
worst-case bulge from 1.61 mm to 0.69 mm and the 90th percentile from 5.51 mm to
1.96 mm across the assembly.

Auditing every part of the `43841` assembly measured 3.5 minutes and reported 1.536x
volume overall, median 1.229 per part, worst 2.688, with the largest gap at 0.45 mm,
below the 0.5 mm tessellation deflection, so no part is meaningfully undersized. Bulge
runs 0.69 mm at the median, 1.96 mm at the 90th percentile and 7.39 mm at the worst,
and it tracks the *voxel* size rather than the part: CoACD's `preprocess_resolution`
divides each part's own bounding box, so the fixed default of 50 gives a 1.6 mm voxel
on a median 82 mm part but a 15.9 mm voxel on the 796 mm rails. Raising it to 800 on
one such rail took its bulge from 5.55 mm to 0.28 mm. Lowering `threshold` and doubling
`max_hulls` did not help at all -- `static_A003/P024` held at 4.42 mm with 32 and with
64 hulls -- so resolution, not hull budget, is the lever that moves bulge.

The tail is what matters: the parts above 2x saturate `max_hulls` at 32 while still
holding an unfilled cavity, and those are the ones worth an override rather than the
median.

Volume is integrated about each part's own centroid rather than the world origin. The
tessellation is not watertight -- about 1% of its welded edges bound a sliver crack --
and the term that leaks through those cracks grows with the distance from the reference
point, so a world-origin integral reports a different volume for the same part at
different placements.

Work is dispatched per sub-part rather than per file, longest first, so one large mesh
cannot set the makespan. Each finished sub-part writes a resume marker, so a build that
is interrupted picks up where it stopped instead of starting over.

Budget memory before raising `--decomposition-workers`. Because the longest parts start
first, the biggest meshes decompose concurrently, so peak memory lands early in the run.
Measured on this assembly, a worker holds 0.5-1.2 GB, and 12 workers ran at about 8 GB
combined on a 16 GB machine without touching swap. Cores bind before memory does: CoACD
is single-threaded per part, so workers past the physical core count only queue, and one
oversized part sets the tail of the run no matter how many workers are free.

Drake filters collision pairs automatically at `Finalize()` for bodies joined by a
joint and for bodies welded into the same subgraph, so each stage's own fixed and
moving halves need no manual filter. Pairs that touch by design belong in the
`ignored_pairs` block of the stage inventory, which the viewer reads by default:

```yaml
ignored_pairs:
  - pair: [P759, P784]
    reason: cable-carrier bracket sits flush on the detector adapter at home
```

Both entries must be leaf part references (`P###`). Collision geometry is split per
reviewed part, so an assembly reference such as `A037` matches no geometry and the
filter silently never fires.

Use `--ignore-file` only to try an alternative list without editing the review.

Reports are engineer-facing. They are meant to drive design changes and travel-limit
decisions, not to gate motion at runtime.

## Accuracy boundary

The current model is suitable for kinematic review and visualization. Hardware
safety decisions still require surveyed joint frames, calibrated encoder zeros,
tolerances, cable envelopes, and reviewed collision geometry.

Clearance numbers inherit the tessellation deflection (2 mm) and the convex
decomposition error, so treat small positive clearances as "needs a closer look"
rather than as a measurement.

`Verify against CAD` in the collision viewer removes the second of those two
terms from every pair inside the warning band. It prefers an exact triangle-to-triangle
distance between the two parts' own tessellations, taken over the triangles within 20 mm
of the witness points Drake reported and capped at 400 triangles a side; where the
tessellation cannot be loaded it falls back to subtracting the audited proudness of the
two hulls, sampled at the three hull vertices nearest the contact. The fallback needs
`slac-hull-audit` to have written its `audit.npz`, and a pair with neither available is
reported `unverified` rather than quietly passed.

Both corrections are one-sided. They can only ever grow a reported distance, because the
hulls they correct are supersets of the parts, so an `explained` verdict genuinely rules
out the decomposition as the cause. That is what makes it safe to fold them into the live
reading: the corrected report drives the status colour, the highlights and the offender
list, and a correction can drop a pair out of the band but never add one. What neither
does is remove the tessellation deflection: BRepMesh inscribes its facets, so the meshes
themselves are undersized on convex surfaces by up to the deflection, and a
sub-millimetre `explained` result is inside that noise. The verdict is a routing decision
— look at the CAD, or look at the design — not a clearance figure.

The two tiers run on different schedules, because they cost three orders of magnitude
apart. Subtracting the audited proudness is a table lookup, 1.7-2.0 ms for twelve pairs,
so it runs on every pose alongside the ~40 ms signed-distance query. The exact mesh
distance is 5-240 ms per pair (720-860 ms for twelve), which no slider drag can absorb,
so it waits until the pose has held still for 0.3 s and until then the reading carries
only the cheaper correction. Both directions of that trade are conservative: the
uncorrected reading is the one that over-reports.

Measured at the reviewed home pose (5 mm band): 22 part pairs inside the band on the
hulls alone, 21 after the proudness correction, 18 after the exact distance — for
instance P662 against P844 reads +0.59 mm on the hulls and 1.98 mm on the CAD. The
control that proves the correction is not simply clearing everything is A044 driven to
-25 mm, where P664/P844 and P652/P844 still report `CAD meshes intersect`.

The 20 mm / 400-triangle neighbourhood is not a limiting approximation here: re-running
the same pairs at 80 mm and 2000 triangles reproduces every distance exactly.

The two tiers were also run against each other on those six pairs. They agree on four; on
the remaining two the audited proudness returns `contact` where the exact distance finds
1.18 mm and 0.18 mm of clearance. The bias is one-directional and structural: bulge is
measured at hull vertices, and a hull face stands off the CAD by more in its interior than
at its corners, so the vertex-sampled correction always understates the true proudness. A
Tier 0 `explained` is therefore trustworthy, while a Tier 0 `contact` only means the pair
has not been ruled out yet.
