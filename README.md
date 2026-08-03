# Twin Lab

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and collision queries.

The current reviewed model is subassembly `*43841` from drawing
`DSG-000040389`. It contains an EPIX detector stage, three crystal stacks, and
three polycapillary stacks with 22 controllable joints.

## Setup

Everything below happens in a single VS Code window. Step 1 is Windows-only
groundwork; on Linux, open this repository in VS Code and start at step 2. From
there on, every command goes into the VS Code integrated terminal, which you
open with `` Ctrl+Shift+` ``.

Run every unlabelled command block, in order. Anything that is not part of the
normal path is labelled in the text introducing it, or at the top of its
section: **Only if** / **Only when** for something you run in one specific case,
**Optional** for something you can skip, **Fallback** for a workaround, and
**Reference** for a command listed for lookup rather than for following along.

### 1. Windows only: move VS Code into Ubuntu

**Do this before anything else.** Twin Lab is a Linux project: Drake publishes no
Windows wheels, and every command in this README is a bash command. VS Code on
Windows opens PowerShell by default, and PowerShell cannot run them. A
copy-paste of `sudo apt update` into PowerShell fails with
`sudo : The term 'sudo' is not recognized`, and `source ~/.bashrc` fails the
same way, because those are Unix shell commands, not Windows ones. WSL 2 gives
you a real Ubuntu system where they work.

The goal is one VS Code window whose terminals, extensions, file explorer, and
search all run inside Ubuntu. Getting there costs one elevated command and one
reboot; after that you never open a separate terminal application again. You
need [VS Code](https://code.visualstudio.com/) installed on Windows, not inside
WSL.

**a. Install WSL.** `wsl --install` requires administrator rights and VS Code's
terminal cannot elevate itself, so for this one step start VS Code elevated:
close it, press the Windows key, type `code`, and choose **Run as administrator**
on **Visual Studio Code**. Open the integrated terminal with `` Ctrl+Shift+` ``.
It is PowerShell, which is the right shell here and nowhere else. Run:

```powershell
wsl --install -d Ubuntu
```

**b. Reboot.** WSL does not work until Windows restarts. From the same terminal:

```powershell
Restart-Computer
```

**c. Create your Linux user.** Reopen VS Code normally this time; the
administrator rights were only for step a. Open a terminal, which is PowerShell
again, and start Ubuntu inside it:

```powershell
wsl -d Ubuntu
```

The first launch asks for a UNIX username and password. These are new
credentials for Linux, unrelated to your Windows login, and nothing appears on
screen while you type the password. You need it for `sudo` later, so pick
something memorable. When it finishes, the prompt becomes something like
`you@LCLS-PC12345:~$`: that is bash, running in Ubuntu, inside VS Code. Type
`exit` to return to PowerShell.

**d. Connect the whole window to Ubuntu.** Open the Extensions view with
`Ctrl+Shift+X`, search for
[WSL](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-wsl),
and install it. Then press `Ctrl+Shift+P`, run **WSL: Connect to WSL**, and wait
for the status bar at the bottom left to read `WSL: Ubuntu`.

