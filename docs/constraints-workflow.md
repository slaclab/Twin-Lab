# STEP-to-SDF Workflow

STEP contains useful assembly geometry and occurrence placement, but it does not
provide a trustworthy robotics joint model. Generated CAD facts and
human-reviewed mechanical intent are therefore kept separate.

## 1. Generate the CAD manifest

```bash
python -m slac_robotics.constraints_wizard \
  step_files/DSG-000046520.stp --show-tree
```

Successful output starts with something like:

```text
STEP READ OK
  Assemblies: 4
  Leaf parts: 10

- [A001] DSG-000046520
  - [A002] REF-000221283
    - [P001] REF-000221282
```

`A` labels are assemblies and `P` labels are assignable leaf parts. The generated
`.cad.json` contains the complete path-based IDs, component names, parent
relationships, assembly flags, and local 4×4 transforms. Regenerate it when the
STEP assembly changes; do not edit it manually.

Open Cascade reports these CAD transforms in millimetres. SDF and Drake use
metres, so the later conversion step must apply a factor of `0.001`.

## 2. Review rigid groups

First, confirm visually that the imported geometry is recognizable:

```bash
slac-cad-manifest step_files/DSG-000046520.stp --view
```

This converts the STEP assembly to a temporary glTF preview and displays it in
Meshcat. The preview verifies geometry and placement, but it does not move yet.
The kinematics review is what tells Drake which pieces move together.

Edit the much smaller `.kinematics.yaml` file. For each moving carriage, copy the
short `P` references into one rigid group:

```yaml
rigid_groups:
  x_carriage:
    occurrences:
      - P003
      - P004
```

An occurrence must belong to exactly one rigid group. Fasteners can initially be
left unassigned; start with the interference-significant housings, carriages,
mounts, and payloads.

Think of a rigid group as answering one physical question: “If I jog this motor,
which of these parts move together without changing their relative position?”

For a serial XYZ stack:

- `base`: structure that never moves.
- `x_carriage`: everything moved by X, including the downstream Y and Z hardware
  only when that hardware is represented as part of the X link.
- `y_carriage`: the rigid Y-moving link.
- `z_carriage`: the rigid Z-moving link and payload.

Each physical leaf part belongs to exactly one link. Parent motion automatically
carries child links, so a Z-carriage part must not also be listed in X and Y.

## 3. Review joints and frames

For each axis, record:

- Parent and child rigid groups.
- Prismatic or revolute joint type.
- Axis and sign.
- Travel limits and home.
- Parent-to-joint translation and orientation.

Use metres and radians. Prefer stable assembly coordinate systems or reference
planes over faces and edges that may disappear in a CAD revision.

Do not start by measuring perfect joint transforms. First get the component
groups, parent/child order, axis directions, and approximate travel correct. The
Meshcat sliders will expose gross mistakes before precision calibration matters.

Check progress at any time:

```bash
slac-cad-manifest step_files/DSG-000046520.stp --check --no-preview
```

The check reports assigned and unassigned parts, duplicate assignments, stale
references, and joints that name missing rigid groups. Regenerating the CAD
manifest does not overwrite the review file unless `--force-template` is passed.

## 4. Compile one reusable SDF model

The reviewed groups and joints become one SDF mechanism containing links,
joints, visual meshes, simplified collision meshes, and named mounting/tool
frames. The current reference is:

- `models/stages/three_axis_stage.sdf`

Define a stage or subassembly once, then instantiate it many times. Do not copy
its component list into the top-level spectrometer scene.

## 5. Compose the instrument

Drake Model Directives adds named model instances and welds each mounting frame
into the chamber or another mechanism. The current three-instance example is:

- `models/scenes/three_stage_demo.dmd.yaml`

Large instruments should use nested directive files by subsystem: detector,
crystals, polycapillaries, chamber, and robot arms.

## 6. Inspect motion visually

```bash
python -m slac_robotics.scene models/scenes/three_stage_demo.dmd.yaml
```

Open the printed Meshcat URL and move the joint sliders. Inspect visual geometry,
collision geometry, and coordinate frames before trusting automated clearance
results.

For the reviewed real STEP groups, use:

```bash
slac-motion step_files/DSG-000046520.kinematics.yaml
```

This produces generated `.obj` meshes under `DSG-000046520.motion/`, colors the
four rigid groups, and provides millimetre X/Y/Z sliders. The original assembled
pose is zero. Parent motion carries all downstream groups.

This first viewer only exercises prismatic motion. It does not yet compute mesh
interference, and provisional group assignments must be confirmed before any
hardware decision.

## Next implementation step

The next code boundary is a compiler from the reviewed kinematics YAML and CAD
manifest into an SDF model with per-rigid-group collision meshes. Until that
compiler exists, the checked-in SDF proxy is the executable reference model.
