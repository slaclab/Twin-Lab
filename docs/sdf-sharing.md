# SDF sharing and MATLAB handoff

The SDF compiler converts the reviewed stage scene into a portable rigid-body
tree. It does not modify or replace the fast STEP viewer.

## Build the package

```bash
slac-compile-sdf \
  cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml
```

Outputs:

```text
exports/DSG-000040389.43841-stage-stack.sdf-package/
  dsg_000040389_43841_stage_stack.sdf
  joint_metadata.csv
  load_in_matlab.m
  meshes/*.stl
  README.md
exports/DSG-000040389.43841-stage-stack.sdf-package.zip
```

All mesh paths inside the SDF are relative. Share the ZIP rather than an isolated
SDF file.

## MATLAB Robotics System Toolbox

Unzip the package, make its directory current in MATLAB, and run:

```matlab
load_in_matlab
```

Equivalent direct import:

```matlab
robot = importrobot("dsg_000040389_43841_stage_stack.sdf", ...
                    "DataFormat", "row");
show(robot, "Visuals", "on", "Collisions", "off");
```

`joint_metadata.csv` maps SDF joint names to stack names, STEP stage references,
axes, limits, and logical home offsets. SDF coordinates are zero at the reviewed
CAD pose. For `A046` and `A051`, the logical display angle is the SDF coordinate
plus 180 degrees.

## Drake validation

Load the exported SDF directly:

```bash
python -m slac_robotics.scene \
  exports/DSG-000040389.43841-stage-stack.sdf-package/*.sdf
```

The package has a welded assembly base and 21 scalar joint positions. The normal
export contains STL visual geometry but no collision geometry, so it remains
fast and works in both Drake and MATLAB.

## Collision export status

`--with-collisions` exists for development experiments, but it is not the normal
sharing path. Drake convex-hulls OBJ collision meshes. A whole rigid group can
contain several separated or concave CAD parts, so one hull creates large false
interferences. Before collision results are useful, meshes must be separated into
reviewed per-part convex pieces and expected mechanical interfaces must be
filtered.
