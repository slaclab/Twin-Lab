# SLAC Robotics Framework

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and collision queries.

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

## Collision detection

This is the point of the model. Quick start, from the repository root:

```bash
source .venv/bin/activate
slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Open the Meshcat URL it prints. First load takes about 20 seconds; the window is
blank until the console says the geometry is loaded. Drag any joint slider and
the background colour tells you the state of the pose immediately.

The collision viewer drives a Drake plant compiled from the same reviewed
inventory, so the geometry drawn on screen and the geometry checked for
interference are the same kinematics. The module form
`python -m slac_robotics.collision_viewer <inventory>` is equivalent.

Checking can be switched off at any time with the
`Collision detection: ON (click to disable)` toggle button, which turns the
window into a plain slider-driven viewer with Drake's normal sky background. The
same command therefore covers both jobs; clicking the toggle back on repaints
the state for the current pose.

The `Animation: OFF (click to start)` toggle and the two `Auto motion` sliders
described under [animated motion](#animated-motion) are available here too, so a
whole sweep can be swept for interference without touching a slider. With
checking left on, each animation frame is evaluated, which is the fastest way to
find the poses that actually collide.

### Reading the result

| Background | State | Meaning |
| --- | --- | --- |
| Green | `clear` | Nothing within the warning band |
| Yellow | `close` | Something inside the warning band, but no contact |
| Red | `interference` | At least one pair is touching or penetrating |

The worst three part pairs are listed by reference ID in the Meshcat controls
panel, for example `TOUCHING 1: P844 <-> P850`, so the offenders are identifiable
without leaving the browser. Distances are deliberately omitted there; a live
number would rebuild the panel on every slider step. The terminal carries the
numbers, one line per state change, and **Log clearance report** dumps the worst
25 pairs with both the part IDs and their owning links.

Only `interference` is a hard finding. `close` depends entirely on the
`Clearance warning band (mm)` slider, so it is a design-review aid rather than a
pass/fail. At the reviewed home pose the assembly is `close` at the default 5 mm
band and only goes `clear` below about 0.9 mm; the stack really is that tightly
packed, so home is reported as close rather than clean.

### Collision modes

| Mode | How geometry is built | Use |
| --- | --- | --- |
| `hull` | One convex hull per part mesh | Fast, but a hull of a concave part such as the enclosure fills its interior, so it reports contact everywhere. Useful only as a smoke test |
| `convex` | CoACD convex decomposition, one `<collision>` per hull with `<drake:declare_convex/>` | Default for the viewer. Tracks true concavity, so clearance numbers are meaningful |

The convex build runs CoACD once and caches the result under
`.cache/slac_robotics/convex-collision/`, keyed by mesh mtime, size, and the
decomposition settings. The cold build on the 43841 assembly is long (roughly
2.6 M triangles across 392 sub-parts), so give it workers and let it finish:

```bash
python -m slac_robotics.collision_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --collision-mode convex --decomposition-workers 8
```

Later runs reuse the cache and start immediately. Meshes can also be decomposed
ahead of time with `slac-decompose`, and the compiler accepts the same options:

```bash
python -m slac_robotics.sdf_compiler \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --with-collisions --collision-mode convex --decomposition-workers 8
```

### Filtering expected contact

Drake automatically ignores pairs that share a body, sit either side of one
joint, or belong to the same welded subgraph, so a reported pair is a real
finding rather than bookkeeping noise. Parts that are in contact by design go in
the `ignored_pairs` block of the stage inventory:

```yaml
ignored_pairs:
  - pair: [P1112, P1170]
    reason: touching at reviewed CAD home (-2.69 mm)
