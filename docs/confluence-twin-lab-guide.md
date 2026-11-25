# Twin Lab: CAD Motion, Collision Review, and EPICS Archive Replay at LCLS

Interference is a serious risk for beamline motion systems throughout LCLS. Precision stages move laser and X-ray optics, detectors, and other equipment through tightly constrained spaces, often inside vacuum or helium-pumped assemblies. A collision can damage sensitive components, compromise an enclosure, and interrupt an experiment that depends on scarce beam time. In severe cases, the combined consequences of equipment damage, repairs, and lost experimental time can reach hundreds of thousands to millions of dollars. Understanding potential interference before moving hardware is therefore an important part of protecting both the instrument and the experiment.

Twin Lab connects Solid Edge CAD assemblies with reviewed motion definitions, collision analysis, and EPICS archive replay. It lets mechanical engineers inspect moving groups, explore travel ranges, investigate clearances, and reconstruct historical motor-command sequences in a shared visual model. Its reusable stage catalog supports expansion across LCLS assemblies that use similar precision-motion hardware. The model still requires careful review: even correctly configured CAD exports can contain missing geometry, unexpected configurations, or changed component identities. Twin Lab supports engineering judgment; it does not replace hardware verification, machine-protection systems, or approved operating procedures.

**[PUBLISHING ACTION: Replace this paragraph with Confluence's native Table of Contents macro.]**

## Start Here

### Repository and Documentation

- [Twin Lab on GitHub](https://github.com/slaclab/Twin-Lab)
- [Repository README and current commands](https://github.com/slaclab/Twin-Lab/blob/main/README.md)
- [CAD import and review reference](https://github.com/slaclab/Twin-Lab/blob/main/docs/cad-review.md)
- [Portable SDF and MATLAB sharing](https://github.com/slaclab/Twin-Lab/blob/main/docs/sdf-sharing.md)
- [Reusable stage catalog](https://github.com/slaclab/Twin-Lab/blob/main/config/stage-catalog.yaml)
- [Existing EPICS command-map example](https://github.com/slaclab/Twin-Lab/blob/main/config/crystal-stack-command-map.yaml)

For repository permissions, contact **[REPLACE WITH @MENTION: Koa Shen]** or **[REPLACE WITH @MENTION: Elon Goliger Mallimson]**.

This guide is for LCLS mechanical engineers using Windows, Ubuntu through Windows Subsystem for Linux (WSL), and Visual Studio Code (VS Code). It assumes no prior experience with VS Code, Git, or Linux terminals. Solid Edge remains the CAD authoring tool; Twin Lab imports a STEP export rather than the native Solid Edge assembly.

### Choose Your Route

| Your situation | Where to start |
| --- | --- |
| Nothing is installed yet | One-Time Windows and VS Code Setup |
| Twin Lab is installed and you want an existing model | Open a Previously Simulated Assembly |
| You have a new Solid Edge assembly | Prepare and Import a New Assembly |
| A previously simulated assembly has revised CAD | Update a Previously Simulated Assembly |
| You want historical equipment motion | Link an Assembly to EPICS Archive Data |
| You want clearance or interference results | Kinematic Simulation with Collision Detection |
| Your reviewed model is ready to share | Publish an Assembly Through Git LFS |

Use the page's table of contents to jump to those sections. First-time users should complete setup in order.

### What the Three Modes Do

| Mode | What drives motion | What it answers | Main limitation |
| --- | --- | --- | --- |
| Kinematic simulation | Manual sliders or cyclic animation | Do the right parts move along the right axes? | No collision queries |
| Kinematic simulation with collision detection | Manual sliders or cyclic animation | Which modeled parts are close, touching, or interfering? | Approximate collision geometry requires interpretation |
| EPICS archive replay | Archived motor commands or a saved recording | What commanded sequence occurred during a chosen interval? | Not measured motion, and no collision queries in the replay viewer |

The standard viewers do not issue motor commands to hardware. Any hardware test mentioned later must be performed separately by an authorized operator using the normal controls and procedures.

### Build Time and Review Expectations

Even a carefully configured Solid Edge export can produce import problems. Examples include library parts with no exported faces, alternate configurations appearing together, missing payloads, and occurrence identifiers changing between exports. Finding and correcting these issues is part of model preparation, not evidence that you necessarily exported incorrectly.

Allow **30-45 minutes for an Open Cascade mesh build** on a large assembly, and **an hour or longer for CoACD convex decomposition**. Smaller models may be faster; detailed geometry, settings, and available computing resources can make either operation slower. These are planning estimates, not guaranteed completion times.

**CoACD should be the last expensive preparation step.** First confirm the imported geometry, included and excluded parts, transparency and collision-only choices, and moving groups. Then confirm the kinematics. Only after those decisions are stable should you build collision hulls.

Generated meshes and hulls are cached under `.cache/twin_lab/`. Repeat runs can reuse them, but revisions or changed build settings can trigger rebuilding. Do not repeatedly force a rebuild simply because the first build is taking time. A blank browser page during loading is not, by itself, a failure; watch the VS Code terminal for progress or errors.

## One-Time Windows and VS Code Setup

### Gather What You Need

You need a Windows computer approved for WSL, permission to install software, an internet connection for setup, a GitHub account for restricted access or publishing, and enough disk space for the repository, Python dependencies, CAD files, and generated meshes. Ask local IT for help if installations or administrator rights are restricted.

Archive queries additionally require a network connection that can reach the PCDS archive service. Saved JSON recordings can be replayed without archive access.

### Install and Open VS Code

1. In your Windows browser, open [the official VS Code download page](https://code.visualstudio.com/Download).
2. Download the Windows installer appropriate for your computer and run it. Follow local IT requirements for user versus system installation.
3. If the installer offers **Add to PATH**, leave it enabled. This makes the `code` command available after setup.
4. Finish installation and launch **Visual Studio Code** from the Windows Start menu. Install it on Windows, not separately inside Ubuntu.
5. If a Welcome screen appears, you can leave its optional customization steps for later.

The left **Explorer** panel will show project files once a folder is open. **Terminal > New Terminal** opens a terminal inside the bottom panel. **View > Command Palette**, or `Ctrl+Shift+P`, opens a searchable list of editor actions. The **Extensions** view, also reachable with `Ctrl+Shift+X`, installs editor integrations.

Commands in this guide are pasted into that embedded terminal, not into the editor's file area, the Command Palette, or a browser address bar. Press Enter after pasting. When the command finishes, the terminal prompt returns. Commands that open viewers deliberately keep running until you stop them.

### Install Ubuntu Through WSL

Twin Lab runs on Linux. Drake does not provide native Windows wheels, so the normal Windows PowerShell terminal is not the environment used for simulation. WSL supplies Ubuntu, while VS Code remains your working window.

**Windows PowerShell only, initial setup:**

1. Close VS Code. In the Windows Start menu, search for **Visual Studio Code**, right-click it, and choose **Run as administrator**. Approve the Windows permission prompt if authorized.
2. Select **Terminal > New Terminal**. For this bootstrap step, a prompt beginning with `PS` is expected.
3. Paste and run:

```powershell
wsl --install -d Ubuntu
```

4. Follow any installation messages. Save other work and restart Windows when required. If WSL installation is blocked, stop here and ask IT rather than bypassing the restriction.
5. Reopen VS Code normally, without administrator rights, and open a new terminal.
6. Start Ubuntu:

```powershell
wsl -d Ubuntu
```

On its first launch, Ubuntu asks for a new Linux username and password. These are separate from your Windows credentials. Nothing appears while you type the password; that is normal. Remember it because Ubuntu may request it when installing packages.

When Ubuntu finishes initializing, its prompt resembles `yourname@computer:~$`. Type the following to leave this temporary Ubuntu session:

```bash
exit
```

**If Ubuntu is already installed:** do not reinstall it. Use the VS Code connection steps below. From a Windows terminal, `wsl --list --verbose` can confirm that Ubuntu uses version 2. If it shows version 1, ask IT whether it should be converted to WSL 2 for your machine.

### Connect the Entire VS Code Window to Ubuntu

1. Open **Extensions**, search for **WSL**, and install Microsoft's WSL extension.
2. Open the Command Palette and select **WSL: Connect to WSL**. If several distributions exist, choose Ubuntu using the corresponding distribution-selection command.
3. Wait for the bottom-left status indicator to show **WSL: Ubuntu**.
4. Open **Terminal > New Terminal**. This new terminal should run Ubuntu bash, not PowerShell.
5. Verify:

```bash
uname -srm
```

Expected result: a line beginning with `Linux`, usually containing `microsoft` or `WSL`. If the prompt still begins with `PS C:\`, reconnect the window to WSL before continuing.

**All remaining shell commands in this article run in the Ubuntu terminal inside VS Code.** The only exception is a block explicitly labelled Windows PowerShell.

### Install Git, Git LFS, and uv

Git manages version history, Git LFS manages large CAD files, and uv installs the project's Python and dependencies. Install Git LFS before downloading Twin Lab so STEP files arrive as real geometry rather than small pointer files.

Run these lines in order:

```bash
sudo apt update
sudo apt install -y git git-lfs pipx
git lfs install
pipx install uv
pipx ensurepath
source ~/.bashrc
```

`sudo` may ask for your Linux password. It will not display characters as you type. If a command fails, resolve that failure before continuing; do not assume later lines succeeded.

Verify:

```bash
git --version
git lfs version
uv --version
```

Each should print a version. If `uv` is not found, close this terminal with its trash-can button, create a new terminal, and try `uv --version` again.

### Download Twin Lab and Open Its Folder

Downloading a working copy of a Git repository is called **cloning**. Keep this copy on Ubuntu's filesystem, not under the Windows `C:` drive; Linux file-intensive operations are generally faster there.

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/slaclab/Twin-Lab.git
cd Twin-Lab
git lfs pull
ls -lh cad/DSG-000040389/source.stp
```

`~` means your Linux home folder. The current example STEP is a large file, approximately 88 MB, not a file of a few hundred bytes. If the clone or LFS download reports an access error, request permission from the contacts above and follow approved GitHub authentication instructions. Do not paste access tokens into shared notes or this article.

Open the downloaded project in the same VS Code window:

```bash
code -r ~/src/Twin-Lab
```

Alternatively, use **File > Open Folder**, browse to `/home/YOUR_LINUX_USERNAME/src/Twin-Lab`, and open it. VS Code's folder picker now browses Ubuntu because the window is connected to WSL. If prompted about workspace trust, trust the folder only after confirming that it is the intended repository.

Open a new terminal and check:

```bash
pwd
```

Expected result: `/home/YOUR_LINUX_USERNAME/src/Twin-Lab`. This is the **repository root**. Commands below assume this working directory.

### Install the Project Environment

```bash
uv sync --all-extras
```

uv reads the repository's Python version and dependency lockfile, creates `.venv`, and installs the CAD, Drake, collision, EPICS, and development packages. Initial installation may take several minutes. Do not manually select an arbitrary system Python version instead.

In VS Code, install Microsoft's **Python** extension into **WSL: Ubuntu**. Then use the Command Palette to run **Developer: Reload Window**. The repository's editor settings point to `.venv/bin/python`.

If necessary, run **Python: Select Interpreter** and select the interpreter inside this project's `.venv`. In a fresh terminal, check:

```bash
which python
```

Expected result: a path ending in `Twin-Lab/.venv/bin/python`. Article commands still use `uv run`, which selects the project environment even if terminal activation has not taken effect.

### Verify Installation

```bash
uv run pytest -q
```

Expected result: the test suite completes without failures. The exact test count can change as the repository develops. These tests do not establish that your particular assembly or hardware is safe.

For a first visual check, run:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

The terminal remains occupied while the viewer runs. A browser normally opens at `http://localhost:7000`; otherwise use the URL printed in the terminal. Wait for geometry loading to finish. Use **Stop viewer**, or click inside the terminal and press `Ctrl+C`, before launching a different viewer.

**Setup checkpoint:** the repository is open in WSL, dependencies are installed, tests pass, and the example viewer loads. The bundled assembly is an example with its own review assumptions, not a certified model of every LCLS system.

## Open a Previously Simulated Assembly

1. Launch VS Code and reconnect to **WSL: Ubuntu** if necessary.
2. Use **File > Open Folder** to open your Twin-Lab folder.
3. In Explorer, locate the drawing under `cad/` and its reviewed `*.inventory.yaml` under `reviews/`.
4. Confirm that the matching STEP, manifest, inventory, stage catalog, and any selection review or supplemental geometry are present. A STEP alone is not a complete simulated assembly.
5. Open a terminal at the repository root and launch the reviewed inventory.

For the bundled example:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

For another assembly, use its own inventory path. If collaborators have published changes, first inspect **Source Control** for local edits. Only use **Pull** when those edits have been safely handled; ask for help if VS Code reports a conflict. After updating, run `git lfs pull` and `uv sync --all-extras` if new CAD or dependencies were published.

## Prepare and Import a New Assembly

### Prepare the Solid Edge Export

Before exporting, confirm the intended physical configuration with the assembly owner. Include the stage internals needed to distinguish fixed bodies from moving carriages, payloads and adapters, and nearby physical obstacles that matter to clearance.

Check that library or standard parts export as actual geometry, not just references that Solid Edge resolves from a local library. Exclude alternate configurations and construction geometry where appropriate. Preserve meaningful assembly names and, where practical, export from a consistent managed configuration to reduce identity churn between revisions.

Vacuum and helium enclosures should be represented when they constrain motion. The simulation does not model pumping, pressure, structural response, leak tightness, thermal effects, or flexible cable and hose behavior. Include suitable reviewed geometry for any physical envelope that matters; do not assume an absent component is automatically clear.

**[REVIEW BEFORE PUBLICATION: Add the locally approved Solid Edge STEP export settings or link to the existing LCLS export procedure. Exact exporter options are not specified by this repository.]**

### Create a Working Branch

A branch isolates the new assembly work from the shared starting point. In VS Code, open the Command Palette, choose **Git: Create Branch**, and enter a descriptive name such as `assembly-your-drawing`. Creating a branch locally does not publish anything.

Do not discard unrelated changes in Source Control. If the folder already has work you do not recognize, ask its owner before proceeding.

### Create the Assembly Folder and Copy the STEP

The examples below use `DSG-NEW` as an obvious placeholder. Replace it consistently with your actual drawing identifier. The inventory example is named `assembly.inventory.yaml` and the visibility recipe `static-review.yaml`; these are filenames you create, not required names for all assemblies.

```bash
mkdir -p cad/DSG-NEW/reviews
```

Find the STEP export in Windows File Explorer. Copy its Windows path. From Ubuntu, `C:\Users\YOUR_WINDOWS_USERNAME\Downloads\your-assembly.stp` becomes `/mnt/c/Users/YOUR_WINDOWS_USERNAME/Downloads/your-assembly.stp`.

Edit the source path before running:

```bash
cp "/mnt/c/Users/YOUR_WINDOWS_USERNAME/Downloads/your-assembly.stp" "cad/DSG-NEW/source.stp"
```

Quotes preserve paths containing spaces. Naming the repository copy `source.stp` also matches the repository's existing Git LFS rule for `*.stp`. Keep the original export elsewhere until the import is verified.

You can also copy the file into the folder through Explorer using the WSL filesystem path `\\wsl$\Ubuntu\home\YOUR_LINUX_USERNAME\src\Twin-Lab\cad\DSG-NEW`. Do not place the working repository under `/mnt/c` just to make file transfer easier.

### Generate the Manifest and Inspect the Tree

Start with hierarchy inspection, without generating preview meshes:

```bash
uv run slac-cad-manifest cad/DSG-NEW/source.stp --show-tree --manifest-only --no-preview
```

Expected output includes **STEP READ OK**, assembly and part counts, and a manifest path. `cad/DSG-NEW/manifest.json` records the imported hierarchy and placements.

Short references beginning with `A` identify assemblies; references beginning with `P` identify leaf parts. These references are meaningful for this manifest and STEP revision. They are not permanent hardware identities.

In VS Code, open the manifest or search the printed tree for known stage and payload names. Confirm the expected root assembly and required subassemblies before creating motion definitions. A manifest entry does not guarantee that a part contains faces; visual review is still required.

### Review Geometry and Show/Hide Decisions

Create a new static review and view the imported assembly:

```bash
uv run slac-static-review cad/DSG-NEW/source.stp --new-review --recipe cad/DSG-NEW/reviews/static-review.yaml
```

Run `--new-review` only once. It refuses to overwrite an existing recipe. This initial review may build meshes and take considerable time, but does not run CoACD.

Inspect the browser view against Solid Edge. Check for missing stages, payloads, duplicated configurations, unexplained overlaps, misplaced components, and incorrect scale. Examine the spaces the mechanism will move through, not only its home pose.

The generated review contains a STEP hash and an empty `omitted_names` mapping. Preserve those generated fields. In the VS Code editor, you can add optional selection lists. The following is an illustrative fragment; replace the names with exact names present in your manifest, or use empty lists when not needed:

```yaml
omitted_assemblies: [EXACT_ALTERNATE_ASSEMBLY_NAME]
omitted_components: [EXACT_NONPHYSICAL_COMPONENT_NAME]
translucent_assemblies: [EXACT_ENCLOSURE_ASSEMBLY_NAME]
collision_only_assemblies: [EXACT_COVER_ASSEMBLY_NAME]
```

Selection names are matched using the review tool's name normalization, not the `A###` or `P###` reference. A repeated name may affect multiple occurrences. For occurrence-specific exclusions, use the scoped rules documented in the existing CAD-review guide rather than hiding every copy of a part.

Understand the difference:

| Selection | Normal illustration | Collision model |
| --- | --- | --- |
| Retained geometry | Visible | Included when incorporated in the reviewed motion model |
| Translucent geometry | Transparent | Not excluded merely because it is transparent |
| Omitted geometry | Hidden | Excluded by the selection review; cannot protect against collisions with that geometry |
| Collision-only assembly | Hidden | Retained for collision checks |

Save the recipe with `Ctrl+S`. Stop the old viewer, then rerun without `--new-review`:

```bash
uv run slac-static-review cad/DSG-NEW/source.stp --recipe cad/DSG-NEW/reviews/static-review.yaml
```

If the preview appears stale after selection edits, use the same command with `--rebuild` once. Do not change the STEP hash manually to silence a revision mismatch.

**Geometry checkpoint:** required geometry is present and accurately placed; omitted components are deliberate and documented; enclosures and covers have the intended visibility and collision participation. Do not start CoACD yet.

## Define and Review Assembly Motion

### Understand the Reviewed Files

STEP supplies geometry and placements, not a complete trustworthy mechanism definition. An engineer must identify fixed bodies, moving carriages, joint axes, limits, pivot points, and which adapters or optics move together.

| File | Purpose | How it changes |
| --- | --- | --- |
| `source.stp` | Exported geometry | Replace through a reviewed revision workflow |
| `manifest.json` | Generated hierarchy and references | Regenerate from STEP, not by hand |
| `config/stage-catalog.yaml` | Reusable stage-model facts | Add or correct verified model definitions |
| `reviews/assembly.inventory.yaml` | Assembly-specific stages, chains, attachments, limits | Edit and review in VS Code |
| `reviews/static-review.yaml` | Included, omitted, translucent, and collision-only geometry | Review against the exact STEP |
| Assembly command map | Joint-to-PV mapping | Review against the inventory and controls documentation |

The importer can also generate a `slac-kinematics-review/v1` rigid-group template. That is a different review format; it is not a stage inventory that can simply be passed to `slac-stage-cad`. This article follows the catalog-backed inventory workflow used by the standard stage and collision viewers.

### Match Stages to the Reusable Catalog

Open `config/stage-catalog.yaml` in VS Code. Match each stage's actual manufacturer, model, handedness, and internal component layout. Similar-looking stages are not necessarily interchangeable.

Catalog facts include joint type, local axis, fixed and moving component roles, default travel limits, pivot offsets where needed, and maximum speed when known. Internal role numbers refer to the stage's component layout, not arbitrary whole-assembly `P###` references. Confirm them against the imported stage subtree.

Catalog distances are in metres and angles in radians. A 10 mm distance is `0.010` metres. Use the exact catalog key in the inventory. If a model is absent, add it only after reviewing manufacturer specifications and actual CAD component roles; do not substitute an unrelated model just to make the viewer run.

### Create the Stage Inventory

In Explorer, right-click the new drawing's `reviews` folder, choose **New File**, and name it `assembly.inventory.yaml`. YAML uses indentation; use spaces, not tabs. Save after editing.

This one-axis example illustrates the file structure. Its `A010`, `P020`, `P021`, drawing name, library ID, and catalog choice are **illustrative, not imported facts**. Replace every reference with one from your own manifest and use the actual stage model. Delete unused blocks instead of leaving fictitious parts in the model.

```yaml
schema: slac-stage-inventory/v1
source_step: cad/DSG-NEW/source.stp
cad_manifest: cad/DSG-NEW/manifest.json
selection_review: cad/DSG-NEW/reviews/static-review.yaml
stage_catalog: config/stage-catalog.yaml
subassembly:
  ref: A001
  name: EXACT_ROOT_ASSEMBLY_NAME
stage_instances:
  - ref: A010
    library_id: EXACT_STAGE_LIBRARY_ID
    catalog: kohzu_sxa0530_r01_bm
motion_chains:
  Optic Translation: [A010]
joint_limit_overrides:
  A010:
    unit: meter
    limits: [-0.015, 0.015]
    home: 0.0
attachment_overrides:
  fixed: [P020]
  moving:
    A010: [P021]
```

`stage_instances` matches assembly occurrences to catalog models. `motion_chains` lists simple stages in base-to-payload order. `attachment_overrides.fixed` identifies explicitly fixed parts; `moving` associates adapters and payloads with the owning stage carriage.

For several serial stages, list them in physical base-to-payload order. An upstream stage should carry downstream stages and their payload. Model stationary nearby obstacles using `static_geometry`, following the existing inventory's `ref`, `name`, and `cad_id` structure. Do not assume a visibility recipe alone assigns every obstacle to a motion or static link.

Compound stages, such as a two-axis XY unit, use `compound_motion_chains`. The existing 43841 inventory provides examples with separate keys such as `A233:y` and `A233:x`, component roles, local axes, and per-axis limits. Their role ordering and axis directions must be adapted to the actual stage; do not paste that assembly's references into a new model.

### Review Homes, Limits, and Payload Ownership

Check each stage's positive direction and rotary pivot against its mounting orientation. Use assembly operating limits, which may be narrower than catalog travel. Document whether the imported CAD position is the intended logical home or whether a reviewed `cad_position` adjustment is required.

The inventory supports `joint_limit_overrides` in metres or degrees, with the explicit `unit` field. Do not mix these with catalog angular values, which are radians. The browser sliders display millimetres or degrees for convenience.

Do not use `home` as an unexplained correction until you understand the relationship between CAD position, slider coordinates, and controller coordinates. A plausible-looking home pose is not proof of a valid calibration.

## Kinematic Simulation

### Launch and Inspect

For your assembly, after replacing `DSG-NEW` and completing its inventory:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml
```

For the bundled assembly:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Open the printed browser URL if it does not open automatically. Under WSL, the normal Windows browser displays the viewer. Keep VS Code available to read diagnostics. Closing the browser tab does not stop the viewer process.

Start at the reviewed home pose. Move one slider a small amount, inspect the result, and reset before checking the next joint. Confirm:

- The fixed stage body remains fixed relative to its parent.
- Only the intended carriage and payload move.
- Downstream stages move with upstream carriages.
- Rotary motion occurs about the correct pivot.
- Positive direction and units match the reviewed mechanism.
- Limits match the intended assembly operating range.
- Required static obstacles remain in place.

Do not infer clearance from this viewer; it does not query collisions.

### Use the Motion Controls

**Reset to home** restores the reviewed home pose and stops cyclic animation. **Animation: OFF (click to start)** starts a cyclic demonstration; clicking it again returns control to the manual sliders.

**Auto motion range (% of travel)** controls the excursion around home, using the smaller available travel on either side. **Auto motion period (s)** controls the cycle time. Joints are phase-staggered. Start with a small range after individual-axis checks. This animation is a demonstration, not an actual controller trajectory or an exhaustive proof of clearance.

### Rebuild Only When Needed

The cache normally rebuilds when its inputs change. To force stage meshes to rebuild when diagnosing a stale scene:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --rebuild
```

To prepare the motion scene without opening its viewer:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --prepare-only
```

Neither command requests CoACD collision decomposition. Avoid repeated forced mesh builds while an earlier build is still running.

**Motion checkpoint:** every joint, moving group, payload attachment, operating limit, and home convention has been checked. Fix incorrect geometry or ownership before building collision hulls.

## Link an Assembly to EPICS Archive Data

### Find and Confirm the PVs

EPICS identifies controls-system values using process variables, or **PVs**. Start with the assembly's page in [SLAC Confluence](https://confluence.slac.stanford.edu/), or the established controls documentation for that assembly. If you need help finding or interpreting PVs, ask the **controls engineer assigned to your hutch**.

For every powered axis, record the physical stage, simulated joint key, command PV, engineering units, positive direction, zero convention, and whether the PV is archived. Confirm that it represents the commanded position expected by the replay model, not a status bit or a different type of signal. A position readback PV is not interchangeable with a command PV in this workflow.

Unpowered/manual axes have no command history. Record their actual manually set positions separately. An omitted powered axis must be explicitly identified as a replay coverage gap; do not treat its lack of motion in the viewer as proof that it stayed still on hardware.

### Create an Assembly-Specific Command Map

In Explorer, create `config/DSG-NEW-command-map.yaml`. The format retains the existing schema name even when the assembly is not a crystal stack.

The chain name must match the inventory's chain name exactly. For a simple stage, `ref` is its assembly reference. For a compound stage, use its exact joint key, such as `A010:x`, not just the stage reference. Axis labels help describe the joint; the `ref` connects it to the model.

The following matches the illustrative one-axis inventory above. Replace the PV before using it:

```yaml
schema: slac-crystal-stack-command-map/v1
joints:
  Optic Translation:
    x:
      ref: A010
      joint_type: prismatic
      command_pv: REPLACE_WITH_ACTUAL_ARCHIVED_COMMAND_PV
```

Use `prismatic` for a linear axis and `revolute` for a rotary axis. A compound stage's individual linear axes are mapped as prismatic joints, not as `planar_xy` tracks.

Always pass your command map explicitly when exporting or replaying a new assembly. Defaults refer to the bundled crystal/polycap assembly. The exporter prints an example replay command for that bundled assembly, so replace its inventory path and add your map rather than blindly following the printed suggestion.

### Verify Units, Direction, and Zero

The current replay code assumes command values are **millimetres for linear joints** and **degrees for rotary joints**. It converts these to metres or radians and adds the joint's reviewed inventory home, which defaults to zero when no override is present.

There are no generic per-PV scale, sign, or controller-zero fields in the command-map format. Do not invent YAML settings for these or assume they are automatically inferred. If the controls use different units or a different coordinate convention, resolve the model calibration or arrange a reviewed conversion with the maintainer before trusting replay.

Controller zero may change with power cycles or homing practices. Confirm the zero for the specific historical interval. A joint may animate smoothly while still being displaced from its real hardware position.

Playback estimates travel between discrete setpoints using available stage-catalog maximum speeds. It is not encoder feedback or a full controller model. Unknown catalog speeds may result in instantaneous changes, and acceleration, stalls, and other hardware behavior are not established by the reconstruction.

### Choose a Known Time Interval

Confirm the last experiment's date and time, then select a short interval where commands are known to have occurred. Record the timezone as well as the clock time.

Alternatively, an authorized operator can connect the motion system and perform a few controlled test commands using the hutch's approved operating procedures. Verify actual hardware clearance independently first. Record commanded values, timestamps, initial pose, and manual-axis settings. Twin Lab does not issue these commands.

Use explicit timezone offsets in examples you save. `2026-08-26T15:32:20-07:00` includes a UTC offset; `2026-08-26T15:32:20` does not. Pacific daylight time uses `-07:00` and Pacific standard time uses `-08:00`; confirm which applies to the chosen date. Interactive exports accept everyday time formats, but an omitted offset relies on the computer's local timezone.

### Export a Saved Session

Archive export requires a network path to the PCDS archive service. Installing dependencies alone does not provide this access. If a request fails, check the network and ask the hutch controls engineer about supported archive access.

For your assembly, run the interactive exporter:

```bash
uv run slac-export-session --command-map config/DSG-NEW-command-map.yaml --out recordings/DSG-NEW-session.json --pv-names
```

Enter start and end times when prompted, inspect the proposed interval and output path, and confirm. The terminal reports per-joint command counts. Investigate missing data before accepting the recording. A count may include a prior value used to initialize the window, so a nonzero count does not necessarily mean that axis changed position during it.

For the bundled map, this example supplies a fixed interval. Replace dates with your known interval as appropriate:

```bash
uv run slac-export-session --command-map config/crystal-stack-command-map.yaml --start 2026-08-26T15:32:20-07:00 --end 2026-08-26T15:36:40-07:00 --out recordings/review-session.json --pv-names
```

The saved JSON can be replayed without network access, provided the matching model and command map are available.

## EPICS Archive Replay

### Replay a Saved Recording

For your assembly:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --playback-command-map config/DSG-NEW-command-map.yaml --playback-recording recordings/DSG-NEW-session.json --pv-names
```

For an included example recording:

```bash
uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml --playback-command-map config/crystal-stack-command-map.yaml --playback-recording recordings/session-20260826T1552.json
```

Finite playback provides speed, pause, restart, and scrub controls. The recording drives the mapped joints; these are not freely editable manual sliders. The bundled viewer exposes manual sliders for the two unpowered LX10 axes. Set them to the actual hardware settings for the interval being reviewed.

Do not assume every unmapped joint will have a manual replay slider: the current special handling is specific to the bundled model. Unmapped or empty tracks can leave parts stationary at model defaults, producing an incomplete reconstruction. Record and resolve these gaps with the maintainer.

Compare the replay with the short known command sequence first. Check the axis identity, direction, magnitude, starting pose, and timestamps. Only then expand to longer sessions.

**Replay does not perform collision queries.** If a replay pose needs a clearance check, reproduce the relevant joint coordinates in the collision viewer and evaluate that pose separately. Do not describe a replay as a collision-checked trajectory.

### Replay Directly from a Fixed Archive Window

This avoids a saved file but requires archive access during the query:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --playback-command-map config/DSG-NEW-command-map.yaml --playback-start 2026-08-26T15:32:20-07:00 --playback-end 2026-08-26T15:36:40-07:00 --playback-speed 1
```

Replace the drawing, map, and times. Start at 1x until timing is understood. Use finite playback's speed controls for review; speed scaling changes the viewing clock, not the historical commands.

### Continuous Historical Replay and Resume

To start at a historical time and continue extending the archive window at real-time speed:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --playback-command-map config/DSG-NEW-command-map.yaml --playback-start 2026-08-26T15:32:20-07:00 --playback-end ongoing --playback-resume-file recordings/DSG-NEW-resume.json
```

**Stop continuous playback** holds the feed at its current archive timestamp. **Resume continuous playback** continues within the same browser session. This mode does not provide finite playback's speed multiplier, restart, or scrub controls.

Stop the viewer normally to save the last archive timestamp. Reopen using the same inventory, map, and resume file:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --playback-command-map config/DSG-NEW-command-map.yaml --playback-start resume --playback-end ongoing --playback-resume-file recordings/DSG-NEW-resume.json
```

Separate resume files keep unrelated runs from sharing a saved timestamp. Continuous historical playback is not the same as a direct real-time controls connection.

### Optional Near-Live Archive Mirror

This follows current archived commands with archive and polling lag. It is not a true direct EPICS live feed; that source is not implemented yet.

In one VS Code terminal with archive access:

```bash
uv run slac-export-live --command-map config/DSG-NEW-command-map.yaml --out recordings/DSG-NEW-live.json
```

Open a second terminal with **Terminal > New Terminal**, then run:

```bash
uv run slac-live-feed cad/DSG-NEW/reviews/assembly.inventory.yaml --command-map config/DSG-NEW-command-map.yaml --live-file recordings/DSG-NEW-live.json
```

Both commands use the same file path in this local example. If they run on different computers, the viewer must receive an up-to-date copy through a supported sharing mechanism; the filename alone does not transfer data.

Use live-style stop controls rather than historical scrub or speed scaling. Stop the exporter with `Ctrl+C` when finished, as well as stopping the viewer. A refreshed recording is not a hardware interlock.

## Kinematic Simulation with Collision Detection

### Final Check Before CoACD

Only proceed when geometry and kinematics have passed review. Confirm enclosures, covers, and other obstacles are included in the right links or static groups. Resolve unwanted configurations and missing physical geometry first.

CoACD decomposes concave parts into convex pieces usable by Drake's proximity queries. This can take an hour or longer on large assemblies. Plan the run, keep the computer powered, and avoid launching duplicate builds. Monitor the terminal rather than refreshing the browser repeatedly.

For the normal motion-review workflow, the collision viewer prepares the required collision geometry automatically:

```bash
uv run slac-collision cad/DSG-NEW/reviews/assembly.inventory.yaml
```

For the bundled assembly:

```bash
uv run slac-collision cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

**Optional static-selection preparation:** after approving the selection recipe, you can explicitly prepare its selected part hulls without opening a viewer:

```bash
uv run slac-static-review cad/DSG-NEW/source.stp --recipe cad/DSG-NEW/reviews/static-review.yaml --decompose --workers 2 --no-view
```

This prepares hulls, not a validated motion model. Cache compatibility depends on the build path and settings; do not assume it eliminates every subsequent collision-viewer build.

### Interpret Clearance Results

| Viewer state | Meaning |
| --- | --- |
| Green / clear | No reported pair inside the selected warning band |
| Yellow / close | At least one reported pair inside the warning band, without contact |
| Red / interference | At least one reported touching or penetrating pair |

The **Clearance warning band (mm)** controls the yellow threshold. A close result is a design-review warning, not a universal pass/fail criterion. Choose a meaningful band for the application rather than reducing it merely to make the display green.

Offending collision geometry is highlighted. The viewer identifies worst pairs by reference, and the terminal provides diagnostic information. Use **Log clearance report** to print a fuller report for review.

**Collision detection: ON (click to disable)** temporarily disables queries; remember to re-enable them before interpreting clearance. **Showing: whole assembly** can switch to **worst pair only** for a focused inspection. The focused display shows tested collision hulls, not necessarily exact CAD surfaces.

The animation controls can explore a motion sweep with checking enabled. They evaluate displayed poses, not every mathematically possible configuration or every point along an arbitrary hardware trajectory.

### Verify Suspected Contacts

Convex decomposition is an approximation. Added material can create apparent contact, while lost fine detail can omit real geometry. A red result deserves investigation, but a shallow hull penetration is not automatically a real CAD overlap. A green result also depends on model completeness, exclusions, and geometric accuracy.

Use **Verify contact against CAD** when examining reported contacts. For deeper hull-quality inspection, the audit tool can compare cached decompositions with their source meshes:

```bash
uv run slac-hull-audit
```

For an assembly view of audited cached geometry:

```bash
uv run slac-hull-audit --assembly
```

Do not silence an unexplained contact by adding it to an exclusion list. Permanent ignored pairs need a mechanical justification. Home-only exclusions apply at the modeled home and can affect what is reported there; review those separately from exclusions that apply throughout travel.

**Collision checkpoint:** the reviewed geometry, selected parts, operating range, observed contacts, approximation limits, and exclusions are documented. Simulation alone does not authorize hardware motion.

## Update a Previously Simulated Assembly

### Preserve the Previous Review First

A new STEP revision can change references even when part numbers remain familiar. An old `A###` or `P###` token can now identify a different object, which is more dangerous than a visibly missing reference.

Before replacing anything, preserve the previous STEP, manifest, inventory, selection review, and command map. Use a reviewed local Git commit through Source Control, or copies outside the working assembly folder. Create a revision branch and do not combine the update with unrelated work.

The general procedure below is candidate-first but not an automatic transaction. Do not open the old inventory against revised CAD until the candidate reviews have been accepted.

### Import and Review a Candidate Revision

Create a temporary revision folder and copy in the new export:

```bash
mkdir -p cad/DSG-NEW/revision-candidate
cp "/mnt/c/Users/YOUR_WINDOWS_USERNAME/Downloads/revised-assembly.stp" "cad/DSG-NEW/revision-candidate/source.stp"
```

Generate its manifest and a remapped inventory without replacing the old files:

```bash
uv run slac-cad-manifest cad/DSG-NEW/revision-candidate/source.stp --refresh-manifest --manifest-only --no-preview --remap-stage-inventory cad/DSG-NEW/reviews/assembly.inventory.yaml --previous-manifest cad/DSG-NEW/manifest.json --remapped-inventory-output cad/DSG-NEW/revision-candidate/assembly.inventory.yaml
```

Read the unresolved-reference report. Open the old and candidate manifests and inventories in VS Code and compare component names, parent assemblies, and placements. Resolve ambiguities manually. Automated remapping does not approve changed mechanical intent or guarantee every YAML field is revision-correct.

If managed part numbers changed, a reviewed alias file can help. Example format:

```yaml
name_aliases:
  OLD_LIBRARY_OR_DRAWING_ID: NEW_LIBRARY_OR_DRAWING_ID
occurrence_id_aliases: {}
```

Save it under the drawing's `reviews` folder and add `--alias-map` with its path when rerunning the remap command. Aliases must describe confirmed identities, not convenient guesses.

Carry the previous static selection into a candidate recipe:

```bash
uv run slac-static-review cad/DSG-NEW/revision-candidate/source.stp --recipe cad/DSG-NEW/reviews/static-review.yaml --carry-review cad/DSG-NEW/manifest.json --output-review cad/DSG-NEW/revision-candidate/static-review.yaml
```

The output path must not already exist. The tool reports new component names; inspect those and repeated occurrences before accepting the carried decisions. View the candidate without decomposition:

```bash
uv run slac-static-review cad/DSG-NEW/revision-candidate/source.stp --recipe cad/DSG-NEW/revision-candidate/static-review.yaml
```

Do not carry historical omission lists into an unrelated new assembly. Start a new review instead.

### Accept and Revalidate the Revision

After resolving identities and selections, use Explorer to install the accepted STEP, inventory, and selection recipe in the drawing's normal locations. Preserve the old manifest as `manifest.previous.json`, then regenerate the canonical manifest:

```bash
uv run slac-cad-manifest cad/DSG-NEW/source.stp --refresh-manifest --manifest-only --no-preview
```

Ensure the accepted inventory points to the canonical STEP, manifest, catalog, and selection-review paths, not the temporary candidate folder. Verify that its refs match the newly generated canonical manifest. Review any other path-bearing fields and supplemental assets as well.

Recheck homes, limits, moving ownership, compound axes, static geometry, and intentional contact exclusions. Update the command map separately; inventory remapping is not a promise that every EPICS mapping or old recording has been repaired.

Saved recordings store joint references. If references changed, old recordings may require a reviewed `legacy_refs` mapping in the command map, as shown by the bundled map. Do not add ambiguous mappings or assume a historical recording remains compatible just because it loads.

Re-run kinematic and short replay checks first. Run collision rebuilding last. Remove or exclude temporary candidate files from the final publication after accepted files and backups are safely preserved.

### Dedicated 43841 Helper

The repository includes `slac-refresh-43841` for the existing `DSG-000040389` review only. It is not a general importer for other drawings.

The helper checks the static review against the replacement STEP. A new hash requires carrying and reviewing that selection first. Follow the repository CAD-review reference, preserve the old review, and have the accepted selection ready before invoking the helper:

```bash
uv run slac-refresh-43841 "/mnt/c/Users/YOUR_WINDOWS_USERNAME/Downloads/DSG-000040389.stp" --rebuild-viewer-cache
```

The helper validates candidate identities before replacing the canonical STEP and motion-review files. If it rejects the update, inspect the errors and candidate files under `.cache/twin_lab/43841-refresh-candidates/`. Do not bypass the checks by copying revised CAD over the old model and building collision hulls.

Even after helper success, recheck the EPICS map, replay assumptions, physical configuration, and motion. Identity matching is not mechanical approval.

## Publish an Assembly Through Git LFS

### Confirm Permission and File Selection

Publishing is separate from importing STEP locally. Confirm that the CAD and any recordings are approved for the repository's visibility and that you have permission to publish a branch. Contact **[REPLACE WITH @MENTION: Koa Shen]** or **[REPLACE WITH @MENTION: Elon Goliger Mallimson]** for repository access.

In VS Code, open **Source Control** and review each changed file. Include the accepted STEP, canonical manifest, inventory, selection recipe, assembly command map, required supplemental geometry, and verified catalog changes. Include the old manifest if it is intentionally retained for revision support. Do not publish generated caches, virtual environments, temporary candidates, credentials, or unrelated changes.

The repository tracks lowercase `*.stp` through Git LFS. Keeping the imported file named `source.stp` avoids extra rules. For a different extension, establish the correct LFS rule before staging large files and include the resulting `.gitattributes` change.

Verify the normal STEP path:

```bash
git check-attr filter -- cad/DSG-NEW/source.stp
```

Expected output ends in `filter: lfs`. If not, stop and correct tracking before committing the large file.

### Set Your Git Identity Once

Git commits identify their author. Edit the placeholders and run these inside the repository to set its local author identity:

```bash
git config user.name "YOUR FULL NAME"
git config user.email "YOUR APPROVED GITHUB COMMIT EMAIL"
```

Use the email associated with your approved GitHub workflow, including a GitHub-provided private address if required. These settings do not authenticate your account.

### Stage, Check, and Commit in VS Code

1. Save your edited files with `Ctrl+S`.
2. In Source Control, click each file to inspect its diff. A binary STEP will not have a useful text diff; confirm its source revision separately.
3. Use the **+** beside each intended file to stage it. Do not use Stage All if unrelated changes are present.
4. In the terminal, run:

```bash
git diff --cached --check
git lfs ls-files
```

The first command should report no whitespace errors. The LFS list should include the staged STEP. Run the project tests, and finish the assembly review checks before committing:

```bash
uv run pytest -q
```

5. Enter a descriptive Source Control message, such as `Add reviewed motion model for DSG-...`, and choose **Commit**. A commit saves history locally; it does not yet upload the branch.

### Publish and Request Review

Use **Publish Branch** for a new branch or **Push** for an already-published working branch. Follow the approved GitHub sign-in flow if prompted. Git LFS uploads tracked large files as part of the push. If authentication does not work from WSL, ask for help rather than copying credentials into configuration files.

Open the repository on GitHub and create a pull request for the branch. Include the source CAD revision, modeled physical configuration, stage and motion checks performed, selection exclusions, collision findings, EPICS coverage and calibration assumptions, and remaining uncertainties.

Do not push unreviewed assembly work directly to the shared main branch. If changes are requested, edit them in the same branch, repeat the affected checks, commit, and push again.

A collaborator should download the branch with Git LFS and verify it. Sharing only an exported STEP, or only a Meshcat URL tied to your running computer, is not a reproducible Twin Lab model.

## Troubleshooting

### Ubuntu Commands Fail in PowerShell

A `PS C:\` prompt means you are in a Windows shell. Reconnect the VS Code window using **WSL: Connect to WSL**, check the status indicator, and open a fresh terminal. Do not translate the simulation commands into PowerShell.

### The STEP Is Only a Few Hundred Bytes

It may be a Git LFS pointer rather than geometry. Run:

```bash
git lfs install
git lfs pull
```

Check the file size again and resolve download permissions if reported. Do not pass a pointer file to the CAD importer.

### A Command Cannot Find an Inventory or STEP

Run `pwd` and confirm that the terminal is at the repository root. Linux paths are case-sensitive. Check the filenames in Explorer and quote any source path containing spaces. Replace every article placeholder before running the new-assembly commands.

### The Viewer Is Blank or Slow

Read the terminal first. A mesh build or collision decomposition may still be running. Wait for geometry-loading messages before diagnosing a blank scene. If the process exited with an error, address that error rather than waiting indefinitely.

Use the URL printed by the current process, or reopen its forwarded port through VS Code's **Ports** panel. If the default port is occupied, stop your previous viewer or choose another port where supported. For the stage viewer:

```bash
uv run slac-stage-cad cad/DSG-NEW/reviews/assembly.inventory.yaml --port 7001
```

Do not terminate processes owned by someone else. Closing a browser tab does not release a viewer's port.

### A Part Is Missing or Moves Incorrectly

Compare the import with Solid Edge. Check whether the STEP contains faces for that component, whether selection rules omitted it, whether its stage roles match the catalog, and whether it belongs to the correct moving or static group. Correct the underlying model before running CoACD.

### The Review Rejects a New STEP

Do not overwrite the review hash manually. Use the revision workflow, compare identities and new occurrences, and approve the candidate selection. Matching part names alone does not establish that all repeated occurrences retain the same role.

### Archive Export Fails or Returns No Useful Motion

Check network access, PV spelling and archival availability, interval dates, timezone, and whether commands actually occurred. Ask the controls engineer assigned to the hutch. An installed Python package does not establish archive connectivity, and a nonzero record count does not prove coordinate calibration.

### Replay Looks Plausible but Disagrees with Hardware

Check command versus readback selection, units, positive direction, zero/home relationship, power-cycle history, manual-axis settings, missing tracks, and model revision compatibility. Remember that the trajectory is reconstructed from commands and speed assumptions, not measured.

### Collision Results Seem Unexpected

Inspect the highlighted parts, selected warning band, hull quality, and contact exclusions. Use CAD contact verification for suspected false positives. Confirm that required obstacles are represented and not omitted. Do not use a green display as a substitute for a complete review.

## Optional Portable Export

To create a shareable SDF package from a reviewed inventory:

```bash
uv run slac-compile-sdf cad/DSG-NEW/reviews/assembly.inventory.yaml
```

For a package with convex collision geometry, only after the earlier review checkpoints:

```bash
uv run slac-compile-sdf cad/DSG-NEW/reviews/assembly.inventory.yaml --with-collisions --collision-mode convex
```

Read the output paths printed by the tool. Follow the repository's [SDF-sharing guide](https://github.com/slaclab/Twin-Lab/blob/main/docs/sdf-sharing.md) for the package contents and MATLAB loader. A portable export is distinct from publishing the editable model and review inputs through GitHub.

## Review Record and Support

Record the drawing and export revision, physical configuration, review date, reviewer, operating limits, manual-axis settings, exclusions, unresolved geometry, collision findings, archive interval, command-map version, and coordinate-calibration assumptions. Keep this with the assembly's review documentation so others know what the simulation does and does not represent.

For repository permission requests, contact **[REPLACE WITH @MENTION: Koa Shen]** or **[REPLACE WITH @MENTION: Elon Goliger Mallimson]**. For PV identification and archive access, contact the controls engineer assigned to your hutch. Follow the assembly owner's and hutch's normal approval process for mechanical review and hardware operation.

---

## Publishing Notes for the Article Editor

This section is editorial guidance, not part of the published engineering procedure. Remove it before publishing.

1. Set the Confluence page title to the article title. If importing the top-level Markdown heading duplicates that title, remove the imported duplicate heading.
2. In SLAC Confluence 9.2.23, select **+ > Markup > Markdown**, paste the article body, and insert it. For a large draft, import sections in order if the dialog struggles with a single paste.
3. Replace the publishing-action paragraph near the introduction with **+ > Table of Contents**. Use real heading styles and test navigation in preview or the saved page. Markdown heading-anchor links did not work in the trial, so none are used here.
4. Replace each `[REPLACE WITH @MENTION: ...]` placeholder with an actual Confluence user mention. Search for that exact marker to find all occurrences.
5. Resolve the Solid Edge export-procedure marker. Review the introduction's financial-risk wording with the appropriate owner if a documented example or citation is needed.
6. Verify imported tables, code blocks, links, and command copying. This draft uses Markdown, not LaTeX or equation macros.
7. Commands containing `DSG-NEW`, `YOUR_...`, `EXACT_...`, or `REPLACE_WITH_...` are deliberate reader-editable templates. Keep their explanatory warnings; do not turn the fictitious YAML references into claims about a real assembly.
8. Validate the Windows installation path with a first-time user or IT before treating it as institutionally approved setup. Archive connectivity and physical calibration require the hutch-specific checks described above.
9. Review screenshots as an optional enhancement: WSL status indicator, Explorer folder structure, one-axis kinematic check, collision highlight, and replay controls. Do not include credentials or sensitive controls information in screenshots.