# STEP Constraints Workflow (3 Linear Motors)

This walkthrough is for assembly STEP files where motor constraints are not
encoded in the CAD export.

## 1) Generate the template

From repo root:

```bash
python -m slac_robotics.constraints_wizard step_files/DSG-000046520.stp
```

This writes:

- `step_files/DSG-000046520.constraints.json`

## 2) Fill base components

In `base_components`, add the names that should remain fixed (chamber base,
hard mounts, static adapters).

Tip: start conservative. Anything uncertain can stay out until joint groups are
 clear.

## 3) Fill the 3 linear motor joints

In each `joints[i]` block:

- Set `name` to your axis naming (for example `motor_x`, `motor_y`, `motor_z`).
- Keep `type` as `linear`.
- Set `axis_xyz` in assembly frame.
- Set `limits_m` from stage travel specs.
- Set `home_m` to your operational home.
- Add all rigidly-connected parts that move with that axis to `components`.

Important: each moving part should belong to exactly one moving joint.

## 4) Practical filtering strategy

Your STEP contains many fasteners and hardware. Start by assigning only major
sub-assemblies (for example `DSG-*`, `REF-*`, `LIB-*` names). Add screws later
if needed.

## 5) Solid Edge-first method (specific)

Use Solid Edge for all kinematic interpretation, then copy results into JSON.

### 5.1 Open and prepare the assembly

1. Open the native assembly in Solid Edge (not the exported STEP).
2. In Pathfinder, expand to the level where each motor-driven carriage/stage is visible.
3. Create three temporary selection sets (or a simple text list) named for each motor axis.

### 5.2 Identify each moving group

For each of the 3 linear motors:

1. Select the carriage (or primary moving body) driven by that motor.
2. Use Show/Hide isolate to verify which components move rigidly with it.
3. Add those components to that motor's selection set.
4. Exclude obvious fixed structure (base plates, chamber mounts, static adapters).

Result: three clean moving groups and one implicit fixed group.

### 5.3 Determine axis direction and sign

For each motor axis:

1. Read the axis direction from the stage orientation in assembly coordinates.
2. Jog or evaluate motion direction in Solid Edge so you know what positive travel means.
3. Map that direction into `axis_xyz` as a unit-like vector:
   - X axis motion: `[1, 0, 0]` or `[-1, 0, 0]`
   - Y axis motion: `[0, 1, 0]` or `[0, -1, 0]`
   - Z axis motion: `[0, 0, 1]` or `[0, 0, -1]`

### 5.4 Capture travel limits and home

1. Pull min/max travel from your stage specs or assembly definition.
2. Convert to meters before entering JSON.
3. Set `home_m` to the operational reference you actually use at beamline startup.

### 5.5 Map Solid Edge names to STEP names

STEP export can rename or duplicate part labels. Use this mapping process:

1. In Solid Edge, export a part list for each motor selection set.
2. In `available_components`, find the matching names.
3. If duplicates exist (for example `name#1`, `name#2`), assign consistently using count/order.
4. Put final mapped names into each joint's `components` list.

### 5.6 Fill fixed components

Add known static structure to `base_components`.

Tip: start with major fixed structure only. You can add hardware (fasteners,
washers) after first validation if needed.

## 6) Suggested next repo step

After this file is filled, the next useful code step is to add a validator that:

1. Confirms every listed component exists in `available_components`.
2. Confirms no component is assigned to multiple joints.
3. Reports unassigned major components.
