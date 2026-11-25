# Published Collision Geometry

## Meeting Launcher on This Workstation

Open the original `Twin-Lab` folder in VS Code. In **Run and Debug**, select
**Meeting: verified baseline (offline)** and click the green Run button. The
default build task, **Meeting: start verified baseline**, runs the same model
without the debugger and is also available with **Ctrl+Shift+B**.

The baseline Run configuration and default task use `../Twin-Lab-review-old`,
its own Python environment, and the exact complete baseline bundle. They verify
the saved data offline first and never run CAD ingestion, tessellation, or hull
generation. The browser address is `http://localhost:7000`.

Allow roughly 60-90 seconds for Drake to load the saved geometry. The canvas can
be blank until the terminal reports that collision geometry is loaded. This is
model loading, not rebuilding the CAD cache. Use **Isometric view** to frame the
assembly if the initial camera is too far away. The model exposes 31 manual
joints, collision detection, and CAD verification.

The recovered new revision is a separate Run choice:
**Meeting: new CAD 2026-11-03 (offline)**. It uses `../Twin-Lab-review-new`,
its own saved bundle and interpreter, and port `http://localhost:7001`.
Its task is **Meeting: start verified new CAD**. Both models retain 31 DOFs;
the new revision keeps the newly exported camera stages fixed, as recorded in
its reviewed inventory. The baseline remains the default presentation fallback.

Each viewer requires several GiB of RAM. Load them sequentially, check available
memory before keeping both open, and stop the new viewer first if the machine
becomes memory constrained. Loading saved geometry is still required after a
restart, but no CoACD or STEP tessellation runs from either meeting launcher.

Leave this baseline separate from `../Twin-Lab-review-new` on branch
`cad/43841-next`. Do not replace its STEP, bundle, interpreter, or worktree before
the meeting. If a browser tab is closed, reopen the URL; if VS Code or WSL
restarts, use the Run button again. If port 7000 is occupied by a working baseline,
reuse that browser session instead of starting another copy. To restart
deliberately, stop the existing viewer first.

These workstation launchers require the two worktrees and environments prepared
here. Other machines should follow the published-bundle setup below rather than
assuming the sibling directory already exists.

Collision geometry is a versioned build artifact, not a disposable startup cache.
A small `*.artifacts.json` reference next to each reviewed inventory selects an
exact bundle. Commit that reference with its CAD review. Branch names are not
cache keys: branches with identical references can use the same published bytes,
and a new build never replaces the previous revision.

## Complete Simulation Revisions

A simulation is more than a STEP file or a directory of hulls. New v2 bundles
contain the exact STEP bytes, stage catalog, reviewed source inventory, assembly
to stage-instance mapping, resolved motion chains, home/limit overrides, compiled
joint table, and generated SDF/meshes. The reviewed inventory is necessary because
catalog entries describe reusable hardware while assembly-specific chains,
directions, attachments, and home positions describe how that hardware is used.

`review/simulation.json` links these components by SHA-256 and records the DOF
count and full compiled joint definitions. Loading validates the saved STEP,
catalog, source inventory, and joint table. The viewer restores DOFs from the
saved compiled model; it does not infer them again from whatever catalog happens
to be in the current branch. Drake still needs to load its plant and geometry.

Each catalog bundle binding exposes a `simulation` object with a simulation ID
that incorporates STEP, stage-catalog, reviewed-inventory, and bundle identities.
It also lists saved metadata paths and the DOF count. One STEP can therefore have
multiple explicitly distinguished reviewed simulations. A hash mismatch fails
closed instead of silently adopting new stage definitions.

Legacy v1 bundles remain readable as compiled-only snapshots. Enriching a legacy
baseline uses a new archive and reference, not an in-place rewrite. The catalog
marks new snapshots `complete` and older registrations `legacy_compiled_only`.
If a CAD revision has several bundles, select the intended `--bundle ID` from
catalog JSON; do not infer it from filesystem ordering or a "latest" filename.

For reproducible execution, retain the framework commit and dependency lockfile
as well. The data bundle isolates assembly state; Git and each worktree's own
environment isolate the software that interprets it.

## Run a Published Review

For a cataloged model, no file discovery is necessary:

