# CAD review workflow

STEP describes geometry, assembly hierarchy, and occurrence poses. It does not
reliably describe which solids form a moving carriage, the joint type, the motion
axis, travel limits, or payload ownership. Those decisions live in a small
reviewed YAML overlay.

## Project files

Each drawing has one directory:

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

Generated previews and motion meshes go under `.cache/slac_robotics/`; they do
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
  --view --focus A035 --manifest-only
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
python -m slac_robotics.stage_cad_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The viewer splits each stage into reviewed rigid roles, nests downstream links,
and attaches adapter/payload meshes to the selected carriage. Slider units are
millimetres or degrees. The original assembled CAD pose is home.

Three extra sliders drive a cyclic demo motion:

- `Auto motion (0 manual / 1 cycle)` toggles between manual sliders and the
  automatic cycle. Switching back to `0` hands control back at the current pose.
- `Auto motion range (% of travel)` scales the excursion. Each joint swings
  symmetrically about its home by that percentage of the smaller side of its
  reviewed limits, so a low value keeps the motion well clear of interference.
- `Auto motion period (s)` sets the cycle time. Joints are phase-staggered so
  the stack does not move as one block.

`Reset to home` also switches the toggle back to manual.

If the STEP, manifest, inventory, or catalog changes, the cache is rebuilt. Use
`--rebuild` only when forcing a fresh tessellation is useful.

## Updating the STEP revision

### Reviewed 43841 workflow

For the current `DSG-000040389` review, use the dedicated helper:

```bash
source .venv/bin/activate
python -m slac_robotics.update_43841_step --rebuild-viewer-cache
```

Or, if the replacement STEP is not yet inside the repo:

```bash
source .venv/bin/activate
python -m slac_robotics.update_43841_step /path/to/new/DSG-000040389.stp --rebuild-viewer-cache
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

## Accuracy boundary

The current model is suitable for kinematic review and visualization. Hardware
safety decisions still require surveyed joint frames, calibrated encoder zeros,
tolerances, cable envelopes, and reviewed collision geometry.
