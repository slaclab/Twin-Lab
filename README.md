# SLAC Robotics Framework

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and eventually collision queries.

The current reviewed model is subassembly `*43841` from drawing
`DSG-000040389`. It contains three crystal stacks and three polycapillary stacks
with 21 controllable joints.

## Quick start

Create the environment once:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

View and move the reviewed real-CAD assembly:

```bash
python -m slac_robotics.stage_cad_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The first run builds meshes under `.cache/slac_robotics/stage-cad/`. Later runs
reuse that cache. Use the North/Middle/South Crystal and Polycap controls in
Meshcat; **Reset to home** restores every reviewed home position.

Build the portable SDF package:

```bash
python -m slac_robotics.sdf_compiler \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The shareable ZIP is written to:

```text
exports/DSG-000040389.43841-stage-stack.sdf-package.zip
```

Unzip it in MATLAB and run `load_in_matlab`. See
[SDF sharing](docs/sdf-sharing.md) for details.

## What to edit

| File | Purpose |
| --- | --- |
| `cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml` | Assembly-specific stage order, axes, limits, fixed geometry, and attachments |
| `config/stage-catalog.yaml` | Reusable manufacturer/model facts and internal component roles |
| `cad/DSG-000040389/manifest.json` | Generated stable occurrence references for this STEP revision |
| `cad/DSG-000040389/source.stp` | Original CAD source |

The inventory and catalog are the important reviewed inputs. Do not edit cache or
export meshes; regenerate them instead.

## Repository layout

```text
cad/
  DSG-000040389/
    source.stp                 original full assembly
    manifest.json              generated CAD occurrence facts
    reviews/
      43841-stage-stack.inventory.yaml
  DSG-000046520/               earlier single-polycap review fixture
config/
  stage-catalog.yaml           reusable stage definitions
docs/
  cad-review.md                STEP hierarchy and constraint-review workflow
  sdf-sharing.md               portable SDF and MATLAB handoff
src/slac_robotics/
  constraints_wizard.py        STEP import, manifest, tree, and preview
  cad_geometry.py              shared Open Cascade traversal/mesh helpers
  stage_cad_viewer.py          current full-stack cached motion viewer
  sdf_compiler.py              reviewed scene to portable SDF package
  scene.py                     generic Drake SDF/URDF loader and queries
tests/
  fixtures/                    small proxy models used only by tests
.cache/slac_robotics/          generated previews and viewer meshes (ignored)
exports/                       generated share packages (ignored)
```

## Other commands

Inspect a STEP tree or generate a focused preview:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp --show-tree --manifest-only
slac-cad-manifest cad/DSG-000040389/source.stp --view --focus A035 --manifest-only
```

Validate the code and reviewed data:

```bash
pytest -q
ruff check .
ruff format --check .
```

## Model status

- Motion and rigid attachment ownership have been visually reviewed.
- SDF joint coordinates are zero at the reviewed CAD pose. North and South RA
  stages have a documented 180-degree logical display offset.
- The normal SDF share package is visual/kinematic only, so it stays fast in
  Drake and portable to MATLAB.
- Collision geometry is intentionally not published yet. Aggregate CAD meshes
  create poor convex hulls; useful interference analysis needs per-part collision
  decomposition, interface filtering, tolerances, and clearance margins.
