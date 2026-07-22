# SLAC Robotics Framework

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and eventually collision queries.

The current reviewed model is subassembly `*43841` from drawing
`DSG-000040389`. It contains an EPIX detector stage, three crystal stacks, and
three polycapillary stacks with 22 controllable joints.

## Linux

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

## Updating The 43841 STEP

For this reviewed polycap assembly, use the dedicated helper instead of running
manifest refresh, remap, and cache rebuild manually.

If the new STEP is already copied into
`cad/DSG-000040389/source.stp`:

```bash
source .venv/bin/activate
python -m slac_robotics.update_43841_step --rebuild-viewer-cache
```

If the new STEP is still somewhere else on disk, pass that file path and let
the helper copy it into the repo first:

```bash
source .venv/bin/activate
python -m slac_robotics.update_43841_step \
  /mnt/c/Users/koashen/Downloads/DSG-000040389.stp \
  --rebuild-viewer-cache
```

If you install the package as a console script entry point, the equivalent
command is `slac-refresh-43841`.

What this command does:

1. Copies the replacement STEP into `cad/DSG-000040389/source.stp` when you pass a path.
2. Backs up the previous manifest to `cad/DSG-000040389/manifest.previous.json`.
3. Regenerates `cad/DSG-000040389/manifest.json` from the new STEP.
4. Remaps `cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml` using `cad/DSG-000040389/reviews/43841-stage-stack.aliases.yaml`.
5. Optionally rebuilds the cached viewer scene.

After it finishes, verify the result with:

```bash
python -m slac_robotics.stage_cad_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

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

## Windows (WSL)

Run the framework in WSL 2 rather than directly in Windows. From an
administrator PowerShell prompt, install Ubuntu if WSL is not already set up:

```powershell
wsl --install -d Ubuntu
```

After the requested restart, open Ubuntu and install the system prerequisites:

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv
```

Clone the repository inside the WSL filesystem (for example, under `~/src`)
instead of under `/mnt/c`; file access and Python environments are generally
faster there. Then create the environment and run the viewer as usual:

```bash
mkdir -p ~/src
cd ~/src
git clone <repository-url> slac-robotics-framework
cd slac-robotics-framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m slac_robotics.stage_cad_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Open the Meshcat URL printed by the viewer in a Windows browser. WSL 2 normally
forwards `localhost` automatically, so no Linux desktop or X server is needed.
The environment is Linux-based: activate it with `source .venv/bin/activate`
each time you open a new Ubuntu shell.

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

The low-level remap command is still available if you need to debug the helper:

```bash
slac-cad-manifest cad/DSG-000040389/source.stp \
  --refresh-manifest --manifest-only --no-preview \
  --remap-stage-inventory cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --previous-manifest cad/DSG-000040389/manifest.previous.json \
  --alias-map cad/DSG-000040389/reviews/43841-stage-stack.aliases.yaml
```

Validate the code and reviewed data:

```bash
pytest -q
ruff check .
ruff format --check .
```

## Model status

- Motion and rigid attachment ownership have been visually reviewed.
- The enclosure, two camera assemblies, shield cone, chamber, long-jet assembly,
  and detector stage 7948 are included as named world-fixed environment groups.
- Viewer and SDF materials distinguish each stage model, adapters,
  crystal/holder payloads, polycap/holder payloads, and transparent enclosure geometry.
- SDF joint coordinates are zero at the reviewed CAD pose. North and South RA
  stages have a documented 180-degree logical display offset.
- The normal SDF share package is visual/kinematic only, so it stays fast in
  Drake and portable to MATLAB.
- Collision geometry is intentionally not published yet. Aggregate CAD meshes
  create poor convex hulls; useful interference analysis needs per-part collision
  decomposition, interface filtering, tolerances, and clearance margins.