That is the whole point of the setup. Every terminal you open from now on
(`` Ctrl+Shift+` ``) is Ubuntu bash rather than PowerShell, and everything else
the editor does — editing, search, extensions, debugging — happens on the Linux
side too. You should not need PowerShell again. Confirm in a fresh terminal:

```bash
uname -srm
```

It should print something like `Linux 5.15.167.4-microsoft-standard-WSL2
x86_64`. A `PS C:\>` prompt or a `not recognized` error means the window is not
connected; check the status bar and re-run **WSL: Connect to WSL**.

One thing still leaves the window: the viewers print a `localhost` URL that you
open in your normal Windows browser. WSL forwards the port for you, so no Linux
desktop or X server is involved.

#### Where your files live, and where to clone

WSL gives you two separate filesystems, and knowing which one you are standing
in is most of what makes WSL confusing at first.

Ubuntu has its own disk with its own root, `/`. Your account lives at
`/home/<your-linux-username>`, which bash abbreviates as `~`. Linux paths use
forward slashes, have no drive letters, and are case-sensitive, so `Source.stp`
and `source.stp` are different files. **Reference**, for whenever you lose track
of where you are:

```bash
pwd     # print the directory you are in
cd ~    # go back to your Linux home
```

Your Windows drives are still reachable, mounted under `/mnt`. `C:\` appears as
`/mnt/c`, so a browser download at `C:\Users\you\Downloads\DSG-000040389.stp` is
`/mnt/c/Users/you/Downloads/DSG-000040389.stp` from Ubuntu. That is how you hand
a Windows file to a Linux command without copying it anywhere.

**Clone into the Linux side, not `/mnt/c`.** Step 3 below uses `~/src/Twin-Lab`,
which is on Ubuntu's own disk. Working under `/mnt/c` instead means every file
read crosses a Windows-to-Linux translation layer: builds and Git operations run
many times slower, and Linux file permissions do not survive the trip. The rule
of thumb is that Linux tools want Linux files.

Because the window is connected to WSL, VS Code's own **File > Open Folder**
dialog browses the Ubuntu filesystem, so the repository is reachable from the
GUI like any other project. If you ever need it from Windows itself, File
Explorer can browse to `\\wsl$\Ubuntu\home\<your-linux-username>`.

### 2. Install the prerequisites

In the VS Code terminal, which is now Ubuntu bash:

```bash
sudo apt update
sudo apt install -y git git-lfs pipx
git lfs install
pipx install uv
pipx ensurepath
source ~/.bashrc
```

Three things happen here. `git lfs install` must run **before** you clone: the
88 MiB STEP files are stored in Git LFS, and a clone made without it silently
gives you small text pointers instead of CAD. `pipx install uv` installs
[uv](https://docs.astral.sh/uv/), the tool that manages this project's Python
version and packages. `source ~/.bashrc` reloads the shell so `uv` is on your
`PATH` right away instead of only in the next terminal you open.

Confirm before continuing:

```bash
uv --version
```

<details>
<summary>Why <code>pipx</code> rather than the one-line uv installer</summary>

`uv` is not packaged in the Ubuntu repositories, and the uv documentation's
`curl ... | sh` line pipes a downloaded script straight into a shell, so a
hijacked host or bad DNS answer would run arbitrary code as your user. `pipx`
installs the official PyPI release into its own isolated environment, records a
version you can audit with `pipx list`, and removes cleanly with
`pipx uninstall uv`.

</details>

### 3. Clone the repository, then open it

**Optional, only if you intend to model a stack other than the XCS
polycapillary assembly.** Fork first and clone your fork, so your catalog
entries, inventories, and STEP files stay yours to change and the reviewed 43841
model is not in your way. Open
[github.com/slaclab/Twin-Lab](https://github.com/slaclab/Twin-Lab), click
**Fork**, and create the fork under your own account or organisation. Then use
your fork's URL in place of the `slaclab` one in the clone below.

[What to edit](#what-to-edit) lists the two reviewed inputs that describe an
assembly: `config/stage-catalog.yaml` for the stage models themselves, and a
per-drawing inventory under `cad/<drawing>/reviews/`. The tooling is not
specific to 43841; that inventory is simply the one assembly reviewed so far.

Clone:

```bash
mkdir -p ~/src && cd ~/src
git clone https://github.com/slaclab/Twin-Lab.git
cd Twin-Lab
```

`~/src` is just a folder for checkouts inside your Linux home, so the clone lands
at `~/src/Twin-Lab`.

**Only if you cloned a fork**, keep a link back to the original so you can still
pull fixes:

```bash
git remote add upstream https://github.com/slaclab/Twin-Lab.git
git fetch upstream
```

Check that the CAD came down as real geometry rather than an LFS pointer:

```bash
ls -lh cad/DSG-000040389/source.stp
```

The size should be about 88M, in which case carry on. A few hundred bytes means
Git LFS was not active for this clone. See [Large files](#large-files) for the
background.

**Only if the size is wrong:**

```bash
git lfs install
git lfs pull
```

Now point the window at the repository so the file explorer, search, and every
new terminal start there:

```bash
code -r ~/src/Twin-Lab
```

`-r` reuses the current window rather than opening a second one. VS Code reloads
with the project open and its terminal already at the repository root, which is
where the remaining commands expect to run. **File > Open Folder** does the same
thing through the GUI.

### 4. Create the environment

```bash
uv sync --all-extras
```

That one command reads `.python-version` and `uv.lock`, downloads the exact
Python this project is tested against, creates `.venv`, and installs the pinned
CAD, Drake, collision, and dev dependencies. It takes a few minutes the first
time. Drake only publishes wheels for specific Python versions, which is why the
interpreter is pinned rather than taken from the system.

### 5. Let VS Code pick the environment up automatically

Install the [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
from the Extensions view (`Ctrl+Shift+X`). Because the window is connected to
WSL, install it into `WSL: Ubuntu` rather than locally; VS Code offers the right
target automatically. Then reload the window with `Ctrl+Shift+P` >
**Developer: Reload Window**.

That is the whole step. The repository ships a `.vscode/settings.json` that
pins the interpreter to `${workspaceFolder}/.venv/bin/python` and turns on
terminal activation, so from now on opening this folder is enough: the status
bar shows the `.venv` interpreter, and every new terminal (`` Ctrl+Shift+` ``)
opens with `(.venv)` already in the prompt. There is nothing to activate by
hand, in this shell or any future one.

