import pytest

pydrake = pytest.importorskip("pydrake")

from slac_robotics.drake_example import run_demo


def test_drake_demo_detects_overlap_then_separation() -> None:
    overlap_count, separated_count = run_demo()
    assert overlap_count > 0
    assert separated_count == 0
