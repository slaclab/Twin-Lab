"""Runnable STEP collision demo.

Usage:
    python -m slac_robotics.step_demo
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Trsf, gp_Vec

from .step_io import detect_step_interferences


def _write_box_step(path: Path, *, size_xyz: tuple[float, float, float], offset_xyz: tuple[float, float, float]) -> None:
    shape = BRepPrimAPI_MakeBox(*size_xyz).Shape()
    if offset_xyz != (0.0, 0.0, 0.0):
        trsf = gp_Trsf()
        trsf.SetTranslation(gp_Vec(*offset_xyz))
        shape = BRepBuilderAPI_Transform(shape, trsf, True).Shape()

    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(str(path))
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to write STEP file: {path}")


def main() -> None:
    with TemporaryDirectory(prefix="slac_step_demo_") as tmpdir:
        tmp = Path(tmpdir)
        left = tmp / "left_box.step"
        right = tmp / "right_box.step"

        _write_box_step(left, size_xyz=(0.20, 0.20, 0.20), offset_xyz=(0.0, 0.0, 0.0))
        _write_box_step(right, size_xyz=(0.20, 0.20, 0.20), offset_xyz=(0.12, 0.0, 0.0))

        collisions = detect_step_interferences(
            [
                ("left_box", left),
                ("right_box", right),
            ]
        )

        if collisions:
            print("STEP mesh interference detected:")
            for report in collisions:
                print(f"- {report.a} vs {report.b}")
        else:
            print("No STEP mesh interference detected.")


if __name__ == "__main__":
    main()
