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

If the STEP, manifest, inventory, or catalog changes, the cache is rebuilt. Use
`--rebuild` only when forcing a fresh tessellation is useful.

## Updating the STEP revision

Regenerate the manifest explicitly:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --refresh-manifest --manifest-only --no-preview
```

Then compare occurrence references before trusting the existing review. A new
CAD revision can reorder `A` and `P` references even when part names look similar.
Do not overwrite reviewed YAML automatically.

## Accuracy boundary

The current model is suitable for kinematic review and visualization. Hardware
safety decisions still require surveyed joint frames, calibrated encoder zeros,
tolerances, cable envelopes, and reviewed collision geometry.