```bash
uv run slac-cad-catalog list
uv run slac-cad-catalog list --json
uv run slac-cad-catalog show dsg-000043841-948f9e9f8820
uv run slac-collision --revision dsg-000043841-948f9e9f8820 --offline --port 7000
```

Selectors may use a unique hash prefix; ambiguous selectors are rejected. The
JSON form contains the full revision ID, assembly identity and display name,
timestamps, original filename, saved STEP path and hash, parent revision, bundle
IDs, collision modes, verified input hashes, archive URLs, and binding dates.
Agents should query this metadata rather than infer relationships from filenames.

Each revision lives under `cad/revisions/<revision-id>/`. Its `source.stp` is a
managed read-only copy; `revision.json` records its provenance and `bundles/`
contains its verified artifact associations. Commit these records and the STEP
using the repository's existing Git LFS rule. Local archives and installed
bundles remain ignored. Existing revisions are not removed when new ones arrive.

`uploaded_at` means the UTC time of import into this repository, not the CAD
authoring time. For a legacy baseline, the original upload time is unknown:
`uploaded_at` is null, `timestamp_basis` is `registered_existing`, and
`ingested_at` records when this catalog registered it. File modification times
are never passed off as upload provenance.

New build/capture commands automatically create the catalog association and embed
the CAD revision metadata inside the bundle manifest. Registering a legacy bundle
adds metadata to its catalog/reference without changing that archive's bytes.
A STEP may have several reviewed collision configurations; each binding names an
exact bundle, and the viewer requires `--bundle ID` if selection is ambiguous.

After the normal repository setup:

```bash
inventory=cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
uv run slac-collision "$inventory"
```

The viewer checks the reference against the CAD review, downloads a missing
bundle, verifies every file, and loads the saved SDF and meshes. It does not
tessellate STEP, run CoACD, or rewrite an installed bundle. Drake scene
loading still takes time; publishing removes geometry generation, not loading.

A checkout with Git LFS pointer files can run a published review without
downloading the STEP: its LFS object ID is checked against the pinned source
hash. Explicit CAD builds still require `git lfs pull` to materialize the STEP.

The reference for this example is
`cad/DSG-000040389/reviews/43841-stage-stack.artifacts.json`. If no reference has
been published for a review, startup stops with capture/build instructions;
there is no silent fallback to computation.

Prepare for a meeting while online, then verify availability without networking:

```bash
uv run slac-artifacts fetch "$inventory"
uv run slac-artifacts verify "$inventory"
uv run slac-collision "$inventory" --offline --port 7000
```

`verify` is an offline integrity and portability preflight. It is not a clearance
certification: review the actual poses and contacts in the viewer.

## What Is Preserved

Each bundle contains:

- The source STEP, exact stage catalog, and reviewed assembly/DOF snapshot (v2).
- The collision-enabled SDF, joint metadata, and portable mesh package.
- Saved tessellations, including the meshes used by beam and contact checks.
- Active convex hulls and their source manifests, with bundle-relative paths.
- Existing hull audits, when available, and reviewed labels and beam metadata.
- Generator versions, generator source hashes, and tessellation settings when
  recorded by the original build.

The reference records the bundle identity, archive SHA-256, download URL,
collision mode, and content hashes of the inventory, STEP, CAD manifest, catalog,
selection review, and supplemental inputs. File modification times and checkout
paths do not select a bundle. Unrelated feature-code changes do not force a
geometry rebuild. An incompatible runtime format must use a new schema version.

Archives are reproducible for identical bundle contents. Installation verifies
the archive and its complete file manifest in a temporary directory, then
atomically installs `.cache/twin_lab/artifacts/<bundle-id>/`. Installed files are
read-only. Path traversal, links, missing files, and checksum mismatches are
rejected. Corrupt installed data is reported, not silently rebuilt or overwritten.

Keep the published archive available independently of local caches. Installed
files and local archives remain ignored by Git; the committed reference is what
connects source history to the saved geometry.

## Migrate a Validated Existing Cache

Capture avoids tessellation and decomposition. The existing SDF build stamp must
match its scene. New scenes also carry content fingerprints that must match the
review. Older scenes lack those fingerprints, so use `--accept-legacy` only after
manually validating that the working cache represents the intended review:

