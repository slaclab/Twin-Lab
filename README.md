# Twin Lab

Kinematic modeling and interference-analysis tooling for STEP-based X-ray
spectrometer stage stacks. Open Cascade reads the CAD hierarchy and Drake handles
motion, visualization, and collision queries.

The current reviewed model is subassembly `*43841` from drawing
`DSG-000040389`. It contains an EPIX detector stage, three crystal stacks, and
three polycapillary stacks with 22 controllable joints.

## For returning users

Set up already? Open the repository in VS Code, open a terminal with
`` Ctrl+Shift+` ``, and use the branch that matches the job in front of you.

Collision review:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Pseudo-live archive playback from a known start time:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-start 2026-08-26T15:32:20-07:00 \
  --playback-end ongoing
```

Resume pseudo-live archive playback from the last stopped timestamp:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-start resume \
  --playback-end ongoing
```

The viewers open a Meshcat page at `http://localhost:7000` in your browser.
First time here? Start at [Setup](#setup) instead.

## Collision detection

Collision detection is the top-level design-review tool: it answers whether a
candidate pose or motion sweep is clear, close, or interfering before anyone
trusts a playback trace or a manually adjusted pose.

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The viewer opens the reviewed `43841` assembly with collision checking on. Move
joints with sliders or run the built-in animation sweep; the background and
part highlights report the state immediately. Use this first when the question
is geometric safety, clearance, or whether the current CAD/inventory model is
ready to compare against real motion.

Detailed collision modes, hull-error auditing, and CAD contact rechecking are
kept later in [Collision reference and rechecking](#collision-reference-and-rechecking)
because they are follow-up tools once the basic collision result needs deeper
interpretation.

## Playback and live data

Playback is the bridge between the reviewed CAD model and real EPICS motor
commands. The controls are open-loop, so every branch below shows commanded
motion reconstructed with each stage's catalog speed limits; it is not encoder
readback or proof that the hardware physically arrived.

| Branch | Command shape | Controls | Why it matters |
| --- | --- | --- | --- |
| Saved session replay | `slac-export-session`, then `slac-stage-cad --playback-recording recordings/session-....json` | Speed, pause, restart, scrub | Portable and repeatable. Use it for design reviews, demos, and sharing an exact historical run without needing archiver access later. |
| Fixed archive replay | `slac-stage-cad --playback-start ISO --playback-end ISO` | Speed, pause, restart, scrub | Fastest path when this machine can reach the archiver and you just want to inspect one finite time window. The top-left viewer label is `fixed playback mode`. |
| Pseudo-live archive replay | `slac-stage-cad --playback-start ISO --playback-end ongoing` | Stop only, plus travel-speed derating | Starts from a user-selected historical time and keeps extending the archive query at 1x until stopped. The top-left viewer label is `continuous playback mode`, matching its role as the integration bridge for true live feed. |
| Resumed pseudo-live replay | `slac-stage-cad --playback-start resume --playback-end ongoing` | Stop only, plus travel-speed derating | Restarts continuous mode from the timestamp where the previous pseudo-live viewer stopped, so a dropped/restarted viewer can continue the same stream instead of starting over. |
| Current archiver live mirror | `slac-export-live` plus `slac-live-feed --live-file recordings/live.json`, or direct `slac-live-feed` where archive access works | Stop only, plus travel-speed derating | Tracks the present hardware run with a few seconds of archiver lag. This is the practical near-live workflow available now. |
| Future true EPICS live feed | Not implemented yet; waiting on controls-system details | Stop only | This should swap the data source under the same live viewer contract once the controls person gives us the supported direct live feed path. It matters because it removes archiver lag and makes Twin Lab a real run-time mirror. |

### Saved session replay

Use this when you want a durable artifact. Export once on a PCDS-networked
machine, then replay the resulting JSON anywhere:

```bash
uv run slac-export-session
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-recording recordings/session-20260826T1552.json
```

The replay viewer is view-only: the recording drives the joints, so manual
sliders are hidden. Because the window is finite and historical, the Meshcat
panel includes playback speed, pause, restart, and scrub controls.

### Fixed archive replay

Use this when the current machine can reach the archive REST endpoint and you
do not need to save a JSON file first:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-start 2026-08-26T15:32:20-07:00 \
  --playback-end 2026-08-26T15:36:40-07:00 \
  --playback-speed 8
```

This is regular historical playback, labeled `fixed playback mode` in the
viewer. Pause is for inspecting one pose in that finite window; it is not the
live-mode stop command.

### Pseudo-live archive replay

Use this when you want live-like behavior from archived data. The user supplies
the start, and the end is `ongoing` or `continuous`:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-start 2026-08-26T15:32:20-07:00 \
  --playback-end ongoing
```

This mode is labeled `continuous playback mode` in the viewer. It advances at
real time, re-polls the archiver as the replay window grows, and stops only
when you press **Stop live feed**, Escape, or `Ctrl-C`. It deliberately has no
speed multiplier, pause, restart, or scrub controls.
When it stops, it saves the last archive timestamp to
`recordings/ongoing-playback-resume.json` by default. Restart from that point
with:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --playback-start resume \
  --playback-end ongoing
```

Use `--playback-resume-file path/to/resume.json` if you need separate resume
state for two different runs. Use `--playback-poll-period-s` to tune how often
the growing archive window is refreshed.

### Current archiver live mirror

For watching a real experiment while it is happening, run the live exporter on
a PCDS-networked machine:

```bash
uv run slac-export-live
```

Then point the live viewer at that continuously refreshed file:

```bash
uv run slac-live-feed cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \
  --live-file recordings/live.json
```

Where direct archive access works from the viewer machine, `slac-live-feed` can
also poll the archive itself. Either way, this branch follows the present run,
not a chosen historical start. It has live-style controls only: stop the feed,
optionally derate travel speed, and do not scrub or speed-scale reality.

### Future true EPICS live feed

This is the branch still waiting on information from the controls person. The
intended shape is the same live viewer contract used above - a source that
reports current joint positions and a current timestamp - but the source will
come from the supported direct live EPICS feed rather than from archived REST
queries or a refreshed JSON file. Keeping pseudo-live and archiver-live modes
separate now lets us swap that source in later without changing the viewer's
stop-only live behavior.

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

One thing still leaves the window: the viewers open a `localhost` URL in your
normal Windows browser. WSL forwards the port for you, so no Linux desktop or X
server is involved.

The viewers open that page in your browser themselves on startup, and print the
URL as well so there is still something to click if the browser cannot be
launched. Under WSL there is no Linux browser to hand it to, so `open_in_browser()`
in [src/twin_lab/meshcat_ui.py](src/twin_lab/meshcat_ui.py) passes the URL to the
Windows default browser through `explorer.exe`. Closing the tab does not stop the
viewer; reopen it from the URL, or from the **Ports** panel next to the terminal,
where the port is listed as *Meshcat viewer*.

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

Expect about `214 passed` in roughly 15 seconds. The suite exercises the CAD manifest,
inventory remap, SDF compiler, and collision plumbing without opening a viewer.
If this passes, setup is done.

### 7. EPICS archiver access (optional, one-time)

Only needed for recreating or mirroring real motor commands (see
[Playback and live data](#playback-and-live-data). Playback from a saved JSON
recording (`--playback-recording`) does not need any of this.

`archapp` (https://github.com/pcdshub/archapp), PCDS's Python interface to
the archiver appliance, is already part of `uv sync --all-extras` from step 4
above - it is a normal pip-installable package straight from its GitHub repo,
not something that needs the PCDS conda environment. There is no separate
one-time step here beyond the setup you already did.

Do not clone `archapp` into the Twin-Lab checkout. The upstream `archapp`
README's old "go to archapp/lib and type ipython" instruction is a manual
developer workflow for that standalone package; in Twin-Lab, `uv` has already
installed it into `.venv`. You can verify that with:

```bash
uv run python3 -c "from archapp.interactive import EpicsArchive; print('archapp OK')"
```

What this does *not* solve, and can't: actually reaching the archiver host
still requires being on the PCDS network (on-site or VPN) at the time you run
the command. Installing `archapp` only means the *code* is available - if a
command below fails to fetch data, that is a network reachability problem,
not a missing-dependency problem, and the command will tell you so plainly
rather than showing a raw error.

Twin-Lab uses `archapp` for real archiver access. `archapp` defaults to a
hostname of `psctlws01` (overridable via the `ARCHAPP_HOSTNAME` environment
variable, `ARCHAPP_DATA_PORT`/`ARCHAPP_MGMT_PORT` for the ports). If that
default doesn't resolve for your connection even while on VPN - your own DNS
server explicitly says it doesn't exist, rather than timing out - that's a
sign you are not on the PCDS network view that exposes that hostname, or the
archiver's real hostname is different for how you're connecting. Ask the PCDS
controls team for the correct `archapp` hostname or for the supported host
where `/reg/g/pcds/setup` is available, then set the hostname, e.g.:

```bash
ARCHAPP_HOSTNAME=the-right-hostname uv run slac-export-session
```

### Running commands

Every command below is prefixed with `uv run`. Step 5 already puts you in the
environment, but the prefix is kept everywhere so a copied line also works in a
plain terminal, on a machine without the Python extension, or in a script — and
so there is never a question of whether the right Python is selected. Run them
in the VS Code terminal, which already opens at the repository root.

## Collision reference and rechecking

This is the deeper collision-reference material behind the quick workflow near
the top. From the repository root:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The command opens a `http://localhost:7000` Meshcat page in your normal browser,
and prints the URL too in case it needs reopening. First load takes about 20
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

Shallow interference is not automatically real. Drake collides with the convex
hulls, which are always slightly larger than the parts, so a penetration of a
millimetre or two can be the decomposition's own error. See
[how wrong are the hulls?](#how-wrong-are-the-hulls-slac-hull-audit) for the
tool that measures that error budget per part, and press
[**`Verify contact against CAD`**](#correcting-for-the-hull-error-verify-contact-against-cad)
to take that error back off the pairs in front of you.

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

### How wrong are the hulls? (`slac-hull-audit`)

A convex piece can only ever be at least as big as the material it wraps, so
every decomposition overshoots: bolt holes fill in, small concavities get
spanned, and the hull surface sits slightly proud of the CAD surface. Drake
collides with that overshoot, not with the part, so a reported contact of a
millimetre or two may be entirely the decomposition's own error. This command
measures that error per part, which is what turns a red readout into either a
false positive or a real finding:

```bash
uv run slac-hull-audit
```

It reads the decomposition cache directly, so it needs no viewer and no compiled
package — only a build that has already run. Each cached hull is compared
against the tessellated part it replaces, and the parts are printed worst fit
first.

#### The three numbers

| Column | Meaning | Read it as |
| --- | --- | --- |
| `vol x` | Hull volume over CAD volume, `1.00` being an exact fit | Bulk overshoot of the part. The union of the hulls is used, not their sum, so overlapping pieces are not double-counted |
| `bulge mm` | Furthest a hull vertex sits *outside* the CAD surface | **The false-positive budget.** Material Drake will collide with that is not physically there |
| `gap mm` | Furthest a CAD vertex sits outside every hull | Real material the hulls fail to cover, which Drake can never collide with |
| `outside` | Share of CAD vertices left uncovered | How widespread that missing material is, rather than how deep |

Bulge is signed against the CAD surface, so hull vertices buried inside solid
material count as zero rather than as error; without that, a well-fitted part
reads as badly bulged. Volume overlap is estimated by sampling, so `vol x` moves
in the third decimal between runs.

The practical rule when triaging a clearance report: a touching pair whose
penetration is smaller than the sum of the two parts' `bulge` values, plus the
2 mm tessellation deflection already in the meshes, is inside the model's error
budget and is a candidate for `ignored_pairs` rather than an interference
finding. A pair that penetrates well past that budget is real.

#### Seeing it in Meshcat

The table says how badly a part fits; the three viewers say *where*. They are
flags on the same command, and each opens a `http://localhost:7000` page in your
browser, exactly like the collision viewer. Press `Escape` in the browser
or `Ctrl-C` in the terminal to stop.

**The ten worst parts, one per click**, which is the review to run if you run
only one:

```bash
uv run slac-hull-audit --tour
```

No index and no slider: the audit already knows which parts fit worst, so it
picks them and shows them in order, one at a time, framed by the camera.
`Next part (right arrow)` advances and wraps round at the end;
`Previous part (left arrow)` goes back. The arrow keys do the same, so a whole
review is ten keystrokes. The panel repeats the numbers for the part on screen —
its rank, its volume ratio and hull count, its bulge, and its gap — so the shape
and the row that flagged it are read together. `--tour-count` changes how many
parts are toured, and `--sort` decides what "worst" means, so
`--tour --sort gap` tours the parts with the most missing material instead.

**Every part where it actually sits**, for a whole-assembly overview:

```bash
uv run slac-hull-audit --assembly
```

The whole assembly is drawn with the translucent hulls layered over the grey CAD
mesh, worst fit first by index.

| Control | Effect |
| --- | --- |
| `Hulls: PIECE COLOURS (click for bulge shading)` | Cycles piece colours, bulge shading, hidden. Piece colours give each hull its own colour, so the cut lines CoACD chose are visible |
| (second click) `Hulls: BULGE SHADING` | Recolours every hull vertex grey where it lies on the CAD surface through amber to red at the full scale, so a spanned concavity shows up as a red patch on the part that has it |
| `CAD mesh: ON (click to hide)` | Hides the grey reference mesh, leaving only what Drake sees |
| `Show worst N parts` | Hides the good parts and leaves the bad ones standing in place |
| `Focus part index` | Flies the camera to one part and prints its row in the terminal |

The tour carries the same two hull buttons, so bulge shading is available there
too. Both colourings are uploaded once and swapped by visibility, so the toggle
is instant. The red end of the ramp defaults to 2 mm of outward bulge and moves
with `--bulge-scale-mm`. The grey end is deliberately held out to a quarter of
that scale: every hull vertex bulges a little at the tessellation deflection, so
a ramp anchored at zero paints the whole assembly amber and separates nothing.

**One part at a time by index**, when you already know the row you want:

```bash
uv run slac-hull-audit static_A003 --view
```

The `Part index` slider steps through the worst parts in isolation, framing the
camera on each, and the hull button cycles solid, wireframe, hidden. Use
`--view-limit` to change how many parts are uploaded (12 by default).

#### Narrowing and exporting

| Flag | Effect |
| --- | --- |
| `meshes` (positional) | Restrict to named cached source OBJs, by name or stem |
| `--part` | Regular expression matching part refs |
| `--sort volume\|bulge\|gap\|hulls` | Which metric defines "worst". Sort by `gap` to find parts that came out too small, by `volume` to find the parts worth a per-part `threshold` or `max_hulls` override |
| `--top` | Rows to print, 25 by default |
| `--csv` | Write every audited part to a CSV |
| `--cache-dir` | Audit a decomposition cache other than the default |
| `--refresh` | Re-measure instead of reusing cached distances |

The measurement itself is the slow part, so each part's distances are cached in
an `audit.npz` beside the hulls they judge, keyed to the source mesh digest and
the decomposition settings. A re-run costs about a second, and only
re-decomposed parts are re-measured. Reach for `--refresh` only after the
metrics themselves change.

### Correcting for the hull error (`Verify contact against CAD`)

Knowing the hulls are proud is one thing; taking that error back off a specific
reported contact is another. The collision viewer can do it on demand. Press
**`Verify contact against CAD`** and every touching pair in the current pose is
re-checked against geometry closer to the CAD than the hulls Drake collided,
and the result is printed to the terminal you launched from. This is the real
output at the reviewed home pose:

```
--- CAD re-check of touching pairs ---
  P1170 <-> P1112: hulls -2.69 mm; CAD meshes intersect -> CONTACT
  P1170 <-> P1069: hulls -2.37 mm; CAD meshes intersect -> CONTACT
  P1170 <-> P1111: hulls -2.10 mm; CAD meshes 1.18 mm apart -> explained by hull proudness
  P1170 <-> P1075: hulls -1.59 mm; CAD meshes 0.18 mm apart -> explained by hull proudness
  P780 <-> P805: hulls -1.34 mm; CAD meshes intersect -> CONTACT
  P056 <-> P1110: hulls -1.15 mm; CAD meshes intersect -> CONTACT
```

Two other line shapes appear when the exact distance cannot be had: `local
proudness 0.98 mm -> +0.56 mm` when it falls back to the audited numbers, and
`nothing cached to check it against -> unverified` when it has neither.

Note what that output actually says: four of the six are real. The proudness
correction does **not** explain most of the home-pose contacts, so they are
genuine touching in the assembled CAD rather than decomposition artefacts. Home
is an assembled state, so by-design contact there is expected — but it has to be
confirmed part by part and recorded, not assumed to be noise.

The button is a button rather than a live readout on purpose. The check costs
about 13 ms per pair once the meshes are cached, and roughly 95 ms on the first
press while they are parsed. That is fine for a review step and not fine for
every frame of the 20 Hz detector. It is only ever run on pairs already flagged
as touching. Pairs merely inside the warning band are left alone: the correction
exists to tell a decomposition artefact from an interference, and a pair with
clearance is neither.

Two corrections sit behind it, and the stronger one wins:

| Correction | What it uses | What it costs | What it leaves behind |
| --- | --- | --- | --- |
| Audited proudness | The `bulge` numbers `slac-hull-audit` already measured, sampled at the three hull vertices nearest the contact | A dictionary lookup | The tessellation deflection, and the fact that a hull face bulges more between its vertices than at them |
| Exact mesh distance | The two parts' own triangles, in the neighbourhood of the contact | ~13 ms per pair, warm | Only the 2 mm tessellation deflection the meshes were built at |

The first needs `slac-hull-audit` to have been run at least once, since it reads
the `audit.npz` the audit writes. Without it the pair comes back `unverified`
rather than silently uncorrected. The second needs nothing but the cached
tessellations, which the decomposition already depends on, so in practice it is
the one that answers.

Run against each other on the home-pose contacts, the two agree on four of six
pairs, and on the other two the audited proudness is the more pessimistic: it
calls `contact` where the exact distance finds 1.18 mm and 0.18 mm of real
clearance. That is the expected direction and the safe one. Bulge is sampled at
hull *vertices*, and a hull face stands off the CAD by more in its interior than
at its corners, so the correction systematically understates itself. Read a Tier
0 `explained` as trustworthy and a Tier 0 `contact` as "not yet ruled out".

The exact distance is a true triangle-to-triangle minimum over the triangles
within 20 mm of the two witness points Drake reported, capped at 400 triangles a
side so the pair arrays stay bounded. Both limits are comfortable: raising them
to 2000 triangles and 80 mm on the home-pose contacts does not move a single
result. Interpenetration is tested for separately, because the closest-feature
minimum between two triangles is only the distance when they are disjoint — an
edge passing clean through a face has candidate distances that are all positive.

Read the verdicts as:

| Verdict | Meaning |
| --- | --- |
| `CONTACT` | The correction did not account for the overlap. The parts really do meet |
| `explained by hull proudness` | The overlap fits inside the collision geometry's own error, and the CAD underneath is clear |
| `unverified` | Nothing cached to check the pair against. Run `slac-hull-audit`, or rebuild the decomposition so the source meshes are present |

`explained` is evidence, not a clearance measurement. It says the flag came from
the collision geometry rather than the hardware, which is a prompt to look at
the pair in the viewer and, if it is genuinely by design, to add it to
`ignored_pairs` with the reason recorded. It is not a statement that the parts
clear each other by the printed amount: that number still inherits the 2 mm
tessellation deflection, and a mesh built by inscribing facets is slightly
undersized on convex surfaces. Treat sub-millimetre results as "too close to
call from the model" and go to the CAD.

If a pair keeps coming back `CONTACT` and the CAD says otherwise, the
decomposition is too coarse there rather than too proud, and the lever is
`preprocess_resolution` on that part — see [convex decomposition](#convex-decomposition-coacd)
above.

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
re-modelled. Run
[**`Verify contact against CAD`**](#correcting-for-the-hull-error-verify-contact-against-cad)
at home before adding to this block: a pair that comes back `explained` is an
artefact of the collision geometry, and recording it as expected contact hides a
decomposition problem instead of a design one.

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

### Framing the assembly for a photograph

Every viewer carries a **view cube** in the bottom left corner, the same navigation
every CAD package puts there. Click a face to look straight down an axis, an edge
to look down the diagonal between two, or a corner for the three-quarter view;
the camera swings round to it and keeps the zoom it already had. The red, green,
and blue arrows through the cube are the model's own X, Y, and Z axes, so a
Twin-Lab view and a CAD view can be checked against each other by their axes
rather than by eye. Face names follow the CAD package: the front of the assembly
faces `-Y`, right is `+X`, top is `+Z`.

Two keys reframe the whole model rather than just turning it:

| Key | View |
| --- | --- |
| `Ctrl-I`, or `I` | **Isometric.** The camera sits at equal angles to all three axes, so no axis is foreshortened more than the others and the stack reads the same way in a still image as it does in a drawing |
| `Ctrl-T`, or `T` | **Trimetric.** Swung 30 degrees off the front and raised 20, which foreshortens the three axes by three different amounts. Use it when an isometric hides a feature behind an edge that happens to be parallel to the view |

Chrome keeps `Ctrl-T` for its own new tab and never passes it to the page, which
is why the unmodified keys do the same thing.

Both look in from the near left corner, the same corner the CAD package presents,
so putting the two side by side is a like-for-like comparison. The camera sits at
`+X -Y +Z`.

The framing is measured, not fixed: the key takes the bounding box of everything
on screen, aims at its centre, and stands back a little over twice the box
radius. Move the joints and press it again and it reframes around wherever the
stack has got to.

**Isometric view** in the collision viewer does the same from the panel, measured
from the collision hulls rather than the render. Expect it to think for about a
second on the 43841 stack, since it walks all 5000-odd hulls.

None of this touches the model or the clearance checking, only the camera, so the
mouse still works normally afterwards. For a clean plate in a screenshot, clear
**Collision detection** first so no parts are lit yellow or red.

## Playback reference

The active playback workflow is now near the top in
[Playback and live data](#playback-and-live-data). Keep lower sections focused
on CAD refreshes, older viewer tools, and repository maintenance.

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
| `slac-stage-cad` | `stage_cad_viewer` | Cached CAD viewer with manual sliders and animation; also plays finite playback and pseudo-live archive playback (`--playback-end ongoing`) |
| `slac-live-feed` | `stage_cad_viewer` | View-only viewer mirroring current EPICS commands live or from a refreshed live JSON file |
| `slac-export-session` | `archive_export` | Guided one-time export of a fixed past EPICS window to a replayable JSON file |
| `slac-export-live` | `archive_export` | Guided continuous export of a trailing EPICS window, for `slac-live-feed --live-file` to tail |
| `slac-collision` | `collision_viewer` | Drake viewer with live clearance reporting |
| `slac-compile-sdf` | `sdf_compiler` | Portable SDF share package |
| `slac-decompose` | `convex_collision` | Convex-decompose cached meshes ahead of time |
| `slac-hull-audit` | `hull_audit` | Measure how far the collision hulls overshoot the CAD |
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