Confirm in a fresh terminal:

```bash
which python
```

It should print `/home/<your-linux-username>/src/Twin-Lab/.venv/bin/python`. If
it prints `/usr/bin/python3`, or nothing at all, the pinned interpreter has not
been applied: run `Python: Select Interpreter` from the Command Palette and
choose the one at `./.venv/bin/python`.

What this buys you is editor-side: working imports, go-to-definition, and
inline errors for `twin_lab` and Drake. Commands stay written as `uv run …`
throughout this README, which works whether or not the environment is active, so
there is only ever one form to copy.

### 6. Verify

```bash
uv run pytest -q
```

Expect `53 passed` in roughly 15 seconds. The suite exercises the CAD manifest,
inventory remap, SDF compiler, and collision plumbing without opening a viewer.
If this passes, setup is done.

### Running commands

Every command below is prefixed with `uv run`. Step 5 already puts you in the
environment, but the prefix is kept everywhere so a copied line also works in a
plain terminal, on a machine without the Python extension, or in a script — and
so there is never a question of whether the right Python is selected. Run them
in the VS Code terminal, which already opens at the repository root.

## Collision detection

This is the point of the model. Quick start, from the repository root:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The command prints a `http://localhost:7000` Meshcat URL; `Ctrl+Click` it in the
VS Code terminal to open it in your normal browser. First load takes about 20
seconds, and the window stays blank until the console says the geometry is
loaded. Note that the very first run also has to build the collision hulls,
which takes far longer; see
[what the first build costs](#what-the-first-build-costs). Drag any joint slider
and the background colour tells you the state of the pose immediately.

The collision viewer drives a Drake plant compiled from the same reviewed
inventory, so the geometry drawn on screen and the geometry checked for
interference are the same kinematics.

Checking can be switched off at any time with the
`Collision detection: ON (click to disable)` toggle button, which turns the
window into a plain slider-driven viewer with Drake's normal sky background. The
same command therefore covers both jobs; clicking the toggle back on repaints
the state for the current pose.

The `Animation: OFF (click to start)` toggle and the two `Auto motion` sliders
described under [animated motion](#animated-motion) are available here too, so a
whole sweep can be checked for interference without touching a slider. With
checking left on, each animation frame is evaluated, which is the fastest way to
find the poses that actually collide.

### Reading the result

| Background | State | Meaning |
| --- | --- | --- |
| Green | `clear` | Nothing within the warning band |
| Yellow | `close` | Something inside the warning band, but no contact |
| Red | `interference` | At least one pair is touching or penetrating |

The offending parts light up in place with the same code: yellow inside the
warning band, red where they touch. The highlight is drawn from the convex hulls
Drake actually tested, so it wraps the reviewed part and stays visible through
the transparent enclosure. It follows the part as the sliders move and clears
itself as soon as the pair separates, which makes a crowded stack searchable
without reading the pair list.

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

The viewer builds `convex` geometry for you, so nothing extra is required.

**Optional**, only when you want a collision-enabled SDF package rather than the
viewer:

```bash
uv run slac-compile-sdf \
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

Drake ships no decomposition tool: `pydrake.geometry` provides the `Convex`
shape, which *consumes* a piece and takes the hull of whatever it is given. That
is deliberate, since decomposition is slow, offline, and wants caching. So the
question is which external tool to use, not whether to use one.

<details>
<summary>How the candidates compare</summary>

| Option | Assessment |
| --- | --- |
| V-HACD | The long-standing default, bundled with Bullet. Voxel-based, so it needs more hulls for the same fidelity, and thin CAD features such as brackets and shields blur out at practical voxel resolutions |
| Hand-authored primitives | What production robot models do, and the fastest at runtime. Rejected here because the geometry is CAD-driven: every STEP revision would invalidate the hand work |
| CoACD | **Chosen.** Its concavity metric is collision-aware, so hulls are spent where contact can actually occur, giving fewer and better-placed hulls than V-HACD on the same part. It also ships `abi3` wheels, so collaborators get a binary instead of a C++ build |

</details>

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
machine.

**Optional**, only if you want the machine back while the build runs:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --decomposition-workers 2
```

Interrupting a build is safe. Every finished sub-part writes a marker, so a
re-run resumes; only the parts in flight when you killed it are repeated.
Because those are dispatched largest-first, they are also the most expensive
ones, which is a good reason to let a nearly-finished build finish.

#### Caching: this cost is paid once

Results are cached under `.cache/twin_lab/convex-collision/`, keyed on the
source mesh mtime and size plus the decomposition settings (`threshold`,
`max_hulls`, `seed`). Later runs start immediately, and the cache is worth
keeping across branches.

It is invalidated only when the STEP is updated and the meshes are
re-tessellated, or when `--threshold` or `--max-hulls` changes. A re-tessellation
that produces byte-identical output is recognised by hash, so rebuilding the
viewer cache alone does not force a re-decomposition.

The compiled package under `exports/` carries a build stamp recording the scene
meshes, the collision mode, and the inventory `decomposition` block it was built
from. `slac-collision` recompiles whenever that stamp no longer matches, so
editing a per-part override reaches the viewer without `--rebuild`.

### Filtering expected contact

Drake automatically ignores pairs that share a body, sit either side of one
joint, or belong to the same welded subgraph, so a reported pair is a real
finding rather than bookkeeping noise. Parts that are in contact by design go in
the `ignored_pairs` block of the stage inventory, which already exists and looks
like this:

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

**Optional**, only when the pairs you want to exclude live elsewhere: pass
`--ignore-file` to read the block from another YAML file instead.

## Viewing and moving the assembly

**Optional.** This viewer is an alternative to the collision viewer, not a step
after it. Reach for it when you want kinematics without the collision plant,
since it is lighter and starts faster:

```bash
uv run slac-stage-cad \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The first run builds meshes under `.cache/twin_lab/stage-cad/`. Later runs
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

**Only when a new STEP revision arrives.** Nothing in this section is part of
first-time setup. For this reviewed polycap assembly, use the dedicated helper
instead of running manifest refresh, remap, and cache rebuild manually. Pass the
path to the new STEP file and the helper copies it into the repository for you:

```bash
uv run slac-refresh-43841 \
  /path/to/DSG-000040389.stp \
  --rebuild-viewer-cache
```

Omit the path if the replacement STEP is already sitting at
`cad/DSG-000040389/source.stp`. Under WSL, a file downloaded on the Windows side
is reachable at `/mnt/c/Users/<your-user>/Downloads/DSG-000040389.stp`.

What this command does:

1. Copies the replacement STEP into `cad/DSG-000040389/source.stp` when you pass a path.
2. Backs up the previous manifest to `cad/DSG-000040389/manifest.previous.json`.
3. Regenerates `cad/DSG-000040389/manifest.json` from the new STEP.
4. Remaps `cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml` using `cad/DSG-000040389/reviews/43841-stage-stack.aliases.yaml`.
5. Rebuilds the cached viewer scene, because `--rebuild-viewer-cache` was passed.

After it finishes, verify the result with:

```bash
uv run slac-stage-cad \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

**Optional**, only when you need to hand the model to someone outside this
repository. Build the portable SDF package:

```bash
uv run slac-compile-sdf \
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
is handled automatically: copy it into place and commit as usual.

**Only when you have committed a new STEP**, confirm it landed in LFS rather
than in git proper:

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
.python-version              interpreter this project is tested against
uv.lock                      pinned dependency set installed by `uv sync`
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
src/twin_lab/
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
.cache/twin_lab/               generated previews, viewer meshes, convex hulls (ignored)
exports/                       generated share and collision packages (ignored)
```

## Command reference

**Reference.** Nothing in this section needs to be run in order. Console-script
entry points, all installed with the package. Prefix each with `uv run`:

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
uv run slac-cad-manifest cad/DSG-000040389/source.stp --show-tree --manifest-only
uv run slac-cad-manifest cad/DSG-000040389/source.stp --view --focus A035 --manifest-only
```

**Fallback**, only if you need to debug the refresh helper. The low-level remap
command it wraps is still available:

```bash
uv run slac-cad-manifest cad/DSG-000040389/source.stp \
  --refresh-manifest --manifest-only --no-preview \
  --remap-stage-inventory cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --previous-manifest cad/DSG-000040389/manifest.previous.json \
  --alias-map cad/DSG-000040389/reviews/43841-stage-stack.aliases.yaml
```

**Only before committing changes**, validate the code and reviewed data:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
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
