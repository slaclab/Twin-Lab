# SLAC Robotics Framework Documentation

Welcome to the SLAC Robotics Framework documentation.

This project provides a practical path for modeling kinematics and
interference in tightly packed stage-stack systems such as XCS spectrometers.

## Getting Started

### Installation

```bash
pip install -e .
```

### Development Setup

```bash
pip install -e ".[dev]"
```

## Usage

Build and evaluate the starter polycapillary-style model:

```bash
python -m slac_robotics.examples
```

Run the STEP mesh-collision demo:

```bash
python -m slac_robotics.step_demo
```

Run the Drake collision demo:

```bash
python -m slac_robotics.drake_example
```

Run tests:

```bash
pytest -q
```

Core modules:

- `slac_robotics.model`
- `slac_robotics.transforms`
- `slac_robotics.collision`
- `slac_robotics.examples`
- `slac_robotics.step_io`
- `slac_robotics.step_demo`
- `slac_robotics.drake_example`

Recommended workflow:

1. Encode each stack and axis limits from engineering docs.
2. Calibrate geometry from CAD exports.
3. Check interference for nominal and worst-case states.
4. Add trajectory sweeps for planned homing and maintenance moves.

Constraints walkthrough:

- See `docs/constraints-workflow.md` for assembly STEP joint assignment steps.

## Contributing

Contributions are welcome. Please follow the coding standards and add tests for new features.
