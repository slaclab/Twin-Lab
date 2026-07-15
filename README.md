# SLAC Robotics Framework

Stage-stack modeling and interference analysis for compact X-ray spectrometer
assemblies. The project uses standard formats wherever possible:

```text
STEP assembly                         human-reviewed intent
      │                                       │
      └── Open Cascade ──> CAD manifest       └──> reusable SDF models
                                                       │
                                      Drake Model Directives
                                                       │
                                      MultibodyPlant + SceneGraph
                                                       │
                                      Meshcat + clearance queries
```

## Tools

The runtime has only two substantive tool families:

- **Open Cascade (`cadquery-ocp`)** reads STEP hierarchy and occurrence poses.
- **Drake** parses SDF/URDF and Model Directives, evaluates kinematics and
  interference, and provides the browser-based Meshcat viewer.

Ruff and pytest are the only development tools. The previous custom kinematics,
trimesh, SciPy, and FCL paths have been removed.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## View the Three-Stack Scene

```bash
python -m slac_robotics.scene models/scenes/three_stage_demo.dmd.yaml
```

Open the printed Meshcat URL, normally `http://localhost:7000`. Meshcat provides
joint sliders for all nine axes, visual/collision geometry controls, and visible
coordinate frames. In WSL, open that URL in the Windows browser.

The reusable stage model is
[three_axis_stage.sdf](models/stages/three_axis_stage.sdf). The scene instantiates
it three times using
[three_stage_demo.dmd.yaml](models/scenes/three_stage_demo.dmd.yaml).

These boxes are deliberately simple proxies. They prove model composition,
joint motion, visualization, and interference queries before real CAD component
groups are available.

## Extract the Real CAD Assembly

```bash
python -m slac_robotics.constraints_wizard step_files/DSG-000046520.stp --show-tree
```

The command prints `STEP READ OK`, the number of assemblies and parts, and a
numbered tree using short labels such as `P003`. It writes three outputs:

- `DSG-000046520.cad.json`: generated occurrence IDs, hierarchy, and transforms;
  do not edit it manually.
- `DSG-000046520.kinematics.yaml`: a compact review template for rigid groups,
  joints, axes, limits, and frames.
- `DSG-000046520.preview.gltf`: a generated browser preview; it is ignored by Git.

View the imported STEP without installing another CAD application:

```bash
slac-cad-manifest step_files/DSG-000046520.stp --view
```

Generated manifests and previews are reused until the STEP file changes. Files
larger than 50 MB automatically use a coarser 2 mm preview tessellation. To trade
more visual detail for a slower one-time conversion, use
`--refresh-preview --preview-deflection-mm 0.5`.

For a large instrument, preview only the subsystem under review so Meshcat does
not send unrelated geometry to the browser:

```bash
slac-cad-manifest step_files/DSG-000040389.stp --view --focus A035
```

For interactive work, prefer the much lighter cataloged-stage preview. It omits
fasteners, cable-chain links, and unrelated payload detail while preserving all
stage occurrence poses:

```bash
slac-cad-manifest step_files/DSG-000040389.stp --view \
  --stage-inventory step_files/DSG-000040389.43841.inventory.yaml
```

For the reusable interactive view, merge each unique manufacturer stage into one
real-CAD mesh and place all 19 occurrences from the inventory. The first run
builds the cache; later runs do not reopen STEP:

```bash
python -m slac_robotics.stage_cad_viewer \
  step_files/DSG-000040389.43841.inventory.yaml
```

## Compile and Share the Reviewed SDF

Once the motion and rigid attachments look correct, compile the cached scene into
a portable SDF package:

```bash
python -m slac_robotics.sdf_compiler \
  step_files/DSG-000040389.43841.inventory.yaml
```

This writes `exports/DSG-000040389.43841.sdf-package/` and a ZIP beside it. The
package contains the SDF, relative-path binary STL visual meshes, joint metadata,
and `load_in_matlab.m`. Collision geometry is deliberately excluded from this
fast sharing model until its per-part convex decomposition is reviewed. The
generated package is ignored by Git because it can be rebuilt from the inventory
and CAD cache.

In MATLAB with Robotics System Toolbox, unzip the package, change into its
directory, and run:

```matlab
load_in_matlab
```

SDF coordinates are zero at the reviewed CAD pose. `joint_metadata.csv` records
logical display offsets, including the 180-degree North/South crystal mounting
orientation.

After assigning `P` references to rigid groups, check progress with:

```bash
slac-cad-manifest step_files/DSG-000046520.stp --check --no-preview
```

The checker lists every unassigned, unknown, or multiply assigned part. Existing
kinematics assignments are never overwritten unless `--force-template` is used.

## Move the Actual STEP Groups

Once the review reports every part assigned, run:

```bash
slac-motion step_files/DSG-000046520.kinematics.yaml
```

Open the printed Meshcat URL and use the X, Y, and Z sliders in the Controls
panel. This viewer tessellates one OBJ per rigid group and nests the groups so
parent motion carries its children. Slider units are millimetres.

The checked-in assignments are provisional guesses for the KOHZU YA04A XY stage
and ZA05A Z stage. The provisional physical chain runs from the large left fixed
block through Z, lower Y, and upper X to the polycap-side payload. The display
origin is the center of that fixed block; replace it with a surveyed mounting
datum later. This is a visual motion test, not yet a collision or hardware safety
model.

The template is intentionally not a second simulation format. It is a review
artifact that will be compiled into an SDF model after the real component groups
are filled.

## Repository Layout

```text
models/stages/       reusable SDF mechanisms
models/scenes/       Drake Model Directives assemblies
step_files/          source STEP plus generated manifest/review files
src/slac_robotics/
  constraints_wizard.py  STEP → CAD manifest and review template
  sdf_compiler.py         reviewed stage scene → portable SDF/STL package
  scene.py               standard model loading, queries, and Meshcat
tests/                CAD extraction and Drake composition tests
```

## Verification

```bash
pytest -q
ruff check .
ruff format --check .
```

## Accuracy

Proxy boxes are not clearance authority. Hardware decisions require CAD-derived
collision meshes, surveyed joint frames, encoder-zero calibration, tolerances,
and explicit clearance margins.
