# SLAC Robotics Framework

Python-first starter framework for stage-stack kinematics and interference checks,
targeted at complex XCS-like spectrometer assemblies.

## Why This Exists

Many LCLS instruments have tightly packed motorized devices with mixed kinematics
(linear, rotary, gonio) in a constrained chamber envelope. This package gives a
fast iteration loop to:

1. Model stage motion and detect interference.
2. Evaluate redesign options to reduce collisions.
3. Build toward homing/path-planning workflows.
4. Prepare for ray-tracing and auto-alignment integration.

## Current Capabilities

- Stage primitives: linear, rotary, gonio.
- Ordered stage stacks with mount offsets.
- Conservative interference detection using transformed AABBs.
- Chamber envelope violation checks.
- Example 7-stack polycapillary-like spectrometer layout.

## Quick Start

### Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,cad]"
```

### Run Example

```bash
python -m slac_robotics.examples
```

### Run STEP Collision Demo

```bash
python -m slac_robotics.step_demo
```

### Run Drake Collision Demo

```bash
python -m slac_robotics.drake_example
```

Expected output:

```text
overlap_count: 1
separated_count: 0
```

### Run Tests

```bash
pytest -q
```

## WSL Notes (Solid Edge + Python)

If you are running in WSL while using Solid Edge on Windows:

1. Export STEP/Parasolid from Windows to a shared path, for example:
   - `/mnt/c/Users/<you>/cad_exports/` for direct access from WSL.
2. Keep simulation code and generated artifacts in Linux paths under your repo
   for better Python tooling performance.
3. Avoid very large mesh processing directly on `/mnt/c/...` when possible; copy
   large CAD-derived mesh files into the repo or another Linux filesystem path.
4. If you later use Drake binaries, confirm compatibility with your WSL distro
   and keep Python + Drake in the same virtual environment.

## Package Layout

- `src/slac_robotics/model.py`: joints, bodies, geometry, limits, stacks, filters.
- `src/slac_robotics/transforms.py`: rigid transform math.
- `src/slac_robotics/collision.py`: conservative interference checks.
- `src/slac_robotics/examples.py`: starter XCS-style 7-stack model and demo.
- `src/slac_robotics/step_io.py`: STEP-to-mesh import and mesh interference checks.
- `src/slac_robotics/step_demo.py`: runnable generated-STEP collision demo.

## STEP Workflow (Simple Start)

Supported import format right now: STEP (`.stp`, `.step`) only.
Parasolid (`.x_t`, `.x_b`) is not imported directly by the current Python
pipeline. In Solid Edge, export Parasolid assemblies as STEP AP242 (preferred)
or AP214 before running the tooling below.

1. Export each moving assembly as one STEP file from Solid Edge.
2. Place files in a known folder, for example `/mnt/c/Users/<you>/cad_exports/`.
3. Use `slac_robotics.step_io.load_step_mesh(...)` to load each file.
4. Run `slac_robotics.step_io.detect_step_interferences(...)` for pair checks.

This gives you a real mesh collision path today while you continue refining
joint frames and motion constraints in the kinematic model.

## Drake Status

This package does not use Drake yet. The current implementation is a pure-Python
broad-phase model that uses simple joint chains and transformed bounding boxes.
That keeps the first iteration easy to inspect while dimensions, coordinate
frames, collision filters, and operating states are still being established.

## Suggested Next Steps For XCS Polycap

1. Replace placeholder dimensions and offsets with CAD-derived values.
2. Add all stage travel limits and software guard bands.
3. Define representative operating poses and sweep trajectories.
4. Create a collision matrix to identify high-risk stage pairs.
5. Add feasibility checks for homing without encoders.

## CAD + Drake Integration Plan

1. Near-term: enter measured stack offsets, joint limits, body boxes, and
   collision filters.
2. Mid-term: import CAD-derived meshes and compare mesh collision results
   against the fast bounding-box screen.
3. Long-term: migrate the kinematic tree and planning to Drake's MultibodyPlant +
   SceneGraph when constraints and planning complexity require it.

## Notes On Accuracy

The current interference engine is conservative and intentionally simple. It is
best used as a fast screening tool, not a final clearance authority. For final
clearance decisions, use mesh collisions with measured assembly tolerances.
