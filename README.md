# SLAC Robotics Framework

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and collision queries.

The current reviewed model is subassembly `*43841` from drawing
`DSG-000040389`. It contains an EPIX detector stage, three crystal stacks, and
three polycapillary stacks with 22 controllable joints.

## Setup

The framework is Linux-based. Windows users run it inside WSL 2 rather than
natively; every step after the first subsection is identical on both.

### Windows: install WSL 2 first

From an administrator PowerShell prompt, install Ubuntu if WSL is not already
set up:

```powershell
wsl --install -d Ubuntu
```

Restart when asked, open Ubuntu, and continue with the steps below. Work inside
the WSL filesystem (for example `~/src`) rather than under `/mnt/c`; file access
and Python environments are markedly faster there.

The viewers print a Meshcat URL that opens in a normal Windows browser. WSL 2
forwards `localhost` automatically, so no Linux desktop or X server is needed.

### Install the prerequisites

```bash
sudo apt update
sudo apt install -y git git-lfs python3 python3-venv
git lfs install
```

Run `git lfs install` before cloning. The STEP sources are stored as LFS
objects, and a clone made without it yields small pointer files instead of CAD.
See [Large files](#large-files) for the full picture.

### Get the code

```bash
mkdir -p ~/src && cd ~/src
git clone <repository-url> slac-robotics-framework
cd slac-robotics-framework
```

If the clone predates your Git LFS setup, `cad/DSG-000040389/source.stp` will be
a few hundred bytes rather than 88 MiB. Run `git lfs install` and then
`git lfs pull` to fill in the real content.

### Create the environment

Either tool works and a team can mix them freely, since both produce the same
`.venv`. [uv](https://docs.astral.sh/uv/) is faster and pins the interpreter:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --seed
uv pip install -r requirements.txt
```

`uv venv` reads `.python-version` and fetches the interpreter this project is
tested against instead of using whatever the system provides, which matters
because Drake publishes wheels only for specific Python versions. The `--seed`
flag installs `pip` into the environment; without it anything that shells out to
`pip` fails, including the VS Code Python extension's package list.

The stock tooling works too:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Use `python3` for that first command. A fresh Ubuntu has no `python` until a
virtual environment is active, and under WSL a bare `python` may resolve to a
Windows interpreter on the shared PATH, which cannot build a working Linux
environment here.

### Running commands

Every command in this README assumes the environment is active, which is one
step per new shell:

```bash
source .venv/bin/activate
```

With uv you can skip activation entirely and prefix any command with `uv run`:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

### Verify

```bash
pytest -q
```

The suite exercises the CAD manifest, inventory remap, SDF compiler, and
collision plumbing without opening a viewer.

## Collision detection

This is the point of the model. Quick start, from the repository root:

```bash
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

Meshes can also be decomposed ahead of time with `slac-decompose`, and the
compiler accepts the same options:

```bash
python -m slac_robotics.sdf_compiler \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --with-collisions --collision-mode convex
```

### Convex decomposition (CoACD)

#### Why it is needed

Drake's proximity queries do not see a concave mesh. The signed-distance support
table states it outright:

> Meshes are represented by the *convex* hull of the mesh, therefore the results
> for Mesh are the same as for Convex.

Every clearance number this tool reports comes from that query, so handing Drake
the enclosure as a single mesh means handing it a solid block: the interior
fills in and anything inside it reports contact. Splitting each part into convex
pieces and declaring them with `<drake:declare_convex/>` is the only way to get
honest distances.

#### Why CoACD, and why Drake has no equivalent

Drake ships no decomposition tool. `pydrake.geometry` provides the `Convex`
shape, which *consumes* a piece and takes the hull of whatever it is given.
That is deliberate: decomposition is slow, offline, and wants caching, which is
the opposite of what belongs in a simulation loop. Drake owns the runtime half
and leaves the asset-pipeline half to the model author. So the question is which
external tool to use, not whether to use one.

| Option | Assessment |
| --- | --- |
| V-HACD | The long-standing default, bundled with Bullet. Voxel-based, so it needs more hulls for the same fidelity, and thin CAD features such as brackets and shields blur out at practical voxel resolutions |
| Hand-authored primitives | What production robot models do, and the fastest at runtime. Rejected here because the geometry is CAD-driven: every STEP revision would invalidate the hand work |
| CoACD | **Chosen.** Its concavity metric is collision-aware, so hulls are spent where contact can actually occur, giving fewer and better-placed hulls than V-HACD on the same part. It also ships `abi3` wheels, so collaborators get a binary instead of a C++ build |

#### What the first build costs

The cold run is genuinely expensive. Measured on the reviewed 43841 inventory,
which is 215 sub-parts totalling 1.2 M triangles:

| | |
| --- | --- |
| Wall time | 34 min on a 12-core Xeon W-2265 |
| CPU | Fully saturated, by design |
| Memory | Up to 2.9 GB per worker, around 14 GB total while the largest parts run |

Do not expect more cores to rescue this. The median part is only about 1,400
triangles, while spawning a worker, importing CoACD, and running its
size-independent tree search costs the equivalent of roughly 15,000. Per-part
overhead dominates the run, not geometry.

A progress bar reports percent complete and an ETA weighted by that setup cost
plus triangle count. Weighting by triangles alone under-predicted the real build
by nearly 4x, because the largest parts are dispatched first.

Workers are sized automatically from CPU count and free memory. CoACD
parallelizes internally with OpenMP, so one worker is not one core; two threads
per worker measured fastest, and the run keeps workers times threads inside the
machine. Override with `--decomposition-workers` if you want the machine back:

```bash
slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --decomposition-workers 2
```

Interrupting a build is safe. Every finished sub-part writes a marker, so a
re-run resumes; only the parts in flight when you killed it are repeated.
Because those are dispatched largest-first, they are also the most expensive
ones, which is a good reason to let a nearly-finished build finish.

#### Caching: this cost is paid once

Results are cached under `.cache/slac_robotics/convex-collision/`, keyed on the
source mesh mtime and size plus the decomposition settings (`threshold`,
`max_hulls`, `seed`). Later runs start immediately, and the cache is worth
keeping across branches.

It is invalidated only when the STEP is updated and the meshes are
re-tessellated, or when `--threshold` or `--max-hulls` changes. A re-tessellation
that produces byte-identical output is recognised by hash, so rebuilding the
viewer cache alone does not force a re-decomposition.

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

## Updating the 43841 STEP

For this reviewed polycap assembly, use the dedicated helper instead of running
manifest refresh, remap, and cache rebuild manually.

If the new STEP is already copied into
`cad/DSG-000040389/source.stp`:

```bash
python -m slac_robotics.update_43841_step --rebuild-viewer-cache
```

If the new STEP is still somewhere else on disk, pass that file path and let
the helper copy it into the repo first:

```bash
python -m slac_robotics.update_43841_step \
  /mnt/c/Users/koashen/Downloads/DSG-000040389.stp \
  --rebuild-viewer-cache
```

The console-script equivalent is `slac-refresh-43841`.

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

## Large files

`cad/DSG-000040389/source.stp` is roughly 88 MiB. GitHub rejects any single file
over 100 MiB in ordinary git storage, and the limit applies to every revision in
a push rather than only the current one, so an oversized blob that reaches
history blocks all later pushes until the history is rewritten.

Git LFS avoids that. `.gitattributes` routes every STEP file to LFS:

```text
*.stp filter=lfs diff=lfs merge=lfs -text
```

What git commits is a small pointer, while the bytes live in LFS storage:

```text
version https://git-lfs.github.com/spec/v1
oid sha256:69dc3dc0b1b64932f25fde6b65b36c38442e9caa34eec7bfe0646d026418734a
size 92523231
```

Because the rule is a pattern rather than a per-file entry, a replacement STEP
is handled automatically: copy it into place and commit as usual. Confirm it
landed in LFS rather than in git proper:

```bash
git lfs ls-files
```

Both STEP files should be listed. A file missing from that output was committed
as a normal blob, which means `git lfs install` never ran in this clone. Undo
that commit before pushing rather than after.

The pointer is also what you see in a diff, so `git show` on a STEP revision
reports an oid and size instead of attempting to render 88 MiB of CAD text.

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
.gitattributes               routes *.stp to Git LFS
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

## Command reference

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
