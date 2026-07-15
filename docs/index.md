# Documentation

The active architecture is:

1. Open Cascade extracts immutable CAD occurrence facts from STEP.
2. A small kinematics review file records the mechanical interpretation.
3. Reusable mechanisms are represented as SDF.
4. Drake Model Directives compose mechanisms into the full instrument.
5. Drake SceneGraph evaluates signed clearance and Meshcat provides joint sliders.

See [constraints-workflow.md](constraints-workflow.md) for the CAD-to-SDF process
and the repository [README](../README.md) for runnable commands.

Active modules:

- `slac_robotics.constraints_wizard`
- `slac_robotics.scene`
