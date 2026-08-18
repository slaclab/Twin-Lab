from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from twin_lab.epics import (
    MotorObservation,
    MotorPvMap,
    RecordedEpicsClient,
    require_fresh_observations,
    to_sdf_position,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def test_controls_value_converts_to_sdf_position() -> None:
    mapping = MotorPvMap(
        joint_name="detector::x",
        command_pv="DET:X:VAL",
        readback_pv="DET:X:RBV",
        units="mm",
        scale_to_sdf=0.001,
        offset_to_sdf=-0.2,
    )

    assert to_sdf_position(mapping, 125.0) == pytest.approx(-0.075)


def test_recorded_client_returns_latest_observation() -> None:
    mapping = MotorPvMap("stage::x", "X:VAL", "X:RBV")
    observation = MotorObservation("stage::x", NOW, readback=0.12, commanded=0.1)

    assert RecordedEpicsClient([observation]).observe(mapping) == observation


def test_fresh_observations_fail_closed_for_stale_or_missing_readback() -> None:
    mappings = {
        name: MotorPvMap(name, f"{name}:VAL", f"{name}:RBV")
        for name in ("fresh", "stale", "missing")
    }
    fresh = MotorObservation("fresh", NOW, readback=0.1)
    stale = MotorObservation("stale", NOW - timedelta(seconds=5), readback=0.2)
    missing = MotorObservation("missing", NOW, readback=None)

    with pytest.raises(ValueError, match="missing, stale"):
        require_fresh_observations(
            [fresh, stale, missing], mappings, max_age_s=1.0, now=NOW
        )


def test_fresh_observations_are_converted_to_sdf_coordinates() -> None:
    mapping = MotorPvMap("stage::x", "X:VAL", "X:RBV", scale_to_sdf=0.001)
    observation = MotorObservation("stage::x", NOW, readback=125.0)

    positions = require_fresh_observations(
        [observation], {"stage::x": mapping}, max_age_s=1.0, now=NOW
    )

    assert positions == {"stage::x": pytest.approx(0.125)}


def test_naive_observation_timestamp_is_rejected() -> None:
    observation = MotorObservation("stage::x", datetime(2026, 8, 18, 12), readback=0.1)

    with pytest.raises(ValueError, match="timezone"):
        observation.is_usable(max_age_s=1.0, now=NOW)