```bash
uv run slac-artifacts capture "$inventory" \
  --archive exports/artifacts/43841-baseline.tar.gz \
  --accept-legacy
```

Only decompositions referenced by the scene are captured. Obsolete working-cache
entries are excluded; active source checksums are still checked. For nonstandard
locations, capture accepts `--scene`, `--package-dir`, and `--decomposition-dir`.

Capture writes the default sidecar reference after successful installation.
Initially its URL is local to this machine. Do not commit a local file URL as a
shared demo reference. Publish first, as described below.

To keep a migration reference entirely local until publishing, add
`--reference .cache/twin_lab/43841-baseline.artifacts.json`. Pass that same
`--reference` to artifact commands and `--artifact-ref` to the collision viewer.

## Revise CAD Intentionally

Download a replacement STEP under a new filename anywhere accessible to the
workspace, such as a Downloads directory. Do not copy it over the baseline's
`source.stp`. Ingest it without changing any existing CAD or cache:

```bash
uv run slac-cad-catalog ingest /path/to/new-revision.step \
  --assembly DSG-000043841 --name "43841 stage stack (DSG-000040389)" \
  --parent dsg-000043841-948f9e9f8820
```

The command copies the file into a new content-identified revision directory,
timestamps the import, records its parent, and returns all metadata as JSON.
Re-importing identical bytes reuses the same record and original ingestion time.
The new revision is `awaiting_review` and cannot accidentally launch with the
old revision's cache.

Give the returned revision selector to the reviewing agent. Prepare a separate
manifest and inventory for that saved STEP under its revision directory; remap
and review occurrences, selection rules, motion chains, and attachments there.
Do not run the fixed-path 43841 replacement command in the baseline checkout.
Then build using the new revision's inventory path. Build/capture automatically
registers its successful bundle and changes the derived status to `cached`.
Assembly identity in the inventory must match the ingestion assembly identity.

Use a development worktree so the presentation checkout, environment, CAD, and
artifact reference remain unchanged. Import and review the new STEP there. The
existing `slac-refresh-43841` workflow remains available for the reviewed 43841
assembly; resolve its occurrence-remapping and static-selection warnings before
building geometry.

Build a new artifact explicitly:

```bash
uv run slac-artifacts build "$inventory" \
  --archive exports/artifacts/43841-revision-two.tar.gz \
  --workers 2
```

This command uses a new isolated scratch workspace for tessellation, convex
decomposition, and SDF compilation. It never writes into an installed bundle or
the older authoring caches. It checks for input changes during the build and
updates the reference only after successful capture and installation. Existing
archive filenames are never overwritten. Choose a new name for each build.

Inspect the new model, verify its contacts, publish the archive, and commit its
reference with the reviewed CAD changes. Changing CAD or review inputs without
updating the reference causes a clear startup error, not an expensive rebuild.
Changing slider positions never rebuilds geometry.

The older `slac-stage-cad`, compiler, hull audit, and decomposition tools remain
authoring tools using working caches. Their outputs are not presentation
artifacts until captured. Collision-viewer `--rebuild`, `--package-dir`, and
`--decomposition-workers` no longer trigger implicit generation; use the artifact
commands instead.

## Publish to GitHub Releases

Create an appropriate release in the repository that will own the artifacts,
using GitHub or `gh release create`. Then upload to that existing release:

```bash
uv run slac-artifacts publish "$inventory" \
  --archive exports/artifacts/43841-baseline.tar.gz \
  --repo OWNER/REPOSITORY --tag geometry-baseline
```

Publishing requires an authenticated GitHub CLI with write access. It checks the
archive against the reference, uploads without `--clobber`, then atomically
updates the reference to the HTTPS release-asset URL. Failed uploads leave the
reference unchanged. Commit the updated sidecar with the matching review after
publishing, and retain the release asset for as long as any revision uses it.

The downloader supports public HTTPS assets and local file URLs. Private release
assets need a separate authenticated download, for example `gh release download`;
use a local reference copy whose `url` points to that downloaded archive. Never
put access tokens in committed references. Private automatic authenticated asset
retrieval is not provided by this workflow.