```

That block is currently seeded from the home-pose report. The reviewed CAD home
is an assembled state, so contact there is pre-existing rather than something
motion caused; baselining it is what keeps the indicator off red at home and
reserves red for interference the stages actually create. Those seven pairs have
**not** been individually validated as by-design, so re-review them if a stack is
re-modelled.

Pass `--ignore-file` to read the block from another YAML file instead.

## Viewing and moving the assembly

For kinematics work without the collision plant, the cached CAD viewer is
lighter and starts faster:

```bash
python -m slac_robotics.stage_cad_viewer \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The first run builds meshes under `.cache/slac_robotics/stage-cad/`. Later runs
reuse that cache. Use the North/Middle/South Crystal and Polycap controls in
Meshcat; **Reset to home** restores every reviewed home position.

### Animated motion

Both viewers carry the same controls. Besides the per-joint sliders, one toggle
button and two sliders drive a continuous demo animation of the whole stack:

| Control | Effect |
| --- | --- |
| `Animation: OFF (click to start)` | Toggle button. Starts the animation and relabels itself to `Animation: ON (click to stop)`; clicking again hands control back to the manual sliders at the current pose |
| `Auto motion range (% of travel)` | Excursion as a percentage of the smaller side of each joint's reviewed limits, so every joint stays inside its operating window |
| `Auto motion period (s)` | Cycle time, 2-60 s |

Each joint swings sinusoidally about its reviewed home. Joints are
phase-staggered around the cycle so the stack does not translate as one block
and stage-to-stage interactions are visible. The manual sliders track the
animation live, so you can stop on any frame by clicking the toggle off and then
nudge individual joints from there. **Reset to home** also switches the toggle
back off.

The range slider is a travel heuristic, not a clearance guarantee. To check an
animated pose for real interference, run the animation inside the collision
viewer above, which evaluates every frame.

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
| `cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml` (`ignored_pairs`) | Part pairs that are in contact by design and excluded from clearance reports |
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
  cad_motion.py                provisional rigid-group motion viewer
  sdf_compiler.py              reviewed scene to portable SDF package
  convex_collision.py          cached CoACD convex decomposition of part meshes
  collision.py                 clearance queries and reviewed pair filtering
  collision_viewer.py          slider-driven viewer with live clearance reporting
  scene.py                     generic Drake SDF/URDF loader and queries
  paths.py                     repo, cache, and export path resolution
tests/
  fixtures/                    small proxy models used only by tests
.cache/slac_robotics/          generated previews, viewer meshes, convex hulls (ignored)
exports/                       generated share and collision packages (ignored)
```

## Other commands

Console-script entry points, all installed with the package:

| Command | Module | Purpose |
| --- | --- | --- |
| `slac-stage-cad` | `stage_cad_viewer` | Cached CAD viewer with manual sliders and animation |
| `slac-collision` | `collision_viewer` | Drake viewer with live clearance reporting |
| `slac-compile-sdf` | `sdf_compiler` | Portable SDF share package |
| `slac-decompose` | `convex_collision` | Convex-decompose cached meshes ahead of time |
| `slac-cad-manifest` | `constraints_wizard` | STEP tree, manifest, remap, preview |
| `slac-refresh-43841` | `update_43841_step` | Update the reviewed STEP revision |
| `slac-view` | `scene` | Plain Drake model visualizer for any SDF/URDF |

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
- Collision geometry is opt-in and lives in a separate package. Aggregate CAD
  meshes make poor convex hulls, so useful interference analysis needs the
  `convex` mode, which splits each part into CoACD hulls before Drake sees it.
- The 43841 assembly has 22 scalar joints and 4798 convex collision hulls. Hull
  mode reports contact almost everywhere because the enclosure hull is solid;
  convex mode is the mode to trust.
- Clearance is reported as a three-state readout: clear, close, and
  interference. Only interference is a hard finding; close tracks the warning
  band slider. Per-interface margins and a fully validated `ignored_pairs` list
  are still open; the current list is baselined from the home pose, not reviewed
  pair by pair.
- The animation range slider is a travel heuristic and has not been
  clearance-verified; treat animated poses as candidates to check, not as
  cleared motion.