For other object stores, upload the unchanged archive and set its HTTPS URL using
the build/capture `--url` option. Make the object immutable and accessible to the
intended audience. A changed object fails checksum verification even if its URL
is reused. Respect the storage provider's asset-size and retention limits.

## Branch and Merge Workflow

Do not use mutable branch names as simulation versions. Use tagged, verified
baseline commits and immutable catalog/bundle identities. Keep `main` as the
reviewed integration branch, not the workspace where replacement CAD is tried.

1. Finish this framework feature branch, publish the complete baseline artifact,
  and commit its matching catalog/reference metadata. Submit a PR to `main`.
2. After tests and review, merge that framework PR once. Tag the integrated
  baseline, for example `review/43841-baseline`; retain its release artifacts.
3. Use a detached worktree at that tag for the old-CAD presentation. It needs no
  long-lived `old-cad` development branch.
4. Create `cad/43841-next` and a separate worktree from the same tagged framework
  commit. Ingest and review the new CAD there, with an independent environment.
5. Test both saved simulations offline and side by side. Only after design review
  should a second PR integrate the new catalog revision. Retain the old CAD,
  bundle binding, and presentation tag when merging the new revision.

Example commands after the framework PR has been integrated and the baseline
artifacts published:

```bash
git tag review/43841-baseline main
git worktree add --detach ../Twin-Lab-review-old review/43841-baseline
git worktree add -b cad/43841-next ../Twin-Lab-review-new review/43841-baseline
code -n ../Twin-Lab-review-old
code -n ../Twin-Lab-review-new
```

Run the normal environment setup in each worktree, then fetch/verify its selected
bundle. Worktrees do not copy ignored virtual environments or installed caches.
No branch switch or writable shared cache is needed during a live presentation.
Keep both reviews on a compatible framework baseline when comparing CAD; make
framework changes on a separate feature branch rather than conflating them with
geometry changes. Do not move an existing presentation tag to a newer commit.

## Compare Two Revisions

After both are cached, prove their saved sources and artifact files remain
available and valid without networking:

```bash
uv run slac-cad-catalog compare OLD_REVISION NEW_REVISION
uv run slac-collision --revision OLD_REVISION --offline --port 7000
uv run slac-collision --revision NEW_REVISION --offline --port 7001
```

`compare` verifies the saved STEP hashes, exact bundle associations, and both
installed bundles, then emits a JSON report containing both revisions and
whether their STEP hashes differ. It does not merely check that two directories
exist. This is the acceptance check for a real two-CAD demonstration.

Keep two Git worktrees and two environments. Each worktree has an independent
artifact store and a committed reference to its selected CAD revision. In the
old revision's terminal:

```bash
uv run slac-collision "$inventory" --offline --port 7000
```

In the new revision's terminal:

```bash
uv run slac-collision "$inventory" --offline --port 7001
```

Forward both ports in VS Code when working remotely. Inputs are independent;
corresponding joint poses must currently be set manually. Preload both models
before the meeting and check available memory. Do not switch a running review's
checkout to another branch or share a writable authoring cache between worktrees.

## Ingest Another Assembly

The artifact commands take an inventory path; they are not tied to drawing
43841. Create the new assembly's STEP manifest, stage inventory, reviewed
kinematics, attachment selections, and collision exceptions using the existing
CAD review tools. Validate that review, then use the same `build`, `verify`, and
`publish` commands with its inventory path. Keep a separate sidecar per reviewed
setup. The assembly-specific 43841 refresh script is not a generic importer.

## Recovery

Catalog listing reports a damaged entry as `invalid` while keeping healthy
revisions discoverable. Catalog-based launch verifies both the managed STEP (or
matching LFS pointer) and its selected bundle. Reassigning a reference to another
STEP fails verification. There is no automatic deletion or cleanup operation.

A failed download or build does not update the selected reference or replace an
installed revision. Correct a stale reference by selecting the intended Git
revision, or intentionally build and publish a new bundle after reviewing the
changed inputs.

If local files were deliberately modified despite read-only permissions, keep
the diagnostic and restore the exact bundle into a clean worktree using its
committed reference. Do not patch installed geometry or change checksums to hide
corruption. Other worktrees and published artifacts remain independent.